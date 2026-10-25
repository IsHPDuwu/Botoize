import asyncio
import json
from unittest.mock import patch

import pytest
from rest_framework.exceptions import PermissionDenied

from .models import Bot
from .onebot_events import message_event
from .onebot_ids import original_id
from .websocket import event_socket


@pytest.mark.django_db
@pytest.mark.parametrize('group', [False, True])
def test_message_conversion(group):
    bot = Bot.objects.create(name='events', app_id='events', encrypted_secret='unused')
    payload = {'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE' if group else 'C2C_MESSAGE_CREATE', 'd': {
        'id': 'message', 'content': '[hello]&', 'timestamp': '2026-10-25T12:00:00+08:00',
        'author': {'member_openid' if group else 'user_openid': 'user'}, 'group_openid': 'group',
    }}
    event = message_event(bot, payload, 123)
    assert event['time'] == 1792900800
    assert event['self_id'] == 123
    assert event['raw_message'] == '&#91;hello&#93;&amp;'
    assert event['message'] == [{'type': 'text', 'data': {'text': '[hello]&'}}]
    assert original_id(bot, 'user', event['user_id']) == 'user'
    assert original_id(bot, 'message', event['message_id']) == 'message'
    if group:
        assert original_id(bot, 'group', event['group_id']) == 'group'
        assert 'role' not in event['sender']
    assert message_event(bot, {**payload, 't': 'AT_MESSAGE_CREATE'}, 123) is None
    assert message_event(bot, {**payload, 'd': {**payload['d'], 'attachments': [{'url': 'image'}]}}, 123) is None
    assert message_event(bot, {**payload, 'd': {**payload['d'], 'timestamp': 'invalid'}}, 123) is None


def test_onebot_event_socket_lifecycle_and_revocation():
    async def run():
        queue = asyncio.Queue()
        await queue.put({'type': 'websocket.connect'})
        messages = []
        async def send(message):
            messages.append(message)
        event = {'post_type': 'message', 'user_id': 123}
        with patch('core.websocket.onebot_identity', return_value=(42, 10)), patch(
            'core.websocket.read_onebot_page', side_effect=[
                [{'cursor': '11', 'payload': None}, {'cursor': '12', 'payload': event}], PermissionDenied(),
            ],
        ) as read:
            await asyncio.wait_for(event_socket({
                'path': '/onebot/event', 'headers': [(b'authorization', b'Bearer token')], 'query_string': b'',
            }, queue.get, send), 5)
        assert json.loads(messages[1]['text'])['meta_event_type'] == 'lifecycle'
        assert json.loads(messages[2]['text']) == event
        assert messages[-1] == {'type': 'websocket.close', 'code': 4403}
        assert read.call_args.args == ('token', 12, 42)
    asyncio.run(run())


@pytest.mark.django_db
def test_real_reader_isolation_and_regrant():
    from .events import ingest_event
    from .models import BotGrant, User
    from .services import issue_key
    from .websocket import read_onebot_page
    bot = Bot.objects.create(name='reader', app_id='reader', encrypted_secret='unused')
    other = Bot.objects.create(name='hidden', app_id='hidden', encrypted_secret='unused')
    user = User.objects.create_user('onebot-reader')
    grant = BotGrant.objects.create(user=user, bot=bot, scopes=['events:read'])
    BotGrant.objects.create(user=user, bot=other, scopes=['events:read'])
    _, token = issue_key(user, bot, 'read', ['events:read'])
    payload = {'op': 0, 'id': 'event', 't': 'C2C_MESSAGE_CREATE', 'd': {
        'id': 'message', 'author': {'user_openid': 'sender'}, 'content': 'hello',
        'timestamp': '2026-10-25T12:00:00Z',
    }}
    ingest_event(bot, payload)
    ingest_event(other, payload)
    assert len(read_onebot_page(token, 0, 42)) == 1
    grant.revision += 1
    grant.save()
    with pytest.raises(PermissionDenied):
        read_onebot_page(token, 0, 42)
    _, renewed = issue_key(user, bot, 'renewed', ['events:read'])
    assert read_onebot_page(renewed, 0, 42) == []


@pytest.mark.django_db
def test_unknown_event_redacts_nested_credentials():
    bot = Bot.objects.create(name='redact', app_id='redact', encrypted_secret='unused')
    payload = {'op': 0, 'id': 'event', 't': 'QQ_UNKNOWN_NOTICE', 'd': {
        'timestamp': 1792900800, 'nested': {'AUTH_TOKEN': 'hidden', 'Authorization': 'hidden',
        'items': ['auth_token=hidden', {'app-secret': 'hidden', 'id': 'visible'}]},
        'message_scene': {'ext': ['auth_token=hidden']},
    }}
    event = message_event(bot, payload, 'self', version=12)
    assert 'hidden' not in json.dumps(event)
    assert event['qq.data']['nested']['items'] == [{'id': 'visible'}]


def test_malformed_attachment_does_not_crash_ingestion():
    from .onebot_events import parsed_message
    payload = {'op': 0, 't': 'C2C_MESSAGE_CREATE', 'd': {
        'id': 'message', 'author': {'user_openid': 'sender'}, 'content': 'hello',
        'timestamp': '2026-10-25T12:00:00Z',
        'attachments': [{'url': 'https://[invalid', 'content_type': 'image/png'}],
    }}
    assert parsed_message(payload) is None
