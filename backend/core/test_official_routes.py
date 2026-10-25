import pytest
from unittest.mock import patch
from rest_framework.test import APIClient

from .models import Bot, BotGrant, User
from .services import issue_key, SCOPES
from .official_routes import ROUTES, OPERATIONS, required_scope
import re


def test_registry_strict_paths():
    assert {scope for _, _, scope in ROUTES} <= SCOPES
    assert required_scope('PATCH', 'channels/channel') == 'channels:write'
    for path in ['channels/../secret', 'https://evil.test/channels/1', 'channels/a/extra']:
        assert required_scope('PATCH', path) is None
    assert required_scope('POST', 'channels/a') is None


@pytest.mark.django_db
@pytest.mark.parametrize('method,path,scope,body', [
    ('get', 'guilds/g', 'guilds:read', None),
    ('post', 'channels/c/schedules', 'schedules:write', {'schedule': {'name': 'meeting'}}),
    ('put', 'channels/c/threads', 'forums:write', {'title': 'post'}),
    ('post', 'channels/c/audio', 'audio:control', {'status': 0}),
    ('patch', 'guilds/g/mute', 'moderation:write', {'mute_seconds': '60'}),
    ('post', 'guilds/g/api_permission/demand', 'api-permissions:write', {'channel_id': 'c'}),
    ('post', 'guilds/g/channels', 'channels:write', {'name': 'channel'}),
    ('patch', 'channels/c', 'channels:write', {'name': 'renamed'}),
    ('delete', 'guilds/g/members/u', 'members:write', None),
    ('put', 'channels/c/members/u/permissions', 'permissions:write', {'add': '1'}),
])
def test_management_scope_and_passthrough(method, path, scope, body):
    user = User.objects.create_user('route-reader')
    bot = Bot.objects.create(name='bot', app_id='route-bot', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=[scope, 'query:read'])
    _, token = issue_key(user, bot, 'limited', ['query:read'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    kwargs = {'data': body, 'format': 'json'} if body is not None else {}
    with patch('core.official._request', return_value=(200, b'{"official":true}', {'Content-Type': 'application/json'})) as upstream:
        assert getattr(client, method)('/qq/' + path, **kwargs).status_code == 403
        upstream.assert_not_called()
        _, token = issue_key(user, bot, 'allowed', [scope])
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        response = getattr(client, method)('/qq/' + path, **kwargs)
        assert response.status_code == 200
        assert response.content == b'{"official":true}'
        assert upstream.call_args.args[1:3] == (method.upper(), path)


@pytest.mark.django_db
@pytest.mark.parametrize('method,template,scope', OPERATIONS)
def test_every_registered_operation_enforces_scope_and_conversation_boundary(method, template, scope):
    user = User.objects.create_user('registry-user')
    bot = Bot.objects.create(name='registry', app_id='registry', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=[scope])
    path = '/qq/' + re.sub(r'\{\w+\}', 'target', template)
    c = APIClient()
    _, token = issue_key(user, bot, 'missing-scope', [])
    c.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    call = getattr(c, method.lower())
    data = {'data': {'official': 'body'}, 'format': 'json'} if method in ('POST', 'PATCH', 'PUT') else {}
    with patch('core.official._request', return_value=(202, b'{"upstream":true}', {'Content-Type': 'application/json'})) as transport:
        assert call(path, **data).status_code == 403
        _, token = issue_key(user, bot, 'restricted-conversations', [scope], all_conversations=False, conversations=[])
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        assert call(path, **data).status_code == 403
        transport.assert_not_called()
        _, token = issue_key(user, bot, 'allowed', [scope])
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        response = call(path, **data)
        assert response.status_code == 202 and response.content == b'{"upstream":true}'
        assert transport.call_count == 1
