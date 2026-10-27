"""Exercise running console HTTP and supervised workers against synthetic local OneBot peers."""
import json
import secrets
import socket
import threading
import time

import uvicorn
from django.core.management.base import BaseCommand, CommandError

from core.models import AuditLog, Bot, Channel, Provider, User
from .verify_live_backend import LocalHTTP


class Peer:
    def __init__(self, version, own_id):
        self.version, self.own_id = version, own_id
        self.connections = 0

    def response(self, value, path):
        action = value.get('action', path.rsplit('/', 1)[-1])
        own = {'platform': 'synthetic', 'user_id': self.own_id}
        data = {'get_login_info': {'user_id': int(self.own_id) if self.version == 11 else 0, 'nickname': 'Synthetic'},
                'get_status': {'good': True, 'online': True} if self.version == 11 else {'good': True, 'bots': [{'self': own, 'online': True}]},
                'get_self_info': {'user_id': self.own_id, 'user_name': 'Synthetic'}}
        return {'status': 'ok', 'retcode': 0, 'data': data.get(action, {}), 'echo': value.get('echo')}

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            body = b''
            while True:
                frame = await receive()
                body += frame.get('body', b'')
                if not frame.get('more_body'):
                    break
            result = self.response(json.loads(body or b'{}'), scope['path'])
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/json')]})
            await send({'type': 'http.response.body', 'body': json.dumps(result).encode()})
        elif scope['type'] == 'websocket':
            await receive()
            await send({'type': 'websocket.accept'})
            self.connections += 1
            while True:
                frame = await receive()
                if frame['type'] == 'websocket.disconnect':
                    break
                if frame.get('text'):
                    await send({'type': 'websocket.send', 'text': json.dumps(self.response(json.loads(frame['text']), scope['path']))})


class Command(BaseCommand):
    help = 'Verify localhost:8000 Channel identity and reconnect for OneBot 11/12 HTTP and WS; synthetic peers only'

    def handle(self, *args, **options):
        suffix, password = secrets.token_hex(5), secrets.token_urlsafe(32)
        owner = User.objects.create_user('connections-qa-' + suffix, password=password, role='Owner')
        http, report = LocalHTTP(), []
        try:
            http.csrf = http.management('/api/v1/auth/csrf/')['csrfToken']
            http.csrf = http.management('/api/v1/auth/login/', 'POST', {'username': owner.username, 'password': password})['csrfToken']
            for version in (11, 12):
                for transport in ('http', 'ws'):
                    result = self.verify(http, version, transport, suffix)
                    report.append(result)
                    self.stdout.write(json.dumps(result))
                    self.stdout.flush()
        finally:
            if http.csrf:
                try:
                    http.management('/api/v1/auth/logout/', 'POST', {})
                except Exception:
                    pass
            AuditLog.objects.filter(actor=owner.username).delete()
            owner.delete()
        self.stdout.write(json.dumps({'running_backend_http': True, 'cases': report, 'real_qq_operations': 0}))

    def verify(self, http, version, transport, suffix):
        own_id = str(secrets.randbelow(10**11) + 10**11) if version == 11 else 'synthetic:' + suffix + ':' + transport
        peer = Peer(version, own_id)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(peer, lifespan='off', log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        provider_id = channel_id = bot_id = None
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if time.monotonic() >= deadline:
                    raise CommandError('Synthetic peer did not start')
                time.sleep(.1)
            provider = http.management('/api/v1/providers/', 'POST', {'name': 'Connections QA ' + suffix,
                'channels': [{'name': 'Synthetic', 'interface_type': f'onebot_v{version}',
                    'app_id': own_id, 'base_url': f'{transport}://127.0.0.1:{listener.getsockname()[1]}',
                    'is_active': True, 'models': []}]})
            provider_id = provider['id']
            channel = provider['channels'][0]
            channel_id, bot_id = channel['id'], channel['bot_id']
            ids = http.management(f'/api/v1/channels/{channel_id}/identity/', 'POST', {})
            assert ids['onebot12'] == own_id and isinstance(ids['onebot11'], int)
            for attempt in range(2):
                before = peer.connections
                http.management(f'/api/v1/channels/{channel_id}/reconnect/', 'POST', {})
                deadline = time.monotonic() + 90
                while True:
                    row = next(row for row in http.management('/api/v1/channels/status/') if row['channel'] == channel_id)
                    if (row['connection_state'] == 'connected' and peer.connections > before
                            and row['reconnect_processed_at'] and row['reconnect_processed_at'] >= row['reconnect_requested_at']):
                        break
                    if time.monotonic() >= deadline:
                        from core.models import ChannelConnectionRequest, OneBotUpstreamSession
                        control = ChannelConnectionRequest.objects.get(channel_id=channel_id)
                        raise CommandError(f'OneBot {version} {transport} reconnect {attempt + 1} did not complete: '
                            f"state={row['connection_state']}, sockets={peer.connections}, "
                            f'processed={control.processed_generation}/{control.generation}, error={control.error_code}, '
                            f'worker={OneBotUpstreamSession.objects.filter(bot_id=bot_id).exists()}')
                    time.sleep(2)
            return {'version': version, 'transport': transport, 'identity': True, 'initial_connection': True, 'manual_reconnect': True}
        finally:
            # Only this command's synthetic resources are disabled/deleted.
            if bot_id:
                Bot.objects.filter(pk=bot_id).update(is_active=False)
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=3)
            listener.close()
            if bot_id:
                # Worker sees disabled Channel on its next renewal before cleanup.
                from core.models import OneBotUpstreamSession
                deadline = time.monotonic() + 15
                while OneBotUpstreamSession.objects.filter(bot_id=bot_id, lease_token__isnull=False).exists() and time.monotonic() < deadline:
                    time.sleep(.2)
                Bot.objects.filter(pk=bot_id).delete()
            if channel_id:
                Channel.objects.filter(pk=channel_id).delete()
            if provider_id:
                Provider.objects.filter(pk=provider_id).delete()
