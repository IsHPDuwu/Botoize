import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from .gateway import (GatewayError, LeaseLost, Reconnect, claim, consume_connection,
                      dispatch, gateway_url, release, renew)
from .models import Bot, BotGrant, Event, EventOutbox, GatewaySession, User
from .services import encrypt_secret

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker():
    bot = Bot.objects.create(name='gateway', app_id='gateway', encrypted_secret=encrypt_secret('secret'))
    user = User.objects.create_user('gateway-admin')
    BotGrant.objects.create(bot=bot, user=user, scopes=['events:read'])
    return claim(bot.pk, 1 << 25)


def ready():
    return {'op': 0, 's': 1, 't': 'READY', 'd': {'session_id': 'official-session'}}


def event():
    return {'op': 0, 's': 2, 't': 'C2C_MESSAGE_CREATE', 'id': 'official-event', 'd': {'id': 'msg'}}


def test_lease_is_exclusive_and_release_is_fenced(worker):
    import uuid
    bot, row, token = worker
    with pytest.raises(GatewayError, match='Another'):
        claim(bot.pk, row.intents)
    release(bot, uuid.uuid4())
    renew(bot, token)
    release(bot, token)
    _, _, next_token = claim(bot.pk, row.intents)
    assert next_token != token
    with pytest.raises(LeaseLost):
        renew(bot, token)


def test_expired_worker_cannot_commit(worker):
    bot, row, token = worker
    GatewaySession.objects.filter(pk=row.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    with pytest.raises(LeaseLost):
        dispatch(bot, token, ready())
    with pytest.raises(LeaseLost):
        renew(bot, token)


@pytest.mark.parametrize('change', [{'is_active': False}, {'encrypted_secret': 'rotated'}])
def test_credential_change_stops_existing_worker(worker, change):
    bot, _, token = worker
    Bot.objects.filter(pk=bot.pk).update(**change)
    with pytest.raises(LeaseLost):
        renew(bot, token)
    with pytest.raises(LeaseLost):
        dispatch(bot, token, ready())


def test_event_and_sequence_commit_together_and_replay_is_deduplicated(worker):
    bot, _, token = worker
    dispatch(bot, token, ready())
    dispatch(bot, token, event())
    dispatch(bot, token, event())
    assert Event.objects.count() == EventOutbox.objects.count() == 1
    assert Event.objects.get().payload == event()
    assert GatewaySession.objects.get(bot=bot).sequence == 2
    bad = {**event(), 's': 3, 'id': 'another-event'}
    with patch('core.gateway.ingest_event', side_effect=RuntimeError('database failure')):
        with pytest.raises(RuntimeError):
            dispatch(bot, token, bad)
    assert GatewaySession.objects.get(bot=bot).sequence == 2
    assert Event.objects.count() == 1


def test_changed_intents_clear_resume_state(worker):
    bot, _, token = worker
    dispatch(bot, token, ready())
    release(bot, token)
    _, row, _ = claim(bot.pk, 1 << 30)
    assert row.session_id == '' and row.sequence is None


@pytest.mark.parametrize('url', ['ws://api.bot.qq.com/websocket', 'wss://evil.test/websocket',
                                 'wss://api.bot.qq.com@evil.test/websocket',
                                 'wss://api.bot.qq.com/websocket?token=secret'])
def test_discovery_never_sends_credentials_to_untrusted_endpoint(worker, url):
    bot, _, _ = worker
    body = json.dumps({'url': url, 'session_start_limit': {'remaining': 1, 'max_concurrency': 1}}).encode()
    with patch('core.gateway.get_gateway', return_value=(200, body, {})):
        with pytest.raises(GatewayError):
            gateway_url(bot)


def test_discovery_enforces_session_start_budget(worker):
    bot, _, _ = worker
    body = b'{"url":"wss://api.bot.qq.com/websocket/","session_start_limit":{"remaining":0,"max_concurrency":1}}'
    with patch('core.gateway.get_gateway', return_value=(200, body, {})):
        with pytest.raises(GatewayError, match='budget'):
            gateway_url(bot)
        assert gateway_url(bot, resume=True) == 'wss://api.bot.qq.com/websocket/'


@pytest.mark.parametrize('host', ['api.bot.qq.com', 'api.sgroup.qq.com'])
def test_discovery_accepts_only_known_official_gateway_hosts(worker, host, settings):
    settings.QQ_GATEWAY_HOST = None
    bot, _, _ = worker
    url = f'wss://{host}/websocket'
    body = json.dumps({'url': url, 'session_start_limit': {'remaining': 1, 'max_concurrency': 1}}).encode()
    with patch('core.gateway.get_gateway', return_value=(200, body, {})):
        assert gateway_url(bot) == url


def test_gateway_canonical_host_override_is_restricted(worker, settings):
    bot, _, _ = worker
    body = b'{"url":"wss://api.sgroup.qq.com/websocket/","session_start_limit":{"remaining":1,"max_concurrency":1}}'
    with patch('core.gateway.get_gateway', return_value=(200, body, {})):
        settings.QQ_GATEWAY_HOST = 'api.bot.qq.com'
        assert gateway_url(bot) == 'wss://api.bot.qq.com/websocket/'
        settings.QQ_GATEWAY_HOST = 'evil.example.com'
        with pytest.raises(GatewayError):
            gateway_url(bot)


def test_bounded_gateway_skips_other_targets_without_persisting_them(worker):
    bot, _, token = worker
    dispatch(bot, token, ready(), allowed_group='allowed')
    other = {'op':0,'s':2,'t':'GROUP_AT_MESSAGE_CREATE','id':'other-event','d':{'group_openid':'other'}}
    dispatch(bot, token, other, allowed_group='allowed')
    assert not Event.objects.exists()
    assert GatewaySession.objects.get(bot=bot).sequence == 2
    accepted = {**other, 's':3, 'id':'allowed-event', 'd':{'group_openid':'allowed'}}
    dispatch(bot, token, accepted, allowed_group='allowed')
    assert Event.objects.get().event_id == 'allowed-event'


@pytest.mark.parametrize('resume', [False, True])
def test_official_identify_and_resume_wire_contract(worker, resume):
    bot, _, token = worker
    if resume:
        dispatch(bot, token, ready())
    socket = MagicMock()
    socket.recv.side_effect = [json.dumps({'op': 10, 'd': {'heartbeat_interval': 45000}}),
                               json.dumps({'op': 7})]
    with patch('core.gateway.gateway_url', return_value='wss://api.bot.qq.com/websocket/'), \
            patch('core.gateway.access_token', return_value='test-token'), \
            patch('core.gateway.connect') as connection:
        connection.return_value.__enter__.return_value = socket
        with pytest.raises(Reconnect):
            consume_connection(bot, token)
    packet = json.loads(socket.send.call_args.args[0])
    from django.conf import settings
    assert connection.call_args.kwargs['proxy'] == (settings.QQ_HTTP_PROXY or True)
    assert packet['d']['token'] == 'QQBot test-token'
    assert packet['op'] == (6 if resume else 2)
    if resume:
        assert packet['d'] == {'token': 'QQBot test-token', 'session_id': 'official-session', 'seq': 1}
    else:
        assert packet['d']['shard'] == [0, 1] and packet['d']['intents'] == 1 << 25


def test_invalid_session_discards_resume_checkpoint(worker):
    bot, _, token = worker
    dispatch(bot, token, ready())
    socket = MagicMock()
    socket.recv.side_effect = [json.dumps({'op': 10, 'd': {'heartbeat_interval': 45000}}),
                               json.dumps({'op': 9, 'd': False})]
    with patch('core.gateway.gateway_url', return_value='wss://api.bot.qq.com/websocket/'), \
            patch('core.gateway.access_token', return_value='test-token'), \
            patch('core.gateway.connect') as connection:
        connection.return_value.__enter__.return_value = socket
        with pytest.raises(Reconnect):
            consume_connection(bot, token)
    row = GatewaySession.objects.get(bot=bot)
    assert row.session_id == '' and row.sequence is None


@pytest.mark.parametrize('ack', [False, True])
def test_heartbeat_ack_contract(worker, ack):
    bot, _, token = worker
    socket = MagicMock()
    incoming = [json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}),
                json.dumps(ready()), json.dumps({'op': 11 if ack else 1}),
                json.dumps({'op': 7})]
    socket.recv.side_effect = incoming
    # first tick 0 -> first heartbeat at 1; next tick 2 must have an ACK.
    ticks = iter([0, 0, 1, 1, 1.1, 1.1, 2, 2, 2.1, 2.1])
    with patch('core.gateway.gateway_url', return_value='wss://api.bot.qq.com/websocket/'), \
            patch('core.gateway.access_token', return_value='test-token'), \
            patch('core.gateway.time.monotonic', side_effect=lambda: next(ticks)), \
            patch('core.gateway.connect') as connection:
        connection.return_value.__enter__.return_value = socket
        with pytest.raises(Reconnect, match='reconnect' if ack else 'acknowledgement'):
            consume_connection(bot, token)
    packets = [json.loads(call.args[0]) for call in socket.send.call_args_list]
    assert any(p['op'] == 1 for p in packets)
