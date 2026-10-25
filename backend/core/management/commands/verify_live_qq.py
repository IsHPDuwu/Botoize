"""Bounded, redacted real QQ acceptance, restricted to the approved group."""
import json
import re
import secrets
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed
from rest_framework.test import APIClient

from core.models import Bot, BotGrant, Channel, Conversation, Provider, User
from core.services import encrypt_secret, decrypt_secret
from core.official import access_token, get_self, OfficialCredentialError
from core.gateway import gateway_url, decode, send, GatewayError
from core.events import ingest_event

TARGET = '36407554EC2084AF78BB2ECFC5820ACE'


def credentials(path):
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*(id|app_?id|secret|app_?secret|type)\s*[:=：]\s*(.*?)\s*', line, re.I)
        if match:
            key = match[1].lower().replace('_', '')
            values[key] = match[2].strip('"\'')
    app_id = values.get('appid', values.get('id'))
    secret = values.get('appsecret', values.get('secret'))
    # The local config may explicitly refer to the adjacent one-line secret file.
    if secret and 'SECRET.txt' in secret:
        secret = (path.parent / 'SECRET.txt').read_text(encoding='utf-8-sig').strip()
    if not app_id or not secret:
        raise CommandError('config.txt must contain id/AppID and secret/AppSecret; values were not logged')
    if any(char.isspace() for char in app_id + secret) or not (app_id + secret).isascii():
        raise CommandError('Credentials contain whitespace or non-ASCII text; check the referenced local secret file')
    return app_id, secret


class Command(BaseCommand):
    help = 'Real QQ verification using config.txt; no other group or destructive operations'

    def add_arguments(self, parser):
        parser.add_argument('--send', action='store_true', help='Send exactly one plain-text test message to the approved group')
        parser.add_argument('--listen-seconds', type=int, default=20)

    def handle(self, *args, **options):
        if not 0 <= options['listen_seconds'] <= 60:
            raise CommandError('listen-seconds must be between 0 and 60')
        app_id, secret = credentials(Path(settings.BASE_DIR).parent / 'config.txt')
        suffix = secrets.token_hex(5)
        user = provider = channel = created_bot = created_conversation = None
        management = client = key_id = None
        report = {'target': TARGET, 'real_network': True, 'other_group_operations': 0}
        try:
            bot = Bot.objects.filter(app_id=app_id).select_related('channel').first()
            if bot:
                if bot.channel.base_url != 'https://api.bot.qq.com' or decrypt_secret(bot) != secret or not bot.is_active:
                    raise CommandError('Existing Bot differs from config or is inactive; no existing configuration was changed')
            else:
                provider = Provider.objects.create(name='Temporary QQ acceptance ' + suffix)
                channel = Channel.objects.create(provider=provider, name='Temporary QQ Bot ' + suffix)
                created_bot = bot = Bot.objects.create(channel=channel, name=channel.name, app_id=app_id,
                                                       encrypted_secret=encrypt_secret(secret))
            user = User.objects.create_user('qq-live-qa-' + suffix, password=secrets.token_urlsafe(32), role='Admin')
            conversation, added = Conversation.objects.get_or_create(bot=bot, is_direct=False, target_id=TARGET)
            if added:
                created_conversation = conversation
            grant = BotGrant.objects.create(user=user, bot=bot, scopes=['query:read', 'events:read', 'messages:send'], all_conversations=False)
            grant.conversations.add(conversation)
            management = APIClient(HTTP_HOST='127.0.0.1')
            management.force_login(user)
            response = management.post('/api/v1/keys/', {'bot': bot.pk, 'name': 'Temporary real QQ acceptance',
                         'scopes': grant.scopes, 'all_conversations': False, 'conversations': [conversation.pk]}, format='json')
            if response.status_code != 201:
                raise CommandError('Temporary scoped Key creation failed')
            key_id, token = response.data['id'], response.data['token']
            report['scoped_key_created'] = True
            copies = [management.post(f'/api/v1/keys/{key_id}/copy/', {}, format='json') for _ in range(2)]
            report['same_token_copy'] = all(row.status_code == 200 and row.data['token'] == token for row in copies)
            client = APIClient(HTTP_HOST='127.0.0.1')
            client.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
            # Unknown-target APIs fail locally, without enumerating any other group.
            report['unidentifiable_target_rejected'] = client.post('/qq/users/@me/dms', {}, format='json').status_code == 403
            report['network_stage'] = 'identity'
            status, body, _ = get_self(bot)
            report['official_token_obtained'] = True
            report['official_identity_http'] = status
            report['official_identity_valid'] = status == 200 and isinstance(json.loads(body), dict) and 'id' in json.loads(body)
            if not report['official_identity_valid']:
                identity = json.loads(body)
                report['official_identity_code'] = identity.get('code')
                report['official_identity_err_code'] = identity.get('err_code')
                if identity.get('err_code') == 40023002:
                    report['official_identity_reason'] = 'source_ip_not_allowlisted'
                    raise OfficialCredentialError('Official source IP not allowlisted', status=status, code=identity.get('code'))
            report['network_stage'] = 'gateway'
            websocket_url = gateway_url(bot)
            auth = 'QQBot ' + access_token(bot)
            session_id = None
            sequence = None
            context_id = None
            received = 0
            report['gateway_ready'] = False
            with connect(websocket_url, open_timeout=10, close_timeout=5, max_size=1048576,
                         max_queue=16, ping_interval=None, proxy=settings.QQ_HTTP_PROXY) as socket:
                hello = decode(socket.recv(timeout=10))
                report['gateway_hello'] = hello['op'] == 10
                interval = hello.get('d', {}).get('heartbeat_interval', 30000) / 1000
                send(socket, 2, {'token': auth, 'intents': 1 << 25, 'shard': [0, 1],
                                'properties': {'$os': 'windows', '$browser': 'qq-proxy-acceptance', '$device': 'qq-proxy-acceptance'}})
                deadline = time.monotonic() + max(10, options['listen_seconds'])
                heartbeat = time.monotonic() + min(interval, 10)
                while time.monotonic() < deadline:
                    if time.monotonic() >= heartbeat:
                        send(socket, 1, sequence)
                        heartbeat = time.monotonic() + interval
                    try:
                        payload = decode(socket.recv(timeout=min(1, max(0.1, deadline - time.monotonic()))))
                    except TimeoutError:
                        continue
                    if payload['op'] == 11:
                        report['heartbeat_ack'] = True
                    if payload['op'] != 0:
                        continue
                    if type(payload.get('s')) is int:
                        sequence = payload['s']
                    data = payload.get('d', {})
                    if payload.get('t') == 'READY':
                        session_id = data.get('session_id')
                        report['gateway_ready'] = bool(session_id)
                        self.stdout.write('QQ Gateway READY; listening only for the approved group (payloads redacted)')
                    elif payload.get('t') in ('GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE') and data.get('group_openid') == TARGET:
                        context_id = data.get('id')
                        ingest_event(bot, payload)
                        received += 1
                    if received and report['gateway_ready']:
                        break
                if session_id and sequence is not None:
                    send(socket, 1, sequence)
                    for _ in range(3):
                        payload = decode(socket.recv(timeout=5))
                        if payload['op'] == 11:
                            report['heartbeat_ack'] = True
                            break
            report['target_events_received'] = received
            if session_id and sequence is not None:
                with connect(websocket_url, open_timeout=10, close_timeout=5, max_size=1048576,
                             ping_interval=None, proxy=settings.QQ_HTTP_PROXY) as resumed:
                    hello = decode(resumed.recv(timeout=10))
                    send(resumed, 6, {'token': auth, 'session_id': session_id, 'seq': sequence})
                    for _ in range(5):
                        payload = decode(resumed.recv(timeout=5))
                        if payload.get('t') == 'RESUMED':
                            report['gateway_resumed'] = True
                            break
                        if payload['op'] == 9:
                            report['gateway_resumed'] = False
                            break
            if options['send']:
                report['network_stage'] = 'send'
                payload = {'content': 'QQ Bot Proxy 连通性验收测试（仅此一条）', 'msg_type': 0}
                if context_id:
                    payload.update(msg_id=context_id, msg_seq=1)
                response = client.post(f'/qq/v2/groups/{TARGET}/messages', payload, format='json',
                                       HTTP_IDEMPOTENCY_KEY='live-acceptance-' + suffix)
                report['send_http'] = response.status_code
                try:
                    result = json.loads(response.content)
                except ValueError:
                    result = {}
                report['send_message_id_returned'] = bool(result.get('id'))
                report['send_official_code'] = result.get('code', result.get('err_code'))
                report['send_used_message_context'] = bool(context_id)
                if 200 <= response.status_code < 300:
                    replay = client.post(f'/qq/v2/groups/{TARGET}/messages', payload, format='json',
                                         HTTP_IDEMPOTENCY_KEY='live-acceptance-' + suffix)
                    report['send_idempotent_replay'] = replay.get('Idempotency-Replayed') == 'true'
            page = client.get('/relay/v1/events/').data
            report['target_event_relay_count'] = len(page.get('events', []))
        except (OfficialCredentialError, GatewayError, ConnectionClosed, OSError, TimeoutError, ValueError) as exc:
            report['network_error_type'] = type(exc).__name__
            if isinstance(exc, OfficialCredentialError):
                report['credential_http'] = exc.status
                report['credential_code'] = exc.code
            # Raw exceptions can contain a request/token; print only class and close code.
            if isinstance(exc, ConnectionClosed):
                report['gateway_close_code'] = exc.rcvd.code if exc.rcvd else None
        finally:
            if management is not None and client is not None and key_id is not None:
                management.post(f'/api/v1/keys/{key_id}/revoke/', {}, format='json')
                report['revoked_key_rejected'] = client.get('/relay/v1/events/').status_code == 401
            if user:
                user.delete()
            if created_conversation:
                created_conversation.delete()
            if created_bot:
                created_bot.delete()
            if channel:
                channel.delete()
            if provider:
                provider.delete()
            report['temporary_resources_cleaned'] = True
        self.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))
