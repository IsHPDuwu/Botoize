"""Owner-created, one-time Admin invitations."""
import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import AuditLog, Invitation, User


def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@transaction.atomic
def create_invitation(actor, lifetime_hours=72):
    if actor.role != User.Role.OWNER or not actor.is_active:
        raise PermissionError('Owner required')
    if type(lifetime_hours) is not int or not 1 <= lifetime_hours <= 720:
        raise ValueError('Invitation lifetime must be between 1 and 720 hours')
    token = 'qqi_' + secrets.token_urlsafe(40)
    invitation = Invitation.objects.create(
        token_digest=_digest(token),
        created_by=actor,
        expires_at=timezone.now() + timedelta(hours=lifetime_hours),
    )
    AuditLog.objects.create(actor=actor.username, action='invitation.create', target=str(invitation.pk))
    return invitation, token


@transaction.atomic
def accept_invitation(token, username, password, email=''):
    if not isinstance(token, str) or len(token) > 256:
        raise ValueError('Invalid invitation')
    if not isinstance(username, str) or not username or len(username) > 150:
        raise ValueError('Invalid username')
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError('Password must contain at least 12 characters')
    invitation = Invitation.objects.select_for_update().select_related('created_by').filter(
        token_digest=_digest(token), used_at__isnull=True, expires_at__gt=timezone.now(),
    ).first()
    if invitation is None:
        raise ValueError('Invitation is invalid or expired')
    if User.objects.filter(username=username).exists():
        raise ValueError('Username already exists')
    user = User.objects.create_user(username=username, password=password, email=email or '', role=User.Role.ADMIN)
    invitation.used_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=['used_at', 'accepted_by'])
    AuditLog.objects.create(actor=username, action='invitation.accept', target=str(invitation.pk))
    return user