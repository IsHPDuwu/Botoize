"""Read-only real HTTP/WS acceptance; never sends or moderates a QQ group."""
import asyncio
import base64
import json
import secrets

from django.core.management.base import BaseCommand, CommandError
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from core.models import Bot, User
from .verify_live_backend import LocalHTTP
from .verify_live_qq import TARGET


class Command(BaseCommand):
    help = 'Verify OneBot 11/12 through localhost:8000 with temporary Session/CSRF grant and key; no QQ sends'

    def add_arguments(self, parser):
        parser.add_argument('--bot', type=int, required=True)

    def handle(self, *args, **options):
        bot = Bot.objects.filter(pk=options['bot'], is_active=True).first()
        if bot is None:
            raise CommandError('Active Bot required')
        conversation = bot.conversations.filter(is_direct=False, target_id=TARGET).first()
        if conversation is None:
            raise CommandError('Approved test group must already be configured')
        suffix, password = secrets.token_hex(5), secrets.token_urlsafe(32)
        bootstrap = User.objects.create_user('onebot-qa-' + suffix, password=password, role='Owner')
        admin, relay = LocalHTTP(), LocalHTTP()
        key_id = None
        report = {'real_http_ws': True, 'qq_sends': 0, 'qq_moderation_actions': 0}
        try:
            admin.csrf = admin.management('/api/v1/auth/csrf/')['csrfToken']
            session = admin.management('/api/v1/auth/login/', 'POST', {'username': bootstrap.username, 'password': password})
            admin.csrf = session['csrfToken']
            policy = {'bot': bot.pk, 'all_conversations': False, 'conversations': [conversation.pk]}
            scopes = ['query:read', 'events:read', 'media:upload', 'groups:read']
            admin.management('/api/v1/grants/', 'POST', {**policy, 'user': bootstrap.pk, 'scopes': scopes})
            issued = admin.management('/api/v1/keys/', 'POST', {**policy, 'name': 'OneBot no-send acceptance', 'scopes': scopes})
            key_id, relay.token = issued['id'], issued['token']

            def call(action, params=None):
                status, response, _ = relay.request('/onebot/v12/', 'POST', {'action': action, 'params': params or {}})
                if status != 200 or not isinstance(response, dict):
                    raise CommandError('OneBot 12 HTTP protocol failed; response redacted')
                return response

            v11_status, v11, _ = relay.request('/onebot/v11/get_login_info')
            report['v11_identity'] = v11_status == 200 and v11.get('retcode') == 0 and type(v11['data']['user_id']) is int
            v12 = call('get_self_info')
            report['v12_string_identity'] = v12.get('retcode') == 0 and isinstance(v12['data']['user_id'], str)
            report['v12_version'] = call('get_version')['data']['onebot_version'] == '12'
            report['v12_action_discovery'] = 'send_message' in call('get_supported_actions')['data']
            report['v12_poll'] = call('get_latest_events')['retcode'] == 0
            report['known_authorized_conversation'] = call('botoize.get_known_conversations')['data'] == [
                {'is_direct': False, 'id': TARGET, 'name': conversation.name}]
            report['unsupported_is_explicit'] = call('send_like')['retcode'] == 10002
            report['send_scope_rejected'] = call('send_message', {'detail_type': 'group', 'group_id': TARGET,
                'message': [{'type': 'text', 'data': {'text': 'MUST NOT SEND'}}]})['retcode'] == 35003
            uploaded = call('upload_file', {'type': 'data', 'name': 'acceptance.txt', 'data': base64.b64encode(b'local-only').decode()})
            fid = uploaded['data']['file_id']
            report['local_file_roundtrip'] = call('get_file', {'file_id': fid, 'type': 'data'})['data']['data'] == base64.b64encode(b'local-only').decode()
            report['no_server_path'] = call('upload_file', {'type': 'path', 'name': 'secret', 'path': 'config.txt'})['retcode'] == 10004
            # This is a read-only call, confined to the already-approved group.
            group = call('get_group_info', {'group_id': TARGET})
            report['group_info_retcode'] = group['retcode']
            report['group_info_available'] = group['retcode'] == 0

            async def verify_ws():
                headers = {'Authorization': 'Bearer ' + relay.token}
                for version in [11, 12]:
                    async with connect(f'ws://127.0.0.1:8000/onebot/v{version}/', additional_headers=headers,
                                       proxy=None, open_timeout=10) as ws:
                        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
                        if version == 12:
                            assert first['detail_type'] == 'connect'
                            assert json.loads(await asyncio.wait_for(ws.recv(), 10))['detail_type'] == 'status_update'
                        else:
                            assert first['meta_event_type'] == 'lifecycle'
                        await ws.send(json.dumps({'action': 'get_version' if version == 12 else 'get_version_info', 'params': {}, 'echo': 'acceptance'}))
                        response = json.loads(await asyncio.wait_for(ws.recv(), 10))
                        report[f'v{version}_universal_ws'] = response['retcode'] == 0 and response['echo'] == 'acceptance'
                        if version == 12:
                            # Exercise a real >1 MiB frame; no QQ upload or message send.
                            encoded = base64.b64encode(b'x' * (1024 * 1024 + 1)).decode()
                            await ws.send(json.dumps({'action': 'upload_file', 'params': {
                                'type': 'data', 'name': 'ws-local-only.bin', 'data': encoded,
                            }, 'echo': 'large-local-upload'}))
                            uploaded = json.loads(await asyncio.wait_for(ws.recv(), 10))
                            report['ws_large_local_file'] = uploaded['retcode'] == 0 and uploaded['echo'] == 'large-local-upload'
                            admin.management(f'/api/v1/keys/{key_id}/revoke/', 'POST', {})
                            try:
                                await asyncio.wait_for(ws.recv(), 5)
                                report['ws_live_revocation'] = False
                            except ConnectionClosed as exc:
                                report['ws_live_revocation'] = exc.code == 4403
                report['revoked_http_401'] = relay.request('/onebot/v12/', 'POST', {'action': 'get_version', 'params': {}})[0] == 401
            asyncio.run(verify_ws())
        except Exception as exc:
            raise CommandError('OneBot acceptance failed: ' + type(exc).__name__ + '; details redacted') from None
        finally:
            if key_id:
                try:
                    admin.management(f'/api/v1/keys/{key_id}/revoke/', 'POST', {})
                except Exception:
                    pass
            bootstrap.delete()
            report['temporary_account_cleaned'] = True
        self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
        if any(value is False for name, value in report.items() if name != 'group_info_available'):
            raise CommandError('OneBot acceptance checks failed; see boolean report')
