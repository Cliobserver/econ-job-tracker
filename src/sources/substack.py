"""Applied Econ Jobs (Substack newsletter by Zoë Plakias) — RSS feed.

Every job is its own post titled "Position at Organization (Country)"; weekly digests just
embed those posts and are skipped. The post body is the (lightly edited) posting text, so
deadline / start / salary / degree are extracted from text.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

import requests
from lxml import html as lxml_html

from ..extract import regex_extract
from ..health import note
from ..models import Job, Location

FEED_URL = "https://appliedeconjobs.substack.com/feed"
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "substack_feed.xml"

# Substack fronts its feed with Cloudflare, which rejects datacenter IPs (GitHub runners)
# unless the request looks like a browser. Try a browser-shaped request, then a public
# read-through proxy, then the last copy we saved.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://appliedeconjobs.substack.com/",
}
PROXIES = [
    "https://api.allorigins.win/raw?url=" + quote(FEED_URL, safe=""),
    "https://r.jina.ai/" + FEED_URL,
]


def _looks_like_feed(raw: bytes) -> bool:
    return b"<rss" in raw[:2000] or b"<feed" in raw[:2000]


def download(session) -> bytes:
    attempts = [(FEED_URL, BROWSER_HEADERS)] + [(p, {"User-Agent": BROWSER_HEADERS["User-Agent"]}) for p in PROXIES]
    errors = []
    for url, headers in attempts:
        try:
            r = session.get(url, headers=headers, timeout=60)
            if r.ok and _looks_like_feed(r.content):
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_bytes(r.content)
                return r.content
            errors.append(f"{url.split('?')[0]} -> HTTP {r.status_code}")
        except requests.RequestException as e:
            errors.append(f"{url.split('?')[0]} -> {type(e).__name__}")
    if CACHE_FILE.exists():
        print(f"[substack] live fetch failed ({'; '.join(errors)}); using cached feed", file=sys.stderr)
        note("substack", "live fetch failed; cached feed")
        return CACHE_FILE.read_bytes()
    raise RuntimeError("Substack feed unavailable: " + "; ".join(errors))


def fetch(session=None, raw: bytes | None = None) -> list[Job]:
    if raw is None:
        raw = download(session or requests.Session())
    return parse(raw)


def split_title(title: str) -> tuple[str, str, str]:
    """'Postdoc in X at Univ of Y (Germany)' -> ('Postdoc in X', 'Univ of Y', 'Germany')."""
    t = re.sub(r"\s+", " ", title).strip()
    country = ""
    m = re.search(r"\(([^()]+)\)\s*$", t)
    if m and len(m.group(1)) <= 40 and not re.search(r"\d", m.group(1)):
        country = m.group(1).strip()
        t = t[: m.start()].strip()
    if " at " in t:
        pos, _, inst = t.rpartition(" at ")
    else:
        pos, inst = t, ""
    return pos.strip(), inst.strip(), country


def _text(html: str) -> str:
    try:
        doc = lxml_html.fromstring(f"<div>{html}</div>")
        for br in doc.xpath(".//br"):
            br.tail = "\n" + (br.tail or "")
        for p in doc.xpath(".//p|.//li|.//h1|.//h2|.//h3|.//h4"):
            p.tail = "\n" + (p.tail or "")
        txt = doc.text_content()
    except Exception:
        txt = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", txt).strip()


def _apply_links(html: str) -> list[str]:
    links = re.findall(r'href="(https?://[^"]+)"', html)
    good = [l for l in links if not re.search(r"substack\.com|mailto:|wikipedia|usajobs\.gov/HiringPath|opm\.gov|usastaffing", l)]
    return good[:3]


def parse(raw: bytes) -> list[Job]:
    root = ET.fromstring(raw)
    jobs = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title or re.match(r"(weekly|monthly) digest", title, re.I):
            continue
        link = (it.findtext("link") or "").strip()
        pid = link.rstrip("/").rsplit("/", 1)[-1] or title
        content = it.find("content:encoded", NS)
        html = (content.text if content is not None else "") or (it.findtext("description") or "")
        text = _text(html)
        pos, inst, country = split_title(title)
        ex = regex_extract(text)
        pub = None
        try:
            pub = datetime.strptime((it.findtext("pubDate") or "").strip(), "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
        except ValueError:
            pass
        state = ex["us_state"] if not country else ""
        loc = Location(state=state, country=country or "United States")
        apply_links = _apply_links(html)
        jobs.append(Job(
            source="substack",
            source_id=pid,
            url=link,
            title=pos,
            institution=inst,
            section="",
            locations=[loc],
            categories=[],
            deadline=ex["deadline"],
            posted=pub,
            start_date_text=ex["start_date_text"],
            degree_required=ex["degree_required"] if ex["degree_required"] == "Doctorate" else "",
            requirements=[f"Apply: {l}" for l in apply_links],
            salary=ex["salary"],
            full_text=text,
        ))
    return jobs
