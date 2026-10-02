"""How much a row can be trusted.

Nothing in this ledger is a quote. The price index cannot see the whole market
(api.donut.auction search is substring-matched and hard-capped at 25 results with
no pagination), a material without a live listing is costed from a smoothed market
value, and the sell side is either a fixed server price or the middle of a handful
of completed sales. So each row carries a confidence score instead of pretending
those inputs are equivalent.

The score is a weighted blend of the signals that actually bear on whether a flip
is real, and the breakdown is returned alongside it so a row can be argued with
rather than just believed.
"""

from __future__ import annotations

import math
from typing import Any

# Weights sum to 1.0. The cost basis and the sell side dominate because a wrong
# price on either end moves the profit by more than any of the statistical signals.
WEIGHTS = {
    "costBasis": 0.34,
    "sellBasis": 0.26,
    "salesDepth": 0.12,
    "agreement": 0.16,
    "freshness": 0.12,
}

# A row whose materials cannot all be bought right now is a guess about the cost,
# whatever the sell side says, so it never reads as high confidence no matter how
# good the price readings look.
UNBUYABLE_CEILING = 0.60

LABELS = {
    "costBasis": "cost basis",
    "sellBasis": "sell price",
    "salesDepth": "sales depth",
    "agreement": "price agreement",
    "freshness": "freshness",
}

# How much a fixed /sell base price is trusted, by where it came from. A value read
# in game with /worth is the real thing; a community value may have drifted.
SELL_SOURCE_SCORE = {"in-game": 1.0, "wiki": 0.9, "community": 0.7}


def _closeness(a: float | None, b: float | None) -> float | None:
    """How close two prices are, 1.0 identical and falling off in log space.

    Ratio-based, not difference-based: being $1k out on a $10k item is a much
    bigger disagreement than being $1k out on a $1M one.
    """
    if not a or not b or a <= 0 or b <= 0:
        return None
    return 1.0 / (1.0 + abs(math.log(a / b)))


def _sell_basis(flip: dict[str, Any], sell: dict[str, Any] | None) -> tuple[float, str]:
    """Score the sell side, and say which side it came from."""
    if sell and sell.get("base"):
        score = SELL_SOURCE_SCORE.get(str(sell.get("source") or ""), 0.6)
        return score, f"fixed /sell base {sell['base']:,.0f} ({sell.get('source') or 'unattributed'})"

    n = int(flip.get("dumpSales") or 0)
    if n >= 8:
        return 0.55, f"{n} recent sales"
    if n >= 4:
        return 0.45, f"{n} recent sales"
    if n >= 1:
        return 0.30, f"only {n} recent sale(s)"
    return 0.0, "no sell side at all"


def _agreement(flip: dict[str, Any], sell: dict[str, Any] | None) -> tuple[float, str]:
    """Do the independent price readings agree with each other?"""
    pairs = [
        ("index vs sales", flip.get("output", {}).get("unitPrice"), flip.get("dumpUnitPrice")),
    ]
    if sell and sell.get("base"):
        pairs.append(("index vs /sell", flip.get("output", {}).get("unitPrice"), sell.get("base")))
        pairs.append(("sales vs /sell", flip.get("dumpUnitPrice"), sell.get("base")))

    scored = [(name, _closeness(a, b)) for name, a, b in pairs]
    got = [(name, v) for name, v in scored if v is not None]
    if not got:
        return 0.5, "nothing to cross-check"
    mean = sum(v for _, v in got) / len(got)
    worst = min(got, key=lambda kv: kv[1])
    return mean, f"{len(got)} reading(s); weakest {worst[0]} at {worst[1]:.2f}"


def _cost_basis(flip: dict[str, Any]) -> tuple[float, str]:
    """Share of materials buyable right now, docked for cheapest-of-many guesses."""
    total = int(flip.get("materialsTotal") or 0)
    listed = int(flip.get("materialsListed") or 0)
    if total <= 0:
        return 0.0, "no materials"
    ratio = listed / total
    # a material resolved from a tag is the cheapest of several candidates, which is
    # an optimistic reading of the slot rather than a price you can rely on
    ingredients = flip.get("ingredients") or []
    loose = sum(1 for c in ingredients if (c.get("optionsConsidered") or 1) > 1)
    penalty = 0.25 * (loose / total)
    score = max(0.0, ratio - penalty)
    detail = f"{listed}/{total} materials listed"
    if loose:
        detail += f"; {loose} resolved from a tag"
    return score, detail


def _sales_depth(flip: dict[str, Any]) -> tuple[float, str]:
    n = int(flip.get("dumpSales") or 0)
    if n <= 0:
        return 0.0, "no recorded sales"
    # saturating: the difference between 1 and 5 sales matters far more than 20 vs 25
    return 1.0 - math.exp(-n / 6.0), f"{n} sales on record"


def _freshness(flip: dict[str, Any], index_age: float | None, ttl: float) -> tuple[float, str]:
    if index_age is None or ttl <= 0:
        return 0.0, "index age unknown"
    score = max(0.0, 1.0 - (index_age / ttl))
    return score, f"index {index_age:,.0f}s old (ttl {ttl:,.0f}s)"


def label_for(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.25:
        return "low"
    return "very low"


def score(
    flip: dict[str, Any],
    sell: dict[str, Any] | None = None,
    index_age: float | None = None,
    index_ttl: float = 600.0,
) -> dict[str, Any]:
    """Blend the signals into a 0-100 confidence for one row."""
    parts = {
        "costBasis": _cost_basis(flip),
        "sellBasis": _sell_basis(flip, sell),
        "salesDepth": _sales_depth(flip),
        "agreement": _agreement(flip, sell),
        "freshness": _freshness(flip, index_age, index_ttl),
    }
    total = sum(WEIGHTS[k] * parts[k][0] for k in WEIGHTS)
    capped = total
    if flip.get("estimated"):
        capped = min(total, UNBUYABLE_CEILING)
    factors = [
        {
            "key": k,
            "label": LABELS[k],
            "score": round(parts[k][0], 4),
            "weight": WEIGHTS[k],
            "contribution": round(WEIGHTS[k] * parts[k][0] * 100, 1),
            "detail": parts[k][1],
        }
        for k in WEIGHTS
    ]
    if flip.get("estimated"):
        factors.append(
            {
                "key": "unbuyable",
                "label": "not buyable",
                "score": 0.0,
                "weight": 0.0,
                "contribution": 0.0,
                "detail": (
                    "some materials have no live listing, so the cost is a market-value "
                    f"estimate; confidence is capped at {int(UNBUYABLE_CEILING * 100)}%"
                ),
            }
        )
    return {
        "confidence": int(round(capped * 100)),
        "confidenceLabel": label_for(capped),
        "confidenceFactors": factors,
    }
