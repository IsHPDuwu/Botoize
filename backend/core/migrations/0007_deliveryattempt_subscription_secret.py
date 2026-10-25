import secrets

import django.db.models.deletion
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import migrations, models


def populate_callback_secrets(apps, schema_editor):
    subscription_model = apps.get_model('core', 'HttpSubscription')
    cipher = Fernet(settings.BOT_ENCRYPTION_KEY.encode())
    for subscription in subscription_model.objects.filter(encrypted_callback_secret=''):
        subscription.encrypted_callback_secret = cipher.encrypt(secrets.token_urlsafe(32).encode()).decode()
        subscription.save(update_fields=['encrypted_callback_secret'])


class Migration(migrations.Migration):
    dependencies = [('core', '0006_invitation')]

    operations = [
        migrations.AddField(
            model_name='httpsubscription',
            name='encrypted_callback_secret',
            field=models.TextField(default=''),
        ),
        migrations.RunPython(populate_callback_secrets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='httpsubscription',
            name='encrypted_callback_secret',
            field=models.TextField(),
        ),
        migrations.CreateModel(
            name='DeliveryAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attempt_number', models.PositiveIntegerField()),
                ('state', models.CharField(choices=[('processing', 'Processing'), ('delivered', 'Delivered'), ('retry', 'Retry'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], default='processing', max_length=12)),
                ('http_status', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('error_code', models.CharField(blank=True, max_length=40)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('outbox', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='delivery_attempts', to='core.eventoutbox')),
            ],
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.UniqueConstraint(fields=('outbox', 'attempt_number'), name='unique_delivery_attempt_number'),
        ),
        migrations.AddIndex(
            model_name='deliveryattempt',
            index=models.Index(fields=['outbox', 'id'], name='delivery_attempt_scan'),
        ),
    ]