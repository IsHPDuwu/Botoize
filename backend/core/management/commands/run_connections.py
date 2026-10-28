"""Continuously supervise active Channels, independently of reconnect acknowledgements."""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections, OperationalError
from django.db.models import F
from django.utils import timezone

from core.models import Bot, ChannelConnectionRequest, GatewaySession, OneBotUpstreamSession
from core.onebot_upstream import configuration_digest

STARTUP_GRACE = 75
STOP_GRACE = 10


def worker_arguments(bot, *, intents, allowed_group):
    args = [sys.executable, str(Path(__file__).resolve().parents[3] / 'manage.py')]
    if bot.channel.interface_type.startswith('onebot_'):
        return args + ['run_onebot_upstream', '--bot', str(bot.pk)]
    saved = GatewaySession.objects.filter(bot=bot).first()
    args += ['run_gateway', '--bot', str(bot.pk), '--intents', str(saved.intents if saved and saved.intents else intents)]
    if allowed_group:
        args += ['--allowed-group', allowed_group]
    return args


class Supervisor:
    def __init__(self, *, intents, allowed_group, stderr):
        self.intents, self.allowed_group, self.stderr = intents, allowed_group, stderr
        self.children, self.failures, self.retry_at, self.probes = {}, {}, {}, {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='channel-http-check')

    @staticmethod
    def probe(bot, generation):
        from core.connection_control import probe_webhook
        close_old_connections()
        try:
            probe_webhook(bot, generation)
        finally:
            close_old_connections()

    def stop(self, child, now):
        if child.get('stopping') is None:
            child['process'].terminate()
            child['stopping'] = now
        elif now - child['stopping'] >= STOP_GRACE:
            child['process'].kill()

    def tick(self):
        close_old_connections()
        now = time.monotonic()
        for bot_id, child in list(self.children.items()):
            if child['process'].poll() is not None:
                del self.children[bot_id]
                failures = min(self.failures.get(bot_id, 0) + 1, 6)
                self.failures[bot_id] = failures
                self.retry_at[bot_id] = now + min(2 ** failures, 60)
                self.stderr.write(f'Channel worker {bot_id} exited; restart scheduled')

        # Webhook checks and stale/disabled requests do not select desired socket state.
        for row in ChannelConnectionRequest.objects.filter(generation__gt=F('processed_generation')).select_related('channel'):
            bot = Bot.objects.select_related('channel').filter(channel=row.channel, is_active=True).first()
            error = 'channel_disabled' if bot is None else (
                'configuration_changed' if row.configuration != configuration_digest(bot) else '')
            if error:
                ChannelConnectionRequest.objects.filter(pk=row.pk, generation=row.generation).update(
                    processed_generation=row.generation, processed_at=timezone.now(), error_code=error)
            elif bot.channel.interface_type == 'qq_official_webhook':
                if bot.pk not in self.probes or self.probes[bot.pk].done():
                    self.probes[bot.pk] = self.pool.submit(self.probe, bot, row.generation)

        # Restore active socket Channels after container restarts, config changes and
        # unexpected exits, including when their manual request was already consumed.
        desired = {bot.pk: bot for bot in Bot.objects.select_related('channel').filter(is_active=True,
            channel__interface_type__in=['qq_official_websocket', 'onebot_v11', 'onebot_v12'])}
        for bot_id, child in self.children.items():
            bot = desired.get(bot_id)
            if bot is None or configuration_digest(bot) != child['configuration']:
                self.stop(child, now)

        for bot_id, bot in desired.items():
            model = OneBotUpstreamSession if bot.channel.interface_type.startswith('onebot_') else GatewaySession
            lease_live = model.objects.filter(bot=bot, lease_token__isnull=False, lease_until__gt=timezone.now()).exists()
            child = self.children.get(bot_id)
            if child:
                if lease_live and child.get('stopping') is None:
                    if now - child['started_at'] >= STARTUP_GRACE:
                        self.failures.pop(bot_id, None)
                elif now - child['started_at'] >= STARTUP_GRACE:
                    # A hung process must not block recovery after its lease dies.
                    self.stop(child, now)
                continue
            if lease_live or now < self.retry_at.get(bot_id, 0):
                continue
            try:
                process = subprocess.Popen(worker_arguments(bot, intents=self.intents, allowed_group=self.allowed_group),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            except OSError:
                self.failures[bot_id] = min(self.failures.get(bot_id, 0) + 1, 6)
                self.retry_at[bot_id] = now + min(2 ** self.failures[bot_id], 60)
                self.stderr.write(f'Channel worker {bot_id} launch failed; retry scheduled')
                continue
            self.children[bot_id] = {'process': process, 'configuration': configuration_digest(bot), 'started_at': now}

    def close(self):
        for child in self.children.values():
            if child['process'].poll() is None:
                child['process'].terminate()
        for child in self.children.values():
            try:
                child['process'].wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                child['process'].kill()
        self.pool.shutdown(wait=True, cancel_futures=True)


class Command(BaseCommand):
    help = 'Continuously supervise enabled Gateway/OneBot Channels and consume manual reconnect requests'

    def add_arguments(self, parser):
        parser.add_argument('--intents', type=int, default=33554432)
        parser.add_argument('--allowed-group', help='Optional exact group OpenID restriction for launched official workers')
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        supervisor = Supervisor(intents=options['intents'], allowed_group=options['allowed_group'], stderr=self.stderr)
        try:
            while True:
                try:
                    supervisor.tick()
                except OperationalError:
                    close_old_connections()
                    self.stderr.write('Connection supervision database unavailable; retrying')
                if options['once']:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            supervisor.close()
