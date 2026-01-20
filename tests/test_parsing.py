from sales_workflow_cli import heuristic_extract

def test_timeline_and_bot_classification():
    text = """预算/时间线：
- 预算：希望先做 POC，预算大概 5-10 万 RMB
- 时间线：希望 2 周内给 POC 原型，1-2 个月内小范围试点上线
Nice-to-have：
- 可做成简单 bot（非必须）
"""
    fields = heuristic_extract(text)
    assert "2 周内" in fields["timeline"] or fields["timeline"].startswith("希望 2")
    assert "bot" in fields["nice_to_haves"]
    assert "bot" not in fields["must_haves"]
