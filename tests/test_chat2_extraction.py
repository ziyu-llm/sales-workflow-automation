from pathlib import Path

from sales_workflow_cli import heuristic_extract


def test_chat2_industry_and_timeline() -> None:
    text = Path("examples/chat2.txt").read_text(encoding="utf-8")
    fields = heuristic_extract(text)

    industry = fields.get("industry", "")
    assert ("跨境物流" in industry) or ("物流" in industry)

    timeline = fields.get("timeline", "")
    assert ("两周" in timeline) or ("2 周" in timeline) or ("2周" in timeline)
