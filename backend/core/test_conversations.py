"""Negative end-to-end coverage: a conversation is an authorization boundary."""
from unittest.mock import patch
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed

from .models import User, Bot, BotGrant, Conversation, EventOutbox, ApiKey
from .services import issue_key, authorize
from .events import ingest_event
from .websocket import read_page, read_onebot_page
from .onebot_socket import call_action
from .onebot_ids import virtual_id
from .outbox import valid_snapshot, claim_outbox
from .replay import replay_delivery
from .subscriptions import set_subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    owner = User.objects.create_user('owner', role='Owner')
    user = User.objects.create_user('admin')
    other = User.objects.create_user('other')
    bot = Bot.objects.create(name='bot', app_id='bot', encrypted_secret='unused')
    foreign = Bot.objects.create(name='foreign', app_id='foreign', encrypted_secret='unused')
    allowed = Conversation.objects.create(bot=bot, is_direct=False, target_id='allowed')
    denied = Conversation.objects.create(bot=bot, is_direct=False, target_id='denied')
    direct = Conversation.objects.create(bot=bot, is_direct=True, target_id='allowed')
    cross = Conversation.objects.create(bot=foreign, is_direct=False, target_id='allowed')
    scopes = ['events:read', 'messages:send', 'media:upload', 'messages:delete', 'query:read', 'channels:write']
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=scopes, all_conversations=False)
    grant.conversations.add(allowed, direct)
    return owner, user, other, bot, grant, allowed, denied, direct, cross


def client(user=None, token=None):
    result = APIClient()
    if user:
        result.force_login(user)
    if token:
        result.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
    return result


def event(bot, target, index):
    return ingest_event(bot, {'op': 0, 'id': f'e-{index}', 't': 'GROUP_AT_MESSAGE_CREATE',
                             'd': {'group_openid': target, 'id': str(index), 'content': 'text',
                                   'author': {'member_openid': 'member'}, 'timestamp': '2026-10-25T00:00:00Z'}})[0]


def test_key_selection_validates_subset_types_and_bot_and_preserves_token(setup):
    _, user, _, bot, grant, allowed, denied, _, cross = setup
    c = client(user)
    data = {'bot': bot.pk, 'name': 'key', 'scopes': grant.scopes,
            'all_conversations': False, 'conversations': [allowed.pk]}
    for ids, all_models, status in [([denied.pk], False, 403), ([cross.pk], False, 400),
                                    ([True], False, 400), ([], True, 403)]:
        assert c.post('/api/v1/keys/', {**data, 'conversations': ids, 'all_conversations': all_models}, format='json').status_code == status
    response = c.post('/api/v1/keys/', data, format='json')
    assert response.status_code == 201
    key_id, token = response.json()['id'], response.json()['token']
    assert response['Cache-Control'] == 'no-store'
    for _ in range(2):
        assert c.post(f'/api/v1/keys/{key_id}/copy/', {}, format='json').json()['token'] == token
    assert c.patch(f'/api/v1/keys/{key_id}/', {'name': 'renamed', 'conversations': []}, format='json').status_code == 200
    assert c.post(f'/api/v1/keys/{key_id}/copy/', {}, format='json').json()['token'] == token
    assert client(setup[2]).post(f'/api/v1/keys/{key_id}/copy/', {}, format='json').status_code == 404
    ApiKey.objects.filter(pk=key_id).update(token='')
    assert c.post(f'/api/v1/keys/{key_id}/copy/', {}, format='json').status_code == 409


@pytest.mark.parametrize('operation', ['messages', 'files', 'upload_prepare', 'upload_part_finish', 'messages/message'])
def test_http_send_upload_delete_and_unknown_targets_fail_closed(setup, operation):
    _, user, _, bot, grant, allowed, *_ = setup
    _, token = issue_key(user, bot, 'key', grant.scopes, all_conversations=False, conversations=[allowed.pk])
    c = client(token=token)
    with patch('core.views.send_message', return_value=(200, b'{}', {})) as send, \
         patch('core.views.upload_media', return_value=(200, b'{}', {})) as upload, \
         patch('core.views.delete_message', return_value=(200, b'{}', {})) as delete:
        for target in ['denied', 'allowed']:
            path = f'/qq/v2/groups/{target}/{operation}'
            response = c.delete(path) if '/' in operation else c.post(path, {'srv_send_msg': False}, format='json')
            assert response.status_code == (403 if target == 'denied' else 200)
        assert c.post('/qq/v2/users/allowed/messages', {}, format='json').status_code == 403
        assert c.post('/qq/channels/allowed/messages', {}, format='json').status_code == 403
        assert c.patch('/qq/channels/allowed', {}, format='json').status_code == 403
        assert send.call_count + upload.call_count + delete.call_count == 1


def test_onebot_http_and_api_ws_enforce_same_policy(setup):
    _, user, _, bot, grant, allowed, *_ = setup
    _, token = issue_key(user, bot, 'key', grant.scopes, all_conversations=False, conversations=[allowed.pk])
    c = client(token=token)
    with patch('core.onebot.send_message', return_value=(200, b'{"id":"message"}', {})) as upstream:
        for target, expected in [('denied', 1403), ('allowed', 0)]:
            params = {'group_id': virtual_id(bot, 'group', target), 'message': 'text'}
            assert c.post('/onebot/send_group_msg', params, format='json').json()['retcode'] == expected
            assert call_action(token, {'action': 'send_group_msg', 'params': params, 'echo': 7})['retcode'] == expected
        assert upstream.call_count == 2


def test_events_filter_before_pagination_and_ws_and_live_key_edit(setup):
    _, user, _, bot, grant, allowed, denied, *_ = setup
    # Old snapshots may have been created under an unrestricted grant.
    grant.all_conversations = True
    grant.save()
    for index in range(55):
        event(bot, 'denied', index)
    visible = event(bot, 'allowed', 100)
    _, token = issue_key(user, bot, 'key', grant.scopes, all_conversations=False, conversations=[allowed.pk])
    c = client(token=token)
    page = c.get('/relay/v1/events/?limit=1').json()
    assert len(page['events']) == 1 and page['events'][0]['payload']['id'] == visible.event_id
    assert not page['has_more']
    assert len(read_page(token, 0)) == 1
    assert len(read_onebot_page(token, 0, 1)) == 1
    key = ApiKey.objects.get(token=token)
    client(user).patch(f'/api/v1/keys/{key.pk}/', {'conversations': []}, format='json')
    assert read_page(token, 0) == []
    # Even database policy reduction without revision changes cannot leak old snapshots.
    grant.all_conversations = False
    grant.conversations.set([allowed])
    grant.save()
    managed = client(user)
    assert len(managed.get('/api/v1/events/').json()['events']) == 1
    assert len(managed.get('/api/v1/deliveries/').json()['deliveries']) == 1
    assert managed.get('/api/v1/dashboard/overview/').json()['event_count'] <= 1


def test_callback_and_replay_recheck_policy(setup):
    _, user, _, bot, grant, allowed, denied, *_ = setup
    grant.all_conversations = True
    grant.save()
    event(bot, 'denied', 1)
    row = EventOutbox.objects.select_related('event', 'grant__user', 'grant__bot').get()
    set_subscription(grant.pk, 'https://example.com/callback')
    grant.all_conversations = False
    grant.conversations.set([allowed])
    grant.save()
    row.grant = grant
    assert not valid_snapshot(row)
    assert claim_outbox() == []
    EventOutbox.objects.filter(pk=row.pk).update(state='failed')
    with pytest.raises(ValueError):
        replay_delivery(row.pk, user)


def test_admin_delegation_cannot_escalate_or_override_and_parent_shrink_invalidates(setup):
    owner, user, other, bot, grant, allowed, denied, *_ = setup
    c = client(user)
    data = {'user': other.pk, 'bot': bot.pk, 'scopes': ['events:read'],
            'all_conversations': False, 'conversations': [allowed.pk]}
    assert c.post('/api/v1/grants/', {**data, 'conversations': [denied.pk]}, format='json').status_code == 403
    assert c.post('/api/v1/grants/', {**data, 'scopes': ['roles:write']}, format='json').status_code == 403
    assert c.post('/api/v1/grants/', {**data, 'user': owner.pk}, format='json').status_code == 403
    assert c.post('/api/v1/grants/', {**data, 'user': user.pk}, format='json').status_code == 403
    response = c.post('/api/v1/grants/', data, format='json')
    assert response.status_code == 200
    assert response.json()['parent_id'] == grant.pk
    _, token = issue_key(other, bot, 'delegated', ['events:read'])
    authorize(token)
    response = client(owner).post('/api/v1/grants/', {'user': user.pk, 'bot': bot.pk, 'scopes': grant.scopes,
                             'all_conversations': False, 'conversations': []}, format='json')
    assert response.status_code == 200
    with pytest.raises(PermissionDenied):
        authorize(token)
    assert client(other).get('/api/v1/my-grants/').json() == []
    assert client(other).post('/api/v1/keys/', {'bot': bot.pk, 'name': 'bad', 'scopes': []}, format='json').status_code == 403


@pytest.mark.parametrize('change', ['revoke', 'expire', 'account', 'bot', 'regrant'])
def test_live_invalidation_all_entry_points(setup, change):
    owner, user, _, bot, grant, *_ = setup
    key, token = issue_key(user, bot, 'key', grant.scopes)
    if change == 'revoke':
        client(user).post(f'/api/v1/keys/{key.pk}/revoke/', {}, format='json')
    elif change == 'expire':
        ApiKey.objects.filter(pk=key.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif change == 'account':
        User.objects.filter(pk=user.pk).update(is_active=False)
    elif change == 'bot':
        Bot.objects.filter(pk=bot.pk).update(is_active=False)
    else:
        client(owner).post('/api/v1/grants/', {'user': user.pk, 'bot': bot.pk, 'scopes': grant.scopes}, format='json')
    for reader in [lambda: read_page(token, 0), lambda: read_onebot_page(token, 0, 1),
                   lambda: call_action(token, {'action': 'get_login_info'})]:
        with pytest.raises((PermissionDenied, AuthenticationFailed)):
            reader()
    assert client(token=token).get('/relay/v1/events/').status_code in (401, 403)
