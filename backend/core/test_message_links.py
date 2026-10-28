import json
import copy
from unittest.mock import patch

import pytest
from django.utils import timezone

from .test_companions import setup, add_mapping, primary_message, slave_message
from .companions import flush_due, backfill_id_evidence
from .events import ingest_event
from .models import BotGrant, CompanionObservation, EventOutbox, OneBotMessage, User
from .onebot import invoke, message_record
from .onebot_ids import original_id, virtual_id, learn_real_id
from .onebot_upstream_events import receive_event
from .services import issue_key
from .websocket import read_onebot_page

pytestmark = pytest.mark.django_db


def quote(slave, *, mid=40005, target=40004):
    event = slave_message(slave, text='quote text', mid=mid)
    event['message'].insert(0, {'type': 'reply', 'data': {
        'id' if slave.channel.interface_type == 'onebot_v11' else 'message_id': str(target)}})
    return event


def primary_quote():
    event = primary_message(text='quote text', mid='quoted!message')
    event['d']['message_scene'] = {'ext': ['msg_idx=quoted/index', 'ref_msg_idx=target/index']}
    return event


def target_primary():
    event = primary_message(mid='target!message')
    event['d']['message_scene'] = {'ext': ['msg_idx=target/index']}
    return event


@pytest.mark.parametrize('slave_first', [False, True])
def test_quote_ids_join_official_message_index_and_real_id_in_both_orders(setup, slave_first):
    master, slave, _, _, key, token = setup
    add_mapping(setup)
    old = virtual_id(master, 'message', 'target/index')
    ingest_event(master, target_primary())
    receive_event(slave, slave_message(slave))
    if slave_first:
        receive_event(slave, quote(slave))
        ingest_event(master, primary_quote())
    else:
        ingest_event(master, primary_quote())
        receive_event(slave, quote(slave))
    assert original_id(master, 'message', old) == 'target!message'
    assert virtual_id(master, 'message', 'target/index') == 40004
    events = read_onebot_page(token, 0, 10001)
    quoted = next(x['payload'] for x in events if x['payload']['message_id'] == 40005)
    assert quoted['message'][0] == {'type': 'reply', 'data': {'id': '40004'}}
    assert message_record(master, key, old, 11).message_id == 'target!message'
    assert message_record(master, key, 'target/index', 12).message_id == 'target!message'
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"sent!opaque/id"}', {})) as send:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': 20002,
            'message': [{'type': 'reply', 'data': {'id': '40004'}}, {'type': 'text', 'data': {'text': 'reply'}}]}, key=key).data
    assert result['retcode'] == 0, result
    assert json.loads(send.call_args.args[2])['message_reference'] == {'message_id': 'target/index'}
    assert message_record(master, key, result['data']['message_id'], 11).message_id == 'sent!opaque/id'


@pytest.mark.parametrize('slave_first', [False, True])
def test_quote_recovers_target_from_companion_history_and_survives_outage(setup, slave_first):
    master, slave, _, _, key, token = setup
    add_mapping(setup)
    receive_event(slave, slave_message(slave))  # No official target received.
    if slave_first:
        receive_event(slave, quote(slave))
    ingest_event(master, primary_quote())
    if not slave_first:
        receive_event(slave, quote(slave))
    reply = next(s for x in read_onebot_page(token, 0, 10001) for s in x['payload']['message'] if s['type'] == 'reply')
    with patch('core.message_links.call', create=True) as remote:
        result = invoke(master, key.scopes, 'get_msg', {'message_id': reply['data']['id']}, key=key).data
    # A previously bridged target already has its content; paired quote upgrades its reference.
    assert result['retcode'] == 0, result
    row = message_record(master, key, reply['data']['id'], 11)
    assert row.reference == 'target/index'
    slave.is_active = False; slave.save()
    assert invoke(master, key.scopes, 'get_msg', {'message_id': 40004}, key=key).data['retcode'] == 0


def test_unknown_quote_fetch_is_authorized_group_checked_cached_and_upgraded(setup):
    master, slave, _, _, key, token = setup
    if slave.channel.interface_type != 'onebot_v11':
        return  # OB12 historical lookup is not a standard action.
    add_mapping(setup)
    receive_event(slave, quote(slave))
    old = read_onebot_page(token, 0, 10001)[0]['payload']['message'][0]['data']['id']
    remote = {'message_id': 40004, 'message_type': 'group', 'group_id': 20002,
        'sender': {'user_id': 30003}, 'time': int(timezone.now().timestamp()),
        'message': [{'type': 'text', 'data': {'text': 'historical target'}}]}
    with patch('core.onebot_upstream.call', return_value=remote) as fetch:
        result = invoke(master, key.scopes, 'get_msg', {'message_id': old}, key=key).data
    assert result['retcode'] == 0, result
    assert fetch.call_args.args[1:] == ('get_msg', {'message_id': 40004})
    cached = message_record(master, key, old, 11)
    assert cached.context_event_id and not cached.source_event_id
    assert not cached.reference and not cached.primary_message_id
    ingest_event(master, primary_quote())
    assert message_record(master, key, old, 11).reference == 'target/index'
    ingest_event(master, target_primary())
    CompanionObservation.objects.filter(side='primary', paired=False).update(due_at=timezone.now())
    flush_due()
    assert message_record(master, key, old, 11).message_id == 'target!message'
    assert virtual_id(master, 'message', 'target!message') == 40004
    assert len(read_onebot_page(token, 0, 10001)) == 2


def test_cached_quote_is_hidden_after_pairing_change(setup):
    master, slave, _, _, key, _ = setup
    if slave.channel.interface_type != 'onebot_v11':
        return
    mapping = add_mapping(setup)
    receive_event(slave, quote(slave))
    remote = {'message_id': 40004, 'message_type': 'group', 'group_id': 20002,
        'sender': {'user_id': 30003}, 'time': int(timezone.now().timestamp()),
        'message': [{'type':'text','data':{'text':'target'}}]}
    with patch('core.onebot_upstream.call', return_value=remote):
        assert invoke(master, key.scopes, 'get_msg', {'message_id':40004}, key=key).data['retcode'] == 0
    mapping.origin = 'manual'; mapping.enabled = False; mapping.save()
    assert invoke(master, key.scopes, 'get_msg', {'message_id':40004}, key=key).data['retcode'] == 1403


@pytest.mark.parametrize('failure', ['wrong_group', 'new_grant', 'revoked_during_fetch'])
def test_lookup_allows_history_without_delivery_snapshot_but_blocks_revoked_keys(setup, failure):
    master, slave, _, _, key, _ = setup
    if slave.channel.interface_type != 'onebot_v11':
        return
    add_mapping(setup)
    receive_event(slave, quote(slave))
    if failure == 'new_grant':
        user = User.objects.create_user('new-history-user')
        BotGrant.objects.create(user=user, bot=master, scopes=['events:read'])
        key, _ = issue_key(user, master, 'new', ['events:read'])
    def fetch(*args, **kwargs):
        if failure == 'revoked_during_fetch':
            key.revoked_at = timezone.now(); key.save()
        return {'message_id': 40004, 'message_type': 'group',
            'group_id': 999 if failure == 'wrong_group' else 20002,
            'sender': {'user_id': 30003}, 'time': int(timezone.now().timestamp()),
            'message': [{'type': 'text', 'data': {'text': 'private history'}}]}
    before = OneBotMessage.objects.filter(bot=master).count()
    with patch('core.onebot_upstream.call', side_effect=fetch) as remote:
        result = invoke(master, key.scopes, 'get_msg', {'message_id': 40004}, key=key).data
    if failure == 'revoked_during_fetch':
        assert result['retcode'] != 0
        assert OneBotMessage.objects.filter(bot=master).count() == before
    else:
        # Authenticated lookups now intentionally allow history without event
        # grant snapshots or conversation selection, as requested by the owner.
        assert result['retcode'] == 0
        remote.assert_called()


def test_quote_links_existing_native_target_without_reference_and_repairs_old_pairs(setup):
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    target = target_primary()
    target['d'].pop('message_scene')
    target['d'].pop('ext_info')
    ingest_event(master, target)
    receive_event(slave, slave_message(slave))
    assert not message_record(master, key, 40004, 11).reference
    # Simulate an older release which paired messages but didn't learn quote evidence.
    with patch('core.message_links.learn_quotes'):
        ingest_event(master, primary_quote())
        receive_event(slave, quote(slave))
    CompanionObservation.objects.filter(side='primary').update(quote_links_checked=False)
    assert not message_record(master, key, 40004, 11).reference
    assert backfill_id_evidence(master.channel) == 0
    assert message_record(master, key, 40004, 11).reference == 'target/index'
    assert virtual_id(master, 'message', 'target/index') == 40004


def test_quote_conflicts_do_not_rebind_message_across_groups(setup):
    from .message_links import learn_quotes
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    ingest_event(master, target_primary())
    receive_event(slave, slave_message(slave))
    other = OneBotMessage.objects.create(bot=master, message_id='other-message',
        target_id='other-group', is_direct=False, conversation_type='group',
        sent_at=timezone.now().timestamp())
    learn_real_id(master, 'message', other.message_id, '99999')
    p = copy.copy(message_record(master, key, 40004, 11))
    s = copy.copy(OneBotMessage.objects.get(bot=slave, message_id='40004'))
    p.segments = [{'type':'reply','data':{'message_id':'target/index'}}]
    s.segments = [{'type':'reply','data':{'message_id':'99999'}}]
    learn_quotes(master, p, s)
    assert original_id(master, 'message', 99999) == 'other-message'
    assert original_id(master, 'message', 40004) == 'target!message'
