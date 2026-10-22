import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0008_job_job_type_alter_job_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='first_seen_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
