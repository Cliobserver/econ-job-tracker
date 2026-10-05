"""Merge the same posting seen on several boards."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

STOP = {"the", "of", "at", "and", "for", "in", "a", "an", "&"}


def norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    return " ".join(w for w in s.split() if w not in STOP)


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def same_posting(a, b) -> bool:
    if a.source == b.source:
        return False  # within one board every id is a distinct posting
    ia, ib = norm(a.institution), norm(b.institution)
    if not ia or not ib:
        return False
    inst_ok = ia == ib or sim(ia, ib) >= 0.85 or ia in ib or ib in ia
    if not inst_ok:
        return False
    ta, tb = norm(a.title), norm(b.title)
    if ta == tb or sim(ta, tb) >= 0.8:
        return True
    # Same deadline plus same department is strong evidence as well.
    if a.deadline and a.deadline == b.deadline and norm(a.department) and norm(a.department) == norm(b.department):
        return True
    return False


def dedup(jobs: list) -> list[list]:
    """Group jobs into clusters of the same posting. Returns list of clusters."""
    clusters: list[list] = []
    for job in jobs:
        for cl in clusters:
            if any(o.source == job.source for o in cl):
                continue  # a cluster holds at most one posting per board
            if any(same_posting(job, other) for other in cl):
                cl.append(job)
                break
        else:
            clusters.append([job])
    return clusters
