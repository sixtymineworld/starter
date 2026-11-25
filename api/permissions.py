"""Роль «Доступ». Власні класи прав."""
from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Без токена -> 401, включно зі списком."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        return obj.owner_id == request.user.id