"""The fixed /sell price table.

DonutSMP's /sell pays a server-defined base price per item, multiplied by the
player's own per-item multiplier (1.0x, rising to 3.0x through repeated selling of
that item; see /sellmulti in game). Unlike the Auction House, the payout does not
depend on another player turning up -- which is exactly why it is worth pricing.

The server does not publish those base prices in bulk. donut.auction's order data
is retired, no live order-book feed survives (lootseller.io retired 2026-09-29;
donutsmp.finance is a frozen 2026-06-25 snapshot whose crawler reports
running:false), and the wiki confirms eight values out of a catalogue that is not
public. The /shop prices are what the server charges, not what it pays, so they
cannot stand in.

So the table is a file the operator owns. It ships with every value that can be
sourced, is merged with an optional volume copy that wins, and is reloaded when
either file changes -- so a price read in game with /worth can be added without a
rebuild. An item with no entry here has no fixed sell price, and callers fall back
to what the item has actually sold for.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("craftflip.sellprices")

SOURCES = {"in-game", "wiki", "community"}


class SellPrices:
    """Base /sell prices, merged from the shipped table and an optional volume copy."""

    def __init__(
        self,
        path: str | Path | None = None,
        seed_path: str | Path | None = None,
        multiplier: float = 1.0,
    ) -> None:
        self.path = Path(path) if path else None
        self.seed_path = Path(seed_path) if seed_path else None
        self.default_multiplier = float(multiplier or 1.0)
        self._items: dict[str, dict[str, Any]] = {}
        self._multiplier = self.default_multiplier
        self._stamps: dict[str, float] = {}
        self._errors: list[str] = []
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
    def _normalise(items: dict[str, Any], errors: list[str], where: str) -> dict[str, dict[str, Any]]:
        """Accept a bare number or an object per item, and drop anything unusable."""
        out: dict[str, dict[str, Any]] = {}
        for raw_name, entry in (items or {}).items():
            name = str(raw_name).strip().lower().replace(" ", "_").replace("-", "_")
            if not name:
                continue
            if isinstance(entry, (int, float)):
                entry = {"base": entry}
            if not isinstance(entry, dict):
                errors.append(f"{where}: {name} is neither a number nor an object")
                continue
            try:
                base = float(entry.get("base"))
            except (TypeError, ValueError):
                errors.append(f"{where}: {name} has no numeric base price")
                continue
            if base <= 0:
                errors.append(f"{where}: {name} has a non-positive base price")
                continue
            source = str(entry.get("source") or "").strip().lower()
            if source and source not in SOURCES:
                errors.append(f"{where}: {name} has unknown source {source!r}")
                source = ""
            item: dict[str, Any] = {"base": base, "source": source or None}
            mult = entry.get("mult")
            if isinstance(mult, (int, float)) and mult > 0:
                item["mult"] = float(mult)
            note = entry.get("note")
            if note:
                item["note"] = str(note)
            out[name] = item
        return out

    def reload(self) -> bool:
        """Re-read both files. Returns True when anything actually changed."""
        stamps: dict[str, float] = {}
        for label, p in (("seed", self.seed_path), ("table", self.path)):
            stamps[label] = p.stat().st_mtime if p and p.exists() else 0.0
        if stamps == self._stamps and self._items:
            return False

        errors: list[str] = []
        seed, seed_err = self._read(self.seed_path)
        table, table_err = self._read(self.path)
        for err in (seed_err, table_err):
            if err:
                errors.append(err)

        merged: dict[str, dict[str, Any]] = {}
        merged.update(self._normalise(seed.get("items") or {}, errors, "seed"))
        # the volume copy wins per item, so operator edits survive a redeploy
        merged.update(self._normalise(table.get("items") or {}, errors, "table"))

        multiplier = self.default_multiplier
        for doc in (seed, table):
            try:
                if doc.get("multiplier") is not None:
                    multiplier = float(doc["multiplier"])
            except (TypeError, ValueError):
                errors.append(f"multiplier {doc.get('multiplier')!r} is not a number")

        self._items = merged
        self._multiplier = multiplier if multiplier > 0 else self.default_multiplier
        self._stamps = stamps
        self._errors = errors
        self.revision += 1
        if errors:
            for err in errors:
                log.warning("sell price table: %s", err)
        log.info(
            "sell price table: %d item(s), multiplier %.2fx, from %s",
            len(self._items),
            self._multiplier,
            self.path if self.path and self.path.exists() else self.seed_path,
        )
        return True

    def refresh(self) -> bool:
        """Pick up edits to either file. Cheap: two stat calls."""
        return self.reload()

    # ---------------------------------------------------------------- reads ----
    def lookup(self, name: str) -> dict[str, Any] | None:
        """Base price and effective payout for one item, or None when unlisted."""
        self.refresh()
        item = self._items.get(str(name).strip().lower().replace(" ", "_"))
        if not item:
            return None
        mult = item.get("mult", self._multiplier)
        return {
            "base": item["base"],
            "multiplier": mult,
            "payout": round(item["base"] * mult, 4),
            "source": item.get("source"),
            "note": item.get("note"),
        }

    def payout(self, name: str) -> float | None:
        got = self.lookup(name)
        return got["payout"] if got else None

    def size(self) -> int:
        return len(self._items)

    def snapshot(self) -> dict[str, Any]:
        return {
            "items": self.size(),
            "multiplier": self._multiplier,
            "tablePath": str(self.path) if self.path else None,
            "tableExists": bool(self.path and self.path.exists()),
            "seedPath": str(self.seed_path) if self.seed_path else None,
            "sources": sorted({str(v.get("source")) for v in self._items.values() if v.get("source")}),
            "errors": self._errors,
            "revision": self.revision,
        }


def default_table() -> SellPrices:
    """The table as configured by the environment."""
    from . import config

    return SellPrices(
        path=config.SELL_PRICES_PATH,
        seed_path=config.SELL_PRICES_SEED_PATH,
        multiplier=config.SELL_MULTIPLIER,
    )
