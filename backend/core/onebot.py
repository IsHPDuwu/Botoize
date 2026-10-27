"""OneBot 11/12 actions over shared authorization and QQ official transport."""
import base64
import json
import re
import time

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .conversations import check_conversation, grant_chain, key_grant
from .models import Conversation, OneBotMessage
from .official import OfficialCredentialError, get_self, send_message, delete_message, upload_media
from .onebot_common import OneBotError, fields, identifier, message_identifier, segment_fields
from .onebot_files import file_action, owned_file, file_bytes, decode_data, download
from .onebot_ids import original_id, virtual_id
from .onebot_guilds import GUILD_SCOPES

VERSION = {'impl': 'botoize', 'version': '0.2.0', 'onebot_version': '12'}
META12 = {'get_version', 'get_supported_actions', 'get_status', 'get_latest_events'}
ACTIONS12 = META12 | {'get_self_info', 'send_message', 'delete_message', 'upload_file', 'get_file',
                       'upload_file_fragmented', 'get_file_fragmented', 'get_group_info',
                       'get_group_member_info', 'get_group_member_list'} | set(GUILD_SCOPES)
ACTIONS11 = {'get_login_info', 'send_private_msg', 'send_group_msg', 'send_msg', 'delete_msg', 'get_msg',
             'get_status', 'get_version_info', 'can_send_image', 'can_send_record', 'clean_cache',
             'get_group_info', 'get_group_member_info', 'get_group_member_list', 'set_group_kick',
             'set_group_ban', 'set_group_add_request'}
EXTENSIONS = {'botoize.get_capabilities', 'botoize.get_known_conversations', 'botoize.get_group_members_page',
              'qq.set_group_kick', 'qq.set_group_ban', 'qq.set_group_add_request'}
MEDIA = {'image': 1, 'video': 2, 'voice': 3, 'file': 4}


def result(data=None, retcode=0, message='', echo=None):
    return Response({'status': 'ok' if retcode == 0 else 'failed', 'retcode': retcode,
                     'data': data, 'message': message, 'echo': echo})


def protocol_result(version, data=None, code=0, message='', echo=None):
    if version == 11:
        code = {10001: 1400, 10002: 1404, 10003: 1400, 10004: 1400, 10005: 1400,
                10006: 1400, 10007: 1400, 10102: 1400, 35003: 1403, 35004: 1400,
                34000: 1500, 33000: 1502, 35029: 1429}.get(code, code)
    response = result(data, code, message, echo)
    if version == 12 and echo is None:
        response.data.pop('echo')
    return response


def official_json(response, *, empty=False):
    status, body, _ = response
    if not 200 <= status < 300:
        raise OneBotError(34000, f'QQ official HTTP {status}')
    if empty and not body:
        return {}
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError('Invalid official response')
    if data.get('code', 0) not in (None, 0) or data.get('errcode', 0) not in (None, 0):
        raise OneBotError(34000, 'QQ official rejected the action')
    return data


def identity(bot):
    from .upstreams import onebot_version
    if onebot_version(bot):
        from .onebot_upstream import identity as upstream_identity
        return upstream_identity(bot)
    response = get_self(bot)
    try:
        data = official_json(response)
    except (OneBotError, ValueError, TypeError):
        from .official import response_code
        raise OfficialCredentialError('Official identity response rejected', status=response[0],
            code=response_code(response[1]), stage='identity', reason='upstream_rejected') from None
    own_id = identifier(data.get('id'))
    if bot.channel.onebot_self_id != own_id:
        from .models import Channel
        Channel.objects.filter(pk=bot.channel_id).update(onebot_self_id=own_id)
        bot.channel.onebot_self_id = own_id
    return {'platform': 'qq', 'user_id': own_id}, data.get('username', '')


def resolve_id(bot, kind, value, version):
    from .upstreams import onebot_version
    if version == 11 and onebot_version(bot) == 11:
        from .onebot_upstream import native_id
        if bot.channel.companion_id:
            try:
                return original_id(bot, kind, value)
            except ValueError:
                pass
        return str(native_id(value, 11, kind=kind))
    if version == 12:
        if onebot_version(bot):
            from .onebot_upstream import native_id
            return native_id(value, 12)
        return message_identifier(value) if kind == 'message' else identifier(value)
    try:
        original = original_id(bot, kind, value)
        if onebot_version(bot):
            from .onebot_upstream import native_id
            return native_id(original, 12)
        return message_identifier(original) if kind == 'message' else identifier(original)
    except ValueError:
        raise OneBotError(10003, 'Unknown or invalid virtual ID') from None


def public_id(bot, kind, value, version):
    from .upstreams import onebot_version
    if version == 11 and onebot_version(bot) == 11:
        from .onebot_upstream import native_id
        if bot.channel.companion_id:
            from .models import OneBotIdMapping
            if OneBotIdMapping.objects.filter(bot=bot, kind=kind, original_id=value).exists():
                return virtual_id(bot, kind, value)
        return native_id(value, 11, kind=kind)
    return value if version == 12 else virtual_id(bot, kind, value)


def known_conversations(key, version):
    rows = Conversation.objects.filter(bot_id=key.bot_id).order_by('pk')
    for policy in (*grant_chain(key_grant(key)), key):
        if not policy.all_conversations:
            rows = rows.filter(pk__in=policy.conversations.values('pk'))
    return [{'is_direct': row.is_direct, 'id': public_id(key.bot, 'user' if row.is_direct else 'group', row.target_id, version),
             'name': row.name} for row in rows]


def capabilities(version):
    return {'version': str(version), 'actions': sorted((ACTIONS12 if version == 12 else ACTIONS11) | EXTENSIONS),
            'message_segments': ['text', 'image', 'video', 'voice' if version == 12 else 'record',
                                 'file' if version == 12 else 'botoize.file', 'reply', 'qq.markdown', 'qq.keyboard'],
            'id_semantics': 'original string OpenID' if version == 12 else 'verified real numeric ID when known; persistent virtual numeric ID otherwise',
            'transports': ['http', 'websocket', 'websocket-reverse', 'http-webhook'],
            'limitations': ['QQ official cannot enumerate all QQ friends or joined QQ groups',
                           'Group info/members/kick/ban/approval require additional QQ permissions, some are invite-only',
                           'Likes, anonymous, cookies and process restart are unavailable',
                           'No server paths, private URLs, automatic transcoding or invented contact metadata',
                           'At most one media segment; unsupported composition is rejected, never silently dropped']}


def unescape(text):
    return text.replace('&#91;', '[').replace('&#93;', ']').replace('&#44;', ',').replace('&amp;', '&')


def segments11(message, auto_escape=False):
    if auto_escape in ('true', 'false'):
        auto_escape = auto_escape == 'true'
    if type(auto_escape) is not bool:
        raise OneBotError(10003, 'auto_escape must be boolean')
    if isinstance(message, list):
        return message
    if not isinstance(message, str):
        raise OneBotError(10003, 'Expected a message string or segment array')
    if auto_escape:
        return [{'type': 'text', 'data': {'text': message}}]
    parts, offset = [], 0
    for match in re.finditer(r'\[CQ:([^\[\]]+)\]', message):
        if '[CQ:' in message[offset:match.start()]:
            raise OneBotError(10006, 'Malformed CQ segment')
        if match.start() > offset:
            parts.append({'type': 'text', 'data': {'text': unescape(message[offset:match.start()])}})
        values = match[1].split(',')
        data = {}
        for value in values[1:]:
            if '=' not in value:
                raise OneBotError(10006, 'Invalid CQ segment')
            k, v = value.split('=', 1)
            if not k or k in data:
                raise OneBotError(10006, 'Invalid CQ segment data')
            data[k] = unescape(v)
        parts.append({'type': values[0], 'data': data})
        offset = match.end()
    if offset < len(message):
        text = message[offset:]
        if '[CQ:' in text:
            raise OneBotError(10006, 'Malformed CQ segment')
        parts.append({'type': 'text', 'data': {'text': unescape(text)}})
    return parts


def message_record(bot, key, value, version):
    from django.db.models import Q
    mid = resolve_id(bot, 'message', value, version)
    from .upstreams import onebot_version
    from .onebot_upstream import configuration_digest
    digest = configuration_digest(bot) if onebot_version(bot) else ''
    row = OneBotMessage.objects.filter(Q(message_id=mid) | Q(reference=mid), bot=bot, source_digest=digest).first()
    if row is None:
        raise OneBotError(35004, 'Message context unavailable')
    if row.source_event_id:
        from .companions import bridge_visible
        if not bridge_visible(bot, row.source_event.payload):
            raise OneBotError(35003, 'Message belongs to a previous companion configuration')
    if key is not None:
        if row.conversation_type == 'channel':
            from .onebot_guilds import broad
            broad(key)
        else:
            check_conversation(key, row.is_direct, row.target_id)
        if row.incoming:
            from .models import EventOutbox
            if row.source_event_id is None or not EventOutbox.objects.filter(
                event_id=row.source_event_id, is_stream=True, grant__user_id=key.user_id,
                grant__bot_id=key.bot_id, grant_revision=key.grant_revision,
            ).exists():
                raise OneBotError(35003, 'Message is outside the current event grant')
        elif row.created_by_id != key.user_id:
            raise OneBotError(35003, 'Message belongs to another account')
    return row


@transaction.atomic
def reply_context(row):
    locked = OneBotMessage.objects.select_for_update().get(pk=row.pk)
    if not locked.incoming or not -30 <= time.time() - locked.sent_at <= 300:
        raise OneBotError(35000, 'QQ passive reply context expired or is not inbound')
    locked.reply_sequence += 1
    locked.save(update_fields=['reply_sequence'])
    if locked.attachment_bot_id and not locked.primary_message_id:
        raise OneBotError(35004, 'The primary has not received this message; no official passive reply ID is available')
    return {'msg_id': locked.primary_message_id or locked.message_id, 'msg_seq': locked.reply_sequence}


def prepare_message(bot, key, scopes, message, direct, target, version):
    fields = segment_fields
    if not isinstance(message, list) or not 1 <= len(message) <= 100:
        raise OneBotError(10003, 'Expected 1..100 message segments')
    content, media, reply, markdown, keyboard = [], None, None, None, None
    for segment in message:
        if (not isinstance(segment, dict) or set(segment) != {'type', 'data'}
                or not isinstance(segment['type'], str) or not isinstance(segment['data'], dict)):
            raise OneBotError(10006, 'Invalid segment structure')
        kind, data = segment['type'], segment['data']
        kind = {'record': 'voice', 'botoize.file': 'file'}.get(kind, kind) if version == 11 else kind
        if kind == 'text':
            fields(data, {'text'}, {'text'})
            if not isinstance(data['text'], str):
                raise OneBotError(10006, 'Text must be a string')
            content.append(data['text'])
        elif kind in MEDIA:
            if media is not None:
                raise OneBotError(10007, 'QQ supports one media attachment per send')
            fields(data, {'file_id'} if version == 12 else {'file'},
                   {'file_id'} if version == 12 else {'file'})
            if key is None or 'media:upload' not in scopes:
                raise OneBotError(35003, 'media:upload scope required')
            value = data['file_id' if version == 12 else 'file']
            if not isinstance(value, str):
                raise OneBotError(10006, 'Invalid media file')
            media = (kind, value)
        elif kind == 'reply':
            fields(data, {'message_id', 'user_id'} if version == 12 else {'id'},
                   {'message_id'} if version == 12 else {'id'})
            if reply is not None:
                raise OneBotError(10007, 'Only one reply segment is supported')
            reply = message_record(bot, key, data['message_id' if version == 12 else 'id'], version)
            if reply.is_direct != direct or reply.target_id != target or reply.deleted:
                raise OneBotError(35003, 'Reply must refer to the same conversation')
            if 'user_id' in data and identifier(data['user_id']) != reply.sender_id:
                raise OneBotError(10006, 'Reply sender does not match')
            if not reply.reference:
                raise OneBotError(10007, 'QQ supplied no reference index; use qq.reply_to for passive reply')
        elif kind in {'qq.markdown', 'qq.keyboard'}:
            if not data or len(json.dumps(data)) > 16384:
                raise OneBotError(10006, 'Invalid QQ extension payload')
            if kind == 'qq.markdown':
                if markdown is not None:
                    raise OneBotError(10007, 'Duplicate markdown')
                markdown = data
            else:
                if keyboard is not None:
                    raise OneBotError(10007, 'Duplicate keyboard')
                keyboard = data
        else:
            raise OneBotError(10005, f'Unsupported message segment: {kind}')
    text = ''.join(content)
    if len(text) > 20000 or (not text and media is None and markdown is None):
        raise OneBotError(10006, 'Message is empty or too large')
    if (media and (markdown or keyboard)) or (markdown and text):
        raise OneBotError(10007, 'Unsupported mixed message composition')
    payload = {'content': text, 'msg_type': 0} if markdown is None else {'msg_type': 2, 'markdown': markdown}
    if keyboard is not None:
        payload['keyboard'] = keyboard
    if reply is not None:
        payload['message_reference'] = {'message_id': reply.reference}
    if media:
        kind, value = media
        if version == 11 and value.startswith('base64://'):
            raw, name = decode_data(value[9:]), 'onebot-media'
        elif version == 11 and value.startswith(('https://', 'http://')):
            raw, name = download(value), 'onebot-media'
        else:
            row = owned_file(key, value)
            raw, name = file_bytes(row), row.name
        if len(raw) > 5 * 1024 * 1024:
            raise OneBotError(10007, 'QQ direct media upload is limited to 5 MiB')
        path = f'v2/{"users" if direct else "groups"}/{target}/files'
        uploaded = official_json(upload_media(bot, path, json.dumps({
            'file_type': MEDIA[kind], 'file_name': name, 'file_data': base64.b64encode(raw).decode(),
            'srv_send_msg': False,
        }).encode()))
        info = uploaded.get('file_info')
        if not isinstance(info, str) or not info:
            raise ValueError('Missing official file handle')
        payload.update(msg_type=7, media={'file_info': info})
        if bot.channel.prefer_markdown and kind == 'image':
            payload['botoize_media_type'] = 'image'
    return payload


def invoke(bot, scopes, action, params, echo=None, *, key=None, version=11, self_info=None):
    from .companion_actions import try_management
    try:
        return try_management(bot, scopes, action, params, echo, key, version, self_info,
            lambda: invoke_primary(bot, scopes, action, params, echo, key=key, version=version, self_info=self_info)) if bot and isinstance(action, str) and isinstance(params, dict) else invoke_primary(bot, scopes, action, params, echo, key=key, version=version, self_info=self_info)
    except OneBotError as exc:
        return protocol_result(version, code=exc.code, message=exc.message, echo=echo)
    except PermissionDenied:
        return protocol_result(version, code=35003, message='Conversation not allowed', echo=echo)
    except (OfficialCredentialError, ValueError, TypeError, KeyError, OverflowError):
        return protocol_result(version, code=33000, message='Upstream management unavailable', echo=echo)


def invoke_primary(bot, scopes, action, params, echo=None, *, key=None, version=11, self_info=None):
    try:
        from .upstreams import onebot_version
        if onebot_version(bot):
            from .onebot_upstream_actions import invoke_upstream
            return invoke_upstream(bot, scopes, action, params, echo, key, version, self_info)
        supported = (ACTIONS12 if version == 12 else ACTIONS11) | EXTENSIONS
        if not isinstance(action, str) or action not in supported:
            raise OneBotError(10002, 'Unsupported action: not available through QQ official API')
        if not isinstance(params, dict):
            raise OneBotError(10003, 'params must be an object')
        if version == 12 and echo is not None and not isinstance(echo, str):
            raise OneBotError(10001, 'OneBot 12 echo must be a string')
        from .onebot_groups import GROUP_SCOPES
        required = GROUP_SCOPES.get(action) or GUILD_SCOPES.get(action) or ('messages:send' if action in {'send_message', 'send_msg', 'send_group_msg', 'send_private_msg'}
                    else 'messages:delete' if action in {'delete_message', 'delete_msg'}
                    else 'media:upload' if action.startswith('upload_file')
                    else 'events:read' if action in {'get_latest_events', 'get_msg', 'get_file', 'get_file_fragmented', 'get_image'} else 'query:read')
        if required not in scopes:
            raise OneBotError(35003, f'{required} scope required')
        if self_info is not None and self_info != identity(bot)[0]:
            raise OneBotError(10102, 'Unknown self for this key')
        return protocol_result(version, dispatch(bot, scopes, action, params, key, version), echo=echo)
    except OneBotError as exc:
        return protocol_result(version, code=exc.code, message=exc.message, echo=echo)
    except PermissionDenied:
        return protocol_result(version, code=35003, message='Conversation not allowed', echo=echo)
    except (OfficialCredentialError, ValueError, TypeError, KeyError, OverflowError):
        return protocol_result(version, code=33000, message='Official outcome unknown; do not blindly retry a send', echo=echo)


def dispatch(bot, scopes, action, params, key, version):
    from .onebot_groups import GROUP_SCOPES, group_action
    if action in GROUP_SCOPES:
        return group_action(bot, key, action, params, version)
    if action in GUILD_SCOPES:
        from .onebot_guilds import guild_action
        return guild_action(bot, key, action, params)
    if action in {'get_login_info', 'get_self_info'}:
        fields(params, {})
        own, name = identity(bot)
        return ({'user_id': own['user_id'], 'user_name': name, 'user_displayname': ''} if version == 12
                else {'user_id': virtual_id(bot, 'user', own['user_id']), 'nickname': name})
    if action in {'get_version', 'get_version_info'}:
        fields(params, {})
        return VERSION.copy() if version == 12 else {'app_name': 'botoize', 'app_version': VERSION['version'], 'protocol_version': 'v11'}
    if action == 'get_supported_actions':
        fields(params, {})
        from .companion_actions import extra_actions
        return sorted(ACTIONS12 | EXTENSIONS | extra_actions(bot, version))
    if action == 'botoize.get_capabilities':
        fields(params, {})
        data = capabilities(version)
        from .companion_actions import extra_actions
        data['actions'] = sorted(set(data['actions']) | extra_actions(bot, version))
        return data
    if action == 'botoize.get_known_conversations':
        fields(params, {})
        return known_conversations(key, version)
    if action == 'get_status':
        fields(params, {})
        own, _ = identity(bot)
        return ({'good': True, 'bots': [{'self': own, 'online': True}], 'botoize.online_basis': 'identity_http'}
                if version == 12 else {'good': True, 'online': True, 'botoize.online_basis': 'identity_http'})
    if action in {'can_send_image', 'can_send_record'}:
        fields(params, {})
        return {'yes': {'messages:send', 'media:upload'} <= set(scopes)}
    if action == 'clean_cache':
        from .models import OneBotFile
        fields(params, {})
        OneBotFile.objects.filter(api_key=key, expires_at__lte=timezone.now()).delete()
        return None
    if action == 'get_latest_events':
        from .onebot_poll import latest_events
        return latest_events(key, params)
    if action in {'upload_file', 'get_file', 'upload_file_fragmented', 'get_file_fragmented'}:
        return file_action(key, action, params)
    if action == 'get_image':
        fields(params, {'file'}, {'file'})
        row = owned_file(key, params['file'])
        if not row.url:
            raise OneBotError(10004, 'No publicly accessible URL for this file')
        return {'file': str(row.pk), 'url': row.url, 'filename': row.name, 'size': row.total_size}
    if action in {'delete_msg', 'delete_message', 'get_msg'}:
        fields(params, {'message_id'}, {'message_id'})
        row = message_record(bot, key, params['message_id'], version)
        if action == 'get_msg':
            from .onebot_events import to11_segments, visible_segments
            if row.conversation_type == 'channel':
                raise OneBotError(10004, 'OneBot 11 has no standard channel message type')
            return {'time': int(row.sent_at), 'message_type': 'private' if row.is_direct else 'group',
                    'message_id': public_id(bot, 'message', row.message_id, 11),
                    'real_id': public_id(bot, 'message', row.message_id, 11),
                    'sender': {'user_id': public_id(bot, 'user', row.sender_id, 11) if row.sender_id else 0,
                               'nickname': '', 'sex': 'unknown', 'age': 0},
                    'message': to11_segments(bot, visible_segments(row, key))}
        if row.incoming:
            raise OneBotError(10004, 'Only bot-sent messages can be recalled here')
        if not row.deleted:
            path = (f'channels/{row.target_id}/messages/{row.message_id}' if row.conversation_type == 'channel' else
                    f'v2/{"users" if row.is_direct else "groups"}/{row.target_id}/messages/{row.message_id}')
            official_json(delete_message(bot, path), empty=True)
            row.deleted = True
            row.save(update_fields=['deleted'])
        return None
    kind = params.get('detail_type') if version == 12 else (
        'private' if action == 'send_private_msg' else 'group' if action == 'send_group_msg'
        else params.get('message_type', 'group' if 'group_id' in params else 'private'))
    if version == 12 and kind == 'channel':
        from .onebot_guilds import send_channel
        return send_channel(bot, key, scopes, params)
    if kind not in {'private', 'group'}:
        raise OneBotError(10004, 'This QQ conversation adapter supports private and group messages')
    direct, target_key = kind == 'private', 'user_id' if kind == 'private' else 'group_id'
    allowed = {target_key, 'message', 'qq.reply_to'} | ({'detail_type'} if version == 12 else {'auto_escape'})
    if action == 'send_msg':
        allowed.add('message_type')
    fields(params, allowed, {target_key, 'message'} | ({'detail_type'} if version == 12 else set()))
    target = resolve_id(bot, 'user' if direct else 'group', params[target_key], version)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', target):
        raise OneBotError(10003, 'QQ target exceeds 128 characters')
    if key is not None:
        check_conversation(key, direct, target)
    message = params['message'] if version == 12 else segments11(params['message'], params.get('auto_escape', False))
    context = None
    if 'qq.reply_to' in params:
        context = message_record(bot, key, params['qq.reply_to'], version)
        if context.target_id != target or context.is_direct != direct:
            raise OneBotError(35003, 'Passive reply must use the same conversation')
        if not context.incoming or not -30 <= time.time() - context.sent_at <= 300:
            raise OneBotError(35000, 'Passive reply context expired')
    payload = prepare_message(bot, key, scopes, message, direct, target, version)
    if context is not None:
        payload.update(reply_context(context))
    response = official_json(send_message(bot, f'v2/{"users" if direct else "groups"}/{target}/messages', json.dumps(payload).encode()))
    try:
        mid = identifier(response.get('id'))
    except OneBotError:
        raise OneBotError(33000, 'QQ accepted without a usable message ID; do not blindly retry') from None
    now = time.time()
    ext = response.get('ext_info')
    reference = ext.get('ref_idx', '') if isinstance(ext, dict) else ''
    from .onebot_events import canonical_segments
    OneBotMessage.objects.get_or_create(bot=bot, source_digest='', message_id=mid, defaults={
        'is_direct': direct, 'target_id': target, 'segments': canonical_segments(bot, message, version),
        'conversation_type': 'private' if direct else 'group',
        'sent_at': now, 'reference': reference if isinstance(reference, str) else '',
        'created_by': key.user if key is not None else None,
    })
    data = {'message_id': public_id(bot, 'message', mid, version)}
    if version == 12:
        data['time'] = now
    return data
