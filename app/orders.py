"""Player buy orders -- the other half of instasell.

In game, /orders lists player-created buy requests: someone offering to pay a
price for a quantity of an item. /sell fills one when it pays more than the
server's own base price, so a recorded order is the best exit a crafted item can
have -- a named buyer, at a known price, right now, with no listing to wait on.

There is no public feed for it, and that is not for want of looking:

  * donut.auction's order mirror is retired. Its /v2/orders/search/ endpoint still
    answers and validates its arguments, but returns an empty book for every
    query -- including single letters, which would surface anything at all. The
    site's own /orders page says "Order data has been retired", and its API
    documentation says the same.
  * the official api.donutsmp.net documents 19 endpoints across v1 and v2 and not
    one of them is an order endpoint. Its only auction schema is an ask-side
    listing: a request body of {search, sort} where sort is one of lowest_price,
    highest_price, recently_listed or last_listed.
  * DonutStats, the main independent tracker, reads the same four official
    endpoints (player stats, lookup, leaderboards, auction listings) and nothing
    else. Item price history there is built from floor listings it observes.
  * the community's own answer is that orders are in-game only, and that reading
    them would take a client mod, which is bannable.

So this is a table the operator owns, filled from what /orders shows in game. It
follows the same two-file pattern as the /sell price table: a seed shipped in the
image, and an optional copy on the mounted volume whose entries win per item, so
an order added at runtime survives a redeploy. Both files are re-read when they
change, so an order can be added without rebuilding anything.

Orders expire. A buyer's offer can be filled or withdrawn the moment someone
takes it, so an order nobody has looked at for a day is not evidence of a buyer.
A stale order is still returned -- the row shows how old it is -- but it is
flagged, and it does not count as easy money.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("craftflip.orders")

DEFAULT_TTL_HOURS = 24.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # a unix timestamp, seconds or milliseconds
        seconds = float(value) / 1000.0 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        got = datetime.fromisoformat(text)
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ENCHANT_PREFIX = re.compile(r"^\[[^\]]*\]\s*")


def normalise_item(raw: Any) -> str:
    """Accept the same loose spellings as every other endpoint.

    netherite_ingot, Netherite Ingot, minecraft:netherite_ingot and
    [Sharpness V] netherite_ingot all resolve to the same key.
    """
    text = ENCHANT_PREFIX.sub("", str(raw or "").strip())
    text = text.replace("minecraft:", "").replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", text).strip("_").lower()


class OrderBook:
    """Player buy orders, merged from the shipped seed and an optional volume copy."""

    def __init__(
        self,
        path: str | Path | None = None,
        seed_path: str | Path | None = None,
        ttl_hours: float = DEFAULT_TTL_HOURS,
    ) -> None:
        self.path = Path(path) if path else None
        self.seed_path = Path(seed_path) if seed_path else None
        self.default_ttl_hours = float(ttl_hours or DEFAULT_TTL_HOURS)
        self._orders: dict[str, dict[str, Any]] = {}
        self._ttl_hours = self.default_ttl_hours
        self._stamps: dict[str, float] = {}
        self._loaded = False
        self._errors: list[str] = []
        self._lock = threading.Lock()
        self.revision = 0
        self.reload()

    # ---------------------------------------------------------------- loading ----
    @staticmethod
    def _read(path: Path | None) -> tuple[dict[str, Any], str | None]:
        if path is None or not path.exists():
            return {}, None
        try:
            with path.open(encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            return {}, f"{path}: {type(exc).__name__}: {exc}"
        if not isinstance(doc, dict):
            return {}, f"{path}: expected a JSON object"
        return doc, None

    @staticmethod
    def _entries(doc: dict[str, Any]) -> list[Any]:
        """Accept either an object keyed by item, or a list of {item, price, ...}."""
        raw = doc.get("orders")
        if raw is None:
            # allow a bare {"netherite_ingot": {...}} document too
            raw = {k: v for k, v in doc.items() if k not in ("ttlHours", "orders", "version")}
        if isinstance(raw, dict):
            out: list[Any] = []
            for name, entry in raw.items():
                if isinstance(entry, dict):
                    out.append({**entry, "item": entry.get("item") or name})
                else:
                    out.append({"item": name, "price": entry})
            return out
        if isinstance(raw, list):
            return raw
        return []

    @classmethod
    def _normalise(
        cls, entries: list[Any], errors: list[str], where: str
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{where}: entry is not an object")
                continue
            name = normalise_item(entry.get("item"))
            if not name:
                errors.append(f"{where}: entry has no item name")
                continue

            # `quantity: 0` must not be read as "unset" and quietly become 1 -- an
            # order for nothing is a mistake worth reporting, not a round number
            raw_quantity = entry.get("quantity")
            if raw_quantity is None:
                raw_quantity = entry.get("amount")
            if raw_quantity is None:
                raw_quantity = 1
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                errors.append(f"{where}: {name} has a non-integer quantity")
                continue
            if quantity < 1:
                errors.append(f"{where}: {name} has a quantity below 1")
                continue

            # `price` and `unitPrice` both mean what the buyer pays per item.
            # `totalPrice` is the whole order, so it is divided out.
            raw_unit = entry.get("unitPrice")
            if raw_unit is None:
                raw_unit = entry.get("price")
            try:
                if raw_unit is not None:
                    unit = float(raw_unit)
                elif entry.get("totalPrice") is not None or entry.get("total") is not None:
                    total = float(entry.get("totalPrice") or entry.get("total"))
                    unit = total / quantity
                else:
                    raise TypeError("no price")
            except (TypeError, ValueError):
                errors.append(f"{where}: {name} has no usable price")
                continue
            if not unit > 0:
                errors.append(f"{where}: {name} has a non-positive price")
                continue

            seen = _parse_time(entry.get("seenAt") or entry.get("at"))
            order: dict[str, Any] = {
                "item": name,
                "unitPrice": round(unit, 4),
                "quantity": quantity,
                "buyer": (str(entry["buyer"]).strip() or None) if entry.get("buyer") else None,
                "note": str(entry["note"]) if entry.get("note") else None,
                "seenAt": _iso(seen) if seen else None,
            }
            out[name] = order
        return out

    def reload(self) -> bool:
        """Re-read both files. Returns True when anything actually changed.

        The guard keys off an explicit `_loaded` flag, not off the book being
        non-empty: an empty book is a perfectly stable state, and testing its
        truthiness would make it re-read and bump `revision` on every call -- which
        in turn would make the flip table look permanently stale and rebuild on
        every request.
        """
        stamps: dict[str, float] = {}
        for label, p in (("seed", self.seed_path), ("book", self.path)):
            stamps[label] = p.stat().st_mtime if p and p.exists() else 0.0
        if self._loaded and stamps == self._stamps:
            return False

        errors: list[str] = []
        seed, seed_err = self._read(self.seed_path)
        book, book_err = self._read(self.path)
        for err in (seed_err, book_err):
            if err:
                errors.append(err)

        merged: dict[str, dict[str, Any]] = {}
        merged.update(self._normalise(self._entries(seed), errors, "seed"))
        # the volume copy wins per item, so an order recorded at runtime survives a
        # redeploy of the image
        merged.update(self._normalise(self._entries(book), errors, "book"))

        ttl_hours = self.default_ttl_hours
        for doc in (seed, book):
            try:
                if doc.get("ttlHours") is not None:
                    ttl_hours = float(doc["ttlHours"])
            except (TypeError, ValueError):
                errors.append(f"ttlHours {doc.get('ttlHours')!r} is not a number")

        self._orders = merged
        self._ttl_hours = ttl_hours if ttl_hours > 0 else self.default_ttl_hours
        self._stamps = stamps
        self._loaded = True
        self._errors = errors
        self.revision += 1
        for err in errors:
            log.warning("order book: %s", err)
        log.info(
            "order book: %d order(s), ttl %.0fh, from %s",
            len(self._orders),
            self._ttl_hours,
            self.path if self.path and self.path.exists() else self.seed_path,
        )
        return True

    def refresh(self) -> bool:
        """Pick up edits to either file. Cheap: two stat calls."""
        return self.reload()

    # ---------------------------------------------------------------- reads ----
    def _decorate(self, order: dict[str, Any]) -> dict[str, Any]:
        seen = _parse_time(order.get("seenAt"))
        age = (_now() - seen).total_seconds() if seen else None
        ttl = self._ttl_hours * 3600.0
        stale = age is None or age > ttl
        return {
            **order,
            "ageSeconds": None if age is None else round(age, 1),
            "ttlSeconds": ttl,
            # an order whose age is unknown cannot be trusted as live either
            "stale": bool(stale),
        }

    def lookup(self, name: str) -> dict[str, Any] | None:
        """The recorded order for one item, or None when there is none."""
        self.refresh()
        order = self._orders.get(normalise_item(name))
        return self._decorate(order) if order else None

    def best(self, name: str) -> dict[str, Any] | None:
        """Alias for lookup -- the book keeps the best order per item."""
        return self.lookup(name)

    def all(self) -> list[dict[str, Any]]:
        self.refresh()
        return [self._decorate(o) for o in self._orders.values()]

    def size(self) -> int:
        return len(self._orders)

    # ---------------------------------------------------------------- writes ----
    def _write_doc(self, doc: dict[str, Any]) -> None:
        if self.path is None:
            raise RuntimeError("no writable order book path is configured")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)

    def put(
        self,
        item: str,
        unit_price: float,
        quantity: int | None = 1,
        buyer: str | None = None,
        note: str | None = None,
        seen_at: str | None = None,
    ) -> dict[str, Any]:
        """Record (or replace) the best known order for one item.

        Replaces rather than appends: the point of the book is the best live offer
        for an item, and two orders for the same item at different prices would
        just be a slower way to store the higher one.
        """
        name = normalise_item(item)
        if not name:
            raise ValueError("item is required")
        try:
            unit = float(unit_price)
        except (TypeError, ValueError) as exc:
            raise ValueError("price must be a number") from exc
        if not unit > 0:
            raise ValueError("price must be greater than zero")
        if quantity is None:
            qty = 1
        else:
            try:
                qty = int(quantity)
            except (TypeError, ValueError) as exc:
                raise ValueError("quantity must be a whole number") from exc
        if qty < 1:
            raise ValueError("quantity must be at least 1")

        with self._lock:
            doc, _ = self._read(self.path)
            entries = {k: v for k, v in doc.items() if k in ("ttlHours", "version")}
            current = doc.get("orders")
            orders = dict(current) if isinstance(current, dict) else {}
            if not isinstance(current, dict):
                # the file was in list form, or absent; keep whatever was there
                for order in self._normalise(self._entries(doc), [], "book").values():
                    orders[order["item"]] = {
                        k: v for k, v in order.items() if k != "item"
                    }
            orders[name] = {
                "price": round(unit, 4),
                "quantity": qty,
                "buyer": (str(buyer).strip() or None) if buyer else None,
                "note": str(note) if note else None,
                "seenAt": seen_at or _iso(_now()),
            }
            entries["orders"] = orders
            entries.setdefault("ttlHours", self._ttl_hours)
            self._write_doc(entries)
            self._stamps = {}
            self.reload()
        got = self.lookup(name)
        assert got is not None
        return got

    def drop(self, item: str) -> bool:
        """Forget one item's order. Returns True when something was removed."""
        name = normalise_item(item)
        if not name:
            return False
        with self._lock:
            doc, _ = self._read(self.path)
            current = doc.get("orders")
            orders = dict(current) if isinstance(current, dict) else {}
            if name not in orders:
                return False
            del orders[name]
            doc["orders"] = orders
            doc.setdefault("ttlHours", self._ttl_hours)
            self._write_doc(doc)
            self._stamps = {}
            self.reload()
        return True

    # ---------------------------------------------------------------- meta ----
    def snapshot(self) -> dict[str, Any]:
        orders = self.all()
        fresh = [o for o in orders if not o["stale"]]
        return {
            "orders": len(orders),
            "fresh": len(fresh),
            "stale": len(orders) - len(fresh),
            "ttlHours": self._ttl_hours,
            "bookPath": str(self.path) if self.path else None,
            "bookExists": bool(self.path and self.path.exists()),
            "seedPath": str(self.seed_path) if self.seed_path else None,
            "writable": self.path is not None,
            "errors": self._errors,
            "revision": self.revision,
        }


def default_book() -> OrderBook:
    """The order book as configured by the environment."""
    from . import config

    return OrderBook(
        path=config.ORDERS_PATH,
        seed_path=config.ORDERS_SEED_PATH,
        ttl_hours=config.ORDERS_TTL_HOURS,
    )


__all__ = ["OrderBook", "default_book", "normalise_item", "DEFAULT_TTL_HOURS"]
