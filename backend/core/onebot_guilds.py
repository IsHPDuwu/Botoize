"""OneBot 12 guild/channel mappings, only for unrestricted conversation keys."""
import json
import re
import time
import uuid
from urllib.parse import urlencode

from .conversations import unrestricted
from .models import OneBotMessage
from .official import _request
from .onebot_common import OneBotError, fields, identifier

GUILD_SCOPES = {'get_guild_info': 'guilds:read', 'get_channel_info': 'channels:read',
                'get_channel_list': 'channels:read', 'set_channel_name': 'channels:write',
                'get_guild_member_info': 'members:read', 'get_guild_member_list': 'members:read'}


def broad(key):
    if key is not None and not unrestricted(key):
        raise OneBotError(35003, 'Guild/channel operations require unrestricted conversation authorization')


def platform_id(value):
    value = identifier(value)
    if not re.fullmatch('[A-Za-z0-9_-]{1,128}', value):
        raise OneBotError(10003, 'Invalid guild/channel ID')
    return value


def upstream(bot, method, path, query='', body=None):
    from .onebot import official_json
    status, raw, headers = _request(bot, method, path, query, body)
    if not 200 <= status < 300:
        raise OneBotError(34000, f'QQ official HTTP {status}')
    data = json.loads(raw)
    if not isinstance(data, (dict, list)):
        raise ValueError('Invalid official response')
    if isinstance(data, dict):
        official_json((status, raw, headers))
    return data


def channel_info(bot, guild, channel):
    data = upstream(bot, 'GET', f'channels/{channel}')
    if data.get('guild_id') != guild:
        raise OneBotError(10003, 'Channel does not belong to the specified guild')
    return data


def member(data):
    user = data['user']
    return {'user_id': identifier(user['id']), 'user_name': user.get('username', ''),
            'user_displayname': data.get('nick', '')}


def guild_action(bot, key, action, params):
    broad(key)
    allowed = {'guild_id'}
    if action in {'get_channel_info', 'set_channel_name'}:
        allowed.add('channel_id')
    if action == 'set_channel_name':
        allowed.add('channel_name')
    if action == 'get_channel_list':
        allowed.add('joined_only')
    if action == 'get_guild_member_info':
        allowed.add('user_id')
    fields(params, allowed, allowed - {'joined_only'})
    guild = platform_id(params['guild_id'])
    if action == 'get_guild_info':
        data = upstream(bot, 'GET', f'guilds/{guild}')
        return {'guild_id': guild, 'guild_name': data.get('name', '')}
    if action == 'get_channel_list':
        if type(params.get('joined_only', False)) is not bool:
            raise OneBotError(10003, 'joined_only must be boolean')
        if params.get('joined_only', False):
            raise OneBotError(10004, 'QQ has no channel joined-only list semantics')
        data = upstream(bot, 'GET', f'guilds/{guild}/channels')
        if not isinstance(data, list):
            raise ValueError('Invalid channel list')
        return [{'channel_id': identifier(row['id']), 'channel_name': row.get('name', '')} for row in data]
    if action in {'get_channel_info', 'set_channel_name'}:
        channel = platform_id(params['channel_id'])
        data = channel_info(bot, guild, channel)
        if action == 'get_channel_info':
            return {'channel_id': channel, 'channel_name': data.get('name', '')}
        name = params['channel_name']
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise OneBotError(10003, 'Invalid channel name')
        upstream(bot, 'PATCH', f'channels/{channel}', body=json.dumps({'name': name}).encode())
        return None
    if action == 'get_guild_member_info':
        return member(upstream(bot, 'GET', f'guilds/{guild}/members/{platform_id(params["user_id"])}'))
    after, seen, result = '0', set(), {}
    for _ in range(20):
        data = upstream(bot, 'GET', f'guilds/{guild}/members', urlencode({'after': after, 'limit': 400}))
        if not isinstance(data, list):
            raise ValueError('Invalid member list')
        if not data:
            return list(result.values())
        for row in data:
            item = member(row)
            result[item['user_id']] = item
        after = data[-1]['user']['id']
        if after in seen:
            raise OneBotError(34000, 'QQ returned repeating guild member cursor')
        seen.add(after)
    raise OneBotError(10004, 'Guild member list exceeds 20 pages; no partial list returned')


def send_channel(bot, key, scopes, params):
    from .onebot import official_json, message_record, send_message
    from .onebot_files import owned_file, file_bytes
    broad(key)
    fields(params, {'detail_type', 'guild_id', 'channel_id', 'message'}, {'guild_id', 'channel_id', 'message'})
    if 'channels:read' not in scopes:
        raise OneBotError(35003, 'channels:read scope is required to verify channel ownership')
    guild, channel = platform_id(params['guild_id']), platform_id(params['channel_id'])
    channel_info(bot, guild, channel)
    message = params['message']
    if not isinstance(message, list) or not 1 <= len(message) <= 100:
        raise OneBotError(10003, 'Expected a segment array')
    content, payload, image = [], {}, None
    for segment in message:
        if not isinstance(segment, dict) or set(segment) != {'type', 'data'} or not isinstance(segment['data'], dict):
            raise OneBotError(10006, 'Invalid segment')
        kind, data = segment['type'], segment['data']
        if kind == 'text':
            fields(data, {'text'}, {'text'})
            if not isinstance(data['text'], str):
                raise OneBotError(10006, 'Text must be string')
            # Do not reinterpret literal platform mention/face markup as structured segments.
            if re.search(r'<(?:@|emoji:)', data['text']):
                raise OneBotError(10007, 'Use mention or qq.face segments for channel markup')
            content.append(data['text'])
        elif kind == 'mention':
            fields(data, {'user_id'}, {'user_id'})
            content.append('<@' + platform_id(data['user_id']) + '>')
        elif kind == 'mention_all':
            fields(data, {})
            content.append('@everyone')
        elif kind == 'qq.face':
            fields(data, {'id'}, {'id'})
            if not isinstance(data['id'], str) or not re.fullmatch('[0-9]{1,10}', data['id']):
                raise OneBotError(10006, 'Invalid face ID')
            content.append('<emoji:' + data['id'] + '>')
        elif kind == 'reply':
            fields(data, {'message_id', 'user_id'}, {'message_id'})
            row = message_record(bot, key, data['message_id'], 12)
            if row.conversation_type != 'channel' or row.target_id != channel or row.guild_id != guild or 'message_reference' in payload:
                raise OneBotError(35003, 'Reply must refer to this channel')
            payload['message_reference'] = {'message_id': row.message_id}
        elif kind == 'image':
            fields(data, {'file_id'}, {'file_id'})
            if image is not None:
                raise OneBotError(10007, 'Only one image is supported')
            if 'media:upload' not in scopes:
                raise OneBotError(35003, 'media:upload scope required')
            image = data['file_id']
        elif kind in {'qq.markdown', 'qq.keyboard', 'qq.ark', 'qq.embed'}:
            name = kind[3:]
            if name in payload or not data:
                raise OneBotError(10006, 'Invalid or duplicate QQ extension')
            payload[name] = data
        else:
            raise OneBotError(10005, 'Unsupported channel segment')
    payload['content'] = ''.join(content)
    if len(payload['content']) > 20000 or not (payload['content'] or image or any(k in payload for k in ['markdown', 'ark', 'embed'])):
        raise OneBotError(10006, 'Empty or oversized message')
    if any(k in payload for k in ['markdown', 'ark', 'embed']) and (image or payload['content']):
        raise OneBotError(10007, 'Unsupported mixed channel message')
    if image is not None:
        row = owned_file(key, image)
        raw = file_bytes(row)
        if len(raw) > 5 * 1024 * 1024:
            raise OneBotError(10007, 'Channel direct upload is limited to 5 MiB')
        boundary = 'botoize-' + uuid.uuid4().hex
        body = b''
        for name, value in payload.items():
            text = value if isinstance(value, str) else json.dumps(value)
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{text}\r\n'.encode()
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="file_image"; filename="image"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
        response = official_json(send_message(bot, f'channels/{channel}/messages', body, content_type=f'multipart/form-data; boundary={boundary}'))
    else:
        response = official_json(send_message(bot, f'channels/{channel}/messages', json.dumps(payload).encode()))
    mid, now = identifier(response['id']), time.time()
    OneBotMessage.objects.get_or_create(bot=bot, source_digest='', message_id=mid, defaults={
        'conversation_type': 'channel', 'guild_id': guild, 'is_direct': False, 'target_id': channel,
        'sent_at': now, 'segments': message, 'created_by': key.user if key else None,
    })
    return {'message_id': mid, 'time': now}
