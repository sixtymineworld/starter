"""Роль «API». Серіалізатори каталогу і заявки.

Пам'ятка: що клієнт НЕ має права задати в тілі — `owner`, `status` —
робіть read-only, а не «сподіваємось, що ніхто не надішле».
"""
from rest_framework import serializers  # noqa: F401
