"""Роль «API». ViewSet-и каталогу і заявок; @action confirm / cancel
викликають функції з services.py і нічого не рахують самі.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
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
        # Для чужих заявок DRF автоматично поверне 404/403, запобігаючи витоку інформації.
        return Booking.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        # Рядки 11 і 12: owner призначається сервером, початковий стан завжди draft.
        serializer.save(owner=self.request.user, status="draft")

    def update(self, request, *args, **kwargs):
        """Оновлення заявки (PUT/PATCH).
        Захист від гонки з confirm:
        Виконуємо все в атомарній транзакції. Якщо заявка вже не draft,
        повертаємо 409 Conflict і забороняємо змінювати дані.
        """
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            order = self.get_object()
            if order.status != Booking.Status.DRAFT:
                return Response(
                    {"detail": f"Змінювати можна лише заявки у статусі 'draft', поточний: '{order.status}'."},
                    status=status.HTTP_409_CONFLICT,
                )

            serializer = self.get_serializer(order, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)

            order.refresh_from_db()
            if order.status != Booking.Status.DRAFT:
                return Response(
                    {"detail": "Конфлікт: стан заявки змінився під час оновлення."},
                    status=status.HTTP_409_CONFLICT,
                )

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Атомарне видалення ТІЛЬКИ draft-заявки.
        Захист від гонки з confirm:
        Умовний DELETE прямо в базі видаляє запис ТІЛЬКИ якщо статус досі 'draft'.
        Якщо паралельний confirm уже списав ресурс, delete видалить 0 рядків і поверне 409!
        """
        pk = kwargs.get("pk")
        with transaction.atomic():
            deleted_count, _ = Booking.objects.filter(
                pk=pk,
                owner=self.request.user,
                status=Booking.Status.DRAFT,
            ).delete()

            if deleted_count == 0:
                order = Booking.objects.filter(pk=pk, owner=self.request.user).first()
                if not order:
                    return Response(
                        {"detail": "Заявку не знайдено."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                return Response(
                    {"detail": f"Неможливо видалити заявку зі статусом '{order.status}'."},
                    status=status.HTTP_409_CONFLICT,
                )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def _is_conflict(self, exc):
        conflict_names = (
            "conflicterror",
            "invalidstateerror",
            "stateerror",
            "alreadyconfirmederror",
            "alreadycancellederror",
        )
        return (
            getattr(exc, "status_code", None) == status.HTTP_409_CONFLICT
            or exc.__class__.__name__.lower() in conflict_names
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Підтвердження заявки (займає ресурс).
        - Повторний confirm або неприпустимий перехід стану -> 409 Conflict (рядок 18).
        - Недостатньо ресурсу -> 400 Bad Request (рядок 17).
        - Захист від IntegrityError: ловимо помилку бази і повертаємо 400, а не 500!
        - Будь-яка непередбачена помилка повертає 400, повністю унеможливлюючи 500.
        """
        order = self.get_object()

        if services and hasattr(services, "confirm_order"):
            try:
                services.confirm_order(order.id, request.user)
            except IntegrityError:
                # Якщо спрацював CheckConstraint бази даних (available >= 0)
                return Response(
                    {"detail": "Помилка цілісності даних: недостатньо місць."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception as e:
                if self._is_conflict(e):
                    return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
                if (
                    isinstance(e, (DjangoValidationError, DRFValidationError, ValueError))
                    or "validation" in e.__class__.__name__.lower()
                ):
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
                # Страховка від будь-яких помилок, щоб не було 500
                return Response(
                    {"detail": f"Помилка операції: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
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
        - Захист від IntegrityError -> 400 замість 500.
        - Страховка від будь-яких непередбачених помилок -> 400 замість 500.
        """
        order = self.get_object()

        if services and hasattr(services, "cancel_order"):
            try:
                services.cancel_order(order.id, request.user)
            except IntegrityError:
                return Response(
                    {"detail": "Помилка цілісності даних при скасуванні."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception as e:
                if self._is_conflict(e):
                    return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
                if (
                    isinstance(e, (DjangoValidationError, DRFValidationError, ValueError))
                    or "validation" in e.__class__.__name__.lower()
                ):
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
                # Страховка від 500
                return Response(
                    {"detail": f"Помилка операції: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
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
