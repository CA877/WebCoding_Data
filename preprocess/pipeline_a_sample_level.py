#!/usr/bin/env python3
"""Backward-compatible wrapper — delegates to pipeline_a.main."""
import sys
from pathlib import Path

# Ensure preprocess/ is on sys.path for imports
_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from pipeline_a.main import main  # noqa: E402

if __name__ == "__main__":
    main()
