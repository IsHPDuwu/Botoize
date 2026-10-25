from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0011_quotapolicy_quotausage')]

    operations = [migrations.CreateModel(
        name='GatewaySession',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('lease_token', models.UUIDField(editable=False, null=True)),
            ('lease_until', models.DateTimeField(null=True)),
            ('credential_digest', models.CharField(blank=True, max_length=64)),
            ('intents', models.PositiveBigIntegerField(default=0)),
            ('session_id', models.CharField(blank=True, max_length=200)),
            ('sequence', models.PositiveBigIntegerField(null=True)),
            ('bot', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='core.bot')),
        ],
    )]