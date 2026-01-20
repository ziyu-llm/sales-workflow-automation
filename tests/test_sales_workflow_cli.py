import unittest

from sales_workflow_cli import generate_followup_email


class GenerateFollowupEmailTests(unittest.TestCase):
    def test_empty_questions_fallbacks(self) -> None:
        fields = {
            "industry": "SaaS",
            "pain_points": [],
            "must_haves": [],
            "budget": "TBD",
            "timeline": "Q4",
            "open_questions": [],
        }
        scores = {"stage": "MQL-Discovery"}

        bilingual = generate_followup_email(fields, scores, "Ziyu", "BILINGUAL")
        self.assertIn("Quick questions / 需要确认的问题：", bilingual)
        self.assertIn("- None for now / 暂无", bilingual)

        zh = generate_followup_email(fields, scores, "Ziyu", "ZH")
        self.assertIn("需要进一步确认的问题：", zh)
        self.assertIn("- 暂无", zh)


if __name__ == "__main__":
    unittest.main()
