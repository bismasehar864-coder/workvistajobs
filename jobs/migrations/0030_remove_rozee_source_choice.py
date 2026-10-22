from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0029_profile_salary_currency_database_and_notification_kind"),
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
                    ("brightspyre", "BrightSpyre"),
                ],
                max_length=50,
            ),
        ),
    ]
