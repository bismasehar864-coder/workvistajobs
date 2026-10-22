from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0033_alter_job_source"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScraperSchedule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "key",
                    models.CharField(
                        default="automatic",
                        max_length=50,
                        unique=True,
                    ),
                ),
                (
                    "last_completed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
