"""Chronicle of Higher Education jobs — RSS feeds plus per-job JSON-LD detail pages.

The RSS items carry title, employer, salary line and a location string but no deadline.
Each job page embeds a schema.org JobPosting with description, datePosted, validThrough
and a structured address, so new jobs are fetched once and cached under data/cache/chronicle.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from lxml import html as lxml_html

from ..extract import deadline_from_text
from ..geo import us_state
from ..models import Job, Location

FEEDS = [
    "https://jobs.chronicle.com/jobsrss/?PositionType=12",     # Economics faculty
    "https://jobs.chronicle.com/jobsrss/?Keywords=economist",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "chronicle"
MAX_PAGES = 20
DETAIL_DELAY = 0.4   # seconds between detail-page requests
MAX_NEW_DETAILS = 400


def _job_id(url: str) -> str:
    m = re.search(r"/job/(\d+)/", url)
    return m.group(1) if m else ""


def _clean_url(url: str) -> str:
    return re.sub(r"\?.*$", "", url)


def fetch_feed_items(session, feed_url: str) -> list[dict]:
    items = []
    for page in range(1, MAX_PAGES + 1):
        r = session.get(f"{feed_url}&Page={page}", headers=HEADERS, timeout=60)
        r.raise_for_status()
        page_items = parse_feed(r.content)
        if not page_items:
            break
        items += page_items
        if len(page_items) < 20:
            break
    return items


def parse_feed(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        link = _clean_url((it.findtext("link") or "").strip())
        jid = _job_id(link)
        if not jid:
            continue
        title = (it.findtext("title") or "").strip()
        desc = (it.findtext("description") or "").strip()
        lines = [l.strip() for l in desc.splitlines() if l.strip()]
        salary = lines[0].rstrip(":") if lines and lines[0].endswith(":") else ""
        location = lines[-1] if len(lines) >= 2 else ""
        employer, _, pos_title = title.partition(": ")
        out.append({"id": jid, "url": link, "title": pos_title or title, "employer": employer if pos_title else "",
                    "salary": salary, "location": location,
                    "pub": (it.findtext("pubDate") or "").strip()})
    return out


def parse_detail(raw: bytes) -> dict:
    """Pull the schema.org JobPosting out of a job page."""
    m = re.search(rb'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', raw, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(1).decode("utf-8", "ignore"))
    except json.JSONDecodeError:
        return {}
    if d.get("@type") != "JobPosting":
        return {}
    desc_html = d.get("description") or ""
    try:
        text = lxml_html.fromstring(f"<div>{desc_html}</div>").text_content()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", desc_html)
    text = re.sub(r"[ \t]+", " ", text).strip()
    loc = {}
    jl = d.get("jobLocation") or []
    if isinstance(jl, dict):
        jl = [jl]
    if jl and isinstance(jl[0], dict):
        loc = jl[0].get("address") or {}
    return {
        "title": d.get("title", ""),
        "employer": (d.get("hiringOrganization") or {}).get("name", ""),
        "description": text,
        "date_posted": d.get("datePosted"),
        "valid_through": d.get("validThrough"),
        "city": loc.get("addressLocality", ""),
        "region": loc.get("addressRegion", ""),
        "country": loc.get("addressCountry", ""),
        "employment_type": d.get("employmentType", ""),
    }


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%b %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


COUNTRY_CODES = {"US": "United States", "GB": "United Kingdom", "UK": "United Kingdom", "CA": "Canada", "CN": "China",
                 "AU": "Australia", "DE": "Germany", "FR": "France", "NL": "Netherlands", "HK": "Hong Kong",
                 "SG": "Singapore", "JP": "Japan", "KR": "South Korea", "AE": "United Arab Emirates", "QA": "Qatar",
                 "SA": "Saudi Arabia", "IT": "Italy", "ES": "Spain", "CH": "Switzerland", "IE": "Ireland",
                 "NZ": "New Zealand", "IN": "India", "TW": "Taiwan", "MX": "Mexico", "BR": "Brazil", "ZA": "South Africa",
                 "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland", "BE": "Belgium", "AT": "Austria",
                 "PT": "Portugal", "IL": "Israel", "TR": "Turkey", "KZ": "Kazakhstan", "CL": "Chile", "CO": "Colombia"}


def _location(detail: dict, rss_location: str) -> Location:
    city, region, country = detail.get("city", ""), detail.get("region", ""), detail.get("country", "")
    if not country and rss_location:
        # RSS form: "Massachusetts, United States" or "China (CN)"
        parts = [p.strip() for p in rss_location.split(",")]
        country = re.sub(r"\s*\([A-Z]{2}\)$", "", parts[-1])
        if len(parts) >= 2 and not region:
            region = parts[-2]
    country = COUNTRY_CODES.get(country.upper(), country) if len(country) == 2 else country
    if country == "United States" and region and not us_state(region):
        region = us_state(region) or region
    return Location(city=city, state=region, country=country)


def _section(title: str, text: str) -> str:
    t = title.lower()
    if "postdoc" in t or "post-doc" in t:
        return "Postdoc"
    if re.search(r"visiting|adjunct|lecturer|instructor|teaching professor|professor of practice|professional practice", t):
        return "Other Academic (Visiting or Temporary)"
    if re.search(r"professor|tenure|chair|faculty", t) or "tenure" in text.lower():
        return "Full-Time Academic (Permanent, Tenure Track or Tenured)"
    return "Other"


def fetch(session=None, raw_feeds=None, raw_details=None) -> list[Job]:
    """raw_feeds: list of RSS bytes (offline). raw_details: {job_id: html bytes} (offline)."""
    s = session or requests.Session()
    items: dict[str, dict] = {}
    if raw_feeds is not None:
        for raw in raw_feeds:
            for it in parse_feed(raw):
                items.setdefault(it["id"], it)
    else:
        for feed in FEEDS:
            for it in fetch_feed_items(s, feed):
                items.setdefault(it["id"], it)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    fetched = 0
    for jid, it in items.items():
        detail = {}
        cache = CACHE_DIR / f"{jid}.json"
        if raw_details is not None and jid in raw_details:
            detail = parse_detail(raw_details[jid])
        elif cache.exists():
            detail = json.loads(cache.read_text(encoding="utf-8"))
        elif raw_details is None and fetched < MAX_NEW_DETAILS:
            try:
                r = s.get(it["url"], headers=HEADERS, timeout=60)
                if r.ok:
                    detail = parse_detail(r.content)
                    cache.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
            except requests.RequestException:
                detail = {}
            fetched += 1
            time.sleep(DETAIL_DELAY)
        text = detail.get("description", "")
        title = detail.get("title") or it["title"]
        deadline = deadline_from_text(text) or _iso(detail.get("valid_through"))
        jobs.append(Job(
            source="chronicle",
            source_id=jid,
            url=it["url"],
            title=title,
            institution=detail.get("employer") or it["employer"],
            section=_section(title, text),
            locations=[_location(detail, it["location"])],
            categories=[],
            deadline=deadline,
            posted=_iso(detail.get("date_posted")) or _iso(it["pub"]),
            salary=it["salary"][:80] if it["salary"].lower() not in ("competitive", "competitive salary", "not specified") else "",
            full_text=text,
        ))
    return jobs
