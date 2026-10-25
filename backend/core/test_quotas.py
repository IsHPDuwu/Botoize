from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import AuditLog, Bot, BotGrant, QuotaPolicy, QuotaUsage, User
from .quotas import QuotaExceeded, consume_quota
from .services import issue_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def keys():
    bot = Bot.objects.create(name='quota', app_id='quota', encrypted_secret='unused')
    keys = []
    for name in ('quota-a', 'quota-b'):
        user = User.objects.create_user(name)
        BotGrant.objects.create(user=user, bot=bot, scopes=['query:read'])
        key, _ = issue_key(user, bot, 'quota', ['query:read'])
        keys.append(key)
    return keys


def test_bot_quota_shared_across_users_and_rejection_rolls_back(keys):
    global_policy = QuotaPolicy.objects.create(scope='platform', subject_id=0, limit=100)
    bot_policy = QuotaPolicy.objects.create(scope='bot', subject_id=keys[0].bot_id, limit=1)
    consume_quota(keys[0])
    with pytest.raises(QuotaExceeded):
        consume_quota(keys[1])
    assert QuotaUsage.objects.get(policy=global_policy).count == 1
    assert QuotaUsage.objects.get(policy=bot_policy).count == 1


def test_window_reset_and_zero_limit(keys):
    policy = QuotaPolicy.objects.create(scope='user', subject_id=keys[0].user_id, limit=0)
    with pytest.raises(QuotaExceeded):
        consume_quota(keys[0])
    assert not QuotaUsage.objects.exists()
    policy.limit = 1
    policy.save()
    with patch('core.quotas.timezone.now') as now:
        now.return_value.timestamp.return_value = 86401
        consume_quota(keys[0])
        with pytest.raises(QuotaExceeded):
            consume_quota(keys[0])
        now.return_value.timestamp.return_value = 172801
        consume_quota(keys[0])
    assert QuotaUsage.objects.count() == 2


def test_quota_owner_management_and_live_enforcement(keys):
    owner = User.objects.create_user('quota-owner', password='quota-password-long', role='Owner')
    client = APIClient()
    client.force_authenticate(keys[0].user)
    assert client.get('/api/v1/quotas/').status_code == 403
    client.force_authenticate(owner)
    payload = {'scope': 'bot', 'subject_id': keys[0].bot_id, 'window_seconds': 60,
               'limit': 0, 'password': 'quota-password-long'}
    assert client.post('/api/v1/quotas/', payload, format='json').status_code == 201
    assert client.get('/api/v1/quotas/').json()[0]['used'] == 0
    assert AuditLog.objects.filter(action='quota.update').exists()
    _, token = issue_key(keys[0].user, keys[0].bot, 'http', ['query:read'])
    data = APIClient()
    data.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    response = data.get('/relay/v1/capabilities/')
    assert response.status_code == 429
    assert int(response['Retry-After']) >= 1
    assert response.json()['code'] == 'quota_exceeded'