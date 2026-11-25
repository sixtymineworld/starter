# API-спринт · стартовий скелет

Порожній проєкт, у якому вже є все, що не є змістом дня: DRF, вхід через JWT,
SQLite, налаштований під одночасні запити, і скрипти атаки. Ваша робота — `api/`.

> Цей файл — шаблон. Роль «Моделі» заповнює розділи **«Наш домен»** і **«Сценарій
> у curl»** під ваш домен, решту лишіть як є: за ним вашу ціль готуватиме інша команда.

## Запуск

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_attack      # акаунти attacker1 / attacker2 і каталог
python manage.py runserver
```

Потрібні Python 3.10+ і Django 5.1+.

## Хто що пише

| Роль | Файли |
|---|---|
| Моделі | `api/models.py`, `api/admin.py`, `api/management/commands/seed_attack.py`, `contract.json`, цей README |
| API | `api/serializers.py`, `api/views.py`, `api/urls.py` (і `config/`, якщо треба) |
| Доступ | `api/permissions.py` |
| Стійкість | `api/services.py` |

Комітьте лише у свої файли — тоді чотири людини в одному репозиторії не конфліктують.
Перед комітом: `git pull --rebase`.

## Вхід

Реєстрації немає і не треба: акаунти створює `seed_attack`.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
     -H "Content-Type: application/json" \
     -d '{"username": "attacker1", "password": "attack-pass-1"}'
# → {"refresh": "...", "access": "..."}

curl -s http://127.0.0.1:8000/api/v1/<заявки>/ -H "Authorization: Bearer <access>"
```

Токен живе 8 годин.

## contract.json

Його читають скрипти атаки — ваші і чужі. Заповніть під свій домен:

| Ключ | Що це | Приклад |
|---|---|---|
| `base_url` | де запущено сервер | `http://127.0.0.1:8000` |
| `token_url` | вхід | `/api/v1/auth/token/` (не міняйте) |
| `items` | список каталогу, зі слешем у кінці | `/api/v1/bikes/` |
| `orders` | список заявок | `/api/v1/rentals/` |
| `item_field` | поле заявки з `id` елемента каталогу | `bike` |
| `qty_field` | поле кількості в заявці | `quantity` |
| `left_field` | поле залишку в елементі каталогу | `available` |
| `order_extra` | інші обов'язкові поля заявки, якщо є | `{"date": "2026-12-01"}` |
| `race_item` | `id` елемента із залишком рівно 1 — друкує `seed_attack` | `4` |
| `users` | паролі `attacker1` / `attacker2`, ті самі, що в `seed_attack` | |

Скрипти припускають, що: у каталогу й заявки є поле `id`; у заявки є `status` зі
значеннями `draft` / `confirmed` / `cancelled`; дії — `POST <orders><id>/confirm/` і
`POST <orders><id>/cancel/`.

## Скрипти атаки

```bash
python tools/attack_open.py                   # уся відкрита карта проти себе
python tools/attack_open.py --only 18,19,21   # вибрані рядки
python tools/race.py --item 1 --orders 10     # 10 різних заявок, одночасний confirm
python tools/race.py --item 1 --orders 10 --same                  # одна заявка
python tools/race.py --item 1 --orders 10 --same --action cancel  # одночасний cancel
python tools/race.py --help
```

Обидва скрипти — лише стандартна бібліотека, нічого ставити не треба. Після гонки на
`race_item` відновіть залишок: `python manage.py seed_attack`.

## Наш домен

*Заповнити:* домен, обмежений ресурс, адреси каталогу й заявок, поля.

## Сценарій у curl

*Заповнити:* вхід → каталог → заявка → `confirm` → залишок зменшився → повторний
`confirm` `409` → `cancel` → залишок повернувся.
