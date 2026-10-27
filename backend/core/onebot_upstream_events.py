"""Authenticated OneBot events stored in a native envelope with explicit targets."""
import copy
import hashlib
import json
import math

from django.db import transaction
from django.utils import timezone

from .models import Bot, OneBotMessage, OneBotUpstreamSession
from .onebot_common import OneBotError
from .onebot_events import safe_extension
from .onebot_upstream import configuration_digest, native_id
from .upstreams import onebot_version


def normalize_event(bot, value):
    version = onebot_version(bot)
    if not isinstance(value, dict):
        raise ValueError('OneBot event object required')
    if version == 11:
        if str(value.get('self_id')) != bot.app_id:
            raise ValueError('OneBot event Bot mismatch')
        kind = value.get('post_type')
        if kind not in {'message', 'message_sent', 'notice', 'request', 'meta_event'}:
            raise ValueError('Invalid OneBot 11 event type')
        if kind == 'meta_event':
            return None
        detail = value.get('message_type')
    else:
        kind, detail = value.get('type'), value.get('detail_type')
        if kind == 'meta':
            return None
        own = value.get('self')
        if (kind not in {'message', 'notice', 'request'} or not isinstance(own, dict)
                or own.get('user_id') != bot.app_id or not isinstance(own.get('platform'), str)
                or not 1 <= len(own['platform']) <= 64):
            raise ValueError('OneBot 12 event Bot mismatch')
        if not isinstance(value.get('id'), str) or not 1 <= len(value['id']) <= 200:
            raise ValueError('Stable OneBot 12 event ID required')
    stamp = value.get('time')
    if type(stamp) not in {float, int} or not math.isfinite(stamp) or not 0 <= stamp <= 253402300799:
        raise ValueError('Invalid OneBot event time')
    target_type, target_id = '', ''
    try:
        # Group ID takes priority: member IDs on group notices are not private conversations.
        if 'group_id' in value:
            target_type, target_id = 'group', str(native_id(value['group_id'], version))
        elif version == 12 and 'channel_id' in value:
            target_type, target_id = 'channel', str(native_id(value['channel_id'], version))
        elif 'user_id' in value and (detail == 'private' or kind in {'notice', 'request'}):
            target_type, target_id = 'private', str(native_id(value['user_id'], version))
        if kind in {'message', 'message_sent'}:
            native_id(value.get('message_id'), version, kind='message')
            native_id(value.get('user_id'), version)
            if detail not in {'private', 'group', 'channel'} or target_type != detail:
                raise ValueError('Message conversation mismatch')
            if target_type == 'channel':
                native_id(value.get('guild_id'), 12)
            if not isinstance(value.get('message'), (str, list) if version == 11 else list):
                raise ValueError('Invalid OneBot message')
    except OneBotError:
        raise ValueError('Invalid OneBot event IDs') from None
    event = safe_extension(value)
    # OB11 has no universal event ID. Exact canonical payload duplicates collapse.
    stable = value['id'] if version == 12 else hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    digest = configuration_digest(bot)
    event_id = hashlib.sha256((digest + ':' + stable).encode()).hexdigest()
    return {'op': 0, 'id': 'onebot:' + event_id, 't': 'ONEBOT_EVENT', 'd': {
        'version': version, 'target_type': target_type, 'target_id': target_id,
        'source_digest': digest, 'event': event,
    }}


@transaction.atomic
def receive_event(bot, value, lease_token=None, event_secret=None):
    from .events import ingest_event
    current = Bot.objects.select_for_update(of=('self',)).select_related('channel').get(pk=bot.pk)
    if not current.is_active or configuration_digest(current) != configuration_digest(bot):
        raise ValueError('OneBot Channel configuration changed')
    if event_secret is not None and current.channel.encrypted_event_secret != event_secret:
        raise ValueError('OneBot event secret changed')
    if lease_token is not None:
        session = OneBotUpstreamSession.objects.select_for_update().filter(
            bot=current, lease_token=lease_token, lease_until__gt=timezone.now()).first()
        if session is None:
            raise ValueError('OneBot worker lease lost')
    payload = normalize_event(current, value)
    if payload is None:
        return None, False
    try:
        result = ingest_event(current, payload)
    except OneBotError:
        raise ValueError('Invalid OneBot message') from None
    OneBotUpstreamSession.objects.filter(bot=current).update(last_event_at=timezone.now())
    return result


def canonical_message(bot, payload):
    if payload.get('t') != 'ONEBOT_EVENT':
        return None
    data, event = payload['d'], payload['d']['event']
    if event.get('post_type', event.get('type')) not in {'message', 'message_sent'}:
        return None
    version = data['version']
    message = event['message']
    if version == 11:
        from .onebot import segments11
        message = segments11(message)
    if not isinstance(message, list) or not 1 <= len(message) <= 100:
        raise ValueError('Invalid OneBot message segments')
    segments = copy.deepcopy(message)
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get('type'), str) or not isinstance(segment.get('data'), dict):
            raise ValueError('Invalid OneBot message segment')
        kind, fields = segment['type'], segment['data']
        if kind == 'text':
            if not isinstance(fields.get('text'), str) or len(fields['text']) > 100000:
                raise ValueError('Invalid OneBot text')
            segment['data'] = {'text': fields['text']}
        elif kind in {'image', 'record', 'voice', 'video', 'file'}:
            handle = fields.get('file_id' if version == 12 else 'file')
            if not isinstance(handle, str) or not 1 <= len(handle) <= 512:
                raise ValueError('Invalid upstream attachment')
            segment['type'] = 'voice' if kind == 'record' else kind
            segment['data'] = {'botoize.upstream_file_id': handle,
                               'botoize.upstream_version': version, 'botoize.media_type': segment['type']}
        elif version == 11 and kind == 'at':
            if str(fields.get('qq')) != 'all':
                native_id(fields.get('qq'), 11)
            segment['type'] = 'mention_all' if str(fields.get('qq')) == 'all' else 'mention'
            segment['data'] = {} if segment['type'] == 'mention_all' else {'user_id': str(fields['qq'])}
        elif kind == 'reply':
            segment['data'] = {'message_id': str(native_id(fields.get('id' if version == 11 else 'message_id'), version, kind='message'))}
        elif kind == 'mention':
            segment['data'] = {'user_id': str(native_id(fields.get('user_id'), version))}
        elif version == 11 and kind == 'face':
            segment['type'] = 'qq.face'
    direct = data['target_type'] == 'private'
    own_message = event.get('post_type') == 'message_sent'
    row, _ = OneBotMessage.objects.get_or_create(bot=bot, source_digest=data['source_digest'], message_id=str(event['message_id']), defaults={
        'is_direct': direct, 'target_id': data['target_id'], 'sender_id': str(event['user_id']),
        'segments': segments, 'sent_at': event['time'], 'incoming': not own_message,
        'conversation_type': data['target_type'], 'guild_id': str(event.get('guild_id', '')),
    })
    if row.conversation_type != data['target_type'] or row.target_id != data['target_id']:
        raise ValueError('OneBot message ID was reused in another conversation')
    return row


def downstream_event(bot, payload, self_id, version, key):
    from .onebot import public_id
    from .onebot_events import raw11, visible_segments
    data, original = payload['d'], payload['d']['event']
    # A newly configured transport must not resurrect events from a previous upstream.
    if data['source_digest'] != configuration_digest(bot):
        return None
    source_version = data['version']
    row = canonical_message(bot, payload)
    if row is not None:
        if version == 11 and row.conversation_type == 'channel':
            return None
        segments = visible_segments(row, key)
        if version == 11:
            from .onebot_upstream_actions import encode_segments
            segments = encode_segments(bot, segments, 11, event=True)
        result = ({'time': int(row.sent_at), 'self_id': self_id, 'post_type': 'message',
                   'message_type': row.conversation_type, 'sub_type': original.get('sub_type', 'normal' if not row.is_direct else 'friend'),
                   'message_id': public_id(bot, 'message', row.message_id, 11),
                   'user_id': public_id(bot, 'user', row.sender_id, 11), 'font': 0,
                   'message': segments, 'raw_message': raw11(segments),
                   'sender': {'user_id': public_id(bot, 'user', row.sender_id, 11), 'nickname': original.get('sender', {}).get('nickname', '')}}
                  if version == 11 else {'id': payload['id'], 'time': float(row.sent_at),
                   'self': {'platform': original.get('self', {}).get('platform', 'qq'), 'user_id': str(self_id)},
                   'type': 'message', 'detail_type': row.conversation_type, 'sub_type': original.get('sub_type', ''),
                   'message_id': row.message_id, 'user_id': row.sender_id, 'message': segments,
                   'alt_message': ''.join(s['data'].get('text', '[' + s['type'] + ']') for s in segments)})
        if row.conversation_type == 'group':
            result['group_id'] = public_id(bot, 'group', row.target_id, version)
        elif row.conversation_type == 'channel':
            result.update(guild_id=row.guild_id, channel_id=row.target_id)
        return result
    if source_version == version:
        result = copy.deepcopy(original)
        if version == 12:
            result['id'] = payload['id']
        # Request flags remain local: upstream flags cannot be used to bypass event grants.
        if result.get('post_type', result.get('type')) == 'request' and 'flag' in result:
            from .models import Event
            event = Event.objects.filter(bot=bot, event_id=payload['id']).first()
            result['flag'] = 'upstream:' + str(event.pk) if event else ''
        return result
    # Preserve untranslatable notices as a clearly named extension, not an invented standard event.
    if version == 12:
        return {'id': payload['id'], 'time': float(original['time']), 'self': {'platform': 'qq', 'user_id': str(self_id)},
                'type': 'notice', 'detail_type': 'botoize.onebot11_event', 'sub_type': '', 'botoize.event': original}
    return {'time': int(original['time']), 'self_id': self_id, 'post_type': 'notice',
            'notice_type': 'botoize.onebot12_event', 'botoize.event': original}
