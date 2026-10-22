from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0034_scraperschedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="scraperschedule",
            name="next_allowed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
