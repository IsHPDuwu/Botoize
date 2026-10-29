"""Active identity probes use synthetic transports only; no real sends/recalls."""
import io
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .test_companions import setup, add_mapping, primary_message, slave_message
from .companions import shadow_user, backfill_id_evidence
from .events import ingest_event, publish_event
from .identity_probes import request_identity, process_probe, process_pending
from .models import IdentityProbe, EventOutbox, OneBotMessage, Channel
from .onebot import invoke
from .onebot_common import OneBotError
from .onebot_events import message_event
from .onebot_ids import real_for_original, original_id, virtual_id, learn_real_id
from .onebot_upstream_events import receive_event
from .upstreams import onebot_version

pytestmark = pytest.mark.django_db
REAL = '3456789'
ORIGINAL = 'unseen-openid'


def enable(setup):
    master = setup[0]
    add_mapping(setup)
    master.channel.identity_probe_enabled = True
    master.channel.save(update_fields=['identity_probe_enabled'])


def evidence(setup, probe, *, group=None, extra=False):
    master, slave = setup[:2]
    text = 'botoize-id:' + probe.marker.hex
    if probe.direction == 'companion':
        event = primary_message(text=text + f' <@{ORIGINAL}>', group=group or 'openid-group', mid='probe-inbound')
        if extra:
            event['d']['content'] += ' <@other-openid>'
        return ingest_event(master, event)[0]
    event = slave_message(slave, text=text, group=group or 20002, user=456789, mid=50005)
    segment = {'type': 'at', 'data': {'qq': REAL}} if onebot_version(slave) == 11 else {'type': 'mention', 'data': {'user_id': REAL}}
    event['message'].append(segment)
    if extra:
        event['message'].append(segment)
    return receive_event(slave, event)[0]


@pytest.mark.parametrize('direction', ['primary', 'companion'])
@pytest.mark.parametrize('early_event', [False, True])
def test_probe_sends_once_recalls_immediately_and_learns_without_downstream_delivery(setup, direction, early_event):
    master, slave, _, _, key, _ = setup
    enable(setup)
    shadow = shadow_user(master, REAL)
    old_id = virtual_id(master, 'user', shadow)
    probe = request_identity(master, 'openid-group', **({'original': ORIGINAL} if direction == 'primary' else {'real': REAL}))
    order = []
    def official(bot, method, path, *args, **kwargs):
        order.append(method)
        assert bot.pk == master.pk
        if method == 'POST':
            body = json.loads(kwargs['body'])
            assert ORIGINAL in body['markdown']['content']
            if early_event:
                evidence(setup, probe)
            return 200, b'{"id":"opaque/probe!id"}', {}
        assert path.endswith('/opaque%2Fprobe%21id')
        return 204, b'', {}
    def remote(bot, action, params, **kwargs):
        order.append(action)
        if action.startswith('send'):
            segment = params['message'][1]
            assert str(next(iter(segment['data'].values()))) == REAL
            if early_event:
                evidence(setup, probe)
            return {'message_id': 60006 if onebot_version(slave) == 11 else 'msg:60006'}
        return None
    with patch('core.official._request', side_effect=official), patch('core.onebot_upstream.call', side_effect=remote), patch(
            'core.onebot_upstream.identity', return_value=({'platform': 'qq', 'user_id': slave.app_id}, 'slave')):
        process_probe(probe.pk)
        process_probe(probe.pk)
        probe.refresh_from_db()
        assert not probe.cleanup_pending
        if not early_event:
            assert probe.state == 'waiting'
            event = evidence(setup, probe)
            assert event.payload['botoize.identity_probe'] is True
            assert message_event(event.bot, event.payload, 123, key=key) is None
            publish_event(event)  # Manual publication cannot leak it either.
    assert order == (['POST', 'DELETE'] if direction == 'primary' else
        ['send_group_msg', 'delete_msg'] if onebot_version(slave) == 11 else ['send_message', 'delete_message'])
    probe.refresh_from_db()
    assert probe.state == 'matched'
    assert real_for_original(master, 'user', ORIGINAL) == REAL
    assert original_id(master, 'user', old_id) == ORIGINAL
    assert virtual_id(master, 'user', ORIGINAL) == int(REAL)
    assert not EventOutbox.objects.exists()
    assert not OneBotMessage.objects.exists()
    with patch('core.onebot_upstream.call') as call:
        backfill_id_evidence(master.channel)
    call.assert_not_called()
    assert not EventOutbox.objects.exists()


@pytest.mark.parametrize('direction', ['primary', 'companion'])
def test_timeout_is_unknown_and_never_resends_even_after_worker_restart(setup, direction):
    master, slave = setup[:2]
    enable(setup)
    probe = request_identity(master, 'openid-group', **({'original': ORIGINAL} if direction == 'primary' else {'real': REAL}))
    with patch('core.official._request', side_effect=TimeoutError) as official, patch(
            'core.onebot_upstream.call', side_effect=OneBotError(33000, 'secret upstream error')) as remote, patch(
            'core.onebot_upstream.identity', return_value=({'platform': 'qq', 'user_id': slave.app_id}, 'slave')):
        process_probe(probe.pk)
        process_pending()
        assert request_identity(master, 'openid-group', **({'original': ORIGINAL} if direction == 'primary' else {'real': REAL})).pk == probe.pk
    probe.refresh_from_db()
    assert probe.state == 'unknown' and probe.error_code == 'send_unknown'
    assert not probe.cleanup_pending
    assert official.call_count + remote.call_count == 1
    evidence(setup, probe)  # Late event can still identify after a timeout.
    assert real_for_original(master, 'user', ORIGINAL) == REAL


def test_recall_failure_retries_only_recall_not_send_and_survives_disabled_switch(setup):
    master, slave = setup[:2]
    enable(setup)
    probe = request_identity(master, 'openid-group', real=REAL)
    calls = []
    def remote(bot, action, params, **kwargs):
        calls.append(action)
        if action.startswith('send'):
            return {'message_id': 60006 if onebot_version(slave) == 11 else '60006'}
        if len(calls) == 2:
            raise OneBotError(33000, 'upstream secret')
    with patch('core.onebot_upstream.call', side_effect=remote), patch('core.onebot_upstream.identity',
            return_value=({'platform': 'qq', 'user_id': slave.app_id}, 'slave')):
        process_probe(probe.pk)
        probe.refresh_from_db()
        assert probe.cleanup_pending and probe.error_code == 'recall_failed'
        Channel.objects.filter(pk=master.channel_id).update(identity_probe_enabled=False)
        IdentityProbe.objects.filter(pk=probe.pk).update(updated_at=timezone.now()-timedelta(seconds=20))
        process_pending()
    probe.refresh_from_db()
    assert probe.cleanup_attempts == 2 and not probe.cleanup_pending
    assert len(calls) == 3 and calls[0].startswith('send') and calls[1].startswith('delete') and calls[2] == calls[1]


@pytest.mark.parametrize('case', ['off', 'unmatched', 'disabled_match', 'inactive_slave', 'already_known'])
def test_no_probe_without_opt_in_valid_matched_group_and_missing_mapping(setup, case):
    master, slave = setup[:2]
    enable(setup)
    if case == 'off':
        master.channel.identity_probe_enabled = False
    elif case == 'disabled_match':
        master.channel.group_matches.update(enabled=False)
    elif case == 'inactive_slave':
        slave.is_active = False; slave.save()
    elif case == 'already_known':
        learn_real_id(master, 'user', ORIGINAL, REAL)
    assert request_identity(master, 'unknown' if case == 'unmatched' else 'openid-group', real=REAL) is None
    assert not IdentityProbe.objects.exists()


@pytest.mark.parametrize('case', ['wrong_group', 'expired', 'disabled', 'changed_config', 'two_mentions', 'conflict'])
@pytest.mark.parametrize('direction', ['primary', 'companion'])
def test_untrusted_stale_or_ambiguous_evidence_does_not_bind(setup, case, direction):
    master = setup[0]
    enable(setup)
    probe = request_identity(master, 'openid-group', **({'original': ORIGINAL} if direction == 'primary' else {'real': REAL}))
    IdentityProbe.objects.filter(pk=probe.pk).update(state='waiting')
    if case == 'expired':
        IdentityProbe.objects.filter(pk=probe.pk).update(created_at=timezone.now()-timedelta(minutes=2))
    elif case == 'disabled':
        Channel.objects.filter(pk=master.channel_id).update(identity_probe_enabled=False)
    elif case == 'changed_config':
        master.channel.group_matches.update(origin='manual', name='changed')
    elif case == 'conflict':
        learn_real_id(master, 'user', ORIGINAL, '99999')
    evidence(setup, probe, group=('other-group' if direction == 'companion' else 99999) if case == 'wrong_group' else None,
        extra=case == 'two_mentions')
    assert real_for_original(master, 'user', ORIGINAL) == ('99999' if case == 'conflict' else None)


def test_requests_are_deduplicated_and_channel_notifications_are_bounded(setup):
    master = setup[0]
    enable(setup)
    first = request_identity(master, 'openid-group', real=REAL)
    assert first.pk == request_identity(master, 'openid-group', real=REAL).pk
    for i in range(4):
        assert request_identity(master, 'openid-group', real=str(88880+i))
    assert request_identity(master, 'openid-group', real='77777') is None
    assert IdentityProbe.objects.count() == 5


def test_switch_off_cancels_queued_probe_before_network_call(setup):
    master = setup[0]
    enable(setup)
    probe = request_identity(master, 'openid-group', real=REAL)
    Channel.objects.filter(pk=master.channel_id).update(identity_probe_enabled=False)
    with patch('core.onebot_upstream.call') as call:
        process_probe(probe.pk)
    call.assert_not_called()
    probe.refresh_from_db()
    assert probe.state == 'cancelled'


def test_normal_message_evidence_arriving_before_probe_avoids_unnecessary_notification(setup):
    master = setup[0]
    enable(setup)
    probe = request_identity(master, 'openid-group', real=REAL)
    learn_real_id(master, 'user', ORIGINAL, REAL)
    with patch('core.onebot_upstream.call') as call:
        process_probe(probe.pk)
    call.assert_not_called()
    probe.refresh_from_db()
    assert probe.state == 'cancelled' and probe.error_code == 'already_identified'


@pytest.mark.parametrize('direction', ['primary', 'companion'])
def test_copying_probe_marker_from_another_known_sender_cannot_rebind_identity(setup, direction):
    master, slave = setup[:2]
    enable(setup)
    master.channel.onebot_self_id = 'official-self'
    master.channel.save()
    learn_real_id(master, 'user', 'official-self', '90009')
    learn_real_id(master, 'user', 'companion-openid', slave.app_id)
    probe = request_identity(master, 'openid-group', **({'original': ORIGINAL} if direction == 'primary' else {'real': REAL}))
    IdentityProbe.objects.filter(pk=probe.pk).update(state='waiting')
    evidence(setup, probe)  # The fixture uses a third user's sender, not either emitter.
    assert real_for_original(master, 'user', ORIGINAL) is None


def test_quote_lookup_requests_sender_identification_but_read_only_key_does_not_send(setup):
    master, slave, _, grant, key, _ = setup
    enable(setup)
    receive_event(slave, slave_message(slave, user=int(REAL)))
    result = invoke(master, key.scopes, 'get_msg', {'message_id': 40004}, key=key).data
    assert result['retcode'] == 0, result
    assert IdentityProbe.objects.get().real_user == REAL
    IdentityProbe.objects.all().delete()
    for policy in (key, grant):
        policy.all_conversations = False
        policy.scopes = []
        policy.save()
    result = invoke(master, [], 'get_msg', {'message_id': 40004}, key=key).data
    assert result['retcode'] == 0, result
    assert not IdentityProbe.objects.exists()


def test_inbound_and_outbound_mentions_queue_both_directions_without_changing_reply_segments(setup):
    master, slave, _, _, key, _ = setup
    enable(setup)
    event = slave_message(slave)
    event['message'].append({'type': 'at', 'data': {'qq': REAL}} if onebot_version(slave) == 11 else
        {'type': 'mention', 'data': {'user_id': REAL}})
    receive_event(slave, event)
    assert IdentityProbe.objects.get().direction == 'companion'
    event = primary_message(text='different text <@other-openid>', mid='primary-mention')
    ingest_event(master, event)
    assert IdentityProbe.objects.filter(direction='primary', original_user='other-openid').exists()
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"sent"}', {})):
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': 20002,
            'message': [{'type': 'at', 'data': {'qq': '998877'}}, {'type': 'text', 'data': {'text': 'body'}}]}, key=key).data
    assert result['retcode'] == 0, result
    assert IdentityProbe.objects.filter(direction='companion', real_user='998877').exists()


def test_provider_switch_is_default_off_owner_only_and_requires_official_companion(setup):
    master, slave, owner = setup[:3]
    client = APIClient(); client.force_login(owner)
    url = f'/api/v1/providers/{master.channel.provider_id}/'
    data = client.get(url).json(); data.pop('id')
    assert data['channels'][0]['identity_probe_enabled'] is False
    data['channels'][0]['identity_probe_enabled'] = True
    response = client.patch(url, data, format='json')
    assert response.status_code == 200, response.content
    assert response.json()['channels'][0]['identity_probe_enabled'] is True
    data['channels'][0]['identity_probe_enabled'] = 'yes'
    assert client.patch(url, data, format='json').status_code == 400
    data['channels'][0]['identity_probe_enabled'] = True
    data['channels'][0]['companion_channel'] = None
    assert client.patch(url, data, format='json').status_code == 400
    url = f'/api/v1/providers/{slave.channel.provider_id}/'
    data = client.get(url).json(); data.pop('id')
    data['channels'][0]['identity_probe_enabled'] = True
    assert client.patch(url, data, format='json').status_code == 400


def test_supervisor_recovers_persisted_probe_work(setup):
    from .management.commands.run_connections import Supervisor
    enable(setup)
    request_identity(setup[0], 'openid-group', real=REAL)
    supervisor = Supervisor(intents=1, allowed_group=None, stderr=io.StringIO())
    supervisor.pool.shutdown()
    supervisor.pool = MagicMock()
    try:
        with patch('core.management.commands.run_connections.subprocess.Popen') as spawn:
            spawn.return_value.poll.return_value = None
            supervisor.tick()
        from .identity_probes import process_pending
        assert any(call.args[0] is process_pending for call in supervisor.pool.submit.call_args_list)
    finally:
        supervisor.close()


@pytest.mark.django_db(transaction=True)
def test_current_outbound_at_waits_for_mapping_then_sends_structured_official_mention(setup):
    master, slave, _, _, key, _ = setup
    enable(setup)
    def remote(bot, action, params, **kwargs):
        if action.startswith('send'):
            evidence(setup, IdentityProbe.objects.get())
            return {'message_id': 60006 if onebot_version(slave) == 11 else '60006'}
        return None
    with patch('core.onebot_upstream.call', side_effect=remote), patch('core.onebot_upstream.identity',
            return_value=({'platform': 'qq', 'user_id': slave.app_id}, 'slave')), patch(
            'core.onebot.send_message', return_value=(200, b'{"id":"body-sent"}', {})) as send:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': 20002,
            'message': [{'type': 'at', 'data': {'qq': REAL}}, {'type': 'text', 'data': {'text': 'business body'}}]}, key=key).data
    assert result['retcode'] == 0, result
    assert json.loads(send.call_args.args[2])['content'] == f'<qqbot-at-user id="{ORIGINAL}" />business body'
    assert IdentityProbe.objects.get().state == 'matched'


@pytest.mark.django_db(transaction=True)
def test_current_quote_get_msg_with_only_openid_returns_real_sender_after_primary_probe(setup):
    master, slave, _, _, key, _ = setup
    enable(setup)
    OneBotMessage.objects.create(bot=master, message_id='quote-target', sender_id=ORIGINAL,
        target_id='openid-group', conversation_type='group', is_direct=False, incoming=True,
        sent_at=100, segments=[{'type': 'text', 'data': {'text': 'quote content'}}])
    old = virtual_id(master, 'user', ORIGINAL)
    def official(bot, method, path, *args, **kwargs):
        if method == 'POST':
            evidence(setup, IdentityProbe.objects.get())
            return 200, b'{"id":"probe-id"}', {}
        return 204, b'', {}
    with patch('core.official._request', side_effect=official) as network:
        result = invoke(master, key.scopes, 'get_msg', {
            'message_id': virtual_id(master, 'message', 'quote-target')}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['sender']['user_id'] == int(REAL)
    assert original_id(master, 'user', old) == ORIGINAL
    assert [call.args[1] for call in network.call_args_list] == ['POST', 'DELETE']
