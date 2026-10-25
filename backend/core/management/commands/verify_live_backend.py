"""Persist QQ configuration via the running management HTTP API, then test HTTP relay.

Secrets stay in memory; only status booleans and local resource IDs are printed.
The configured Provider/Channel/Conversation and selected Owner's grant are retained.
"""
import json
import base64
import secrets
import subprocess
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPCookieProcessor, build_opener

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Bot, BotGrant, User
from core.official import NoRedirect
from core.services import decrypt_secret
from .verify_live_qq import credentials, TARGET

BASE = 'http://127.0.0.1:8000'
SCOPES = ['query:read', 'events:read', 'messages:send']


class LocalHTTP:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirect())
        self.csrf = None
        self.token = None

    def request(self, path, method='GET', body=None):
        headers = {'Content-Type': 'application/json', 'Origin': BASE}
        if self.csrf:
            headers['X-CSRFToken'] = self.csrf
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
            headers.pop('Origin', None)
        # Stable within this test client; repeated sending verifies cache only.
        if method == 'POST' and path.startswith('/qq/v2/groups/') and path.endswith('/messages'):
            headers['Idempotency-Key'] = self.idempotency
        request = Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=25)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(1_048_576)
            try:
                data = json.loads(raw) if raw else None
            except ValueError:
                data = None
            return response.status, data, response.headers

    def management(self, path, method='GET', body=None):
        status, data, headers = self.request(path, method, body)
        if not 200 <= status < 300:
            raise CommandError(f'Local management HTTP {method} {path} returned {status}; response redacted')
        return data


class Command(BaseCommand):
    help = 'Persist config.txt QQ Bot through localhost:8000 HTTP API and verify real backend relay'

    def add_arguments(self, parser):
        parser.add_argument('--owner', required=True, help='Existing active Owner to receive the approved-group grant')
        parser.add_argument('--send', action='store_true', help='Send one approved-group message through backend HTTP')
        parser.add_argument('--all-messages', action='store_true', help='Send one of every currently documented group message/media type')

    def handle(self, *args, **options):
        owner = User.objects.filter(username=options['owner'], role='Owner', is_active=True).first()
        if owner is None:
            raise CommandError('Specified active Owner does not exist')
        app_id, secret = credentials(Path(settings.BASE_DIR).parent / 'config.txt')
        existing = Bot.objects.filter(app_id=app_id).select_related('channel__provider').first()
        if existing and (decrypt_secret(existing) != secret or not existing.is_active
                         or existing.channel.base_url != 'https://api.bot.qq.com'):
            raise CommandError('Existing configuration differs; no existing credentials were overwritten')
        suffix = secrets.token_hex(5)
        password = secrets.token_urlsafe(32)
        bootstrap = User.objects.create_user('qq-http-qa-' + suffix, password=password, role='Owner')
        admin, relay = LocalHTTP(), LocalHTTP()
        relay.idempotency = 'backend-http-acceptance-' + suffix
        key_id = None
        report = {'real_backend_http': True, 'backend': BASE, 'other_group_operations': 0}
        try:
            admin.csrf = admin.management('/api/v1/auth/csrf/')['csrfToken']
            session = admin.management('/api/v1/auth/login/', 'POST', {'username': bootstrap.username, 'password': password})
            admin.csrf = session['csrfToken']
            if existing:
                provider = admin.management(f'/api/v1/providers/{existing.channel.provider_id}/')
                channel = next(row for row in provider['channels'] if row['bot_id'] == existing.pk)
            else:
                provider = admin.management('/api/v1/providers/', 'POST', {
                    'name': 'QQ 官方机器人', 'channels': [{'name':'QQ 官机', 'interface_type':'qq_official_websocket',
                    'base_url':'https://api.bot.qq.com', 'app_id':app_id, 'secret':secret, 'is_active':True,
                    'models':[{'name':'批准测试群','isDirect':False,'groupid':TARGET}]}]})
                channel = provider['channels'][0]
            models = channel['models']
            conversation = next((row for row in models if row.get('groupid') == TARGET and not row['isDirect']), None)
            if conversation is None:
                # Append only the approved conversation and preserve all other saved fields.
                channel['models'].append({'name':'批准测试群','isDirect':False,'groupid':TARGET})
                provider = admin.management(f'/api/v1/providers/{provider["id"]}/', 'PATCH', {
                    'name':provider['name'], 'channels':provider['channels']})
                channel = next(row for row in provider['channels'] if row['bot_id'] == existing.pk)
                conversation = next(row for row in channel['models'] if row.get('groupid') == TARGET and not row['isDirect'])
            bot_id = channel['bot_id']
            report.update(provider_id=provider['id'], channel_id=channel['id'], bot_id=bot_id, conversation_id=conversation['id'],
                          configuration_retained=True)
            grant_scopes = SCOPES + (['media:upload'] if options['all_messages'] else [])
            grant_body = {'bot':bot_id,'scopes':grant_scopes,'all_conversations':False,'conversations':[conversation['id']]}
            if not BotGrant.objects.filter(user=owner, bot_id=bot_id).exists():
                admin.management('/api/v1/grants/', 'POST', {**grant_body,'user':owner.pk})
            report['owner_grant_present'] = True
            admin.management('/api/v1/grants/', 'POST', {**grant_body,'user':bootstrap.pk})
            key = admin.management('/api/v1/keys/', 'POST', {**grant_body,'scopes':SCOPES,'name':'Temporary backend HTTP acceptance'})
            key_id, relay.token = key['id'], key['token']
            first = admin.management(f'/api/v1/keys/{key_id}/copy/', 'POST', {})
            second = admin.management(f'/api/v1/keys/{key_id}/copy/', 'POST', {})
            report['same_token_copy'] = first['token'] == second['token'] == relay.token
            admin.management(f'/api/v1/keys/{key_id}/', 'PATCH', {'name':'Backend HTTP acceptance edited'})
            report['same_token_after_edit'] = admin.management(f'/api/v1/keys/{key_id}/copy/', 'POST', {})['token'] == relay.token
            status, identity, _ = relay.request('/qq/users/@me')
            report['official_identity_http'] = status
            report['official_identity_valid'] = status == 200 and isinstance(identity, dict) and bool(identity.get('id'))
            report['unidentifiable_target_rejected'] = relay.request('/qq/users/@me/dms', 'POST', {})[0] == 403
            report['missing_media_scope_rejected'] = relay.request(f'/qq/v2/groups/{TARGET}/files', 'POST', {'srv_send_msg':False})[0] == 403
            report['event_list_http'] = relay.request('/relay/v1/events/')[0]
            if options['all_messages'] and report['official_identity_valid']:
                admin.management(f'/api/v1/keys/{key_id}/', 'PATCH', {'scopes':grant_scopes})
                self.verify_message_types(relay, suffix, report)
            if options['send'] and report['official_identity_valid']:
                path = f'/qq/v2/groups/{TARGET}/messages'
                payload = {'content':'QQ Bot Proxy 后端 HTTP 链路验收（仅此一条）','msg_type':0}
                status, result, _ = relay.request(path, 'POST', payload)
                report['send_http'] = status
                report['send_message_id_returned'] = isinstance(result, dict) and bool(result.get('id'))
                if 200 <= status < 300:
                    replay_status, _, headers = relay.request(path, 'POST', payload)
                    report['idempotent_replay'] = replay_status == status and headers.get('Idempotency-Replayed') == 'true'
                elif isinstance(result, dict):
                    report['send_official_code'] = result.get('code', result.get('err_code'))
        except (URLError, OSError, ValueError):
            report['transport_error'] = True
            raise CommandError('Local backend HTTP unavailable; details redacted') from None
        finally:
            if key_id is not None:
                try:
                    admin.management(f'/api/v1/keys/{key_id}/revoke/', 'POST', {})
                    report['revoked_key_rejected'] = relay.request('/relay/v1/events/')[0] == 401
                except (CommandError, URLError, OSError):
                    report['revoke_http_failed'] = True
            bootstrap.delete()
            report['temporary_account_cleaned'] = True
            self.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))

    def verify_message_types(self, relay, suffix, report):
        from core.live_message_cases import synthetic_media, synthetic_video
        rows = []
        report['message_types'] = rows
        def result_row(name, stage, status, result):
            row = {'type':name,'stage':stage,'http':status,
                   'accepted':200 <= status < 300,
                   'message_id_returned':isinstance(result,dict) and bool(result.get('id'))}
            if isinstance(result,dict):
                for field in ('code','err_code'):
                    if type(result.get(field)) is int:
                        row[field] = result[field]
            rows.append(row)
            self.stdout.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
            self.stdout.flush()
            return row
        def send_case(name, payload):
            relay.idempotency = 'backend-types-' + suffix + '-' + name
            status, result, _ = relay.request(f'/qq/v2/groups/{TARGET}/messages', 'POST', payload)
            row = result_row(name, 'send', status, result)
            if row['accepted']:
                cached_status, _, headers = relay.request(f'/qq/v2/groups/{TARGET}/messages', 'POST', payload)
                row['idempotent_replay'] = cached_status == status and headers.get('Idempotency-Replayed') == 'true'
            return result if row['accepted'] and isinstance(result,dict) else {}
        text = send_case('text', {'msg_type':0,'content':'QQ Bot Proxy 类型验收：纯文本'})
        send_case('markdown', {'msg_type':2,'markdown':{'content':'# QQ Bot Proxy 类型验收\n\n这是一条 **Markdown** 测试消息。'}})
        send_case('keyboard', {'msg_type':2,'markdown':{'content':'QQ Bot Proxy 类型验收：内嵌键盘'},
                  'keyboard':{'content':{'rows':[{'buttons':[{'id':'qa-command',
                  'render_data':{'label':'验收测试','style':1},'action':{'type':2,'permission':{'type':2},
                  'data':'/验收测试','enter':False}}]}]}}})
        reference = text.get('ext_info', {}).get('ref_idx')
        if reference:
            send_case('reference', {'msg_type':0,'content':'QQ Bot Proxy 类型验收：引用上一条测试文本',
                                   'message_reference':{'message_id':reference}})
        else:
            rows.append({'type':'reference','stage':'context','accepted':False,'blocked':'official_response_has_no_ref_idx'})
        media = synthetic_media()
        try:
            media['video'] = synthetic_video()
        except (ImportError, OSError, subprocess.SubprocessError):
            rows.append({'type':'video','stage':'fixture','accepted':False,'blocked':'optional_ffmpeg_fixture_unavailable'})
        for name in ('image','video','voice','file'):
            if name not in media:
                continue
            file_type, filename, data = media[name]
            if len(data) > 500_000:
                raise CommandError('Synthetic media fixture exceeds bounded upload budget')
            status, uploaded, _ = relay.request(f'/qq/v2/groups/{TARGET}/files', 'POST', {
                'file_type':file_type,'file_name':filename,'file_data':base64.b64encode(data).decode(), 'srv_send_msg':False})
            result_row(name, 'upload', status, uploaded)
            info = uploaded.get('file_info') if isinstance(uploaded,dict) else None
            if 200 <= status < 300 and isinstance(info,str) and info:
                send_case(name, {'msg_type':7,'media':{'file_info':info}})
        report['not_documented_for_group'] = ['ark','embed','streaming']
