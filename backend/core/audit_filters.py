"""Bounded, server-side audit filters, always applied after account isolation."""
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def filter_calls(rows, params):
    for key, field, maximum in [('search', None, 200), ('username', 'username', 150), ('path', 'path', 512)]:
        value = params.get(key, '').strip()
        if len(value) > maximum:
            raise ValidationError({key: 'Filter too long'})
        if value:
            if field:
                rows = rows.filter(**{field + '__icontains': value})
            else:
                rows = rows.filter(Q(request_id__icontains=value) | Q(path__icontains=value)
                                   | Q(bot_name__icontains=value) | Q(username__icontains=value)
                                   | Q(key_name__icontains=value))
    for key, field in [('bot', 'bot_id'), ('api_key', 'api_key_id')]:
        value = params.get(key, '')
        if value:
            if not value.isascii() or not value.isdigit() or not 0 < len(value) <= 18 or int(value) < 1:
                raise ValidationError({key: 'Positive integer required'})
            rows = rows.filter(**{field: int(value)})
    method = params.get('method', '')
    if method:
        if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'WS'}:
            raise ValidationError({'method': 'Unsupported method'})
        rows = rows.filter(method=method)
    status = params.get('status', '')
    if status:
        if status in {'2xx', '3xx', '4xx', '5xx'}:
            rows = rows.filter(status_code__gte=int(status[0]) * 100, status_code__lt=(int(status[0]) + 1) * 100)
        elif len(status) == 3 and status.isascii() and status.isdigit() and 100 <= int(status) <= 599:
            rows = rows.filter(status_code=int(status))
        else:
            raise ValidationError({'status': 'HTTP status or 2xx–5xx required'})
    replayed = params.get('replayed', '')
    if replayed:
        if replayed not in {'true', 'false'}:
            raise ValidationError({'replayed': 'Expected true or false'})
        rows = rows.filter(replayed=replayed == 'true')
    bounds = {}
    for key, lookup in [('from', 'created_at__gte'), ('to', 'created_at__lt')]:
        value = params.get(key, '')
        if value:
            try:
                parsed = parse_datetime(value) if len(value) <= 40 else None
            except ValueError:
                parsed = None
            if parsed is None or timezone.is_naive(parsed):
                raise ValidationError({key: 'Timezone-aware ISO datetime required'})
            bounds[key] = parsed
            rows = rows.filter(**{lookup: parsed})
    if len(bounds) == 2 and bounds['from'] >= bounds['to']:
        raise ValidationError('Start time must precede end time')
    return rows
