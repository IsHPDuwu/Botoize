"""Explicit, audited replay of a terminal HTTP delivery."""
from django.db import transaction
from django.utils import timezone

from .models import AuditLog, EventOutbox, HttpSubscription, User
from .subscriptions import subscription_is_current
from .outbox import valid_snapshot


@transaction.atomic
def replay_delivery(delivery_id, actor):
    row = EventOutbox.objects.select_for_update().select_related(
        'grant__user', 'grant__bot', 'grant__httpsubscription', 'event',
    ).filter(pk=delivery_id).first()
    if row is None:
        raise LookupError
    if not actor.is_active or (actor.role != User.Role.OWNER and row.grant.user_id != actor.pk):
        raise LookupError
    subscription = HttpSubscription.objects.filter(grant_id=row.grant_id).first()
    if not (
        row.state in ('failed', 'delivered')
        and valid_snapshot(row)
        and row.grant.is_active
        and row.grant.user.is_active
        and row.grant.bot.is_active
        and row.grant_revision == row.grant.revision
        and row.event.bot_id == row.grant.bot_id
        and 'events:read' in row.grant.scopes
        and subscription is not None
        and subscription_is_current(subscription)
        and subscription.grant_revision == row.grant_revision
    ):
        raise ValueError('Delivery is not currently replayable')
    row.attempt_generation += 1
    row.attempts = 0
    row.state = 'pending'
    row.available_at = timezone.now()
    row.lease_token = None
    row.lease_until = None
    row.save(update_fields=[
        'attempt_generation', 'attempts', 'state', 'available_at', 'lease_token', 'lease_until',
    ])
    AuditLog.objects.create(actor=actor.username, action='delivery.replay', target=str(row.pk))
    return row
