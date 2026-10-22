from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'Owner'
        ADMIN = 'Admin'
    role = models.CharField(max_length=5, choices=Role.choices, default=Role.ADMIN)


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


class AuditLog(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)