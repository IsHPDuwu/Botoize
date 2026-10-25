import pytest
from rest_framework.test import APIClient

from .models import User, Provider, Bot, BotGrant, Conversation

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    user = User.objects.create_user('provider-owner', password='password', role='Owner')
    client = APIClient()
    client.force_login(user)
    return client


def payload():
    return {'name': '生产', 'password': 'password', 'channels': [{
        'name': 'Bot A', 'interface_type': 'qq_official_websocket',
        'app_id': 'appid', 'secret': 'private', 'is_active': True,
        'models': [{'name': '群聊', 'isDirect': False, 'groupid': 'group-openid'}],
    }]}


def test_provider_roundtrip_and_identity(client):
    response = client.post('/api/v1/providers/', payload(), format='json')
    assert response.status_code == 201
    data = response.json()
    bot = data['channels'][0]
    assert 'secret' not in bot and 'encrypted_secret' not in bot
    update = {**data, 'password': 'password'}
    update.pop('id')
    update['channels'][0]['name'] = 'Renamed Bot'
    update['channels'][0]['interface_type'] = 'qq_official_webhook'
    response = client.patch(f'/api/v1/providers/{data["id"]}/', update, format='json')
    assert response.status_code == 200
    assert response.json()['channels'][0]['interface_type'] == 'qq_official_webhook'
    assert response.json()['channels'][0]['bot_id'] == bot['bot_id']
    assert Bot.objects.get(pk=bot['bot_id']).name == 'Renamed Bot'
    assert response.json()['channels'][0]['models'][0]['groupid'] == 'group-openid'
    # Saving without modifications is legal and does not rotate credentials.
    assert client.patch(f'/api/v1/providers/{data["id"]}/', update, format='json').status_code == 200


def test_reserved_interface_and_atomic_rollback(client):
    data = payload()
    data['channels'][0].update(interface_type='onebot_v11')
    assert client.post('/api/v1/providers/', data, format='json').status_code == 400
    assert not Provider.objects.filter(name='生产').exists()
    assert not Bot.objects.exists()
    types = client.get('/api/v1/upstream-interfaces/').json()
    assert any(item['interface_type'] == 'onebot_v11' and not item['implemented'] for item in types)


def test_admin_only_sees_granted_models(client):
    data = client.post('/api/v1/providers/', payload(), format='json').json()
    admin = User.objects.create_user('provider-admin')
    client.force_login(admin)
    assert client.get('/api/v1/providers/').json() == []
    assert client.post('/api/v1/providers/', payload(), format='json').status_code == 403
    bot = Bot.objects.get(pk=data['channels'][0]['bot_id'])
    grant = BotGrant.objects.create(user=admin, bot=bot, scopes=['query:read'], all_conversations=False)
    assert client.get('/api/v1/providers/').json()[0]['channels'][0]['models'] == []
    grant.conversations.add(bot.conversations.get())
    assert client.get('/api/v1/providers/').json()[0]['channels'][0]['models'][0]['groupid'] == 'group-openid'


def test_sync_only_backfills_real_events_and_cross_bot_models_rejected(client):
    from .models import Event
    data = client.post('/api/v1/providers/', payload(), format='json').json()
    channel = data['channels'][0]
    bot = Bot.objects.get(pk=channel['bot_id'])
    Event.objects.create(bot=bot, event_id='historical', event_type='C2C_MESSAGE_CREATE',
                         payload={'t': 'C2C_MESSAGE_CREATE', 'd': {'author': {'user_openid': 'history-user'}}})
    response = client.post(f'/api/v1/channels/{channel["id"]}/sync/', {}, format='json')
    assert response.json()['created'] == 1
    assert not response.json()['upstream_enumeration_supported']
    assert client.post(f'/api/v1/channels/{channel["id"]}/sync/', {}, format='json').json()['created'] == 0
    foreign = Bot.objects.create(name='foreign', app_id='foreign', encrypted_secret='unused')
    other = Conversation.objects.create(bot=foreign, is_direct=True, target_id='cross')
    update = {'name': data['name'], 'channels': [{**channel, 'models': [{'id': other.pk, 'isDirect': True, 'userid': 'cross'}]}]}
    assert client.patch(f'/api/v1/providers/{data["id"]}/', update, format='json').status_code == 404
