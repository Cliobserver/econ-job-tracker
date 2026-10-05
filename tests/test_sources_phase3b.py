"""Offline tests for the AAEA, INOMICS and Econ-Jobs adapters (fixtures trimmed from real pages)."""
import unittest

from src.sources import aaea, inomics, econjobs
from src.filters import position_type, screen

AAEA_BOARD = b"""<html><body><ul class="jobboard">
<li class="ad"> <div class="topright">09/17/2026</div>
 <a href="https://aaea.execinc.com/edibo/JobBoard/ViewPosting/next?SubmissionId=2673"><span class="positiontitle">Associate/Full Professor of Agricultural Economics</span></a>
 <br><strong>University of California Davis</strong> <br>Davis, CA, United States <div class="noflair">ES</div> </li>
<li class="ad"> <div class="topright">09/15/2026</div>
 <a href="https://aaea.execinc.com/edibo/JobBoard/ViewPosting/next?SubmissionId=2671"><span class="positiontitle">Senior Lecturer in Farm Management</span></a>
 <br><strong>Massey University</strong> <br>Palmerston North, Manawatu, New Zealand </li>
</ul></body></html>"""

AAEA_POST = b"""<html><body>
<div id="ctl01_ctl00_CphBody_CphWizardBody_ctl00_ctl01_ctl00_Value">Associate/Full Professor of Agricultural Economics<br>
The Department of Agricultural and Resource Economics is recruiting a tenured professor. Review of applications begins
November 10, 2026. See https://coststudies.ucdavis.edu for context.<br>To apply, visit https://apptrkr.com/9836752.</div>
<div class="FieldControl"><div class="ControlLabel">City</div><span>Davis</span></div>
<div class="FieldControl"><div class="ControlLabel">State/Province</div><span>CA</span></div>
<div class="FieldControl"><div class="ControlLabel">Country</div><span>United States</span></div>
</body></html>"""

INOMICS_LIST = b"""<html><body><ul>
<li><a class="post-link" href="/job/postdoctoral-scholarship-3-years-in-economics-1555359">
 <ul class="psh"><li><span class='type-badge'> Scholarship, Postdoc Job </span></li><li class="since"> Posted 2 days ago </li></ul>
 <h2> Postdoctoral scholarship (3 years) in Economics </h2>
 <span content="APPLICATION CLOSING DATE: 15-11-2026"></span>
 <span class="informations"><span content="Postdoctoral scholarship (3 years) in Economics"></span><span content="02-10-2026"></span>
 At <span class="bold">Umea University</span> <span class="location bold"><span>Umea</span>, <span>Sweden</span></span></span></a></li>
<li><a class="post-link" href="/job/phd-scholarships-in-economics-1555300">
 <ul class="psh"><li><span class='type-badge'> PhD Candidate Job </span></li></ul><h2> PhD scholarships in Economics </h2>
 <span class="informations"><span content="01-10-2026"></span> At <span class="bold">University of Southern Denmark</span>
 <span class="location bold"><span>Odense</span>, <span>Denmark</span></span></span></a></li>
</ul></body></html>"""

INOMICS_DETAIL = b"""<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Postdoctoral scholarship (3 years) in Economics",
"datePosted":"2026-10-02T10:00:00Z","hiringOrganization":{"@type":"Organization","name":"Umea University"},
"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Umea","addressCountry":"SE"}},
"industry":"Economics, Environmental and Resource Economics (JEL Q)","description":"x"}</script></head>
<body><div class="post-description"><p>Applicants must hold a PhD. Application deadline: 15 November 2026. Start: spring 2027.</p></div></body></html>"""

ECONJOBS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:job_listing="https://econ-jobs.com"><channel>
<item><title>PhD Economics Intern &#8211; Structural IO</title><link>https://econ-jobs.com/job-offer/phd-intern/</link>
<guid>https://econ-jobs.com/?post_type=job_listing&amp;p=980</guid><pubDate>Mon, 29 Sep 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>Summer 2027 internship for PhD students.</p>]]></content:encoded>
<job_listing:location>Seattle, WA, United States</job_listing:location><job_listing:job_type>Internship &amp; Fellowship</job_listing:job_type>
<job_listing:job_category>Economic Researcher</job_listing:job_category><job_listing:company>Amazon.com</job_listing:company></item>
<item><title>Principal Data Scientist &#8211; Economic Research</title><link>https://econ-jobs.com/job-offer/pds/</link>
<guid>https://econ-jobs.com/?post_type=job_listing&amp;p=986</guid><pubDate>Wed, 30 Sep 2026 09:21:07 +0000</pubDate>
<content:encoded><![CDATA[<p>PhD in economics required. Applications close on 27 October 2026.</p>]]></content:encoded>
<job_listing:location>Sydney, NSW, Australia</job_listing:location><job_listing:job_type>Full Time</job_listing:job_type>
<job_listing:job_category>Data Scientist &amp; Statistician, Economic Researcher</job_listing:job_category><job_listing:company>Reserve Bank of Australia</job_listing:company></item>
</channel></rss>"""


class AaeaTests(unittest.TestCase):
    def test_board_and_posting(self):
        jobs = aaea.fetch(raw_board=AAEA_BOARD, raw_postings={"2673": AAEA_POST})
        self.assertEqual(len(jobs), 2)
        ucd, massey = jobs
        self.assertEqual(ucd.institution, "University of California Davis")
        self.assertEqual(ucd.posted, "2026-09-17")
        self.assertEqual(ucd.deadline, "2026-11-10")
        self.assertEqual(ucd.requirements, ["Apply: https://apptrkr.com/9836752"])
        self.assertEqual(ucd.locations[0].state, "California")
        self.assertEqual(massey.locations[0].country, "New Zealand")
        self.assertEqual(massey.locations[0].city, "Palmerston North")
        self.assertEqual(position_type(ucd), "Tenure-track")


class InomicsTests(unittest.TestCase):
    def test_list_and_detail(self):
        jobs = inomics.fetch(raw_pages=[INOMICS_LIST], raw_details={"1555359": INOMICS_DETAIL})
        self.assertEqual(len(jobs), 2)
        post, phd = jobs
        self.assertEqual(post.institution, "Umea University")
        self.assertEqual(post.deadline, "2026-11-15")
        self.assertEqual(post.posted, "2026-10-02")
        self.assertEqual(post.jel_codes, ["Q"])
        self.assertEqual(post.locations[0].country, "SE")
        self.assertEqual(position_type(post), "Postdoc")
        self.assertTrue(screen(post, "Postdoc")[0])
        self.assertEqual(position_type(phd), "Student/Intern")
        self.assertFalse(screen(phd, "Student/Intern")[0])
        self.assertEqual(phd.locations[0].country, "Denmark")   # no detail -> listing location


class EconJobsTests(unittest.TestCase):
    def test_feed(self):
        jobs = econjobs.fetch(raw_feed=ECONJOBS_FEED, raw_details={})
        intern, pds = jobs
        self.assertEqual(intern.section, "Internship & Fellowship")
        self.assertEqual(intern.locations[0].state, "Washington")
        self.assertEqual(position_type(intern), "Student/Intern")
        self.assertEqual(pds.institution, "Reserve Bank of Australia")
        self.assertEqual(pds.deadline, "2026-10-27")
        self.assertEqual(pds.locations[0].country, "Australia")
        self.assertEqual(pds.categories, ["Data Scientist & Statistician", "Economic Researcher"])
        self.assertEqual(position_type(pds), "Government/IO")


if __name__ == "__main__":
    unittest.main()
