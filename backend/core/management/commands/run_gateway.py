import random
import time

from django.core.management.base import BaseCommand, CommandError
from websockets.exceptions import ConnectionClosed, WebSocketException

from core.gateway import (FATAL_CLOSE_CODES, GatewayError, LeaseLost, Reconnect,
                          claim, clear_session, consume_connection, release, renew)
from core.models import Bot
from core.official import OfficialCredentialError


class Command(BaseCommand):
    help = 'Run one fenced official QQ Gateway connection ([0,1]) for a Bot'

    def add_arguments(self, parser):
        parser.add_argument('--bot', type=int, required=True)
        parser.add_argument('--intents', type=int, required=True)

    def handle(self, *args, **options):
        try:
            bot, _, token = claim(options['bot'], options['intents'])
        except (Bot.DoesNotExist, GatewayError) as error:
            raise CommandError(str(error)) from None
        failures = 0
        try:
            while True:
                try:
                    consume_connection(bot, token)
                except LeaseLost:
                    raise
                except ConnectionClosed as error:
                    code = error.rcvd.code if error.rcvd is not None else None
                    if code in FATAL_CLOSE_CODES:
                        raise GatewayError(f'Official Gateway closed with fatal code {code}') from None
                    if code not in {4009, None, 1001, 1006, 1011, 1012, 1013}:
                        clear_session(bot, token)
                except (Reconnect, OfficialCredentialError, OSError, TimeoutError, WebSocketException):
                    pass
                # Backoff stays below the lease and periodically revalidates Bot
                # credentials. No payloads, tokens or exception bodies are logged.
                failures = min(failures + 1, 5)
                delay = min(2 ** failures, 25) + random.uniform(0, 1)
                self.stderr.write('Gateway reconnect scheduled')
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    renew(bot, token)
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            pass
        except GatewayError as error:
            raise CommandError(str(error)) from None
        finally:
            release(bot, token)