"""OneBot forward API WebSocket. No cookies, URL tokens or parallel sends."""
import asyncio
import json
import time
import uuid

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from rest_framework.exceptions import APIException

from .models import ApiCallAudit
from .onebot import invoke
from .quotas import consume_quota
from .services import authorize
from .throttle import bearer_throttle, RateLimitExceeded


def check_token(token):
    close_old_connections()
    try:
        authorize(token)
    finally:
        close_old_connections()


def call_action(token, envelope, version=11):
    close_old_connections()
    try:
        key, scopes = authorize(token)
        started = time.monotonic()
        status = 200
        try:
            if not bearer_throttle(key):
                raise RateLimitExceeded()
            consume_quota(key)
            kwargs = {'version': version, 'self_info': envelope.get('self')} if version == 12 else {}
            return invoke(key.bot, scopes, envelope['action'], envelope.get('params', {}), envelope.get('echo'), key=key, **kwargs).data
        except APIException as exc:
            status = exc.status_code
            return {'status': 'failed', 'retcode': (35029 if status == 429 else 35003) if version == 12 else (1429 if status == 429 else 1500),
                    'data': None, 'message': 'Request limit exceeded' if status == 429 else 'Request failed',
                    'echo': envelope.get('echo')}
        except Exception:
            status = 500
            raise
        finally:
            from .onebot import ACTIONS11, ACTIONS12, EXTENSIONS
            from .onebot_upstream_actions import RULES
            from .request_context import onebot_message_type
            action = envelope.get('action')
            action = action if isinstance(action, str) and action in ACTIONS11 | ACTIONS12 | EXTENSIONS | set(RULES) else '<unsupported>'
            ApiCallAudit.objects.create(
                api_key=key, user=key.user, bot=key.bot, request_id=uuid.uuid4().hex,
                bot_name=key.bot.name, username=key.user.username, key_name=key.name,
                method='WS', path=('/onebot/v12/' if version == 12 else '/onebot/') + action,
                message_type=onebot_message_type(action, envelope.get('params', {}), version), status_code=status,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
    finally:
        close_old_connections()


async def api_socket(scope, receive, send):
    headers = dict(scope.get('headers', []))
    try:
        if b'origin' in headers or scope.get('query_string', b''):
            raise ValueError
        parts = headers.get(b'authorization', b'').decode('ascii').split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            raise ValueError
        token = parts[1]
        await sync_to_async(check_token)(token)
    except (ValueError, UnicodeError, APIException):
        await send({'type': 'websocket.close', 'code': 4403})
        return
    if (await receive())['type'] != 'websocket.connect':
        return
    await send({'type': 'websocket.accept'})
    incoming = asyncio.create_task(receive())
    try:
        while True:
            await sync_to_async(check_token)(token)
            done, _ = await asyncio.wait({incoming}, timeout=1)
            if not done:
                continue
            frame = incoming.result()
            if frame['type'] == 'websocket.disconnect':
                return
            text = frame.get('text')
            if frame['type'] != 'websocket.receive' or not isinstance(text, str):
                await send({'type': 'websocket.close', 'code': 4400})
                return
            if len(text.encode('utf-8')) > 65536:
                await send({'type': 'websocket.close', 'code': 1009})
                return
            try:
                envelope = json.loads(text)
                if (not isinstance(envelope, dict) or set(envelope) - {'action', 'params', 'echo'}
                        or not isinstance(envelope.get('action'), str)):
                    raise ValueError
            except (ValueError, RecursionError):
                await send({'type': 'websocket.close', 'code': 4400})
                return
            response = await sync_to_async(call_action)(token, envelope)
            await asyncio.wait_for(send({'type': 'websocket.send', 'text': json.dumps(response)}), timeout=10)
            incoming = asyncio.create_task(receive())
    except APIException:
        await send({'type': 'websocket.close', 'code': 4403})
    except TimeoutError:
        await send({'type': 'websocket.close', 'code': 1013})
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)
