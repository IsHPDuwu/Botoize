from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0007_deliveryattempt_subscription_secret')]

    operations = [
        migrations.AddField(
            model_name='eventoutbox',
            name='attempt_generation',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='deliveryattempt',
            name='generation',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RemoveConstraint(
            model_name='deliveryattempt',
            name='unique_delivery_attempt_number',
        ),
        migrations.AddConstraint(
            model_name='deliveryattempt',
            constraint=models.UniqueConstraint(
                fields=('outbox', 'generation', 'attempt_number'),
                name='unique_delivery_attempt_generation_number',
            ),
        ),
    ]