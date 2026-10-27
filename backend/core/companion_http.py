"""Equivalent group operations for raw QQ HTTP; unsupported translations preserve the primary result."""
import json
import re
from datetime import datetime
from urllib.parse import parse_qs

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .onebot_common import OneBotError


def management_fallback(request, path, primary):
    from .companion_actions import try_management
    from .onebot import protocol_result
    from .upstreams import onebot_version
    bot = request.auth.bot
    if not bot.channel.companion_id:
        return primary
    status, raw, _ = primary
    try:
        payload = json.loads(raw) if raw else {}
        failed = not 200 <= status < 300 or (isinstance(payload, dict)
            and (payload.get('code', 0) not in (None, 0) or payload.get('errcode', 0) not in (None, 0)))
        if not failed:
            return primary
        route = re.fullmatch(r'v2/groups/([A-Za-z0-9_-]{1,128})/(info|members(?:/[A-Za-z0-9_-]{1,128})?|batch_remove_members|restrict_chat_setting)', path)
        if not route:
            return primary
        group, operation = route.groups()
        query = parse_qs(request.META.get('QUERY_STRING', ''), keep_blank_values=True)
        data = json.loads(request.body) if request.body else {}
        params = {'group_id': group}
        action = None
        if request.method == 'GET' and operation == 'info' and not query:
            action = 'get_group_info'
        elif request.method == 'GET' and operation == 'members' and set(query) <= {'cursor'} and not any(any(v for v in values) for values in query.values()):
            action = 'get_group_member_list'
        elif request.method == 'GET' and operation.startswith('members/') and not query:
            action, params['user_id'] = 'get_group_member_info', operation.split('/')[1]
        elif request.method == 'POST' and operation == 'batch_remove_members' and not query:
            if set(data) <= {'member_openids', 'add_to_member_blacklist'} and isinstance(data.get('member_openids'), list) and len(data['member_openids']) == 1:
                action = 'set_group_kick'
                params.update(user_id=data['member_openids'][0], reject_add_request=data.get('add_to_member_blacklist', False))
        elif request.method == 'POST' and operation == 'restrict_chat_setting' and not query:
            if set(data) == {'members'} and isinstance(data['members'], list) and len(data['members']) == 1:
                member = data['members'][0]
                if isinstance(member, dict) and set(member) <= {'member_openid', 'op', 'mute_expire_at'} and member.get('op') in {'add', 'del'}:
                    duration = 0 if member['op'] == 'del' else max(1, int((datetime.fromisoformat(member['mute_expire_at'].replace('Z', '+00:00')) - timezone.now()).total_seconds()))
                    action = 'set_group_ban'
                    params.update(user_id=member['member_openid'], duration=duration)
        if action is None:
            return primary
        # Use the slave's supported dialect for moderation, without changing primary OpenID inputs.
        version = 12
        if action in {'set_group_kick', 'set_group_ban'}:
            slave = bot.channel.companion.bots.first()
            if not slave or onebot_version(slave) != 11:
                return primary
            from .onebot import public_id
            version = 11
            params['group_id'] = public_id(bot, 'group', group, 11)
            params['user_id'] = public_id(bot, 'user', params['user_id'], 11)
        response = try_management(bot, request.effective_scopes, action, params, None, request.auth,
            version, None, lambda: protocol_result(version, code=34000))
        if response.data['retcode']:
            return primary
        result = response.data['data']
        if action == 'get_group_info':
            output = {'group_openid': group, 'group_name': result.get('group_name', '')}
            if type(result.get('member_count')) is int:
                output['group_member_num'] = result['member_count']
        elif action in {'get_group_member_list', 'get_group_member_info'}:
            def member(row):
                return {'member_openid': row['user_id'], 'username': row.get('user_name', ''),
                        'botoize.source': 'companion'}
            output = {'members': [member(row) for row in result], 'next_cursor': ''} if isinstance(result, list) else member(result)
        else:
            output = {'remove_members_result': 'success', 'add_to_member_blacklist_fail_openids': []} if action == 'set_group_kick' else {}
        return 200, json.dumps(output, ensure_ascii=False).encode(), {'Content-Type': 'application/json', 'X-Botoize-Source': 'companion'}
    except PermissionDenied:
        raise
    except (OneBotError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return primary
