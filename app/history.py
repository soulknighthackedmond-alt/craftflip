"""Flip history.

One compact line per index refresh, in /data/flips-YYYY-MM-DD.jsonl, so the table
shows whether a flip has been worth doing for days rather than for one snapshot.

Line shape: {"t": iso8601, "fee": 0.0, "n": 200, "f": {"<item>": [profit, margin]}}

Everything here degrades silently: if the volume is not mounted, or the disk is
read-only, history is simply unavailable and the live table is unaffected. It must
never be able to break the table.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("craftflip.history")


class FlipHistory:
    def __init__(self, data_dir: str, top_n: int = 200, retention_days: int = 14):
        self.dir = Path(data_dir)
        self.top_n = top_n
        self.retention_days = retention_days
        self.available = self._probe()
        self.last_error: str | None = None
        self.writes = 0

    def _probe(self) -> bool:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            probe = self.dir / ".craftflip-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("flip history unavailable (%s); continuing without it", self.last_error)
            return False

    def _path_for(self, when: datetime) -> Path:
        return self.dir / f"flips-{when.strftime('%Y-%m-%d')}.jsonl"

    def append(self, rows: list[dict[str, Any]], fee_percent: float = 0.0) -> bool:
        """Record the top N flips. Returns False (never raises) if it cannot."""
        if not self.available or not rows:
            return False
        now = datetime.now(timezone.utc)
        payload = {
            "t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fee": fee_percent,
            "n": min(self.top_n, len(rows)),
            "f": {
                r["item"]: [round(r["profit"], 2), round(r["margin"], 6)]
                for r in rows[: self.top_n]
            },
        }
        try:
            with self._path_for(now).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self.writes += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("flip history write failed (%s); continuing without it", self.last_error)
            return False

    def prune(self) -> int:
        """Drop day-files older than the retention window."""
        if not self.available:
            return 0
        cutoff = time.time() - self.retention_days * 86400
        removed = 0
        try:
            for p in self.dir.glob("flips-*.jsonl"):
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
                        removed += 1
                except OSError:
                    continue
        except Exception:  # noqa: BLE001
            return removed
        return removed

    def series(self, item_name: str, days: int | None = None) -> list[dict[str, Any]]:
        """Profit/margin over time for one item, oldest first."""
        if not self.available:
            return []
        days = days or self.retention_days
        cutoff = time.time() - days * 86400
        points: list[dict[str, Any]] = []
        try:
            files = sorted(self.dir.glob("flips-*.jsonl"))
        except Exception:  # noqa: BLE001
            return []
        for path in files:
            try:
                if path.stat().st_mtime < cutoff - 86400:
                    continue
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        hit = (rec.get("f") or {}).get(item_name)
                        if hit:
                            points.append(
                                {"at": rec.get("t"), "profit": hit[0], "margin": hit[1]}
                            )
            except OSError:
                continue
        points.sort(key=lambda p: p["at"] or "")
        return points

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "dir": str(self.dir),
            "topN": self.top_n,
            "retentionDays": self.retention_days,
            "writes": self.writes,
            "lastError": self.last_error,
        }
