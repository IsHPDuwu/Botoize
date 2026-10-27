"""One leased forward event connection per configured upstream Bot."""
import json
import uuid
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Bot, OneBotUpstreamSession
from .onebot_upstream import configuration_digest, identity, socket_connection
from .onebot_upstream_events import receive_event
from .upstreams import onebot_version


class LeaseLost(ValueError):
    pass


@transaction.atomic
def claim(bot_id):
    bot = Bot.objects.select_for_update(of=('self',)).select_related('channel').get(pk=bot_id)
    if not bot.is_active or not onebot_version(bot):
        raise LeaseLost('An active OneBot Channel is required')
    row, _ = OneBotUpstreamSession.objects.get_or_create(bot=bot)
    now, token = timezone.now(), uuid.uuid4()
    if not OneBotUpstreamSession.objects.filter(pk=row.pk).filter(
            Q(lease_until__isnull=True) | Q(lease_until__lte=now)).update(
                credential_digest=configuration_digest(bot), lease_token=token,
                lease_until=now + timedelta(seconds=60), connected=False, self_platform=''):
        raise LeaseLost('Another OneBot worker holds this Channel lease')
    return bot, token


@transaction.atomic
def renew(bot, token, *, connected=None, platform=None):
    current = Bot.objects.select_for_update(of=('self',)).select_related('channel').get(pk=bot.pk)
    if not current.is_active or configuration_digest(current) != configuration_digest(bot):
        raise LeaseLost('OneBot Channel disabled or configuration changed')
    changes = {'lease_until': timezone.now() + timedelta(seconds=60)}
    if connected is not None:
        changes['connected'] = connected
    if platform is not None:
        changes['self_platform'] = platform
    if not OneBotUpstreamSession.objects.filter(bot=bot, lease_token=token,
            lease_until__gt=timezone.now()).update(**changes):
        raise LeaseLost('OneBot worker lease lost')


def release(bot, token):
    OneBotUpstreamSession.objects.filter(bot=bot, lease_token=token).update(
        connected=False, lease_token=None, lease_until=None)


def event_url(bot):
    parts = urlsplit(bot.channel.base_url)
    if parts.scheme in {'ws', 'wss'}:
        return bot.channel.base_url
    path = parts.path.rstrip('/') + ('/event' if onebot_version(bot) == 11 else '/')
    return urlunsplit(('wss' if parts.scheme == 'https' else 'ws', parts.netloc, path, '', ''))


def consume(bot, token):
    own, _ = identity(bot)
    renew(bot, token, platform=own['platform'])
    with socket_connection(bot, event_url(bot)) as ws:
        renew(bot, token, connected=True)
        while True:
            renew(bot, token)
            try:
                raw = ws.recv(timeout=10)
            except TimeoutError:
                continue
            if not isinstance(raw, str):
                raise ValueError('Only JSON text events are supported')
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError
                # API responses on a universal connection are not events.
                if 'retcode' in value:
                    continue
                if onebot_version(bot) == 12 and value.get('type') != 'meta' and value.get('self') != own:
                    # Multi-Bot OneBot implementations may multiplex all their events.
                    continue
                if onebot_version(bot) == 11 and str(value.get('self_id')) != bot.app_id:
                    continue
                receive_event(bot, value, lease_token=token)
            except (ValueError, KeyError, TypeError, RecursionError):
                # Invalid events close this connection; no payload or credential is logged.
                raise ValueError('Invalid OneBot event received') from None
