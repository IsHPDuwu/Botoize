import random
import time

from django.core.management.base import BaseCommand, CommandError
from websockets.exceptions import WebSocketException

from core.models import Bot, OneBotUpstreamSession
from core.onebot_common import OneBotError
from core.onebot_upstream_worker import claim, renew, release, consume, LeaseLost
from core.connection_control import ManualReconnect


class Command(BaseCommand):
    help = 'Receive OneBot 11/12 upstream events through a fenced forward WebSocket'

    def add_arguments(self, parser):
        parser.add_argument('--bot', type=int, required=True)

    def handle(self, *args, **options):
        try:
            bot, token = claim(options['bot'])
        except (Bot.DoesNotExist, LeaseLost):
            raise CommandError('Cannot claim this active OneBot Channel') from None
        failures = 0
        try:
            while True:
                try:
                    consume(bot, token)
                except LeaseLost:
                    raise
                except ManualReconnect:
                    OneBotUpstreamSession.objects.filter(bot=bot, lease_token=token).update(connected=False)
                    failures = 0
                    continue
                except (OneBotError, OSError, TimeoutError, WebSocketException, ValueError):
                    try:
                        renew(bot, token, connected=False)
                    except ManualReconnect:
                        failures = 0
                        continue
                failures = min(failures + 1, 5)
                deadline = time.monotonic() + min(2 ** failures, 25) + random.random()
                self.stderr.write('OneBot upstream reconnect scheduled')
                while time.monotonic() < deadline:
                    try:
                        renew(bot, token)
                    except ManualReconnect:
                        failures = 0
                        break
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            pass
        except LeaseLost:
            raise CommandError('OneBot Channel changed or worker lease lost') from None
        finally:
            release(bot, token)
