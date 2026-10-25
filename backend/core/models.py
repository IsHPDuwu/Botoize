from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'Owner'
        ADMIN = 'Admin'
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.ADMIN)


class Invitation(models.Model):
    token_digest = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_invitations')
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='accepted_invitation')
    created_at = models.DateTimeField(auto_now_add=True)


class OwnerLock(models.Model):
    """Singleton serializes all supported console role mutations."""
    revision = models.PositiveBigIntegerField(default=0)


class Bot(models.Model):
    name = models.CharField(max_length=120)
    app_id = models.CharField(max_length=100, unique=True)
    encrypted_secret = models.TextField()
    is_active = models.BooleanField(default=True)


class BotGrant(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'bot'], name='unique_user_bot')]


class ApiKey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=16)
    digest = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    grant_revision = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class Event(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    event_id = models.CharField(max_length=200)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bot', 'event_id'], name='unique_bot_event')]


class EventOutbox(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    grant = models.ForeignKey(BotGrant, on_delete=models.CASCADE)
    grant_revision = models.PositiveBigIntegerField()
    state = models.CharField(max_length=20, default='pending')
    lease_token = models.UUIDField(null=True, editable=False)
    lease_until = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    attempt_generation = models.PositiveIntegerField(default=1)
    available_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'grant'], name='unique_event_grant')]
        indexes = [models.Index(fields=['state', 'id'], name='outbox_scan')]


class DeliveryAttempt(models.Model):
    class State(models.TextChoices):
        PROCESSING = 'processing'
        DELIVERED = 'delivered'
        RETRY = 'retry'
        FAILED = 'failed'
        CANCELLED = 'cancelled'

    outbox = models.ForeignKey(EventOutbox, on_delete=models.CASCADE, related_name='delivery_attempts')
    generation = models.PositiveIntegerField(default=1)
    attempt_number = models.PositiveIntegerField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.PROCESSING)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['outbox', 'generation', 'attempt_number'], name='unique_delivery_attempt_generation_number')]
        indexes = [models.Index(fields=['outbox', 'id'], name='delivery_attempt_scan')]


class HttpSubscription(models.Model):
    grant = models.OneToOneField(BotGrant, on_delete=models.CASCADE)
    grant_revision = models.PositiveBigIntegerField()
    url = models.URLField(max_length=2048)
    encrypted_callback_secret = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditLog(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


class ApiCallAudit(models.Model):
    api_key = models.ForeignKey(ApiKey, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    bot = models.ForeignKey(Bot, on_delete=models.SET_NULL, null=True, blank=True)
    request_id = models.CharField(max_length=64, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=512)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class ThrottleCounter(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_started_at = models.DateTimeField(db_index=True)
    count = models.PositiveIntegerField(default=0)


class IdempotentSend(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    key_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=16, default='processing')
    encrypted_result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user', 'bot', 'key_digest'], name='unique_idempotent_send',
        )]