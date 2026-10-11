#!/usr/bin/env python3
"""Launch the Gradio interface. Thin wrapper around `gcsi ui`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gcsi.cli import main

if __name__ == "__main__":
    main(["ui", *sys.argv[1:]])
