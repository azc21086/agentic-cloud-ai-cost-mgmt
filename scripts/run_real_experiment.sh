#!/usr/bin/env bash
# End-to-end run of the GCSI experiment against a real model, from a fresh terminal.
#
#   bash run_real_experiment.sh                 # finds the repo in the usual places
#   bash run_real_experiment.sh /path/to/agentic-cloud-ai-cost-mgmt
#
# Optional settings (environment variables):
#   MODEL=gpt-4o-mini  FULL_SEEDS=5  REPEATS=3  TEMP=0.7  GCSI_BASE_URL=https://.../v1
#
# The key is typed once, hidden, cleaned of quotes and spaces, used in this process only,
# and never written to a file. The script stops if the small test shows the model is not working.
set -euo pipefail

PROVIDER="${PROVIDER:-openai}"          # "mock" is for testing the script itself
MODEL="${MODEL:-gpt-4o-mini}"
FULL_SEEDS="${FULL_SEEDS:-5}"
REPEATS="${REPEATS:-3}"
TEMP="${TEMP:-0.7}"
AUTO_YES="${AUTO_YES:-0}"

say() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# 1. find the repo -----------------------------------------------------------
REPO="${1:-}"
if [ -z "$REPO" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  for d in "$PWD" "$HERE" "$HOME/Downloads/agentic-cloud-ai-cost-mgmt" "$HOME/Desktop/agentic-cloud-ai-cost-mgmt" "$HOME/Documents/agentic-cloud-ai-cost-mgmt"; do
    if [ -f "$d/pyproject.toml" ] && grep -q "gcsi-governance" "$d/pyproject.toml"; then REPO="$d"; break; fi
  done
fi
[ -n "$REPO" ] && [ -f "$REPO/pyproject.toml" ] || die "could not find the repository folder. Run: bash run_real_experiment.sh /full/path/to/agentic-cloud-ai-cost-mgmt"
cd "$REPO"
say "Using repo: $PWD"

# 2. python environment ------------------------------------------------------
command -v python3 >/dev/null || die "python3 not found. Install Python 3.10 or newer from python.org."
python3 -c 'import sys; assert sys.version_info >= (3,10), sys.version' || die "Python 3.10 or newer is required."
if [ ! -d .venv ]; then say "Creating virtual environment"; python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
if ! python -c "import gcsi, openai, gradio" >/dev/null 2>&1; then
  say "Installing the package (one time, a minute or two)"
  pip install -q -e ".[all]"
fi
say "Running the unit tests"
python -m pytest -q | tail -2

# 3. the key -----------------------------------------------------------------
if [ "$PROVIDER" = "openai" ]; then
  if [ -z "${GCSI_API_KEY:-}" ]; then
    read -r -s -p "Paste your API key and press Enter (nothing will show): " GCSI_API_KEY
    echo
  fi
  # strip spaces, newlines and straight or curly quotes that terminals and documents add
  GCSI_API_KEY="$(printf '%s' "$GCSI_API_KEY" | python -c "import sys; s=sys.stdin.read(); print(''.join(c for c in s if not c.isspace() and c not in '\"\'‘’“”'), end='')")"
  export GCSI_API_KEY
  python - <<'PY' || die "the key contains non-ASCII characters or is too short. Copy it again from the provider's page."
import os, sys
k = os.environ.get("GCSI_API_KEY", "")
sys.exit(0 if (len(k) >= 20 and k.isascii()) else 1)
PY
  say "Key accepted (length ${#GCSI_API_KEY}, plain ASCII)"
fi

run() {  # run <out_dir> <extra args...>
  local out="$1"; shift
  python scripts/run_experiment.py --provider "$PROVIDER" --model "$MODEL" --out "$out" "$@"
}

validity() {  # prints the schema-valid percentage from a finished report
  python - "$1" <<'PY'
import csv, re, sys
for row in csv.reader(open(sys.argv[1] + "/table_E3_governance.csv")):
    if row and row[0].startswith("Schema and business"):
        print(re.match(r"[\d.]+", row[1]).group(0)); break
PY
}

# 4. small test --------------------------------------------------------------
say "Small test: 1 scenario, at most 20 live model calls"
rm -rf results/real_test
run results/real_test --families steady --seeds 1 --max-calls 20
PCT="$(validity results/real_test)"
say "Schema-valid responses in the small test: ${PCT}%"
if python -c "import sys; sys.exit(0 if float('$PCT') >= 50 else 1)"; then
  echo "The model connection works."
else
  echo "Fewer than half of the responses were valid. First stored errors, if any:"
  grep -o '"error": "[^"]*"' results/real_test/llm_cache.jsonl 2>/dev/null | sort | uniq -c | head -3 || true
  die "Stopping before the full run. Fix the key or model name (MODEL=...) and run again."
fi

# 5. confirm, then the full run ---------------------------------------------
say "Size of the full run"
python scripts/run_experiment.py --provider "$PROVIDER" --seeds "$FULL_SEEDS" --repeats "$REPEATS" --dry-run | head -4
if [ "$AUTO_YES" != "1" ]; then
  read -r -p "Start the full run now (15 to 30 minutes, keep this window open)? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Stopped. Rerun this script when ready."; exit 0;; esac
fi
say "Full run"
FULL_ARGS=(--seeds "$FULL_SEEDS" --repeats "$REPEATS" --temperature "$TEMP")
run results/real "${FULL_ARGS[@]}"

# 6. retry any calls that failed (errors are cached, so strip them and rerun once) --
ERRS="$(grep -c '"error": "' results/real/llm_cache.jsonl 2>/dev/null || true)"
if [ "${ERRS:-0}" -gt 0 ]; then
  say "$ERRS calls failed. Removing them from the cache and retrying once"
  grep -v '"error": "' results/real/llm_cache.jsonl > results/real/clean.jsonl && mv results/real/clean.jsonl results/real/llm_cache.jsonl
  run results/real "${FULL_ARGS[@]}"
  ERRS="$(grep -c '"error": "' results/real/llm_cache.jsonl 2>/dev/null || true)"
  echo "Failed calls remaining: ${ERRS:-0}"
fi

# 7. package the logs and check the key is not in them ------------------------
if [ "$PROVIDER" = "openai" ]; then
  python - <<'PY' || die "the API key was found inside the results folder. Do NOT share it. Tell Claude."
import os, pathlib, sys
k = os.environ["GCSI_API_KEY"]
bad = [str(p) for p in pathlib.Path("results/real").rglob("*") if p.is_file() and k in p.read_text(errors="ignore")]
sys.exit(1 if bad else 0)
PY
  say "Checked: the key does not appear in any results file"
fi
rm -f results/real_logs.zip
(cd results && zip -qr real_logs.zip real)
say "Done. Attach this file to the chat:"
echo "  $PWD/results/real_logs.zip"
echo "  Model used: $MODEL"
if [ "$PROVIDER" = "openai" ]; then unset GCSI_API_KEY; echo "  Key removed from this session."; fi
command -v open >/dev/null && open results || true
