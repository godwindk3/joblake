import unittest

from joblake.parsing.models import ParseContext
from joblake.parsing.parsers.itviec import ITviecParser
from joblake.parsing.parsers.topcv import TopCVParser
from joblake.parsing.validation import assess_parsed_job


def _context(source: str) -> ParseContext:
    return ParseContext(
        source=source,
        canonical_url=f"https://example.test/{source}/job-1",
        crawler_job_id=1,
        raw_object_id=2,
        fetched_at="2026-09-03T00:00:00+00:00",
    )


class ITviecParserTests(unittest.TestCase):

    def test_extracts_fields_and_removes_section_headings(self) -> None:
        html = """
        <html><body>
          <div class="job-header-info">
            <h1>Senior Data Engineer</h1>
            <div class="employer-name">Acme Vietnam</div>
          </div>
          <div class="itag bg-light-grey itag-sm cursor-default">Data</div>
          <div>Job Expertise:</div>
          <div><a data-controller="utm-tracking" href="/it-jobs/data">
            Data Engineering
          </a></div>
          <div class="imy-5 paragraph">
            <h2>Job description</h2><p>Build reliable pipelines.</p>
          </div>
          <div class="imy-5 paragraph">
            <h2>Your skills and experience</h2><p>Strong Python.</p>
          </div>
          <div>Skills:</div>
          <div>
            <a data-controller="utm-tracking" href="/it-jobs/python">Python</a>
            <a data-controller="utm-tracking" href="/it-jobs/sql">SQL</a>
          </div>
          <div class="imy-5 paragraph">
            <h2>Why you'll love working here</h2>
            <p>-</p><ul><li>Health insurance</li><li>Remote work</li></ul>
          </div>
        </body></html>
        """

        output = ITviecParser().parse(html, _context("itviec"))
        job = output.job

        self.assertEqual(job.title, "Senior Data Engineer")
        self.assertEqual(job.employer_name_raw, "Acme Vietnam")
        self.assertEqual(job.domains_raw, ("Data",))
        self.assertEqual(job.categories_raw, ("Data Engineering",))
        self.assertEqual(job.skills_raw, ("Python", "SQL"))
        self.assertEqual(job.description_text, "Build reliable pipelines.")
        self.assertEqual(job.requirements_text, "Strong Python.")
        self.assertNotIn("Why you'll love", job.benefits_text or "")
        self.assertNotIn("\n-\n", job.benefits_text or "")
        self.assertEqual(
            job.benefit_items,
            ("Health insurance", "Remote work"),
        )
        self.assertEqual(output.issues, ())


class TopCVParserTests(unittest.TestCase):

    def test_parses_normal_layout_with_tuple_fields(self) -> None:
        html = """
        <html><body>
          <div id="job-detail" data-job-title="Backend Engineer"></div>
          <div class="box-company-info__detail"><a class="name">Acme</a></div>
          <div class="ctn-breadcrumb-detail">
            <a>Trang chủ</a><a>IT</a><a>Backend Engineer</a>
          </div>
          <div class="job-tags__group">
            <span class="job-tags__group-name">Chuyên môn:</span>
            <a class="item">Backend</a>
          </div>
          <div class="box-job-information-detail-item">
            <h2 class="box-job-information-detail-item__title--title">
              Mô tả công việc
            </h2>
            <div class="box-job-information-detail-item__text">
              Mô tả công việc
              <p>Build APIs.</p>
            </div>
          </div>
          <div class="box-job-information-detail-item">
            <h2 class="box-job-information-detail-item__title--title">
              Yêu cầu ứng viên
            </h2>
            <div class="box-job-information-detail-item__text">Know Python.</div>
          </div>
          <div class="box-job-information-detail-item">
            <h2 class="box-job-information-detail-item__title--title">
              Quyền lợi ứng viên
            </h2>
            <div class="box-job-information-detail-item__text">Annual bonus.</div>
          </div>
        </body></html>
        """

        output = TopCVParser().parse(html, _context("topcv"))
        job = output.job

        self.assertEqual(job.source_variant, "normal")
        self.assertEqual(job.title, "Backend Engineer")
        self.assertEqual(job.employer_name_raw, "Acme")
        self.assertEqual(job.domains_raw, ("IT",))
        self.assertEqual(job.categories_raw, ("Backend",))
        self.assertEqual(job.description_text, "Build APIs.")
        self.assertEqual(job.skills_raw, ())
        self.assertEqual(assess_parsed_job(output).status, "partial")

    def test_parses_premium_layout_and_splits_domains(self) -> None:
        html = """
        <html><head><meta name="keywords" content="IT, Software, IT"></head>
        <body>
          <h2 class="premium-job-basic-information__content--title">
            Lead Engineer <span class="icon-verified-employer">Verified</span>
          </h2>
          <a class="company-content__name"><h1 class="title">Premium Co</h1></a>
          <div class="job-tags__group">
            <span class="job-tags__group-name">Chuyên môn:</span>
            <a class="item">Software Engineering</a>
          </div>
          <div class="premium-job-description__box">
            <h2 class="premium-job-description__box--title">Mô tả công việc</h2>
            <div class="premium-job-description__box--content">Lead a team.</div>
          </div>
          <div class="premium-job-description__box">
            <h2 class="premium-job-description__box--title">Yêu cầu ứng viên</h2>
            <div class="premium-job-description__box--content">Five years.</div>
          </div>
          <div class="premium-job-description__box">
            <h2 class="premium-job-description__box--title">Quyền lợi ứng viên</h2>
            <div class="premium-job-description__box--content">Stock options.</div>
          </div>
        </body></html>
        """

        output = TopCVParser().parse(html, _context("topcv"))
        job = output.job

        self.assertEqual(job.source_variant, "premium")
        self.assertEqual(job.title, "Lead Engineer")
        self.assertEqual(job.domains_raw, ("IT", "Software"))
        self.assertIsInstance(job.domains_raw, tuple)
        self.assertEqual(job.skills_raw, ())
        self.assertEqual(assess_parsed_job(output).status, "partial")

    def test_unknown_layout_returns_structured_error(self) -> None:
        output = TopCVParser().parse(
            "<html><body>not a job</body></html>",
            _context("topcv"),
        )

        self.assertEqual(output.job.source_variant, "unknown")
        self.assertEqual(len(output.issues), 1)
        self.assertEqual(output.issues[0].severity, "error")
        self.assertEqual(output.issues[0].code, "unknown_layout")
        self.assertEqual(assess_parsed_job(output).status, "rejected")


if __name__ == "__main__":
    unittest.main()
