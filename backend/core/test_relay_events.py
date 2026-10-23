import pytest
from rest_framework.test import APIClient

from .events import ingest_event
from .models import Bot, BotGrant, User
from .services import issue_key

pytestmark = pytest.mark.django_db


def setup_reader():
    bot = Bot.objects.create(name='bot', app_id='1', encrypted_secret='unused')
    user = User.objects.create_user('reader')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=['events:read', 'query:read'])
    key, token = issue_key(user, bot, 'events', ['events:read'])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return bot, user, grant, client


def emit(bot, name):
    ingest_event(bot, {'op': 0, 'id': name, 't': 'C2C_MESSAGE_CREATE', 'd': {}})


def test_cursor_pagination_and_bot_isolation():
    bot, user, grant, client = setup_reader()
    other = Bot.objects.create(name='other', app_id='2', encrypted_secret='unused')
    BotGrant.objects.create(user=user, bot=other, scopes=['events:read'])
    emit(bot, 'one')
    emit(other, 'hidden')
    emit(bot, 'two')
    response = client.get('/relay/v1/events/?limit=1')
    assert response['Cache-Control'] == 'no-store'
    data = response.json()
    assert data['events'][0]['payload']['id'] == 'one'
    assert data['has_more']
    page = client.get('/relay/v1/events/', {'after': data['next_cursor'], 'limit': 1}).json()
    assert page['events'][0]['payload']['id'] == 'two'
    assert not page['has_more']


def test_regrant_does_not_expose_old_events():
    bot, user, grant, client = setup_reader()
    emit(bot, 'old')
    grant.revision += 1
    grant.save()
    assert client.get('/relay/v1/events/').status_code == 403
    key, token = issue_key(user, bot, 'new', ['events:read'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    assert client.get('/relay/v1/events/').json()['events'] == []
    emit(bot, 'new')
    assert [row['payload']['id'] for row in client.get('/relay/v1/events/').json()['events']] == ['new']


def test_scope_and_cursor_validation():
    bot, user, grant, client = setup_reader()
    for query in ['after=-1', 'after=abc', 'limit=0', 'limit=101']:
        assert client.get('/relay/v1/events/?' + query).status_code == 400
    key, token = issue_key(user, bot, 'query-only', ['query:read'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    assert client.get('/relay/v1/events/').status_code == 403
    assert APIClient().get('/relay/v1/events/').status_code == 401