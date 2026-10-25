from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import Bot, BotGrant, User
from .official import OfficialCredentialError, delete_message
from .services import issue_key

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('kind', ['users', 'groups'])
def test_delete_preserves_empty_response_and_checks_independent_scope(kind):
    user = User.objects.create_user('delete-user')
    bot = Bot.objects.create(name='delete', app_id='delete-app', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=['messages:send', 'messages:delete'])
    client = APIClient()
    _, token = issue_key(user, bot, 'send-only', ['messages:send'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    path = f'/qq/v2/{kind}/openid/messages/message-id'
    with patch('core.views.delete_message') as upstream:
        assert client.delete(path).status_code == 403
        upstream.assert_not_called()
    _, token = issue_key(user, bot, 'delete', ['messages:delete'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.views.delete_message', return_value=(200, b'', {'X-Tps-trace-ID': 'delete-trace'})) as upstream:
        response = client.delete(path + '?test=1')
        assert response.status_code == 200 and response.content == b''
        assert response['X-Tps-trace-ID'] == 'delete-trace'
        assert upstream.call_args.args[1:] == (f'v2/{kind}/openid/messages/message-id', 'test=1')
    with patch('core.views.delete_message', side_effect=OfficialCredentialError) as upstream:
        assert client.delete(path).status_code == 502
        upstream.assert_called_once()


def test_delete_transport_uses_only_registered_fixed_host_path():
    with patch('core.official._request', return_value=(204, b'', {})) as upstream:
        assert delete_message(None, 'v2/groups/target/messages/message') == (204, b'', {})
        upstream.assert_called_once_with(None, 'DELETE', 'v2/groups/target/messages/message', '')
        with pytest.raises(ValueError):
            delete_message(None, 'v2/groups/target/messages/../../token')