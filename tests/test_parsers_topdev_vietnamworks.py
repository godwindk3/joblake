import unittest

from joblake.parsing.models import ParseContext
from joblake.parsing.parsers.topdev import TopDevParser
from joblake.parsing.parsers.vietnamworks import VietnamWorksParser


def _context(source: str) -> ParseContext:
    return ParseContext(
        source=source,
        canonical_url=f"https://example.test/{source}/job-42",
        crawler_job_id=42,
        raw_object_id=84,
        fetched_at="2026-09-03T00:00:00+00:00",
    )


class TopDevParserTests(unittest.TestCase):

    def test_parses_graph_json_ld_and_html_sections(self) -> None:
        html = """
        <html><body>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@graph": [
              {"@type": "WebPage", "name": "Example"},
              {
                "@type": ["Thing", "JobPosting"],
                "identifier": {"value": "TD-42"},
                "title": "Platform Engineer",
                "hiringOrganization": {"name": "Example Co"},
                "industry": ["Information Technology", "Software"],
                "skills": "Python, Docker, Python",
                "description": "<p>JSON-LD fallback description</p>",
                "experienceRequirements": "<p>Three years</p>",
                "jobBenefits": "<ul><li>Insurance</li></ul>",
                "employmentType": "FULL_TIME",
                "datePosted": "2026-09-01T08:00:00+07:00",
                "validThrough": "2026-10-01T23:59:59+07:00",
                "baseSalary": {"currency": "VND", "value": 30000000},
                "jobLocation": {
                  "address": {
                    "addressLocality": "Hà Nội",
                    "addressCountry": "VN"
                  }
                }
              }
            ]
          }
          </script>
          <span>Your role &amp; responsibilities</span>
          <div><p>Build the platform</p><p>Operate it</p></div>
          <span>Your skills &amp; qualifications</span>
          <div><p>Strong Linux knowledge</p></div>
          <span>Benefits for you</span>
          <div><ul><li>Health insurance</li><li>Training</li></ul></div>
        </body></html>
        """

        output = TopDevParser().parse(html, _context("topdev"))
        job = output.job

        self.assertEqual(job.title, "Platform Engineer")
        self.assertEqual(job.employer_name_raw, "Example Co")
        self.assertEqual(
            job.domains_raw,
            ("Information Technology", "Software"),
        )
        self.assertEqual(job.skills_raw, ("Python", "Docker"))
        self.assertEqual(job.categories_raw, ("IT / Phần mềm",))
        self.assertIn("Build the platform", job.description_text or "")
        self.assertEqual(job.requirements_text, "Strong Linux knowledge")
        self.assertEqual(
            job.benefit_items,
            ("Health insurance", "Training"),
        )
        self.assertEqual(job.locations_raw, ("Hà Nội, VN",))
        self.assertEqual(job.source_external_job_id, "TD-42")
        self.assertEqual(job.posted_at.isoformat(), "2026-09-01T08:00:00+07:00")
        self.assertTrue(any(
            issue.code == "inferred_category"
            and issue.severity == "info"
            for issue in output.issues
        ))

    def test_uses_json_ld_description_when_html_section_is_absent(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "Backend Developer",
          "hiringOrganization": {"name": "Backend Co"},
          "description": "<p>Build APIs</p><p>Ship reliably</p>"
        }
        </script>
        """

        job = TopDevParser().parse(html, _context("topdev")).job

        self.assertEqual(job.description_text, "Build APIs\nShip reliably")


class VietnamWorksParserTests(unittest.TestCase):

    def test_parses_json_ld_html_domain_and_truncates_benefits(self) -> None:
        html = """
        <html><body>
          <script type="application/ld+json">
          {
            "@graph": [{
              "@type": "JobPosting",
              "identifier": {"name": "VW-99"},
              "title": "Data Engineer",
              "hiringOrganization": {"name": "Data Bank"},
              "industry": "Ngân hàng",
              "description": "<p>Build the data platform.</p>",
              "skills": [
                {"skillName": "Python"},
                {"name": "PostgreSQL"}
              ],
              "jobBenefits": "<ul><li>Annual bonus</li><li>Healthcare</li></ul>",
              "employmentType": ["FULL_TIME", "PERMANENT"],
              "datePosted": "2026-09-01",
              "validThrough": "2026-09-30T23:59:59+07:00",
              "jobLocation": [{
                "address": {
                  "streetAddress": "1 Main Street",
                  "addressLocality": "Hà Nội",
                  "addressCountry": "VN"
                }
              }]
            }]
          }
          </script>
          <section>
            <label>Ngành nghề</label>
            <p><span>Công Nghệ Thông Tin/Viễn Thông &gt; Dữ Liệu</span></p>
          </section>
          <h2>Yêu cầu công việc</h2>
          <div class="title-banner-c">Mức độ phù hợp</div>
          <div>
            <p>Ít nhất 3 năm kinh nghiệm.</p>
            <p>Thành thạo SQL.</p>
            <p>Vì sao đây là cơ hội đáng cân nhắc?</p>
            <p>Lương tháng 13.</p>
          </div>
        </body></html>
        """

        output = VietnamWorksParser().parse(
            html,
            _context("vietnamworks"),
        )
        job = output.job

        self.assertEqual(job.title, "Data Engineer")
        self.assertEqual(job.employer_name_raw, "Data Bank")
        self.assertEqual(
            job.domains_raw,
            ("Công Nghệ Thông Tin/Viễn Thông > Dữ Liệu",),
        )
        self.assertEqual(job.categories_raw, ("Ngân hàng",))
        self.assertEqual(job.skills_raw, ("Python", "PostgreSQL"))
        self.assertIn("Ít nhất 3 năm", job.requirements_text or "")
        self.assertNotIn("cơ hội đáng cân nhắc", job.requirements_text or "")
        self.assertNotIn("Lương tháng 13", job.requirements_text or "")
        self.assertEqual(
            job.benefit_items,
            ("Annual bonus", "Healthcare"),
        )
        self.assertEqual(
            job.benefits_text,
            "Annual bonus\nHealthcare",
        )
        self.assertEqual(
            job.locations_raw,
            ("1 Main Street, Hà Nội, VN",),
        )
        self.assertEqual(job.source_external_job_id, "VW-99")

    def test_parses_list_benefits_and_experience_fallback(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "QA Engineer",
          "hiringOrganization": {"name": "Quality Co"},
          "description": "<p>Test products</p>",
          "experienceRequirements": "<p>Two years of testing</p>",
          "jobBenefits": [
            {"benefitNameVI": "Bảo hiểm"},
            {"benefitName": "Training"}
          ]
        }
        </script>
        """

        job = VietnamWorksParser().parse(
            html,
            _context("vietnamworks"),
        ).job

        self.assertEqual(job.requirements_text, "Two years of testing")
        self.assertEqual(job.benefit_items, ("Bảo hiểm", "Training"))
        self.assertEqual(job.benefits_text, "Bảo hiểm\nTraining")


if __name__ == "__main__":
    unittest.main()
