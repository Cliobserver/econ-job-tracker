"""AERE Career Center — the public web list that mirrors many RESECON job announcements."""
from __future__ import annotations

import re
from datetime import datetime

import requests
from lxml import html

from ..geo import us_state
from ..models import Job, Location

URL = "https://www.aere.org/career-center"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}


def fetch(session=None, raw: bytes | None = None) -> list[Job]:
    if raw is None:
        s = session or requests.Session()
        r = s.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        raw = r.content
    return parse(raw)


def _date(s: str):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s or "")
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return datetime(y, mo, d).date().isoformat()
    except ValueError:
        return None


def _location(text: str) -> Location:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return Location()
    if len(parts) >= 2 and us_state(parts[-1]):
        return Location(city=parts[-2] if len(parts) >= 2 else "", state=us_state(parts[-1]), country="United States")
    if us_state(parts[-1]):
        return Location(state=us_state(parts[-1]), country="United States")
    if len(parts) >= 2:
        return Location(city=parts[-2], country=parts[-1])
    return Location(country=parts[-1])


def parse(raw: bytes) -> list[Job]:
    doc = html.fromstring(raw)
    jobs = []
    # Listings are <li>/<p> blocks: "<a>Title</a>, Employer ... Location ... Posted MM/DD/YY".
    for node in doc.xpath("//li[.//a[starts-with(@href,'http')]] | //p[.//a[starts-with(@href,'http')]]"):
        text = re.sub(r"\s+", " ", node.text_content()).strip()
        if "Posted" not in text:
            continue
        a = node.xpath(".//a[starts-with(@href,'http')]")[0]
        link = a.get("href")
        if "aere.org" in link and "career" in link:
            continue
        title_emp = re.sub(r"\s+", " ", a.text_content()).strip()
        rest = text.replace(title_emp, "", 1).strip(" ,-–—")
        posted_m = re.search(r"Posted\s+(\d{1,2}/\d{1,2}/\d{2,4})", rest)
        posted = _date(posted_m.group(1)) if posted_m else None
        rest = re.sub(r"\(?Posted\s+\d{1,2}/\d{1,2}/\d{2,4}\)?\.?", "", rest).strip(" ,.-–—()")
        # Title/employer are often "Title, Employer" or "Title - Employer".
        m = re.match(r"^(.*?)(?:\s[-–—]\s|,\s)(.+)$", title_emp)
        title, employer = (m.group(1).strip(), m.group(2).strip()) if m else (title_emp, "")
        if not employer and rest:
            emp_m = re.match(r"^([^,]+?(?:University|College|Institute|Bank|Foundation|Agency|Laboratory|Center)[^,]*)", rest)
            if emp_m:
                employer = emp_m.group(1).strip()
                rest = rest.replace(employer, "", 1).strip(" ,")
        loc_text = rest
        jid = re.sub(r"[^a-z0-9]+", "-", (link or title_emp).lower())[:80]
        jobs.append(Job(
            source="aere",
            source_id=jid,
            url=link,
            title=title,
            institution=employer,
            section="",
            locations=[_location(loc_text)] if loc_text else [],
            categories=["Environmental"],
            deadline=None,
            posted=posted,
            full_text="",   # the list carries no description, so PhD requirement stays "unknown"
        ))
    return jobs
