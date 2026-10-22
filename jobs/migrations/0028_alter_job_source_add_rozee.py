from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0027_scraper_run_counts_and_job_title_capacity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="source",
            field=models.CharField(
                choices=[
                    ("mustakbil", "Mustakbil"),
                    ("indeed", "Indeed"),
                    ("python_org", "Python.org"),
                    ("ppsc", "PPSC"),
                    ("njp", "National Job Portal"),

                ],
                max_length=50,
            ),
        ),
    ]
