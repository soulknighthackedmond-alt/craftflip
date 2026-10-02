"""Is the 10-point confidence drop caused by my edit, or by the data?

Scores the same live flip dicts with the committed confidence.py (from git) and the
working-tree one, so the only variable is the code.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8801"
ITEMS = ["bamboo_block", "bone_meal", "diamond", "dried_kelp_block", "iron_door"]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    old_src = subprocess.run(
        ["git", "show", "HEAD:app/confidence.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    tmp = Path(tempfile.mkdtemp()) / "old_confidence.py"
    tmp.write_text(old_src, encoding="utf-8")

    # the old module's package-relative imports, if any, resolve against the repo
    sys.path.insert(0, str(REPO))
    old = load("old_confidence", tmp)
    new = load("new_confidence", REPO / "app" / "confidence.py")

    print(f"{'item':<20} {'old':>5} {'new':>5}  verdict")
    moved_by_code = 0
    for item in ITEMS:
        d = json.load(urllib.request.urlopen(f"{base}/api/crafts/{item}", timeout=120))
        flip = d.get("flip") or {}
        sell = d.get("sellPrice")
        if not flip:
            print(f"{item:<20}   --    --  no flip")
            continue
        age, ttl = 30.0, 600.0
        o = old.score(flip, sell, index_age=age, index_ttl=ttl)["confidence"]
        n = new.score(flip, sell, index_age=age, index_ttl=ttl)["confidence"]
        verdict = "same" if o == n else "CHANGED BY CODE"
        if o != n:
            moved_by_code += 1
        print(f"{item:<20} {o:>5} {n:>5}  {verdict}")
        if o != n:
            of = {f["key"]: f["score"] for f in old.score(flip, sell, index_age=age, index_ttl=ttl)["confidenceFactors"]}
            nf = {f["key"]: f["score"] for f in new.score(flip, sell, index_age=age, index_ttl=ttl)["confidenceFactors"]}
            for k in of:
                if of[k] != nf.get(k):
                    print(f"      {k}: {of[k]} -> {nf.get(k)}")

    print()
    print(
        "no code-caused movement — the drop is data (index/sales state), not my edit"
        if moved_by_code == 0
        else f"{moved_by_code} row(s) moved because of the code — fix before shipping"
    )
    return 0 if moved_by_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
