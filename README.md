# Sales Workflow CLI

## Overview
A Python CLI for sales enablement workflows. It parses inbound emails, chat logs, or meeting notes into structured lead summaries, next actions, a bilingual follow-up email, and a CRM upsert payload. Extraction is heuristic/rule-based by default; no external services are required.

## Requirements
- Python 3.10+
- macOS/Linux with bash

## What it does
- Extracts lead fields: account, industry, use case, budget, timeline, pain points, must-haves, stakeholders
- Generates next actions and a bilingual follow-up email
- Scores and stages leads and writes a one-page report
- Produces Salesforce-compatible upsert payloads (create/update-ready JSON)
- Logs runs to SQLite for auditability

## Engineering highlights
- Rule-based extraction aligned with `schemas/lead_schema.json`
- Template assets in `prompts/extract.txt` and `prompts/email.txt`
- PII redaction before output artifacts are written
- Deterministic, offline-friendly execution
- Pytest regression coverage for key examples

## Quickstart
```bash
pip install -r requirements.txt
chmod +x demo.sh
./demo.sh all --fresh
python3 -m pytest
```

## Usage
- Batch run all examples and reset outputs/DB: `./demo.sh all --fresh`
- Single run: `python3 sales_workflow_cli.py run --input <file> --out <dir> --db tracking.sqlite --lang BILINGUAL --owner <name>`
- Export CRM payload: `python3 sales_workflow_cli.py export-crm --out <dir> --format salesforce`
- View run history: `python3 sales_workflow_cli.py history --db tracking.sqlite --limit <n>`

## Output artifacts
Each run writes core artifacts to `out/<case>/`:
- `report.md` one-page summary, next actions, follow-up email
- `fields.json` structured lead fields (PII redacted)
- `scores.json` fit/intent scores and stage

CRM payloads are generated as `crm_payload.json` during a run and/or via `export-crm`, depending on script usage and configuration. No external API calls are made.

## Testing
```bash
python3 -m pytest
```

## Security/Data handling
- PII redaction is enabled by default (see `config.json`).
- Example inputs are synthetic.
- Output folders and run history are ignored by git: `out/` and `tracking.sqlite`.

## Customization
- Heuristics live in `sales_workflow_cli.py` (see `heuristic_extract`).
- Scoring, stages, and redaction are configured in `config.json`.
- Schemas and prompt templates are in `schemas/` and `prompts/`.
- To integrate an LLM later, keep the same schema and run tracking so outputs remain comparable.
