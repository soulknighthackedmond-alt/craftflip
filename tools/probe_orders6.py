"""Dump the official DonutSMP OpenAPI spec and inspect the auction endpoints:
what does the `auction` filter accept, and does the response schema carry a
buy/bid side?
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "*/*"}


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def main() -> None:
    st, html = get("https://api.donutsmp.net/v1/")
    urls = re.findall(r"url:\s*[\"']([^\"']+)[\"']", html)
    print("spec url in page:", urls)
    spec = None
    for c in urls + ["/v1/doc.json", "/v1/swagger.json", "/v1/openapi.json"]:
        if c.startswith("http"):
            url = c
        elif c.startswith("/"):
            url = "https://api.donutsmp.net" + c
        else:
            url = "https://api.donutsmp.net/v1/" + c
        st, body = get(url)
        if st == 200 and body.lstrip().startswith("{"):
            spec = json.loads(body)
            print(f"loaded spec from {url} ({len(body)} bytes)")
            break
    if not spec:
        print("no spec")
        return

    with open("tools/donutsmp_openapi.json", "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)

    for p in ("/v1/auction/list/{page}", "/v1/auction/transactions/{page}"):
        op = spec["paths"][p]["get"]
        print(f"\n=== GET {p} ===")
        print("summary:", op.get("summary"))
        print("description:", (op.get("description") or "")[:600])
        for q in op.get("parameters", []):
            print(f"  param {q.get('name')} required={q.get('required')} schema={json.dumps(q.get('schema'))}")
            if "enum" in (q.get("schema") or {}):
                print(f"     ENUM: {q['schema']['enum']}")
        ref = (op.get("responses", {}).get("200", {}).get("content", {})
               .get("application/json", {}).get("schema", {}).get("$ref"))
        print("  response ref:", ref)
        if ref:
            name = ref.split("/")[-1]
            schema = spec["components"]["schemas"].get(name, {})
            print("  schema:", json.dumps(schema)[:1500])

    print("\n=== every schema name ===")
    print(sorted(spec.get("components", {}).get("schemas", {})))

    print("\n=== security schemes ===")
    print(json.dumps(spec.get("components", {}).get("securitySchemes", {}), indent=1)[:600])
    print("global security:", spec.get("security"))


if __name__ == "__main__":
    main()
