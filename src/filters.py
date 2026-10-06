"""Position-type classification and the PhD / 2027-start screen."""
from __future__ import annotations

import re

PHD_RE = re.compile(r"\b(ph\.?\s?d\.?|doctora(?:l|te)|d\.?phil|doctoral degree)\b", re.I)
NOT_PHD_TITLE_RE = re.compile(
    r"pre-?doc|predoctoral|research assistant|undergraduate|\bRA\b|\bintern(ship)?\b|"
    r"master'?s? (student|program)|teaching assistant", re.I)
GOV_RE = re.compile(
    r"federal reserve|\bfed\b|\bbank of\b|central bank|reserve bank|\bUSDA\b|department of|"
    r"ministry|government|\bagency\b|commission|bureau|census|treasury|\bIMF\b|world bank|"
    r"\bOECD\b|united nations|\bUN\b|\bFAO\b|\bIFPRI\b|\bCGIAR\b|national institute|"
    r"congressional|\bGAO\b|\bCBO\b|\bERS\b|economic research service|laboratory|\bNOAA\b|\bEPA\b",
    re.I)
# Only start-of-appointment phrasings; month names are excluded on purpose because
# they mostly appear in deadlines ("November 30, 2026").
START_RE = re.compile(
    r"(?:\bstart(?:ing|s)?(?: date)?|\bbegin(?:ning|s)?|\bcommenc\w*|\beffective|academic year|"
    r"\bfall\b|\bautumn\b|\bspring\b|\bsummer\b|\bAY\b|available (?:from|in|starting|beginning))"
    r"[^.\n]{0,60}?\b(20\d\d)\b", re.I)


def position_type(job) -> str:
    title = job.title or ""
    sec = (job.section or "").lower()
    blob = title + " " + sec
    if re.search(r"post-?doc", blob, re.I):
        return "Postdoc"
    if re.search(r"\bintern(ship)?\b|traineeship|phd (?:student|candidate|scholarship)|\bstudent\b|scholarship", blob, re.I):
        return "Student/Intern"
    if ("nonacademic" in sec or "non-academic" in sec or re.search(r"consultant|economist\b", sec)
            or (re.search(r"full time|full-time|fixed term|consulting|part time", sec)
                and not re.search(r"professor|lecturer|faculty|academic|tenure", blob, re.I))):
        inst_blob = " ".join([job.institution, job.department, job.title])
        return "Government/IO" if GOV_RE.search(inst_blob) else "Industry/Nonprofit"
    if re.search(r"visiting|temporary|adjunct|lecturer|instructor|teaching|clinical", blob, re.I):
        return "Visiting/Teaching"
    if "tenure" in sec or "permanent" in sec or re.search(
            r"assistant professor|associate professor|full professor|\bprofessor\b|tenure|\bchair\b|"
            r"\basst\.? prof|\bassoc\.? prof|\bfaculty position", blob, re.I):
        return "Tenure-track"
    if not sec or "other" in sec:
        inst_blob = " ".join([job.institution, job.department, job.title])
        return "Government/IO" if GOV_RE.search(inst_blob) else "Industry/Nonprofit"
    return "Other"


def phd_required(job, ptype: str = ""):
    """True / False / None (unknown).

    Faculty and postdoc positions require a PhD by definition, so only
    non-academic and teaching postings are judged on their text.
    """
    if NOT_PHD_TITLE_RE.search(job.title or ""):
        return False
    deg = (job.degree_required or "").strip().lower()
    if deg.startswith("doctor") or deg.startswith("phd"):
        return True
    if deg:
        # EJM states another degree explicitly (e.g. Masters) — not a PhD job.
        return False
    if ptype in ("Tenure-track", "Postdoc"):
        return True
    text = job.full_text or ""
    if PHD_RE.search(text) or re.search(r"terminal degree|post-?doctoral", text, re.I):
        return True
    if not text:
        return None
    return False


def start_year(job):
    s = job.start_date_text or ""
    m = re.search(r"\b(20\d\d)\b", s)
    if m and 2025 <= int(m.group(1)) <= 2030:
        return int(m.group(1))
    if re.search(r"flexible|negotiable|asap|as soon as", s, re.I):
        return None
    blob = (job.title or "") + "\n" + (job.full_text or "")
    # Any mention of 2027 in a current-cycle posting almost always refers to the start.
    if re.search(r"\b2027\b", blob):
        return 2027
    years = [int(y) for y in START_RE.findall(blob)]
    years = [y for y in years if 2025 <= y <= 2030]
    if years:
        return max(set(years), key=years.count)
    return None


def screen(job, ptype: str):
    """Return (passes, reasons_for_exclusion)."""
    reasons = []
    if ptype == "Student/Intern":
        reasons.append("student/intern role")
    phd = phd_required(job, ptype)
    if phd is False and ptype != "Student/Intern":
        reasons.append("PhD not required")
    sy = start_year(job)
    if sy is not None and sy != 2027:
        reasons.append(f"start year {sy}")
    if re.search(r"adjunct|part-time", job.title, re.I) or \
            re.search(r"part-time or adjunct|temporary, part-time", job.section or "", re.I):
        reasons.append("adjunct/part-time")
    return (not reasons, reasons)
