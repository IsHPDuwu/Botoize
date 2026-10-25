from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from core.subscriptions import disable_subscription, set_subscription


class Command(BaseCommand):
    help = 'Manage HTTPS callbacks per grant; does not start a delivery worker.'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        configure = sub.add_parser('set')
        configure.add_argument('grant_id', type=int)
        configure.add_argument('url')
        configure.add_argument('--subscription', type=int, help='Edit this callback ID')
        configure.add_argument('--new', action='store_true', help='Create an additional callback')
        disable = sub.add_parser('disable')
        disable.add_argument('grant_id', type=int)
        disable.add_argument('--subscription', type=int, help='Required when the grant has multiple callbacks')

    def handle(self, *args, **options):
        try:
            if options['action'] == 'set':
                if options.get('new') and options.get('subscription'):
                    raise ValueError('Use either --new or --subscription')
                subscription = set_subscription(options['grant_id'], options['url'],
                                                subscription_id=options.get('subscription'), create=options.get('new', False))
                self.stdout.write(f'Subscription {subscription.pk} configured; run the delivery worker to send events.')
            else:
                disable_subscription(options['grant_id'], subscription_id=options.get('subscription'))
                self.stdout.write('Subscription disabled.')
        except (ValueError, ObjectDoesNotExist) as error:
            raise CommandError(str(error)) from None
