"""Tiny on-disk cache for per-job detail pages so each posting is downloaded once."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent / "data" / "cache"


def cached_detail(session, source: str, key: str, url: str, parse, *, headers=None, delay=0.4,
                  offline: dict | None = None, budget: list | None = None) -> dict:
    """Return parse(html) for `url`, memoised at data/cache/<source>/<key>.json.

    offline: optional {key: raw_bytes} used instead of the network (tests / --offline runs).
    budget:  optional single-element list [remaining_fetches]; decremented per live fetch so one
             run never hammers a site (returns {} once exhausted; next run continues).
    """
    path = ROOT / source / f"{key}.json"
    if offline is not None:
        if key in offline:
            return parse(offline[key])
        return {}
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if budget is not None:
        if budget[0] <= 0:
            return {}
        budget[0] -= 1
    try:
        r = session.get(url, headers=headers, timeout=60)
        detail = parse(r.content) if r.ok else {}
    except requests.RequestException as e:
        print(f"[{source}] detail fetch failed for {url}: {type(e).__name__}", file=sys.stderr)
        detail = {}
    if detail:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    time.sleep(delay)
    return detail
