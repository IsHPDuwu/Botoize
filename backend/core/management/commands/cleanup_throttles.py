from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ThrottleCounter


class Command(BaseCommand):
    help = 'Remove expired database-backed throttle counters.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=5)
        deleted, _ = ThrottleCounter.objects.filter(window_started_at__lt=cutoff).delete()
        self.stdout.write(f'Removed {deleted} throttle counter rows.')