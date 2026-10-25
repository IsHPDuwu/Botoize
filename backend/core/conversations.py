"""Shared conversation policy for management, HTTP, WS and outbox delivery."""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Conversation, BotGrant

GROUP_EVENTS = ['GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE', 'GROUP_ADD_ROBOT', 'GROUP_DEL_ROBOT',
                'GROUP_MSG_RECEIVE', 'GROUP_MSG_REJECT', 'GROUP_MEMBER_ADD', 'GROUP_MEMBER_REMOVE', 'GROUP_JOIN_REQUEST']
DIRECT_EVENTS = ['FRIEND_ADD', 'FRIEND_DEL', 'C2C_MSG_RECEIVE', 'C2C_MSG_REJECT']


def conversation_data(row):
    return {'id': row.pk, 'name': row.name, 'isDirect': row.is_direct,
            'userid' if row.is_direct else 'groupid': row.target_id}


def policy_data(policy):
    return {'all_conversations': policy.all_conversations,
            'conversations': list(policy.conversations.order_by('pk').values_list('pk', flat=True))}


def selection(bot_id, data, default=None):
    all_models = data.get('all_conversations', default.all_conversations if default else True)
    ids = data.get('conversations', list(default.conversations.values_list('pk', flat=True)) if default else [])
    if type(all_models) is not bool or not isinstance(ids, list) or any(type(value) is not int for value in ids):
        raise ValidationError('Invalid conversation selection')
    models = Conversation.objects.filter(bot_id=bot_id, pk__in=ids)
    if models.count() != len(set(ids)):
        raise ValidationError('Conversation belongs to another Bot or does not exist')
    if all_models and ids:
        raise ValidationError('Select either all conversations or an explicit list')
    return all_models, sorted(set(ids))


def require_subset(all_models, ids, parent):
    if not parent.all_conversations and (all_models or not set(ids) <= set(parent.conversations.values_list('pk', flat=True))):
        raise PermissionDenied('Conversation selection exceeds your grant')


def configure_policy(policy, data, parent=None):
    all_models, ids = selection(policy.bot_id, data, default=policy)
    if parent:
        require_subset(all_models, ids, parent)
    policy.all_conversations = all_models
    policy.save(update_fields=['all_conversations'])
    policy.conversations.set(ids)


def grant_chain(grant):
    seen = set()
    while grant is not None:
        if grant.pk in seen or not grant.is_active or not grant.user.is_active or not grant.bot.is_active:
            raise PermissionDenied('Grant no longer valid')
        seen.add(grant.pk)
        yield grant
        if grant.parent_id is None:
            break
        parent = BotGrant.objects.select_related('user', 'bot').filter(pk=grant.parent_id).first()
        if parent is None or parent.revision != grant.parent_revision or parent.bot_id != grant.bot_id:
            raise PermissionDenied('Delegating grant no longer valid')
        if not set(grant.scopes) <= set(parent.scopes):
            raise PermissionDenied('Delegating scopes no longer valid')
        require_subset(grant.all_conversations, grant.conversations.values_list('pk', flat=True), parent)
        grant = parent


def grant_current(grant):
    try:
        list(grant_chain(grant))
        return True
    except PermissionDenied:
        return False


def active_grants(user):
    return [g for g in BotGrant.objects.filter(user=user, is_active=True, bot__is_active=True)
            .select_related('user', 'bot') if grant_current(g)]


def event_target(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('d'), dict):
        return None
    data = payload['d']
    kind = payload.get('t')
    if kind == 'C2C_MESSAGE_CREATE':
        author = data.get('author', {})
        target = author.get('user_openid') if isinstance(author, dict) else None
        direct = True
    elif kind in GROUP_EVENTS:
        target, direct = data.get('group_openid'), False
    elif kind in DIRECT_EVENTS:
        target, direct = data.get('openid'), True
    else:
        return None
    if not isinstance(target, str) or not 1 <= len(target) <= 256:
        return None
    return direct, target


def event_allowed(policy, payload):
    if policy.all_conversations:
        return True
    target = event_target(payload)
    return bool(target and policy.conversations.filter(
        bot_id=policy.bot_id, is_direct=target[0], target_id=target[1]).exists())


def filter_events(rows, policy, prefix='event__'):
    """Filter before pagination; never leak hidden rows or stall a cursor on them."""
    if policy.all_conversations:
        return rows
    models = policy.conversations.filter(bot_id=policy.bot_id)
    direct = list(models.filter(is_direct=True).values_list('target_id', flat=True))
    groups = list(models.filter(is_direct=False).values_list('target_id', flat=True))
    payload = prefix + 'payload__'
    return rows.filter(
        Q(**{payload + 't': 'C2C_MESSAGE_CREATE', payload + 'd__author__user_openid__in': direct})
        | Q(**{payload + 't__in': GROUP_EVENTS, payload + 'd__group_openid__in': groups})
        | Q(**{payload + 't__in': DIRECT_EVENTS, payload + 'd__openid__in': direct}))


def discover(bot, payload):
    target = event_target(payload)
    if target is None:
        return None
    return Conversation.objects.get_or_create(bot=bot, is_direct=target[0], target_id=target[1])[0]


def key_grant(key):
    grant = BotGrant.objects.select_related('user', 'bot').filter(
        user_id=key.user_id, bot_id=key.bot_id, revision=key.grant_revision, is_active=True).first()
    if grant is None or not grant_current(grant):
        raise PermissionDenied('Grant no longer valid')
    return grant


def check_conversation(key, is_direct, target_id):
    for policy in (*grant_chain(key_grant(key)), key):
        if not policy.all_conversations and not policy.conversations.filter(
            bot_id=key.bot_id, is_direct=is_direct, target_id=target_id,
        ).exists():
            raise PermissionDenied('Conversation not allowed')


def unrestricted(key):
    return key.all_conversations and all(g.all_conversations for g in grant_chain(key_grant(key)))
