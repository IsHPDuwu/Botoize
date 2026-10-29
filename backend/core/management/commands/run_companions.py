import time
from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections, OperationalError
from django.core.management.base import BaseCommand
from core.companions import flush_due, refresh_pairing, backfill_id_evidence
from core.models import Channel


class Command(BaseCommand):
    help = 'Flush durable primary reception fallbacks; periodically refresh companion group/identity matches'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        def refresh_all():
            close_old_connections()
            try:
                for channel in Channel.objects.exclude(companion=None).order_by('pk'):
                    try:
                        backfill_id_evidence(channel)
                        refresh_pairing(channel)
                    except Exception:
                        self.stderr.write('Companion refresh unavailable; primary reception remains enabled')
            finally:
                close_old_connections()

        refresh_at = 0
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='companion-discovery')
        pending = None
        probes = None
        try:
            while True:
                if probes is None or probes.done():
                    from core.identity_probes import process_pending
                    probes = pool.submit(process_pending)
                try:
                    flush_due(limit=1000)
                except OperationalError:
                    close_old_connections()
                    self.stderr.write('Companion queue temporarily unavailable; retrying')
                if time.monotonic() >= refresh_at and (pending is None or pending.done()):
                    # Slow/offline upstream discovery must not delay the two-second fallback queue.
                    pending = pool.submit(refresh_all)
                    refresh_at = time.monotonic() + 60
                if options['once']:
                    if pending:
                        pending.result()
                    if probes:
                        probes.result()
                    return
                time.sleep(0.5)
        except KeyboardInterrupt:
            return
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
