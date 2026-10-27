"""Upstream Provider integration; all remote side effects use local synthetic peers."""
import base64
import hashlib
import hmac
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from websockets.sync.server import serve

from .models import Bot, BotGrant, Channel, Conversation, Event, OneBotMessage, Provider, User
from .onebot import invoke, public_id
from .onebot_common import OneBotError
from .onebot_upstream import call, configuration_digest, identity
from .onebot_upstream_events import receive_event
from .onebot_upstream_worker import claim, consume, event_url, renew, release, LeaseLost
from .services import encrypt_secret, issue_key, SCOPES
from .websocket import read_onebot_page

pytestmark = pytest.mark.django_db


def make_bot(version=11, url='http://127.0.0.1:3000'):
    provider = Provider.objects.create(name='Synthetic upstream')
    channel = Channel.objects.create(provider=provider, name='Synthetic Bot', base_url=url,
        interface_type=f'onebot_v{version}', encrypted_event_secret=encrypt_secret('event-only'))
    return Bot.objects.create(channel=channel, name='Synthetic', app_id='10001' if version == 11 else 'self:001',
                              encrypted_secret=encrypt_secret('upstream-only'))


@pytest.fixture(params=[11, 12])
def setup(request):
    bot = make_bot(request.param)
    user = User.objects.create_user('upstream-user')
    grant = BotGrant.objects.create(bot=bot, user=user, scopes=sorted(SCOPES))
    key, token = issue_key(user, bot, 'synthetic-key', sorted(SCOPES))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return bot, user, grant, key, token, client


def event_for(bot, target=None, message_id=None, **extra):
    version = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    if version == 11:
        return {'time': 1700000000, 'self_id': int(bot.app_id), 'post_type': 'message',
                'message_type': 'group', 'sub_type': 'normal', 'message_id': message_id or 91,
                'group_id': target or 20002, 'user_id': 30003,
                'message': [{'type': 'text', 'data': {'text': 'synthetic inbound'}}], **extra}
    return {'id': 'event:' + str(message_id or 'msg:001'), 'time': 1700000000.25,
            'self': {'platform': 'test-platform', 'user_id': bot.app_id}, 'type': 'message',
            'detail_type': 'group', 'sub_type': '', 'message_id': message_id or 'msg:001',
            'group_id': target or 'group:0002', 'user_id': 'user:0003',
            'message': [{'type': 'text', 'data': {'text': 'synthetic inbound'}}], **extra}


@contextmanager
def upstream_server(bot, websocket=False):
    version = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    seen = []
    def respond(action, params, echo=None):
        own = {'platform': 'test-platform', 'user_id': bot.app_id}
        data = {'get_login_info': {'user_id': int(bot.app_id) if version == 11 else 0, 'nickname': 'Synthetic'},
                'get_status': {'good': True, 'online': True} if version == 11 else {'good': True, 'bots': [{'self': own, 'online': True}]},
                'get_self_info': {'user_id': bot.app_id, 'user_name': 'Synthetic'},
                'send_group_msg': {'message_id': 92}, 'send_private_msg': {'message_id': 93},
                'send_message': {'message_id': 'sent:0002', 'time': 1700000001.5},
                'get_file': {'name': 'test.bin', 'data': base64.b64encode(b'synthetic bytes').decode()},
                'upload_file': {'file_id': 'remote:file'},
                'get_group_list': [{'group_id': 20002 if version == 11 else 'group:0002', 'group_name': 'Allowed'},
                                   {'group_id': 99999 if version == 11 else 'other:9999', 'group_name': 'Hidden'}],
                'get_user_info': {'user_id': 'user:0003', 'user_name': 'Member'},
                'get_stranger_info': {'user_id': 30003, 'nickname': 'Member'},
                'get_supported_actions': ['get_status', 'get_self_info', 'send_message', 'get_group_list', 'get_user_info', 'get_file', 'upload_file', 'delete_message'],
                'get_group_info': {'group_id': 20002 if version == 11 else 'group:0002', 'group_name': 'Allowed'},
                'can_send_image': {'yes': True}, 'can_send_record': {'yes': True}}
        return {'status': 'ok', 'retcode': 0, 'data': data.get(action), **({'echo': echo} if echo is not None else {})}
    if websocket:
        def handler(ws):
            assert ws.request.headers['Authorization'] == 'Bearer upstream-only'
            for raw in ws:
                envelope = json.loads(raw)
                seen.append(envelope)
                # Event frames and unrelated responses must not satisfy an action wait.
                ws.send(json.dumps({'type': 'meta', 'detail_type': 'heartbeat'}))
                ws.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': {}, 'echo': 'unrelated'}))
                ws.send(json.dumps(respond(envelope['action'], envelope['params'], envelope['echo'])))
        server = serve(handler, '127.0.0.1', 0)
        endpoint = f'ws://127.0.0.1:{server.socket.getsockname()[1]}'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
    else:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                assert self.headers['Authorization'] == 'Bearer upstream-only'
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                action = self.path.rsplit('/', 1)[-1] if version == 11 else value['action']
                params = value if version == 11 else value['params']
                if version == 12 and action not in {'get_status', 'get_supported_actions'}:
                    assert value['self'] == {'platform': 'test-platform', 'user_id': bot.app_id}
                seen.append({'action': action, 'params': params, 'path': self.path, 'self': value.get('self')})
                raw = json.dumps(respond(action, params, value.get('echo') if version == 12 else None)).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        endpoint = f'http://127.0.0.1:{server.server_port}/prefix'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
    bot.channel.base_url = endpoint
    bot.channel.save(update_fields=['base_url'])
    thread.start()
    try:
        with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True):
            yield seen
    finally:
        server.shutdown()
        if not websocket:
            server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('scheme', ['http', 'https', 'ws', 'wss'])
def test_local_endpoint_accepts_supported_transports_when_enabled(scheme):
    from .upstreams import validate_onebot_url
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True):
        assert validate_onebot_url(f'{scheme}://127.0.0.1:3000/') == f'{scheme}://127.0.0.1:3000'


@pytest.mark.parametrize('url,expected', [
    ('127.0.0.1:3000', '开头'),
    ('ws://127.0.0.1:99999', '端口'),
    ('ws://127.0.0.1:3000/?access_token=never-echo-this-secret', 'Access Token'),
    ('http://user:never-echo-this-secret@127.0.0.1:3000', 'Access Token'),
    ('ws://127.0.0.1:0', '端口 0'),
])
def test_endpoint_validation_explains_problem_without_echoing_credentials(url, expected):
    from .upstreams import validate_onebot_url
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True), pytest.raises(ValueError) as error:
        validate_onebot_url(url)
    assert expected in str(error.value)
    assert 'never-echo-this-secret' not in str(error.value)


def test_endpoint_validation_explains_private_transport_opt_in():
    from .upstreams import validate_onebot_url
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=False), pytest.raises(ValueError, match='ONEBOT_UPSTREAM_ALLOW_PRIVATE=1'):
        validate_onebot_url('ws://127.0.0.1:3000')


@pytest.mark.parametrize('transport', ['http', 'websocket'])
def test_real_wire_send_and_identity(setup, transport):
    bot, _, _, key, _, client = setup
    source = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    target = 20002 if source == 11 else 'group:0002'
    with upstream_server(bot, websocket=transport == 'websocket') as seen, patch('core.official.access_token', side_effect=AssertionError('QQ called')):
        own, name = identity(bot)
        assert own['user_id'] == bot.app_id and name == 'Synthetic'
        if source == 11:
            response = client.post('/onebot/v11/send_group_msg', {'group_id': target, 'message': '[CQ:at,qq=30003] hello'}, format='json')
        else:
            response = client.post('/onebot/v12/', {'action': 'send_message', 'params': {'detail_type': 'group', 'group_id': target,
                'message': [{'type': 'text', 'data': {'text': 'hello'}}]}, 'echo': 'test'}, format='json')
        assert response.status_code == 200 and response.json()['retcode'] == 0, response.content
        sent = next(item for item in seen if item['action'] in {'send_group_msg', 'send_message'})
        assert sent['params']['group_id'] == target
        assert response.json()['data']['message_id'] == (92 if source == 11 else 'sent:0002')
        if source == 11:
            assert sent['params']['message'][0] == {'type': 'at', 'data': {'qq': '30003'}}
        mid = response.json()['data']['message_id']
        action = 'delete_msg' if source == 11 else 'delete_message'
        assert invoke(bot, key.scopes, action, {'message_id': mid}, key=key, version=source).data['retcode'] == 0
        assert OneBotMessage.objects.get(bot=bot).deleted


def test_provider_creation_rotation_and_redaction():
    owner = User.objects.create_user('owner', role='Owner')
    client = APIClient()
    client.force_login(owner)
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True):
        for version in (11, 12):
            data = {'name': f'provider-{version}', 'channels': [{'name': 'Bot', 'app_id': '123' if version == 11 else 'bot:/001',
                    'base_url': 'ws://127.0.0.1:3001', 'interface_type': f'onebot_v{version}', 'is_active': True,
                    'event_secret': 'private-event', 'models': [{'name': 'group', 'isDirect': False, 'groupid': '456' if version == 11 else 'group:/001'}]}]}
            response = client.post('/api/v1/providers/', data, format='json')
            assert response.status_code == 201, response.content
            result = response.json()
            assert result['channels'][0]['event_reporting_enabled'] is True
            assert 'private-event' not in response.content.decode()
            data = {'name': result['name'], 'channels': result['channels']}
            response = client.patch(f'/api/v1/providers/{result["id"]}/', data, format='json')
            assert response.status_code == 200, response.content
            bot = Bot.objects.get(pk=result['channels'][0]['bot_id'])
            grant = BotGrant.objects.create(bot=bot, user=owner, scopes=['query:read'])
            key, _ = issue_key(owner, bot, 'key', ['query:read'])
            data['channels'][0]['secret'] = 'rotated-token'
            data['channels'][0]['event_secret'] = ''
            assert client.patch(f'/api/v1/providers/{result["id"]}/', data, format='json').status_code == 200
            key.refresh_from_db()
            grant.refresh_from_db()
            assert key.revoked_at and grant.revision > 1
            assert not client.get(f'/api/v1/providers/{result["id"]}/').json()['channels'][0]['event_reporting_enabled']


def test_http_reports_dedup_filter_and_message_context(setup):
    bot, _, grant, key, token, client = setup
    payload = event_for(bot)
    target = str(payload['group_id'])
    conversation = Conversation.objects.create(bot=bot, is_direct=False, target_id=target)
    grant.all_conversations = key.all_conversations = False
    grant.save(); key.save()
    grant.conversations.add(conversation); key.conversations.add(conversation)
    raw = json.dumps(payload).encode()
    path = f'/webhooks/onebot/{bot.pk}/'
    headers = ({'HTTP_X_SIGNATURE': 'sha1=' + hmac.new(b'event-only', raw, hashlib.sha1).hexdigest()}
               if bot.channel.interface_type == 'onebot_v11' else {'HTTP_AUTHORIZATION': 'Bearer event-only'})
    anonymous = APIClient()
    assert anonymous.post(path, raw, content_type='application/json').status_code == 401
    assert anonymous.post(path, raw, content_type='application/json', **headers).status_code == 204
    assert anonymous.post(path, raw, content_type='application/json', **headers).status_code == 204
    assert Event.objects.count() == 1
    assert OneBotMessage.objects.get().source_event_id == Event.objects.get().pk
    hidden = event_for(bot, target=9999 if bot.channel.interface_type == 'onebot_v11' else 'hidden', message_id=9999 if bot.channel.interface_type == 'onebot_v11' else 'hidden-id')
    receive_event(bot, hidden)
    for version in (11, 12):
        self_id = public_id(bot, 'user', bot.app_id, version)
        rows = read_onebot_page(token, 0, self_id, version=version)
        assert len(rows) == 1 and rows[0]['payload']['message'][0]['data']['text'] == 'synthetic inbound'
        assert rows[0]['payload']['group_id'] == public_id(bot, 'group', target, version)
    response = client.get('/relay/v1/capabilities/')
    assert response.json()['operations'] == []
    assert client.get('/qq/users/@me').status_code == 501
    with upstream_server(bot), patch('core.onebot_upstream_actions.call') as remote:
        # A different target is denied before any upstream identity, upload or action.
        answer = invoke(bot, key.scopes, 'send_group_msg', {'group_id': public_id(bot, 'group', str(hidden['group_id']), 11), 'message': 'blocked'}, key=key)
        assert answer.data['retcode'] == 1403
        remote.assert_not_called()


def test_cross_version_send_and_media(setup):
    bot, _, _, key, _, _ = setup
    source = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    with upstream_server(bot) as seen:
        if source == 11:
            response = invoke(bot, key.scopes, 'send_message', {'detail_type': 'private', 'user_id': '30003',
                'message': [{'type': 'text', 'data': {'text': 'mixed'}}, {'type': 'image', 'data': {'file_id': invoke(bot, key.scopes, 'upload_file',
                    {'type': 'data', 'name': 'a.png', 'data': base64.b64encode(b'png-bytes').decode()}, key=key, version=12).data['data']['file_id']}}]}, key=key, version=12)
            assert response.data['retcode'] == 0
            sent = next(item for item in seen if item['action'] == 'send_private_msg')
            assert sent['params']['user_id'] == 30003
            assert sent['params']['message'][1]['data']['file'] == 'base64://' + base64.b64encode(b'png-bytes').decode()
        else:
            target = public_id(bot, 'group', 'group:0002', 11)
            response = invoke(bot, key.scopes, 'send_group_msg', {'group_id': target, 'message': '[CQ:image,file=base64://aW1hZ2U=]'}, key=key)
            assert response.data['retcode'] == 0, response.data
            sent = next(item for item in seen if item['action'] == 'send_message')
            assert sent['params']['group_id'] == 'group:0002'
            assert sent['params']['message'][0]['data']['file_id'] == 'remote:file'


def test_event_files_and_source_isolation(setup):
    bot, _, _, key, token, _ = setup
    version = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    with upstream_server(bot):
        payload = event_for(bot, message=[{'type': 'image', 'data': {'file' if version == 11 else 'file_id': 'native-file'}}])
        receive_event(bot, payload)
        output = read_onebot_page(token, 0, bot.app_id, version=12)[0]['payload']
        local_file = output['message'][0]['data']['file_id']
        assert local_file != 'native-file'
        if version == 12:
            data = invoke(bot, key.scopes, 'get_file', {'file_id': local_file, 'type': 'data'}, key=key, version=12).data
            assert base64.b64decode(data['data']['data']) == b'synthetic bytes'
        mid = payload['message_id']
        bot.encrypted_secret = encrypt_secret('new-source')
        bot.save(update_fields=['encrypted_secret'])
        assert invoke(bot, key.scopes, 'get_msg', {'message_id': public_id(bot, 'message', str(mid), 11)}, key=key).data['retcode'] == 1400
        receive_event(bot, payload)
        assert OneBotMessage.objects.filter(bot=bot, message_id=str(mid)).count() == 2


def test_lists_filter_before_exposure(setup):
    bot, _, grant, key, _, _ = setup
    source = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    group = Conversation.objects.create(bot=bot, is_direct=False, target_id='20002' if source == 11 else 'group:0002')
    grant.all_conversations = key.all_conversations = False
    grant.save(); key.save()
    grant.conversations.add(group); key.conversations.add(group)
    with upstream_server(bot):
        response = invoke(bot, key.scopes, 'get_group_list', {}, key=key, version=12)
        assert response.data['retcode'] == 0 and len(response.data['data']) == 1
        assert response.data['data'][0]['group_id'] == group.target_id


def test_worker_fencing_configuration_and_event_urls(setup):
    bot, _, _, _, _, _ = setup
    original_url = event_url(bot)
    assert original_url.startswith('ws://')
    assert original_url.endswith('/event' if bot.channel.interface_type == 'onebot_v11' else '/')
    _, token = claim(bot.pk)
    with pytest.raises(LeaseLost):
        claim(bot.pk)
    renew(bot, token, connected=True)
    receive_event(bot, event_for(bot), lease_token=token)
    release(bot, token)
    _, replacement = claim(bot.pk)
    with pytest.raises(LeaseLost):
        renew(bot, token)
    with pytest.raises(ValueError):
        receive_event(bot, event_for(bot), lease_token=token)
    bot.is_active = False
    bot.save(update_fields=['is_active'])
    with pytest.raises(LeaseLost):
        renew(bot, replacement)


def test_worker_consumes_authenticated_socket_event(setup):
    bot = setup[0]
    payload = event_for(bot)
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def recv(self, timeout):
            if Event.objects.exists():
                raise LeaseLost('test finished')
            return json.dumps(payload)
    _, token = claim(bot.pk)
    own = payload.get('self', {'platform': 'qq', 'user_id': bot.app_id})
    with patch('core.onebot_upstream_worker.identity', return_value=(own, 'name')), patch('core.onebot_upstream_worker.socket_connection', return_value=Socket()):
        with pytest.raises(LeaseLost):
            consume(bot, token)
    assert Event.objects.count() == 1


@pytest.mark.parametrize('url', ['http://127.0.0.1:3000', 'https://127.0.0.1:3000', 'http://example.com', 'ws://localhost:3000'])
def test_private_upstream_requires_explicit_server_optin(url):
    from .upstreams import validate_onebot_url
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=False), pytest.raises(ValueError):
        validate_onebot_url(url)


def test_http_unknown_outcome_never_retries(setup):
    bot = setup[0]
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True), patch('core.onebot_upstream.address_for', return_value='127.0.0.1'), patch(
            'core.onebot_upstream.PinnedConnection') as connection:
        connection.return_value.getresponse.side_effect = TimeoutError
        with pytest.raises(OneBotError) as error:
            call(bot, 'send_message', {})
        assert error.value.code == 33000
        assert connection.return_value.request.call_count == 1


def test_invalid_events_and_rotated_report_secret_are_rejected(setup):
    bot = setup[0]
    for message in [[{'type': 'text', 'data': {'text': {}}}], [{'type': 'image', 'data': {}}], []]:
        with pytest.raises(ValueError):
            receive_event(bot, event_for(bot, message=message))
    assert not Event.objects.exists()
    old_secret = bot.channel.encrypted_event_secret
    Channel.objects.filter(pk=bot.channel_id).update(encrypted_event_secret=encrypt_secret('rotated'))
    with pytest.raises(ValueError):
        receive_event(bot, event_for(bot), event_secret=old_secret)
    assert not Event.objects.exists()


def test_supported_actions_reflect_remote_12(setup):
    bot, _, _, key, _, _ = setup
    if bot.channel.interface_type != 'onebot_v12':
        return
    with upstream_server(bot):
        result = invoke(bot, key.scopes, 'get_supported_actions', {}, key=key, version=12).data
    assert result['retcode'] == 0
    assert 'send_message' in result['data'] and 'get_guild_list' not in result['data']


def test_onebot11_negative_message_ids_and_identity_mismatch():
    bot = make_bot()
    user = User.objects.create_user('negative-id')
    BotGrant.objects.create(user=user, bot=bot, scopes=sorted(SCOPES))
    key, _ = issue_key(user, bot, 'key', sorted(SCOPES))
    receive_event(bot, event_for(bot, message_id=-123))
    result = invoke(bot, key.scopes, 'get_msg', {'message_id': -123}, key=key).data
    assert result['retcode'] == 0 and result['data']['message_id'] == -123
    with patch('core.onebot_upstream.call', return_value={'user_id': 9999, 'nickname': 'wrong'}), pytest.raises(OneBotError):
        identity(bot)


def test_protocol_switch_requires_explicit_replacement_secret():
    bot = make_bot()
    owner = User.objects.create_user('switch-owner', role='Owner')
    client = APIClient()
    client.force_login(owner)
    data = client.get(f'/api/v1/providers/{bot.channel.provider_id}/').json()
    data.pop('id')
    data['channels'][0]['interface_type'] = 'onebot_v12'
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True):
        assert client.patch(f'/api/v1/providers/{bot.channel.provider_id}/', data, format='json').status_code == 400
        data['channels'][0]['clear_secret'] = True
        assert client.patch(f'/api/v1/providers/{bot.channel.provider_id}/', data, format='json').status_code == 200


def test_upstream_dns_and_redirects_cannot_bypass_destination_policy(setup):
    from .onebot_upstream import address_for
    from socket import AF_INET, SOCK_STREAM
    bot = setup[0]
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=False), patch('core.onebot_upstream.socket.getaddrinfo', return_value=[
            (AF_INET, SOCK_STREAM, 6, '', ('127.0.0.1', 443))]), pytest.raises(OneBotError):
        address_for('public.example', 443)
    with override_settings(ONEBOT_UPSTREAM_ALLOW_PRIVATE=True), patch('core.onebot_upstream.address_for', return_value='127.0.0.1'), patch('core.onebot_upstream.PinnedConnection') as connection:
        response = connection.return_value.getresponse.return_value
        response.status, response.read.return_value = 302, b''
        with pytest.raises(OneBotError):
            call(bot, 'get_status')
        assert connection.return_value.request.call_count == 1


def test_onebot_status_is_not_counted_as_official_gateway(setup):
    bot, user, _, _, _, _ = setup
    user.role = 'Owner'
    user.save(update_fields=['role'])
    _, token = claim(bot.pk)
    renew(bot, token, connected=True)
    client = APIClient()
    client.force_login(user)
    data = client.get('/api/v1/dashboard/overview/').json()
    assert data['gateway_worker_count'] == 0
    assert data['channels'][0]['worker_lease_live'] is True
    assert data['channels'][0]['upstream_connected'] is True


def test_denied_scope_does_not_probe_identity_even_with_self(setup):
    bot, _, _, key, _, _ = setup
    with patch('core.onebot_upstream_actions.identity') as remote:
        result = invoke(bot, [], 'send_message', {'detail_type': 'group', 'group_id': '20002',
            'message': [{'type': 'text', 'data': {'text': 'blocked'}}]}, key=key, version=12,
            self_info={'platform': 'qa', 'user_id': bot.app_id}).data
    assert result['retcode'] == 35003
    remote.assert_not_called()


def test_switching_to_qq_does_not_reuse_onebot_message_context(setup):
    from django.utils import timezone
    from .onebot_events import remember_message
    bot = setup[0]
    receive_event(bot, event_for(bot, message_id=91 if bot.channel.interface_type == 'onebot_v11' else '91'))
    bot.channel.interface_type = 'qq_official_webhook'
    bot.channel.save(update_fields=['interface_type'])
    row = remember_message(bot, {'op': 0, 'id': 'qq-native-event', 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {
        'id': '91', 'group_openid': 'official-group', 'author': {'member_openid': 'official-user'},
        'content': 'native context', 'timestamp': timezone.now().isoformat()}})
    assert row.source_digest == '' and row.target_id == 'official-group'
    assert OneBotMessage.objects.filter(bot=bot, message_id='91').count() == 2


def test_ws_status_preserves_upstream_offline_state(setup):
    from .onebot_connect import probe_status
    bot, _, _, _, token, _ = setup
    version = 11 if bot.channel.interface_type == 'onebot_v11' else 12
    own = {'platform': 'qa', 'user_id': bot.app_id}
    status = {'good': False, 'online': False, 'bots': [{'self': own, 'online': False}]}
    with patch('core.onebot_connect.identity', return_value=(own, 'name')), patch('core.onebot_upstream.call', return_value=status):
        result = probe_status(token, 12, bot.app_id, 'qa')
    assert result['good'] is False
    assert result['bots'] == [{'self': own, 'online': False}]
    assert result['botoize.online_basis'] == 'upstream_status'
