"""Спільний клієнт для attack_open.py і race.py. Лише стандартна бібліотека,
тож працює на будь-якому ноутбуці з Python 3.10+, зокрема на Windows."""
import json
import threading
import urllib.error
import urllib.request

ALLOWED_CONTRACT_KEYS = {
    "base_url", "token_url", "items", "orders", "item_field", "qty_field",
    "left_field", "order_extra", "race_item", "users",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редірект — теж відповідь сервера, його треба побачити, а не пройти."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def load_contract(path):
    with open(path, encoding="utf-8") as f:
        contract = json.load(f)
    missing = ALLOWED_CONTRACT_KEYS - contract.keys()
    if missing:
        raise SystemExit(f"У {path} бракує ключів: {', '.join(sorted(missing))}")
    return contract


class Api:
    def __init__(self, contract):
        self.c = contract
        self.base = contract["base_url"].rstrip("/")
        self._tokens = {}

    # --- низький рівень ---------------------------------------------------

    def request(self, method, path, body=None, token=None, raw=None, headers=None):
        """Повертає (код, розібране тіло або текст). Код 0 — сервер недоступний."""
        url = path if path.startswith("http") else self.base + path
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with _opener.open(req, timeout=30) as resp:
                status, payload = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, payload = err.code, err.read()
        except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
            return 0, str(err)
        try:
            return status, json.loads(payload or b"null")
        except ValueError:
            return status, payload.decode(errors="replace")[:300]

    # --- предметний рівень -------------------------------------------------

    def token(self, user):
        if user not in self._tokens:
            password = self.c["users"][user]
            code, data = self.request("POST", self.c["token_url"],
                                      {"username": user, "password": password})
            if code != 200 or not isinstance(data, dict) or "access" not in data:
                raise SystemExit(f"Не вдалося отримати токен для {user}: {code} {data}\n"
                                 "Перевірте token_url, users у contract.json і чи запущено seed_attack.")
            self._tokens[user] = data["access"]
        return self._tokens[user]

    def order_path(self, order_id=None, action=None):
        path = self.c["orders"]
        if order_id is not None:
            path += f"{order_id}/"
        if action:
            path += f"{action}/"
        return path

    def item_path(self, item_id=None):
        return self.c["items"] + (f"{item_id}/" if item_id is not None else "")

    @staticmethod
    def as_list(data):
        """Список — або голий, або з пагінацією {"results": [...]}."""
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"]
        return data if isinstance(data, list) else []

    def items(self):
        return self.as_list(self.request("GET", self.item_path())[1])

    def left(self, item_id):
        code, data = self.request("GET", self.item_path(item_id))
        if code != 200 or not isinstance(data, dict) or self.c["left_field"] not in data:
            raise SystemExit(f"GET {self.item_path(item_id)} → {code}, поля "
                             f"'{self.c['left_field']}' немає: {data}")
        return data[self.c["left_field"]]

    def order_body(self, item_id, qty, **override):
        body = {self.c["item_field"]: item_id, self.c["qty_field"]: qty, **self.c["order_extra"]}
        body.update(override)
        return body

    def create_order(self, token, item_id, qty=1, **override):
        return self.request("POST", self.order_path(), self.order_body(item_id, qty, **override), token)

    def action(self, token, order_id, name):
        return self.request("POST", self.order_path(order_id, name), token=token)[0]


def fire_at_once(calls):
    """Запускає всі виклики в окремих потоках і відпускає їх одночасно через Barrier.
    Повертає список результатів у тому самому порядку."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def worker(i, fn):
        barrier.wait()
        results[i] = fn()

    threads = [threading.Thread(target=worker, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def is_ok(code):
    return 200 <= code < 300
