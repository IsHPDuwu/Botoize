"""Read-only user/message lookups for an authenticated Channel.

These lookups intentionally don't require action scopes, conversation selection or
an event delivery snapshot. They never select a different primary/companion.
"""
from .onebot_common import OneBotError, fields

QUERY_ACTIONS = {'get_msg', 'get_stranger_info', 'get_user_info'}


def invoke_query(bot, action, params, echo, key, version, self_info):
    from .companion_actions import current_authority
    from .onebot import identity, protocol_result
    if not isinstance(params, dict):
        raise OneBotError(10003, 'params must be an object')
    if version == 12 and echo is not None and not isinstance(echo, str):
        raise OneBotError(10001, 'OneBot 12 echo must be a string')
    if key is not None:
        key = current_authority(key)
        if key.bot_id != bot.pk:
            raise OneBotError(35003, 'Key belongs to another Channel')
    if self_info is not None and self_info != identity(bot)[0]:
        raise OneBotError(10102, 'Unknown self for this Key')
    data = lookup_message(bot, key, params, version) if action == 'get_msg' else lookup_user(bot, params, version)
    if key is not None:
        current_authority(key)  # Re-check revocation after a network lookup.
    return protocol_result(version, data, echo=echo)


def lookup_user(bot, params, version):
    from .companions import companion_bot
    from .onebot import identity, resolve_id, public_id
    from .onebot_ids import real_for_original
    from .onebot_upstream import call, identity as upstream_identity, native_id
    from .onebot_events import safe_extension
    from .upstreams import onebot_version
    fields(params, {'user_id', 'no_cache'}, {'user_id'})
    value = params['user_id']
    own = bot.channel.onebot_self_id
    # Old sent-message records didn't store the sender; Koishi then asks for 0.
    if str(value) == '0':
        own_info, name = identity(bot)
        original = own_info['user_id']
        raw = {'nickname': name}
    else:
        try:
            original = resolve_id(bot, 'user', value, version)
        except OneBotError:
            original = None
        if original and own and original == own:
            own_info, name = identity(bot)
            raw = {'nickname': name}
        else:
            remote = bot if onebot_version(bot) else companion_bot(bot.channel)
            real = original if onebot_version(bot) else real_for_original(bot, 'user', original) if original else None
            if remote is None:
                raise OneBotError(35004, 'User information unavailable without a OneBot upstream')
            source = onebot_version(remote)
            if real is None:
                # Unknown OB11 numbers can be queried as real QQ accounts. Never
                # forward an unmapped official OpenID as a numeric account.
                if version != 11:
                    raise OneBotError(35004, 'No OneBot identity mapping for this user')
                real = str(native_id(value, 11))
            own_info, _ = upstream_identity(remote)
            raw = call(remote, 'get_stranger_info' if source == 11 else 'get_user_info',
                {'user_id': native_id(real, source)}, self_info=own_info)
            if not isinstance(raw, dict) or str(raw.get('user_id')) != real:
                raise OneBotError(33000, 'Invalid upstream user information')
            if not onebot_version(bot):
                from .companions import shadow_user
                original = shadow_user(bot, real)
    result = safe_extension(raw)
    result['user_id'] = public_id(bot, 'user', original, version)
    if version == 12:
        result['user_name'] = result.pop('nickname', result.get('user_name', ''))
        result['user_displayname'] = result.pop('card', result.get('user_displayname', ''))
    else:
        result['nickname'] = result.pop('user_name', result.get('nickname', ''))
    return result


def lookup_message(bot, key, params, version):
    from .onebot import message_record, public_id, identity
    from .onebot_events import visible_segments, to11_segments, message_metadata, raw11
    from .onebot_upstream_actions import encode_segments
    from .upstreams import onebot_version
    fields(params, {'message_id'}, {'message_id'})
    try:
        row = message_record(bot, key, params['message_id'], version, lookup=True)
    except OneBotError as exc:
        if exc.code not in {10003, 35004}:
            raise
        row = fetch_message(bot, params['message_id'], version)
    sender = row.sender_id
    if not sender and not row.incoming:
        sender = bot.channel.onebot_self_id or identity(bot)[0]['user_id']
        row.sender_id = sender
        row.save(update_fields=['sender_id'])
    if not sender:
        # Repair old records from received history rather than inventing an account.
        event = row.source_event or row.context_event
        if event:
            from .onebot_events import parsed_message
            parsed = parsed_message(event.payload)
            sender = parsed[2] if parsed else ''
        if sender:
            row.sender_id = sender
            row.save(update_fields=['sender_id'])
    segments = visible_segments(row, key)
    wire = encode_segments(bot, segments, 11, event=True) if onebot_version(bot) else to11_segments(bot, segments)
    uid = public_id(bot, 'user', sender, 11) if sender else 0
    result = {'time': int(row.sent_at), 'message_type': row.conversation_type,
        'message_id': public_id(bot, 'message', row.message_id, 11),
        'real_id': public_id(bot, 'message', row.message_id, 11),
        'sender': {'user_id': uid, 'nickname': '', 'sex': 'unknown', 'age': 0},
        'user_id': uid, 'message': wire, 'raw_message': raw11(wire), **message_metadata(row)}
    if row.conversation_type == 'group':
        result['group_id'] = public_id(bot, 'group', row.target_id, 11)
    return result


def fetch_message(bot, value, version):
    from .companions import companion_bot, shadow_user, pairing_digest
    from .models import OneBotMessage
    from .onebot import resolve_id
    from .onebot_ids import real_for_original, learn_real_id
    from .onebot_upstream import call, native_id, configuration_digest
    from .onebot_upstream_events import normalize_event, canonical_message
    from .upstreams import onebot_version
    remote = bot if onebot_version(bot) else companion_bot(bot.channel)
    if remote is None or onebot_version(remote) != 11:
        raise OneBotError(35004, 'Message context unavailable')
    try:
        original = resolve_id(bot, 'message', value, version)
    except OneBotError:
        original = None
    real = original if onebot_version(bot) else real_for_original(bot, 'message', original) if original else None
    if real is None:
        if version != 11:
            raise OneBotError(35004, 'No OneBot mapping for this message')
        real = str(native_id(value, 11, kind='message'))
    data = call(remote, 'get_msg', {'message_id': native_id(real, 11, kind='message')})
    if not isinstance(data, dict) or str(data.get('message_id')) != real:
        raise OneBotError(33000, 'Invalid upstream message response')
    event = {**data, 'self_id': int(remote.app_id), 'post_type': 'message',
        'user_id': data.get('sender', {}).get('user_id', data.get('user_id'))}
    if data.get('message_type') == 'private':
        event.setdefault('user_id', data.get('user_id'))
    row = canonical_message(remote, normalize_event(remote, event))
    if remote.pk == bot.pk:
        return row
    from .message_links import bridge_segments
    import hashlib
    original = original or 'companion_' + hashlib.sha256(('message:' + real).encode()).hexdigest()[:40]
    # Unknown official virtual IDs resolve to their real upstream ID only when the
    # upstream confirms it; preserve the official OpenID if it was already known.
    learn_real_id(bot, 'message', original, real)
    if row.is_direct:
        target = shadow_user(bot, row.target_id)
    else:
        match = bot.channel.group_matches.filter(companion_id=remote.channel_id,
            companion_group=row.target_id, enabled=True).first()
        target = match.primary_group if match else 'companion_' + hashlib.sha256(('group:' + row.target_id).encode()).hexdigest()[:40]
        learn_real_id(bot, 'group', target, row.target_id)
    return OneBotMessage.objects.get_or_create(bot=bot, source_digest='', message_id=original, defaults={
        'incoming': True, 'is_direct': row.is_direct, 'conversation_type': row.conversation_type,
        'target_id': target, 'sender_id': shadow_user(bot, row.sender_id), 'sent_at': row.sent_at,
        'segments': bridge_segments(bot, row.segments), 'attachment_bot': remote,
        'attachment_digest': configuration_digest(remote), 'context_pairing': pairing_digest(bot.channel)})[0]
