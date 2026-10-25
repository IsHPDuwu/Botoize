from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0010_idempotentsend')]
    operations = [
        migrations.CreateModel(name='QuotaPolicy', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('scope', models.CharField(max_length=10, choices=[('platform', 'Platform'), ('bot', 'Bot'), ('user', 'User'), ('key', 'Key')])),
            ('subject_id', models.PositiveBigIntegerField(default=0)),
            ('window_seconds', models.PositiveIntegerField(default=86400)),
            ('limit', models.PositiveIntegerField()),
            ('is_active', models.BooleanField(default=True)),
        ], options={'constraints': [models.UniqueConstraint(fields=('scope', 'subject_id', 'window_seconds'), name='unique_quota_policy')]}),
        migrations.CreateModel(name='QuotaUsage', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('window', models.PositiveBigIntegerField()),
            ('count', models.PositiveBigIntegerField(default=0)),
            ('policy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.quotapolicy')),
        ], options={'constraints': [models.UniqueConstraint(fields=('policy', 'window'), name='unique_quota_window')]}),
    ]