#!/usr/bin/env bash
set -e

# Usage:
#   ./demo.sh                # default chat1
#   ./demo.sh chat2          # run examples/chat2.txt -> out/chat2
#   ./demo.sh all            # run all examples/chat*.txt and print summary
#   ./demo.sh all --fresh    # reset DB + outputs before running all
#   ./demo.sh chat3 --out out/demo_3

INPUT="${1:-chat1}"
shift || true

OUT_DIR=""
DB="tracking.sqlite"
LANG="BILINGUAL"
OWNER="Ziyu"
FRESH="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fresh) FRESH="true"; shift ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --lang) LANG="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

python3 -m py_compile sales_workflow_cli.py

summarize_outdir () {
  python3 - "$1" <<'PY'
import json, sys
from pathlib import Path

out = Path(sys.argv[1])
fields = json.loads((out / "fields.json").read_text(encoding="utf-8"))
scores = json.loads((out / "scores.json").read_text(encoding="utf-8"))

chat = out.name
acct = fields.get("account_name", "Unknown")
industry = fields.get("industry", "Unknown")
seg = fields.get("business_model", "Unknown")
fit = scores.get("fit_score", "")
intent = scores.get("intent_score", "")
stage = scores.get("stage", "")
print(f"{chat}\t{acct}\t{industry}\t{seg}\t{fit}\t{intent}\t{stage}")
PY
}

run_one () {
  local input_path="$1"
  local out_dir="$2"

  echo "[RUN] $input_path -> $out_dir"
  python3 sales_workflow_cli.py run --input "$input_path" --out "$out_dir" --db "$DB" --lang "$LANG" --owner "$OWNER" >/dev/null
  python3 sales_workflow_cli.py export-crm --out "$out_dir" --format salesforce >/dev/null
}

# -------- all mode --------
if [[ "$INPUT" == "all" ]]; then
  if [[ "$FRESH" == "true" ]]; then
    rm -f "$DB"
    rm -rf out/chat* out/demo* out/all_summary 2>/dev/null || true
  fi

  echo -e "chat\taccount\tindustry\tsegment\tfit\tintent\tstage"
  for f in examples/chat*.txt; do
    base=$(basename "$f" .txt)
    od="out/${base}"
    rm -rf "$od" 2>/dev/null || true
    run_one "$f" "$od"
    summarize_outdir "$od"
  done

  echo ""
  echo "[HISTORY] last 10 runs:"
  python3 sales_workflow_cli.py history --db "$DB" --limit 10
  exit 0
fi

# -------- single mode --------
# If user passes "chat2" treat as examples/chat2.txt
if [[ "$INPUT" != *.txt ]]; then
  INPUT="examples/${INPUT}.txt"
fi

# Default out dir: out/<chatname>
if [[ -z "$OUT_DIR" ]]; then
  base=$(basename "$INPUT" .txt)
  OUT_DIR="out/${base}"
fi

if [[ "$FRESH" == "true" ]]; then
  rm -rf "$OUT_DIR"
  rm -f "$DB"
fi

run_one "$INPUT" "$OUT_DIR"

echo ""
echo "[REPORT] $OUT_DIR/report.md"
cat "$OUT_DIR/report.md"

echo ""
echo "[HISTORY] last 5 runs:"
python3 sales_workflow_cli.py history --db "$DB" --limit 5
