from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0008_delivery_replay_generation')]

    operations = [
        migrations.CreateModel(
            name='ThrottleCounter',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('window_started_at', models.DateTimeField(db_index=True)),
                ('count', models.PositiveIntegerField(default=0)),
            ],
        ),
    ]