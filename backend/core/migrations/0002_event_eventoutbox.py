import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='Event',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=200)),
                ('event_type', models.CharField(max_length=100)),
                ('payload', models.JSONField()),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('bot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.bot')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('bot', 'event_id'), name='unique_bot_event')]},
        ),
        migrations.CreateModel(
            name='EventOutbox',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('grant_revision', models.PositiveBigIntegerField()),
                ('state', models.CharField(default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.event')),
                ('grant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.botgrant')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('event', 'grant'), name='unique_event_grant')],
                'indexes': [models.Index(fields=['state', 'id'], name='outbox_scan')],
            },
        ),
    ]