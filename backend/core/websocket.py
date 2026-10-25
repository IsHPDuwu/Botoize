"""Native and OneBot downstream event streams; not a QQ gateway."""
import asyncio
import json
import time
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from rest_framework.exceptions import APIException

from .models import EventOutbox
from .services import authorize
from .conversations import filter_events, key_grant


def onebot_identity(token):
    from .official import get_self, OfficialCredentialError
    from .onebot_ids import virtual_id
    from rest_framework.exceptions import PermissionDenied
    close_old_connections()
    try:
        key, _ = authorize(token, scope='events:read')
        status, body, _ = get_self(key.bot)
        if status != 200:
            raise ValueError('Upstream identity unavailable')
        identity = virtual_id(key.bot, 'user', json.loads(body)['id'])
        cursor = EventOutbox.objects.filter(is_stream=True, grant__user_id=key.user_id, grant__bot_id=key.bot_id).order_by('-pk').values_list('pk', flat=True).first() or 0
        return identity, cursor
    except (OfficialCredentialError, ValueError, TypeError, KeyError) as exc:
        raise PermissionDenied('Upstream identity unavailable') from exc
    finally:
        close_old_connections()


def read_onebot_page(token, cursor, self_id):
    from .onebot_events import message_event
    close_old_connections()
    try:
        key, _ = authorize(token, scope='events:read')
        rows = EventOutbox.objects.filter(
            is_stream=True,
            grant__user_id=key.user_id, grant__bot_id=key.bot_id,
            grant_revision=key.grant_revision, event__bot_id=key.bot_id,
            pk__gt=cursor,
        ).select_related('event').order_by('pk')
        rows = filter_events(filter_events(rows, key_grant(key)), key)[:50]
        return [{'cursor': str(row.pk), 'payload': message_event(key.bot, row.event.payload, self_id)} for row in rows]
    finally:
        close_old_connections()


def read_page(token, cursor):
    close_old_connections()
    try:
        key, _ = authorize(token, scope='events:read')
        rows = EventOutbox.objects.filter(
            is_stream=True,
            grant__user_id=key.user_id, grant__bot_id=key.bot_id,
            grant_revision=key.grant_revision, event__bot_id=key.bot_id,
            pk__gt=cursor,
        ).select_related('event').order_by('pk')
        rows = filter_events(filter_events(rows, key_grant(key)), key)[:50]
        return [{'cursor': str(row.pk), 'payload': row.event.payload} for row in rows]
    finally:
        close_old_connections()


async def event_socket(scope, receive, send):
    onebot = scope['path'] in {'/onebot/event', '/onebot/event/'}
    if not onebot and scope['path'] != '/relay/v1/ws/':
        await send({'type': 'websocket.close', 'code': 4404})
        return
    headers = dict(scope.get('headers', []))
    # Browser cookie credentials are never accepted; use a server-side WS client.
    if b'origin' in headers:
        await send({'type': 'websocket.close', 'code': 4403})
        return
    try:
        auth = headers.get(b'authorization', b'').decode('ascii').split()
        params = parse_qs(scope.get('query_string', b'').decode('ascii'), strict_parsing=True)
        after = params.get('after', ['0'])
        if set(params) - {'after'} or len(after) != 1 or not after[0].isascii() or not after[0].isdigit() or len(after[0]) > 18:
            raise ValueError
        if len(auth) != 2 or auth[0].lower() != 'bearer':
            raise ValueError
        cursor = int(after[0])
        if onebot:
            if params:
                raise ValueError
            self_id, cursor = await sync_to_async(onebot_identity)(auth[1])
        else:
            await sync_to_async(read_page)(auth[1], cursor)
    except (ValueError, UnicodeError, APIException):
        await send({'type': 'websocket.close', 'code': 4403})
        return
    if (await receive())['type'] != 'websocket.connect':
        return
    await send({'type': 'websocket.accept'})
    if onebot:
        await asyncio.wait_for(send({'type': 'websocket.send', 'text': json.dumps({
            'time': int(time.time()), 'self_id': self_id,
            'post_type': 'meta_event', 'meta_event_type': 'lifecycle', 'sub_type': 'connect',
        })}), timeout=10)
    incoming = asyncio.create_task(receive())
    try:
        while True:
            if incoming.done():
                message = incoming.result()
                if message['type'] == 'websocket.disconnect':
                    return
                await send({'type': 'websocket.close', 'code': 4400})
                return
            try:
                if onebot:
                    page = await sync_to_async(read_onebot_page)(auth[1], cursor, self_id)
                else:
                    page = await sync_to_async(read_page)(auth[1], cursor)
            except APIException:
                await send({'type': 'websocket.close', 'code': 4403})
                return
            for event in page:
                payload = event['payload'] if onebot else event
                if payload is not None:
                    await asyncio.wait_for(send({'type': 'websocket.send', 'text': json.dumps(payload)}), timeout=10)
                cursor = int(event['cursor'])
            await asyncio.wait({incoming}, timeout=1)
    except TimeoutError:
        await send({'type': 'websocket.close', 'code': 1013})
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)
