"""Offline unit tests (no network). Run: python -m pytest -q  or  python -m unittest"""
import unittest
from datetime import date

from src.models import Job, Location
from src.geo import geo_tags, us_state
from src.fields import field_tags
from src.filters import position_type, screen, start_year, phd_required
from src.dedup import dedup
from src import store


def mk(**kw):
    base = dict(source="joe", source_id="1", url="u", title="Assistant Professor", institution="Test U")
    base.update(kw)
    return Job(**base)


class GeoTests(unittest.TestCase):
    def test_us_state_forms(self):
        self.assertEqual(us_state("CA"), "California")
        self.assertEqual(us_state("california"), "California")
        self.assertEqual(us_state("Davis, CA 95616"), "California")
        self.assertEqual(us_state("36"), "")

    def test_regions(self):
        g = geo_tags([Location(city="Davis", state="California", country="UNITED STATES")])
        self.assertEqual(g["regions"], ["US-West"])
        self.assertEqual(g["primary"], "California")
        g = geo_tags([Location(city="Berlin", country="Germany")])
        self.assertEqual(g["regions"], ["Europe"])
        g = geo_tags([Location(city="Burnaby", state="BC", country="Canada")])
        self.assertEqual(g["regions"], ["North America"])
        g = geo_tags([Location(country="UNITED STATES")])
        self.assertEqual(g["regions"], ["US-Other"])


class FieldTests(unittest.TestCase):
    def test_jel_and_keywords(self):
        j = mk(jel_codes=["Q1", "Q5"], title="Assistant Professor of Agricultural Economics")
        tags = field_tags(j)
        self.assertIn("Agricultural", tags)
        self.assertIn("Environmental", tags)
        self.assertNotIn("Agricultural/Environmental", tags)

    def test_any_field_last(self):
        j = mk(jel_codes=["00", "J"])
        self.assertEqual(field_tags(j)[-1], "Any Field")


class FilterTests(unittest.TestCase):
    def test_tenure_track_passes_without_phd_text(self):
        j = mk(section="US: Full-Time Academic (Permanent, Tenure Track or Tenured)",
               full_text="Position starting approximately August 12, 2027.")
        pt = position_type(j)
        self.assertEqual(pt, "Tenure-track")
        self.assertTrue(screen(j, pt)[0])

    def test_deadline_month_not_treated_as_start(self):
        j = mk(section="Full-Time Nonacademic", title="Economist", institution="Bates White",
               full_text="PhD required. Applications due November 15, 2026.")
        self.assertIsNone(start_year(j))
        self.assertTrue(screen(j, position_type(j))[0])

    def test_2026_start_excluded(self):
        j = mk(section="US: Other Academic (Visiting or Temporary)", title="Visiting Assistant Professor",
               full_text="PhD required. Beginning fall semester 2026.")
        ok, reasons = screen(j, position_type(j))
        self.assertFalse(ok)
        self.assertIn("start year 2026", reasons)

    def test_predoc_excluded(self):
        j = mk(title="Pre-doctoral Research Assistant", section="Full-Time Nonacademic", full_text="PhD economists supervise.")
        self.assertFalse(phd_required(j, position_type(j)))

    def test_ejm_degree_field(self):
        j = mk(source="ejm", degree_required="Doctorate", start_date_text="2027-07-01", section="Assistant Professor")
        self.assertTrue(screen(j, position_type(j))[0])
        j = mk(source="ejm", degree_required="Doctorate", start_date_text="2026-10-01", section="Consultant")
        self.assertFalse(screen(j, position_type(j))[0])


class DedupTests(unittest.TestCase):
    def test_cross_source_merge(self):
        a = mk(source="joe", source_id="1", institution="Brown University", title="Assistant Professor of Economics")
        b = mk(source="ejm", source_id="2", institution="Economics Brown University", title="Assistant Professor of Economics")
        c = mk(source="joe", source_id="3", institution="Brown University", title="Assistant Professor of Economics")
        clusters = dedup([a, b, c])
        self.assertEqual(len(clusters), 2)  # same-source ids never merge


class StoreTests(unittest.TestCase):
    def test_merge_keeps_first_seen(self):
        old = {"updated": "2026-10-01", "jobs": [
            {"source_keys": ["joe:1"], "institution": "A", "deadline": "2026-12-01", "first_seen": "2026-09-20", "last_seen": "2026-10-01"},
            {"source_keys": ["joe:9"], "institution": "B", "deadline": None, "first_seen": "2026-09-01", "last_seen": "2026-09-10"},
        ]}
        fresh = [{"source_keys": ["joe:1", "ejm:5"], "institution": "A", "deadline": "2026-12-01"}]
        out = store.merge(old, fresh, date(2026, 10, 4))
        a = next(j for j in out["jobs"] if "joe:1" in j["source_keys"])
        b = next(j for j in out["jobs"] if "joe:9" in j["source_keys"])
        self.assertEqual(a["first_seen"], "2026-09-20")
        self.assertEqual(a["status"], "active")
        self.assertEqual(b["status"], "gone")

    def test_failed_source_keeps_records(self):
        old = {"updated": "2026-10-03", "jobs": [
            {"source_keys": ["substack:a"], "institution": "A", "deadline": None, "first_seen": "2026-10-01",
             "last_seen": "2026-10-03", "status": "active"},
        ]}
        out = store.merge(old, [], date(2026, 10, 4), failed_sources=["substack"])
        self.assertEqual(out["jobs"][0]["status"], "active")
        out = store.merge(old, [], date(2026, 10, 4))
        self.assertEqual(out["jobs"][0]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
