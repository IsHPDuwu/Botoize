from getpass import getpass
from django.core.management.base import BaseCommand, CommandError
from core.models import User
from core.services import owner_change


class Command(BaseCommand):
    help = 'Console-only Owner initialization, listing, grant and revocation'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['init', 'list', 'grant', 'revoke'])
        parser.add_argument('username', nargs='?')

    def handle(self, action, username=None, **options):
        if action == 'list':
            for name, active in User.objects.filter(role='Owner').values_list('username', 'is_active'):
                self.stdout.write(f'{name} active={active}')
            return
        if not username:
            raise CommandError('username is required')
        password = None
        if action == 'init':
            password = getpass('New Owner password: ')
            if len(password) < 12:
                raise CommandError('Password must contain at least 12 characters')
        try:
            owner_change(username, action, password)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write('Owner updated')