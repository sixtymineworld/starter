"""Роль «Доступ». Власні класи прав.

Заявку бачить і змінює лише її власник. Пам'ятайте: `has_object_permission`
не викликається для списку — список фільтрує `get_queryset`.
"""
from rest_framework import permissions  # noqa: F401
