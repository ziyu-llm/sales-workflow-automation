from pathlib import Path

from sales_workflow_cli import generate_actions, heuristic_extract


def test_chat3_business_model_inferred_and_actions() -> None:
    text = Path("examples/chat3.txt").read_text(encoding="utf-8")
    fields = heuristic_extract(text)

    assert fields.get("business_model") == "Likely B2B (inferred)"
    assert any(
        "目前用的 CRM 是什么" in q or "Which CRM are you using" in q
        for q in fields.get("open_questions", [])
    )

    actions = generate_actions(fields, {"stage": "Early (Needs discovery)"})
    assert any("确认当前 CRM" in action or "Confirm current CRM" in action for action in actions)
