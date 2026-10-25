from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Bot, BotGrant, ThrottleCounter, User
from .services import issue_key
from .throttle import LIMITS, _counter

pytestmark = pytest.mark.django_db


def test_database_counter_increments_and_resets_window():
    assert _counter('test-counter') == 1
    assert _counter('test-counter') == 2
    row = ThrottleCounter.objects.get()
    ThrottleCounter.objects.filter(pk=row.pk).update(window_started_at=timezone.now() - timedelta(seconds=61))
    assert _counter('test-counter') == 1
    assert ThrottleCounter.objects.get().count == 1


def test_bearer_limits_share_user_and_bot_across_keys(monkeypatch):
    monkeypatch.setitem(LIMITS, 'bearer_key', 2)
    monkeypatch.setitem(LIMITS, 'bearer_user', 4)
    monkeypatch.setitem(LIMITS, 'bearer_bot', 100)
    user = User.objects.create_user('rate-user')
    bot = Bot.objects.create(name='rate-bot', app_id='rate-app', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
    _, token_a = issue_key(user, bot, 'a', ['query:read'])
    _, token_b = issue_key(user, bot, 'b', ['query:read'])
    first, second = APIClient(), APIClient()
    first.credentials(HTTP_AUTHORIZATION='Bearer ' + token_a)
    second.credentials(HTTP_AUTHORIZATION='Bearer ' + token_b)
    for _ in range(2):
        assert first.get('/relay/v1/capabilities/').status_code == 200
    assert first.get('/relay/v1/capabilities/').status_code == 429
    response = second.get('/relay/v1/capabilities/')
    assert response.status_code == 200
    response = second.get('/relay/v1/capabilities/')
    assert response.status_code == 429
    assert response['Retry-After'] == '60'
    assert response.json()['code'] == 'rate_limited'


def test_bot_limit_is_shared_across_admins(monkeypatch):
    monkeypatch.setitem(LIMITS, 'bearer_key', 100)
    monkeypatch.setitem(LIMITS, 'bearer_user', 100)
    monkeypatch.setitem(LIMITS, 'bearer_bot', 4)
    bot = Bot.objects.create(name='shared-rate-bot', app_id='shared-rate-app', encrypted_secret='unused')
    clients = []
    for username in ('rate-admin-a', 'rate-admin-b'):
        user = User.objects.create_user(username)
        BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
        _, token = issue_key(user, bot, 'shared', ['query:read'])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
        clients.append(client)
    for client in clients:
        assert client.get('/relay/v1/capabilities/').status_code == 200
        assert client.get('/relay/v1/capabilities/').status_code == 200
    assert clients[0].get('/relay/v1/capabilities/').status_code == 429


def test_login_limit_is_per_remote_address():
    client = APIClient(enforce_csrf_checks=True)
    for _ in range(10):
        csrf = client.get('/api/v1/auth/csrf/').json()['csrfToken']
        response = client.post('/api/v1/auth/login/', {'username': 'missing', 'password': 'wrong'}, HTTP_X_CSRFTOKEN=csrf)
        assert response.status_code == 403
    csrf = client.get('/api/v1/auth/csrf/').json()['csrfToken']
    response = client.post('/api/v1/auth/login/', {'username': 'missing', 'password': 'wrong'}, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 429
    assert response['Retry-After'] == '60'