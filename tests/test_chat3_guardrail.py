from pathlib import Path

from sales_workflow_cli import heuristic_extract


def test_chat3_company_name_guardrail() -> None:
    text = Path("examples/chat3.txt").read_text(encoding="utf-8")
    fields = heuristic_extract(text)

    account = fields.get("account_name")
    assert account in (None, "", "Unknown")

    open_questions = fields.get("open_questions", [])
    assert any(("公司名称" in q) or ("Company name" in q) for q in open_questions)
