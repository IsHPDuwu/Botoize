import json
import re

from rest_framework.response import Response

from .official import OfficialCredentialError, get_self, send_message
from .onebot_ids import original_id, virtual_id


def result(data=None, retcode=0, message='', echo=None):
    return Response({'status': 'ok' if retcode == 0 else 'failed', 'retcode': retcode,
                     'data': data, 'message': message, 'echo': echo})


def invoke(bot, scopes, action, params, echo=None, *, key=None):
    if not isinstance(params, dict):
        return result(retcode=1400, message='params must be an object', echo=echo)
    if not isinstance(action, str) or action not in {'get_login_info', 'send_private_msg', 'send_group_msg'}:
        return result(retcode=1404, message='Unsupported action', echo=echo)
    required = 'query:read' if action == 'get_login_info' else 'messages:send'
    if required not in scopes:
        return result(retcode=1403, message='Missing scope', echo=echo)
    try:
        if action == 'get_login_info':
            if params:
                return result(retcode=1400, message='Unexpected params', echo=echo)
            status, body, _ = get_self(bot)
        else:
            target_key = 'user_id' if action == 'send_private_msg' else 'group_id'
            try:
                target = original_id(bot, 'user' if target_key == 'user_id' else 'group', params.get(target_key))
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', target):
                    raise ValueError('Invalid official target')
            except ValueError:
                return result(retcode=1400, message='Unknown or invalid virtual ID', echo=echo)
            if key is not None:
                from .conversations import check_conversation
                from rest_framework.exceptions import PermissionDenied
                try:
                    check_conversation(key, target_key == 'user_id', target)
                except PermissionDenied:
                    return result(retcode=1403, message='Conversation not allowed', echo=echo)
            text = params.get('message')
            auto_escape = params.get('auto_escape', False)
            if auto_escape in ('true', 'false'):
                auto_escape = auto_escape == 'true'
            if isinstance(text, list):
                if not all(isinstance(s, dict) and s.get('type') == 'text'
                           and isinstance(s.get('data'), dict) and isinstance(s['data'].get('text'), str) for s in text):
                    return result(retcode=1400, message='Only text segments are supported', echo=echo)
                text = ''.join(s['data']['text'] for s in text)
            elif isinstance(text, str) and auto_escape is False:
                if '[CQ:' in text:
                    return result(retcode=1400, message='Unsupported CQ segment', echo=echo)
                text = text.replace('&#91;', '[').replace('&#93;', ']').replace('&amp;', '&')
            if (set(params) - {target_key, 'message', 'auto_escape'}
                or not isinstance(text, str) or not text or type(auto_escape) is not bool):
                return result(retcode=1400, message='Only plain text is supported', echo=echo)
            payload = {'content': text, 'msg_type': 0}
            kind = 'users' if target_key == 'user_id' else 'groups'
            status, body, _ = send_message(bot, f'v2/{kind}/{target}/messages', json.dumps(payload).encode())
        if not 200 <= status < 300:
            return result(retcode=1500, message=f'Official HTTP {status}', echo=echo)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
        if action == 'get_login_info':
            if 'id' not in data:
                raise ValueError
            return result({'user_id': virtual_id(bot, 'user', data['id']), 'nickname': data.get('username', '')}, echo=echo)
        if 'id' not in data:
            return result(retcode=1502, message='Official accepted without message ID; do not blindly retry', echo=echo)
        return result({'message_id': virtual_id(bot, 'message', data['id'])}, echo=echo)
    except (OfficialCredentialError, ValueError, TypeError):
        return result(retcode=1502, message='Official outcome unknown; do not blindly retry', echo=echo)
