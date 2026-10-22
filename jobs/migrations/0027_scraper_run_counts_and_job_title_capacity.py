from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0026_alter_job_salary_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="title",
            field=models.CharField(max_length=500),
        ),
        migrations.AddField(
            model_name="scraperun",
            name="jobs_found",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="scraperun",
            name="jobs_updated",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="scraperun",
            name="jobs_failed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="scraperun",
            name="status",
            field=models.CharField(
                choices=[
                    ("running", "Running"),
                    ("success", "Succeeded"),
                    ("failed", "Failed"),
                    ("blocked", "Blocked by Cloudflare"),
                ],
                default="running",
                max_length=10,
            ),
        ),
    ]
