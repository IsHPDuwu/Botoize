"""Optional official Markdown attempt. The caller's text and original body stay intact."""
import copy
import json
import re
from html import escape


# Current QQ text-interaction syntax; accept the older syntax at the boundary too.
MENTION = re.compile(r'<qqbot-at-user\s+id=[\"\']([A-Za-z0-9_.=+-]{1,256})[\"\']\s*/>'
    r'|<qqbot-at-everyone\s*/>|<@!?([A-Za-z0-9_.=+-]{1,256})>'
    r'|(?<![\w@])@everyone(?!\w)')


def mention_text(text, *, literal=False):
    def plain(value):
        if not literal:
            return value
        value = escape(value, quote=False)
        return re.sub(r'([\\`*_{}\[\]()#+\-.!|~])', r'\\\1', value)
    output, start = [], 0
    for match in MENTION.finditer(text):
        output.append(plain(text[start:match.start()]))
        user = match[1] or match[2]
        output.append(f'<qqbot-at-user id="{user}" />' if user else '<qqbot-at-everyone />')
        start = match.end()
    output.append(plain(text[start:]))
    return ''.join(output)


def markdown_body(path, body, *, media_type=None, prefer=True):
    try:
        data = json.loads(body)
    except (TypeError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or 'markdown' in data or not isinstance(data.get('content'), str):
        return None
    text = data['content']
    if not text:
        return None
    has_mention = bool(MENTION.search(text))
    if not prefer and not has_mention:
        return None
    group = path.startswith('v2/')
    if group and data.get('msg_type', 0) not in {0, 7}:
        return None
    if group and data.get('msg_type') == 7 and (media_type or data.get('botoize_media_type')) != 'image':
        return None
    if not group and any(k in data for k in ('ark', 'embed', 'file_image')):
        return None
    converted = copy.deepcopy(data)
    converted.pop('botoize_media_type', None)
    converted.pop('content', None)
    converted['markdown'] = {'content': mention_text(text, literal=not prefer) if has_mention else text}
    if group:
        converted['msg_type'] = 2
    return json.dumps(converted, ensure_ascii=False).encode()


def handle_digest(path, info):
    import hashlib
    return hashlib.sha256((path.rsplit('/', 1)[0] + ':' + info).encode()).hexdigest()


def remember_upload(bot, path, body, result):
    from datetime import timedelta
    from django.utils import timezone
    from .models import OfficialMediaHandle
    try:
        request = json.loads(body)
        response = json.loads(result[1])
        kind, info = request.get('file_type'), response.get('file_info')
        if (not 200 <= result[0] < 300 or type(kind) is not int or kind not in (1, 2, 3, 4)
                or not isinstance(info, str) or not info or response.get('code', 0) not in (0, None)):
            return
        ttl = response.get('ttl', 3600)
        ttl = min(max(ttl, 1), 86400) if type(ttl) is int else 3600
        OfficialMediaHandle.objects.filter(expires_at__lte=timezone.now()).delete()
        OfficialMediaHandle.objects.update_or_create(bot=bot, digest=handle_digest(path, info),
            defaults={'file_type': kind, 'expires_at': timezone.now() + timedelta(seconds=ttl)})
    except (ValueError, TypeError, AttributeError):
        return


def uploaded_type(bot, path, body):
    from django.utils import timezone
    from .models import OfficialMediaHandle
    try:
        info = json.loads(body).get('media', {}).get('file_info')
        if isinstance(info, str) and info:
            kind = OfficialMediaHandle.objects.filter(bot=bot, digest=handle_digest(path, info),
                expires_at__gt=timezone.now()).values_list('file_type', flat=True).first()
            return {1: 'image', 2: 'video', 3: 'voice', 4: 'file'}.get(kind)
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def accepted(result):
    status, raw, _ = result
    if not 200 <= status < 300:
        return False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get('code', 0) in (0, None) and data.get('errcode', 0) in (0, None) and bool(data.get('id'))
