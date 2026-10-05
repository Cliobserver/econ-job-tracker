"""Offline tests for the Chronicle / Substack adapters and text extraction."""
import unittest

from src.extract import deadline_from_text, start_from_text, salary_from_text, degree_from_text, regex_extract
from src.sources import chronicle, substack

CHRON_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item><title>Massachusetts Institute of Technology: Assistant or Untenured Associate Professor</title>
<description>
Competitive Salary:

Massachusetts Institute of Technology:
The Department of Economics ...
Massachusetts, United States
</description>
<link>https://jobs.chronicle.com/job/38042395/assistant-or-untenured-associate-professor/?TrackID=10</link>
<pubDate>Wed, 23 Sep 2026 00:00:00 -0500</pubDate></item>
</channel></rss>"""

CHRON_DETAIL = b"""<html><head><script type="application/ld+json"> { "@context": "https://schema.org/", "@type": "JobPosting",
"title": "Assistant or Untenured Associate Professor",
"description": "<p>Tenure-track openings beginning July 1, 2027. A PhD in Economics is required by the start of employment. Applications must be received by November 6, 2026.</p>",
"datePosted": "2026-09-23T04:00:00.000Z", "validThrough": "2026-11-22T04:59:00.000Z",
"hiringOrganization": {"name": "Massachusetts Institute of Technology", "@type": "Organization"},
"jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Cambridge", "addressRegion": "Massachusetts", "addressCountry": "US"}}]
} </script></head><body></body></html>"""

SUBSTACK_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Weekly Digest - October 2, 2026</title><link>https://x.substack.com/p/weekly-digest</link>
<content:encoded><![CDATA[<div>digest</div>]]></content:encoded><pubDate>Fri, 02 Oct 2026 17:02:34 GMT</pubDate></item>
<item><title>Postdoctoral Researcher in Climate Economics at Technical University of Munich (Germany)</title>
<link>https://x.substack.com/p/postdoc-tum</link>
<content:encoded><![CDATA[<p>Applicants should hold an excellent Ph.D. degree in Applied Economics. Salary TV-L E13. The position starts in spring 2027. Application deadline: 31 October 2026. Apply at <a href="https://tum.de/jobs/1">tum.de</a>.</p>]]></content:encoded>
<pubDate>Wed, 30 Sep 2026 17:02:57 GMT</pubDate></item>
<item><title>Economist at American Farm Bureau Federation</title>
<link>https://x.substack.com/p/afbf</link>
<content:encoded><![CDATA[<p>Located in Washington, DC. Salary range $90,000 - $110,000. Master's degree required; PhD preferred. Apply by 10/15/2026.</p>]]></content:encoded>
<pubDate>Tue, 29 Sep 2026 17:02:11 GMT</pubDate></item>
</channel></rss>"""


class ExtractTests(unittest.TestCase):
    def test_deadline_formats(self):
        self.assertEqual(deadline_from_text("Applications must be received by November 6, 2026."), "2026-11-06")
        self.assertEqual(deadline_from_text("Application deadline: 31 October 2026 (12:00 UTC)."), "2026-10-31")
        self.assertEqual(deadline_from_text("Apply by 10/15/2026."), "2026-10-15")
        self.assertEqual(deadline_from_text("Closing date 2026-12-01."), "2026-12-01")
        self.assertIsNone(deadline_from_text("Interviews will take place the week of December 14, 2026."))

    def test_deadline_prefers_strong_cue(self):
        txt = "The position was created by May 1, 2026 legislation. Review of applications begins December 1, 2026."
        self.assertEqual(deadline_from_text(txt), "2026-12-01")

    def test_start_salary_degree(self):
        self.assertEqual(start_from_text("beginning July 1, 2027 or as soon thereafter"), "July 2027")
        self.assertEqual(start_from_text("The position starts in spring 2027."), "Spring 2027")
        self.assertEqual(salary_from_text("Salary range $90,000 - $110,000 per year."), "$90,000 - $110,000 per year")
        self.assertEqual(degree_from_text("A PhD in Economics is required by the start of employment."), "Doctorate")
        self.assertEqual(degree_from_text("Master's degree required; PhD preferred."), "Doctorate")
        self.assertEqual(degree_from_text("Bachelor's degree in economics."), "Bachelors")
        self.assertEqual(regex_extract("Located in Washington, DC.")["us_state"], "District of Columbia")


class ChronicleTests(unittest.TestCase):
    def test_feed_and_detail(self):
        jobs = chronicle.fetch(raw_feeds=[CHRON_FEED], raw_details={"38042395": CHRON_DETAIL})
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.institution, "Massachusetts Institute of Technology")
        self.assertEqual(j.deadline, "2026-11-06")          # text deadline beats validThrough
        self.assertEqual(j.posted, "2026-09-23")
        self.assertEqual(j.locations[0].state, "Massachusetts")
        self.assertEqual(j.locations[0].country, "United States")
        self.assertEqual(j.url, "https://jobs.chronicle.com/job/38042395/assistant-or-untenured-associate-professor/")
        self.assertIn("Tenure Track", j.section)

    def test_detail_fallback_to_valid_through(self):
        detail = CHRON_DETAIL.replace(b"Applications must be received by November 6, 2026.", b"")
        jobs = chronicle.fetch(raw_feeds=[CHRON_FEED], raw_details={"38042395": detail})
        self.assertEqual(jobs[0].deadline, "2026-11-22")


class SubstackTests(unittest.TestCase):
    def test_parse_skips_digest_and_splits_title(self):
        jobs = substack.fetch(raw=SUBSTACK_FEED)
        self.assertEqual(len(jobs), 2)
        tum, afbf = jobs
        self.assertEqual(tum.title, "Postdoctoral Researcher in Climate Economics")
        self.assertEqual(tum.institution, "Technical University of Munich")
        self.assertEqual(tum.locations[0].country, "Germany")
        self.assertEqual(tum.deadline, "2026-10-31")
        self.assertEqual(tum.start_date_text, "Spring 2027")
        self.assertEqual(tum.degree_required, "Doctorate")
        self.assertEqual(tum.requirements, ["Apply: https://tum.de/jobs/1"])
        self.assertEqual(afbf.locations[0].country, "United States")
        self.assertEqual(afbf.locations[0].state, "District of Columbia")
        self.assertEqual(afbf.deadline, "2026-10-15")
        self.assertEqual(afbf.salary, "$90,000 - $110,000")

    def test_split_title_without_country(self):
        self.assertEqual(substack.split_title("Economist at American Farm Bureau Federation"),
                         ("Economist", "American Farm Bureau Federation", ""))
        self.assertEqual(substack.split_title("Chief of Party at TechnoServe (Ethiopia)")[2], "Ethiopia")


if __name__ == "__main__":
    unittest.main()
