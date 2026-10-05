"""Geographic tagging: US jobs get a state + census region, others get a continent."""
from __future__ import annotations

import re

US_NAMES = {"UNITED STATES", "UNITED STATES OF AMERICA", "USA", "US", "U.S.", "U.S.A."}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}
STATE_BY_NAME = {v.upper(): v for v in US_STATES.values()}

US_REGIONS = {
    "West": ["Alaska", "Arizona", "California", "Colorado", "Hawaii", "Idaho", "Montana", "Nevada",
             "New Mexico", "Oregon", "Utah", "Washington", "Wyoming"],
    "Midwest": ["Illinois", "Indiana", "Iowa", "Kansas", "Michigan", "Minnesota", "Missouri",
                "Nebraska", "North Dakota", "Ohio", "South Dakota", "Wisconsin"],
    "South": ["Alabama", "Arkansas", "Delaware", "District of Columbia", "Florida", "Georgia",
              "Kentucky", "Louisiana", "Maryland", "Mississippi", "North Carolina", "Oklahoma",
              "South Carolina", "Tennessee", "Texas", "Virginia", "West Virginia", "Puerto Rico"],
    "Northeast": ["Connecticut", "Maine", "Massachusetts", "New Hampshire", "New Jersey",
                  "New York", "Pennsylvania", "Rhode Island", "Vermont"],
}
REGION_BY_STATE = {s: r for r, states in US_REGIONS.items() for s in states}

CONTINENTS = {
    "North America": ["CANADA", "MEXICO", "GUATEMALA", "COSTA RICA", "PANAMA", "CUBA", "JAMAICA",
                      "DOMINICAN REPUBLIC", "HONDURAS", "EL SALVADOR", "NICARAGUA", "BAHAMAS",
                      "BARBADOS", "TRINIDAD AND TOBAGO", "HAITI", "BELIZE", "BERMUDA"],
    "South America": ["BRAZIL", "ARGENTINA", "CHILE", "COLOMBIA", "PERU", "URUGUAY", "ECUADOR",
                      "BOLIVIA", "PARAGUAY", "VENEZUELA", "GUYANA", "SURINAME"],
    "Europe": ["UNITED KINGDOM", "UK", "ENGLAND", "SCOTLAND", "WALES", "NORTHERN IRELAND", "GERMANY",
               "FRANCE", "ITALY", "SPAIN", "PORTUGAL", "NETHERLANDS", "THE NETHERLANDS", "BELGIUM",
               "LUXEMBOURG", "SWITZERLAND", "AUSTRIA", "IRELAND", "DENMARK", "SWEDEN", "NORWAY",
               "FINLAND", "ICELAND", "POLAND", "CZECH REPUBLIC", "CZECHIA", "SLOVAKIA", "HUNGARY",
               "ROMANIA", "BULGARIA", "GREECE", "CYPRUS", "MALTA", "CROATIA", "SLOVENIA", "SERBIA",
               "BOSNIA AND HERZEGOVINA", "MONTENEGRO", "NORTH MACEDONIA", "ALBANIA", "KOSOVO",
               "ESTONIA", "LATVIA", "LITHUANIA", "UKRAINE", "BELARUS", "MOLDOVA", "RUSSIA",
               "RUSSIAN FEDERATION", "LIECHTENSTEIN", "MONACO", "ANDORRA",
               "ARMENIA", "AZERBAIJAN"],
    "Asia": ["CHINA", "PEOPLE'S REPUBLIC OF CHINA", "HONG KONG", "HONG KONG SAR", "MACAU", "MACAO",
             "TAIWAN", "JAPAN", "SOUTH KOREA", "KOREA", "KOREA, REPUBLIC OF", "REPUBLIC OF KOREA",
             "SINGAPORE", "MALAYSIA", "INDONESIA", "THAILAND", "VIETNAM", "VIET NAM", "PHILIPPINES",
             "CAMBODIA", "LAOS", "MYANMAR", "BRUNEI", "INDIA", "PAKISTAN", "BANGLADESH", "SRI LANKA",
             "NEPAL", "BHUTAN", "MALDIVES", "MONGOLIA", "KAZAKHSTAN", "UZBEKISTAN", "KYRGYZSTAN",
             "TAJIKISTAN", "TURKMENISTAN", "AFGHANISTAN", "IRAN", "IRAQ", "ISRAEL", "JORDAN",
             "LEBANON", "SYRIA", "SAUDI ARABIA", "UNITED ARAB EMIRATES", "UAE", "QATAR", "KUWAIT",
             "BAHRAIN", "OMAN", "YEMEN", "TURKEY", "TÜRKIYE", "TURKIYE", "PALESTINE"],
    "Africa": ["EGYPT", "MOROCCO", "ALGERIA", "TUNISIA", "LIBYA", "SUDAN", "ETHIOPIA", "KENYA",
               "UGANDA", "TANZANIA", "RWANDA", "BURUNDI", "SOUTH AFRICA", "NIGERIA", "GHANA",
               "SENEGAL", "COTE D'IVOIRE", "CÔTE D'IVOIRE", "IVORY COAST", "CAMEROON", "MALI",
               "BURKINA FASO", "NIGER", "CHAD", "MOZAMBIQUE", "ZAMBIA", "ZIMBABWE", "MALAWI",
               "BOTSWANA", "NAMIBIA", "ANGOLA", "MADAGASCAR", "MAURITIUS", "BENIN", "TOGO",
               "SIERRA LEONE", "LIBERIA", "GAMBIA", "SOMALIA", "DJIBOUTI", "ERITREA",
               "DEMOCRATIC REPUBLIC OF THE CONGO", "CONGO", "GABON", "LESOTHO", "ESWATINI"],
    "Oceania": ["AUSTRALIA", "NEW ZEALAND", "FIJI", "PAPUA NEW GUINEA", "SAMOA", "TONGA"],
}
CONTINENT_BY_COUNTRY = {c: cont for cont, cs in CONTINENTS.items() for c in cs}


def is_us(country: str) -> bool:
    return country.strip().upper() in US_NAMES


def continent_of(country: str) -> str:
    c = country.strip().upper()
    if not c:
        return "Unknown"
    if c in US_NAMES:
        return "North America"
    return CONTINENT_BY_COUNTRY.get(c, "Other")


def us_state(text: str) -> str:
    """Return the full state name for a state abbreviation or name, else ''."""
    t = (text or "").strip()
    if not t:
        return ""
    if t.upper() in US_STATES:
        return US_STATES[t.upper()]
    if t.upper() in STATE_BY_NAME:
        return STATE_BY_NAME[t.upper()]
    # Strings like "CA 95616" or "Davis, CA"
    m = re.search(r"\b([A-Z]{2})\b(?:\s+\d{5})?$", t)
    if m and m.group(1) in US_STATES:
        return US_STATES[m.group(1)]
    return ""


def _uniq(seq):
    out = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


def geo_tags(locations) -> dict:
    """Collapse a list of Location objects into display tags.

    `regions` holds "US-<Census region>" for US jobs and the continent otherwise.
    """
    countries, regions, states = [], [], []
    for loc in locations:
        country = (loc.country or "").strip()
        if is_us(country):
            countries.append("United States")
            st = us_state(loc.state) or us_state(loc.city)
            if st:
                states.append(st)
                regions.append("US-" + REGION_BY_STATE.get(st, "Other"))
            else:
                regions.append("US-Other")
        elif country:
            countries.append(country.title() if country.isupper() else country)
            regions.append(continent_of(country))
    countries, regions, states = _uniq(countries), _uniq(regions), _uniq(states)
    if "United States" in countries:
        primary = states[0] if states else "United States"
    elif countries:
        primary = countries[0]
    else:
        primary = "Unknown"
    return {"countries": countries, "regions": regions or ["Unknown"],
            "us_states": states, "primary": primary}
