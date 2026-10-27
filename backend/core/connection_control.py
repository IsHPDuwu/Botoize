"""Durable, credential-free reconnect requests consumed by fenced event workers."""
from django.db.models import F
from django.utils import timezone

from .models import ChannelConnectionRequest


class ManualReconnect(Exception):
    pass


def check_reconnect(bot):
    from .onebot_upstream import configuration_digest
    row = ChannelConnectionRequest.objects.filter(channel_id=bot.channel_id,
        generation__gt=F('processed_generation'), configuration=configuration_digest(bot)).first()
    if row and ChannelConnectionRequest.objects.filter(pk=row.pk, generation=row.generation,
            processed_generation=row.processed_generation).update(processed_generation=row.generation,
                processed_at=timezone.now(), error_code=''):
        raise ManualReconnect('Manual upstream reconnect requested')


def probe_webhook(bot, generation):
    """Webhook has no socket to reconnect; check official identity instead."""
    from .onebot import identity
    from .models import Bot
    from .onebot_upstream import configuration_digest
    digest = configuration_digest(bot)
    reachable = False
    try:
        identity(bot)
        reachable = True
    except Exception:
        pass  # Never persist upstream bodies, URLs, tokens or exception text.
    current = Bot.objects.select_related('channel').filter(pk=bot.pk, is_active=True).first()
    if not current or configuration_digest(current) != digest:
        return
    ChannelConnectionRequest.objects.filter(channel_id=bot.channel_id, generation=generation).update(
        processed_generation=generation, processed_at=timezone.now(), checked_at=timezone.now(),
        reachable=reachable, error_code='' if reachable else 'identity_unavailable')
