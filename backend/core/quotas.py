"""Atomic shared request quotas. Rejected requests consume no quota."""
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from .models import QuotaPolicy, QuotaUsage


class QuotaExceeded(APIException):
    status_code = 429
    default_code = 'quota_exceeded'

    def __init__(self, wait):
        self.wait = wait
        super().__init__({'code': 'quota_exceeded', 'source': 'platform', 'detail': 'Shared request quota exhausted'})


@transaction.atomic
def consume_quota(key):
    now = int(timezone.now().timestamp())
    policies = QuotaPolicy.objects.filter(
        Q(scope='platform', subject_id=0)
        | Q(scope='bot', subject_id=key.bot_id)
        | Q(scope='user', subject_id=key.user_id)
        | Q(scope='key', subject_id=key.pk),
        is_active=True,
    ).order_by('pk')
    for policy in policies:
        window = now // policy.window_seconds
        usage, _ = QuotaUsage.objects.get_or_create(policy=policy, window=window)
        if not QuotaUsage.objects.filter(pk=usage.pk, count__lt=policy.limit).update(count=F('count') + 1):
            raise QuotaExceeded((window + 1) * policy.window_seconds - now)