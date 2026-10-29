"""Official self -> actual QQ account persists across downstream IDs and outages."""
from unittest.mock import patch

import pytest
from django.utils import timezone

from .test_companions import setup, add_mapping, slave_message
from .companions import backfill_id_evidence
from .models import OneBotMessage
from .onebot import invoke
from .onebot_ids import original_id, real_for_original, virtual_id, learn_real_id
from .onebot_upstream_events import receive_event
from .self_identity import repair_self_identity
from .upstreams import onebot_version

pytestmark = pytest.mark.django_db
OWN = 'official-self'
ACCOUNT = '3889808476'
TEXT = 'unique official rendering hint'


def own_setup(setup):
    master = setup[0]
    add_mapping(setup)
    master.channel.onebot_self_id = OWN
    master.channel.save(update_fields=['onebot_self_id'])
    return virtual_id(master, 'user', OWN)


def sent_message(setup, *, mid='official-sent', text=TEXT, sender=OWN):
    return OneBotMessage.objects.create(bot=setup[0], message_id=mid, target_id='openid-group',
        incoming=False, is_direct=False, conversation_type='group', sender_id=sender,
        created_by=setup[2], sent_at=timezone.now().timestamp(),
        segments=[{'type': 'text', 'data': {'text': text}}])


@pytest.mark.parametrize('companion_first', [False, True])
def test_self_binding_from_own_send_in_both_orders_survives_outage(setup, companion_first):
    master, slave, _, _, key, _ = setup
    old = own_setup(setup)
    remote = slave_message(slave, text=TEXT, user=int(ACCOUNT))
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"official-sent"}', {})) as send:
        if companion_first:
            receive_event(slave, remote)
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': 20002, 'message': TEXT}, key=key).data
        assert result['retcode'] == 0, result
        send.assert_called_once()
        if not companion_first:
            receive_event(slave, remote)
    assert real_for_original(master, 'user', OWN) == ACCOUNT
    assert virtual_id(master, 'user', OWN) == int(ACCOUNT)
    assert original_id(master, 'user', old) == OWN
    assert real_for_original(master, 'message', 'official-sent') == '40004'
    assert ACCOUNT != slave.app_id
    slave.is_active = False
    slave.save(update_fields=['is_active'])
    with patch('core.onebot_upstream.call') as upstream:
        data = invoke(master, key.scopes, 'get_msg', {'message_id': result['data']['message_id']}, key=key).data
    assert data['retcode'] == 0, data
    assert data['data']['sender']['user_id'] == int(ACCOUNT)
    upstream.assert_not_called()


@pytest.mark.parametrize('version', [11, 12])
def test_legacy_self_member_query_repairs_mapping_and_uses_actual_account(setup, version):
    master, slave, _, _, key, _ = setup
    old = own_setup(setup)
    sent_message(setup, sender='')
    with patch('core.self_identity.learn_from_companion', return_value=False):
        receive_event(slave, slave_message(slave, text=TEXT, user=int(ACCOUNT)))
    assert real_for_original(master, 'user', OWN) is None
    with patch('core.onebot_groups._request', return_value=(403, b'{}', {})), patch(
            'core.companion_actions.identity', return_value=({'platform': 'qq', 'user_id': slave.app_id}, 'slave')), patch(
            'core.companion_actions.call', return_value={'group_id': 20002, 'user_id': int(ACCOUNT), 'nickname': 'Official'}) as remote:
        result = invoke(master, key.scopes, 'get_group_member_info', {
            'group_id': 20002 if version == 11 else 'openid-group',
            'user_id': str(old) if version == 11 else OWN}, key=key, version=version).data
    assert result['retcode'] == 0, result
    remote.assert_called_once()
    assert remote.call_args.args[2]['user_id'] == (int(ACCOUNT) if onebot_version(slave) == 11 else ACCOUNT)
    assert result['data']['user_id'] == (int(ACCOUNT) if version == 11 else OWN)
    assert OneBotMessage.objects.get(bot=master, message_id='official-sent').sender_id == OWN


def test_history_maintenance_repairs_self_without_network_or_replaying_sends(setup):
    master, slave = setup[:2]
    old = own_setup(setup)
    sent_message(setup)
    with patch('core.self_identity.learn_from_companion', return_value=False):
        receive_event(slave, slave_message(slave, text=TEXT, user=int(ACCOUNT)))
    with patch('core.onebot_upstream.call') as network, patch('core.onebot.send_message') as send:
        backfill_id_evidence(master.channel)
    assert real_for_original(master, 'user', OWN) == ACCOUNT
    assert original_id(master, 'user', old) == OWN
    network.assert_not_called()
    send.assert_not_called()


def test_get_msg_repairs_legacy_self_before_returning_sender(setup):
    master, slave, _, _, key, _ = setup
    old = own_setup(setup)
    row = sent_message(setup)
    with patch('core.self_identity.learn_from_companion', return_value=False):
        receive_event(slave, slave_message(slave, text=TEXT, user=int(ACCOUNT)))
    result = invoke(master, key.scopes, 'get_msg', {
        'message_id': virtual_id(master, 'message', row.message_id)}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['sender']['user_id'] == int(ACCOUNT)
    assert original_id(master, 'user', old) == OWN


@pytest.mark.parametrize('case', ['duplicate_sent', 'duplicate_received', 'disabled_group', 'conflict', 'stale_source'])
def test_unreliable_evidence_does_not_bind_official_self(setup, case):
    master, slave = setup[:2]
    own_setup(setup)
    sent_message(setup)
    with patch('core.self_identity.learn_from_companion', return_value=False):
        receive_event(slave, slave_message(slave, text=TEXT, user=int(ACCOUNT)))
        if case == 'duplicate_received':
            receive_event(slave, slave_message(slave, text=TEXT, user=34567, mid=40005))
    if case == 'duplicate_sent':
        sent_message(setup, mid='second-sent')
    elif case == 'disabled_group':
        master.channel.group_matches.update(enabled=False)
    elif case == 'conflict':
        learn_real_id(master, 'user', OWN, '12345678')
    elif case == 'stale_source':
        OneBotMessage.objects.filter(bot=slave).update(source_digest='old-source')
    assert not repair_self_identity(master)
    assert real_for_original(master, 'user', OWN) == ('12345678' if case == 'conflict' else None)


def test_verified_message_id_can_repair_self_even_for_media_without_text(setup):
    master, slave = setup[:2]
    own_setup(setup)
    row = sent_message(setup)
    row.segments = [{'type': 'botoize.sent_media', 'data': {}}]
    row.save(update_fields=['segments'])
    learn_real_id(master, 'message', row.message_id, '40004')
    receive_event(slave, slave_message(slave, text='other representation', user=int(ACCOUNT)))
    assert real_for_original(master, 'user', OWN) == ACCOUNT
