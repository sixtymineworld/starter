"""Роль «Моделі». Готує базу до атаки; запускати можна скільки завгодно разів.

    python manage.py migrate
    python manage.py seed_attack

Атакувальник клонує ваш репозиторій на тегу `attack` і запускає саме ці дві команди,
тож усе, без чого атака неможлива, має створюватися тут.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

# Ті самі паролі — у contract.json.
ATTACKERS = {"attacker1": "attack-pass-1", "attacker2": "attack-pass-2"}


class Command(BaseCommand):
    help = "Акаунти attacker1/attacker2 і каталог для атаки."

    def handle(self, *args, **options):
        User = get_user_model()
        for username, password in ATTACKERS.items():
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()

        # TODO (Моделі), через update_or_create, щоб повторний запуск відновлював стан:
        #   1. кілька звичайних елементів каталогу із залишком 50;
        #   2. один елемент для гонки із залишком рівно 1 — його id іде
        #      в contract.json як "race_item".
        # Заявки attacker2 створювати не треба: скрипт атаки зробить це сам.

        self.stdout.write(self.style.SUCCESS("Готово: attacker1, attacker2, каталог."))
