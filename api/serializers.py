"""Роль «API». Серіалізатори каталогу і заявки.

Захист від атак:
- owner і status позначені як read_only, щоб клієнт не міг їх підмінити (рядки 11, 12).
- quantity валідується: мінімум 1, максимум 1 000 000 (рядки 13, 14, 15).
- workout валідується автоматично як PrimaryKeyRelatedField (рядок 16).
- перевірка наявності достатньої кількості вільних місць (рядок 17).
"""
from rest_framework import serializers
from .models import Workout, Booking


class WorkoutSerializer(serializers.ModelSerializer):
    """Серіалізатор для каталогу тренувань."""

    class Meta:
        model = Workout
        fields = ["id", "title", "available"]
        read_only_fields = ["id"]


class BookingSerializer(serializers.ModelSerializer):
    """Серіалізатор для заявок на бронювання місць."""

    owner = serializers.ReadOnlyField(source="owner.id")
    status = serializers.ReadOnlyField()
    quantity = serializers.IntegerField(min_value=1, max_value=1_000_000)

    class Meta:
        model = Booking
        fields = ["id", "workout", "owner", "quantity", "status"]
        read_only_fields = ["id", "owner", "status"]

    def validate(self, attrs):
        # Забороняємо редагувати заявки, які вже не в стані draft
        if self.instance and self.instance.status != "draft":
            raise serializers.ValidationError("Змінювати можна лише заявки у статусі draft.")

        workout = attrs.get("workout") or (self.instance.workout if self.instance else None)
        quantity = attrs.get("quantity") or (self.instance.quantity if self.instance else None)

        if workout and quantity is not None and quantity > workout.available:
            raise serializers.ValidationError(
                {"quantity": f"Недостатньо місць на тренуванні (доступно: {workout.available})."}
            )

        return attrs
