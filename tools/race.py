"""Одночасні дії над заявками — для власного доказу гонки і для атак понад карту.

    # 10 різних заявок по 1 одиниці на елемент 7, одночасний confirm
    python tools/race.py --item 7 --orders 10

    # одна заявка, 10 одночасних confirm
    python tools/race.py --item 7 --orders 10 --same

    # заявки по 3 одиниці
    python tools/race.py --item 7 --orders 5 --qty 3

    # одна підтверджена заявка, 10 одночасних cancel
    python tools/race.py --item 7 --orders 10 --same --action cancel

    # confirm одночасно з PATCH або DELETE тієї самої draft-заявки
    python tools/race.py --item 7 --orders 10 --action confirm-patch
    python tools/race.py --item 7 --orders 10 --action confirm-delete
    python tools/race.py --item 7 --orders 10 --action confirm-cancel
    python tools/race.py --item 7 --orders 10 --action confirm-double-patch

Скрипт друкує коди, залишок до і після та висновок, чи збігається бухгалтерія.
"""
import argparse
import sys
from collections import Counter

from apiclient import Api, fire_at_once, is_ok, load_contract


def confirm_vs_mutation(api, token, item, qty, action, attempts=10):
    """Перевіряє інваріант при одночасних confirm і PATCH/DELETE.

    Допустимі лише два серіалізовані результати: DELETE перемагає і заявка
    зникає без списання, або confirm перемагає і заявка лишається confirmed
    з рівно тим залишком, який відповідає її quantity.
    """
    code, order = api.create_order(token, item, qty)
    if code not in (200, 201) or not isinstance(order, dict):
        return False, f"заявка не створилась: {code} {order}"

    order_id = order["id"]
    before = api.left(item)
    if action == "confirm-patch":
        changed_qty = qty + 1
        if changed_qty > before:
            return False, f"для PATCH потрібно щонайменше {changed_qty} вільних місць, є {before}"
        mutation = lambda: api.request(
            "PATCH", api.order_path(order_id), api.order_body(item, changed_qty), token=token
        )[0]
    elif action == "confirm-delete":
        mutation = lambda: api.request("DELETE", api.order_path(order_id), token=token)[0]
    elif action == "confirm-cancel":
        mutation = lambda: api.action(token, order_id, "cancel")
    else:
        raise ValueError(f"Невідома змішана гонка: {action}")

    calls = []
    for _ in range(attempts):
        calls.extend((lambda: api.action(token, order_id, "confirm"), mutation))
    codes = fire_at_once(calls)
    confirm_codes, mutation_codes = codes[::2], codes[1::2]
    after = api.left(item)
    get_code, data = api.request("GET", api.order_path(order_id), token=token)
    errors = sum(code >= 500 or code == 0 for code in codes)

    if action == "confirm-patch":
        final_qty = data.get(api.c["qty_field"]) if isinstance(data, dict) else None
        ok = (
            get_code == 200
            and isinstance(final_qty, int)
            and data.get("status") == "confirmed"
            and after == before - final_qty
            and any(is_ok(code) for code in confirm_codes)
            and errors == 0
        )
    elif action == "confirm-delete":
        # Або DELETE випередив confirm (заявки немає, місця не списані), або
        # confirm випередив DELETE (заявка confirmed і списана рівно один раз).
        missing_ok = get_code == 404 and after == before
        confirmed_ok = (
            get_code == 200
            and isinstance(data, dict)
            and data.get("status") == "confirmed"
            and after == before - qty
        )
        ok = (missing_ok or confirmed_ok) and errors == 0
    else:
        # Незалежно від порядку один cancel має завершити заявку, а сумарний
        # залишок мусить повернутися точно до початкового значення.
        ok = (
            get_code == 200
            and isinstance(data, dict)
            and data.get("status") == "cancelled"
            and after == before
            and errors == 0
        )

    note = (
        f"confirm {dict(sorted(Counter(confirm_codes).items()))}; "
        f"{action.removeprefix('confirm-')} {dict(sorted(Counter(mutation_codes).items()))}; "
        f"залишок {before}→{after}; GET {get_code}"
    )
    return ok, note


def confirm_vs_two_patches(api, token, item, qty, attempts=10):
    """Зіставляє confirm з двома різними PATCH draft-заявки.

    Який саме PATCH виграє — неважливо. Важливо, щоб списання відповідало
    фінальному quantity, а не значенню, прочитаному confirm до гонки.
    """
    code, order = api.create_order(token, item, qty)
    if code not in (200, 201) or not isinstance(order, dict):
        return False, f"заявка не створилась: {code} {order}"

    before = api.left(item)
    values = (qty + 1, qty + 2)
    if values[-1] > before:
        return False, f"для двох PATCH потрібно щонайменше {values[-1]} вільних місць, є {before}"

    order_id = order["id"]
    patch_one = lambda: api.request(
        "PATCH", api.order_path(order_id), api.order_body(item, values[0]), token=token
    )[0]
    patch_two = lambda: api.request(
        "PATCH", api.order_path(order_id), api.order_body(item, values[1]), token=token
    )[0]
    calls = []
    for _ in range(attempts):
        calls.extend((lambda: api.action(token, order_id, "confirm"), patch_one, patch_two))
    codes = fire_at_once(calls)
    confirm_codes = codes[::3]
    patch_codes = codes[1::3] + codes[2::3]
    after = api.left(item)
    get_code, data = api.request("GET", api.order_path(order_id), token=token)
    final_qty = data.get(api.c["qty_field"]) if isinstance(data, dict) else None
    errors = sum(code >= 500 or code == 0 for code in codes)
    ok = (
        get_code == 200
        and isinstance(data, dict)
        and data.get("status") == "confirmed"
        and final_qty in (qty, *values)
        and after == before - final_qty
        and sum(is_ok(code) for code in confirm_codes) == 1
        and errors == 0
    )
    note = (
        f"confirm {dict(sorted(Counter(confirm_codes).items()))}; "
        f"PATCH {dict(sorted(Counter(patch_codes).items()))}; "
        f"quantity {final_qty}; залишок {before}→{after}"
    )
    return ok, note


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--contract", default="contract.json")
    parser.add_argument("--item", type=int, required=True, help="id елемента каталогу")
    parser.add_argument("--orders", type=int, default=10, help="скільки одночасних запитів")
    parser.add_argument("--qty", type=int, default=1, help="кількість у кожній заявці")
    parser.add_argument("--same", action="store_true", help="усі запити на ОДНУ заявку")
    parser.add_argument(
        "--action",
        choices=(
            "confirm", "cancel", "confirm-patch", "confirm-delete", "confirm-cancel",
            "confirm-double-patch",
        ),
        default="confirm",
    )
    parser.add_argument("--user", default="attacker1")
    args = parser.parse_args()

    api = Api(load_contract(args.contract))
    token = api.token(args.user)

    if args.action.startswith("confirm-"):
        if args.action == "confirm-double-patch":
            ok, note = confirm_vs_two_patches(api, token, args.item, args.qty, args.orders)
        else:
            ok, note = confirm_vs_mutation(api, token, args.item, args.qty, args.action, args.orders)
        print(f"{'✅' if ok else '❌'} {args.action}: {note}")
        sys.exit(0 if ok else 1)

    stock = api.left(args.item)

    count = 1 if args.same else args.orders
    orders = []
    for _ in range(count):
        code, data = api.create_order(token, args.item, args.qty)
        if code not in (200, 201) or not isinstance(data, dict):
            sys.exit(f"Заявка не створилась: {code} {data}")
        orders.append(data["id"])

    if args.action == "cancel":
        for order in orders:
            code = api.action(token, order, "confirm")
            if not is_ok(code):
                sys.exit(f"Підготовчий confirm заявки {order} → {code}; cancel перевіряти нічим.")
    before = api.left(args.item)

    targets = orders * args.orders if args.same else orders
    codes = fire_at_once([lambda o=o: api.action(token, o, args.action) for o in targets])
    after = api.left(args.item)
    wins = sum(is_ok(c) for c in codes)

    print(f"Заявок: {len(orders)} по {args.qty} од. · запитів {args.action}: {len(targets)}")
    print(f"Коди: {dict(sorted(Counter(codes).items()))}")
    print(f"Залишок: на старті {stock}, перед залпом {before}, після {after}")

    if args.action == "confirm" and args.same:
        expected_wins, expected_left = 1, before - args.qty
    elif args.action == "confirm":
        expected_wins = min(len(orders), before // args.qty)
        expected_left = before - expected_wins * args.qty
    elif args.same:
        expected_wins, expected_left = 1, before + args.qty
    else:
        expected_wins, expected_left = len(orders), before + len(orders) * args.qty

    errors = sum(c >= 500 or c == 0 for c in codes)
    ok = wins == expected_wins and after == expected_left and errors == 0
    print(f"Очікували: {expected_wins}×2xx, залишок {expected_left}, без 5xx")
    print("✅ бухгалтерія зійшлась" if ok else "❌ ПРОБІЙ: бухгалтерія не зійшлась")
    print("Один зелений прогін — не доказ. Повторіть кілька разів.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
