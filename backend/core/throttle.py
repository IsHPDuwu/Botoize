"""Small-window throttling using database-backed atomic counters."""
import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .models import ThrottleCounter


WINDOW_SECONDS = 60
LIMITS = {
    'login': 10,
    'management': 120,
    'bearer_key': 120,
    'bearer_user': 300,
    'bearer_bot': 600,
}


class RateLimitExceeded(APIException):
    status_code = 429
    default_detail = {'code': 'rate_limited', 'source': 'platform', 'detail': 'Too many requests'}
    default_code = 'rate_limited'


def _counter(key):
    key = hashlib.sha256(key.encode('utf-8')).hexdigest()
    now = timezone.now()
    cutoff = now - timedelta(seconds=WINDOW_SECONDS)
    row, created = ThrottleCounter.objects.get_or_create(
        key=key, defaults={'window_started_at': now, 'count': 1},
    )
    if created:
        return 1
    with transaction.atomic():
        reset = ThrottleCounter.objects.filter(key=key, window_started_at__lte=cutoff).update(
            window_started_at=now, count=1,
        )
        if reset:
            return 1
        updated = ThrottleCounter.objects.filter(
            key=key, window_started_at=row.window_started_at,
        ).update(count=F('count') + 1)
    if not updated:
        return _counter(key)
    row.refresh_from_db(fields=['count'])
    return row.count


def limit_response(retry_after=WINDOW_SECONDS):
    response = Response({'code': 'rate_limited', 'source': 'platform', 'detail': 'Too many requests'}, status=429)
    response['Retry-After'] = str(retry_after)
    response['Cache-Control'] = 'no-store'
    return response


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(exc, RateLimitExceeded):
        response['Retry-After'] = str(WINDOW_SECONDS)
        response['Cache-Control'] = 'no-store'
    return response


def throttle(*parts, limit):
    count = _counter('qq-proxy:throttle:' + ':'.join(str(part) for part in parts))
    return count <= limit


def request_ip(request):
    # Do not trust X-Forwarded-For; only the trusted proxy's REMOTE_ADDR is used.
    return request.META.get('REMOTE_ADDR', 'unknown')[:64]


def bearer_throttle(key):
    if key is None:
        return True
    key_allowed = throttle('key', key.pk, limit=LIMITS['bearer_key'])
    user_allowed = throttle('user', key.user_id, limit=LIMITS['bearer_user'])
    bot_allowed = throttle('bot', key.bot_id, limit=LIMITS['bearer_bot'])
    return key_allowed and user_allowed and bot_allowed