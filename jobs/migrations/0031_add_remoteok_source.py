from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0030_remove_rozee_source_choice"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="source",
            field=models.CharField(
                choices=[
                    ("mustakbil", "Mustakbil"),
                    ("brightspyre", "BrightSpyre"),
                    ("python_org", "Python.org"),
                    ("ppsc", "PPSC"),
                    ("njp", "National Job Portal"),
                    ("remoteok", "Remote OK"),
                ],
                max_length=50,
            ),
        ),
    ]
