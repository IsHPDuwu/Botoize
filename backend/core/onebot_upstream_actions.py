"""Authorized actions for OneBot-backed Channels, including version translation."""
import copy
import re
import time

from .conversations import check_conversation, unrestricted, event_allowed
from .models import OneBotMessage, EventOutbox
from .onebot_common import OneBotError, fields
from .onebot_files import file_action, owned_file, file_bytes, decode_data, download
from .onebot_upstream import call, identity, native_id, configuration_digest
from .upstreams import onebot_version

# Local permissions describe side effects independently of upstream credentials.
RULES = {
    'get_login_info': ('query:read', set()), 'get_self_info': ('query:read', set()),
    'get_stranger_info': ('query:read', {'user_id', 'no_cache'}),
    'get_user_info': ('query:read', {'user_id'}),
    'get_friend_list': ('friends:read', set()), 'send_like': ('friends:write', {'user_id', 'times'}),
    'get_group_list': ('groups:read', set()), 'get_group_info': ('groups:read', {'group_id', 'no_cache'}),
    'get_group_member_info': ('group-members:read', {'group_id', 'user_id', 'no_cache'}),
    'get_group_member_list': ('group-members:read', {'group_id'}),
    'get_group_honor_info': ('groups:read', {'group_id', 'type'}),
    'set_group_kick': ('group-moderation:write', {'group_id', 'user_id', 'reject_add_request'}),
    'set_group_ban': ('group-moderation:write', {'group_id', 'user_id', 'duration'}),
    'set_group_whole_ban': ('group-moderation:write', {'group_id', 'enable'}),
    'set_group_admin': ('group-moderation:write', {'group_id', 'user_id', 'enable'}),
    'set_group_anonymous': ('group-moderation:write', {'group_id', 'enable'}),
    'set_group_card': ('group-moderation:write', {'group_id', 'user_id', 'card'}),
    'set_group_name': ('group-moderation:write', {'group_id', 'group_name'}),
    'set_group_leave': ('group-moderation:write', {'group_id', 'is_dismiss'}),
    'set_group_special_title': ('group-moderation:write', {'group_id', 'user_id', 'special_title', 'duration'}),
    'leave_group': ('group-moderation:write', {'group_id'}),
    'set_group_add_request': ('group-requests:write', {'flag', 'sub_type', 'type', 'approve', 'reason'}),
    'set_friend_add_request': ('friend-requests:write', {'flag', 'approve', 'remark'}),
    'get_guild_info': ('guilds:read', {'guild_id'}), 'get_guild_list': ('guilds:read', set()),
    'get_channel_info': ('channels:read', {'guild_id', 'channel_id'}),
    'get_channel_list': ('channels:read', {'guild_id', 'joined_only'}),
    'get_guild_member_info': ('members:read', {'guild_id', 'user_id'}),
    'get_guild_member_list': ('members:read', {'guild_id'}),
    'get_channel_member_info': ('members:read', {'guild_id', 'channel_id', 'user_id'}),
    'get_channel_member_list': ('members:read', {'guild_id', 'channel_id'}),
    'set_guild_name': ('channels:write', {'guild_id', 'guild_name'}),
    'set_channel_name': ('channels:write', {'guild_id', 'channel_id', 'channel_name'}),
    'leave_guild': ('channels:write', {'guild_id'}), 'leave_channel': ('channels:write', {'guild_id', 'channel_id'}),
}
SHARED = {'get_version', 'get_version_info', 'get_supported_actions', 'get_status', 'get_latest_events',
          'botoize.get_capabilities', 'botoize.get_known_conversations', 'send_message', 'send_msg',
          'send_private_msg', 'send_group_msg', 'delete_message', 'delete_msg', 'get_msg',
          'upload_file', 'get_file', 'upload_file_fragmented', 'get_file_fragmented',
          'can_send_image', 'can_send_record', 'clean_cache'}
V11_ONLY = {'get_login_info', 'get_stranger_info', 'send_like', 'get_group_honor_info',
            'set_group_whole_ban', 'set_group_admin', 'set_group_anonymous', 'set_group_card',
            'set_group_special_title', 'set_friend_add_request', 'set_group_add_request', 'set_group_kick', 'set_group_ban'}
V12_ONLY = {'get_self_info', 'get_user_info', 'leave_group'} | {a for a in RULES if 'guild' in a or 'channel' in a}


def require(scopes, scope):
    if scope not in scopes:
        raise OneBotError(35003, scope + ' scope required')


def available_actions(source, version):
    actions = set(RULES) | SHARED
    actions -= (V11_ONLY if version == 12 else V12_ONLY)
    if version == 11:
        actions -= {'get_version', 'get_supported_actions', 'get_latest_events', 'send_message', 'delete_message',
                    'upload_file', 'get_file', 'upload_file_fragmented', 'get_file_fragmented'}
    else:
        actions -= {'get_version_info', 'send_msg', 'send_private_msg', 'send_group_msg', 'delete_msg', 'get_msg',
                    'can_send_image', 'can_send_record', 'clean_cache'}
    if source == 12:
        actions -= {'send_like', 'get_group_honor_info', 'set_group_whole_ban', 'set_group_admin',
                    'set_group_anonymous', 'set_group_card', 'set_group_special_title',
                    'set_group_add_request', 'set_friend_add_request', 'set_group_kick', 'set_group_ban'}
    if source == 11:
        actions -= {a for a in actions if 'guild' in a or 'channel' in a}
    return actions


def supported_actions(bot, version):
    actions = available_actions(onebot_version(bot), version)
    if onebot_version(bot) != 12:
        # OB11 has no standard upstream discovery action; the implementation can reject a listed bridge action.
        return actions
    remote = call(bot, 'get_supported_actions')
    if not isinstance(remote, list) or any(not isinstance(name, str) for name in remote):
        raise OneBotError(33000, 'Invalid upstream action discovery response')
    local = {'get_version', 'get_version_info', 'get_supported_actions', 'get_latest_events', 'get_msg',
             'botoize.get_capabilities', 'botoize.get_known_conversations', 'upload_file', 'get_file',
             'upload_file_fragmented', 'get_file_fragmented', 'clean_cache', 'can_send_image', 'can_send_record'}
    aliases = {'get_login_info': 'get_self_info', 'get_stranger_info': 'get_user_info',
               'send_msg': 'send_message', 'send_private_msg': 'send_message', 'send_group_msg': 'send_message',
               'delete_msg': 'delete_message', 'set_group_leave': 'leave_group'}
    return {name for name in actions if name in local or aliases.get(name, name) in remote}


def encode_segments(bot, segments, version, *, event=False):
    """Canonical segments -> wire representation without changing target IDs."""
    from .onebot import public_id
    result = copy.deepcopy(segments)
    for segment in result:
        kind, data = segment['type'], segment['data']
        if version == 11:
            if kind == 'reply':
                segment['data'] = {'id': str(public_id(bot, 'message', data['message_id'], 11))}
            elif kind == 'mention':
                segment['type'], segment['data'] = 'at', {'qq': str(public_id(bot, 'user', data['user_id'], 11))}
            elif kind == 'mention_all':
                segment['type'], segment['data'] = 'at', {'qq': 'all'}
            elif kind == 'qq.face':
                segment['type'] = 'face'
            elif kind in {'image', 'voice', 'video', 'file'}:
                segment['type'] = {'voice': 'record', 'file': 'botoize.file' if event else 'file'}.get(kind, kind)
                segment['data'] = {'file': data['file_id']}
    return result


def canonical_input(bot, key, message, version, scopes, target_type, target):
    from .onebot import resolve_id, segments11, message_record
    if version == 11:
        message = segments11(message)
    if not isinstance(message, list) or not 1 <= len(message) <= 100:
        raise OneBotError(10003, 'Expected 1..100 message segments')
    output = []
    for segment in message:
        if (not isinstance(segment, dict) or set(segment) != {'type', 'data'}
                or not isinstance(segment['type'], str) or not isinstance(segment['data'], dict)):
            raise OneBotError(10006, 'Invalid message segment')
        kind, data = segment['type'], copy.deepcopy(segment['data'])
        if version == 11:
            kind = {'record': 'voice', 'botoize.file': 'file', 'face': 'qq.face'}.get(kind, kind)
            if kind == 'at':
                kind, data = ('mention_all', {}) if str(data.get('qq')) == 'all' else (
                    'mention', {'user_id': resolve_id(bot, 'user', data.get('qq'), version)})
        if kind == 'text':
            fields(data, {'text'}, {'text'})
            if not isinstance(data['text'], str) or len(data['text']) > 100000:
                raise OneBotError(10006, 'Invalid text')
        elif kind in {'image', 'voice', 'video', 'file'}:
            require(scopes, 'media:upload')
            fields(data, {'file'} if version == 11 else {'file_id'}, {'file'} if version == 11 else {'file_id'})
            value = data['file' if version == 11 else 'file_id']
            if not isinstance(value, str):
                raise OneBotError(10006, 'Invalid file')
            # Validate every segment before a remote upload or a send occurs.
            if version == 11 and value.startswith(('base64://', 'http://', 'https://')):
                if value.startswith('base64://'):
                    decode_data(value[9:])
                else:
                    from .onebot_files import destination
                    destination(value)
                data = {'botoize.local_upload': value}
            else:
                row = owned_file(key, value)
                data = {'file_id': str(row.pk)}
        elif kind == 'reply':
            fields(data, {'id'} if version == 11 else {'message_id', 'user_id'}, {'id'} if version == 11 else {'message_id'})
            row = message_record(bot, key, data['id' if version == 11 else 'message_id'], version)
            if row.conversation_type != target_type or row.target_id != target:
                raise OneBotError(35003, 'Reply context belongs to another conversation')
            if row.attachment_digest and not row.primary_message_id:
                raise OneBotError(35004, 'No primary message ID is available for this companion reply')
            data = {'message_id': row.primary_message_id or row.message_id}
        elif kind == 'mention':
            fields(data, {'user_id'}, {'user_id'})
            if version == 12:
                data['user_id'] = native_id(data['user_id'], 12)
        elif kind == 'mention_all':
            fields(data, {})
        elif kind == 'qq.face':
            fields(data, {'id'}, {'id'})
            if not isinstance(data['id'], (str, int)) or not re.fullmatch(r'[0-9]{1,10}', str(data['id'])):
                raise OneBotError(10006, 'Invalid face ID')
        else:
            raise OneBotError(10005, 'Unsupported message segment for this OneBot bridge')
        output.append({'type': kind, 'data': data})
    return output


def wire_message(bot, key, canonical, own):
    source = onebot_version(bot)
    wire = copy.deepcopy(canonical)
    for segment in wire:
        data = segment['data']
        if segment['type'] not in {'image', 'voice', 'video', 'file'}:
            continue
        if 'botoize.local_upload' in data:
            value = data['botoize.local_upload']
            raw = decode_data(value[9:]) if value.startswith('base64://') else download(value)
        else:
            row = owned_file(key, data['file_id'])
            if row.upstream_file_id and not row.upstream_bot_id:
                segment['data'] = {'file_id': row.upstream_file_id}
                continue
            raw = file_bytes(row)
        import base64
        encoded = base64.b64encode(raw).decode()
        if source == 12:
            uploaded = call(bot, 'upload_file', {'type': 'data', 'name': 'attachment.bin', 'data': encoded}, self_info=own)
            if not isinstance(uploaded, dict) or not isinstance(uploaded.get('file_id'), str):
                raise OneBotError(33000, 'OneBot upload did not return a file ID')
            segment['data'] = {'file_id': uploaded['file_id']}
        else:
            segment['data'] = {'file_id': 'base64://' + encoded}
    if source == 11:
        for segment in wire:
            kind, data = segment['type'], segment['data']
            if kind == 'reply':
                segment['data'] = {'id': str(native_id(data['message_id'], 11, kind='message'))}
            elif kind == 'mention':
                segment['type'], segment['data'] = 'at', {'qq': str(native_id(data['user_id'], 11))}
            elif kind == 'mention_all':
                segment['type'], segment['data'] = 'at', {'qq': 'all'}
            elif kind == 'qq.face':
                segment['type'] = 'face'
            elif kind in {'image', 'voice', 'video', 'file'}:
                if kind == 'file':
                    raise OneBotError(10005, 'OneBot 11 has no standard file message segment')
                segment['type'] = 'record' if kind == 'voice' else kind
                segment['data'] = {'file': data['file_id']}
    return wire


def download_upstream_file(row):
    if row.upstream_digest and not row.upstream_bot_id:
        raise OneBotError(35003, 'Companion attachment source no longer exists')
    bot = row.upstream_bot or row.api_key.bot
    if row.upstream_bot_id:
        primary = row.api_key.bot
        if (not bot.is_active or primary.channel.companion_id != bot.channel_id
                or row.upstream_digest != configuration_digest(bot)):
            raise OneBotError(35003, 'Companion attachment source changed')
    own, _ = identity(bot)
    if onebot_version(bot) == 12:
        data = call(bot, 'get_file', {'file_id': row.upstream_file_id, 'type': 'data'}, self_info=own)
        if not isinstance(data, dict):
            raise OneBotError(33000, 'Invalid OneBot file response')
        return decode_data(data.get('data'))
    # OB11 paths refer to the upstream filesystem; only its public URL can be downloaded.
    data = call(bot, 'get_image', {'file': row.upstream_file_id})
    if not isinstance(data, dict) or not isinstance(data.get('url'), str):
        raise OneBotError(10004, 'Upstream file is not available through a public URL')
    return download(data['url'])


def invoke_upstream(bot, scopes, action, params, echo, key, version, self_info):
    from .onebot import protocol_result, VERSION, known_conversations, resolve_id, public_id, message_record
    from .onebot_events import visible_segments
    source = onebot_version(bot)
    actions = available_actions(source, version)
    if not isinstance(action, str) or action not in actions:
        raise OneBotError(10002, 'Unsupported action for this OneBot upstream bridge')
    if not isinstance(params, dict):
        raise OneBotError(10003, 'params must be an object')
    if version == 12 and echo is not None and not isinstance(echo, str):
        raise OneBotError(10001, 'OneBot 12 echo must be a string')
    def result(data=None):
        return protocol_result(version, data, echo=echo)
    def checked_identity():
        own, name = identity(bot)
        if self_info is not None and self_info != own:
            raise OneBotError(10102, 'Unknown self for this Key')
        return own, name
    if action in {'get_version', 'get_version_info', 'get_supported_actions', 'botoize.get_capabilities', 'botoize.get_known_conversations'}:
        require(scopes, 'query:read')
        fields(params, {})
        if self_info is not None:
            checked_identity()
        if action == 'get_supported_actions':
            return result(sorted(supported_actions(bot, version)))
        if action == 'botoize.get_capabilities':
            return result({'version': str(version), 'upstream_version': str(source), 'actions': sorted(supported_actions(bot, version)),
                           'id_semantics': 'native numeric IDs' if source == version == 11 else 'original string IDs' if version == 12 else 'persistent numeric mappings',
                           'limitations': ['Only the configured upstream Bot is exposed', 'Upstream capabilities and permissions still apply',
                                           'Filesystem paths, credentials and process restart are not exposed']})
        if action == 'botoize.get_known_conversations':
            return result(known_conversations(key, version))
        return result(VERSION.copy() if version == 12 else {'app_name': 'botoize', 'app_version': VERSION['version'], 'protocol_version': 'v11'})
    if action == 'get_latest_events':
        require(scopes, 'events:read')
        if self_info is not None:
            checked_identity()
        from .onebot_poll import latest_events
        return result(latest_events(key, params))
    if action in {'upload_file', 'upload_file_fragmented', 'get_file', 'get_file_fragmented'}:
        require(scopes, 'media:upload' if action.startswith('upload') else 'events:read')
        if self_info is not None:
            checked_identity()
        return result(file_action(key, action, params))
    if action == 'clean_cache':
        require(scopes, 'query:read')
        fields(params, {})
        from .models import OneBotFile
        from django.utils import timezone
        OneBotFile.objects.filter(api_key=key, expires_at__lte=timezone.now()).delete()
        return result()
    if action in {'can_send_image', 'can_send_record'}:
        require(scopes, 'query:read')
        fields(params, {})
        allowed = {'messages:send', 'media:upload'} <= set(scopes)
        if source == 11 and allowed:
            answer = call(bot, action)
            allowed = isinstance(answer, dict) and answer.get('yes') is True
        elif source == 12:
            # OB12 has no can_send_record/image equivalent.
            allowed = False
        return result({'yes': allowed})
    if action in {'get_login_info', 'get_self_info', 'get_status'}:
        require(scopes, 'query:read')
        fields(params, {})
        own, name = checked_identity()
        if action == 'get_status':
            raw = call(bot, 'get_status')
            if not isinstance(raw, dict):
                raise OneBotError(33000, 'Invalid OneBot status response')
            if source == 12:
                bots = [r for r in raw.get('bots', []) if isinstance(r, dict) and r.get('self') == own]
                online = any(r.get('online') is True for r in bots)
            else:
                online = raw.get('online') is True
            return result({'good': raw.get('good') is True, 'bots': [{'self': own, 'online': online}]} if version == 12 else
                          {'good': raw.get('good') is True, 'online': online})
        return result({'user_id': own['user_id'], 'user_name': name, 'user_displayname': ''} if version == 12 else
                      {'user_id': public_id(bot, 'user', own['user_id'], 11), 'nickname': name})
    if action in {'delete_msg', 'delete_message', 'get_msg'}:
        require(scopes, 'events:read' if action == 'get_msg' else 'messages:delete')
        fields(params, {'message_id'}, {'message_id'})
        row = message_record(bot, key, params['message_id'], version)
        if action == 'get_msg':
            if self_info is not None:
                checked_identity()
            return result({'time': int(row.sent_at), 'message_type': row.conversation_type,
                           'message_id': public_id(bot, 'message', row.message_id, 11),
                           'real_id': public_id(bot, 'message', row.message_id, 11),
                           'sender': {'user_id': public_id(bot, 'user', row.sender_id, 11) if row.sender_id else 0},
                           'message': encode_segments(bot, visible_segments(row, key), 11, event=True)})
        if row.incoming:
            raise OneBotError(10004, 'Only messages sent through this account may be deleted')
        if not row.deleted:
            own, _ = checked_identity()
            call(bot, 'delete_msg' if source == 11 else 'delete_message', {'message_id': native_id(row.message_id, source, kind='message')}, self_info=own)
            row.deleted = True
            row.save(update_fields=['deleted'])
        return result()
    if action in {'send_message', 'send_msg', 'send_private_msg', 'send_group_msg'}:
        require(scopes, 'messages:send')
        kind = params.get('detail_type') if version == 12 else ('private' if action == 'send_private_msg' else
               'group' if action == 'send_group_msg' else params.get('message_type', 'group' if 'group_id' in params else 'private'))
        if kind not in {'private', 'group', 'channel'} or (kind == 'channel' and source == 11):
            raise OneBotError(10004, 'Unsupported target type')
        target_key = {'private': 'user_id', 'group': 'group_id', 'channel': 'channel_id'}[kind]
        allowed = {target_key, 'message'} | ({'detail_type'} if version == 12 else {'auto_escape'})
        if kind == 'channel':
            allowed.add('guild_id')
        if action == 'send_msg':
            allowed.add('message_type')
        fields(params, allowed, {target_key, 'message'} | ({'detail_type'} if version == 12 else set()))
        target = resolve_id(bot, 'user' if kind == 'private' else 'group', params[target_key], version)
        if kind == 'channel':
            if not unrestricted(key):
                raise OneBotError(35003, 'Channel messages require unrestricted conversation grants')
        else:
            check_conversation(key, kind == 'private', target)
        message = params['message']
        if version == 11:
            from .onebot import segments11
            message = segments11(message, params.get('auto_escape', False))
        canonical = canonical_input(bot, key, message, version, scopes, kind, target)
        if source == 11 and any(s['type'] == 'file' for s in canonical):
            raise OneBotError(10005, 'OneBot 11 has no standard file message segment')
        own, _ = checked_identity()
        wire = wire_message(bot, key, canonical, own)
        outgoing = {target_key: native_id(target, source), 'message': wire}
        if source == 12:
            outgoing['detail_type'] = kind
            if kind == 'channel':
                outgoing['guild_id'] = native_id(params.get('guild_id'), 12)
        response = call(bot, 'send_message' if source == 12 else 'send_private_msg' if kind == 'private' else 'send_group_msg', outgoing, self_info=own)
        if not isinstance(response, dict):
            raise OneBotError(33000, 'Message outcome unknown; do not blindly retry')
        try:
            mid = str(native_id(response.get('message_id'), source, kind='message'))
        except OneBotError:
            raise OneBotError(33000, 'Message outcome unknown; upstream returned an invalid message ID') from None
        # Do not persist arbitrary URLs or Base64 in outgoing message history.
        saved = copy.deepcopy(canonical)
        for segment in saved:
            if 'botoize.local_upload' in segment['data']:
                segment['type'], segment['data'] = 'botoize.sent_media', {}
        now = time.time()
        OneBotMessage.objects.get_or_create(bot=bot, source_digest=configuration_digest(bot), message_id=mid, defaults={
            'is_direct': kind == 'private', 'target_id': target, 'sender_id': bot.app_id,
            'segments': saved, 'sent_at': now, 'created_by': key.user,
            'conversation_type': kind, 'guild_id': params.get('guild_id', ''),
        })
        return result({'message_id': public_id(bot, 'message', mid, version), **({'time': now} if version == 12 else {})})
    required, allowed = RULES[action]
    require(scopes, required)
    fields(params, allowed)
    validate_parameters(action, params, version)
    upstream_action, outgoing = action, copy.deepcopy(params)
    if action in {'get_friend_list', 'get_group_list'}:
        pass  # Results are filtered through the entire grant chain below.
    elif 'guild_id' in allowed or action == 'get_guild_list':
        if not unrestricted(key):
            raise OneBotError(35003, 'Guild/channel operations require unrestricted conversation grants')
    elif 'group_id' in allowed:
        if 'group_id' not in params:
            raise OneBotError(10003, 'group_id required')
        group = resolve_id(bot, 'group', params['group_id'], version)
        check_conversation(key, False, group)
    elif 'user_id' in allowed:
        if 'user_id' not in params:
            raise OneBotError(10003, 'user_id required')
        user = resolve_id(bot, 'user', params['user_id'], version)
        check_conversation(key, True, user)
    elif 'flag' in allowed:
        flag = params.get('flag')
        if not isinstance(flag, str) or not re.fullmatch(r'upstream:[0-9]{1,18}', flag):
            raise OneBotError(10003, 'Current local request flag required')
        entry = EventOutbox.objects.filter(event_id=int(flag[9:]), is_stream=True,
            grant__user_id=key.user_id, grant__bot_id=bot.pk, grant_revision=key.grant_revision).select_related('event').first()
        if entry is None or not event_allowed(key, entry.event.payload):
            raise OneBotError(35003, 'Request event is outside this grant')
        original = entry.event.payload.get('d', {}).get('event', {})
        if entry.event.payload.get('d', {}).get('source_digest') != configuration_digest(bot):
            raise OneBotError(35003, 'Request belongs to a previous upstream configuration')
        expected = 'group' if action == 'set_group_add_request' else 'friend'
        if original.get('post_type') != 'request' or original.get('request_type') != expected:
            raise OneBotError(10003, 'Request flag type mismatch')
        if expected == 'group':
            subtype = original.get('sub_type')
            if subtype not in {'add', 'invite'} or any(outgoing.get(name, subtype) != subtype for name in ('type', 'sub_type')):
                raise OneBotError(10003, 'Request subtype mismatch')
            outgoing.pop('type', None)
            outgoing['sub_type'] = subtype
        outgoing['flag'] = original['flag']
    for name in ['group_id', 'user_id', 'guild_id', 'channel_id']:
        if name in outgoing:
            outgoing[name] = native_id(resolve_id(bot, 'group' if name == 'group_id' else 'user', outgoing[name], version), source)
    if source != version:
        aliases = {'get_stranger_info': 'get_user_info', 'get_user_info': 'get_stranger_info',
                   'leave_group': 'set_group_leave', 'set_group_leave': 'leave_group',
                   'get_login_info': 'get_self_info', 'get_self_info': 'get_login_info'}
        upstream_action = aliases.get(action, action)
        outgoing.pop('no_cache', None)
        if action == 'set_group_leave' and outgoing.pop('is_dismiss', False):
            raise OneBotError(10004, 'OneBot 12 leave_group does not support dismiss')
    own, _ = checked_identity()
    response = call(bot, upstream_action, outgoing, self_info=own)
    return result(translate_result(bot, key, action, response, source, version))


def validate_parameters(action, params, version):
    """Validate standard required fields before contacting an upstream service."""
    required = {
        'set_group_kick': {'user_id'}, 'set_group_ban': {'user_id'},
        'set_group_admin': {'user_id'}, 'set_group_special_title': {'user_id'},
        'set_group_name': {'group_name'}, 'set_group_add_request': {'flag'},
        'set_friend_add_request': {'flag'}, 'set_guild_name': {'guild_id', 'guild_name'},
        'set_channel_name': {'guild_id', 'channel_id', 'channel_name'},
        'get_group_member_info': {'user_id'}, 'get_guild_info': {'guild_id'},
        'get_channel_info': {'guild_id', 'channel_id'}, 'get_channel_list': {'guild_id'},
        'get_guild_member_info': {'guild_id', 'user_id'}, 'get_guild_member_list': {'guild_id'},
        'get_channel_member_info': {'guild_id', 'channel_id', 'user_id'},
        'get_channel_member_list': {'guild_id', 'channel_id'},
        'leave_guild': {'guild_id'}, 'leave_channel': {'guild_id', 'channel_id'},
    }.get(action, set())
    if not required <= params.keys():
        raise OneBotError(10003, 'Missing required OneBot parameters')
    for name in {'enable', 'approve', 'reject_add_request', 'no_cache', 'is_dismiss', 'joined_only'} & params.keys():
        if type(params[name]) is not bool:
            if version == 11 and params[name] in ('true', 'false'):
                params[name] = params[name] == 'true'
            else:
                raise OneBotError(10003, 'Boolean parameter required')
    for name in {'duration', 'times'} & params.keys():
        value = params[name]
        if version == 11 and isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value):
            value = int(value)
        if type(value) is not int or not 0 <= value <= 2**31 - 1:
            raise OneBotError(10003, 'Invalid numeric parameter')
        params[name] = value
    for name in {'card', 'group_name', 'guild_name', 'channel_name', 'special_title', 'reason', 'remark'} & params.keys():
        if not isinstance(params[name], str) or len(params[name]) > 4096:
            raise OneBotError(10003, 'Invalid text parameter')
    if action == 'get_group_honor_info' and params.get('type') not in {'talkative', 'performer', 'legend', 'strong_newbie', 'emotion', 'all'}:
        raise OneBotError(10003, 'Invalid honor type')


def translate_result(bot, key, action, value, source, version):
    from .onebot import public_id
    from .onebot_events import safe_extension
    from .conversations import grant_chain, key_grant
    if action in {'get_group_list', 'get_friend_list'}:
        if not isinstance(value, list):
            raise OneBotError(33000, 'Invalid upstream list')
        direct = action == 'get_friend_list'
        name = 'user_id' if direct else 'group_id'
        for policy in (*grant_chain(key_grant(key)), key):
            if not policy.all_conversations:
                allowed = set(policy.conversations.filter(is_direct=direct).values_list('target_id', flat=True))
                value = [row for row in value if isinstance(row, dict) and str(row.get(name)) in allowed]
    def convert(row):
        if not isinstance(row, dict):
            return row
        result = safe_extension(row)
        for name, kind in [('user_id', 'user'), ('group_id', 'group'), ('message_id', 'message')]:
            if name in result:
                result[name] = public_id(bot, kind, str(result[name]), version)
        if source != version:
            if version == 12 and 'nickname' in result:
                result['user_name'] = result.pop('nickname')
                result['user_displayname'] = result.pop('card', '')
            elif version == 11 and 'user_name' in result:
                result['nickname'] = result.pop('user_name')
                result['card'] = result.pop('user_displayname', '')
        return result
    return [convert(row) for row in value] if isinstance(value, list) else convert(value)
