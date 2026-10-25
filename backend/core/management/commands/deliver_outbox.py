import json

from django.core.management.base import BaseCommand, CommandError

from core.delivery import deliver_batch


class Command(BaseCommand):
    help = 'Deliver one bounded batch of subscribed HTTP events; schedule repeatedly.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)

    def handle(self, *args, **options):
        try:
            result = deliver_batch(options['limit'])
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(json.dumps(result))