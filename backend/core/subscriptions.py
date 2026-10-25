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
def set_subscription(grant_id, url, actor='console'):
    url = validate_callback(url)
    grant = BotGrant.objects.select_for_update().select_related('user', 'bot').get(pk=grant_id)
    if not (grant.is_active and grant.user.is_active and grant.bot.is_active and 'events:read' in grant.scopes):
        raise ValueError('Active events:read grant required')
    subscription, _ = HttpSubscription.objects.update_or_create(
        grant=grant,
        defaults={
            'url': url,
            'grant_revision': grant.revision,
            'encrypted_callback_secret': _encrypt_callback_secret(secrets.token_urlsafe(32)),
            'is_active': True,
        },
    )
    AuditLog.objects.create(actor=actor, action='subscription.set', target=str(subscription.pk))
    return subscription


@transaction.atomic
def disable_subscription(grant_id, actor='console'):
    subscription = HttpSubscription.objects.select_for_update().get(grant_id=grant_id)
    subscription.is_active = False
    subscription.save(update_fields=['is_active', 'updated_at'])
    AuditLog.objects.create(actor=actor, action='subscription.disable', target=str(subscription.pk))


def subscription_is_current(subscription):
    grant = subscription.grant
    return (
        subscription.is_active and subscription.grant_revision == grant.revision
        and grant.is_active and grant.user.is_active and grant.bot.is_active
        and 'events:read' in grant.scopes
    )