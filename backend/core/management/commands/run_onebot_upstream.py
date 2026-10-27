import random
import time

from django.core.management.base import BaseCommand, CommandError
from websockets.exceptions import WebSocketException

from core.models import Bot
from core.onebot_common import OneBotError
from core.onebot_upstream_worker import claim, renew, release, consume, LeaseLost


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
                except (OneBotError, OSError, TimeoutError, WebSocketException, ValueError):
                    renew(bot, token, connected=False)
                failures = min(failures + 1, 5)
                deadline = time.monotonic() + min(2 ** failures, 25) + random.random()
                self.stderr.write('OneBot upstream reconnect scheduled')
                while time.monotonic() < deadline:
                    renew(bot, token)
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            pass
        except LeaseLost:
            raise CommandError('OneBot Channel changed or worker lease lost') from None
        finally:
            release(bot, token)
