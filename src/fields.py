"""Field-of-study tagging from JEL codes, source categories, and title keywords."""
from __future__ import annotations

import re

# Two-character JEL prefixes take precedence over one-letter prefixes.
JEL_MAP = {
    "Q1": "Agricultural", "Q2": "Natural Resources", "Q3": "Natural Resources", "Q4": "Energy",
    "Q5": "Environmental", "Q0": "Agricultural/Environmental", "Q": "Agricultural/Environmental",
    "R": "Urban/Regional", "O": "Development", "I1": "Health", "I2": "Education", "I3": "Public",
    "I": "Health", "J": "Labor", "H": "Public", "F": "International/Trade", "G": "Finance",
    "E": "Macro", "D9": "Behavioral/Experimental", "C9": "Behavioral/Experimental", "D": "Micro",
    "C": "Econometrics", "L": "Industrial Organization", "K": "Law & Economics",
    "M": "Business/Management", "N": "Economic History", "P": "Political Economy",
    "A": "Any Field", "B": "Any Field", "0": "Any Field", "00": "Any Field", "Z": "Other",
    "Y": "Other",
}

# (regex, tag). Applied to title + department + categories, not the full text.
KEYWORD_RULES = [
    (r"agricultur|agri-?food|\bfood\b|farm|agribusiness|\bag\b|\bARE\b", "Agricultural"),
    (r"environment|climate|sustainab|ecolog|conservation", "Environmental"),
    (r"natural resource|resource econ|\bwater\b|fisher|forest|\bland\b", "Natural Resources"),
    (r"energy|electricity|\boil\b|power market", "Energy"),
    (r"development|poverty|global south|africa", "Development"),
    (r"urban|regional|housing|real estate|spatial|transport", "Urban/Regional"),
    (r"health|medic|epidemiolog", "Health"),
    (r"education", "Education"),
    (r"labor|labour|demograph|population|migration", "Labor"),
    (r"public econ|public finance|taxation|\btax\b|fiscal", "Public"),
    (r"international|trade|global econ", "International/Trade"),
    (r"financ|banking|asset pricing|corporate", "Finance"),
    (r"macro|monetary|business cycle|growth", "Macro"),
    (r"microeconomic theory|micro theory|game theory|mechanism design|decision theory", "Micro"),
    (r"econometric|statistic|data science|machine learning|quantitative method", "Econometrics"),
    (r"industrial organi[sz]ation|\bIO\b|antitrust|competition", "Industrial Organization"),
    (r"behavio|experimental", "Behavioral/Experimental"),
    (r"law and econ|law & econ", "Law & Economics"),
    (r"political econ|public choice|institution", "Political Economy"),
    (r"economic history|cliometric", "Economic History"),
    (r"any field|open field|all fields|various fields", "Any Field"),
]

AG_ENV_TAGS = {"Agricultural", "Environmental", "Natural Resources", "Energy",
               "Agricultural/Environmental"}


def tags_from_jel(codes) -> list[str]:
    out = []
    for code in codes:
        c = (code or "").strip().upper()
        tag = JEL_MAP.get(c[:2]) or JEL_MAP.get(c[:1])
        if tag and tag not in out:
            out.append(tag)
    return out


def tags_from_text(text: str) -> list[str]:
    out = []
    for pat, tag in KEYWORD_RULES:
        if re.search(pat, text, flags=re.I) and tag not in out:
            out.append(tag)
    return out


def field_tags(job) -> list[str]:
    tags = tags_from_jel(job.jel_codes)
    text = " | ".join([job.title, job.department] + list(job.categories))
    for t in tags_from_text(text):
        if t not in tags:
            tags.append(t)
    # Drop the generic Q tag when a specific one is also present.
    if "Agricultural/Environmental" in tags and (AG_ENV_TAGS - {"Agricultural/Environmental"}) & set(tags):
        tags.remove("Agricultural/Environmental")
    # "Any Field" goes last when other fields are listed.
    if "Any Field" in tags and len(tags) > 1:
        tags = [t for t in tags if t != "Any Field"] + ["Any Field"]
    return tags or ["Unspecified"]


def is_ag_env(tags) -> bool:
    return bool(AG_ENV_TAGS & set(tags))
