"""Роль «API». ViewSet-и каталогу і заявок; @action confirm / cancel
викликають функції з services.py і нічого не рахують самі.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from .models import Booking, Workout
from .permissions import IsOwner
from .serializers import BookingSerializer, WorkoutSerializer

try:
    from . import services
except ImportError:
    services = None


class WorkoutViewSet(viewsets.ReadOnlyModelViewSet):
    """Каталог тренувань відкритий для читання без токена (рядок 1 карти)."""

    queryset = Workout.objects.all()
    serializer_class = WorkoutSerializer
    permission_classes = [permissions.AllowAny]


class BookingViewSet(viewsets.ModelViewSet):
    """Заявки на тренування доступні лише авторизованим користувачам (рядки 2-4 карти)."""

    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        # Рядки 7-10: повертаємо ТІЛЬКИ власні заявки поточного користувача.
        # Для чужих заявок DRF автоматично поверне 404/403, запобігаючи доступу інших.
        return Booking.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        # Рядки 11 і 12: owner призначається сервером, початковий стан завжди draft.
        serializer.save(owner=self.request.user, status="draft")

    def _is_conflict(self, exc):
        conflict_names = ("conflicterror", "invalidstateerror", "stateerror")
        return (
            getattr(exc, "status_code", None) == status.HTTP_409_CONFLICT
            or exc.__class__.__name__.lower() in conflict_names
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Підтвердження заявки (займає ресурс).
        - Повторний confirm або неприпустимий перехід стану -> 409 Conflict (рядок 18).
        - Недостатньо ресурсу -> 400 Bad Request (рядок 17).
        """
        order = self.get_object()

        if services and hasattr(services, "confirm_order"):
            try:
                services.confirm_order(order.id, request.user)
            except Exception as e:
                if self._is_conflict(e):
                    return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
                if isinstance(e, (DjangoValidationError, DRFValidationError)) or "validation" in e.__class__.__name__.lower():
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
                raise
        else:
            if order.status != "draft":
                return Response(
                    {"detail": f"Неможливо підтвердити заявку зі статусом {order.status}"},
                    status=status.HTTP_409_CONFLICT,
                )
            order.status = "confirmed"
            order.save()

        order.refresh_from_db()
        return Response(self.get_serializer(order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Скасування заявки (повертає ресурс, якщо був confirmed).
        - Повторний cancel або спроба змінити кінцевий стан -> 409 Conflict (рядок 19).
        """
        order = self.get_object()

        if services and hasattr(services, "cancel_order"):
            try:
                services.cancel_order(order.id, request.user)
            except Exception as e:
                if self._is_conflict(e):
                    return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
                if isinstance(e, (DjangoValidationError, DRFValidationError)) or "validation" in e.__class__.__name__.lower():
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
                raise
        else:
            if order.status == "cancelled":
                return Response(
                    {"detail": "Заявка вже була скасована"},
                    status=status.HTTP_409_CONFLICT,
                )
            order.status = "cancelled"
            order.save()

        order.refresh_from_db()
        return Response(self.get_serializer(order).data, status=status.HTTP_200_OK)
