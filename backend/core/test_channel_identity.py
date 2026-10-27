from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from .models import Bot, User
from .onebot import public_id

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    bot = Bot.objects.create(name='Identity', app_id='identity-test')
    owner = User.objects.create_user('identity-owner', role='Owner')
    client = APIClient(); client.force_login(owner)
    return bot, owner, client, f'/api/v1/channels/{bot.channel_id}/identity/'


def test_first_identity_fetch_persists_and_returns_protocol_ids(setup):
    bot, _, client, path = setup
    with patch('core.onebot.get_self', return_value=(200, b'{"id":"17357542118528704598","username":"Synthetic"}', {})):
        response = client.post(path, {}, format='json')
    assert response.status_code == 200
    bot.channel.refresh_from_db()
    assert bot.channel.onebot_self_id == '17357542118528704598'
    assert response.json() == {'onebot11': public_id(bot, 'user', bot.channel.onebot_self_id, 11), 'onebot12': bot.channel.onebot_self_id}
    assert response['Cache-Control'] == 'no-store'


def test_identity_requires_owner_csrf_and_enabled_channel(setup):
    bot, owner, client, path = setup
    strict = APIClient(enforce_csrf_checks=True); strict.force_login(owner)
    assert strict.post(path, {}, format='json').status_code == 403
    client.force_login(User.objects.create_user('identity-admin'))
    with patch('core.channel_identity.identity') as upstream:
        assert client.post(path, {}, format='json').status_code == 403
        client.force_login(owner)
        assert client.post(path, {'endpoint':'untrusted'}, format='json').status_code == 400
        bot.is_active = False; bot.save()
        assert client.post(path, {}, format='json').status_code == 400
    upstream.assert_not_called()


def test_identity_failure_is_sanitized_and_keeps_saved_identity(setup):
    bot, _, client, path = setup
    bot.channel.onebot_self_id = 'saved'; bot.channel.save()
    with patch('core.channel_identity.identity', side_effect=ValueError('secret-token upstream body')):
        response = client.post(path, {}, format='json')
    assert response.status_code == 502 and b'secret-token' not in response.content
    bot.channel.refresh_from_db()
    assert bot.channel.onebot_self_id == 'saved'
