"""Management fallback on primary authorization; sends never enter this module."""
import copy

from .conversations import check_conversation, key_grant
from .models import ChannelGroupMatch
from .onebot_common import OneBotError, fields
from .onebot_ids import real_for_original, original_for_real
from .onebot_upstream import call, identity, native_id
from .onebot_upstream_actions import RULES, validate_parameters, available_actions
from .upstreams import onebot_version

MANAGEMENT = {name for name in RULES if ('group' in name or name in {
    'get_friend_list', 'get_stranger_info', 'get_user_info', 'send_like'}) and name not in {
        'set_group_add_request', 'set_friend_add_request', 'get_login_info', 'get_self_info'}}


def current_authority(key, scope=None):
    from django.utils import timezone
    from rest_framework.exceptions import PermissionDenied
    from .models import ApiKey
    current = ApiKey.objects.select_related('user', 'bot').filter(pk=key.pk).first() if key else None
    if (not current or current.revoked_at or not current.user.is_active or not current.bot.is_active
            or (current.expires_at and current.expires_at <= timezone.now())):
        raise PermissionDenied('Primary Key no longer valid')
    grant = key_grant(current)
    if scope is not None and (scope not in current.scopes or scope not in grant.scopes):
        raise PermissionDenied('Primary scope no longer valid')
    return current


def extra_actions(bot, version):
    from .companions import companion_bot
    slave = companion_bot(bot.channel)
    return MANAGEMENT & available_actions(onebot_version(slave), version) if slave else set()


def try_management(bot, scopes, action, params, echo, key, version, self_info, primary):
    from .companions import companion_bot, shadow_user
    from .onebot import protocol_result, resolve_id, public_id
    if not bot.channel.companion_id or action not in MANAGEMENT:
        return primary()
    required, allowed = RULES[action]
    if required not in scopes:
        raise OneBotError(35003, required + ' scope required')
    fields(params, allowed)
    params = copy.deepcopy(params)
    validate_parameters(action, params, version)
    group = None
    if 'group_id' in allowed:
        fields(params, allowed, {'group_id'})
        group = resolve_id(bot, 'group', params['group_id'], version)
        check_conversation(key, False, group)
    elif 'user_id' in allowed:
        fields(params, allowed, {'user_id'})
        check_conversation(key, True, resolve_id(bot, 'user', params['user_id'], version))
    result = primary()
    if result.data['retcode'] not in {1404, 1500, 1502, 10002, 33000, 34000}:
        return result
    slave = companion_bot(bot.channel)
    if not slave or action not in extra_actions(bot, version):
        return result
    key = current_authority(key, required)
    if group is not None:
        check_conversation(key, False, group)
    # Self always names the primary. It can never select an arbitrary companion Bot.
    if self_info is not None:
        from .onebot import identity as primary_identity
        if self_info != primary_identity(bot)[0]:
            raise OneBotError(10102, 'Unknown primary self')
    matches = ChannelGroupMatch.objects.filter(channel=bot.channel, companion=slave.channel, enabled=True)
    outgoing = copy.deepcopy(params)
    if group is not None:
        mapping = matches.filter(primary_group=group).first()
        if not mapping:
            return result
        outgoing['group_id'] = native_id(mapping.companion_group, onebot_version(slave))
    if 'user_id' in outgoing:
        original = resolve_id(bot, 'user', params['user_id'], version)
        real = real_for_original(bot, 'user', original)
        if not real and group is not None:
            from .identity_probes import ensure_identity
            ensure_identity(bot, group, original=original)
            real = real_for_original(bot, 'user', original)
        if not real and original == bot.channel.onebot_self_id:
            from .self_identity import repair_self_identity
            repair_self_identity(bot)
            real = real_for_original(bot, 'user', original)
        if not real:
            return result  # Never pass a QQ OpenID to an unrelated numeric account.
        outgoing['user_id'] = native_id(real, onebot_version(slave))
    aliases = {'get_stranger_info': 'get_user_info', 'get_user_info': 'get_stranger_info',
               'set_group_leave': 'leave_group', 'leave_group': 'set_group_leave'}
    remote_action = aliases.get(action, action) if onebot_version(slave) != version else action
    if onebot_version(slave) == 12:
        outgoing.pop('no_cache', None)
        if outgoing.pop('is_dismiss', False):
            raise OneBotError(10004, 'Companion OneBot 12 cannot dismiss a group')
    own, _ = identity(slave)
    raw = call(slave, remote_action, outgoing, self_info=own)
    from .onebot_events import safe_extension
    raw = safe_extension(raw)
    def convert(row):
        if not isinstance(row, dict):
            return row
        row = copy.deepcopy(row)
        if 'group_id' in row:
            match = matches.filter(companion_group=str(row['group_id'])).first()
            if not match:
                raise OneBotError(33000, 'Companion returned an unmatched group')
            row['group_id'] = public_id(bot, 'group', match.primary_group, version)
        if 'user_id' in row:
            row['user_id'] = public_id(bot, 'user', shadow_user(bot, str(row['user_id'])), version)
        if version == 12 and 'nickname' in row:
            row['user_name'] = row.pop('nickname')
            row['user_displayname'] = row.pop('card', '')
        elif version == 11 and 'user_name' in row:
            row['nickname'] = row.pop('user_name')
            row['card'] = row.pop('user_displayname', '')
        return row
    if action == 'get_group_list':
        if not isinstance(raw, list):
            raise OneBotError(33000, 'Invalid companion group list')
        visible = []
        for row in raw:
            match = matches.filter(companion_group=str(row.get('group_id'))).first() if isinstance(row, dict) else None
            if match:
                from rest_framework.exceptions import PermissionDenied
                try:
                    check_conversation(key, False, match.primary_group)
                except PermissionDenied:
                    continue
                visible.append(convert(row))
        raw = visible
    elif action == 'get_friend_list':
        if not isinstance(raw, list):
            raise OneBotError(33000, 'Invalid companion friend list')
        from rest_framework.exceptions import PermissionDenied
        visible = []
        for row in raw:
            original = original_for_real(bot, 'user', str(row.get('user_id'))) if isinstance(row, dict) else None
            if original is None:
                continue
            try:
                check_conversation(key, True, original)
            except PermissionDenied:
                continue
            visible.append(convert(row))
        raw = visible
    else:
        raw = [convert(row) for row in raw] if isinstance(raw, list) else convert(raw)
    return protocol_result(version, raw, echo=echo)
