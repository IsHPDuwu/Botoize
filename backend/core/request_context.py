"""Request correlation and best-effort data-plane audit utilities."""
import re
import time
from uuid import uuid4

from .models import ApiCallAudit

REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,64}$')


def audit_path(request, match):
    """Allowlisted templates only: never persist arbitrary paths or identifiers."""
    from .official_routes import ID, OPERATIONS

    path = (getattr(match, 'kwargs', None) or {}).get('path', '')
    if request.path.startswith('/onebot/'):
        from .onebot import ACTIONS11, ACTIONS12, EXTENSIONS
        action = getattr(request, 'onebot_action', path.rstrip('/'))
        prefix = '/onebot/v12/' if request.path.startswith('/onebot/v12') else '/onebot/'
        return prefix + (action if action in ACTIONS11 | ACTIONS12 | EXTENSIONS else '<unsupported>')
    if request.path.startswith('/qq/'):
        templates = ['users/@me', 'users/@me/dms']
        for kind, identifier in [('v2/users', 'user_id'), ('v2/groups', 'group_id'),
                                 ('channels', 'channel_id'), ('dms', 'guild_id')]:
            base = kind + '/{' + identifier + '}'
            templates.extend([base + '/messages', base + '/messages/{message_id}'])
            if kind.startswith('v2/'):
                templates.extend(base + '/' + suffix for suffix in
                                 ['files', 'upload_prepare', 'upload_part_finish'])
        templates.extend(template for _, template, _ in OPERATIONS)
        for template in templates:
            pattern = re.sub(r'\{\w+\}', lambda match: r'[A-Za-z0-9_.=+-]{1,256}'
                             if match[0] == '{message_id}' else ID, template)
            if re.fullmatch(pattern, path):
                return '/qq/' + template
        return '/qq/<unsupported>'
    return getattr(match, 'route', None) or '<unmatched>'


def onebot_message_type(action, params, version=11):
    """Fixed labels only; never put segment data or arbitrary type names in logs."""
    if action not in {'send_message', 'send_msg', 'send_private_msg', 'send_group_msg'} or not isinstance(params, dict):
        return ''
    segments = params.get('message')
    if version == 11:
        from .onebot import segments11
        try:
            segments = segments11(segments, params.get('auto_escape', False))
        except Exception:
            return ''
    if not isinstance(segments, list):
        return ''
    labels = {'text': 'text', 'image': 'image', 'video': 'video', 'record': 'audio', 'voice': 'audio',
              'file': 'file', 'botoize.file': 'file', 'reply': 'reference', 'qq.markdown': 'markdown',
              'qq.keyboard': 'keyboard', 'qq.ark': 'ark', 'qq.embed': 'embed'}
    found = []
    for segment in segments:
        if isinstance(segment, dict) and isinstance(segment.get('type'), str):
            label = labels.get(segment['type'])
            if label and label not in found:
                found.append(label)
    if 'qq.reply_to' in params and 'reference' not in found:
        found.append('reference')
    label = '+'.join(found)
    return label if len(label) <= 32 else 'mixed'


def audit_message_type(request, path):
    """Read already-parsed data only; logging must not parse a rejected request."""
    if request.method != 'POST':
        return ''
    if path.startswith('/onebot/'):
        envelope = getattr(request, 'onebot_envelope', None)
        if envelope is not None:
            return onebot_message_type(envelope['action'], envelope['params'], 12)
        data = getattr(request, '_full_data', None)
        if not isinstance(data, dict):
            data = getattr(request, 'query_params', {})
        return onebot_message_type(path.rsplit('/', 1)[-1], data.dict() if hasattr(data, 'dict') else dict(data))
    data = getattr(request, '_full_data', None)
    if not isinstance(data, dict):
        return ''
    if path.endswith('/files'):
        return {1: 'image', 2: 'video', 3: 'audio', 4: 'file'}.get(
            data.get('file_type') if type(data.get('file_type')) is int else None, '')
    if not path.endswith('/messages'):
        return ''
    kind = data.get('msg_type')
    label = {0: 'text', 1: 'mixed', 2: 'markdown', 3: 'ark', 4: 'embed', 7: 'media'}.get(
        kind if type(kind) is int else None, '')
    if 'keyboard' in data and label:
        label += '+keyboard'
    if 'message_reference' in data or (isinstance(data.get('ext_info'), dict)
                                    and 'ref_idx' in data['ext_info']):
        label = (label + '+reference') if label else 'reference'
    return label


def request_id_from_header(value):
    if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


def persist_api_call(request, response, started_at):
    auth = getattr(request, 'auth', None)
    key = auth if getattr(auth, '_meta', None) and auth._meta.model_name == 'apikey' else None
    bot = getattr(auth, 'bot', None) if key is not None else None
    user = key.user if key is not None else None
    duration_ms = max(0, min(2_147_483_647, int((time.monotonic() - started_at) * 1000)))
    try:
        django_request = getattr(request, '_request', request)
        match = getattr(django_request, 'resolver_match', None)
        route = audit_path(request, match)
        ApiCallAudit.objects.create(
            api_key=key,
            user=user,
            bot=bot,
            bot_name=bot.name if bot else '',
            username=user.username if user else '',
            key_name=key.name if key else '',
            request_id=getattr(django_request, 'request_id', ''),
            method=request.method[:10],
            path=route[:512],
            message_type=audit_message_type(request, route),
            replayed=response.get('Idempotency-Replayed') == 'true',
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    except Exception:
        # Audit availability must not change the upstream proxy response.
        pass


class DataPlaneAuditMixin:
    def dispatch(self, request, *args, **kwargs):
        started_at = time.monotonic()
        response = super().dispatch(request, *args, **kwargs)
        persist_api_call(self.request, response, started_at)
        return response
