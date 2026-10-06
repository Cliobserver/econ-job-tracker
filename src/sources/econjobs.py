"""Econ-Jobs.com — WP Job Manager RSS feed (newest listings) plus cached job pages for deadlines."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from html import unescape
from pathlib import Path

import requests
from lxml import etree as ET
from lxml import html

# The feed occasionally contains stray control characters; recover instead of failing the source.
XML_PARSER = ET.XMLParser(recover=True, huge_tree=True)

from ..cache import cached_detail
from ..extract import deadline_from_text
from ..geo import us_state
from ..models import Job, Location

FEED_URL = "https://www.econ-jobs.com/?feed=job_feed&posts_per_page=100"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
NS = {"content": "http://purl.org/rss/1.0/modules/content/", "jl": "https://econ-jobs.com"}
CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "econjobs_feed.xml"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(s or "")).strip()


def _html_text(h: str) -> str:
    try:
        doc = html.fromstring(f"<div>{h}</div>")
        for p in doc.xpath(".//p|.//li|.//br|.//h2|.//h3"):
            p.tail = "\n" + (p.tail or "")
        return re.sub(r"[ \t]+", " ", doc.text_content()).strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", h)


def parse_feed(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw, XML_PARSER)
    out = []
    if root is None:
        return out
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        guid = it.findtext("guid") or link
        m = re.search(r"p=(\d+)", guid)
        jid = m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", link.lower())[-60:]
        content = it.find("content:encoded", namespaces=NS)
        body = _html_text(content.text if content is not None and content.text else (it.findtext("description") or ""))
        try:
            pub = datetime.strptime((it.findtext("pubDate") or "").strip(), "%a, %d %b %Y %H:%M:%S %z").date().isoformat()
        except ValueError:
            pub = None
        out.append({
            "id": jid, "url": link, "title": _clean(it.findtext("title")),
            "company": _clean(it.findtext("jl:company", namespaces=NS)),
            "location": _clean(it.findtext("jl:location", namespaces=NS)),
            "job_type": _clean(it.findtext("jl:job_type", namespaces=NS)),
            "category": _clean(it.findtext("jl:job_category", namespaces=NS)),
            "posted": pub, "text": body,
        })
    return out


def parse_detail(raw: bytes) -> dict:
    doc = html.fromstring(raw)
    out = {}
    body = doc.xpath('//div[contains(@class,"job_description")] | //div[contains(@class,"single_job_listing")]')
    if body:
        for p in body[0].xpath(".//p|.//li|.//br|.//h2|.//h3"):
            p.tail = "\n" + (p.tail or "")
        out["text"] = re.sub(r"[ \t]+", " ", body[0].text_content()).strip()
    page = _clean(doc.text_content())
    m = re.search(r"(?:Closes|Closing date|Application deadline|Deadline)\s*:?\s*([A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]+ \d{4})", page)
    if m:
        out["closes"] = m.group(1)
    return out


def _location(text: str) -> Location:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return Location()
    country = parts[-1]
    state = parts[-2] if len(parts) >= 2 else ""
    city = parts[-3] if len(parts) >= 3 else (parts[0] if len(parts) == 2 else "")
    if country.upper() in ("US", "USA", "UNITED STATES") or us_state(country):
        if us_state(country):
            state, country = country, "United States"
        country = "United States"
        state = us_state(state) or state
    return Location(city=city, state=state, country=country)


def _download_feed(s) -> bytes:
    """Fetch the RSS feed; on a bot wall / 429 fall back to the last good copy, else fail loudly."""
    err = ""
    try:
        r = s.get(FEED_URL, headers={**HEADERS, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5"},
                  timeout=60)
        if r.ok and b"<rss" in r.content[:3000]:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_bytes(r.content)
            return r.content
        err = f"HTTP {r.status_code}, {'HTML page' if b'<html' in r.content[:500].lower() else 'unexpected body'}"
    except requests.RequestException as e:
        err = type(e).__name__
    if CACHE_FILE.exists():
        print(f"[econjobs] live feed unavailable ({err}); using cached feed", file=sys.stderr)
        return CACHE_FILE.read_bytes()
    raise RuntimeError(f"Econ-Jobs feed unavailable: {err}")


def fetch(session=None, raw_feed: bytes | None = None, raw_details: dict | None = None) -> list[Job]:
    s = session or requests.Session()
    if raw_feed is None:
        raw_feed = _download_feed(s)
    budget = [40]
    jobs = []
    for it in parse_feed(raw_feed):
        detail = cached_detail(s, "econjobs", it["id"], it["url"], parse_detail, headers=HEADERS,
                               offline=raw_details, budget=budget)
        text = detail.get("text") or it["text"]
        deadline = deadline_from_text(text)
        if not deadline and detail.get("closes"):
            deadline = deadline_from_text("deadline " + detail["closes"])
        section = it["job_type"]
        if re.search(r"academic", it["job_type"] + " " + it["category"], re.I):
            section = "Academic"
        jobs.append(Job(
            source="econjobs",
            source_id=it["id"],
            url=it["url"],
            title=it["title"],
            institution=it["company"],
            section=section,
            locations=[_location(it["location"])] if it["location"] else [],
            categories=[c.strip() for c in it["category"].split(",") if c.strip()],
            deadline=deadline,
            posted=it["posted"],
            full_text=text,
        ))
    return jobs
