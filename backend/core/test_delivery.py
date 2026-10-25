import socket
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .delivery import UnsafeDestination, deliver_batch, post_event, resolve_public
from .events import ingest_event
from .models import AuditLog, Bot, BotGrant, DeliveryAttempt, EventOutbox, User
from .replay import replay_delivery
from .subscriptions import decrypt_callback_secret, set_subscription

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('change', [{'is_active': False}, {'revision': 2}, {'scopes': []}])
def test_attempt_history_rechecks_live_grant(change):
    grant, row = queued()
    DeliveryAttempt.objects.create(outbox=row, attempt_number=1)
    client = APIClient()
    client.force_login(grant.user)
    url = f'/api/v1/deliveries/{row.pk}/attempts/'
    assert client.get(url).status_code == 200
    BotGrant.objects.filter(pk=grant.pk).update(**change)
    assert client.get(url).status_code == 404


def queued(subscribe=True):
    bot = Bot.objects.create(name='push', app_id='push', encrypted_secret='unused')
    user = User.objects.create_user('push')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=['events:read'])
    if subscribe:
        set_subscription(grant.pk, 'https://example.com/events')
    ingest_event(bot, {'op': 0, 'id': 'event1', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    return grant, EventOutbox.objects.get()


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '224.0.0.1', '::ffff:8.8.8.8'])
def test_private_dns_rejected(address):
    with patch('core.delivery.socket.getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]):
        with pytest.raises(UnsafeDestination):
            resolve_public('example.com')


def test_mixed_dns_rejected():
    records = [(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]
    with patch('core.delivery.socket.getaddrinfo', return_value=records):
        with pytest.raises(UnsafeDestination):
            resolve_public('example.com')


def test_https_pinned_and_redirect_not_followed():
    with patch('core.delivery.resolve_public', return_value='8.8.8.8'), patch('core.delivery.PinnedHTTPSConnection') as cls:
        conn = cls.return_value
        conn.getresponse.return_value.status = 302
        assert not post_event('https://example.com/path?q=1', {'id': '1'}, 17, 'secret')
        cls.assert_called_once_with('example.com', '8.8.8.8')
        assert conn.request.call_count == 1
        headers = conn.request.call_args.kwargs['headers']
        assert headers['X-QQ-Proxy-Delivery-ID'] == '17'
        body = conn.request.call_args.kwargs['body']
        expected = hmac.new(
            b'secret', headers['X-QQ-Proxy-Timestamp'].encode() + b'.17.' + body, hashlib.sha256,
        ).hexdigest()
        assert headers['X-QQ-Proxy-Signature'] == 'v1=' + expected
        assert json.loads(body) == {'id': '1'}
        conn.close.assert_called_once()


def test_callback_signature_binds_timestamp_delivery_id_and_body():
    with patch('core.delivery.resolve_public', return_value='8.8.8.8'), patch('core.delivery.PinnedHTTPSConnection') as cls:
        cls.return_value.getresponse.return_value.status = 204
        result = post_event('https://example.com/hook', {'a': 1}, 'delivery-9', 'callback-secret')
        assert bool(result) and result.status == 204
        headers = cls.return_value.request.call_args.kwargs['headers']
        body = cls.return_value.request.call_args.kwargs['body']
        assert abs(int(headers['X-QQ-Proxy-Timestamp']) - int(time.time())) <= 2
        message = headers['X-QQ-Proxy-Timestamp'].encode() + b'.delivery-9.' + body
        expected = hmac.new(b'callback-secret', message, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(headers['X-QQ-Proxy-Signature'], 'v1=' + expected)


def test_delivery_and_dedup():
    _, row = queued()
    secret = decrypt_callback_secret(row.grant.httpsubscription)
    with patch('core.delivery.post_event', return_value=True) as send:
        assert deliver_batch()['delivered'] == 1
        assert deliver_batch()['claimed'] == 0
        send.assert_called_once_with('https://example.com/events', row.event.payload, row.pk, secret)
    row.refresh_from_db()
    assert row.state == 'delivered'
    assert DeliveryAttempt.objects.get(outbox=row).state == DeliveryAttempt.State.DELIVERED


def test_network_failure_retries_without_immediate_loop():
    _, row = queued()
    with patch('core.delivery.post_event', side_effect=TimeoutError):
        assert deliver_batch()['retry_or_failed'] == 1
    row.refresh_from_db()
    assert row.state == 'pending' and row.attempts == 1 and row.available_at
    assert DeliveryAttempt.objects.get(outbox=row).error_code == 'network_error'


def test_http_failure_is_recorded_without_response_body():
    _, row = queued()
    with patch('core.delivery.post_event', return_value=type('Result', (), {'__bool__': lambda self: False, 'status': 503})()):
        assert deliver_batch()['retry_or_failed'] == 1
    attempt = DeliveryAttempt.objects.get(outbox=row)
    assert attempt.state == DeliveryAttempt.State.RETRY
    assert attempt.http_status == 503 and attempt.error_code == 'http_status'


def test_unsubscribed_not_claimed():
    _, row = queued(False)
    with patch('core.delivery.post_event') as send:
        assert deliver_batch()['claimed'] == 0
        send.assert_not_called()
    row.refresh_from_db()
    assert row.attempts == 0


def test_old_subscription_not_revived_by_new_grant():
    grant, row = queued()
    grant.revision += 1
    grant.save()
    with patch('core.delivery.post_event') as send:
        assert deliver_batch()['claimed'] == 0
        send.assert_not_called()


def test_revoked_grant_not_sent():
    grant, row = queued()
    grant.is_active = False
    grant.save()
    with patch('core.delivery.post_event') as send:
        assert deliver_batch()['claimed'] == 0
        send.assert_not_called()
    row.refresh_from_db()
    assert row.state == 'cancelled'


def test_delivery_management_isolation():
    from rest_framework.test import APIClient
    grant, row = queued()
    client = APIClient()
    client.force_authenticate(grant.user)
    assert client.get('/api/v1/deliveries/').json()['deliveries'][0]['id'] == row.pk
    other = User.objects.create_user('unrelated')
    client.force_authenticate(other)
    assert client.get('/api/v1/deliveries/').json()['deliveries'] == []


def test_delivery_attempt_history_isolated():
    grant, row = queued()
    with patch('core.delivery.post_event', return_value=True):
        deliver_batch()
    client = APIClient()
    client.force_authenticate(grant.user)
    response = client.get(f'/api/v1/deliveries/{row.pk}/attempts/')
    assert response.status_code == 200 and len(response.json()) == 1
    other = User.objects.create_user('delivery-history-other')
    client.force_authenticate(other)
    assert client.get(f'/api/v1/deliveries/{row.pk}/attempts/').status_code == 404


def test_failed_delivery_can_be_replayed_with_new_generation():
    grant, row = queued()
    with patch('core.delivery.post_event', return_value=False):
        assert deliver_batch()['retry_or_failed'] == 1
    row.refresh_from_db()
    row.attempts = 5
    row.save(update_fields=['attempts'])
    # Drive a failure through the ordinary worker until the terminal state.
    with patch('core.delivery.post_event', return_value=False):
        for _ in range(4):
            EventOutbox.objects.filter(pk=row.pk).update(available_at=None, state='pending')
            deliver_batch()
    row.refresh_from_db()
    assert row.state == 'failed'
    response = APIClient()
    response.force_authenticate(grant.user)
    replay = response.post(f'/api/v1/deliveries/{row.pk}/replay/', {}, format='json')
    assert replay.status_code == 202
    assert replay.json()['attempt_generation'] == 2
    assert 'more than once' in replay.json()['warning']
    row.refresh_from_db()
    assert row.state == 'pending' and row.attempts == 0 and row.attempt_generation == 2
    assert AuditLog.objects.filter(action='delivery.replay', target=str(row.pk)).exists()


def test_replay_rechecks_current_authorization_and_subscription():
    grant, row = queued()
    EventOutbox.objects.filter(pk=row.pk).update(state='failed', attempts=5)
    grant.revision += 1
    grant.save()
    with pytest.raises(ValueError, match='not currently replayable'):
        replay_delivery(row.pk, grant.user)
    row.refresh_from_db()
    assert row.state == 'failed'


def test_websocket_page_checks_live_database_authorization():
    from rest_framework.exceptions import PermissionDenied
    from .services import issue_key
    from .websocket import read_page
    grant, row = queued()
    _, token = issue_key(grant.user, grant.bot, 'ws', ['events:read'])
    assert read_page(token, 0)[0]['cursor'] == str(row.pk)
    assert read_page(token, row.pk) == []
    grant.revision += 1
    grant.save()
    with pytest.raises(PermissionDenied):
        read_page(token, 0)
