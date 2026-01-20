from pathlib import Path

from sales_workflow_cli import heuristic_extract


def test_chat3_timeline_and_stakeholders() -> None:
    text = Path("examples/chat3.txt").read_text(encoding="utf-8")
    fields = heuristic_extract(text)

    timeline = fields.get("timeline", "")
    assert timeline and timeline != "Unknown"
    assert ("ASAP" in timeline) or ("越快越好" in timeline)

    stakeholders = fields.get("stakeholders", [])
    assert any("领导/管理层" in s for s in stakeholders)
