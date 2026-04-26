#!/usr/bin/env bash
# Run gather eval suite, commit results to depot, notify via Telegram.
set -euo pipefail

source /home/agent/.api-keys 2>/dev/null || true

REPORT_DIR="/home/agent/projects/agent-depot/evals"
TS=$(date -u +"%Y-%m-%dT%H%M%SZ")
REPORT="$REPORT_DIR/${TS}-gather-suite.md"
VENV="/home/agent/claude-stack-env/bin"

echo "[evals] Starting gather eval suite at $TS"

# Run pytest — dims 1-3 and 5 (skip slow LLM-judged dim 4 unless explicitly enabled)
cd /home/agent/projects/claude-power-search

SKIP_LLM_EVALS="${SKIP_LLM_EVALS:-1}" \
$VENV/python -m pytest evals/test_gather_eval.py \
  -v \
  --tb=short \
  --no-header \
  -p no:cacheprovider \
  2>&1 | tee /tmp/eval-run-$TS.txt

EXIT_CODE=${PIPESTATUS[0]}

# Parse results
PASSED=$(grep -oP '\d+(?= passed)' /tmp/eval-run-$TS.txt || echo "0")
FAILED=$(grep -oP '\d+(?= failed)' /tmp/eval-run-$TS.txt || echo "0")
ERRORS=$(grep -oP '\d+(?= error)' /tmp/eval-run-$TS.txt || echo "0")
TOTAL=$((PASSED + FAILED + ERRORS))
STATUS=$( [ "$EXIT_CODE" -eq 0 ] && echo "PASS" || echo "FAIL" )

# Build markdown report
cat > "$REPORT" << MDEOF
---
type: evals
title: Gather Eval Suite $TS
date: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
status: $STATUS
passed: $PASSED
failed: $FAILED
errors: $ERRORS
total: $TOTAL
---

# Gather Eval Suite — $TS

**Status:** $STATUS | **Score:** $PASSED/$TOTAL

## Raw Output

\`\`\`
$(cat /tmp/eval-run-$TS.txt)
\`\`\`
MDEOF

# Commit to depot + notify
cd /home/agent/projects/agent-depot
git add "evals/${TS}-gather-suite.md"
git commit -m "eval(gather-suite): $STATUS $PASSED/$TOTAL — $TS"

# Telegram notify
BOT_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
SUMMARY="*[evals]* Gather Suite Complete
Status: $STATUS
Score: $PASSED/$TOTAL passed
$([ "$FAILED" -gt 0 ] && echo "Failed: $FAILED" || true)

\`evals/${TS}-gather-suite.md\`"

# Send summary text
curl -s -X POST "$BOT_URL/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "text=${SUMMARY}" \
  -d "parse_mode=Markdown" > /dev/null

# Send report file
curl -s -X POST "$BOT_URL/sendDocument" \
  -F "chat_id=${TELEGRAM_CHAT_ID}" \
  -F "document=@${REPORT}" \
  -F "caption=Full eval report" > /dev/null

echo "[evals] Done. Report: $REPORT"
echo "[evals] Result: $STATUS $PASSED/$TOTAL"
