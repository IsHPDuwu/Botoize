"""Current QQ group APIs (2026 autogen docs); never translate QQ groups to guilds."""
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.utils import timezone

from .conversations import check_conversation
from .models import EventOutbox
from .official import _request
from .onebot_common import OneBotError, fields, integer

GROUP_SCOPES = {
    'get_group_info': 'groups:read', 'get_group_member_info': 'group-members:read',
    'get_group_member_list': 'group-members:read', 'botoize.get_group_members_page': 'group-members:read',
    'set_group_kick': 'group-moderation:write', 'set_group_ban': 'group-moderation:write',
    'set_group_add_request': 'group-requests:write', 'qq.set_group_kick': 'group-moderation:write',
    'qq.set_group_ban': 'group-moderation:write', 'qq.set_group_add_request': 'group-requests:write',
}


def boolean(value):
    if value in ('true', 'false'):
        value = value == 'true'
    if type(value) is not bool:
        raise OneBotError(10003, 'Expected a boolean')
    return value


def member_info(bot, group, data, version):
    from .onebot import public_id
    user = data.get('member_openid')
    if not isinstance(user, str) or not user:
        raise ValueError('Missing member ID')
    if version == 12:
        return {'user_id': user, 'user_name': data.get('username', ''), 'user_displayname': ''}
    try:
        joined = int(datetime.fromisoformat(data.get('joined_at', '').replace('Z', '+00:00')).timestamp())
    except (ValueError, TypeError, AttributeError):
        joined = 0
    return {'group_id': public_id(bot, 'group', group, 11), 'user_id': public_id(bot, 'user', user, 11),
            'nickname': data.get('username', ''), 'card': '', 'sex': 'unknown', 'age': 0, 'area': '',
            'join_time': joined, 'last_sent_time': 0, 'level': '', 'role': data.get('member_role', ''),
            'unfriendly': False, 'title': '', 'title_expire_time': 0, 'card_changeable': False,
            'botoize.unknown_fields': ['card', 'sex', 'age', 'area', 'last_sent_time', 'level', 'unfriendly', 'title', 'card_changeable']}


def group_action(bot, key, action, params, version):
    from .onebot import official_json, public_id, resolve_id
    original_action = action
    action = action.removeprefix('qq.')
    if action == 'set_group_add_request':
        fields(params, {'flag', 'sub_type', 'type', 'approve', 'reason'}, {'flag'})
        flag = params['flag']
        if not isinstance(flag, str) or not flag.startswith('botoize:') or not flag[8:].isdigit() or len(flag) > 26:
            raise OneBotError(10003, 'Unknown request flag')
        row = EventOutbox.objects.filter(event_id=int(flag[8:]), is_stream=True,
                grant__user_id=key.user_id, grant__bot_id=key.bot_id, grant_revision=key.grant_revision,
                event__event_type='GROUP_JOIN_REQUEST').select_related('event').first()
        if row is None:
            raise OneBotError(35003, 'Request is outside the current event grant')
        data = row.event.payload['d']
        target = resolve_id(bot, 'group', data['group_openid'], 12)
        check_conversation(key, False, target)
        if params.get('sub_type', params.get('type', 'add')) != 'add':
            raise OneBotError(10004, 'Only user join requests (not bot invitations) are supported')
        approved, reason = boolean(params.get('approve', True)), params.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 1000:
            raise OneBotError(10003, 'Invalid rejection reason')
        member = resolve_id(bot, 'user', data['member_openid'], 12)
        official_json(_request(bot, 'POST', f'v2/groups/{target}/approval_join_request/{member}', body=json.dumps({
            'op': 'approve' if approved else 'decline', 'join_request_id': data['join_request_id'],
            **({'reject_reason': reason} if not approved else {}),
        }).encode()), empty=True)
        return None
    allowed = ({'group_id', 'no_cache'} if action == 'get_group_info' else
               {'group_id', 'user_id', 'no_cache'} if action == 'get_group_member_info' else
               {'group_id'} if action == 'get_group_member_list' else
               {'group_id', 'cursor'} if original_action == 'botoize.get_group_members_page' else
               {'group_id', 'user_id', 'reject_add_request'} if action == 'set_group_kick' else
               {'group_id', 'user_id', 'duration'})
    fields(params, allowed, {'group_id'} | ({'user_id'} if action in {'get_group_member_info', 'set_group_kick', 'set_group_ban'} else set()))
    if 'no_cache' in params:
        boolean(params['no_cache'])  # Always live; no cache exists here.
    target = resolve_id(bot, 'group', params['group_id'], version)
    if len(target) > 128:
        raise OneBotError(10003, 'Invalid QQ group ID')
    check_conversation(key, False, target)
    path = f'v2/groups/{target}'
    if action == 'get_group_info':
        data = official_json(_request(bot, 'GET', path + '/info'))
        result = {'group_id': public_id(bot, 'group', target, version), 'group_name': data.get('group_name', '')}
        if version == 11:
            result.update(member_count=data.get('group_member_num', 0), max_member_count=0,
                          **{'botoize.unknown_fields': ['max_member_count']})
        return result
    if action == 'get_group_member_info':
        user = resolve_id(bot, 'user', params['user_id'], version)
        return member_info(bot, target, official_json(_request(bot, 'GET', path + '/members/' + user)), version)
    if action in {'get_group_member_list', 'botoize.get_group_members_page'}:
        cursor, seen, members = params.get('cursor', ''), set(), []
        if not isinstance(cursor, str) or len(cursor) > 2048:
            raise OneBotError(10003, 'Invalid member cursor')
        for _ in range(20):
            data = official_json(_request(bot, 'GET', path + '/members', urlencode({'cursor': cursor})))
            items, next_cursor = data.get('members'), data.get('next_cursor', '')
            if not isinstance(items, list) or not isinstance(next_cursor, str):
                raise ValueError('Invalid member page')
            members.extend(member_info(bot, target, item, version) for item in items)
            if original_action == 'botoize.get_group_members_page':
                return {'members': members, 'next_cursor': next_cursor}
            if not next_cursor:
                return members
            if next_cursor in seen:
                raise OneBotError(34000, 'QQ returned a repeating member cursor')
            seen.add(next_cursor)
            cursor = next_cursor
        raise OneBotError(10004, 'Member list exceeds 20 pages; use botoize.get_group_members_page, no partial list returned')
    user = resolve_id(bot, 'user', params['user_id'], version)
    if action == 'set_group_kick':
        blocked = boolean(params.get('reject_add_request', False))
        data = official_json(_request(bot, 'POST', path + '/batch_remove_members', body=json.dumps({
            'member_openids': [user], 'add_to_member_blacklist': blocked,
        }).encode()))
        if data.get('remove_members_result') != 'success' or (blocked and data.get('add_to_member_blacklist_fail_openids')):
            raise OneBotError(34000, 'QQ kick/blacklist operation did not fully succeed')
        return None
    duration = params.get('duration', 1800)
    if version == 11 and isinstance(duration, str) and duration.isascii() and duration.isdigit() and len(duration) <= 7:
        duration = int(duration)
    duration = integer(duration, 0, 30 * 86400)
    item = {'member_openid': user, 'op': 'add' if duration else 'del',
            'mute_expire_at': (timezone.now() + timedelta(seconds=duration)).isoformat() if duration else ''}
    official_json(_request(bot, 'POST', path + '/restrict_chat_setting', body=json.dumps({'members': [item]}).encode()), empty=True)
    return None
