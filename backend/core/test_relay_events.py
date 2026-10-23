import pytest
from rest_framework.test import APIClient
from django.utils import timezone

from .events import ingest_event
from .models import ApiKey, Bot, BotGrant, User
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


def test_management_events_are_session_scoped_and_revision_filtered():
    bot, user, grant, bearer = setup_reader()
    emit(bot, 'private')
    session = APIClient()
    session.force_login(user)
    assert session.get('/api/v1/events/').json()['events'][0]['event_id'] == 'private'
    assert session.get('/api/v1/events/?before=invalid').status_code == 400
    grant.revision += 1
    grant.save()
    assert session.get('/api/v1/events/').json()['events'] == []
    owner = User.objects.create_user('owner', role='Owner')
    session.force_login(owner)
    assert session.get('/api/v1/events/').json()['events'][0]['event_id'] == 'private'
    assert APIClient().get('/api/v1/events/').status_code == 403


def test_later_recipient_cannot_read_replayed_historical_event():
    bot, user, grant, first = setup_reader()
    emit(bot, 'historical')
    later = User.objects.create_user('later-reader')
    BotGrant.objects.create(user=later, bot=bot, scopes=['events:read'])
    key, token = issue_key(later, bot, 'later', ['events:read'])
    second = APIClient()
    second.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    # Official retries must not create new historical recipient snapshots.
    emit(bot, 'historical')
    assert second.get('/relay/v1/events/').json()['events'] == []
    emit(bot, 'current')
    assert [row['payload']['id'] for row in second.get('/relay/v1/events/').json()['events']] == ['current']
    assert [row['payload']['id'] for row in first.get('/relay/v1/events/').json()['events']] == ['historical', 'current']


def test_revoked_key_and_disabled_account_stop_event_access():
    bot, user, grant, client = setup_reader()
    emit(bot, 'private')
    key, token = issue_key(user, bot, 'revocable', ['events:read'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    assert client.get('/relay/v1/events/').status_code == 200
    ApiKey.objects.filter(pk=key.pk).update(revoked_at=timezone.now())
    assert client.get('/relay/v1/events/').status_code == 401
    key, token = issue_key(user, bot, 'account-check', ['events:read'])
    client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    user.is_active = False
    user.save()
    assert client.get('/relay/v1/events/').status_code in (401, 403)