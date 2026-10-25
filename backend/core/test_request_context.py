import pytest
from rest_framework.test import APIClient

from .models import ApiCallAudit, Bot, BotGrant, User
from .services import encrypt_secret, issue_key

pytestmark = pytest.mark.django_db


def setup_key(username='audit-admin'):
    user = User.objects.create_user(username)
    bot = Bot.objects.create(name='audit-bot', app_id=username, encrypted_secret=encrypt_secret('unused'))
    BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
    _, token = issue_key(user, bot, 'audit', ['query:read'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return user, bot, client


def test_request_id_is_validated_and_returned():
    client = APIClient()
    response = client.get('/health/', HTTP_X_REQUEST_ID='trace-123')
    assert response['X-Request-ID'] == 'trace-123'
    rejected = client.get('/health/', HTTP_X_REQUEST_ID='bad value\r\nX-Evil: yes')
    assert rejected['X-Request-ID'] != 'bad value\r\nX-Evil: yes'
    assert len(rejected['X-Request-ID']) == 32


def test_proxy_call_is_audited_and_request_id_is_correlated():
    _, bot, client = setup_key()
    response = client.get('/qq/users/@me', HTTP_X_REQUEST_ID='audit-trace-1')
    assert response.status_code == 502
    assert response['X-Request-ID'] == 'audit-trace-1'
    record = ApiCallAudit.objects.get()
    assert record.request_id == 'audit-trace-1'
    assert record.bot_id == bot.pk
    assert record.path == '/qq/users/@me'
    assert record.method == 'GET' and record.status_code == 502


def test_call_audit_isolated_and_does_not_store_path_values():
    owner, bot, client = setup_key('audit-owner')
    client.get('/qq/users/@me?openid=private-value')
    record = ApiCallAudit.objects.get()
    assert 'private-value' not in record.path
    admin = APIClient()
    admin.force_authenticate(owner)
    assert admin.get('/api/v1/api-calls/').json()['calls'][0]['bot'] == bot.pk
    outsider = User.objects.create_user('audit-outsider')
    admin.force_authenticate(outsider)
    assert admin.get('/api/v1/api-calls/').json()['calls'] == []


def test_official_proxy_response_body_remains_unmodified():
    from unittest.mock import patch

    _, _, client = setup_key('audit-preserve')
    raw = b'{ "id": "original" }'
    with patch('core.views.get_self', return_value=(429, raw, {'Content-Type': 'application/json', 'X-Tps-trace-ID': 'official-trace'})):
        response = client.get('/qq/users/@me', HTTP_X_REQUEST_ID='platform-trace')
    assert response.status_code == 429
    assert response.content == raw
    assert response['X-Tps-trace-ID'] == 'official-trace'
    assert response['X-Request-ID'] == 'platform-trace'


@pytest.mark.parametrize(('path', 'expected'), [
    ('/qq/v2/groups/private-group/messages', '/qq/v2/groups/{group_id}/messages'),
    ('/qq/v2/users/private-user/files', '/qq/v2/users/{user_id}/files'),
    ('/qq/channels/private-channel/messages/private-message', '/qq/channels/{channel_id}/messages/{message_id}'),
    ('/qq/guilds/private-guild/members/private-user', '/qq/guilds/{guild_id}/members/{user_id}'),
    ('/qq/arbitrary-private-path', '/qq/<unsupported>'),
    ('/onebot/private-action', '/onebot/<unsupported>'),
    ('/onebot/get_login_info', '/onebot/get_login_info'),
])
def test_audit_templates_never_include_target_or_unknown_path(path, expected):
    _, _, client = setup_key()
    client.get(path + '?token=private-query')
    record = ApiCallAudit.objects.get()
    assert record.path == expected
    assert 'private' not in record.path
    assert record.replayed is False


@pytest.mark.parametrize(('body', 'expected'), [
    ({'msg_type': 0, 'content': 'private-body'}, 'text'),
    ({'msg_type': 2, 'markdown': {'content': 'private-body'}, 'keyboard': {}}, 'markdown+keyboard'),
    ({'msg_type': 0, 'ext_info': {'ref_idx': 'private-ref'}}, 'text+reference'),
    ({'msg_type': 7, 'media': {'file_info': 'private-media'}}, 'media'),
    ({'msg_type': {'unexpected': 'private'}}, ''),
])
def test_message_audit_metadata_and_replay(body, expected):
    from unittest.mock import patch
    from .models import IdempotentSend

    user, bot, client = setup_key()
    BotGrant.objects.filter(user=user, bot=bot).update(scopes=['messages:send'])
    _, token = issue_key(user, bot, 'sender', ['messages:send'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.views.send_message', return_value=(200, b'{"id":"result"}', {})) as send:
        for _ in range(2):
            response = client.post('/qq/v2/groups/private-group/messages', body, format='json',
                                   HTTP_IDEMPOTENCY_KEY='audit-replay')
            assert response.status_code == 200
        assert send.call_count == 1
    rows = list(ApiCallAudit.objects.order_by('id'))
    assert [row.message_type for row in rows] == [expected, expected]
    assert [row.replayed for row in rows] == [False, True]
    assert 'private' not in str(list(ApiCallAudit.objects.values()))
    assert IdempotentSend.objects.count() == 1
    client.force_authenticate(user)
    entry = client.get('/api/v1/api-calls/').json()['calls'][0]
    assert entry['message_type'] == expected and entry['replayed'] is True


@pytest.mark.parametrize(('file_type', 'expected'), [(1, 'image'), (2, 'video'), (3, 'audio'), (4, 'file'), ({}, '')])
def test_media_upload_audit_type(file_type, expected):
    from unittest.mock import patch

    user, bot, client = setup_key()
    BotGrant.objects.filter(user=user, bot=bot).update(scopes=['media:upload'])
    _, token = issue_key(user, bot, 'uploader', ['media:upload'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    with patch('core.views.upload_media', return_value=(200, b'{}', {})):
        response = client.post('/qq/v2/groups/private-group/files',
                               {'file_type': file_type, 'srv_send_msg': False, 'url': 'private-url'}, format='json')
    assert response.status_code == 200
    assert ApiCallAudit.objects.get().message_type == expected


def test_rejected_malformed_body_is_still_audited_without_parsing_again():
    _, _, client = setup_key()
    response = client.post('/qq/v2/groups/private-group/messages', '{invalid', content_type='application/json')
    assert response.status_code == 403
    assert ApiCallAudit.objects.get().message_type == ''


def test_audit_owner_visibility_and_pagination():
    user, _, client = setup_key()
    for _ in range(52):
        client.get('/qq/unsupported')
    owner = User.objects.create_user('global-audit-owner', role='Owner')
    client.force_authenticate(owner)
    response = client.get('/api/v1/api-calls/')
    page = response.json()
    assert response['Cache-Control'] == 'no-store'
    assert len(page['calls']) == 50 and page['has_more']
    older = client.get('/api/v1/api-calls/', {'before': page['next_before']}).json()
    assert len(older['calls']) == 2 and not older['has_more']
    assert not ({row['id'] for row in page['calls']} & {row['id'] for row in older['calls']})
    assert client.get('/api/v1/api-calls/?before=invalid').status_code == 400
