"""Recovery primitives; scanning is not delivery acknowledgement."""
from django.db import transaction

from .models import EventOutbox


@transaction.atomic
def scan_outbox(after=0, limit=100):
    if not isinstance(after, int) or after < 0 or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError('Invalid scan bounds')
    rows = list(EventOutbox.objects.select_for_update().filter(
        state='pending', pk__gt=after,
    ).select_related('grant__user', 'grant__bot', 'event').order_by('pk')[:limit])
    cancelled = []
    ready = []
    for row in rows:
        grant = row.grant
        valid = (
            grant.is_active and grant.user.is_active and grant.bot.is_active
            and row.grant_revision == grant.revision
            and row.event.bot_id == grant.bot_id
            and 'events:read' in grant.scopes
        )
        if valid:
            ready.append(row.pk)
        else:
            cancelled.append(row.pk)
    if cancelled:
        EventOutbox.objects.filter(pk__in=cancelled, state='pending').update(state='cancelled')
    return {'next_cursor': rows[-1].pk if rows else after, 'scanned': len(rows), 'cancelled': len(cancelled), 'ready': ready}