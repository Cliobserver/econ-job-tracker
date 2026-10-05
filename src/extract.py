"""Field extraction from unstructured posting text.

Two layers:
  * `regex_extract(text)` - cheap heuristics for deadline, start date, salary, degree,
    US state. Always runs.
  * `claude_extract(job)` - optional, only when ANTHROPIC_API_KEY is set. Asks Claude for
    the same fields as strict JSON and caches the answer per posting so each posting is
    extracted once. Model via JOB_TRACKER_MODEL (default claude-opus-5).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "llm"

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december|" \
         "jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
DATE_RE = re.compile(
    rf"(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m1>{MONTHS})\.?,?\s+(?P<y1>20\d\d))"      # 6 November 2026
    rf"|(?:(?P<m2>{MONTHS})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y2>20\d\d))"    # November 6, 2026
    rf"|(?:(?P<y3>20\d\d)-(?P<mo3>\d{{2}})-(?P<dd3>\d{{2}}))"                               # 2026-11-06
    rf"|(?:(?P<mo4>\d{{1,2}})/(?P<dd4>\d{{1,2}})/(?P<y4>20\d\d))",                          # 11/06/2026
    re.I)
DEADLINE_CUE = re.compile(
    r"(application deadline|deadline|apply by|applications? (?:must be |should be |are )?"
    r"(?:received|submitted|due|accepted until|close)|closing date|closes? on|close date|"
    r"review of applications (?:will )?begins?|for full consideration|priority (?:deadline|consideration)|"
    r"open until|until the position is filled|no later than|by)",
    re.I)
START_CUE = re.compile(
    r"(start(?:ing|s)?(?: date)?|begin(?:ning|s)?|commenc\w*|effective|appointment (?:will )?(?:start|begin)|"
    r"available (?:from|in|starting|beginning)|academic year|fall|autumn|spring|summer)", re.I)
SALARY_RE = re.compile(
    r"(?:\$|USD\s?|US\$|€|£|CAD\s?|AUD\s?)\s?\d{2,3}(?:,\d{3})+(?:\s?(?:-|–|to)\s?(?:\$|USD\s?|US\$|€|£)?\s?\d{2,3}(?:,\d{3})+)?"
    r"(?:\s?(?:per|/)\s?(?:year|annum|yr|month))?", re.I)
DEGREE_RE = re.compile(r"\b(ph\.?\s?d\.?|doctora(?:l|te)|d\.?phil|terminal degree|master'?s|m\.?s\.?|m\.?a\.?|bachelor'?s|b\.?s\.?|b\.?a\.?)\b", re.I)

US_STATE_RE = re.compile(
    r"\b(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
    r"Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
    r"Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|"
    r"Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|"
    r"Virginia|Washington,? D\.?C\.?|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia)\b")


def _to_iso(m: re.Match) -> str | None:
    g = m.groupdict()
    try:
        if g.get("y1"):
            return datetime.strptime(f"{g['d1']} {g['m1'][:3]} {g['y1']}", "%d %b %Y").date().isoformat()
        if g.get("y2"):
            return datetime.strptime(f"{g['d2']} {g['m2'][:3]} {g['y2']}", "%d %b %Y").date().isoformat()
        if g.get("y3"):
            return datetime(int(g["y3"]), int(g["mo3"]), int(g["dd3"])).date().isoformat()
        if g.get("y4"):
            return datetime(int(g["y4"]), int(g["mo4"]), int(g["dd4"])).date().isoformat()
    except ValueError:
        return None
    return None


def find_dates(text: str):
    return [(_to_iso(m), m.start()) for m in DATE_RE.finditer(text) if _to_iso(m)]


def deadline_from_text(text: str) -> str | None:
    """Return the first date that appears within ~80 chars after a deadline cue."""
    if not text:
        return None
    best = None
    for cue in DEADLINE_CUE.finditer(text):
        window = text[cue.end(): cue.end() + 90]
        m = DATE_RE.search(window)
        if m and _to_iso(m):
            iso = _to_iso(m)
            # Prefer explicit "deadline"/"apply by" over weak cues like "by".
            strong = not cue.group(0).lower().strip() in ("by",)
            if strong:
                return iso
            best = best or iso
    return best


def start_from_text(text: str) -> str:
    if not text:
        return ""
    for cue in START_CUE.finditer(text):
        window = text[cue.start(): cue.end() + 60]
        m = re.search(r"\b(202[5-9]|2030)\b", window)
        if m:
            season = re.search(r"(fall|autumn|spring|summer|january|february|march|april|may|june|july|august|"
                               r"september|october|november|december)", window, re.I)
            return f"{season.group(1).title() + ' ' if season else ''}{m.group(1)}"
    return ""


def salary_from_text(text: str) -> str:
    m = SALARY_RE.search(text or "")
    return m.group(0).strip() if m else ""


def degree_from_text(text: str) -> str:
    """'Doctorate' if a PhD is mentioned as required/preferred, else the highest degree named."""
    t = text or ""
    if re.search(r"\b(ph\.?\s?d|doctora(?:l|te)|d\.?phil)\b[^.]{0,80}\b(required|is required|must|preferred|"
                 r"or equivalent|in hand|completed|by the (start|time))", t, re.I) or \
       re.search(r"(require|must (?:have|hold|possess)|hold|earned|completed)[^.]{0,60}\b(ph\.?\s?d|doctora(?:l|te))\b", t, re.I):
        return "Doctorate"
    if re.search(r"\b(ph\.?\s?d|doctora(?:l|te))\b", t, re.I):
        return "Doctorate (mentioned)"
    if re.search(r"(?i:\bmaster'?s\b)|\bM\.?S\.?\b|\bM\.?A\.?\b", t):
        return "Masters"
    if re.search(r"(?i:\bbachelor'?s\b)|\bB\.?S\.?\b|\bB\.?A\.?\b", t):
        return "Bachelors"
    return ""


def us_state_from_text(text: str) -> str:
    m = US_STATE_RE.search(text or "")
    if not m:
        return ""
    s = m.group(1)
    return "District of Columbia" if s.lower().startswith("washington, d") or s.lower().startswith("washington d") else s


def regex_extract(text: str) -> dict:
    return {
        "deadline": deadline_from_text(text),
        "start_date_text": start_from_text(text),
        "salary": salary_from_text(text),
        "degree_required": degree_from_text(text),
        "us_state": us_state_from_text(text),
    }


# ---------------------------------------------------------------------------
# Optional Claude extraction
# ---------------------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "application_deadline": {"type": ["string", "null"], "description": "ISO date yyyy-mm-dd, or null if none stated"},
        "start_date": {"type": ["string", "null"], "description": "Stated start of appointment, e.g. '2027-08-16' or 'Fall 2027'"},
        "phd_required": {"type": ["boolean", "null"], "description": "True if a PhD/doctorate is required (or expected by start)"},
        "city": {"type": ["string", "null"]},
        "state_or_region": {"type": ["string", "null"], "description": "US state full name or non-US region"},
        "country": {"type": ["string", "null"]},
        "remote": {"type": "boolean"},
        "position_type": {"type": "string", "enum": ["Tenure-track", "Postdoc", "Visiting/Teaching", "Government/IO", "Industry/Nonprofit", "Other"]},
        "fields": {"type": "array", "items": {"type": "string"}, "description": "Economics subfields, e.g. Agricultural, Environmental, Development, Labor"},
        "salary": {"type": ["string", "null"]},
        "application_materials": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["application_deadline", "start_date", "phd_required", "city", "state_or_region", "country",
                 "remote", "position_type", "fields", "salary", "application_materials"],
    "additionalProperties": False,
}
SYSTEM = ("You extract structured facts from economics job postings. Use only what the posting states. "
          "Dates as ISO yyyy-mm-dd. If the posting gives several deadlines, return the final application deadline, "
          "not the review-begins date. Unknown fields are null.")


def claude_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _cache_path(key: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".json")


def claude_extract(title: str, institution: str, text: str, cache_key: str) -> dict | None:
    """Return the extracted dict (cached per posting), or None when disabled/failed."""
    if not claude_enabled() or not text:
        return None
    path = _cache_path(cache_key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        import anthropic
    except ImportError:
        print("[extract] anthropic SDK not installed; skipping LLM extraction", file=sys.stderr)
        return None
    client = anthropic.Anthropic()
    model = os.environ.get("JOB_TRACKER_MODEL", "claude-opus-5")
    prompt = f"Title: {title}\nInstitution: {institution}\n\nPosting:\n{text[:12000]}"
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "low"},
            thinking={"type": "adaptive"},
        )
    except anthropic.RateLimitError as e:
        print(f"[extract] rate limited: {e}", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"[extract] API error {e.status_code}: {e.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as e:
        print(f"[extract] connection error: {e}", file=sys.stderr)
        return None
    if response.stop_reason == "refusal":
        return None
    raw = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
