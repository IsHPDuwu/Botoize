"""Run one explicitly configured downstream OneBot transport (never QQ credentials)."""
import asyncio
import os
import time

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from core.models import ApiKey
from core.onebot_common import OneBotError
from core.onebot_files import destination
from core.onebot_peer import acquire_peer, release_peer, renew_peer
from core.onebot_reverse import reverse_destination, reverse_session, webhook_batch, post_webhook, quick_operations
from core.onebot_connect import connection_info, meta, status_data, probe_status
from core.services import authorize


class Command(BaseCommand):
    help = 'Run OneBot 11/12 HTTP webhook or reverse universal WS with a stored API key'

    def add_arguments(self, parser):
        parser.add_argument('--key-id', type=int, required=True)
        parser.add_argument('--version', type=int, choices=[11, 12], required=True)
        parser.add_argument('--transport', choices=['http-webhook', 'reverse-ws'], required=True)
        parser.add_argument('--url', required=True)
        parser.add_argument('--token-env', default='BOTOIZE_ONEBOT_REMOTE_TOKEN')
        parser.add_argument('--secret-env', default='BOTOIZE_ONEBOT_WEBHOOK_SECRET')
        parser.add_argument('--interval', type=int, default=3)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        version, kind, url = options['version'], options['transport'], options['url']
        if not 1 <= options['interval'] <= 30:
            raise CommandError('interval must be 1..30 seconds (within the worker lease)')
        key = ApiKey.objects.filter(pk=options['key_id']).first()
        if key is None or not key.token:
            raise CommandError('A stored API key is required')
        token = key.token
        remote_token, secret = os.environ.get(options['token_env'], ''), os.environ.get(options['secret_env'], '')
        if any(len(v) > 8192 or not v.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in v) for v in [remote_token, secret]):
            raise CommandError('Invalid remote token or signing secret')
        try:
            authorize(token, scope='events:read')
            target = reverse_destination(url) if kind == 'reverse-ws' else destination(url)
            if target.scheme != 'https':
                raise ValueError('Only public TLS destinations on port 443 are supported')
            peer = acquire_peer(token, version, kind, url)
        except (ValueError, OneBotError, APIException) as exc:
            raise CommandError('Peer configuration rejected: ' + type(exc).__name__) from None
        self.stdout.write(f'OneBot {version} {kind} worker started (key #{key.pk}); secrets and URL are not logged')
        try:
            status_pending = kind == 'http-webhook' and version == 12
            last_status, next_status = None, 0
            while True:
                try:
                    renew_peer(peer, token)
                    if status_pending:
                        self_id, _, _, _ = connection_info(token, version)
                        event = meta(version, self_id, 'status_update', status=status_data(version, self_id))
                        response = post_webhook(url, event, version, remote_token)
                        status_pending = False
                        last_status, next_status = event['status'], time.monotonic() + 30
                        quick_operations(token, event, response, version)
                    if kind == 'http-webhook' and version == 12 and time.monotonic() >= next_status:
                        current = probe_status(token, version, self_id)
                        if current != last_status:
                            event = meta(version, self_id, 'status_update', status=current)
                            response = post_webhook(url, event, version, remote_token)
                            last_status = current
                            quick_operations(token, event, response, version)
                        next_status = time.monotonic() + 30
                    if kind == 'reverse-ws':
                        asyncio.run(reverse_session(peer, token, url, version, remote_token))
                    else:
                        delivered, rejected = webhook_batch(peer, token, url, version, remote_token, secret)
                        if delivered or rejected:
                            self.stdout.write(f'delivered={delivered}, rejected_quick_actions={rejected}')
                except APIException:
                    raise CommandError('Key authorization or worker lease invalidated; stopped') from None
                except Exception as exc:
                    self.stderr.write(f'Transport failed ({type(exc).__name__}); cursor retained, retrying')
                    if options['once']:
                        raise CommandError('OneBot transport failed') from None
                if options['once']:
                    break
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('OneBot worker stopped')
        finally:
            release_peer(peer)
