import hashlib
import secrets
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from .models import ApiKey, AuditLog, Bot, BotGrant, OwnerLock, User

from .official_routes import ROUTES

SCOPES = frozenset(['events:read', 'messages:send', 'messages:delete', 'media:upload', 'query:read',
                    'friends:read', 'friends:write', 'friend-requests:write']) | frozenset(scope for _, _, scope in ROUTES)


def validate_scopes(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or x not in SCOPES for x in value):
        raise ValidationError({'scopes': 'Unknown scope or invalid list'})
    return sorted(set(value))


def encrypt_secret(value):
    return Fernet(settings.BOT_ENCRYPTION_KEY.encode()).encrypt(value.encode()).decode()


def decrypt_secret(bot):
    return Fernet(settings.BOT_ENCRYPTION_KEY.encode()).decrypt(bot.encrypted_secret.encode()).decode()


@transaction.atomic
def owner_change(username, action, password=None):
    OwnerLock.objects.get_or_create(pk=1)
    OwnerLock.objects.filter(pk=1).update(revision=F('revision') + 1)
    list(OwnerLock.objects.select_for_update().filter(pk=1))
    user = User.objects.filter(username=username).first()
    if action == 'init':
        if User.objects.filter(role='Owner', is_active=True).exists():
            raise ValueError('An active Owner already exists')
        if user is not None or not password:
            raise ValueError('Use a new username and supply a password')
        user = User.objects.create_user(username=username, password=password, role='Owner')
    elif user is None:
        raise ValueError('Unknown user')
    elif action == 'grant':
        if not user.is_active:
            raise ValueError('Cannot promote inactive user')
        user.role = 'Owner'
        user.save(update_fields=['role'])
    elif action == 'revoke':
        if user.role == 'Owner' and user.is_active and User.objects.filter(role='Owner', is_active=True).count() <= 1:
            raise ValueError('Cannot revoke the last active Owner')
        user.role = 'Admin'
        user.save(update_fields=['role'])
    else:
        raise ValueError('Unknown action')
    AuditLog.objects.create(actor='console', action='owner.' + action, target=username)


@transaction.atomic
def issue_key(user, bot, name, scopes, expires_at=None, **policy):
    from .conversations import grant_current, selection, require_subset
    grant = BotGrant.objects.select_for_update().filter(user=user, bot=bot, is_active=True).first()
    if not user.is_active or not bot.is_active or not grant or not grant_current(grant) or not set(scopes) <= set(grant.scopes):
        raise PermissionDenied('No matching BotGrant/scopes')
    all_models, ids = selection(bot.pk, policy, default=grant)
    require_subset(all_models, ids, grant)
    token = 'qqp_' + secrets.token_urlsafe(48)
    key = ApiKey.objects.create(user=user, bot=bot, name=name, prefix=token[:12], digest=hashlib.sha256(token.encode()).hexdigest(), scopes=scopes, grant_revision=grant.revision, expires_at=expires_at)
    key.token = token
    key.all_conversations = all_models
    key.save(update_fields=['token', 'all_conversations'])
    key.conversations.set(ids)
    AuditLog.objects.create(actor=user.username, action='key.create', target=str(key.pk))
    return key, token


@transaction.atomic
def rotate_key(user, key_id, name=None, scopes=None, **values):
    from .conversations import policy_data
    old_key = ApiKey.objects.select_for_update().select_related('bot').filter(
        pk=key_id, user=user, revoked_at__isnull=True,
    ).first()
    if old_key is None:
        raise ApiKey.DoesNotExist
    if name is None:
        name = old_key.name
    if scopes is None:
        scopes = old_key.scopes
    policy = policy_data(old_key)
    policy.update({k: v for k, v in values.items() if k in ('all_conversations', 'conversations')})
    new_key, token = issue_key(user, old_key.bot, name, scopes, values.get('expires_at', old_key.expires_at), **policy)
    old_key.revoked_at = timezone.now()
    old_key.save(update_fields=['revoked_at'])
    AuditLog.objects.create(actor=user.username, action='key.rotate', target=str(old_key.pk))
    return new_key, token, old_key


@transaction.atomic
def update_bot(bot_id, actor, *, name=None, app_id=None, secret=None, is_active=None):
    if actor.role != User.Role.OWNER or not actor.is_active:
        raise PermissionDenied('Owner required')
    bot = Bot.objects.select_for_update().filter(pk=bot_id).first()
    if bot is None:
        raise Bot.DoesNotExist
    changed = []
    if name is not None and name != bot.name:
        bot.name = name
        changed.append('name')
    if app_id is not None and app_id != bot.app_id:
        if Bot.objects.exclude(pk=bot.pk).filter(app_id=app_id).exists():
            raise ValueError('app_id already exists')
        bot.app_id = app_id
        changed.append('app_id')
    if secret is not None:
        bot.encrypted_secret = encrypt_secret(secret)
        changed.append('encrypted_secret')
    if is_active is not None and is_active != bot.is_active:
        bot.is_active = is_active
        changed.append('is_active')
    if not changed:
        return bot, []
    bot.save(update_fields=changed)
    grants = list(BotGrant.objects.select_for_update().filter(bot=bot))
    affected_grants = []
    for grant in grants:
        if 'encrypted_secret' in changed or 'app_id' in changed or 'is_active' in changed:
            grant.revision += 1
            grant.save(update_fields=['revision'])
        affected_grants.append(grant.pk)
    if 'encrypted_secret' in changed or 'app_id' in changed:
        ApiKey.objects.filter(bot=bot, revoked_at__isnull=True).update(revoked_at=timezone.now())
    AuditLog.objects.create(actor=actor.username, action='bot.update', target=str(bot.pk))
    return bot, affected_grants


def authorize(token, bot_id=None, scope=None):
    key = ApiKey.objects.select_related('user', 'bot').filter(digest=hashlib.sha256(token.encode()).hexdigest()).first()
    if not key or key.revoked_at or not key.user.is_active or not key.bot.is_active or (key.expires_at and key.expires_at <= timezone.now()):
        raise AuthenticationFailed('Invalid or expired key')
    grant = BotGrant.objects.filter(user=key.user, bot=key.bot, is_active=True, revision=key.grant_revision).first()
    if not grant:
        raise PermissionDenied('Grant no longer valid')
    from .conversations import grant_current
    if not grant_current(grant):
        raise PermissionDenied('Grant no longer valid')
    if bot_id is not None and str(key.bot_id) != str(bot_id):
        raise PermissionDenied('Bot mismatch')
    scopes = set(key.scopes) & set(grant.scopes)
    if scope and scope not in scopes:
        raise PermissionDenied('Missing scope')
    return key, sorted(scopes)
