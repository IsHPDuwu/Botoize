"""Protocol conformance, current QQ mappings and isolation (no real QQ side effects)."""
import asyncio
import base64
import hashlib
import json
import time
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .conversations import configure_policy
from .events import ingest_event
from .models import Bot, BotGrant, Conversation, EventOutbox, OneBotFile, OneBotMessage, User
from .onebot import invoke
from .onebot_connect import universal_socket
from .onebot_ids import virtual_id
from .onebot_peer import acquire_peer, release_peer, renew_peer
from .onebot_reverse import quick_operations, webhook_batch
from .services import SCOPES, issue_key
from .websocket import read_onebot_page

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    user = User.objects.create_user('ob12')
    bot = Bot.objects.create(name='OneBot12', app_id='ob12', encrypted_secret='unused')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=sorted(SCOPES))
    conversation = Conversation.objects.create(bot=bot, is_direct=False, target_id='group', name='Known')
    key, token = issue_key(user, bot, 'ob12', sorted(SCOPES))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return user, bot, grant, conversation, key, token, client


def action(setup, name, params=None, version=12, **kwargs):
    _, bot, _, _, key, _, _ = setup
    return invoke(bot, key.scopes, name, params or {}, key=key, version=version, **kwargs).data


def inbound(event_id='dispatch', group='group', attachments=None, **extra):
    return {'op': 0, 'id': event_id, 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {
        'id': 'ROBOT1.0_' + event_id, 'group_openid': group, 'content': 'hello',
        'author': {'member_openid': 'member', 'username': 'name'}, 'timestamp': timezone.now().isoformat(),
        'message_scene': {'ext': ['msg_idx=REFIDX_' + event_id + '==', 'auth_token=DO_NOT_FORWARD']},
        **({'attachments': attachments} if attachments else {}), **extra,
    }}


@pytest.mark.parametrize('name', ['get_version', 'get_supported_actions', 'botoize.get_capabilities'])
def test_meta_and_discovery(setup, name):
    response = action(setup, name, echo='echo')
    assert response['retcode'] == 0 and response['echo'] == 'echo'
    if name == 'get_supported_actions':
        with patch('core.onebot.get_self', return_value=(200, b'{"id":"self"}', {})):
            for supported in response['data']:
                assert action(setup, supported)['retcode'] != 10002


def test_http_envelope_and_auth(setup):
    client = setup[-1]
    response = client.post('/onebot/v12/', {'action': 'get_version', 'params': {}, 'echo': 'a'}, format='json')
    assert response.status_code == 200 and response.json()['data']['onebot_version'] == '12'
    assert response.json()['echo'] == 'a' and response['Cache-Control'] == 'no-store'
    for data, code in [({'action': 'get_version'}, 10001), ({'action': 'get_version', 'params': {}, 'echo': 1}, 10001),
                       ({'action': 'not_real', 'params': {}}, 10002), ({'action': 'get_version', 'params': {'invalid': 1}}, 10004)]:
        response = client.post('/onebot/v12/', data, format='json')
        assert response.status_code == 200 and response.json()['retcode'] == code
    assert client.post('/onebot/v12/', '{', content_type='application/json').json()['retcode'] == 10001
    assert client.post('/onebot/v12/', 'text', content_type='text/plain').status_code == 415
    assert client.get('/onebot/v12/').status_code == 405
    anon = APIClient()
    assert anon.post('/onebot/v12/', {'action': 'get_version', 'params': {}}, format='json').status_code == 401
    assert anon.post('/onebot/v12/?access_token=' + setup[-2], {'action': 'get_version', 'params': {}}, format='json').status_code == 200
    anon.credentials(HTTP_AUTHORIZATION='Bearer wrong')
    assert anon.post('/onebot/v12/?access_token=' + setup[-2], {'action': 'get_version', 'params': {}}, format='json').status_code == 401


def test_original_ids_and_self(setup):
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"000original","username":"display"}', {})):
        assert action(setup, 'get_self_info')['data']['user_id'] == '000original'
        assert action(setup, 'get_self_info', self_info={'platform': 'qq', 'user_id': 'other'})['retcode'] == 10102
        assert action(setup, 'get_login_info', version=11)['data']['user_id'] == virtual_id(setup[1], 'user', '000original')
    params = {'detail_type': 'group', 'group_id': '000group', 'message': [{'type': 'text', 'data': {'text': 'text'}}]}
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"ROBOT1.0_real=="}', {})) as send:
        response = action(setup, 'send_message', params)
        assert response['data']['message_id'] == 'ROBOT1.0_real==' and isinstance(response['data']['time'], float)
        assert send.call_args.args[1] == 'v2/groups/000group/messages'
    assert action(setup, 'send_message', {**params, 'group_id': 12})['retcode'] == 10003
    assert action(setup, 'send_message', {**params, 'message': 'not an array'})['retcode'] == 10003


@pytest.mark.parametrize('segment,file_type', [('image', 1), ('video', 2), ('voice', 3), ('file', 4)])
def test_media_both_versions(setup, segment, file_type):
    upload = action(setup, 'upload_file', {'type': 'data', 'name': 'a.bin', 'data': base64.b64encode(b'file').decode()})
    file_id = upload['data']['file_id']
    with patch('core.onebot.upload_media', return_value=(200, b'{"file_info":"opaque"}', {})) as media, patch(
        'core.onebot.send_message', return_value=(200, b'{"id":"media"}', {})) as send:
        response = action(setup, 'send_message', {'detail_type': 'group', 'group_id': 'group',
            'message': [{'type': segment, 'data': {'file_id': file_id}}]})
        assert response['retcode'] == 0
        assert json.loads(media.call_args.args[2])['file_type'] == file_type
        assert json.loads(media.call_args.args[2])['srv_send_msg'] is False
        assert json.loads(send.call_args.args[2])['media']['file_info'] == 'opaque'
        kind = {'voice': 'record', 'file': 'botoize.file'}.get(segment, segment)
        group = virtual_id(setup[1], 'group', 'group')
        assert action(setup, 'send_group_msg', {'group_id': group, 'message': [{'type': kind, 'data': {'file': file_id}}]}, version=11)['retcode'] == 0


def test_unsupported_compositions_no_side_effects(setup):
    with patch('core.onebot.send_message') as send, patch('core.onebot.upload_media') as upload:
        for segments, code in [([{'type': 'mention', 'data': {'user_id': 'u'}}], 10005),
            ([{'type': 'text', 'data': {'text': 1}}], 10006),
            ([{'type': 'image', 'data': {'file_id': 'x'}}, {'type': 'video', 'data': {'file_id': 'y'}}], 10007),
            ([{'type': 'image', 'data': {'file_id': 'x'}}, {'type': 'unknown', 'data': {}}], 10005)]:
            assert action(setup, 'send_message', {'detail_type': 'group', 'group_id': 'group', 'message': segments})['retcode'] == code
        send.assert_not_called()
        upload.assert_not_called()


def test_file_roundtrip_fragments_isolation_and_integrity(setup):
    raw, digest = b'abcdef', hashlib.sha256(b'abcdef').hexdigest()
    fid = action(setup, 'upload_file_fragmented', {'stage': 'prepare', 'name': 'a.bin', 'total_size': 6})['data']['file_id']
    for offset, value in [(3, b'def'), (0, b'abc'), (0, b'abc')]:
        assert action(setup, 'upload_file_fragmented', {'stage': 'transfer', 'file_id': fid, 'offset': offset,
            'data': base64.b64encode(value).decode()})['retcode'] == 0
    assert action(setup, 'upload_file_fragmented', {'stage': 'transfer', 'file_id': fid, 'offset': 2, 'data': 'eA=='})['retcode'] == 10003
    assert action(setup, 'upload_file_fragmented', {'stage': 'finish', 'file_id': fid, 'sha256': digest})['retcode'] == 0
    assert action(setup, 'get_file', {'file_id': fid, 'type': 'data'})['data']['data'] == base64.b64encode(raw).decode()
    assert action(setup, 'get_file_fragmented', {'stage': 'prepare', 'file_id': fid})['data']['sha256'] == digest
    assert action(setup, 'get_file_fragmented', {'stage': 'transfer', 'file_id': fid, 'offset': 1, 'size': 2})['data']['data'] == 'YmM='
    assert action(setup, 'upload_file', {'type': 'path', 'name': 'secret', 'path': 'config.txt'})['retcode'] == 10004
    assert action(setup, 'get_file', {'file_id': fid, 'type': 'path'})['retcode'] == 10004
    other, _ = issue_key(setup[0], setup[1], 'other', sorted(SCOPES))
    assert invoke(setup[1], other.scopes, 'get_file', {'file_id': fid, 'type': 'data'}, key=other, version=12).data['retcode'] == 35004
    assert action(setup, 'upload_file', {'type': 'data', 'name': 'bad', 'data': '!!!'})['retcode'] == 10003
    assert action(setup, 'upload_file', {'type': 'data', 'name': '../bad', 'data': ''})['retcode'] == 10003


def test_file_ssrf_and_headers(setup):
    from .onebot_files import destination, download
    from .onebot_common import OneBotError
    from .delivery import UnsafeDestination
    for url in ['file:///config.txt', 'https://u:p@example.com/a', 'https://example.com:444/a', 'https://example.com/#x']:
        with pytest.raises(OneBotError):
            destination(url)
    with patch('core.onebot_files.resolve_public', side_effect=UnsafeDestination()):
        assert action(setup, 'upload_file', {'type': 'url', 'url': 'http://127.0.0.1/a', 'name': 'a'})['retcode'] == 10003
    with patch('core.onebot_files.resolve_public', return_value='1.1.1.1'):
        with pytest.raises(OneBotError):
            download('https://example.com/a', {'Host': 'localhost'})


def test_event_media_reply_recall_and_scope(setup):
    _, bot, grant, conversation, key, token, _ = setup
    event, _ = ingest_event(bot, inbound(attachments=[{'content_type': 'voice', 'url': 'https://example.com/voice', 'filename': 'v.silk'}]))
    output = read_onebot_page(token, 0, 'self', version=12)[0]['payload']
    assert output['self']['user_id'] == 'self' and output['message_id'] == 'ROBOT1.0_dispatch'
    assert output['message'][1]['type'] == 'voice' and 'DO_NOT_FORWARD' not in json.dumps(output)
    fid = output['message'][1]['data']['file_id']
    assert OneBotFile.objects.get(pk=fid).target_id == 'group'
    params = {'detail_type': 'group', 'group_id': 'group', 'qq.reply_to': output['message_id'],
              'message': [{'type': 'reply', 'data': {'message_id': output['message_id']}}, {'type': 'text', 'data': {'text': 'reply'}}]}
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"ROBOT1.0_sent"}', {})) as send:
        assert action(setup, 'send_message', params)['retcode'] == 0
        payload = json.loads(send.call_args.args[2])
        assert payload['message_reference']['message_id'] == 'REFIDX_dispatch=='
        assert payload['msg_seq'] == 1 and payload['msg_id'] == output['message_id']
    with patch('core.onebot.delete_message', return_value=(204, b'', {})) as delete:
        assert action(setup, 'delete_message', {'message_id': 'ROBOT1.0_sent'})['retcode'] == 0
        assert action(setup, 'delete_message', {'message_id': 'ROBOT1.0_sent'})['retcode'] == 0
        assert delete.call_count == 1
        assert action(setup, 'delete_message', {'message_id': output['message_id']})['retcode'] == 10004
    configure_policy(key, {'all_conversations': False, 'conversations': []})
    assert action(setup, 'get_file', {'file_id': fid, 'type': 'url'})['retcode'] == 35003
    assert action(setup, 'delete_message', {'message_id': 'ROBOT1.0_sent'})['retcode'] == 35003
    assert read_onebot_page(token, 0, 'self', version=12) == []


def test_event_grant_revision_history_and_poll_dedup(setup):
    _, bot, grant, _, key, token, _ = setup
    ingest_event(bot, inbound('first'))
    ingest_event(bot, inbound('second'))
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"self"}', {})):
        first = action(setup, 'get_latest_events', {'limit': 1})
        second = action(setup, 'get_latest_events', {'limit': 1})
        assert first['data'][0]['id'] != second['data'][0]['id']
        assert action(setup, 'get_latest_events')['data'] == []
    assert len(read_onebot_page(token, 0, 'self', version=12)) == 2  # WS cursor is independent.
    grant.revision += 1
    grant.save()
    _, renewed = issue_key(setup[0], bot, 'renewed', sorted(SCOPES))
    assert read_onebot_page(renewed, 0, 'self', version=12) == []


@pytest.mark.parametrize('version', [11, 12])
def test_group_info_members_and_mutations_are_mapped_not_executed_live(setup, version):
    bot, gid, uid = setup[1], 'group', 'member'
    if version == 11:
        gid, uid = virtual_id(bot, 'group', gid), virtual_id(bot, 'user', uid)
    with patch('core.onebot_groups._request', return_value=(200, b'{"group_name":"real","group_member_num":7}', {})):
        assert action(setup, 'get_group_info', {'group_id': gid}, version=version)['data']['group_name'] == 'real'
    with patch('core.onebot_groups._request', side_effect=[
        (200, b'{"members":[{"member_openid":"m1","username":"a"}],"next_cursor":"next"}', {}),
        (200, b'{"members":[{"member_openid":"m2","username":"b"}],"next_cursor":""}', {}),
    ]) as upstream:
        response = action(setup, 'get_group_member_list', {'group_id': gid}, version=version)
        assert response['retcode'] == 0 and len(response['data']) == 2
        assert upstream.call_args.args[-1] == 'cursor=next'
    prefix = 'qq.' if version == 12 else ''
    with patch('core.onebot_groups._request', return_value=(200, b'{}', {})) as upstream:
        assert action(setup, prefix + 'set_group_ban', {'group_id': gid, 'user_id': uid, 'duration': 0}, version=version)['retcode'] == 0
        payload = json.loads(upstream.call_args.kwargs['body'])
        assert payload == {'members': [{'op': 'del', 'member_openid': 'member', 'mute_expire_at': ''}]}
    with patch('core.onebot_groups._request', return_value=(200, b'{"remove_members_result":"success"}', {})) as upstream:
        assert action(setup, prefix + 'set_group_kick', {'group_id': gid, 'user_id': uid}, version=version)['retcode'] == 0
        assert json.loads(upstream.call_args.kwargs['body'])['member_openids'] == ['member']


def test_standard_notices_requests_and_approval(setup):
    bot, token = setup[1], setup[-2]
    for index, (kind, data) in enumerate([
        ('FRIEND_ADD', {'openid': 'friend'}), ('GROUP_MEMBER_ADD', {'group_openid': 'group', 'member_openid': 'member'}),
        ('GROUP_JOIN_REQUEST', {'group_openid': 'group', 'member_openid': 'member', 'join_request_id': 'real-request',
                                'verify_info': {'verify_message': 'comment'}}),
    ]):
        ingest_event(bot, {'op': 0, 'id': 'notice' + str(index), 't': kind, 'd': {'timestamp': int(time.time()), **data}})
    rows = read_onebot_page(token, 0, 'self', version=12)
    assert [r['payload']['detail_type'] for r in rows] == ['friend_increase', 'group_member_increase', 'qq.group_join']
    assert rows[1]['payload']['operator_id'] == ''
    flag = rows[-1]['payload']['flag']
    with patch('core.onebot_groups._request', return_value=(200, b'{}', {})) as upstream:
        assert action(setup, 'qq.set_group_add_request', {'flag': flag, 'approve': False, 'reason': 'reason'})['retcode'] == 0
        payload = json.loads(upstream.call_args.kwargs['body'])
        assert payload['join_request_id'] == 'real-request' and payload['op'] == 'decline'
    configure_policy(setup[4], {'all_conversations': False, 'conversations': []})
    assert action(setup, 'qq.set_group_add_request', {'flag': flag})['retcode'] == 35003
    assert read_onebot_page(token, 0, 'self', version=12) == []


def test_guild_channel_scope_and_mapping(setup):
    with patch('core.onebot_guilds._request', return_value=(200, b'{"id":"channel","guild_id":"guild","name":"name"}', {})):
        assert action(setup, 'get_channel_info', {'guild_id': 'guild', 'channel_id': 'channel'})['data']['channel_name'] == 'name'
        with patch('core.onebot.send_message', return_value=(200, b'{"id":"channel-message"}', {})) as send:
            response = action(setup, 'send_message', {'detail_type': 'channel', 'guild_id': 'guild', 'channel_id': 'channel',
                              'message': [{'type': 'mention', 'data': {'user_id': 'user'}}, {'type': 'text', 'data': {'text': 'hi'}}]})
            assert response['retcode'] == 0 and json.loads(send.call_args.args[2])['content'] == '<@user>hi'
    configure_policy(setup[4], {'all_conversations': False, 'conversations': [setup[3].pk]})
    with patch('core.onebot_guilds._request') as upstream:
        assert action(setup, 'get_channel_info', {'guild_id': 'guild', 'channel_id': 'channel'})['retcode'] == 35003
        upstream.assert_not_called()


def test_webhook_cursor_ack_before_quick_actions_and_live_revoke(setup):
    peer = acquire_peer(setup[-2], 12, 'http-webhook', 'https://receiver.example/events')
    ingest_event(setup[1], inbound())
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"self"}', {})), patch(
            'core.onebot_reverse.post_webhook', return_value=[{'action': 'get_version', 'params': {}}]) as post:
        assert webhook_batch(peer, setup[-2], 'https://receiver.example/events', 12) == (1, 0)
        assert webhook_batch(peer, setup[-2], 'https://receiver.example/events', 12) == (0, 0)
        assert post.call_count == 1
    setup[4].revoked_at = timezone.now()
    setup[4].save()
    from rest_framework.exceptions import APIException
    with pytest.raises(APIException):
        renew_peer(peer, setup[-2])
    release_peer(peer)


@pytest.mark.django_db(transaction=True)
def test_universal_v12_connect_action_error_and_disconnect():
    async def run():
        queue, messages = asyncio.Queue(), []
        for frame in [{'type': 'websocket.connect'}, {'type': 'websocket.receive', 'text': '{'},
                      {'type': 'websocket.receive', 'text': '{"action":"get_version","params":{},"echo":"e"}'},
                      {'type': 'websocket.disconnect'}]:
            queue.put_nowait(frame)
        async def send(message):
            messages.append(message)
        with patch('core.onebot_connect.check_token', new=lambda token: None), patch('core.onebot_connect.probe_status', return_value={'good': True, 'bots': []}), patch('core.onebot_connect.connection_info', new=lambda token, version: ('self', 0, False, 'qq')), patch(
                'core.onebot_connect.call_action', return_value={'status': 'ok', 'retcode': 0, 'data': {}, 'echo': 'e'}):
            await universal_socket({'path': '/onebot/v12/', 'headers': [(b'authorization', b'Bearer test')], 'query_string': b''}, queue.get, send)
        payloads = [json.loads(m['text']) for m in messages if m['type'] == 'websocket.send']
        assert payloads, messages
        assert payloads[0]['detail_type'] == 'connect' and payloads[0]['version']['onebot_version'] == '12'
        assert payloads[1]['detail_type'] == 'status_update'
        assert payloads[2]['retcode'] == 10001 and payloads[3]['echo'] == 'e'
    asyncio.run(run())
