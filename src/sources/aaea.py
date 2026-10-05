"""AAEA Job Board (aaea.execinc.com) — server-rendered list + posting pages.

Posting pages only render inside a session that has visited the board first (otherwise the
server bounces back to the list), so one requests.Session is used for the whole run.
"""
from __future__ import annotations

import re
from datetime import datetime

import requests
from lxml import html

from ..cache import cached_detail
from ..extract import deadline_from_text
from ..geo import us_state
from ..models import Job, Location

BOARD_URL = "https://aaea.execinc.com/edibo/JobBoard"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
DESC_ID = "ctl01_ctl00_CphBody_CphWizardBody_ctl00_ctl01_ctl00_Value"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _date(s: str):
    try:
        return datetime.strptime(_clean(s), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def parse_board(raw: bytes) -> list[dict]:
    doc = html.fromstring(raw)
    out = []
    for li in doc.xpath('//ul[contains(@class,"jobboard")]/li'):
        a = li.xpath('.//a[contains(@href,"ViewPosting")]')
        if not a:
            continue
        url = a[0].get("href")
        m = re.search(r"SubmissionId=(\d+)", url)
        if not m:
            continue
        title = _clean(" ".join(li.xpath('.//span[contains(@class,"positiontitle")]//text()')))
        employer = _clean(" ".join(li.xpath('.//strong//text()')))
        posted = _date(" ".join(li.xpath('.//div[contains(@class,"topright")]//text()')))
        # Location is the bare text after the <strong> employer line.
        tail = [t for t in li.xpath("text()") if _clean(t)]
        location = _clean(tail[-1]) if tail else ""
        out.append({"id": m.group(1), "url": url, "title": title, "employer": employer,
                    "posted": posted, "location": location})
    return out


def parse_posting(raw: bytes) -> dict:
    doc = html.fromstring(raw)
    node = doc.xpath(f'//*[@id="{DESC_ID}"]')
    if not node:
        return {}
    for br in node[0].xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    for p in node[0].xpath(".//p|.//div|.//li"):
        p.tail = "\n" + (p.tail or "")
    text = re.sub(r"[ \t]+", " ", node[0].text_content()).strip()
    links = [l.rstrip(".,") for l in re.findall(r"https?://[^\s<>\"')\]]+", text) if not re.search(r"execinc|aaea\.org", l)]
    # Prefer the URL that follows "apply", else the last URL in the ad (usually the application portal).
    apply = [l for l in links if re.search(r"apply[^.]{0,60}" + re.escape(l), text, re.I)]
    if not apply and links:
        apply = [links[-1]]
    fields = {}
    for lab in doc.xpath('//*[contains(@class,"ControlLabel")]'):
        name = _clean(lab.text_content())
        val = _clean(lab.getparent().text_content()).replace(name, "", 1).strip()
        if name in ("City", "State/Province", "Country"):
            fields[name] = val
    return {"text": text, "apply": apply[:2], **fields}


def _location(listing_loc: str, detail: dict) -> Location:
    city, state, country = detail.get("City", ""), detail.get("State/Province", ""), detail.get("Country", "")
    if not country and listing_loc:
        parts = [p.strip() for p in listing_loc.split(",") if p.strip()]
        if parts:
            country = parts[-1]
            state = parts[-2] if len(parts) >= 2 else ""
            city = parts[-3] if len(parts) >= 3 else ""
    if country.upper() in ("US", "USA", "UNITED STATES"):
        country = "United States"
        state = us_state(state) or state
    return Location(city=city, state=state, country=country)


def fetch(session=None, raw_board: bytes | None = None, raw_postings: dict | None = None) -> list[Job]:
    s = session or requests.Session()
    if raw_board is None:
        r = s.get(BOARD_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        raw_board = r.content
    listings = parse_board(raw_board)
    budget = [60]
    jobs = []
    for it in listings:
        detail = cached_detail(s, "aaea", it["id"], it["url"], parse_posting,
                               headers={**HEADERS, "Referer": BOARD_URL},
                               offline=raw_postings, budget=budget)
        text = detail.get("text", "")
        jobs.append(Job(
            source="aaea",
            source_id=it["id"],
            url=it["url"],
            title=it["title"],
            institution=it["employer"],
            section="",
            locations=[_location(it["location"], detail)],
            categories=["Agricultural"],
            deadline=deadline_from_text(text),
            posted=it["posted"],
            requirements=[f"Apply: {l}" for l in detail.get("apply", [])],
            full_text=text,
        ))
    return jobs
