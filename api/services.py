"""Роль «Стійкість». Уся бухгалтерія ресурсу — тут, а не у views.

    def confirm_order(order_id: int, user) -> Order: ...
    def cancel_order(order_id: int, user) -> Order: ...

Головне правило дня: ресурс зайнятий тоді й лише тоді, коли заявка в стані
`confirmed`. Кожна функція — одна `transaction.atomic()` і умовні UPDATE
(див. регламент, етап 2). Помилки віддавайте винятками, а views перетворять
їх на 400 / 409.
"""
from django.db import transaction  # noqa: F401
from django.db.models import F  # noqa: F401
