"""EconJobMarket.org — public positions list (HTML)."""
from __future__ import annotations

import re
from datetime import datetime

import requests
from lxml import html

from ..geo import us_state
from ..models import Job, Location

LIST_URL = "https://econjobmarket.org/positions?page={page}"
HEADERS = {"User-Agent": "Mozilla/5.0 (econ-job-tracker; personal job search)"}
MAX_PAGES = 30
US_NAMES = {"UNITED STATES", "USA", "UNITED STATES OF AMERICA", "US", "U.S.", "U.S.A."}


def fetch(session=None, raw_pages=None) -> list[Job]:
    pages = raw_pages
    if pages is None:
        s = session or requests.Session()
        pages = []
        for page in range(1, MAX_PAGES + 1):
            r = s.get(LIST_URL.format(page=page), headers=HEADERS, timeout=60)
            r.raise_for_status()
            pages.append(r.content)
            if not re.search(rb"positions\?page=%d\b" % (page + 1), r.content):
                break
    jobs, seen = [], set()
    for raw in pages:
        for j in parse(raw):
            if j.source_id not in seen:
                seen.add(j.source_id)
                jobs.append(j)
    return jobs


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" . ")


def _date(s: str):
    s = _clean(s)
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", s)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %b %Y").date().isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def _detail_field(detail, label: str) -> str:
    for strong in detail.xpath(".//strong"):
        if _clean(strong.text_content()).lower().startswith(label.lower()):
            parent = strong.getparent()
            txt = parent.text_content().replace(strong.text_content(), "", 1)
            return _clean(txt)
    return ""


def _location(text: str) -> Location:
    """Parse strings like '8888 University Drive, Burnaby, BC, V5A 1S6, Canada'."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return Location()
    country = parts[-1]
    rest = [p for p in parts[:-1] if p.lower() != country.lower()]
    # Drop street addresses, postal codes, and numeric region codes.
    rest = [re.sub(r"\s*\d{5}(-\d{4})?$", "", p) for p in rest]
    rest = [p for p in rest if p and not re.search(r"\d", p)]
    city = state = ""
    if country.upper() in US_NAMES:
        country = "United States"
        idx = next((i for i in range(len(rest) - 1, -1, -1) if us_state(rest[i])), None)
        if idx is not None:
            state = rest[idx]
            city = rest[idx - 1] if idx >= 1 else ""
        elif rest:
            city = rest[-1]
    else:
        if len(rest) >= 2:
            state, city = rest[-1], rest[-2]
        elif rest:
            city = rest[-1]
    return Location(city=city, state=state, country=country)


def parse(raw: bytes) -> list[Job]:
    doc = html.fromstring(raw)
    jobs = []
    for a in doc.xpath('//a[contains(@class,"adBody")]'):
        pid = (a.get("name") or "").strip()
        if not pid.isdigit():
            continue
        title = _clean(a.text_content())
        card = a.getparent()
        while card is not None and "card" not in (card.get("class") or ""):
            card = card.getparent()
        if card is None:
            continue
        cols = card.xpath('./div[contains(@class,"row")]/div[contains(@class,"col-md-4")]')
        inst = _clean(cols[1].text_content()) if len(cols) >= 2 else ""
        col2 = card.xpath('./div[contains(@class,"row")]/div[contains(@class,"col-md-2")]')
        ptype = ""
        cats = []
        if col2:
            # Position type sits above the <hr>, field(s) below it.
            before = col2[0].xpath("./hr/preceding-sibling::text()") or col2[0].xpath("text()")
            ptype = _clean(" ".join(t for t in before if t.strip()))
            after = _clean(" ".join(t for t in col2[0].xpath("./hr/following-sibling::text()") if t.strip()))
            if after:
                cats.append(after)
        cats += [_clean(t) for t in card.xpath(f'.//div[@id="cats-{pid}"]/text()')]
        cats = [c for c in cats if c and c not in ("•", "•")]
        detail = card.xpath(f'.//div[@id="ad-{pid}"]')
        detail = detail[0] if detail else None
        deadline = None
        loc_text = degree = start = duration = body = ""
        reqs = []
        if detail is not None:
            loc_text = _detail_field(detail, "Location of job")
            degree = _detail_field(detail, "Degree required")
            start = _detail_field(detail, "Job start date")
            duration = _detail_field(detail, "Job duration")
            deadline = _date(_detail_field(detail, "Application deadline"))
            letters = _detail_field(detail, "Letters of reference required")
            if letters:
                reqs.append(f"Letters of reference: {letters}")
            body = _clean(" ".join(detail.xpath(".//p//text() | .//li//text() | .//h3//text()")))
        if not deadline:
            neg = card.xpath('.//span[contains(@class,"negative")]/text()')
            deadline = _date(neg[0]) if neg else None
        info = card.xpath('.//span[contains(@class,"bg-info")]/text()')
        posted = _date(info[0]) if info else None
        if not loc_text and cols:
            lines = [_clean(t) for t in cols[0].xpath("text()") if _clean(t)]
            loc_text = lines[0] if lines else ""
        jobs.append(Job(
            source="ejm",
            source_id=pid,
            url=f"https://econjobmarket.org/positions/{pid}",
            title=title,
            institution=inst,
            section=ptype,
            locations=[_location(loc_text)] if loc_text else [],
            categories=cats,
            deadline=deadline,
            posted=posted,
            start_date_text=start,
            degree_required=degree,
            requirements=reqs,
            full_text=body + (f" Duration: {duration}" if duration else ""),
        ))
    return jobs
