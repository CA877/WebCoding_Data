#!/usr/bin/env python3
"""Run the unified WebCoding release quality gate.

This is a thin CLI over utils/webcoding_pipeline so existing scripts can keep
their specialized jobs while the final release gate has one shared implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.webcoding_pipeline import run_release_quality_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run WebCoding full release quality pipeline")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--skip-image-open", action="store_true")
    parser.add_argument("--allow-missing-output-files", action="store_true")
    args = parser.parse_args()

    report = run_release_quality_pipeline(
        args.release_root,
        args.out_dir,
        check_images=not args.skip_image_open,
        require_output_files=not args.allow_missing_output_files,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
