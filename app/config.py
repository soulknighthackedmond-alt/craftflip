"""craftflip configuration. Every knob is an env var with a sane default."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent

UPSTREAM_BASE = os.getenv("DONUT_API_BASE", "https://api.donut.auction").rstrip("/")

PORT = int(os.getenv("PORT", "8789"))

# How long a built market index stays usable before a background refresh. A full
# refresh costs a few hundred upstream requests, so this is deliberately unhurried.
INDEX_TTL_SECONDS = float(os.getenv("INDEX_TTL_SECONDS", "600"))

# How long a computed flip table is served before it is recomputed from the index.
# Recomputation is pure arithmetic over the cached index, so this costs no upstream
# requests -- it exists so the "age" the UI shows stays honest.
FLIPS_TTL_SECONDS = float(os.getenv("FLIPS_TTL_SECONDS", "30"))

# DonutSMP's cut on a completed auction sale, as a percentage of the sale price.
# 0 until a real figure is supplied.
DONUT_FEE_PERCENT = float(os.getenv("DONUT_FEE_PERCENT", "0"))

# Gap between upstream requests during an index refresh. Kept deliberately slow so
# a full refresh never looks like an attack to api.donut.auction.
REQUEST_SPACING_SECONDS = float(os.getenv("REQUEST_SPACING_SECONDS", "0.25"))

# Hard ceiling on upstream requests in a single refresh. A full refresh of the
# vanilla recipe set needs a few hundred; this stops a pathological run.
MAX_REQUESTS_PER_REFRESH = int(os.getenv("MAX_REQUESTS_PER_REFRESH", "1400"))

# Where the recipe dataset and the flip-history log live.
DATA_DIR = os.getenv("DATA_DIR", str(ROOT_DIR / "data"))
RECIPES_PATH = os.getenv("RECIPES_PATH", str(ROOT_DIR / "data" / "recipes.json"))

# Flip history
HISTORY_TOP_N = int(os.getenv("HISTORY_TOP_N", "200"))
HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "14"))

# Built SPA, served by the same process.
WEB_DIST = os.getenv("WEB_DIST", str(ROOT_DIR / "web" / "dist"))
