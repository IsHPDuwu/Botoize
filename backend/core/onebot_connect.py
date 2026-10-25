"""Universal forward/reverse WS session: serialized actions, live revocation, events."""
import asyncio
import json
import time
import uuid
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from rest_framework.exceptions import APIException

from .models import EventOutbox
from .onebot import VERSION, identity, protocol_result
from .onebot_common import OneBotError
from .official import OfficialCredentialError
from .onebot_http import envelope_error
from .onebot_socket import call_action, check_token
from .services import authorize
from .websocket import read_onebot_page

MAX_FRAME = 12 * 1024 * 1024


def connection_info(token, version):
    close_old_connections()
    try:
        key, scopes = authorize(token)
        own, _ = identity(key.bot)
        if version == 11:
            from .onebot_ids import virtual_id
            self_id = virtual_id(key.bot, 'user', own['user_id'])
        else:
            self_id = own['user_id']
        cursor = EventOutbox.objects.filter(is_stream=True, grant__user_id=key.user_id,
                                           grant__bot_id=key.bot_id).order_by('-pk').values_list('pk', flat=True).first() or 0
        return self_id, cursor, 'events:read' in scopes
    finally:
        close_old_connections()


def meta(protocol_version, self_id, kind, **data):
    if protocol_version == 12:
        return {'id': str(uuid.uuid4()), 'time': time.time(), 'type': 'meta', 'detail_type': kind, 'sub_type': '', **data}
    return {'time': int(time.time()), 'self_id': self_id, 'post_type': 'meta_event',
            'meta_event_type': 'lifecycle' if kind == 'connect' else kind,
            **({'sub_type': 'connect'} if kind == 'connect' else {}), **data}


def status_data(version, self_id, online=True):
    if version == 12:
        return {'good': online, 'bots': [{'self': {'platform': 'qq', 'user_id': str(self_id)}, 'online': online}],
                'botoize.online_basis': 'identity_http'}
    return {'good': online, 'online': online, 'botoize.online_basis': 'identity_http'}


def probe_status(token, version, self_id):
    key, _ = authorize(token)
    try:
        identity(key.bot)
        online = True
    except (OfficialCredentialError, OneBotError, ValueError, KeyError, TypeError):
        online = False
    return status_data(version, self_id, online)


async def session(token, version, receive, emit, *, role='Universal', cursor_start=None, acknowledge=None, renew=None):
    self_id, cursor, events = await sync_to_async(connection_info)(token, version)
    if cursor_start is not None:
        cursor = cursor_start
    await emit(meta(version, self_id, 'connect', **({'version': VERSION} if version == 12 else {})))
    if version == 12:
        await emit(meta(version, self_id, 'status_update', status=status_data(version, self_id)))
    last_status = status_data(version, self_id)
    incoming = asyncio.create_task(receive())
    heartbeat_at, errors = time.monotonic() + 30, 0
    try:
        while True:
            await sync_to_async(check_token)(token)
            if renew is not None:
                await sync_to_async(renew)()
            if incoming.done():
                frame = incoming.result()
                if frame is None:
                    return
                if role == 'Event':
                    raise ValueError('Event-only connection received an action')
                try:
                    if not isinstance(frame, str):
                        raise ValueError
                    if len(frame.encode()) > MAX_FRAME:
                        raise ValueError
                    envelope = json.loads(frame)
                    error = envelope_error(envelope, version)
                except (ValueError, RecursionError):
                    envelope = {}
                    error = protocol_result(version, code=10001, message='Invalid or unsupported action frame').data
                if error:
                    errors += 1
                    if errors > 20:
                        raise ValueError('Too many invalid frames')
                    await emit(error)
                else:
                    await emit(await sync_to_async(call_action)(token, envelope, version=version))
                incoming = asyncio.create_task(receive())
            if events and role != 'API':
                page = await sync_to_async(read_onebot_page)(token, cursor, self_id, version=version)
                for event in page:
                    if event['payload'] is not None:
                        await emit(event['payload'])
                    cursor = int(event['cursor'])
                    if acknowledge is not None:
                        await sync_to_async(acknowledge)(cursor)
            if time.monotonic() >= heartbeat_at:
                current_status = await sync_to_async(probe_status)(token, version, self_id)
                if version == 12 and current_status != last_status:
                    await emit(meta(version, self_id, 'status_update', status=current_status))
                last_status = current_status
                await emit(meta(version, self_id, 'heartbeat', interval=30000,
                                **({'status': last_status} if version == 11 else {})))
                heartbeat_at = time.monotonic() + 30
            await asyncio.wait({incoming}, timeout=0.2)
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)


def websocket_token(scope):
    headers = dict(scope.get('headers', []))
    if b'origin' in headers:
        raise ValueError('Browser-origin WS is disabled')
    if b'authorization' in headers:
        auth = headers[b'authorization'].decode('ascii').split()
        if len(auth) != 2 or auth[0].lower() != 'bearer':
            raise ValueError
        return auth[1]
    params = parse_qs(scope.get('query_string', b'').decode('ascii'), strict_parsing=True)
    if set(params) != {'access_token'} or len(params['access_token']) != 1:
        raise ValueError
    return params['access_token'][0]


async def universal_socket(scope, receive, send):
    version = 12 if scope['path'].startswith('/onebot/v12') else 11
    suffix = scope['path'].rstrip('/').rsplit('/', 1)[-1]
    role = 'API' if suffix == 'api' else 'Event' if suffix == 'event' else 'Universal'
    try:
        token = websocket_token(scope)
        await sync_to_async(check_token)(token)
        if role == 'Event':
            await sync_to_async(authorize)(token, scope='events:read')
    except (ValueError, UnicodeError, APIException):
        # ASGI denial response avoids upgrading an unauthenticated connection.
        if 'websocket.http.response' in scope.get('extensions', {}):
            await send({'type': 'websocket.http.response.start', 'status': 401, 'headers': []})
            await send({'type': 'websocket.http.response.body', 'body': b''})
        else:
            await send({'type': 'websocket.close', 'code': 4401})
        return
    if (await receive())['type'] != 'websocket.connect':
        return
    await send({'type': 'websocket.accept'})

    async def recv():
        frame = await receive()
        return None if frame['type'] == 'websocket.disconnect' else frame.get('text', frame.get('bytes', b''))

    async def emit(payload):
        await asyncio.wait_for(send({'type': 'websocket.send', 'text': json.dumps(payload)}), timeout=10)

    try:
        await session(token, version, recv, emit, role=role)
    except APIException:
        await send({'type': 'websocket.close', 'code': 4403})
    except (ValueError, TimeoutError):
        await send({'type': 'websocket.close', 'code': 4400})
    except Exception:
        await send({'type': 'websocket.close', 'code': 1011})
