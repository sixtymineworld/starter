"""Роль «Моделі». Готує базу до атаки; запускати можна скільки завгодно разів.

    python manage.py migrate
    python manage.py seed_attack

Атакувальник клонує ваш репозиторій на тегу `attack` і запускає саме ці дві команди,
тож усе, без чого атака неможлива, має створюватися тут.
"""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from api.models import Workout

ATTACKERS = {"attacker1": "attack-pass-1", "attacker2": "attack-pass-2"}


class Command(BaseCommand):
    help = "Створює attacker1/attacker2 та тренування для тестів API."

    def handle(self, *args, **options):
        User = get_user_model()
        for username, password in ATTACKERS.items():
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save(update_fields=["password"])

        # update_or_create робить команду повторно-запускною і відновлює
        # залишки після race-тесту.
        workouts = [
            ("Загальна фізична підготовка", 50),
            ("Силове тренування", 50),
            ("Тренування з одним вільним місцем", 1),
        ]
        race_workout = None
        for title, available in workouts:
            workout, _ = Workout.objects.update_or_create(
                title=title,
                defaults={"available": available},
            )
            if available == 1:
                race_workout = workout

        # Скрипти атаки беруть id ресурсу саме з contract.json.
        contract_path = Path(settings.BASE_DIR) / "contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["race_item"] = race_workout.pk
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: attacker1, attacker2, каталог; race_item={race_workout.pk}."
            )
        )
