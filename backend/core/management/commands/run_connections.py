"""Launch requested event connections outside ASGI; existing fenced workers consume requests themselves."""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import F
from django.utils import timezone

from core.models import Bot, ChannelConnectionRequest, GatewaySession, OneBotUpstreamSession
from core.onebot_upstream import configuration_digest


def worker_arguments(bot, *, intents, allowed_group):
    args = [sys.executable, str(Path(__file__).resolve().parents[3] / 'manage.py')]
    if bot.channel.interface_type.startswith('onebot_'):
        return args + ['run_onebot_upstream', '--bot', str(bot.pk)]
    saved = GatewaySession.objects.filter(bot=bot).first()
    args += ['run_gateway', '--bot', str(bot.pk), '--intents', str(saved.intents if saved and saved.intents else intents)]
    if allowed_group:
        args += ['--allowed-group', allowed_group]
    return args


class Command(BaseCommand):
    help = 'Process console Channel reconnect requests and supervise requested Gateway/OneBot workers'

    def add_arguments(self, parser):
        parser.add_argument('--intents', type=int, default=33554432)
        parser.add_argument('--allowed-group', help='Optional exact group OpenID restriction for launched official workers')
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        children, probes = {}, {}
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='channel-http-check')
        def probe(bot, generation):
            from core.connection_control import probe_webhook
            close_old_connections()
            try:
                probe_webhook(bot, generation)
            finally:
                close_old_connections()
        try:
            while True:
                close_old_connections()
                for bot_id, process in list(children.items()):
                    if process.poll() is not None:
                        del children[bot_id]
                pending = ChannelConnectionRequest.objects.filter(generation__gt=F('processed_generation'))
                for row in pending.select_related('channel'):
                    bot = Bot.objects.select_related('channel').filter(channel=row.channel, is_active=True).first()
                    if bot is None:
                        ChannelConnectionRequest.objects.filter(pk=row.pk, generation=row.generation).update(
                            processed_generation=row.generation, processed_at=timezone.now(), error_code='channel_disabled')
                        continue
                    if row.configuration != configuration_digest(bot):
                        ChannelConnectionRequest.objects.filter(pk=row.pk, generation=row.generation).update(
                            processed_generation=row.generation, processed_at=timezone.now(), error_code='configuration_changed')
                        continue
                    if bot.channel.interface_type == 'qq_official_webhook':
                        if bot.pk not in probes or probes[bot.pk].done():
                            probes[bot.pk] = pool.submit(probe, bot, row.generation)
                        continue
                    session_model = OneBotUpstreamSession if bot.channel.interface_type.startswith('onebot_') else GatewaySession
                    if bot.pk in children or session_model.objects.filter(bot=bot, lease_token__isnull=False, lease_until__gt=timezone.now()).exists():
                        continue
                    # Fencing in each command prevents two supervisors owning one Channel.
                    children[bot.pk] = subprocess.Popen(worker_arguments(bot, intents=options['intents'], allowed_group=options['allowed_group']),
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if options['once']:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            for process in children.values():
                if process.poll() is None:
                    process.terminate()
            for process in children.values():
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            pool.shutdown(wait=True, cancel_futures=True)
