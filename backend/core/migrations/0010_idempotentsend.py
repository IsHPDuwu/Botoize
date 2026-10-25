from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0009_throttlecounter')]
    operations = [
        migrations.CreateModel(
            name='IdempotentSend',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key_digest', models.CharField(max_length=64)),
                ('request_digest', models.CharField(max_length=64)),
                ('state', models.CharField(default='processing', max_length=16)),
                ('encrypted_result', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.user')),
                ('bot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.bot')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'bot', 'key_digest'), name='unique_idempotent_send')]},
        ),
    ]