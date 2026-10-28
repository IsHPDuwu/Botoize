"""Koishi quote/profile/media regressions, with synthetic transports only."""
import json
from unittest.mock import patch

import pytest
from django.utils import timezone

from .test_companions import setup, add_mapping, primary_message, slave_message
from .companions import backfill_id_evidence
from .events import ingest_event
from .models import CompanionObservation, OneBotMessage
from .onebot import invoke
from .onebot_ids import learn_real_id, virtual_id, original_id, real_for_original
from .onebot_upstream_events import receive_event
from .upstreams import onebot_version
from . import companion_actions, onebot_upstream_actions  # Load call aliases before transport patches.

pytestmark = pytest.mark.django_db


def restrict(key, grant):
    for policy in (key, grant):
        policy.scopes = []
        policy.all_conversations = False
        policy.save()
        policy.conversations.clear()


def test_profile_lookup_from_group_member_does_not_require_private_chat_or_scope(setup):
    master, slave, _, grant, key, _ = setup
    learn_real_id(master, 'user', 'member-openid', '30003')
    uid = virtual_id(master, 'user', 'member-openid')
    restrict(key, grant)
    with patch('core.onebot_upstream.identity', return_value=({'platform': 'qq', 'user_id': '10001'}, 'slave')), patch(
            'core.onebot_upstream.call', return_value={'user_id': 30003, 'nickname': 'Member'}) as call:
        result = invoke(master, [], 'get_stranger_info', {'user_id': uid}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['user_id'] == 30003
    assert call.call_args.args[2]['user_id'] == (30003 if onebot_version(slave) == 11 else '30003')
    # Access relaxation doesn't grant any write operation.
    assert invoke(master, [], 'send_group_msg', {'group_id': 20002, 'message': 'blocked'}, key=key).data['retcode'] == 1403


def test_get_msg_repairs_sent_sender_and_legacy_zero_profile(setup):
    master, _, _, grant, key, _ = setup
    master.channel.onebot_self_id = 'official-self'
    master.channel.save()
    row = OneBotMessage.objects.create(bot=master, message_id='own-message', target_id='old-group',
        conversation_type='group', is_direct=False, sender_id='', incoming=False, sent_at=100,
        segments=[{'type': 'text', 'data': {'text': 'old sent message'}}])
    restrict(key, grant)
    result = invoke(master, [], 'get_msg', {'message_id': virtual_id(master, 'message', row.message_id)}, key=key).data
    assert result['retcode'] == 0, result
    row.refresh_from_db()
    assert row.sender_id == 'official-self'
    assert original_id(master, 'user', result['data']['sender']['user_id']) == 'official-self'
    assert result['data']['group_id'] == virtual_id(master, 'group', 'old-group')
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"official-self","username":"Official"}', {})):
        result = invoke(master, [], 'get_stranger_info', {'user_id': 0}, key=key).data
    assert result['retcode'] == 0 and result['data']['nickname'] == 'Official'
    assert result['data']['user_id'] != 0


def test_cache_miss_get_msg_fetches_companion_without_quote_anchor_then_caches(setup):
    master, slave, _, grant, key, _ = setup
    if onebot_version(slave) != 11:
        return
    add_mapping(setup)
    restrict(key, grant)
    remote = {'message_id': 441239540, 'message_type': 'group', 'group_id': 20002,
        'sender': {'user_id': 30003}, 'time': 100,
        'message': [{'type': 'text', 'data': {'text': 'quoted content'}}]}
    with patch('core.onebot_upstream.call', return_value=remote) as call:
        result = invoke(master, [], 'get_msg', {'message_id': 441239540}, key=key).data
    assert result['retcode'] == 0, result
    assert result['data']['sender']['user_id'] == 30003
    assert result['data']['group_id'] == 20002
    call.assert_called_once()
    with patch('core.onebot_upstream.call') as call:
        assert invoke(master, [], 'get_msg', {'message_id': 441239540}, key=key).data['retcode'] == 0
        call.assert_not_called()
    key.revoked_at = timezone.now(); key.save()
    assert invoke(master, [], 'get_msg', {'message_id': 441239540}, key=key).data['retcode'] == 1403


def test_old_unpaired_observations_upgrade_user_and_message_ids(setup):
    master, slave, _, _, key, _ = setup
    add_mapping(setup)
    # Simulate an older version that saved both observations with incompatible
    # metadata fingerprints, then already published both sides without pairing.
    with patch('core.companions.reconcile', return_value=False):
        ingest_event(master, primary_message(mid='official-old'))
        receive_event(slave, slave_message(slave))
    CompanionObservation.objects.filter(channel=master.channel, side='primary').update(
        fingerprint='a' * 64, published=True)
    CompanionObservation.objects.filter(channel=master.channel, side='companion').update(fingerprint='b' * 64)
    assert not real_for_original(master, 'user', 'openid-user')
    backfill_id_evidence(master.channel, limit=1)
    assert real_for_original(master, 'user', 'openid-user') == '30003'
    assert virtual_id(master, 'message', 'official-old') == 40004
    assert not CompanionObservation.objects.filter(channel=master.channel, paired=False).exists()


@pytest.mark.parametrize('cache', [0, 1, '0', '1', False])
def test_koishi_image_options_are_ignored_before_official_upload(setup, cache):
    master, _, _, _, key, _ = setup
    gid = virtual_id(master, 'group', 'openid-group')
    with patch('core.onebot.download', return_value=b'synthetic-image') as download, patch(
            'core.onebot.upload_media', return_value=(200, b'{"file_info":"uploaded"}', {})), patch(
            'core.onebot.send_message', return_value=(200, b'{"id":"image-sent"}', {})) as send:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': gid, 'message': [
            {'type': 'image', 'data': {'file': 'https://cdn.example.org/img.png', 'cache': cache, 'proxy': 0, 'timeout': 60}}]}, key=key).data
    assert result['retcode'] == 0, result
    download.assert_called_once_with('https://cdn.example.org/img.png')
    assert json.loads(send.call_args.args[2])['media'] == {'file_info': 'uploaded'}


def test_unconvertible_segments_do_not_block_convertible_official_text(setup):
    master, _, _, _, key, _ = setup
    gid = virtual_id(master, 'group', 'openid-group')
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"text-sent"}', {})) as send:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': gid, 'message': [
            {'type': 'reply', 'data': {'id': '123456'}},
            {'type': 'at', 'data': {'qq': '88888'}},
            {'type': 'face', 'data': {'id': '123'}},
            {'type': 'unknown', 'data': {'anything': 'unsupported'}},
            {'type': 'text', 'data': {'text': 'still sent'}}]}, key=key).data
    assert result['retcode'] == 0, result
    assert json.loads(send.call_args.args[2]) == {'content': 'still sent', 'msg_type': 0}


def test_all_unconvertible_segments_are_a_silent_noop(setup):
    master, _, _, _, key, _ = setup
    gid = virtual_id(master, 'group', 'openid-group')
    with patch('core.onebot.send_message') as send:
        result = invoke(master, key.scopes, 'send_group_msg', {'group_id': gid,
            'message': [{'type': 'reply', 'data': {'id': '99999'}},
                        {'type': 'face', 'data': {'id': '1'}}]}, key=key).data
    assert result['retcode'] == 0 and result['data'] is None
    send.assert_not_called()


@pytest.mark.parametrize('version', [11, 12])
def test_http_and_ws_profile_queries_work_with_zero_scopes_and_revoke_immediately(setup, version):
    from rest_framework.test import APIClient
    from .onebot_socket import call_action
    master, _, _, grant, key, token = setup
    learn_real_id(master, 'user', 'member-openid', '30003')
    restrict(key, grant)
    uid = 30003 if version == 11 else 'member-openid'
    envelope = {'action': 'get_stranger_info' if version == 11 else 'get_user_info',
                'params': {'user_id': uid}}
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.onebot_upstream.identity', return_value=({'platform': 'qq', 'user_id': '10001'}, 'slave')), patch(
            'core.onebot_upstream.call', return_value={'user_id': 30003, 'nickname': 'Member'}):
        response = client.post('/onebot/get_stranger_info' if version == 11 else '/onebot/v12/',
            envelope['params'] if version == 11 else envelope, format='json')
        assert response.status_code == 200 and response.json()['retcode'] == 0, response.content
        assert call_action(token, envelope, version)['retcode'] == 0
    key.revoked_at = timezone.now(); key.save()
    assert client.post('/onebot/get_stranger_info', {'user_id': 30003}, format='json').status_code in {401, 403}
