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

# The sell side (what an item has actually sold for) costs one upstream request per
# craftable output, so it runs on its own much slower cycle instead of slowing the
# price refresh down. An item has no dump price until its turn comes round. At a
# 1s gap a full pass over the ~875 outputs takes about 15 minutes, which leaves the
# whole thing well inside an hour-long TTL -- roughly 0.25 requests/second average.
SALES_TTL_SECONDS = float(os.getenv("SALES_TTL_SECONDS", "3600"))
SALES_SPACING_SECONDS = float(os.getenv("SALES_SPACING_SECONDS", "1.0"))
SALES_MAX_PER_CYCLE = int(os.getenv("SALES_MAX_PER_CYCLE", "600"))

# Where the recipe dataset and the flip-history log live.
DATA_DIR = os.getenv("DATA_DIR", str(ROOT_DIR / "data"))
RECIPES_PATH = os.getenv("RECIPES_PATH", str(ROOT_DIR / "data" / "recipes.json"))

# The fixed /sell base prices. Two files are merged: the seed shipped in the image,
# and an optional copy in DATA_DIR (the mounted volume) whose entries win, so values
# read in game with /worth survive a redeploy. Both are reloaded when they change.
SELL_PRICES_SEED_PATH = os.getenv(
    "SELL_PRICES_SEED_PATH", str(ROOT_DIR / "data" / "sell_prices.json")
)
SELL_PRICES_PATH = os.getenv("SELL_PRICES_PATH", str(Path(DATA_DIR) / "sell_prices.json"))
# Your own /sellmulti level, 1.0x by default. The table can override it per item.
SELL_MULTIPLIER = float(os.getenv("SELL_MULTIPLIER", "1.0"))

# Player buy orders -- the instasell side that /sell routes into. No public feed
# exists for them (see app/orders.py), so this is a table the operator fills from
# what /orders shows in game. Two files are merged: a seed in the image, and an
# optional copy in DATA_DIR whose entries win, so orders survive a redeploy. The
# volume copy is also where the write API records new orders.
ORDERS_SEED_PATH = os.getenv("ORDERS_SEED_PATH", str(ROOT_DIR / "data" / "orders.json"))
ORDERS_PATH = os.getenv("ORDERS_PATH", str(Path(DATA_DIR) / "orders.json"))
# How long a recorded order is treated as live. A buyer's offer can be filled or
# withdrawn at any moment, so an order nobody has re-checked for a day is not
# evidence of a buyer -- it still shows, flagged, but it is not easy money.
ORDERS_TTL_HOURS = float(os.getenv("ORDERS_TTL_HOURS", "24"))

# Flip history
HISTORY_TOP_N = int(os.getenv("HISTORY_TOP_N", "200"))
HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "14"))

# Built SPA, served by the same process.
WEB_DIST = os.getenv("WEB_DIST", str(ROOT_DIR / "web" / "dist"))
