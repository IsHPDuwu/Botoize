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
    grants = BotGrant.objects.select_for_update().filter(bot=current, is_active=True, user__is_active=True)
    EventOutbox.objects.bulk_create([
        EventOutbox(event=event, grant=grant, grant_revision=grant.revision)
        for grant in grants if 'events:read' in grant.scopes
    ])
    return event, True