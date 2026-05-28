#!/usr/bin/env python3
"""Compatibility wrapper for the split WebCode2M task constructors.

The seven task types are intentionally implemented in separate modules:

- construct_text_generation.py
- construct_image_generation.py
- construct_video_generation.py
- construct_text_editing.py
- construct_image_editing.py
- construct_text_repair.py
- construct_image_repair.py

Use construct_webcode2m_dataset.py as the thin orchestrator.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_webcode2m_dataset import main


if __name__ == "__main__":
    main()
