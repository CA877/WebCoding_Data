#!/usr/bin/env python3
"""Filter an existing construct project list to the final 40K-code contract."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from preprocess.pipeline_c.qwen_token_gate import count_project_tokens


def iter_projects(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if value and not value.startswith("#"):
                yield Path(value).resolve()


def temporary_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
    )
    handle.close()
    return Path(handle.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-list", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output-list", type=Path, required=True)
    parser.add_argument("--audit-jsonl", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=40_000)
    parser.add_argument(
        "--eligible-limit",
        type=int,
        default=0,
        help="Stop after this many eligible projects; zero scans the full list.",
    )
    parser.add_argument("--allow-missing-screenshot", action="store_true")
    args = parser.parse_args()

    if not args.tokenizer.is_file():
        parser.error(f"tokenizer does not exist: {args.tokenizer}")
    output_tmp = temporary_path(args.output_list)
    audit_tmp = temporary_path(args.audit_jsonl)
    checked = eligible = over_limit = errors = missing_screenshots = 0
    try:
        with output_tmp.open("w", encoding="utf-8") as output, audit_tmp.open(
            "w", encoding="utf-8"
        ) as audit:
            for project in iter_projects(args.project_list):
                checked += 1
                record = {"project": str(project)}
                try:
                    if not project.is_dir():
                        raise FileNotFoundError("project directory does not exist")
                    screenshots = sorted(project.glob(f"{project.name}*.png"))
                    record["screenshot_count"] = len(screenshots)
                    if not screenshots and not args.allow_missing_screenshot:
                        record["status"] = "missing_screenshot"
                        missing_screenshots += 1
                    else:
                        tokens = count_project_tokens(project, args.tokenizer)
                        record["tokens"] = tokens
                        if tokens <= args.max_tokens:
                            record["status"] = "eligible"
                            output.write(str(project) + "\n")
                            eligible += 1
                        else:
                            record["status"] = "over_token_limit"
                            over_limit += 1
                except Exception as exc:  # noqa: BLE001
                    record.update(
                        status="error", error=f"{type(exc).__name__}: {exc}"
                    )
                    errors += 1
                audit.write(json.dumps(record, ensure_ascii=False) + "\n")
                if checked % 100 == 0 or record.get("status") == "eligible":
                    print(
                        f"checked={checked} eligible={eligible} over={over_limit} "
                        f"missing_screenshot={missing_screenshots} errors={errors}"
                    )
                if args.eligible_limit and eligible >= args.eligible_limit:
                    break
        os.replace(output_tmp, args.output_list)
        os.replace(audit_tmp, args.audit_jsonl)
    finally:
        for temporary in (output_tmp, audit_tmp):
            if temporary.exists():
                temporary.unlink()
    print(
        json.dumps(
            {
                "checked": checked,
                "eligible": eligible,
                "over_token_limit": over_limit,
                "missing_screenshot": missing_screenshots,
                "errors": errors,
                "output_list": str(args.output_list),
                "audit_jsonl": str(args.audit_jsonl),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
