import asyncio
import json
from unittest.mock import patch

import pytest
from rest_framework.exceptions import PermissionDenied

from .onebot_socket import api_socket, call_action


def run_api(frame, check=None):
    async def run():
        queue = asyncio.Queue()
        for message in [{'type': 'websocket.connect'}, frame, {'type': 'websocket.disconnect'}]:
            await queue.put(message)
        messages = []
        async def send(message):
            messages.append(message)
        with patch('core.onebot_socket.check_token', side_effect=check), patch(
            'core.onebot_socket.call_action', side_effect=lambda token, value: {
                'status': 'ok', 'retcode': 0, 'data': {}, 'echo': value.get('echo'),
            },
        ) as call:
            await asyncio.wait_for(api_socket({
                'headers': [(b'authorization', b'Bearer secret')], 'query_string': b'',
            }, queue.get, send), 5)
        return messages, call.call_count
    return asyncio.run(run())


def test_api_echo():
    messages, count = run_api({'type': 'websocket.receive', 'text': json.dumps({
        'action': 'get_login_info', 'params': {}, 'echo': {'request': 12},
    })})
    assert messages[0]['type'] == 'websocket.accept'
    assert json.loads(messages[1]['text'])['echo'] == {'request': 12}
    assert count == 1


@pytest.mark.parametrize('frame,code', [
    ({'type': 'websocket.receive', 'text': '{'}, 4400),
    ({'type': 'websocket.receive', 'text': '[]'}, 4400),
    ({'type': 'websocket.receive', 'bytes': b'bad'}, 4400),
    ({'type': 'websocket.receive', 'text': 'a' * 65537}, 1009),
])
def test_bad_api_frame(frame, code):
    messages, count = run_api(frame)
    assert messages[-1]['code'] == code
    assert count == 0


def test_api_live_revocation():
    messages, count = run_api({'type': 'websocket.receive', 'text': '{"action":"get_login_info"}'},
                               [None, PermissionDenied()])
    assert messages[-1]['code'] == 4403
    assert count == 0


@pytest.mark.django_db
def test_actions_share_quota_and_audit():
    from .models import ApiCallAudit, Bot, BotGrant, QuotaPolicy, User
    from .services import issue_key
    bot = Bot.objects.create(name='ws', app_id='ws', encrypted_secret='unused')
    user = User.objects.create_user('ws-api')
    BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
    _, token = issue_key(user, bot, 'ws', ['query:read'])
    QuotaPolicy.objects.create(scope='bot', subject_id=bot.pk, limit=1)
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"bot","username":"test"}', {})) as upstream:
        assert call_action(token, {'action': 'get_login_info', 'echo': 1})['retcode'] == 0
        response = call_action(token, {'action': 'get_login_info', 'echo': 2})
        assert response['retcode'] == 1429 and response['echo'] == 2
        assert upstream.call_count == 1
    assert list(ApiCallAudit.objects.order_by('pk').values_list('status_code', flat=True)) == [200, 429]