import json

from django.core.management.base import BaseCommand, CommandError

from core.outbox import scan_outbox


class Command(BaseCommand):
    help = 'Scan pending Outbox and cancel invalid grant snapshots; does not deliver events.'

    def add_arguments(self, parser):
        parser.add_argument('--after', type=int, default=0)
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        try:
            result = scan_outbox(options['after'], options['limit'])
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result))