"""Write docs/data.json for the dashboard and the README summary table."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
README = ROOT / "README.md"

README_HEAD = """# Econ Job Tracker

Daily aggregation of economics job postings for the 2026-27 market, filtered to
PhD-required positions starting in 2027, tagged by field and location.

**Dashboard:** https://cliobserver.github.io/econ-job-tracker/

Sources: AEA JOE (official XML export), EconJobMarket.org, Chronicle of Higher Education (RSS + job pages),
INOMICS, AAEA Job Board, Econ-Jobs.com (RSS), AERE Career Center, Applied Econ Jobs Substack (RSS), and
mailing-list e-mail (RESECON, CWAE, AAEA sections, ARE Grads) when Gmail credentials are configured.
Runs every day at 12:00 America/Los_Angeles via GitHub Actions.

"""


def write_data_json(store: dict, health: dict, today: date) -> None:
    DOCS.mkdir(exist_ok=True)
    jobs = [j for j in store["jobs"] if j["status"] != "gone"]
    payload = {
        "updated": store["updated"],
        "generated_on": today.isoformat(),
        "health": health,
        "counts": {
            "total": len(jobs),
            "passing": sum(1 for j in jobs if j["passes_filter"]),
            "new_today": sum(1 for j in jobs if j["first_seen"] == today.isoformat()),
        },
        "jobs": jobs,
    }
    with (DOCS / "data.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def _md(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def write_readme(store: dict, health: dict, today: date, limit: int = 60) -> None:
    jobs = [j for j in store["jobs"] if j["status"] == "active" and j["passes_filter"]]
    upcoming = [j for j in jobs if (j.get("deadline") or "9999") >= today.isoformat()]
    upcoming.sort(key=lambda j: (j.get("deadline") or "9999-99-99"))
    new_today = sum(1 for j in jobs if j["first_seen"] == today.isoformat())
    lines = [README_HEAD]
    lines.append(f"_Last run: {store['updated']}. Active postings passing the filter: "
                 f"{len(jobs)} ({new_today} new today)._\n")
    lines.append("| Source | Fetched | Status |\n|---|---|---|")
    for name, h in health.items():
        lines.append(f"| {name} | {h.get('count', 0)} | {_md(h.get('status', ''))} |")
    lines.append(f"\n## Next {min(limit, len(upcoming))} deadlines\n")
    lines.append("| Deadline | Position | Institution | Location | Fields | Type | New |\n|---|---|---|---|---|---|---|")
    for j in upcoming[:limit]:
        links = " ".join(f"[{s['source'].upper()}]({s['url']})" for s in j["sources"])
        new = "🆕" if j["first_seen"] == today.isoformat() else ""
        lines.append(
            f"| {j.get('deadline') or '—'} | {_md(j['title'])} {links} | {_md(j['institution'])} | "
            f"{_md(j['geo']['primary'])} | {_md(', '.join(j['fields'][:3]))} | {_md(j['type'])} | {new} |")
    lines.append("\n_Table shows the next deadlines only; use the dashboard for filtering by field, "
                 "region, type, and source._\n")
    README.write_text("\n".join(lines), encoding="utf-8")
