#!/usr/bin/env python3
"""Generate labeled synthetic datasets. Thin wrapper around `gcsi synth`.

Example: python scripts/generate_synthetic_data.py --family all --n-seeds 3 --out data/synthetic
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gcsi.cli import main

if __name__ == "__main__":
    main(["synth", *sys.argv[1:]])
