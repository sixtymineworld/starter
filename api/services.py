"""Роль «Стійкість». Уся бухгалтерія ресурсу — тут, а не у views.

    def confirm_order(order_id: int, user) -> Booking: ...
    def cancel_order(order_id: int, user) -> Booking: ...

Головне правило дня: ресурс зайнятий тоді й лише тоді, коли заявка в стані
`confirmed`. Кожна функція — одна `transaction.atomic()` і умовні UPDATE
(див. регламент, етап 2).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F

from .models import Booking, Workout


class ConflictError(Exception):
    """Помилка неприпустимого переходу стану або конфлікту (HTTP 409)."""
    status_code = 409


class ValidationError(DjangoValidationError):
    """Помилка валідації або нестачі доступного ресурсу (HTTP 400)."""
    status_code = 400


def confirm_order(order_id: int, user) -> Booking:
    """Підтвердження заявки (займає ресурс).
    
    Перехід: draft -> confirmed
    Захист від гонки (race condition):
    - Умовний UPDATE переводить статус ТІЛЬКИ якщо статус був 'draft'.
    - Умовний UPDATE зменшує available ТІЛЬКИ якщо available >= quantity.
    """
    with transaction.atomic():
        try:
            order = Booking.objects.select_related("workout").get(pk=order_id)
        except Booking.DoesNotExist:
            raise ConflictError("Заявку не знайдено.")

        # Перевірка поточного стану згідно зі схемою станів
        if order.status == Booking.Status.CONFIRMED:
            raise ConflictError("Заявка вже підтверджена (повторний confirm заборонено).")
        if order.status == Booking.Status.CANCELLED:
            raise ConflictError("Заявка вже скасована і не може бути підтверджена.")
        if order.status != Booking.Status.DRAFT:
            raise ConflictError(f"Неможливо підтвердити заявку зі статусом '{order.status}'.")

        # 1. Атомарно фіксуємо зміну статусу: draft -> confirmed
        updated_order_count = Booking.objects.filter(
            pk=order_id,
            status=Booking.Status.DRAFT,
        ).update(status=Booking.Status.CONFIRMED)

        if updated_order_count == 0:
            # Інший одночасний потік уже перехопив заявку
            raise ConflictError("Конфлікт: стан заявки вже було змінено паралельним запитом.")

        # 2. Атомарно списуємо ресурс умовним UPDATE (тільки якщо вистачає місць)
        updated_workout_count = Workout.objects.filter(
            pk=order.workout_id,
            available__gte=order.quantity,
        ).update(available=F("available") - order.quantity)

        if updated_workout_count == 0:
            # Не вистачає місць — викидаємо помилку, що автоматично відкочує transaction.atomic()
            raise ValidationError(
                f"Недостатньо вільних місць на тренуванні. Потрібно: {order.quantity}."
            )

        order.refresh_from_db()
        return order


def cancel_order(order_id: int, user) -> Booking:
    """Скасування заявки (повертає ресурс, якщо був confirmed).
    
    Переходи:
    - confirmed -> cancelled (повертає quantity назад у available)
    - draft -> cancelled (ресурс не займали — нічого не повертаємо)
    - cancelled -> заборонено (409 Conflict, cancelled — кінцевий стан)
    """
    with transaction.atomic():
        try:
            order = Booking.objects.select_related("workout").get(pk=order_id)
        except Booking.DoesNotExist:
            raise ConflictError("Заявку не знайдено.")

        if order.status == Booking.Status.CANCELLED:
            raise ConflictError("Заявка вже була скасована (кінцевий стан).")

        if order.status == Booking.Status.CONFIRMED:
            # 1. Атомарно переводимо confirmed -> cancelled
            updated_order_count = Booking.objects.filter(
                pk=order_id,
                status=Booking.Status.CONFIRMED,
            ).update(status=Booking.Status.CANCELLED)

            if updated_order_count == 0:
                raise ConflictError("Конфлікт: стан заявки вже було змінено іншим запитом.")

            # 2. Повертаємо зайняті місця
            Workout.objects.filter(pk=order.workout_id).update(
                available=F("available") + order.quantity
            )

        elif order.status == Booking.Status.DRAFT:
            # 1. Атомарно переводимо draft -> cancelled (ресурс не займали, нічого не повертаємо)
            updated_order_count = Booking.objects.filter(
                pk=order_id,
                status=Booking.Status.DRAFT,
            ).update(status=Booking.Status.CANCELLED)

            if updated_order_count == 0:
                raise ConflictError("Конфлікт: стан заявки вже було змінено іншим запитом.")
        else:
            raise ConflictError(f"Неможливо скасувати заявку зі статусом '{order.status}'.")

        order.refresh_from_db()
        return order
