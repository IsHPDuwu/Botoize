"""Official QQ Gateway consumer. Run outside ASGI; never exposes tokens downstream."""
import hashlib
import json
import platform
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from websockets.sync.client import connect

from .events import ingest_event
from .models import Bot, GatewaySession
from .official import OfficialCredentialError, access_token, get_gateway

LEASE_SECONDS = 60
FATAL_CLOSE_CODES = {4001, 4002, 4010, 4011, 4012, 4013, 4014, 4914, 4915}


class GatewayError(Exception):
    """Safe operational error without credentials or upstream payloads."""


class LeaseLost(GatewayError):
    pass


class Reconnect(GatewayError):
    pass


def credential_digest(bot):
    return hashlib.sha256((bot.app_id + ':' + bot.encrypted_secret + ':' + bot.channel.base_url + ':' + bot.channel.interface_type).encode()).hexdigest()


@transaction.atomic
def claim(bot_id, intents):
    if type(intents) is not int or not 0 < intents < 2 ** 32:
        raise GatewayError('Intents must be a positive 32-bit bitmask')
    bot = Bot.objects.select_for_update().get(pk=bot_id)
    if not bot.is_active:
        raise GatewayError('Bot is inactive')
    if bot.channel.interface_type != 'qq_official_websocket':
        raise GatewayError('Channel is not configured for WebSocket')
    row, _ = GatewaySession.objects.get_or_create(bot=bot)
    now = timezone.now()
    token = uuid.uuid4()
    acquired = GatewaySession.objects.filter(pk=row.pk).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=now),
    ).update(lease_token=token, lease_until=now + timedelta(seconds=LEASE_SECONDS))
    if not acquired:
        raise GatewayError('Another Gateway worker holds this Bot lease')
    digest = credential_digest(bot)
    if row.credential_digest != digest or row.intents != intents:
        GatewaySession.objects.filter(pk=row.pk, lease_token=token).update(
            credential_digest=digest, intents=intents, session_id='', sequence=None,
        )
    row.refresh_from_db()
    return bot, row, token


def renew(bot, token):
    now = timezone.now()
    current = Bot.objects.get(pk=bot.pk)
    if not current.is_active or credential_digest(current) != credential_digest(bot):
        raise LeaseLost('Bot disabled or credentials changed')
    if not GatewaySession.objects.filter(
        bot=bot, lease_token=token, lease_until__gt=now,
    ).update(lease_until=now + timedelta(seconds=LEASE_SECONDS)):
        raise LeaseLost('Gateway lease expired or was replaced')


def release(bot, token):
    GatewaySession.objects.filter(bot=bot, lease_token=token).update(lease_token=None, lease_until=None)


def clear_session(bot, token):
    if not GatewaySession.objects.filter(bot=bot, lease_token=token).update(session_id='', sequence=None):
        raise LeaseLost('Gateway lease replaced')


@transaction.atomic
def dispatch(bot, token, payload):
    # Same lock order as ingestion and claim: Bot, then GatewaySession.
    current = Bot.objects.select_for_update().get(pk=bot.pk)
    row = GatewaySession.objects.select_for_update().get(bot=bot)
    if (not current.is_active or credential_digest(current) != credential_digest(bot)
            or row.lease_token != token or row.lease_until <= timezone.now()):
        raise LeaseLost('Gateway lease or credentials are no longer valid')
    sequence = payload.get('s')
    if type(sequence) is not int or sequence < 0:
        raise GatewayError('Gateway dispatch lacks a valid sequence')
    event_type = payload.get('t')
    if event_type == 'READY':
        data = payload.get('d')
        session_id = data.get('session_id') if isinstance(data, dict) else None
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 200:
            raise GatewayError('Gateway READY lacks a valid session')
        row.session_id = session_id
    else:
        if not row.session_id:
            raise GatewayError('Gateway dispatch before READY or Resume')
        if row.sequence is not None and sequence <= row.sequence:
            return row
        if event_type != 'RESUMED':
            # Require the documented upstream event ID; never manufacture an
            # official event or acknowledge an event that failed durable ingestion.
            ingest_event(current, payload)
    row.sequence = sequence
    row.save(update_fields=['session_id', 'sequence'])
    return row


def gateway_url(bot, resume=False):
    status, raw, _ = get_gateway(bot)
    if status != 200:
        raise OfficialCredentialError('Gateway discovery failed')
    try:
        data = json.loads(raw)
        url = data['url']
        parts = urlsplit(url)
        if (parts.scheme != 'wss' or parts.hostname != 'api.bot.qq.com'
                or parts.port not in (None, 443) or parts.username or parts.password
                or parts.fragment or parts.query or parts.path not in {'/websocket', '/websocket/'}):
            raise ValueError
        # This worker deliberately operates [0,1], not a partially started shard set.
        limit = data['session_start_limit']
        if type(limit['remaining']) is not int or type(limit['max_concurrency']) is not int:
            raise ValueError
        if not resume and (limit['remaining'] < 1 or limit['max_concurrency'] < 1):
            raise GatewayError('Gateway session start budget exhausted')
    except (ValueError, TypeError, KeyError, AttributeError):
        raise GatewayError('Gateway discovery returned an invalid response') from None
    return url


def decode(raw):
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise GatewayError('Invalid Gateway JSON') from None
    if not isinstance(data, dict) or type(data.get('op')) is not int:
        raise GatewayError('Invalid Gateway envelope')
    return data


def send(socket, opcode, data):
    socket.send(json.dumps({'op': opcode, 'd': data}, separators=(',', ':')))


def consume_connection(bot, token):
    renew(bot, token)
    row = GatewaySession.objects.get(bot=bot, lease_token=token)
    resume = bool(row.session_id and row.sequence is not None)
    url = gateway_url(bot, resume)
    credential = 'QQBot ' + access_token(bot)
    renew(bot, token)
    with connect(url, open_timeout=10, close_timeout=5, max_size=1048576,
                 max_queue=16, ping_interval=None, proxy=settings.QQ_HTTP_PROXY) as socket:
        hello = decode(socket.recv(timeout=10))
        data = hello.get('d')
        interval = data.get('heartbeat_interval') if isinstance(data, dict) else None
        if hello['op'] != 10 or type(interval) is not int or not 1000 <= interval <= 300000:
            raise GatewayError('Invalid Gateway Hello')
        if resume:
            send(socket, 6, {'token': credential, 'session_id': row.session_id, 'seq': row.sequence})
        else:
            send(socket, 2, {'token': credential, 'intents': row.intents, 'shard': [0, 1],
                             'properties': {'$os': platform.system(), '$browser': 'qq-official-proxy',
                                            '$device': 'qq-official-proxy'}})
        interval /= 1000
        heartbeat_at = time.monotonic() + interval
        renew_at = time.monotonic() + 5
        awaiting_ack = False
        while True:
            now = time.monotonic()
            if now >= renew_at:
                renew(bot, token)
                renew_at = now + 5
            if now >= heartbeat_at:
                if awaiting_ack:
                    raise Reconnect('Gateway heartbeat acknowledgement timed out')
                send(socket, 1, row.sequence)
                awaiting_ack = True
                heartbeat_at = now + interval
            try:
                payload = decode(socket.recv(timeout=max(0.01, min(1, heartbeat_at - time.monotonic()))))
            except TimeoutError:
                continue
            opcode = payload['op']
            if opcode == 0:
                row = dispatch(bot, token, payload)
            elif opcode == 11:
                awaiting_ack = False
            elif opcode == 1:
                send(socket, 1, row.sequence)
            elif opcode == 7:
                raise Reconnect('Gateway requested reconnect')
            elif opcode == 9:
                clear_session(bot, token)
                raise Reconnect('Gateway session invalidated')
            else:
                raise GatewayError('Unexpected Gateway opcode')
