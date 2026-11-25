"""Відкрита карта атаки — автоматичний прогін.

    python tools/attack_open.py                      # contract.json поруч
    python tools/attack_open.py --contract ../team3/contract.json
    python tools/attack_open.py --only 18,19,21      # лише вибрані рядки

Рядки 1–20 — по 1 балу. 21 (гонка на одній заявці) і 22 (гонка за ресурс) рахуються
окремо. Скрипт сам створює потрібні заявки від attacker1 і attacker2. Перед повторним
прогоном 22-го рядка відновіть залишок: python manage.py seed_attack.

Рядки 23–35 — додаткові регресійні перевірки інваріанта: їхній результат не входить
до відкритої карти, зате вони ловлять неочевидні обходи через PATCH, DELETE і гонки.

Ганяйте його проти себе скільки завгодно: це специфікація, а не іспит.
"""
import argparse
import http.cookiejar
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from apiclient import Api, _NoRedirect, fire_at_once, is_ok, load_contract
from race import confirm_vs_mutation, confirm_vs_two_patches

DENIED = (403, 404)
ROWS = {}


def row(number, title, expected):
    def wrap(fn):
        ROWS[number] = (title, expected, fn)
        return fn
    return wrap


class Ctx:
    """Спільні дані прогону: токени, звичайний елемент, чужа заявка."""

    def __init__(self, api):
        self.api = api
        self.t1 = api.token("attacker1")
        self.t2 = api.token("attacker2")
        items = api.items()
        left_field = api.c["left_field"]
        regular = [i for i in items
                   if isinstance(i, dict) and i.get("id") != api.c["race_item"]
                   and isinstance(i.get(left_field), int)]
        if not regular:
            raise SystemExit(f"GET {api.item_path()} не повернув елементів із полем '{left_field}'.")
        self.item = max(regular, key=lambda i: i[left_field])["id"]
        if api.left(self.item) < 10:
            raise SystemExit("Найбільший залишок у каталозі менший за 10 — запустіть seed_attack.")

    def new_order(self, token=None, qty=1, item=None):
        code, data = self.api.create_order(token or self.t1, item or self.item, qty)
        if code not in (200, 201) or not isinstance(data, dict) or "id" not in data:
            raise RuntimeError(f"не вдалося створити заявку: {code} {data}")
        return data["id"]

    def foreign(self):
        return self.new_order(self.t2)


# --- без токена --------------------------------------------------------------

@row(1, "GET каталогу без токена", "200")
def r1(c):
    code, _ = c.api.request("GET", c.api.item_path())
    return code == 200, code


@row(2, "GET заявок без токена", "401")
def r2(c):
    code, _ = c.api.request("GET", c.api.order_path())
    return code == 401, code


@row(3, "POST заявки без токена", "401")
def r3(c):
    code, _ = c.api.request("POST", c.api.order_path(), c.api.order_body(c.item, 1))
    return code == 401, code


@row(4, "confirm без токена", "401")
def r4(c):
    code, _ = c.api.request("POST", c.api.order_path(c.foreign(), "confirm"))
    return code == 401, code


@row(5, "неіснуюча адреса /api/v1/neisnuie/", "404")
def r5(c):
    code, _ = c.api.request("GET", "/api/v1/neisnuie/")
    return code == 404, code


def _admin_login(base, username, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)
    url = base + "/admin/login/"
    try:
        html = opener.open(url, timeout=15).read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    form = urllib.parse.urlencode({
        "username": username, "password": password, "next": "/admin/",
        "csrfmiddlewaretoken": match.group(1) if match else "",
    }).encode()
    req = urllib.request.Request(url, data=form, method="POST", headers={"Referer": url})
    try:
        return opener.open(req, timeout=15).status
    except urllib.error.HTTPError as err:
        return err.code


@row(6, "вхід в /admin/ з admin/admin і admin/1234", "вхід не проходить")
def r6(c):
    codes = [_admin_login(c.api.base, "admin", pw) for pw in ("admin", "1234")]
    # 302 після POST — успішний вхід і редірект в адмінку.
    return 302 not in codes, "/".join(map(str, codes))


# --- зі своїм токеном ----------------------------------------------------------

@row(7, "список заявок attacker1", "чужих немає")
def r7(c):
    foreign = c.foreign()
    code, data = c.api.request("GET", c.api.order_path(), token=c.t1)
    ids = [o.get("id") for o in c.api.as_list(data) if isinstance(o, dict)]
    return code == 200 and foreign not in ids, f"{code}, чужа {'є' if foreign in ids else 'немає'}"


@row(8, "GET чужої заявки", "403/404")
def r8(c):
    code, _ = c.api.request("GET", c.api.order_path(c.foreign()), token=c.t1)
    return code in DENIED, code


@row(9, "PATCH і DELETE чужої заявки", "403/404 обидва")
def r9(c):
    foreign = c.foreign()
    patch, _ = c.api.request("PATCH", c.api.order_path(foreign),
                             {c.api.c["qty_field"]: 2}, token=c.t1)
    delete, _ = c.api.request("DELETE", c.api.order_path(foreign), token=c.t1)
    return patch in DENIED and delete in DENIED, f"{patch}/{delete}"


@row(10, "confirm чужої заявки", "403/404")
def r10(c):
    before = c.api.left(c.item)
    code = c.api.action(c.t1, c.foreign(), "confirm")
    after = c.api.left(c.item)
    return code in DENIED and after == before, f"{code}, залишок {before}→{after}"


@row(11, "\"owner\" чужий у тілі створення", "власник — ви (або 400)")
def r11(c):
    code, data = c.api.request("GET", c.api.order_path(c.foreign()), token=c.t2)
    owner = data.get("owner") if isinstance(data, dict) else None
    owner = owner if isinstance(owner, int) else 1
    code, data = c.api.create_order(c.t1, c.item, 1, owner=owner)
    if code == 400:
        return True, code
    if code not in (200, 201) or not isinstance(data, dict):
        return False, code
    mine, _ = c.api.request("GET", c.api.order_path(data["id"]), token=c.t1)
    theirs, _ = c.api.request("GET", c.api.order_path(data["id"]), token=c.t2)
    return mine == 200 and theirs in DENIED, f"{code}; видно мені {mine}, attacker2 {theirs}"


@row(12, "\"status\": \"confirmed\" у тілі створення", "стан draft (або 400)")
def r12(c):
    before = c.api.left(c.item)
    code, data = c.api.create_order(c.t1, c.item, 1, status="confirmed")
    if code == 400:
        return True, code
    if code not in (200, 201) or not isinstance(data, dict):
        return False, code
    _, got = c.api.request("GET", c.api.order_path(data["id"]), token=c.t1)
    status = got.get("status") if isinstance(got, dict) else None
    after = c.api.left(c.item)
    return status == "draft" and after == before, f"{code}, стан {status}, залишок {before}→{after}"


@row(13, "кількість -5", "400")
def r13(c):
    code, data = c.api.create_order(c.t1, c.item, -5)
    if code == 400:
        return True, code
    note = code
    if code in (200, 201) and isinstance(data, dict):
        before = c.api.left(c.item)
        c.api.action(c.t1, data["id"], "confirm")
        after = c.api.left(c.item)
        if after > before:
            note = f"{code}, ГРУБИЙ ПРОБІЙ: confirm збільшив залишок {before}→{after}"
    return False, note


@row(14, "кількість 0", "400")
def r14(c):
    code, _ = c.api.create_order(c.t1, c.item, 0)
    return code == 400, code


@row(15, "кількість 99999999999999999999", "400")
def r15(c):
    code, _ = c.api.create_order(c.t1, c.item, 99999999999999999999)
    return code == 400, code


@row(16, "заявка на елемент 999999", "400")
def r16(c):
    code, _ = c.api.create_order(c.t1, 999999, 1)
    return code == 400, code


@row(17, "кількість більша за залишок", "400 на створенні або на confirm")
def r17(c):
    before = c.api.left(c.item)
    code, data = c.api.create_order(c.t1, c.item, before + 1)
    if code == 400:
        return True, f"{code} на створенні"
    if code not in (200, 201) or not isinstance(data, dict):
        return False, code
    confirm = c.api.action(c.t1, data["id"], "confirm")
    after = c.api.left(c.item)
    return confirm == 400 and after == before, f"створення {code}, confirm {confirm}, залишок {before}→{after}"


@row(18, "confirm двічі", "2xx, потім 409")
def r18(c):
    order = c.new_order()
    first = c.api.action(c.t1, order, "confirm")
    second = c.api.action(c.t1, order, "confirm")
    return is_ok(first) and second == 409, f"{first}/{second}"


@row(19, "confirm → cancel → cancel", "другий cancel 409, залишок повернувся рівно раз")
def r19(c):
    before = c.api.left(c.item)
    order = c.new_order()
    codes = [c.api.action(c.t1, order, name) for name in ("confirm", "cancel", "cancel")]
    after = c.api.left(c.item)
    ok = is_ok(codes[0]) and is_ok(codes[1]) and codes[2] == 409 and after == before
    return ok, f"{'/'.join(map(str, codes))}, залишок {before}→{after}"


@row(20, "зламаний JSON", "400")
def r20(c):
    code, _ = c.api.request("POST", c.api.order_path(), token=c.t1,
                            raw=('{"%s":' % c.api.c["qty_field"]).encode())
    return code == 400, code


# --- гонки ---------------------------------------------------------------------

@row(21, "Гонка А: 10 одночасних confirm ОДНІЄЇ заявки, 3 раунди",
     "у кожному рівно один 2xx, залишок −1")
def r21(c):
    notes, ok = [], True
    for _ in range(3):
        order = c.new_order()
        before = c.api.left(c.item)
        codes = fire_at_once([lambda: c.api.action(c.t1, order, "confirm")] * 10)
        after = c.api.left(c.item)
        wins = sum(is_ok(x) for x in codes)
        ok &= wins == 1 and after == before - 1
        notes.append(f"{wins}×2xx {before}→{after}")
    return ok, "; ".join(notes)


@row(22, "Гонка Б: різні заявки на елемент race_item, одночасно",
     "успішних рівно стільки, скільки було залишку; залишок 0")
def r22(c):
    item = c.api.c["race_item"]
    stock = c.api.left(item)
    if stock > 10:
        return False, f"залишок race_item {stock} > 10 — дайте елемент із залишком 1"
    orders = []
    for _ in range(stock + 9):
        code, data = c.api.create_order(c.t1, item, 1)
        if code in (200, 201) and isinstance(data, dict):
            orders.append(data["id"])
    if len(orders) <= stock:
        return False, (f"створилось лише {len(orders)} заявок — сервер не приймає заявки понад "
                       "залишок; гонку перевірити нічим, відновіть залишок seed_attack")
    codes = fire_at_once([lambda o=o: c.api.action(c.t1, o, "confirm") for o in orders])
    after = c.api.left(item)
    wins = sum(is_ok(x) for x in codes)
    errors = sum(x >= 500 or x == 0 for x in codes)
    note = f"{len(orders)} заявок, {wins}×2xx, {errors}×5xx, залишок {stock}→{after}"
    return wins == stock and after == 0 and errors == 0, note


# --- додаткові регресійні перевірки захисту ----------------------------------

@row(23, "після confirm PATCH, PUT і DELETE заборонені", "409/409/409; cancel повертає рівно ресурс")
def r23(c):
    before = c.api.left(c.item)
    order = c.new_order(qty=1)
    confirmed = c.api.action(c.t1, order, "confirm")
    patch, _ = c.api.request(
        "PATCH", c.api.order_path(order), {c.api.c["qty_field"]: 2}, token=c.t1
    )

    other_item = next(
        (item["id"] for item in c.api.items() if isinstance(item, dict) and item.get("id") != c.item),
        c.item,
    )
    put_body = c.api.order_body(other_item, 1)
    put, _ = c.api.request("PUT", c.api.order_path(order), put_body, token=c.t1)
    delete, _ = c.api.request("DELETE", c.api.order_path(order), token=c.t1)
    cancelled = c.api.action(c.t1, order, "cancel")
    after = c.api.left(c.item)
    ok = is_ok(confirmed) and patch == 409 and put == 409 and delete == 409 and is_ok(cancelled) and after == before
    return ok, f"confirm/PATCH/PUT/DELETE/cancel: {confirmed}/{patch}/{put}/{delete}/{cancelled}; {before}→{after}"


@row(24, "Гонка: confirm одночасно з PATCH", "confirmed-заявка і залишок відповідає її quantity")
def r24(c):
    return confirm_vs_mutation(c.api, c.t1, c.item, 1, "confirm-patch")


@row(25, "Гонка: confirm одночасно з DELETE", "або draft видалено без списання, або confirmed лишився")
def r25(c):
    return confirm_vs_mutation(c.api, c.t1, c.item, 1, "confirm-delete")


@row(26, "PATCH не підміняє owner або status", "заявка лишається моєю draft, залишок не змінюється")
def r26(c):
    before = c.api.left(c.item)
    foreign = c.foreign()
    _, foreign_data = c.api.request("GET", c.api.order_path(foreign), token=c.t2)
    foreign_owner = foreign_data.get("owner") if isinstance(foreign_data, dict) else None
    order = c.new_order()
    code, _ = c.api.request(
        "PATCH", c.api.order_path(order),
        {"owner": foreign_owner, "status": "confirmed"}, token=c.t1,
    )
    mine, data = c.api.request("GET", c.api.order_path(order), token=c.t1)
    theirs, _ = c.api.request("GET", c.api.order_path(order), token=c.t2)
    after = c.api.left(c.item)
    if code == 400:
        return True, f"PATCH {code}"
    ok = (
        code == 200
        and mine == 200
        and isinstance(data, dict)
        and data.get("status") == "draft"
        and data.get("owner") != foreign_owner
        and theirs in DENIED
        and after == before
    )
    return ok, f"PATCH {code}; статус {data.get('status') if isinstance(data, dict) else data}; залишок {before}→{after}"


@row(27, "cancel draft не повертає не зайняті місця", "cancel 2xx; залишок без змін; confirm після цього 409")
def r27(c):
    before = c.api.left(c.item)
    order = c.new_order()
    cancelled = c.api.action(c.t1, order, "cancel")
    confirm = c.api.action(c.t1, order, "confirm")
    after = c.api.left(c.item)
    return is_ok(cancelled) and confirm == 409 and after == before, f"cancel/confirm: {cancelled}/{confirm}; {before}→{after}"


@row(28, "зміна draft списує та повертає саме нову кількість і тренування", "після cancel обидва залишки відновлено")
def r28(c):
    items = c.api.items()
    other = next(
        (
            item["id"] for item in items
            if isinstance(item, dict)
            and item.get("id") not in {c.item, c.api.c["race_item"]}
            and isinstance(item.get(c.api.c["left_field"]), int)
            and item[c.api.c["left_field"]] >= 2
        ),
        None,
    )
    if other is None:
        return False, "немає другого звичайного тренування з двома вільними місцями"
    original_before, other_before = c.api.left(c.item), c.api.left(other)
    order = c.new_order(item=c.item, qty=1)
    patch, _ = c.api.request(
        "PATCH", c.api.order_path(order), c.api.order_body(other, 2), token=c.t1
    )
    confirmed = c.api.action(c.t1, order, "confirm")
    original_after_confirm, other_after_confirm = c.api.left(c.item), c.api.left(other)
    cancelled = c.api.action(c.t1, order, "cancel")
    original_after_cancel, other_after_cancel = c.api.left(c.item), c.api.left(other)
    ok = (
        patch == 200
        and is_ok(confirmed)
        and original_after_confirm == original_before
        and other_after_confirm == other_before - 2
        and is_ok(cancelled)
        and original_after_cancel == original_before
        and other_after_cancel == other_before
    )
    return ok, (
        f"PATCH/confirm/cancel {patch}/{confirmed}/{cancelled}; "
        f"старе {original_before}→{original_after_confirm}→{original_after_cancel}; "
        f"нове {other_before}→{other_after_confirm}→{other_after_cancel}"
    )


@row(29, "Гонка: confirm одночасно з cancel", "заявка cancelled, залишок повернувся рівно раз")
def r29(c):
    return confirm_vs_mutation(c.api, c.t1, c.item, 1, "confirm-cancel")


@row(30, "Гонка: 10 cancel однієї confirmed-заявки", "один 2xx, заявка cancelled, місця повернуті раз")
def r30(c):
    order = c.new_order()
    if not is_ok(c.api.action(c.t1, order, "confirm")):
        return False, "підготовчий confirm не пройшов"
    before = c.api.left(c.item)
    codes = fire_at_once([lambda: c.api.action(c.t1, order, "cancel")] * 10)
    after = c.api.left(c.item)
    code, data = c.api.request("GET", c.api.order_path(order), token=c.t1)
    wins = sum(is_ok(code) for code in codes)
    ok = code == 200 and isinstance(data, dict) and data.get("status") == "cancelled" and wins == 1 and after == before + 1
    return ok, f"{dict(sorted(Counter(codes).items()))}; залишок {before}→{after}"


@row(31, "Пакетна бухгалтерія: 6 заявок різної кількості", "після часткових cancel залишок точний, після всіх — початковий")
def r31(c):
    quantities = (1, 2, 3, 1, 2, 3)
    before = c.api.left(c.item)
    if before < sum(quantities):
        return False, f"потрібно {sum(quantities)} місць, є {before}"
    orders = [c.new_order(qty=qty) for qty in quantities]
    confirms = [c.api.action(c.t1, order, "confirm") for order in orders]
    middle = (1, 3, 5)
    partial_cancels = [c.api.action(c.t1, orders[index], "cancel") for index in middle]
    after_partial = c.api.left(c.item)
    expected_partial = before - sum(qty for index, qty in enumerate(quantities) if index not in middle)
    rest = [index for index in range(len(orders)) if index not in middle]
    final_cancels = [c.api.action(c.t1, orders[index], "cancel") for index in rest]
    after_final = c.api.left(c.item)
    ok = (
        all(is_ok(code) for code in confirms + partial_cancels + final_cancels)
        and after_partial == expected_partial
        and after_final == before
    )
    return ok, f"залишок {before}→{after_partial} (очікували {expected_partial})→{after_final}"


@row(32, "Нетипові JSON-тіла", "null, масив і рядок у quantity дають 400, не 500")
def r32(c):
    bad_bodies = (
        b"null",
        b"[]",
        ('{"%s": %d, "%s": "not-a-number"}' % (c.api.c["item_field"], c.item, c.api.c["qty_field"])).encode(),
    )
    codes = [
        c.api.request("POST", c.api.order_path(), token=c.t1, raw=body)[0]
        for body in bad_bodies
    ]
    return all(code == 400 for code in codes), "/".join(map(str, codes))


@row(33, "Недозволені HTTP-методи для confirm/cancel", "405 і стан/залишок не змінюються")
def r33(c):
    before = c.api.left(c.item)
    order = c.new_order()
    methods = (
        c.api.request("GET", c.api.order_path(order, "confirm"), token=c.t1)[0],
        c.api.request("PATCH", c.api.order_path(order, "confirm"), {}, token=c.t1)[0],
        c.api.request("PUT", c.api.order_path(order, "cancel"), {}, token=c.t1)[0],
    )
    code, data = c.api.request("GET", c.api.order_path(order), token=c.t1)
    after = c.api.left(c.item)
    ok = all(method == 405 for method in methods) and code == 200 and isinstance(data, dict) and data.get("status") == "draft" and after == before
    return ok, f"методи {'/'.join(map(str, methods))}; стан {data.get('status') if isinstance(data, dict) else data}; {before}→{after}"


@row(34, "Невалідний JWT", "401 для читання й запису, без створення заявки")
def r34(c):
    fake = "not-a.jwt.token"
    before = c.api.left(c.item)
    listing, _ = c.api.request("GET", c.api.order_path(), token=fake)
    created, _ = c.api.request("POST", c.api.order_path(), c.api.order_body(c.item, 1), token=fake)
    after = c.api.left(c.item)
    return listing == 401 and created == 401 and after == before, f"GET/POST {listing}/{created}; {before}→{after}"


@row(35, "Гонка: confirm одночасно з двома різними PATCH", "залишок дорівнює фінальній quantity")
def r35(c):
    return confirm_vs_two_patches(c.api, c.t1, c.item, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--contract", default="contract.json")
    parser.add_argument("--only", help="номери рядків через кому, напр. 18,19,21")
    args = parser.parse_args()

    api = Api(load_contract(args.contract))
    numbers = sorted(ROWS) if not args.only else [int(x) for x in args.only.split(",")]
    ctx = Ctx(api)

    passed = {}
    for n in numbers:
        title, expected, fn = ROWS[n]
        try:
            ok, got = fn(ctx)
        except RuntimeError as err:
            ok, got = False, str(err)
        passed[n] = ok
        print(f"{'✅' if ok else '❌'} {n:>2}. {title}\n       очікувано: {expected} · отримано: {got}")

    open_rows = [n for n in passed if n <= 20]
    print("\n" + "─" * 60)
    if open_rows:
        print(f"Відкрита карта: {sum(passed[n] for n in open_rows)} / {len(open_rows)}")
    for n, name in ((21, "Гонка А"), (22, "Гонка Б")):
        if n in passed:
            print(f"{name}: {'витримано' if passed[n] else 'ПРОБИТО'}")
    extra_rows = [n for n in passed if n >= 23]
    if extra_rows:
        print(f"Додатковий захист: {sum(passed[n] for n in extra_rows)} / {len(extra_rows)}")
    print("Гонки ймовірнісні: зелений результат — не доказ, червоний — доказ.")
    sys.exit(0 if all(passed.values()) else 1)


if __name__ == "__main__":
    main()
