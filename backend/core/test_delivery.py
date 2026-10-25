import socket
from unittest.mock import patch

import pytest

from .delivery import UnsafeDestination, deliver_batch, post_event, resolve_public
from .events import ingest_event
from .models import Bot, BotGrant, EventOutbox, User
from .subscriptions import set_subscription

pytestmark = pytest.mark.django_db


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
        assert not post_event('https://example.com/path?q=1', {'id': '1'}, 17)
        cls.assert_called_once_with('example.com', '8.8.8.8')
        assert conn.request.call_count == 1
        assert conn.request.call_args.kwargs['headers']['X-QQ-Proxy-Delivery-ID'] == '17'
        conn.close.assert_called_once()


def test_delivery_and_dedup():
    _, row = queued()
    with patch('core.delivery.post_event', return_value=True) as send:
        assert deliver_batch()['delivered'] == 1
        assert deliver_batch()['claimed'] == 0
        send.assert_called_once_with('https://example.com/events', row.event.payload, row.pk)
    row.refresh_from_db()
    assert row.state == 'delivered'


def test_network_failure_retries_without_immediate_loop():
    _, row = queued()
    with patch('core.delivery.post_event', side_effect=TimeoutError):
        assert deliver_batch()['retry_or_failed'] == 1
    row.refresh_from_db()
    assert row.state == 'pending' and row.attempts == 1 and row.available_at


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
    client.force_authenticate(grant.user)
    grant.revision += 1
    grant.save()
    assert client.get('/api/v1/deliveries/').json()['deliveries'] == []


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