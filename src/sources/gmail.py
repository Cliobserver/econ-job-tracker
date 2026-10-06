"""Gmail (IMAP) — job announcements arriving on mailing lists.

Reads the mailbox named by GMAIL_USER over IMAP and turns list e-mails that look like job
announcements into postings. Two ways to authenticate, checked in this order:

  1. App password:   GMAIL_USER + GMAIL_APP_PASSWORD
  2. OAuth refresh:  GMAIL_USER + GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN
                     (scope https://mail.google.com/, exchanged for an access token at run time)

Which e-mails count is driven by LIST_RULES below (List-Id / From / Subject patterns).
Processed Message-IDs are remembered in data/cache/gmail_seen.json so each e-mail is parsed once;
parsed postings are kept in data/cache/gmail_jobs.json so a run without credentials (e.g. a local
test) still has them.
"""
from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import requests
from lxml import html as lxml_html

from ..extract import regex_extract
from ..models import Job, Location

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"
SEEN_FILE = CACHE_DIR / "gmail_seen.json"
JOBS_FILE = CACHE_DIR / "gmail_jobs.json"
LOOKBACK_DAYS = 45
KEEP_DAYS = 120

# (rule name, regex matched against "List-Id | From | Subject")
LIST_RULES = [
    ("resecon", re.compile(r"resecon@listserv\.utk\.edu|RESECON", re.I)),
    ("cwae", re.compile(r"cwae@aaealist\.org|\[AAEA CWAE\]|\bCWAE\b", re.I)),
    ("aaea", re.compile(r"@aaealist\.org|\[AAEA [A-Z&-]+\]", re.I)),
    ("are-grads", re.compile(r"\[ARE Grads\]|are-grads", re.I)),
]
# Senders we already ingest elsewhere (Substack adapter) - skip to avoid double counting.
SKIP_FROM = re.compile(r"substack\.com|aeaweb\.org|econjobmarket\.org", re.I)

JOB_SUBJECT = re.compile(
    r"\b(position|professor|postdoc|post-doc|postdoctoral|fellow(?:ship)?|economist|opening|vacanc|hiring|"
    r"job|lecturer|researcher|scientist|analyst|faculty|tenure|search|recruit|opportunit|internship|PhD stud)",
    re.I)
NOT_JOB_SUBJECT = re.compile(
    r"\b(webinar|seminar|conference|call for (?:papers|abstracts|proposals)|cfp|workshop|newsletter|minutes|"
    r"business meeting|reminder: (?:webinar|seminar)|survey|election|nominations?|award|special issue|"
    r"registration|deadline extended: (?:call|cfp)|table of contents|panel|scheduling|mentorship|"
    r"scholars'? circle|nobel|summer school|short course|symposium|annual meeting|office hours|softball|"
    r"mentoring|learning experience|field trip|student travel|travel grant|"
    r"\bgame\b|party|potluck|happy hour|picnic|retreat|orientation|town hall|social|lunch|coffee)\b", re.I)
# When a subject also contains one of the words above, only these phrasings still count as a job.
STRONG_JOB_SUBJECT = re.compile(
    r"position announcement|job (?:opening|posting|announcement)|\bhiring\b|vacanc|openings? (?:in|at|for) [A-Z]|"
    r"\b(?:assistant|associate|full) professor|postdoc(?:toral)? (?:position|opening)|economist (?:position|opening|job)", re.I)
JOB_BODY = re.compile(r"\b(apply|application|applicants|candidates?|qualifications|salary|appointment)\b", re.I)
# The subscriber's own institution shows up in every forwarded message's signature; never
# treat it as the hiring institution unless it is in the subject line.
OWN_INSTITUTION = re.compile(os.environ.get("GMAIL_OWN_INSTITUTION", r"University of California|UC Davis"), re.I)
INST_RE = re.compile(
    r"\b(?:The )?((?:[A-Z][\w&.'-]+\s){0,4}(?:University|College|Institute|Bank|Laboratory|School|Council|Foundation|Centre|Center)"
    r"(?:\s(?:of|at|for)\s(?:the\s)?[A-Z][\w&.'-]+(?:\s[A-Z][\w&.'-]+){0,3})?|"
    r"USDA(?:['’]s)?[\w\s-]{0,40}?(?:Service|Office of (?:the )?Chief Economist|Office|Agency)|"
    r"Federal Reserve Bank of [A-Z][a-z]+(?: [A-Z][a-z]+)?)")


# --------------------------------------------------------------------------- auth / fetch

def configured() -> bool:
    u = os.environ.get("GMAIL_USER")
    return bool(u and (os.environ.get("GMAIL_APP_PASSWORD") or
                       (os.environ.get("GMAIL_CLIENT_ID") and os.environ.get("GMAIL_CLIENT_SECRET")
                        and os.environ.get("GMAIL_REFRESH_TOKEN"))))


def _access_token() -> str:
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["GMAIL_CLIENT_ID"],
        "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def connect() -> imaplib.IMAP4_SSL:
    user = os.environ["GMAIL_USER"]
    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    if os.environ.get("GMAIL_APP_PASSWORD"):
        conn.login(user, os.environ["GMAIL_APP_PASSWORD"])
    else:
        token = _access_token()
        auth = f"user={user}\x01auth=Bearer {token}\x01\x01"
        conn.authenticate("XOAUTH2", lambda _: auth.encode())
    return conn


def fetch_raw_messages(conn, since: date) -> list[bytes]:
    conn.select('"[Gmail]/All Mail"', readonly=True)
    criteria = f'(SINCE {since.strftime("%d-%b-%Y")})'
    typ, data = conn.search(None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()
    out = []
    # Fetch headers first, keep only list mail, then fetch bodies for those.
    for i in range(0, len(ids), 200):
        chunk = b",".join(ids[i:i + 200])
        typ, parts = conn.fetch(chunk, "(BODY.PEEK[HEADER.FIELDS (LIST-ID FROM SUBJECT MESSAGE-ID)])")
        if typ != "OK":
            continue
        wanted = []
        for part in parts:
            if not isinstance(part, tuple):
                continue
            hdr = part[1].decode("utf-8", "ignore")
            if match_rule(hdr) and not SKIP_FROM.search(hdr):
                m = re.match(rb"(\d+) ", part[0])
                if m:
                    wanted.append(m.group(1))
        for uid in wanted:
            typ, body = conn.fetch(uid, "(BODY.PEEK[])")
            if typ == "OK":
                for part in body:
                    if isinstance(part, tuple):
                        out.append(part[1])
    return out


def match_rule(header_blob: str) -> str | None:
    blob = header_blob.replace("\r\n ", " ")
    for name, rx in LIST_RULES:
        if rx.search(blob):
            return name
    return None


# --------------------------------------------------------------------------- parsing

def _html_to_text(h: str) -> str:
    try:
        doc = lxml_html.fromstring(f"<div>{h}</div>")
        for bad in doc.xpath(".//style|.//script"):
            bad.drop_tree()
        for br in doc.xpath(".//br"):
            br.tail = "\n" + (br.tail or "")
        for p in doc.xpath(".//p|.//div|.//li|.//tr|.//h1|.//h2|.//h3"):
            p.tail = "\n" + (p.tail or "")
        return doc.text_content()
    except Exception:
        return re.sub(r"<[^>]+>", " ", h)


def _body_text(msg: EmailMessage) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    text = ""
    if html_part is not None:
        text = _html_to_text(html_part.get_content())
    elif plain is not None:
        text = plain.get_content()
    text = text.replace("\r\n", "\n")
    # Forwarded mail: drop the forwarder's note and signature, keep the original announcement.
    fwd = re.search(r"\n\s*(?:-+\s*(?:Original Message|Forwarded message)\s*-+|Begin forwarded message:|From:\s.+\n\s*(?:Sent|Date):)", text)
    if fwd and len(text) - fwd.start() > 300:
        text = text[fwd.start():]
    # Drop list footers / unsubscribe boilerplate.
    text = re.split(r"\n_{10,}|\nTo unsubscribe|\nYou are receiving this|\n-- ?\n|\nThis message was sent to", text)[0]
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_subject(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip().replace("’", "'").replace("‘", "'")
    s = re.sub(r"^((re|fwd?|fw|aw)\s*:\s*|\[[^\]]+\]\s*)+", "", s, flags=re.I)
    s = re.sub(r"^((re|fwd?|fw)\s*:\s*|\[[^\]]+\]\s*)+", "", s, flags=re.I)
    return s.strip(" -:")


def _split_title(subject: str, text: str) -> tuple[str, str]:
    """'Assistant Professor in X at University of Y' -> (title, institution)."""
    s = subject
    m = re.search(r"^(.*?)\s+(?:at|@|-|–|—|\|)\s+(.+)$", s)
    if m and re.search(r"universit|college|school|institute|bank|department|lab|center|centre|foundation|"
                       r"agency|usda|epa|noaa|service|council|corporation|inc\b|llc|group", m.group(2), re.I):
        return m.group(1).strip(), m.group(2).strip()
    # "... Job At Iowa State", "openings at USDA" - only "at"; "in X" names a field, not an employer.
    m = re.search(r"\b(?:jobs?|positions?|openings?|postdoc\w*|professor\w*|economists?|fellow\w*)\s+at\s+((?:[A-Z][\w&.'-]+\s?){1,5})", s, re.I)
    if m and m.group(1)[0].isupper():
        return s, m.group(1).strip()
    m = re.match(r"^([A-Z][\w&.' -]{2,40}?):\s", s)       # "Monash: recruiting ..."
    if m and not re.search(r"fw|fwd|^re$|job|position|reminder|announcement|opening|opportunit|urgent|deadline|"
                           r"postdoc|professor|economist|hiring|vacanc|call", m.group(1), re.I):
        return s[m.end():].strip(), m.group(1).strip()
    # Otherwise the most-mentioned institution in the body, ignoring the subscriber's own.
    counts: dict[str, int] = {}
    for mm in INST_RE.finditer(text[:4000]):
        name = mm.group(1).strip(" .,")
        if OWN_INSTITUTION.search(name) or len(name) < 8:
            continue
        counts[name] = counts.get(name, 0) + 1
    if counts:
        return s, max(counts, key=lambda k: (counts[k], -text.find(k)))
    return s, ""


def is_job(subject: str, text: str) -> bool:
    if NOT_JOB_SUBJECT.search(subject):
        return bool(STRONG_JOB_SUBJECT.search(subject))
    if JOB_SUBJECT.search(subject):
        return True
    return bool(JOB_BODY.search(text[:3000])) and bool(STRONG_JOB_SUBJECT.search(text[:800]))


def parse_message(raw: bytes) -> dict | None:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    hdr = " | ".join(str(msg.get(h, "")) for h in ("List-Id", "From", "Subject"))
    rule = match_rule(hdr)
    if not rule or SKIP_FROM.search(str(msg.get("From", ""))):
        return None
    subject = _clean_subject(str(msg.get("Subject", "")))
    text = _body_text(msg)
    if not is_job(subject, text):
        return None
    mid = str(msg.get("Message-ID", "")).strip() or f"<{hash(raw)}@local>"
    try:
        sent = email.utils.parsedate_to_datetime(str(msg.get("Date"))).date().isoformat()
    except Exception:
        sent = None
    title, inst = _split_title(subject, text)
    ex = regex_extract(text)
    links = re.findall(r"https?://[^\s<>\"')\]]+", text)
    apply_links = [l for l in links if not re.search(r"unsubscribe|listserv|mailto|aaealist|aaea\.org/membership|google\.com/url", l, re.I)][:3]
    return {
        "message_id": mid,
        "rule": rule,
        "subject": subject,
        "title": title,
        "institution": inst,
        "sent": sent,
        "deadline": ex["deadline"],
        "start_date_text": ex["start_date_text"],
        "salary": ex["salary"],
        "degree_required": ex["degree_required"] if ex["degree_required"] == "Doctorate" else "",
        "us_state": ex["us_state"],
        "apply_links": apply_links,
        "text": text[:8000],
    }


def to_job(rec: dict) -> Job:
    country = "United States" if rec.get("us_state") else ""
    return Job(
        source="gmail",
        source_id=re.sub(r"[<>]", "", rec["message_id"]),
        url=rec["apply_links"][0] if rec["apply_links"] else "https://mail.google.com/mail/u/0/#search/" + requests.utils.quote(rec["subject"][:80]),
        title=rec["title"],
        institution=rec["institution"],
        section="",
        locations=[Location(state=rec.get("us_state", ""), country=country)] if country else [],
        categories=[f"list:{rec['rule']}"],
        deadline=rec.get("deadline"),
        posted=rec.get("sent"),
        start_date_text=rec.get("start_date_text", ""),
        degree_required=rec.get("degree_required", ""),
        requirements=[f"Apply: {l}" for l in rec["apply_links"]],
        salary=rec.get("salary", ""),
        full_text=rec["text"],
    )


# --------------------------------------------------------------------------- orchestration

def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return default


def fetch(session=None, raw_messages: list[bytes] | None = None, today: date | None = None) -> list[Job]:
    today = today or date.today()
    seen = set(_load(SEEN_FILE, []))
    stored = _load(JOBS_FILE, [])
    if raw_messages is None:
        if not configured():
            print("[gmail] not configured (GMAIL_USER / GMAIL_APP_PASSWORD or OAuth vars); "
                  f"using {len(stored)} stored postings", file=sys.stderr)
            return [to_job(r) for r in stored]
        conn = connect()
        try:
            raw_messages = fetch_raw_messages(conn, today - timedelta(days=LOOKBACK_DAYS))
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    new = 0
    def _sig(r):   # same subject = same announcement, however many times it is forwarded
        return re.sub(r"\W+", " ", r["subject"]).lower().strip()
    known = {_sig(r) for r in stored}
    for raw in raw_messages:
        rec = parse_message(raw)
        if not rec or rec["message_id"] in seen:
            continue
        seen.add(rec["message_id"])
        sig = _sig(rec)
        if sig in known:
            continue
        known.add(sig)
        stored.append(rec)
        new += 1
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    stored = [r for r in stored if (r.get("sent") or today.isoformat()) >= cutoff]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    JOBS_FILE.write_text(json.dumps(stored, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"[gmail] {new} new list e-mails parsed as postings; {len(stored)} kept", file=sys.stderr)
    return [to_job(r) for r in stored]
