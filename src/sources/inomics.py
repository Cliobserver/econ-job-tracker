"""INOMICS job listings — paginated HTML list plus JSON-LD on each job page."""
from __future__ import annotations

import json
import re
from datetime import datetime

import requests
from lxml import html

from ..cache import cached_detail
from ..extract import deadline_from_text
from ..models import Job, Location

LIST_URL = "https://inomics.com/top/jobs?page={page}"
BASE = "https://inomics.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
MAX_PAGES = 8
# Badge text -> (section label, degree hint). Degree "Masters" marks student-level roles so the
# PhD screen excludes them.
TYPE_MAP = [
    (r"postdoc", "Postdoc", ""),
    (r"professor|lecturer", "Faculty", ""),
    (r"senior researcher|group leader", "Full-Time Nonacademic", ""),
    (r"researcher|analyst|practitioner|consultant|industry|administration", "Full-Time Nonacademic", ""),
    (r"phd candidate|scholarship|traineeship|graduate|research assistant|technician|internship", "Student", "Masters"),
]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _date_dmy(s: str):
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return None


def parse_list(raw: bytes) -> list[dict]:
    doc = html.fromstring(raw)
    out = []
    for a in doc.xpath('//a[contains(@class,"post-link")]'):
        href = a.get("href") or ""
        m = re.search(r"/job/.*-(\d+)$", href)
        if not m:
            continue
        title = _clean(" ".join(a.xpath(".//h2//text()")))
        badge = _clean(" ".join(a.xpath('.//span[contains(@class,"type-badge")]//text()')))
        contents = [s.get("content") for s in a.xpath(".//span[@content]")]
        closing = next((c for c in contents if c and c.upper().startswith("APPLICATION CLOSING DATE")), "")
        posted = next((_date_dmy(c) for c in contents if c and re.fullmatch(r"\d{2}-\d{2}-\d{4}", c)), None)
        employer = _clean(" ".join(a.xpath('.//span[contains(@class,"bold")][not(contains(@class,"location"))]//text()')))
        location = _clean(" ".join(a.xpath('.//span[contains(@class,"location")]//text()')))
        remote = bool(a.xpath('.//li[contains(@class,"attendance")][contains(.,"Remote")]'))
        out.append({"id": m.group(1), "url": BASE + href, "title": title, "badge": badge,
                    "closing": closing.split(":", 1)[-1].strip(), "posted": posted,
                    "employer": employer, "location": location, "remote": remote})
    return out


def parse_detail(raw: bytes) -> dict:
    doc = html.fromstring(raw)
    out = {}
    for s in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            d = json.loads(s.text_content())
        except json.JSONDecodeError:
            continue
        if d.get("@type") != "JobPosting":
            continue
        out.setdefault("title", d.get("title") or d.get("name"))
        org = d.get("hiringOrganization") or {}
        out.setdefault("employer", org.get("name", "") if isinstance(org, dict) else "")
        if d.get("industry"):
            out["industry"] = d["industry"]
        loc = d.get("jobLocation") or {}
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        if isinstance(addr, dict) and (addr.get("addressLocality") or addr.get("addressCountry")):
            out.setdefault("city", addr.get("addressLocality", ""))
            out.setdefault("region", addr.get("addressRegion", ""))
            out.setdefault("country", addr.get("addressCountry", ""))
        if d.get("datePosted"):
            out.setdefault("date_posted", str(d["datePosted"])[:10].replace("/", "-"))
        if d.get("validThrough"):
            vt = str(d["validThrough"])[:10].replace("/", "-")
            # Some listings carry a stale validThrough from an earlier posting cycle; ignore
            # anything that is not after the posting date.
            if vt > (out.get("date_posted") or ""):
                out["valid_through"] = vt
    body = doc.xpath('//div[contains(@class,"post-description")]')
    if body:
        for p in body[0].xpath(".//p|.//li|.//br|.//h2|.//h3"):
            p.tail = "\n" + (p.tail or "")
        out["text"] = re.sub(r"[ \t]+", " ", body[0].text_content()).strip()
    return out


def _location(listing_loc: str, detail: dict, remote: bool) -> Location:
    parts = [p.strip() for p in listing_loc.split(",") if p.strip()]
    city = detail.get("city") or (parts[0] if len(parts) >= 2 else "")
    country = detail.get("country") or (parts[-1] if parts else "")
    if isinstance(city, str) and "," in city:          # "Cairo, Egypt" style locality
        city, country = [x.strip() for x in city.rsplit(",", 1)]
    if remote and not country:
        country = "Remote"
    return Location(city=city or "", state=detail.get("region", "") if detail.get("region") != city else "",
                    country=country or "")


def _jel_from_industry(industry: str) -> list[str]:
    return re.findall(r"\(JEL ([A-Z]\d?)\)", industry or "")


def fetch(session=None, raw_pages: list[bytes] | None = None, raw_details: dict | None = None) -> list[Job]:
    s = session or requests.Session()
    pages = raw_pages
    if pages is None:
        pages = []
        for page in range(MAX_PAGES):
            r = s.get(LIST_URL.format(page=page), headers=HEADERS, timeout=60)
            r.raise_for_status()
            pages.append(r.content)
            if len(parse_list(r.content)) < 20:
                break
    items, seen = [], set()
    for raw in pages:
        for it in parse_list(raw):
            if it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
    budget = [120]
    jobs = []
    for it in items:
        detail = cached_detail(s, "inomics", it["id"], it["url"], parse_detail, headers=HEADERS,
                               offline=raw_details, budget=budget)
        text = detail.get("text", "")
        section, degree = "", ""
        for pat, sec, deg in TYPE_MAP:
            if re.search(pat, it["badge"], re.I):
                section, degree = sec, deg
                break
        posted = it["posted"] or detail.get("date_posted")
        deadline = deadline_from_text(text) or (_date_dmy(it["closing"]) if it["closing"] else None) \
            or detail.get("valid_through")
        if deadline and posted and deadline < posted:
            deadline = None
        jobs.append(Job(
            source="inomics",
            source_id=it["id"],
            url=it["url"],
            title=detail.get("title") or it["title"],
            institution=detail.get("employer") or it["employer"],
            section=section or it["badge"],
            locations=[_location(it["location"], detail, it["remote"])],
            jel_codes=_jel_from_industry(detail.get("industry", "")),
            categories=[c.strip() for c in re.split(r",", detail.get("industry", "")) if c.strip() and "JEL" not in c][:4],
            deadline=deadline,
            posted=posted,
            start_date_text="",
            degree_required=degree,
            full_text=text,
        ))
    return jobs
