"""Роль «Доступ». Власні класи прав."""
from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Без токена -> 401, чужі об'єкти недоступні."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return obj.owner_id == request.user.id


class ReadOnlyOrAdmin(permissions.BasePermission):
    """Каталог: читають усі, пишуть тільки адміни."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)