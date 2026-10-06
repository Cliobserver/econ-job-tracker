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
from .health import NOTES
from .extract import claude_extract, claude_enabled
from .fields import field_tags, is_ag_env, tags_from_body
from .filters import position_type, screen, phd_required, start_year
from .geo import geo_tags
from .models import Location
from .sources import joe, ejm, chronicle, substack, gmail, aere, aaea, inomics, econjobs

# Sources whose postings are free text: run the optional Claude extraction on them.
UNSTRUCTURED = {"chronicle", "substack", "gmail", "aaea", "inomics", "econjobs"}

try:
    TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # Windows without the tzdata package: fall back to local time
    TZ = None


def llm_fill(job) -> None:
    """Fill gaps in an unstructured posting from Claude's extraction (no-op when disabled)."""
    if job.source not in UNSTRUCTURED or not claude_enabled():
        return
    data = claude_extract(job.title, job.institution, job.full_text, job.key)
    if not data:
        return
    if data.get("application_deadline") and not job.deadline:
        job.deadline = data["application_deadline"]
    if data.get("start_date") and not job.start_date_text:
        job.start_date_text = data["start_date"]
    if data.get("phd_required") is True and not job.degree_required:
        job.degree_required = "Doctorate"
    elif data.get("phd_required") is False and not job.degree_required:
        job.degree_required = "Not doctorate"
    if data.get("country") or data.get("state_or_region") or data.get("city"):
        job.locations = [Location(city=data.get("city") or "", state=data.get("state_or_region") or "",
                                  country=data.get("country") or (job.locations[0].country if job.locations else ""))]
    if data.get("salary") and not job.salary:
        job.salary = data["salary"]
    for f in data.get("fields") or []:
        if f and f not in job.categories:
            job.categories.append(f)
    for m in data.get("application_materials") or []:
        if m and m not in job.requirements:
            job.requirements.append(m)
    if data.get("position_type") and not job.section:
        job.section = data["position_type"]


def enrich(job) -> dict:
    llm_fill(job)
    if job.source in UNSTRUCTURED and not job.categories:
        # No JEL codes on these boards: mine the full text for field keywords.
        job.categories = tags_from_body(job.full_text[:6000])
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
    """Merge a cluster of the same posting into one record; structured boards win on fields."""
    rank = {"joe": 0, "ejm": 1, "chronicle": 2, "inomics": 3, "aaea": 4, "econjobs": 5, "substack": 6, "aere": 7, "gmail": 8}
    cluster = sorted(cluster, key=lambda j: rank.get(j.source, 9))
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
    def offline_chronicle():
        feeds = [p.read_bytes() for p in sorted(offline_dir.glob("chronicle_feed*.xml"))]
        details = {p.stem.split("_")[-1]: p.read_bytes() for p in offline_dir.glob("chronicle_detail_*.html")}
        return chronicle.fetch(raw_feeds=feeds, raw_details=details)

    sources = [
        ("joe", lambda: joe.fetch(session) if offline_dir is None
         else joe.fetch(raw=(offline_dir / "joe.xml").read_bytes())),
        ("ejm", lambda: ejm.fetch(session) if offline_dir is None
         else ejm.fetch(raw_pages=[p.read_bytes() for p in sorted(offline_dir.glob("ejm*.html"))])),
        ("chronicle", lambda: chronicle.fetch(session) if offline_dir is None else offline_chronicle()),
        ("substack", lambda: substack.fetch(session) if offline_dir is None
         else substack.fetch(raw=(offline_dir / "substack.xml").read_bytes())),
        ("aere", lambda: aere.fetch(session) if offline_dir is None
         else aere.fetch(raw=(offline_dir / "aere.html").read_bytes())),
        ("gmail", lambda: gmail.fetch(session) if offline_dir is None
         else gmail.fetch(raw_messages=[p.read_bytes() for p in sorted(offline_dir.glob("gmail_*.eml"))])),
        ("aaea", lambda: aaea.fetch(session) if offline_dir is None
         else aaea.fetch(raw_board=(offline_dir / "aaea_board.html").read_bytes(),
                         raw_postings={p.stem.split("_")[-1]: p.read_bytes() for p in offline_dir.glob("aaea_post_*.html")})),
        ("inomics", lambda: inomics.fetch(session) if offline_dir is None
         else inomics.fetch(raw_pages=[p.read_bytes() for p in sorted(offline_dir.glob("inomics_list*.html"))],
                            raw_details={p.stem.split("_")[-1]: p.read_bytes() for p in offline_dir.glob("inomics_job_*.html")})),
        ("econjobs", lambda: econjobs.fetch(session) if offline_dir is None
         else econjobs.fetch(raw_feed=(offline_dir / "econjobs_feed.xml").read_bytes(), raw_details={})),
    ]
    for name, fn in sources:
        try:
            got = fn()
            jobs += got
            status = "ok" + (f" ({NOTES[name]})" if name in NOTES else "")
            health[name] = {"count": len(got), "status": status}
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
    failed = [name for name, h in health.items() if h["status"] != "ok"]
    merged = store.merge(store.load(), fresh, today, failed_sources=failed)
    store.save(merged)
    render.write_data_json(merged, health, today)
    render.write_readme(merged, health, today)
    passing = sum(1 for j in merged["jobs"] if j["status"] == "active" and j["passes_filter"])
    print(f"{len(jobs)} raw -> {len(fresh)} unique; {passing} active & passing filter.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
