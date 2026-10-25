from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import Bot, BotGrant, User
from .services import issue_key
from .official import send_message

pytestmark = pytest.mark.django_db


@pytest.fixture
def channel_client():
    user = User.objects.create_user('channel-admin')
    bot = Bot.objects.create(name='channel', app_id='channel-app', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=['messages:send', 'messages:delete'])
    _, token = issue_key(user, bot, 'channel', ['messages:send', 'messages:delete'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return client


@pytest.mark.parametrize('path', ['channels/123/messages', 'dms/123/messages', 'users/@me/dms'])
def test_channel_json_uses_registered_transport_and_preserves_audit_result(channel_client, path):
    body = b'{ "content":"hello", "msg_id":"context" }'
    raw = b'{"code":304023,"data":{"message_audit":{"audit_id":"a"}}}'
    with patch('core.views.send_message', return_value=(202, raw, {'Content-Type': 'application/json'})) as upstream:
        response = channel_client.post('/qq/' + path, body, content_type='application/json')
        assert response.status_code == 202 and response.content == raw
        assert upstream.call_args.args[1:] == (path, body, '')
    with patch('core.official._request', return_value=(200, b'{}', {})) as transport:
        send_message(None, path, body)
        transport.assert_called_once_with(None, 'POST', path, '', body)


@pytest.mark.parametrize('path', ['channels/123/messages/456', 'dms/123/messages/456'])
def test_channel_recall_preserves_hidetip(channel_client, path):
    with patch('core.views.delete_message', return_value=(200, b'', {})) as upstream:
        response = channel_client.delete('/qq/' + path + '?hidetip=true')
        assert response.status_code == 200 and response.content == b''
        assert upstream.call_args.args[1:] == (path, 'hidetip=true')