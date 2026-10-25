import json
from unittest.mock import patch

import pytest

from .onebot import invoke
from .onebot_ids import original_id, virtual_id

pytestmark = pytest.mark.django_db


@pytest.fixture
def bot():
    from .models import Bot
    return Bot.objects.create(name='onebot', app_id='virtual', encrypted_secret='unused')


def test_onebot_login_info(bot):
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"openid","username":"bot"}', {})):
        data = invoke(bot, ['query:read'], 'get_login_info', {}, 'echo-value').data
    assert data['data'] == {'user_id': virtual_id(bot, 'user', 'openid'), 'nickname': 'bot'}
    assert data['echo'] == 'echo-value' and data['retcode'] == 0


@pytest.mark.parametrize('action,key,kind', [('send_private_msg', 'user_id', 'users'), ('send_group_msg', 'group_id', 'groups')])
def test_onebot_text_send(bot, action, key, kind):
    target = virtual_id(bot, 'user' if key == 'user_id' else 'group', 'official-openid')
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"message-id"}', {})) as send:
        data = invoke(bot, ['messages:send'], action, {key: target, 'message': 'hello'}).data
    assert original_id(bot, 'message', data['data']['message_id']) == 'message-id'
    assert send.call_args.args[1] == f'v2/{kind}/official-openid/messages'
    assert json.loads(send.call_args.args[2]) == {'content': 'hello', 'msg_type': 0}


@pytest.mark.parametrize('params', [
    {'user_id': 123, 'message': 'hi'},
    {'user_id': 'id', 'message': '[CQ:image,file=bad]'},
    {'user_id': 'id', 'message': [{'type': 'text', 'data': {'text': 'hi'}}]},
    {'user_id': 'id', 'message': 'hi', 'msg_seq': True},
])
def test_onebot_rejects_unsupported_message(params):
    with patch('core.onebot.send_message') as send:
        assert invoke(None, ['messages:send'], 'send_private_msg', params).data['retcode'] == 1400
        send.assert_not_called()


def test_onebot_scope_and_unknown_action():
    assert invoke(None, [], 'send_private_msg', {}).data['retcode'] == 1403
    assert invoke(None, [], 'delete_msg', {}).data['retcode'] == 1403
    assert invoke(None, [], 'set_group_ban', {}).data['retcode'] == 1403
    assert invoke(None, [], 'send_like', {}).data['retcode'] == 1404
    assert invoke(None, [], [], {}).data['retcode'] == 1404


def test_virtual_ids_collision_and_isolation(bot):
    from .models import Bot
    from .onebot_ids import MAX_ID
    a = virtual_id(bot, 'user', 'abcdefabcdefa111')
    b = virtual_id(bot, 'user', 'abcdefabcdefa222')
    assert a != b
    assert a == virtual_id(bot, 'user', 'abcdefabcdefa111')
    assert original_id(bot, 'user', str(b)) == 'abcdefabcdefa222'
    other = Bot.objects.create(name='other', app_id='other', encrypted_secret='unused')
    for target, kind, value in [(other, 'user', a), (bot, 'group', a), (bot, 'user', True), (bot, 'user', MAX_ID + 1)]:
        with pytest.raises(ValueError):
            original_id(target, kind, value)
    assert 1 <= virtual_id(bot, 'message', 'not-hex') <= MAX_ID


@pytest.mark.parametrize('message,extra,expected', [
    ('&#91;hello&#93;&amp;', {}, '[hello]&'),
    ('[CQ:literal]', {'auto_escape': True}, '[CQ:literal]'),
    ([{'type': 'text', 'data': {'text': 'hello'}}], {}, 'hello'),
])
def test_standard_text_input(bot, message, extra, expected):
    target = virtual_id(bot, 'user', 'official-openid')
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"sent"}', {})) as send:
        response = invoke(bot, ['messages:send'], 'send_private_msg', {'user_id': target, 'message': message, **extra})
    assert response.data['retcode'] == 0
    assert json.loads(send.call_args.args[2])['content'] == expected


@pytest.fixture
def http_client(db):
    from rest_framework.test import APIClient
    from .models import Bot, BotGrant, User
    from .services import encrypt_secret, issue_key
    user = User.objects.create_user('onebot-http')
    bot = Bot.objects.create(name='test', app_id='http', encrypted_secret=encrypt_secret('secret'))
    BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
    _, token = issue_key(user, bot, 'test', ['query:read'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return client


@pytest.mark.parametrize('method,content_type', [
    ('get', None), ('post', 'application/json'),
    ('post', 'application/x-www-form-urlencoded'),
])
def test_http_action_transport(http_client, method, content_type):
    from rest_framework.response import Response
    with patch('core.onebot.invoke', return_value=Response({'status': 'ok', 'retcode': 0, 'data': {}})) as action:
        if method == 'get':
            response = http_client.get('/onebot/get_login_info/?no_cache=true')
            expected = {'no_cache': 'true'}
        else:
            body = b'{"no_cache":true}' if content_type == 'application/json' else b'no_cache=true'
            response = http_client.post('/onebot/get_login_info', body, content_type=content_type)
            expected = {'no_cache': True} if content_type == 'application/json' else {'no_cache': 'true'}
        assert response.status_code == 200
        assert action.call_args.args[2:] == ('get_login_info', expected)
        assert response['Cache-Control'] == 'no-store'


def test_http_rejects_ws_envelope_and_unknown_action(http_client):
    assert http_client.post('/onebot/', {'action': 'get_login_info'}, format='json').status_code == 404
    assert http_client.get('/onebot/unknown_action').status_code == 404
    assert http_client.post('/onebot/get_login_info', 'text', content_type='text/plain').status_code == 406
    assert http_client.post('/onebot/get_login_info', '[1]', content_type='application/json').status_code == 400
    assert http_client.post('/onebot/get_login_info', '{', content_type='application/json').status_code == 400
