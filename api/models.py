"""Роль «Моделі». Перші 30 хвилин дня цей файл пише вся команда разом.

Що має бути:
- елемент каталогу з числовим полем залишку (`PositiveIntegerField`);
- заявка: власник (FK на User), елемент (FK), кількість, `status`
  зі значеннями рівно `draft` / `confirmed` / `cancelled`;
- `CheckConstraint`, що залишок не від'ємний, — страхувальна сітка, а не головний захист.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class Workout(models.Model):
    """Тренування в каталозі спортзалу."""

    title = models.CharField(max_length=200)
    available = models.PositiveIntegerField(
        default=0,
        help_text="Кількість вільних місць на тренуванні.",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(available__gte=0),
                name="workout_available_non_negative",
            ),
        ]
        verbose_name = "Тренування"
        verbose_name_plural = "Тренування"

    def __str__(self):
        return f"{self.title} (вільних місць: {self.available})"


class Booking(models.Model):
    """Бронювання місць на тренування."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Чернетка"
        CONFIRMED = "confirmed", "Підтверджено"
        CANCELLED = "cancelled", "Скасовано"

    workout = models.ForeignKey(
        Workout,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workout_bookings",
    )
    quantity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    class Meta:
        ordering = ["-id"]
        verbose_name = "Бронювання"
        verbose_name_plural = "Бронювання"

    def __str__(self):
        return f"{self.workout.title}: {self.quantity} місць ({self.status})"