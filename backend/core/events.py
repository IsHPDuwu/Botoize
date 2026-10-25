"""Durable ingestion. Only verified upstream envelopes may call this service."""
from django.db import transaction

from .models import Bot, BotGrant, Event, EventOutbox


@transaction.atomic
def ingest_event(bot, payload):
    if not isinstance(payload, dict) or payload.get('op') != 0:
        raise ValueError('Dispatch envelope required')
    event_id, event_type = payload.get('id'), payload.get('t')
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
        raise ValueError('Stable upstream event ID required')
    if not isinstance(event_type, str) or not 1 <= len(event_type) <= 100:
        raise ValueError('Event type required')
    # Serialize repeated first inserts and grant snapshot creation for this Bot.
    current = Bot.objects.select_for_update().get(pk=bot.pk)
    if not current.is_active:
        raise ValueError('Inactive Bot')
    event, created = Event.objects.get_or_create(
        bot=current, event_id=event_id,
        defaults={'event_type': event_type, 'payload': payload},
    )
    if not created:
        return event, False
    from .conversations import discover, event_allowed, grant_current
    discover(current, payload)
    from .onebot_ids import virtual_id
    data = payload.get('d')
    if isinstance(data, dict) and event_type in {'C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'}:
        author = data.get('author')
        if isinstance(author, dict):
            user = author.get('user_openid') if event_type == 'C2C_MESSAGE_CREATE' else author.get('member_openid')
            if isinstance(user, str) and 1 <= len(user) <= 256:
                virtual_id(current, 'user', user)
        group = data.get('group_openid')
        if event_type == 'GROUP_AT_MESSAGE_CREATE' and isinstance(group, str) and 1 <= len(group) <= 256:
            virtual_id(current, 'group', group)
        message = data.get('id')
        if isinstance(message, str) and 1 <= len(message) <= 256:
            virtual_id(current, 'message', message)
    grants = BotGrant.objects.select_for_update().filter(bot=current, is_active=True, user__is_active=True)
    from .subscriptions import subscription_is_current
    rows = []
    for grant in grants:
        if not ('events:read' in grant.scopes and grant_current(grant) and event_allowed(grant, payload)):
            continue
        subscriptions = [sub for sub in grant.subscriptions.order_by('pk') if subscription_is_current(sub)]
        for index, sub in enumerate(subscriptions or [None]):
            rows.append(EventOutbox(event=event, grant=grant, grant_revision=grant.revision,
                                    is_stream=index == 0, subscription=sub,
                                    subscription_revision=sub.revision if sub else None))
    EventOutbox.objects.bulk_create(rows)
    return event, True
