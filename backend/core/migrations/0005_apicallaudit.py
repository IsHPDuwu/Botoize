from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0004_httpsubscription')]

    operations = [
        migrations.CreateModel(
            name='ApiCallAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_id', models.CharField(db_index=True, max_length=64)),
                ('method', models.CharField(max_length=10)),
                ('path', models.CharField(max_length=512)),
                ('status_code', models.PositiveSmallIntegerField()),
                ('duration_ms', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('api_key', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.apikey')),
                ('bot', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.bot')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.user')),
            ],
        ),
    ]