import json
import re

from rest_framework.response import Response

from .official import OfficialCredentialError, get_self, send_message


def result(data=None, retcode=0, message='', echo=None):
    return Response({'status': 'ok' if retcode == 0 else 'failed', 'retcode': retcode,
                     'data': data, 'message': message, 'echo': echo})


def invoke(bot, scopes, action, params, echo=None):
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
            target = params.get(target_key)
            text = params.get('message')
            if (set(params) - {target_key, 'message', 'auto_escape', 'msg_id', 'msg_seq'}
                or not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', target)
                or not isinstance(text, str) or not text or '[CQ:' in text
                or ('auto_escape' in params and params['auto_escape'] is not True)):
                return result(retcode=1400, message='Only plain text and string official OpenID are supported', echo=echo)
            payload = {'content': text, 'msg_type': 0}
            if 'msg_id' in params:
                if not isinstance(params['msg_id'], str) or not 1 <= len(params['msg_id']) <= 200:
                    return result(retcode=1400, message='Invalid msg_id', echo=echo)
                payload['msg_id'] = params['msg_id']
            if 'msg_seq' in params:
                if type(params['msg_seq']) is not int or not 1 <= params['msg_seq'] <= 2147483647:
                    return result(retcode=1400, message='Invalid msg_seq', echo=echo)
                payload['msg_seq'] = params['msg_seq']
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
            return result({'user_id': str(data['id']), 'nickname': data.get('username', '')}, echo=echo)
        if 'id' not in data:
            return result(retcode=1502, message='Official accepted without message ID; do not blindly retry', echo=echo)
        return result({'message_id': str(data['id'])}, echo=echo)
    except (OfficialCredentialError, ValueError, TypeError):
        return result(retcode=1502, message='Official outcome unknown; do not blindly retry', echo=echo)