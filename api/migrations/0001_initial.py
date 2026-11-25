import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Workout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("available", models.PositiveIntegerField(default=0, help_text="Кількість вільних місць на тренуванні.")),
            ],
            options={
                "verbose_name": "Тренування",
                "verbose_name_plural": "Тренування",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="Booking",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("draft", "Чернетка"), ("confirmed", "Підтверджено"), ("cancelled", "Скасовано")], default="draft", max_length=10)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workout_bookings", to=settings.AUTH_USER_MODEL)),
                ("workout", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="api.workout")),
            ],
            options={
                "verbose_name": "Бронювання",
                "verbose_name_plural": "Бронювання",
                "ordering": ["-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="workout",
            constraint=models.CheckConstraint(condition=models.Q(("available__gte", 0)), name="workout_available_non_negative"),
        ),
    ]
