import json
from unittest.mock import patch

import pytest

from .onebot import invoke


def test_onebot_login_info():
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"openid","username":"bot"}', {})):
        data = invoke(None, ['query:read'], 'get_login_info', {}, 'echo-value').data
    assert data['data'] == {'user_id': 'openid', 'nickname': 'bot'}
    assert data['echo'] == 'echo-value' and data['retcode'] == 0


@pytest.mark.parametrize('action,key,kind', [('send_private_msg', 'user_id', 'users'), ('send_group_msg', 'group_id', 'groups')])
def test_onebot_text_send(action, key, kind):
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"message-id"}', {})) as send:
        data = invoke(None, ['messages:send'], action, {key: 'official-openid', 'message': 'hello', 'msg_id': 'reply', 'msg_seq': 2}).data
    assert data['data']['message_id'] == 'message-id'
    assert send.call_args.args[1] == f'v2/{kind}/official-openid/messages'
    assert json.loads(send.call_args.args[2])['msg_seq'] == 2


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
    assert invoke(None, [], 'delete_msg', {}).data['retcode'] == 1404
    assert invoke(None, [], [], {}).data['retcode'] == 1404