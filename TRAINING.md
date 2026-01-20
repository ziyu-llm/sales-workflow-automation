# Sales Workflow Agent — Training Guide

## What this tool does
Paste customer communication text (email/chat/meeting notes). The tool will:
1) Extract key requirements into a structured summary
2) Score and stage the lead (Fit / Intent)
3) Suggest next actions
4) Generate a follow-up email you can copy-paste
5) Log each run for tracking and weekly review

## When to use
- After a discovery call
- After receiving an inbound email inquiry
- When you need a standardized weekly pipeline update

## 3-step usage
1) Save the text as a `.txt` file (or use stdin)
2) Run:
```bash
python sales_workflow_cli.py run --input <file.txt> --out <out_dir> --db tracking.sqlite
```
3) Open:
- `<out_dir>/report.md` and copy the email / next steps

## How to read the output
- Fit score: how well the lead matches our typical workflow automation use-cases
- Intent score: how likely they are to move forward (budget/timeline clarity)
- Stage:
  - SQL: high priority, propose POC plan this week
  - MQL: nurture, clarify missing info
  - Early: discovery needed

## Data & compliance
- Do not paste: ID cards, bank cards, full addresses, or other sensitive information
- The tool will attempt to redact emails/phones automatically, but always double-check before sharing

## FAQ
- Missing budget? The tool will list clarification questions—send those in your follow-up.
- Output looks off? Add 2–3 lines of context (industry, timeline, CRM, stakeholders) and rerun.
