"""Persistent store: data/jobs.json keeps every posting ever seen with first/last-seen dates."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "data" / "jobs.json"
EXPIRE_AFTER_DAYS = 14   # not seen on any board for this long -> status "gone"


def load() -> dict:
    if STORE.exists():
        with STORE.open(encoding="utf-8") as f:
            return json.load(f)
    return {"updated": None, "jobs": []}


def save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=False)


def merge(existing: dict, fresh: list[dict], today: date) -> dict:
    """Merge today's canonical records into the store.

    Records match when they share any source key (e.g. "joe:123"). Matched records
    take today's content but keep their original first_seen date.
    """
    today_s = today.isoformat()
    by_key: dict[str, dict] = {}
    for rec in existing.get("jobs", []):
        for k in rec.get("source_keys", []):
            by_key[k] = rec

    seen_ids = set()
    merged: list[dict] = []
    for rec in fresh:
        olds = [by_key[k] for k in rec["source_keys"] if k in by_key]
        first_seen = min([o["first_seen"] for o in olds] + [today_s])
        rec["first_seen"] = first_seen
        rec["last_seen"] = today_s
        rec["status"] = "active"
        for o in olds:
            seen_ids.add(id(o))
        merged.append(rec)

    # Carry over records not seen today.
    for rec in existing.get("jobs", []):
        if id(rec) in seen_ids:
            continue
        last = date.fromisoformat(rec["last_seen"])
        rec["status"] = "gone" if (today - last).days > EXPIRE_AFTER_DAYS else "missing"
        merged.append(rec)

    merged.sort(key=lambda r: (r.get("deadline") or "9999-99-99", r["institution"]))
    return {"updated": today_s, "jobs": merged}
