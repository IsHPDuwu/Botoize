"""Recovery primitives; scanning is not delivery acknowledgement."""
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from datetime import timedelta
from uuid import uuid4

from .models import EventOutbox


def valid_snapshot(row):
    grant = row.grant
    return (
        grant.is_active and grant.user.is_active and grant.bot.is_active
        and row.grant_revision == grant.revision
        and row.event.bot_id == grant.bot_id
        and 'events:read' in grant.scopes
    )


def claim_outbox(limit=100, lease_seconds=60):
    """Claim with compare-and-swap; expired leases may be recovered."""
    if not 1 <= limit <= 1000 or not 1 <= lease_seconds <= 3600:
        raise ValueError('Invalid claim bounds')
    now = timezone.now()
    eligible = (
        Q(state='pending') & (Q(available_at__isnull=True) | Q(available_at__lte=now))
        | Q(state='processing', lease_until__lte=now)
    )
    ids = list(EventOutbox.objects.filter(eligible).order_by('pk').values_list('pk', flat=True)[:limit])
    claimed = []
    for pk in ids:
        token = uuid4()
        updated = EventOutbox.objects.filter(eligible, pk=pk).update(
            state='processing', lease_token=token,
            lease_until=now + timedelta(seconds=lease_seconds), attempts=F('attempts') + 1,
        )
        if updated and validate_lease(pk, token):
            claimed.append((pk, token))
    return claimed


def validate_lease(pk, token):
    """Recheck immediately before sending; this is not an atomic network fence."""
    row = EventOutbox.objects.select_related('grant__user', 'grant__bot', 'event').filter(
        pk=pk, state='processing', lease_token=token, lease_until__gt=timezone.now(),
    ).first()
    if row is None:
        return False
    if valid_snapshot(row):
        return True
    EventOutbox.objects.filter(pk=pk, state='processing', lease_token=token).update(
        state='cancelled', lease_token=None, lease_until=None,
    )
    return False


def finish_outbox(pk, token, success, max_attempts=5):
    """Reject stale acknowledgements; retry with capped exponential backoff."""
    if max_attempts < 1:
        raise ValueError('Invalid attempt limit')
    if not validate_lease(pk, token):
        return False
    row = EventOutbox.objects.get(pk=pk)
    now = timezone.now()
    state = 'delivered' if success else ('failed' if row.attempts >= max_attempts else 'pending')
    return bool(EventOutbox.objects.filter(
        pk=pk, state='processing', lease_token=token, lease_until__gt=now,
    ).update(
        state=state, lease_token=None, lease_until=None,
        available_at=now + timedelta(seconds=min(3600, 2 ** min(row.attempts, 12))) if state == 'pending' else None,
    ))


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
        if valid_snapshot(row):
            ready.append(row.pk)
        else:
            cancelled.append(row.pk)
    if cancelled:
        EventOutbox.objects.filter(pk__in=cancelled, state='pending').update(state='cancelled')
    return {'next_cursor': rows[-1].pk if rows else after, 'scanned': len(rows), 'cancelled': len(cancelled), 'ready': ready}