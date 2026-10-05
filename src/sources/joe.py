"""AEA Job Openings for Economists (JOE) — official XML export."""
from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree as ET

import requests

from ..models import Job, Location

XML_URL = "https://www.aeaweb.org/joe/resultset_output.php?mode=full_xml"
LISTING_URL = "https://www.aeaweb.org/joe/listing.php?JOE_ID={id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (econ-job-tracker; personal job search)"}


def fetch(session=None, raw: bytes | None = None) -> list[Job]:
    if raw is None:
        s = session or requests.Session()
        r = s.get(XML_URL, headers=HEADERS, timeout=120)
        r.raise_for_status()
        raw = r.content
    return parse(raw)


def _date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _requirements(full_text: str) -> list[str]:
    m = re.search(r"Application Requirements:\s*(.*)$", full_text, flags=re.S | re.I)
    if not m:
        return []
    lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
    return lines[:12]


def _unescape(s: str) -> str:
    return (s or "").replace("&amp;amp;", "&").replace("&amp;", "&").strip()


def parse(raw: bytes) -> list[Job]:
    root = ET.fromstring(raw)
    jobs = []
    for year in root.iter("year"):
        for issue in year.iter("issue"):
            for p in issue.iter("position"):
                jobs.append(_parse_position(p, year.get("joe_year_ID", ""), issue.get("joe_issue_ID", "")))
    return jobs


def _parse_position(p, year: str, issue: str) -> Job:
    if True:  # keep indentation shallow for the body below
        jp_id = p.get("jp_id", "").strip()
        # Canonical listing URL is e.g. listing.php?JOE_ID=2026-02_111477855
        joe_ref = f"{year}-{int(issue):02d}_{jp_id}" if year and issue.isdigit() else jp_id
        full_text = _unescape(p.findtext("jp_full_text"))
        locs = [Location(city=(l.findtext("city") or "").strip().title(),
                         state=(l.findtext("state") or "").strip(),
                         country=(l.findtext("country") or "").strip())
                for l in p.iter("location")]
        jels = [(j.findtext("jc_code") or "").strip() for j in p.iter("jel_class")]
        keywords = [k.strip() for k in _unescape(p.findtext("jp_keywords")).splitlines() if k.strip()]
        return Job(
            source="joe",
            source_id=jp_id,
            url=LISTING_URL.format(id=joe_ref),
            title=_unescape(p.findtext("jp_title")),
            institution=_unescape(p.findtext("jp_institution")),
            department=" / ".join(x for x in [_unescape(p.findtext("jp_division")),
                                              _unescape(p.findtext("jp_department"))] if x),
            section=(p.findtext("jp_section") or "").strip(),
            locations=locs,
            jel_codes=[c for c in jels if c],
            categories=keywords,
            deadline=_date(p.findtext("jp_application_deadline")),
            posted=None,
            requirements=_requirements(full_text),
            salary=(p.findtext("jp_salary_range") or "").strip(),
            full_text=full_text,
        )
