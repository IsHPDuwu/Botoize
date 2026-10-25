from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import Bot, BotGrant, User
from .services import issue_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def media_client():
    user = User.objects.create_user('media-user')
    bot = Bot.objects.create(name='media', app_id='media-app', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=['media:upload', 'messages:send'])
    _, token = issue_key(user, bot, 'media', ['media:upload'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return client, user, bot


@pytest.mark.parametrize('kind', ['users', 'groups'])
def test_media_preserves_official_payload_response_and_ttl(media_client, kind):
    client, _, _ = media_client
    body = b'{ "file_type":1, "url":"https://example.com/a.png", "srv_send_msg":false }'
    with patch('core.views.upload_media', return_value=(200, b'{"file_info":"opaque","ttl":300}', {'Content-Type': 'application/json', 'X-Tps-trace-ID': 'media-trace'})) as upstream:
        response = client.post(f'/qq/v2/{kind}/target/files?x=1', body, content_type='application/json')
    assert response.status_code == 200 and response.json()['ttl'] == 300
    assert response['X-Tps-trace-ID'] == 'media-trace'
    assert upstream.call_args.args[1:] == (f'v2/{kind}/target/files', body, 'x=1')


def test_upload_only_key_cannot_send_and_requires_explicit_side_effect(media_client):
    client, user, bot = media_client
    with patch('core.views.upload_media', return_value=(200, b'{}', {})) as upstream:
        assert client.post('/qq/v2/users/target/files', {'srv_send_msg': True}, format='json').status_code == 403
        assert client.post('/qq/v2/users/target/files', {'url': 'https://example.com'}, format='json').status_code == 400
        upstream.assert_not_called()
        _, token = issue_key(user, bot, 'send-media', ['media:upload', 'messages:send'])
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        assert client.post('/qq/v2/users/target/files', {'srv_send_msg': True}, format='json').status_code == 200


def test_upload_supports_idempotency_without_duplicate_side_effects(media_client):
    client, _, _ = media_client
    with patch('core.views.upload_media', return_value=(200, b'{}', {})) as upstream:
        for _ in range(2):
            assert client.post('/qq/v2/groups/target/files', {'srv_send_msg': False}, format='json', HTTP_IDEMPOTENCY_KEY='media-once').status_code == 200
        upstream.assert_called_once()