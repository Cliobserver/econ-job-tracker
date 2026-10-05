"""Orchestrator: fetch -> enrich -> dedup -> merge store -> render.

Usage:
    python -m src.run                 # live fetch
    python -m src.run --offline DIR   # parse cached files in DIR (joe.xml, ejm_1.html, ...)
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import store, render
from .dedup import dedup
from .fields import field_tags, is_ag_env
from .filters import position_type, screen, phd_required, start_year
from .geo import geo_tags
from .sources import joe, ejm

try:
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # Windows without the tzdata package: fall back to local time
    TZ = None


def enrich(job) -> dict:
    ptype = position_type(job)
    passes, reasons = screen(job, ptype)
    fields = field_tags(job)
    return {
        "title": job.title,
        "institution": job.institution,
        "department": job.department,
        "type": ptype,
        "section": job.section,
        "fields": fields,
        "ag_env": is_ag_env(fields),
        "geo": geo_tags(job.locations),
        "location_text": "; ".join(l.text() for l in job.locations),
        "jel_codes": job.jel_codes,
        "categories": job.categories,
        "deadline": job.deadline,
        "posted": job.posted,
        "start_date_text": job.start_date_text,
        "start_year": start_year(job),
        "degree_required": job.degree_required,
        "phd_required": phd_required(job, ptype),
        "requirements": job.requirements,
        "salary": job.salary,
        "summary": (job.full_text or "")[:600],
        "passes_filter": passes,
        "exclusion_reasons": reasons,
        "sources": [{"source": job.source, "url": job.url, "id": job.source_id}],
        "source_keys": [job.key],
    }


def canonical(cluster) -> dict:
    """Merge a cluster of the same posting into one record; JOE wins on structured fields."""
    cluster = sorted(cluster, key=lambda j: 0 if j.source == "joe" else 1)
    recs = [enrich(j) for j in cluster]
    base = recs[0]
    for r in recs[1:]:
        base["sources"] += r["sources"]
        base["source_keys"] += r["source_keys"]
        for key in ("fields", "categories", "requirements"):
            for v in r[key]:
                if v not in base[key]:
                    base[key].append(v)
        for key in ("deadline", "posted", "start_date_text", "degree_required", "department", "salary"):
            if not base[key] and r[key]:
                base[key] = r[key]
        if base["start_year"] is None:
            base["start_year"] = r["start_year"]
        if base["phd_required"] is None:
            base["phd_required"] = r["phd_required"]
        if base["geo"]["primary"] == "Unknown":
            base["geo"], base["location_text"] = r["geo"], r["location_text"]
        if not base["summary"]:
            base["summary"] = r["summary"]
        # A posting passes if either copy passes (sources differ in detail).
        if r["passes_filter"] and not base["passes_filter"]:
            base["passes_filter"], base["exclusion_reasons"] = True, []
    base["ag_env"] = is_ag_env(base["fields"])
    if "Unspecified" in base["fields"] and len(base["fields"]) > 1:
        base["fields"].remove("Unspecified")
    return base


def fetch_all(offline_dir: Path | None):
    session = requests.Session()
    jobs, health = [], {}
    sources = [
        ("joe", lambda: joe.fetch(session) if offline_dir is None
         else joe.fetch(raw=(offline_dir / "joe.xml").read_bytes())),
        ("ejm", lambda: ejm.fetch(session) if offline_dir is None
         else ejm.fetch(raw_pages=[p.read_bytes() for p in sorted(offline_dir.glob("ejm*.html"))])),
    ]
    for name, fn in sources:
        try:
            got = fn()
            jobs += got
            health[name] = {"count": len(got), "status": "ok"}
            print(f"[{name}] {len(got)} postings", file=sys.stderr)
        except Exception as e:  # one broken board must not sink the run
            health[name] = {"count": 0, "status": f"error: {type(e).__name__}: {e}"[:200]}
            traceback.print_exc()
    return jobs, health


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=Path, default=None, help="directory of cached source files")
    ap.add_argument("--today", default=None, help="override run date (yyyy-mm-dd)")
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else datetime.now(TZ).date()
    jobs, health = fetch_all(args.offline)
    if not jobs:
        print("No postings fetched from any source; leaving store untouched.", file=sys.stderr)
        return 1
    clusters = dedup(jobs)
    fresh = [canonical(c) for c in clusters]
    merged = store.merge(store.load(), fresh, today)
    store.save(merged)
    render.write_data_json(merged, health, today)
    render.write_readme(merged, health, today)
    passing = sum(1 for j in merged["jobs"] if j["status"] == "active" and j["passes_filter"])
    print(f"{len(jobs)} raw -> {len(fresh)} unique; {passing} active & passing filter.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
