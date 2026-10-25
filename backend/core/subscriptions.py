"""Console-managed callback configuration. No network requests are made here."""
import secrets
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from .models import AuditLog, BotGrant, HttpSubscription


def _encrypt_callback_secret(secret):
    return Fernet(settings.BOT_ENCRYPTION_KEY.encode()).encrypt(secret.encode('utf-8')).decode()


def decrypt_callback_secret(subscription):
    return Fernet(settings.BOT_ENCRYPTION_KEY.encode()).decrypt(
        subscription.encrypted_callback_secret.encode(),
    ).decode('utf-8')


def validate_callback(url):
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('Invalid HTTPS callback URL')
    try:
        URLValidator(schemes=['https'])(url)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError('Invalid HTTPS callback URL')
        if not parsed.hostname or parsed.port not in (None, 443):
            raise ValueError('Only HTTPS port 443 is supported')
    except (ValidationError, ValueError):
        raise ValueError('Invalid HTTPS callback URL') from None
    return url


@transaction.atomic
def set_subscription(grant_id, url, actor='console', callback_secret=None, *, subscription_id=None, create=False):
    url = validate_callback(url)
    if callback_secret is not None and (
        not isinstance(callback_secret, str) or not 32 <= len(callback_secret) <= 256
    ):
        raise ValueError('callback_secret must contain 32–256 characters')
    grant = BotGrant.objects.select_for_update().select_related('user', 'bot').get(pk=grant_id)
    from .conversations import grant_current
    if not (grant_current(grant) and 'events:read' in grant.scopes):
        raise ValueError('Active events:read grant required')
    existing = (HttpSubscription.objects.get(grant=grant, pk=subscription_id) if subscription_id is not None
                else None if create else HttpSubscription.objects.filter(grant=grant).order_by('pk').first())
    if not create and subscription_id is None and HttpSubscription.objects.filter(grant=grant).count() > 1:
        raise ValueError('Specify subscription ID when editing multiple callbacks')
    encrypted = (
        _encrypt_callback_secret(callback_secret) if callback_secret is not None
        else existing.encrypted_callback_secret if existing
        else _encrypt_callback_secret(secrets.token_urlsafe(32))
    )
    subscription = existing or HttpSubscription(grant=grant)
    if existing:
        subscription.revision += 1
        from .models import EventOutbox
        EventOutbox.objects.filter(subscription=existing, state__in=['pending', 'processing']).update(
            state='cancelled', lease_token=None, lease_until=None, available_at=None)
    subscription.url = url
    subscription.grant_revision = grant.revision
    subscription.encrypted_callback_secret = encrypted
    subscription.is_active = True
    subscription.save()
    AuditLog.objects.create(actor=actor, action='subscription.set', target=str(subscription.pk))
    return subscription


@transaction.atomic
def disable_subscription(grant_id, actor='console', *, subscription_id=None):
    rows = HttpSubscription.objects.select_for_update().filter(grant_id=grant_id)
    if subscription_id is None and rows.count() > 1:
        raise ValueError('Specify subscription ID when disabling multiple callbacks')
    subscription = rows.get(pk=subscription_id) if subscription_id is not None else rows.get()
    subscription.is_active = False
    subscription.revision += 1
    subscription.save(update_fields=['is_active', 'revision', 'updated_at'])
    from .models import EventOutbox
    EventOutbox.objects.filter(subscription=subscription, state__in=['pending', 'processing']).update(
        state='cancelled', lease_token=None, lease_until=None, available_at=None)
    AuditLog.objects.create(actor=actor, action='subscription.disable', target=str(subscription.pk))


def subscription_is_current(subscription):
    from .conversations import grant_current
    grant = subscription.grant
    return (
        subscription.is_active and subscription.grant_revision == grant.revision
        and grant.is_active and grant.user.is_active and grant.bot.is_active
        and 'events:read' in grant.scopes
        and grant_current(grant)
    )
