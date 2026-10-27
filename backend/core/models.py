import uuid

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


class Provider(models.Model):
    name = models.CharField(max_length=120, unique=True)


class Channel(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name='channels')
    name = models.CharField(max_length=120)
    base_url = models.URLField(max_length=2048, default='https://api.bot.qq.com')
    interface_type = models.CharField(max_length=40, default='qq_official_websocket')
    encrypted_event_secret = models.TextField(blank=True)
    companion = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='primary_channels')
    prefer_markdown = models.BooleanField(default=False)
    onebot_self_id = models.CharField(max_length=256, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'name'], name='unique_provider_channel_name')]


class ChannelConnectionRequest(models.Model):
    channel = models.OneToOneField(Channel, on_delete=models.CASCADE)
    generation = models.PositiveBigIntegerField(default=0)
    processed_generation = models.PositiveBigIntegerField(default=0)
    requested_at = models.DateTimeField(null=True)
    processed_at = models.DateTimeField(null=True)
    checked_at = models.DateTimeField(null=True)
    reachable = models.BooleanField(null=True)
    error_code = models.CharField(max_length=40, blank=True)
    configuration = models.CharField(max_length=64, blank=True)


def default_channel_id():
    # Historical migration 0014 references this callable. Keep its lookup compatible
    # with the schema at that point (before Channel.base_url existed).
    provider, _ = Provider.objects.get_or_create(name='默认服务提供商')
    existing = Channel.objects.filter(provider=provider, name='QQ 开放平台').values_list('pk', flat=True).first()
    if existing is not None:
        return existing
    return Channel.objects.get_or_create(provider=provider, name='QQ 开放平台')[0].pk


def new_bot_channel_id():
    from uuid import uuid4
    provider, _ = Provider.objects.get_or_create(name='默认服务提供商')
    return Channel.objects.create(provider=provider, name='Bot ' + uuid4().hex).pk


class Bot(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name='bots', default=new_bot_channel_id)
    name = models.CharField(max_length=120)
    app_id = models.CharField(max_length=256, unique=True)
    encrypted_secret = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['channel'], name='one_bot_per_channel')]


class Conversation(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name='conversations')
    name = models.CharField(max_length=120, blank=True)
    is_direct = models.BooleanField()
    target_id = models.CharField(max_length=256)
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bot', 'is_direct', 'target_id'], name='unique_bot_conversation')]


class BotGrant(models.Model):
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='delegated_grants')
    parent_revision = models.PositiveBigIntegerField(null=True, blank=True)
    all_conversations = models.BooleanField(default=True)
    conversations = models.ManyToManyField(Conversation, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'bot'], name='unique_user_bot')]


class GatewaySession(models.Model):
    """One single-shard Gateway consumer per Bot, fenced by a renewable lease."""
    connected = models.BooleanField(default=False)
    bot = models.OneToOneField(Bot, on_delete=models.CASCADE)
    lease_token = models.UUIDField(null=True, editable=False)
    lease_until = models.DateTimeField(null=True)
    credential_digest = models.CharField(max_length=64, blank=True)
    intents = models.PositiveBigIntegerField(default=0)
    session_id = models.CharField(max_length=200, blank=True)
    sequence = models.PositiveBigIntegerField(null=True)


class ApiKey(models.Model):
    all_conversations = models.BooleanField(default=True)
    conversations = models.ManyToManyField(Conversation, blank=True)
    token = models.TextField(blank=True)
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
    subscription = models.ForeignKey('HttpSubscription', null=True, blank=True, on_delete=models.PROTECT)
    subscription_revision = models.PositiveBigIntegerField(null=True)
    is_stream = models.BooleanField(default=True)
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
        constraints = [
            models.UniqueConstraint(fields=['event', 'grant'], condition=models.Q(is_stream=True), name='unique_event_stream_grant'),
            models.UniqueConstraint(fields=['event', 'subscription'], name='unique_event_subscription'),
        ]
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
    grant = models.ForeignKey(BotGrant, on_delete=models.CASCADE, related_name='subscriptions')
    revision = models.PositiveBigIntegerField(default=1)
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
    bot_name = models.CharField(max_length=120, blank=True)
    username = models.CharField(max_length=150, blank=True)
    key_name = models.CharField(max_length=120, blank=True)
    api_key = models.ForeignKey(ApiKey, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    bot = models.ForeignKey(Bot, on_delete=models.SET_NULL, null=True, blank=True)
    request_id = models.CharField(max_length=64, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=512)
    message_type = models.CharField(max_length=32, blank=True)
    replayed = models.BooleanField(null=True)
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


class QuotaPolicy(models.Model):
    scope = models.CharField(max_length=10, choices=[('platform', 'Platform'), ('bot', 'Bot'), ('user', 'User'), ('key', 'Key')])
    subject_id = models.PositiveBigIntegerField(default=0)
    window_seconds = models.PositiveIntegerField(default=86400)
    limit = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['scope', 'subject_id', 'window_seconds'], name='unique_quota_policy')]


class OneBotIdMapping(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16, choices=[('user', 'User'), ('group', 'Group'), ('message', 'Message')])
    original_id = models.CharField(max_length=256)
    virtual_id = models.PositiveBigIntegerField()
    real_id = models.CharField(max_length=256, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['bot', 'kind', 'original_id'], name='onebot_original_unique'),
            models.UniqueConstraint(fields=['bot', 'kind', 'virtual_id'], name='onebot_virtual_unique'),
            models.CheckConstraint(condition=models.Q(virtual_id__gte=1, virtual_id__lte=9007199254740991), name='onebot_safe_integer'),
        ]


class OneBotIdAlias(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    alias = models.CharField(max_length=256)
    original_id = models.CharField(max_length=256)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bot', 'kind', 'alias'], name='onebot_old_id_alias_unique')]


class OfficialMediaHandle(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64)
    file_type = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bot', 'digest'], name='official_media_handle_unique')]


class QuotaUsage(models.Model):
    policy = models.ForeignKey(QuotaPolicy, on_delete=models.CASCADE)
    window = models.PositiveBigIntegerField()
    count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['policy', 'window'], name='unique_quota_window')]


class OneBotMessage(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE)
    source_digest = models.CharField(max_length=64, blank=True)
    message_id = models.CharField(max_length=256)
    is_direct = models.BooleanField()
    target_id = models.CharField(max_length=256)
    sender_id = models.CharField(max_length=256, blank=True)
    segments = models.JSONField(default=list)
    sent_at = models.FloatField()
    incoming = models.BooleanField(default=False)
    reference = models.CharField(max_length=256, blank=True)
    reply_sequence = models.PositiveIntegerField(default=0)
    deleted = models.BooleanField(default=False)
    source_event = models.ForeignKey(Event, null=True, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    conversation_type = models.CharField(max_length=16, blank=True)
    guild_id = models.CharField(max_length=256, blank=True)
    attachment_bot = models.ForeignKey(Bot, null=True, on_delete=models.SET_NULL, related_name='+')
    attachment_digest = models.CharField(max_length=64, blank=True)
    primary_message_id = models.CharField(max_length=256, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bot', 'source_digest', 'message_id'], name='onebot_message_source_unique')]


class OneBotFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.ForeignKey(ApiKey, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    data = models.BinaryField(default=bytes)
    url = models.URLField(max_length=2048, blank=True)
    total_size = models.PositiveIntegerField(default=0)
    complete = models.BooleanField(default=False)
    sha256 = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    # Files received in events remain subject to the current conversation policy.
    is_direct = models.BooleanField(null=True)
    target_id = models.CharField(max_length=256, blank=True)
    ranges = models.JSONField(default=list)
    conversation_type = models.CharField(max_length=16, blank=True)
    upstream_file_id = models.CharField(max_length=512, blank=True)
    upstream_bot = models.ForeignKey(Bot, null=True, on_delete=models.SET_NULL, related_name='+')
    upstream_digest = models.CharField(max_length=64, blank=True)


class ChannelGroupMatch(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='group_matches')
    companion = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='+')
    primary_group = models.CharField(max_length=256)
    companion_group = models.CharField(max_length=256)
    name = models.CharField(max_length=120, blank=True)
    origin = models.CharField(max_length=16, default='manual')
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['channel', 'companion', 'primary_group'], name='companion_primary_group_unique'),
            models.UniqueConstraint(fields=['channel', 'companion', 'companion_group'], name='companion_remote_group_unique'),
        ]


class CompanionObservation(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    side = models.CharField(max_length=16)
    group_id = models.CharField(max_length=256)
    sender_id = models.CharField(max_length=256, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True, db_index=True)
    sent_at = models.FloatField()
    paired = models.BooleanField(default=False)
    output = models.ForeignKey(Event, null=True, on_delete=models.SET_NULL, related_name='+')
    due_at = models.DateTimeField(null=True, db_index=True)
    published = models.BooleanField(default=False)
    configuration = models.CharField(max_length=64)
    grant_snapshot = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['channel', 'event', 'side'], name='companion_observation_unique')]


class OneBotUpstreamSession(models.Model):
    bot = models.OneToOneField(Bot, on_delete=models.CASCADE)
    credential_digest = models.CharField(max_length=64, blank=True)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    connected = models.BooleanField(default=False)
    self_platform = models.CharField(max_length=64, blank=True)
    last_event_at = models.DateTimeField(null=True)


class OneBotPollCursor(models.Model):
    api_key = models.OneToOneField(ApiKey, on_delete=models.CASCADE)
    cursor = models.PositiveBigIntegerField(default=0)


class OneBotPeer(models.Model):
    api_key = models.ForeignKey(ApiKey, on_delete=models.CASCADE)
    version = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=16)
    destination_digest = models.CharField(max_length=64)
    cursor = models.PositiveBigIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['api_key', 'version', 'kind', 'destination_digest'], name='onebot_peer_unique')]
