#!/usr/bin/env python3
"""Run the anomaly detectors on a dataset. Thin wrapper around `gcsi detect`.

Examples
  python scripts/detect_anomalies.py --input data/sample --min-abs 0.5 --scale-floor 0.2
  python scripts/detect_anomalies.py --input path/to/focus.csv --format focus
  python scripts/detect_anomalies.py --input data/synthetic/steady_1000/panel.csv --format panel
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gcsi.cli import main

if __name__ == "__main__":
    main(["detect", *sys.argv[1:]])
