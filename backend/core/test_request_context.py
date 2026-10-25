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
    assert record.path == '^(?:qq|onebot)/(?P<path>.*)$'
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