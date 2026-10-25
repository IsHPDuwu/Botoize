"""OneBot 11 message subset. IDs are platform-local virtual numbers."""
from datetime import datetime

from .onebot_ids import virtual_id


def cq_text(text):
    return text.replace('&', '&amp;').replace('[', '&#91;').replace(']', '&#93;')


def message_event(bot, payload, self_id):
    if not isinstance(payload, dict) or payload.get('op') != 0:
        return None
    event_type = payload.get('t')
    if event_type not in {'C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'}:
        return None
    data = payload.get('d')
    if not isinstance(data, dict) or data.get('attachments'):
        return None
    author = data.get('author')
    if not isinstance(author, dict):
        return None
    group = event_type == 'GROUP_AT_MESSAGE_CREATE'
    user = author.get('member_openid' if group else 'user_openid')
    text, message = data.get('content'), data.get('id')
    ids = [user, message] + ([data.get('group_openid')] if group else [])
    if not all(isinstance(value, str) and 1 <= len(value) <= 256 for value in ids):
        return None
    if not isinstance(text, str):
        return None
    try:
        timestamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            return None
        time = int(timestamp.timestamp())
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None
    uid = virtual_id(bot, 'user', user)
    event = {
        'time': time, 'self_id': self_id, 'post_type': 'message',
        'message_type': 'group' if group else 'private',
        'sub_type': 'normal' if group else 'other',
        'message_id': virtual_id(bot, 'message', message), 'user_id': uid,
        'message': [{'type': 'text', 'data': {'text': text}}],
        'raw_message': cq_text(text), 'font': 0,
        'sender': {'user_id': uid, 'nickname': '', 'sex': 'unknown', 'age': 0},
    }
    if group:
        event['group_id'] = virtual_id(bot, 'group', data['group_openid'])
    return event