"""Одночасні дії над заявками — для власного доказу гонки і для атак понад карту.

    # 10 різних заявок по 1 одиниці на елемент 7, одночасний confirm
    python tools/race.py --item 7 --orders 10

    # одна заявка, 10 одночасних confirm
    python tools/race.py --item 7 --orders 10 --same

    # заявки по 3 одиниці
    python tools/race.py --item 7 --orders 5 --qty 3

    # одна підтверджена заявка, 10 одночасних cancel
    python tools/race.py --item 7 --orders 10 --same --action cancel

Скрипт друкує коди, залишок до і після та висновок, чи збігається бухгалтерія.
"""
import argparse
import sys
from collections import Counter

from apiclient import Api, fire_at_once, is_ok, load_contract


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--contract", default="contract.json")
    parser.add_argument("--item", type=int, required=True, help="id елемента каталогу")
    parser.add_argument("--orders", type=int, default=10, help="скільки одночасних запитів")
    parser.add_argument("--qty", type=int, default=1, help="кількість у кожній заявці")
    parser.add_argument("--same", action="store_true", help="усі запити на ОДНУ заявку")
    parser.add_argument("--action", choices=("confirm", "cancel"), default="confirm")
    parser.add_argument("--user", default="attacker1")
    args = parser.parse_args()

    api = Api(load_contract(args.contract))
    token = api.token(args.user)
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
