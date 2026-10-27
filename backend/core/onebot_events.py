"""Lossless supported QQ messages, stable events and version-specific ID encoding."""
import copy
import json
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.utils import timezone

from .models import Event, OneBotFile, OneBotMessage
from .onebot_ids import virtual_id, original_id


def cq_text(text):
    return text.replace('&', '&amp;').replace('[', '&#91;').replace(']', '&#93;')


def safe_extension(value):
    """Unknown nested QQ structures must not forward authentication material."""
    if isinstance(value, dict):
        return {k: safe_extension(v) for k, v in value.items()
                if k.lower().replace('-', '_') not in {
                    'token', 'access_token', 'auth_token', 'secret', 'app_secret', 'appsecret',
                    'authorization', 'message_scene',
                }}
    if isinstance(value, list):
        return [safe_extension(v) for v in value
                if not (isinstance(v, str) and v.split('=', 1)[0].lower() in {'auth_token', 'access_token', 'token'})]
    return value


def canonical_segments(bot, segments, version):
    output = copy.deepcopy(segments)
    if version == 11:
        for segment in output:
            kind, data = segment['type'], segment['data']
            if kind == 'reply':
                segment['data'] = {'message_id': original_id(bot, 'message', data['id'])}
            elif kind in {'image', 'record', 'video', 'botoize.file'}:
                segment['type'] = {'record': 'voice', 'botoize.file': 'file'}.get(kind, kind)
                # Do not persist Base64 or arbitrary caller URLs in message history.
                value = data['file']
                try:
                    value = str(uuid.UUID(value))
                except ValueError:
                    segment['type'], value = 'botoize.sent_media', ''
                segment['data'] = {'file_id': value} if value else {}
    return output


def to11_segments(bot, segments):
    output = copy.deepcopy(segments)
    for segment in output:
        kind, data = segment['type'], segment['data']
        if kind == 'reply':
            segment['data'] = {'id': str(virtual_id(bot, 'message', data['message_id']))}
        elif kind == 'mention':
            segment['type'], segment['data'] = 'at', {'qq': str(virtual_id(bot, 'user', data['user_id']))}
        elif kind == 'mention_all':
            segment['type'], segment['data'] = 'at', {'qq': 'all'}
        elif kind == 'qq.face':
            segment['type'] = 'face'
        elif kind in {'image', 'voice', 'video', 'file'}:
            segment['type'] = {'voice': 'record', 'file': 'botoize.file'}.get(kind, kind)
            segment['data'] = {'file': data['file_id']}
            if 'qq.url' in data:
                segment['data']['url'] = data['qq.url']
            else:
                try:
                    file = OneBotFile.objects.filter(pk=data['file_id']).first()
                    if file and file.url:
                        segment['data']['url'] = file.url
                except (ValueError, TypeError):
                    pass
    return output


def raw11(segments):
    return ''.join(cq_text(s['data']['text']) if s['type'] == 'text' else
                   '[CQ:' + s['type'] + ''.join(',' + k + '=' + cq_text(str(v)).replace(',', '&#44;')
                                              for k, v in s['data'].items()) + ']' for s in segments)


def parsed_message(payload):
    if not isinstance(payload, dict) or payload.get('op') != 0:
        return None
    kind, data = payload.get('t'), payload.get('d')
    if kind not in {'C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE', 'AT_MESSAGE_CREATE', 'MESSAGE_CREATE'} or not isinstance(data, dict):
        return None
    guild = data.get('guild_id', '') if kind in {'AT_MESSAGE_CREATE', 'MESSAGE_CREATE'} else ''
    if kind in {'AT_MESSAGE_CREATE', 'MESSAGE_CREATE'} and not guild:
        return None
    if guild and (not isinstance(guild, str) or len(guild) > 128):
        return None
    direct = kind == 'C2C_MESSAGE_CREATE'
    author = data.get('author')
    if not isinstance(author, dict):
        return None
    user, mid = author.get('id' if guild else 'user_openid' if direct else 'member_openid'), data.get('id')
    target = user if direct else data.get('channel_id' if guild else 'group_openid')
    if not all(isinstance(v, str) and 1 <= len(v) <= 256 for v in (user, mid, target)):
        return None
    try:
        timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            return None
        sent_at = timestamp.timestamp()
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None
    text = data.get('content', '')
    if not isinstance(text, str):
        return None
    segments = [{'type': 'text', 'data': {'text': text}}] if text else []
    attachments = data.get('attachments', [])
    if not isinstance(attachments, list) or len(attachments) > 100:
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            return None
        url, content_type = attachment.get('url'), attachment.get('content_type')
        if not isinstance(url, str) or not isinstance(content_type, str):
            return None
        url = 'https:' + url if url.startswith('//') else url
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
        except ValueError:
            return None
        if parsed.scheme not in {'http', 'https'} or not hostname or len(url) > 2048:
            return None
        media_type = ('image' if content_type.startswith('image/') else 'voice' if content_type == 'voice' or content_type.startswith('audio/')
                      else 'video' if content_type.startswith('video/') else 'file')
        segments.append({'type': media_type, 'data': {'qq.url': url,
                         'qq.name': attachment.get('filename', 'attachment') or 'attachment'}})
    reference = data.get('message_reference')
    if isinstance(reference, dict) and isinstance(reference.get('message_id'), str):
        segments.insert(0, {'type': 'reply', 'data': {'message_id': reference['message_id']}})
    # Preserve rich inbound structures as explicit receive-only QQ extensions.
    for key in ['ark_data', 'msg_elements', 'mentions']:
        if data.get(key):
            segments.append({'type': 'qq.' + key, 'data': {'value': safe_extension(data[key])}})
    scene = data.get('message_scene', {})
    ext = scene.get('ext', []) if isinstance(scene, dict) else []
    ref = next((s.split('=', 1)[1] for s in ext if isinstance(s, str) and s.startswith('ref_msg_idx=')), '') if isinstance(ext, list) else ''
    if ref and not isinstance(reference, dict):
        segments.insert(0, {'type': 'reply', 'data': {'message_id': ref}})
    if not segments:
        return None
    return direct, target, user, mid, sent_at, segments, guild


def remember_message(bot, payload):
    if payload.get('t') == 'COMPANION_MESSAGE_CREATE':
        from .companions import remember_bridge
        return remember_bridge(bot, payload)
    if payload.get('t') == 'ONEBOT_EVENT':
        from .onebot_upstream_events import canonical_message
        return canonical_message(bot, payload)
    parsed = parsed_message(payload)
    if not parsed:
        return None
    direct, target, user, mid, sent_at, segments, guild = parsed
    data = payload['d']
    ref = data.get('ext_info')
    ref = ref.get('ref_idx', '') if isinstance(ref, dict) else ''
    scene = data.get('message_scene', {})
    ext = scene.get('ext', []) if isinstance(scene, dict) else []
    if isinstance(ext, list):
        ref = next((s.split('=', 1)[1] for s in ext if isinstance(s, str) and s.startswith('msg_idx=')), ref)
    return OneBotMessage.objects.get_or_create(bot=bot, source_digest='', message_id=mid, defaults={
        'is_direct': direct, 'target_id': target, 'sender_id': user, 'segments': segments,
        'sent_at': sent_at, 'incoming': True, 'reference': ref if isinstance(ref, str) else '',
        'conversation_type': 'channel' if guild else 'private' if direct else 'group', 'guild_id': guild,
    })[0]


def visible_segments(row, key):
    segments = copy.deepcopy(row.segments)
    for index, segment in enumerate(segments):
        data = segment['data']
        if 'qq.url' not in data and 'botoize.upstream_file_id' not in data:
            continue
        if key is None:
            return None
        OneBotFile.objects.filter(api_key=key, expires_at__lte=timezone.now()).delete()
        file_id = uuid.uuid5(uuid.NAMESPACE_URL, f'botoize:{key.pk}:{row.bot_id}:{row.message_id}:{index}')
        if not OneBotFile.objects.filter(pk=file_id).exists() and OneBotFile.objects.filter(api_key=key).count() >= 1000:
            segment['type'] = 'qq.attachment'
            segment['data']['botoize.reason'] = 'file cache capacity exceeded'
            continue
        name = str(data.get('qq.name', 'attachment'))[:255].replace('/', '_').replace('\\', '_')
        file, _ = OneBotFile.objects.get_or_create(pk=file_id, defaults={
            'api_key': key, 'name': name, 'url': data.get('qq.url', ''), 'complete': True,
            'upstream_file_id': data.get('botoize.upstream_file_id', ''),
            'upstream_bot_id': row.attachment_bot_id,
            'upstream_digest': row.attachment_digest,
            'expires_at': timezone.now() + timedelta(hours=24), 'is_direct': row.is_direct, 'target_id': row.target_id,
            'conversation_type': row.conversation_type,
        })
        segment['data'] = {'file_id': str(file.pk)}
    return segments


def notice_event(bot, payload, self_id, version, received_at=None):
    data, kind = payload['d'], payload.get('t')
    stamp = data.get('timestamp')
    if type(stamp) not in {int, float}:
        try:
            stamp = datetime.fromisoformat(str(data.get('apply_at', stamp)).replace('Z', '+00:00')).timestamp()
        except (ValueError, OverflowError, OSError):
            stamp = received_at.timestamp() if received_at else 0
    eid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'botoize:{bot.pk}:{payload.get("id", json.dumps(payload, sort_keys=True))}'))
    event = ({'id': eid, 'self': {'platform': 'qq', 'user_id': str(self_id)}, 'time': float(stamp),
              'type': 'notice', 'detail_type': 'qq.raw_event', 'sub_type': ''} if version == 12 else
             {'self_id': self_id, 'time': int(stamp), 'post_type': 'notice'})
    def uid(value):
        return (str(value) if version == 12 else virtual_id(bot, 'user', value)) if value else ('' if version == 12 else 0)
    if kind in {'FRIEND_ADD', 'FRIEND_DEL'} and isinstance(data.get('openid'), str):
        if version == 11 and kind == 'FRIEND_DEL':
            event.update(notice_type='botoize.friend_decrease', user_id=uid(data['openid']))
        elif version == 11:
            event.update(notice_type='friend_add', user_id=uid(data['openid']))
        else:
            event.update(detail_type='friend_increase' if kind == 'FRIEND_ADD' else 'friend_decrease', user_id=data['openid'])
        return event
    if kind in {'GROUP_MEMBER_ADD', 'GROUP_MEMBER_REMOVE', 'GROUP_ADD_ROBOT', 'GROUP_DEL_ROBOT'} and isinstance(data.get('group_openid'), str):
        increase, own = kind in {'GROUP_MEMBER_ADD', 'GROUP_ADD_ROBOT'}, kind in {'GROUP_ADD_ROBOT', 'GROUP_DEL_ROBOT'}
        user = self_id if own else uid(data.get('member_openid'))
        operator = uid(data.get('op_member_openid'))
        group = data['group_openid'] if version == 12 else virtual_id(bot, 'group', data['group_openid'])
        event.update(group_id=group, user_id=user, operator_id=operator)
        if version == 12:
            event.update(detail_type='group_member_increase' if increase else 'group_member_decrease')
        else:
            event.update(notice_type='group_increase' if increase else 'group_decrease', sub_type='botoize.unknown')
        return event
    if kind == 'GROUP_JOIN_REQUEST' and isinstance(data.get('group_openid'), str):
        source = Event.objects.filter(bot=bot, event_id=payload.get('id')).first()
        if source is None:
            return None
        user, group = uid(data.get('member_openid')), data['group_openid']
        verify = data.get('verify_info', {})
        comment = verify.get('verify_message', '') if isinstance(verify, dict) else ''
        event.update(user_id=user, group_id=group if version == 12 else virtual_id(bot, 'group', group), flag=f'botoize:{source.pk}')
        if version == 12:
            event.update(type='request', detail_type='qq.group_join', **{'qq.comment': comment})
        else:
            event.update(post_type='request', request_type='group', sub_type='add', comment=comment)
        return event
    if version == 11:
        return None
    event.update({'qq.event_type': kind, 'qq.data': safe_extension(data)})
    return event


def message_event(bot, payload, self_id, version=11, key=None, received_at=None):
    from .companions import bridge_visible
    if not bridge_visible(bot, payload):
        return None
    if isinstance(payload, dict) and payload.get('t') == 'ONEBOT_EVENT':
        from .onebot_upstream_events import downstream_event
        return downstream_event(bot, payload, self_id, version, key)
    row = remember_message(bot, payload)
    if row is None:
        if (not isinstance(payload, dict) or payload.get('op') != 0
                or not isinstance(payload.get('d'), dict) or str(payload.get('t', '')).endswith('MESSAGE_CREATE')):
            return None
        return notice_event(bot, payload, self_id, version, received_at)
    segments = visible_segments(row, key)
    if segments is None:
        return None
    if version == 12:
        event = {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'botoize:{bot.pk}:{payload.get("id", row.message_id)}')),
                 'self': {'platform': 'qq', 'user_id': str(self_id)}, 'time': row.sent_at,
                 'type': 'message', 'detail_type': 'channel' if row.conversation_type == 'channel' else 'private' if row.is_direct else 'group', 'sub_type': '',
                 'message_id': row.message_id, 'user_id': row.sender_id, 'message': segments,
                 'alt_message': ''.join(s['data']['text'] if s['type'] == 'text' else '[' + s['type'] + ']' for s in segments)}
        if row.conversation_type == 'channel':
            event.update(guild_id=row.guild_id, channel_id=row.target_id)
        elif not row.is_direct:
            event['group_id'] = row.target_id
        return event
    if row.conversation_type == 'channel':
        return None
    uid = virtual_id(bot, 'user', row.sender_id)
    message = to11_segments(bot, segments)
    event = {'time': int(row.sent_at), 'self_id': self_id, 'post_type': 'message',
             'message_type': 'private' if row.is_direct else 'group', 'sub_type': 'other' if row.is_direct else 'normal',
             'message_id': virtual_id(bot, 'message', row.message_id), 'user_id': uid,
             'message': message, 'raw_message': raw11(message), 'font': 0,
             'sender': {'user_id': uid, 'nickname': '', 'sex': 'unknown', 'age': 0}}
    author = payload['d'].get('author', {})
    if isinstance(author, dict):
        if isinstance(author.get('username'), str):
            event['sender']['nickname'] = author['username']
        if not row.is_direct and author.get('member_role') in {'owner', 'admin', 'member'}:
            event['sender']['role'] = author['member_role']
    if not row.is_direct:
        event['group_id'] = virtual_id(bot, 'group', row.target_id)
    if payload.get('t') == 'COMPANION_MESSAGE_CREATE':
        event['sender']['nickname'] = payload['d'].get('nickname', '')
    return event
