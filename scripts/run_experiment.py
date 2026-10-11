#!/usr/bin/env python3
"""Run the controlled experiment and write report.md. Thin wrapper around `gcsi experiment`.

Mock run (no key):      python scripts/run_experiment.py --seeds 20 --out results/mock
Size a real run:        python scripts/run_experiment.py --provider openai --seeds 5 --dry-run
Real run:               export GCSI_API_KEY=...   (read from the environment, never stored)
                        python scripts/run_experiment.py --provider openai --model gpt-4o-mini --seeds 5 \
                            --repeats 3 --temperature 0.7 --out results/real
Re-score offline:       rerun the same command; cached responses in results/real/llm_cache.jsonl are reused
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gcsi.cli import main

if __name__ == "__main__":
    main(["experiment", *sys.argv[1:]])
