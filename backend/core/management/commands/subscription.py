from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from core.subscriptions import disable_subscription, set_subscription


class Command(BaseCommand):
    help = 'Configure one HTTPS event callback per grant; does not start delivery.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        configure = sub.add_parser('set')
        configure.add_argument('grant_id', type=int)
        configure.add_argument('url')
        disable = sub.add_parser('disable')
        disable.add_argument('grant_id', type=int)

    def handle(self, *args, **options):
        try:
            if options['action'] == 'set':
                subscription = set_subscription(options['grant_id'], options['url'])
                self.stdout.write(f'Subscription {subscription.pk} configured; delivery is not enabled yet.')
            else:
                disable_subscription(options['grant_id'])
                self.stdout.write('Subscription disabled.')
        except (ValueError, ObjectDoesNotExist) as error:
            raise CommandError(str(error)) from None