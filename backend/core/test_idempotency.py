from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Bot, BotGrant, IdempotentSend, User
from .official import OfficialCredentialError
from .services import issue_key
from .idempotency import SendConflict, reserve_send

pytestmark = pytest.mark.django_db
PATH = '/qq/v2/users/example/messages'


@pytest.fixture
def sender():
    user = User.objects.create_user('idempotent-user')
    bot = Bot.objects.create(name='bot', app_id='idem', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=['messages:send'])
    key, token = issue_key(user, bot, 'send', ['messages:send'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return client, key


def send(client, body=b'{"content":"hello"}', identifier='test-send'):
    return client.post(PATH, body, content_type='application/json', HTTP_IDEMPOTENCY_KEY=identifier)


def test_repeated_send_preserves_response_without_resending(sender):
    client, key = sender
    with patch('core.views.send_message', return_value=(202, b'{ "id":"original" }', {'X-Tps-trace-ID': 'trace'})) as upstream:
        first = send(client)
        second = send(client)
    assert first.status_code == second.status_code == 202
    assert first.content == second.content
    assert second['Idempotency-Replayed'] == 'true'
    upstream.assert_called_once()
    record = IdempotentSend.objects.get()
    assert 'original' not in record.encrypted_result
    # Rotating the transport key must not bypass the user's Bot deduplication domain.
    _, token = issue_key(key.user, key.bot, 'second', ['messages:send'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.views.send_message') as upstream:
        assert send(client).status_code == 202
        upstream.assert_not_called()


def test_different_body_conflicts_and_revocation_precedes_cache(sender):
    client, key = sender
    with patch('core.views.send_message', return_value=(200, b'{}', {})):
        assert send(client).status_code == 200
    with patch('core.views.send_message') as upstream:
        assert send(client, b'{"content":"different"}').status_code == 409
        key.revoked_at = timezone.now()
        key.save()
        assert send(client).status_code == 401
        upstream.assert_not_called()


def test_unknown_outcome_is_not_retried(sender):
    client, _ = sender
    with patch('core.views.send_message', side_effect=OfficialCredentialError) as upstream:
        assert send(client).status_code == 502
        response = send(client)
        assert response.status_code == 409
        assert response.json()['code'] == 'idempotency_outcome_unknown'
        upstream.assert_called_once()


def test_pending_and_expired_reservations_never_resend(sender):
    client, key = sender
    body = b'{"content":"hello"}'
    row, result = reserve_send(key, 'test-send', 'v2/users/example/messages', '', body)
    assert result is None
    with pytest.raises(SendConflict, match='idempotency_in_progress'):
        reserve_send(key, 'test-send', 'v2/users/example/messages', '', body)
    IdempotentSend.objects.filter(pk=row.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with patch('core.views.send_message') as upstream:
        assert send(client).json()['code'] == 'idempotency_expired'
        upstream.assert_not_called()