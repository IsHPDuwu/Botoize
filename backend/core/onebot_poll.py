"""Per-key HTTP polling, independent of WS/webhook consumers."""
import time

from django.db import transaction

from .models import ApiKey, OneBotPollCursor
from .onebot_common import fields, integer
from .services import authorize


def latest_events(key, params):
    from .onebot import identity
    from .websocket import read_onebot_page, onebot_rows
    fields(params, {'limit', 'timeout'})
    limit = integer(params.get('limit', 0), 0, 2**63-1)
    timeout = integer(params.get('timeout', 0), 0, 30)
    self_id = identity(key.bot)[0]['user_id']
    deadline = time.monotonic() + timeout
    output = []
    while True:
        # Every wait iteration checks expiration, disable, grant revision and scopes.
        authorize(key.token, scope='events:read')
        from .companions import flush_due
        flush_due(channel_id=key.bot.channel_id)
        with transaction.atomic():
            ApiKey.objects.select_for_update().get(pk=key.pk)
            cursor, _ = OneBotPollCursor.objects.get_or_create(api_key=key)
            buffered = list(onebot_rows(key, cursor.cursor, flush=False).order_by('-pk').values_list('pk', flat=True)[:1000])
            through = buffered[0] if buffered else cursor.cursor
            if buffered:
                cursor.cursor = max(cursor.cursor, buffered[-1] - 1)
            while True:
                page = read_onebot_page(key.token, cursor.cursor, self_id, version=12, limit=min(limit or 1000, 50), through=through, flush=False)
                if not page:
                    break
                for row in page:
                    cursor.cursor = int(row['cursor'])
                    if row['payload'] is not None:
                        output.append(row['payload'])
                    if len(output) >= (limit or 1000):
                        break
                if len(output) >= (limit or 1000):
                    break
            cursor.save(update_fields=['cursor'])
        if output or time.monotonic() >= deadline:
            return output
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
