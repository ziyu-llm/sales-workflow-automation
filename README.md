# Sales Workflow Agent (CLI MVP)

A lightweight internal-tool style demo for Sales teams:
- Input: customer emails / chat logs / meeting notes (plain text)
- Output: structured lead fields + scoring/stage + next actions + follow-up email
- Tracking: SQLite audit trail for ops iteration
- Optional: export a CRM-friendly payload (Salesforce-style mapping)

## Quickstart

```bash
python sales_workflow_cli.py --help
python sales_workflow_cli.py run --input examples/chat1.txt --out out/lead_001 --db tracking.sqlite
cat out/lead_001/report.md
python sales_workflow_cli.py export-crm --out out/lead_001 --format salesforce
python sales_workflow_cli.py history --db tracking.sqlite --limit 5
```

## Outputs

- `fields.json`  structured lead fields (PII redacted)
- `scores.json`  fit/intent scores + stage
- `report.md`    one-page sales-ready summary + next actions + follow-up email
- `crm_payload.json` (from export-crm) payload for CRM upsert integration

## Notes

This repo ships with a heuristic extractor by default (runs offline).
To plug in a real LLM, edit `call_llm()` in `sales_workflow_cli.py`.
