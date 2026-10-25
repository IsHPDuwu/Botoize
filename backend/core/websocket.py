"""Native downstream event stream; not a QQ gateway or OneBot WebSocket."""
import asyncio
import json
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from rest_framework.exceptions import APIException

from .models import EventOutbox
from .services import authorize


def read_page(token, cursor):
    close_old_connections()
    try:
        key, _ = authorize(token, scope='events:read')
        rows = EventOutbox.objects.filter(
            grant__user_id=key.user_id, grant__bot_id=key.bot_id,
            grant_revision=key.grant_revision, event__bot_id=key.bot_id,
            pk__gt=cursor,
        ).select_related('event').order_by('pk')[:50]
        return [{'cursor': str(row.pk), 'payload': row.event.payload} for row in rows]
    finally:
        close_old_connections()


async def event_socket(scope, receive, send):
    if scope['path'] != '/relay/v1/ws/':
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
        await sync_to_async(read_page)(auth[1], cursor)
    except (ValueError, UnicodeError, APIException):
        await send({'type': 'websocket.close', 'code': 4403})
        return
    if (await receive())['type'] != 'websocket.connect':
        return
    await send({'type': 'websocket.accept'})
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
                page = await sync_to_async(read_page)(auth[1], cursor)
            except APIException:
                await send({'type': 'websocket.close', 'code': 4403})
                return
            for event in page:
                await asyncio.wait_for(send({'type': 'websocket.send', 'text': json.dumps(event)}), timeout=10)
                cursor = int(event['cursor'])
            await asyncio.wait({incoming}, timeout=1)
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)