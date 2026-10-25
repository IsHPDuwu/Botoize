from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import IdempotentSend


class Command(BaseCommand):
    help = 'Erase expired send response payloads while retaining deduplication tombstones.'

    def handle(self, *args, **options):
        count = IdempotentSend.objects.filter(expires_at__lte=timezone.now()).exclude(
            encrypted_result='',
        ).update(encrypted_result='')
        self.stdout.write(f'Erased {count} expired idempotency response payloads.')