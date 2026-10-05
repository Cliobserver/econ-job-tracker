"""Offline tests for the Gmail list adapter and the AERE career center adapter."""
import unittest
from datetime import date

from src.sources import gmail, aere

RESECON_EML = b"""Message-ID: <abc123@listserv.utk.edu>
Date: Mon, 28 Sep 2026 14:02:11 -0400
From: "Sims, Charles" <csims@UTK.EDU>
To: RESECON@LISTSERV.UTK.EDU
Subject: Assistant Professor in Environmental Economics at University of Tennessee
List-Id: Environmental & Resource Economics Network <RESECON.LISTSERV.UTK.EDU>
Content-Type: text/plain; charset="utf-8"

The Department of Economics at the University of Tennessee, Knoxville invites applications for a
tenure-track Assistant Professor position in environmental economics beginning August 1, 2027.
Candidates must have a Ph.D. in economics by the start date. Review of applications will begin
November 15, 2026. Apply at https://apply.interfolio.com/12345 .

________________________________________
To unsubscribe from the RESECON list, click the following link:
"""

CWAE_EML = b"""Message-ID: <def456@aaealist.org>
Date: Tue, 29 Sep 2026 09:00:00 -0500
From: Jane Doe via CWAE <cwae@aaealist.org>
Subject: [AAEA CWAE] FW: Postdoctoral Scholar, Agricultural Economics - Purdue University
Content-Type: text/html; charset="utf-8"

<html><body><p>Purdue University seeks a postdoctoral scholar in agricultural economics. A PhD is required.
Salary: $65,000. Applications are due 10/31/2026.</p><p>Apply: <a href="https://careers.purdue.edu/job/999">link</a></p>
<p>Located in West Lafayette, Indiana.</p></body></html>
"""

WEBINAR_EML = b"""Message-ID: <ghi789@aaealist.org>
Date: Tue, 29 Sep 2026 09:00:00 -0500
From: AAEA <cwae@aaealist.org>
Subject: [AAEA CWAE] Reminder: Webinar on October 27 - Sharing our Struggles
Content-Type: text/plain; charset="utf-8"

Join us for the webinar. Register here.
"""

SUBSTACK_EML = b"""Message-ID: <sub@substack.com>
Date: Tue, 29 Sep 2026 09:00:00 -0500
From: Applied Econ Jobs <appliedeconjobs@substack.com>
Subject: Economist at Farm Bureau (shared on the RESECON listserv)
Content-Type: text/plain; charset="utf-8"

Apply now.
"""

AERE_HTML = b"""<html><body><h2><span>Jobs:</span></h2><ul>
<li><strong style="font-size: 15px;"><a href="https://secure7.saashr.com/ta/6213629.careers?ein_id=119000450">Research Fellow (Early Career), Resources for the Future</a>, </strong><span style="font-size: 15px;"> Washington, DC Posted 09/21/26.</span></li>
<li><strong><a href="https://apptrkr.com/9822154">Clarence F. Korstian Professor of Forest Economics &amp; Management, Duke University</a>, </strong><span> Durham, NC Posted 09/14/26.</span></li>
<li><strong><a href="https://ghforum.fudan.edu.cn/page.htm">Faculty-Interdisciplinary Research, Fudan University, The MOE Laboratory</a>, </strong><span> Shanghai, China Posted 06/03/26.</span></li>
</ul></body></html>"""


class GmailTests(unittest.TestCase):
    def test_resecon_plain(self):
        rec = gmail.parse_message(RESECON_EML)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["rule"], "resecon")
        self.assertEqual(rec["title"], "Assistant Professor in Environmental Economics")
        self.assertEqual(rec["institution"], "University of Tennessee")
        self.assertEqual(rec["deadline"], "2026-11-15")
        self.assertEqual(rec["start_date_text"], "August 2027")
        self.assertEqual(rec["degree_required"], "Doctorate")
        self.assertEqual(rec["apply_links"], ["https://apply.interfolio.com/12345"])
        self.assertNotIn("unsubscribe", rec["text"].lower())

    def test_cwae_html_forward(self):
        rec = gmail.parse_message(CWAE_EML)
        self.assertEqual(rec["rule"], "cwae")
        self.assertEqual(rec["title"], "Postdoctoral Scholar, Agricultural Economics")
        self.assertEqual(rec["institution"], "Purdue University")
        self.assertEqual(rec["deadline"], "2026-10-31")
        self.assertEqual(rec["salary"], "$65,000")
        self.assertEqual(rec["us_state"], "Indiana")

    def test_non_job_and_duplicate_sources_skipped(self):
        self.assertIsNone(gmail.parse_message(WEBINAR_EML))
        self.assertIsNone(gmail.parse_message(SUBSTACK_EML))

    def test_fetch_offline_dedups_and_builds_jobs(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            gmail.SEEN_FILE = pathlib.Path(d) / "seen.json"
            gmail.JOBS_FILE = pathlib.Path(d) / "jobs.json"
            gmail.CACHE_DIR = pathlib.Path(d)
            jobs = gmail.fetch(raw_messages=[RESECON_EML, CWAE_EML, RESECON_EML], today=date(2026, 10, 5))
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0].source, "gmail")
            self.assertEqual(jobs[0].url, "https://apply.interfolio.com/12345")
            # Second run with no new mail keeps the stored postings.
            jobs2 = gmail.fetch(raw_messages=[], today=date(2026, 10, 6))
            self.assertEqual(len(jobs2), 2)


class AereTests(unittest.TestCase):
    def test_parse(self):
        jobs = aere.fetch(raw=AERE_HTML)
        self.assertEqual(len(jobs), 3)
        rff, duke, fudan = jobs
        self.assertEqual(rff.title, "Research Fellow (Early Career)")
        self.assertEqual(rff.institution, "Resources for the Future")
        self.assertEqual(rff.locations[0].state, "District of Columbia")
        self.assertEqual(rff.posted, "2026-09-21")
        self.assertEqual(duke.institution, "Duke University")
        self.assertEqual(duke.locations[0].state, "North Carolina")
        self.assertEqual(fudan.locations[0].country, "China")
        self.assertEqual(fudan.locations[0].city, "Shanghai")


if __name__ == "__main__":
    unittest.main()
