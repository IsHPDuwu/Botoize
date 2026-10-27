from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from .events import ingest_event
from .models import ApiCallAudit, Bot, BotGrant, EventOutbox, GatewaySession, HttpSubscription, User
from .services import issue_key
from .subscriptions import disable_subscription, set_subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def account():
    user = User.objects.create_user('console-user', password='test-password-123')
    bot = Bot.objects.create(name='依卡', app_id='console-bot', encrypted_secret='unused')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=['events:read', 'query:read'])
    client = APIClient()
    client.force_authenticate(user)
    return user, bot, grant, client


def test_multiple_callbacks_fanout_and_stream_dedup(account):
    user, bot, grant, client = account
    urls = ['https://example.com/first', 'https://example.com/second', 'https://example.com/third']
    for url in urls:
        response = client.post('/api/v1/subscriptions/', {'bot': bot.pk, 'url': url, 'is_active': True}, format='json')
        assert response.status_code == 201
    assert HttpSubscription.objects.filter(grant=grant).count() == 3
    _, created = ingest_event(bot, {'op': 0, 'id': 'fanout', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    assert created and EventOutbox.objects.count() == 3
    assert EventOutbox.objects.filter(is_stream=True).count() == 1
    from .delivery import deliver_batch
    with patch('core.delivery.post_event', return_value=True) as send:
        assert deliver_batch()['delivered'] == 3
        assert {call.args[0] for call in send.call_args_list} == set(urls)
    _, token = issue_key(user, bot, 'stream', ['events:read'])
    downstream = APIClient()
    downstream.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    result = downstream.get('/relay/v1/events/').json()
    assert len(result['events']) == 1
    ingest_event(bot, {'op': 0, 'id': 'fanout', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    assert EventOutbox.objects.count() == 3


def test_callbacks_retry_and_edit_independently(account):
    _, bot, grant, _ = account
    first = set_subscription(grant.pk, 'https://example.com/first', create=True)
    second = set_subscription(grant.pk, 'https://example.com/second', create=True)
    ingest_event(bot, {'op': 0, 'id': 'independent', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    from .delivery import deliver_batch
    with patch('core.delivery.post_event', side_effect=lambda url, *args: url.endswith('second')):
        result = deliver_batch()
    assert result['delivered'] == 1 and result['retry_or_failed'] == 1
    one = EventOutbox.objects.get(subscription=first)
    two = EventOutbox.objects.get(subscription=second)
    assert one.state == 'pending' and two.state == 'delivered'
    set_subscription(grant.pk, 'https://example.com/replacement', subscription_id=first.pk)
    one.refresh_from_db()
    two.refresh_from_db()
    assert one.state == 'cancelled' and two.state == 'delivered'
    assert first.revision == 1 and HttpSubscription.objects.get(pk=first.pk).revision == 2
    with patch('core.delivery.post_event') as send:
        assert deliver_batch()['claimed'] == 0
        send.assert_not_called()


def test_disabling_one_callback_keeps_others_and_future_events(account):
    _, bot, grant, _ = account
    first = set_subscription(grant.pk, 'https://example.com/first', create=True)
    second = set_subscription(grant.pk, 'https://example.com/second', create=True)
    ingest_event(bot, {'op': 0, 'id': 'before-disable', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    disable_subscription(grant.pk, subscription_id=first.pk)
    assert EventOutbox.objects.get(subscription=first).state == 'cancelled'
    assert EventOutbox.objects.get(subscription=second).state == 'pending'
    ingest_event(bot, {'op': 0, 'id': 'after-disable', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    assert EventOutbox.objects.filter(subscription=first).count() == 1
    assert EventOutbox.objects.filter(subscription=second).count() == 2


def test_callback_id_cannot_cross_accounts_or_implicitly_disable_all(account):
    _, bot, grant, client = account
    own = set_subscription(grant.pk, 'https://example.com/own', create=True)
    other = User.objects.create_user('other-subscriber')
    other_grant = BotGrant.objects.create(user=other, bot=bot, scopes=['events:read'])
    foreign = set_subscription(other_grant.pk, 'https://example.com/foreign', create=True)
    for active in [True, False]:
        response = client.post('/api/v1/subscriptions/', {'id': foreign.pk, 'bot': bot.pk, 'is_active': active, 'url': 'https://example.com/wrong'}, format='json')
        assert response.status_code == 404
    assert client.post('/api/v1/subscriptions/', {'bot': bot.pk, 'is_active': False}, format='json').status_code == 400
    set_subscription(grant.pk, 'https://example.com/extra', create=True)
    with pytest.raises(CommandError, match='Specify subscription ID'):
        call_command('subscription', 'disable', str(grant.pk))
    call_command('subscription', 'disable', str(grant.pk), subscription=own.pk)
    assert HttpSubscription.objects.get(pk=foreign.pk).is_active


def test_no_artificial_callback_count_cap(account):
    _, bot, grant, _ = account
    # More than common ten / sixteen endpoint limits, using the actual service.
    for index in range(20):
        set_subscription(grant.pk, f'https://example.com/hook/{index}', create=True)
    ingest_event(bot, {'op': 0, 'id': 'many', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    assert EventOutbox.objects.count() == 20
    assert EventOutbox.objects.filter(is_stream=True).count() == 1


def make_call(user, bot, **overrides):
    return ApiCallAudit.objects.create(user=user, bot=bot, username=user.username, bot_name=bot.name,
        request_id='console-trace', method='POST', path='/qq/v2/groups/{group_id}/messages',
        duration_ms=12, **{'status_code': 200, 'replayed': False, **overrides})


def test_audit_filters_are_server_side_and_do_not_bypass_isolation(account):
    user, bot, _, client = account
    wanted = make_call(user, bot)
    make_call(user, bot, status_code=403, replayed=True)
    other = User.objects.create_user('foreign-caller')
    make_call(other, bot)
    response = client.get('/api/v1/api-calls/', {'search': '依卡', 'username': user.username,
        'method': 'POST', 'status': '2xx', 'replayed': 'false', 'bot': bot.pk})
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['calls']] == [wanted.pk]
    assert response.json()['calls'][0]['username'] == user.username
    assert client.get('/api/v1/api-calls/', {'username': other.username}).json()['calls'] == []
    owner = User.objects.create_user('console-owner', role='Owner')
    client.force_authenticate(owner)
    assert len(client.get('/api/v1/api-calls/', {'status': '200'}).json()['calls']) == 2


@pytest.mark.parametrize('query', [
    {'bot': '-1'}, {'api_key': '0'}, {'method': 'DROP'}, {'status': '600'}, {'replayed': 'yes'},
    {'search': 'x' * 201}, {'from': '2026-10-25T12:00:00'}, {'to': 'broken'},
    {'from': '2026-10-26T00:00:00Z', 'to': '2026-10-25T00:00:00Z'},
])
def test_invalid_audit_filter_is_rejected(account, query):
    assert account[3].get('/api/v1/api-calls/', query).status_code == 400


def test_audit_date_bounds_and_pagination_apply_after_filters(account):
    user, bot, _, client = account
    now = timezone.now().replace(microsecond=0)
    first = make_call(user, bot)
    second = make_call(user, bot)
    ApiCallAudit.objects.filter(pk=first.pk).update(created_at=now)
    ApiCallAudit.objects.filter(pk=second.pk).update(created_at=now + timedelta(seconds=1))
    response = client.get('/api/v1/api-calls/', {'from': now.isoformat(), 'to': (now + timedelta(seconds=1)).isoformat()})
    assert [row['id'] for row in response.json()['calls']] == [first.pk]
    assert client.get('/api/v1/api-calls/', {'before': first.pk}).json()['calls'] == []


def test_dashboard_counts_callbacks_not_stream_placeholders_and_uses_all_rows(account):
    user, bot, grant, client = account
    ingest_event(bot, {'op': 0, 'id': 'stream-only', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    result = client.get('/api/v1/dashboard/overview/').json()
    assert result['event_count'] == 1 and result['pending_count'] == 0 and result['delivery_count'] == 0
    set_subscription(grant.pk, 'https://example.com/hook', create=True)
    for index in range(55):
        ingest_event(bot, {'op': 0, 'id': f'callback-{index}', 't': 'C2C_MESSAGE_CREATE', 'd': {}})
    make_call(user, bot)
    make_call(user, bot, status_code=502)
    result = client.get('/api/v1/dashboard/overview/').json()
    assert result['event_count'] == 56 and result['pending_count'] == 55 and result['delivery_count'] == 55
    assert result['api_call_count'] == 2 and result['api_success_count'] == 1 and result['api_error_count'] == 1
    assert len(client.get('/api/v1/deliveries/').json()['deliveries']) == 50
    assert client.get('/api/v1/deliveries/').json()['has_more']


def test_channel_snapshot_scopes_last_http_call_and_never_claims_online(account):
    from uuid import uuid4
    user, bot, _, client = account
    make_call(user, bot)
    other = User.objects.create_user('channel-other')
    make_call(other, bot, status_code=503)
    from .gateway import credential_digest
    GatewaySession.objects.create(bot=bot, credential_digest=credential_digest(bot), lease_token=uuid4(), lease_until=timezone.now() + timedelta(minutes=1), session_id='snapshot')
    result = client.get('/api/v1/dashboard/overview/').json()
    assert result['gateway_worker_count'] == 1
    channel = result['channels'][0]
    assert channel['last_http_status'] == 200
    assert channel['worker_lease_live'] and channel['session_recorded']
    assert 'online' not in channel
    GatewaySession.objects.filter(bot=bot).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert client.get('/api/v1/dashboard/overview/').json()['gateway_worker_count'] == 0
