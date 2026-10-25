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
        action = path.rstrip('/')
        return '/onebot/' + (action if action in {
            'get_login_info', 'send_private_msg', 'send_group_msg',
        } else '<unsupported>')
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
            pattern = re.sub(r'\{\w+\}', lambda match: r'[A-Za-z0-9_-]{1,256}'
                             if match[0] == '{message_id}' else ID, template)
            if re.fullmatch(pattern, path):
                return '/qq/' + template
        return '/qq/<unsupported>'
    return getattr(match, 'route', None) or '<unmatched>'


def audit_message_type(request, path):
    """Read already-parsed data only; logging must not parse a rejected request."""
    if request.method != 'POST':
        return ''
    if path in {'/onebot/send_private_msg', '/onebot/send_group_msg'}:
        return 'text'
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
