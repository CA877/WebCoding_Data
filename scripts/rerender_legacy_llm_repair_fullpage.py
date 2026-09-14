#!/usr/bin/env python3
"""Normalize legacy LLM image-repair defects to canonical full-page renders."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    screenshot_project_to_dir,
    write_code_bundle_from_source,
)
from reverse.construct_text_repair import _full_page_difference


RULE_ENGINE = "deterministic-rule-injector-v1"
VIEWPORT = [("desktop", 1920, 1080)]


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_jsonl(path: Path, records: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def render_one(record: dict, browser_proxy: str, minimum_ratio: float) -> dict:
    instance_id = str(record["instance_id"])
    project = Path(str(record["metadata"]["source_project"]))
    canonical = project / f"{instance_id}_clean.png"
    if not canonical.is_file():
        raise FileNotFoundError(canonical)
    old_source = Path(str(record["src_screenshot"][0]))
    defect_dir = old_source.parent
    with tempfile.TemporaryDirectory(prefix="legacy-llm-fullpage-") as temporary:
        broken = Path(temporary) / "broken"
        write_code_bundle_from_source(project, record["input_files"], broken)
        raw = screenshot_project_to_dir(
            broken, defect_dir, browser_proxy, viewports=VIEWPORT, full_page=True,
            index_only=True,
        )
    screens = [
        {**item, "path": str((defect_dir / Path(item["path"]).name).resolve())}
        for item in raw
    ]
    screen = next((item for item in screens if item.get("page") == "index.html"), screens[0])
    visual = _full_page_difference(str(canonical.resolve()), screen["path"])
    visual["minimum_changed_ratio"] = minimum_ratio
    visual["clean_rerender_max_changed_ratio"] = 0.0
    return {
        "instance_id": instance_id,
        "eligible": visual["max_changed_ratio"] >= minimum_ratio,
        "defect": screen,
        "clean": {"path": str(canonical.resolve()), "kind": "shared_image_generate_full_page"},
        "visual": visual,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--browser-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--minimum-changed-ratio", type=float, default=0.01)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    repair = args.production_root / "repair"
    image_path = repair / "image-repair.v2.jsonl"
    text_path = repair / "text-repair.v2.jsonl"
    raw_path = repair / "records.jsonl"
    images = load_jsonl(image_path)
    legacy = [
        record for record in images
        if record.get("metadata", {}).get("construction_model") != RULE_ENGINE
        and record.get("metadata", {}).get("screenshot_protocol") != "desktop_1920_full_page"
    ]
    print(f"legacy LLM full-page rerender: {len(legacy)} records, {args.workers} workers", flush=True)
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(render_one, record, args.browser_proxy, args.minimum_changed_ratio): record
            for record in legacy
        }
        for index, future in enumerate(as_completed(futures), 1):
            instance_id = str(futures[future]["instance_id"])
            try:
                result = future.result()
                results[instance_id] = result
            except Exception as exc:  # noqa: BLE001
                errors[instance_id] = f"{type(exc).__name__}: {exc}"
            if index % 100 == 0 or index == len(futures):
                passed = sum(item["eligible"] for item in results.values())
                print(f"rendered {index}/{len(futures)} eligible={passed} errors={len(errors)}", flush=True)

    # Any failed/sub-threshold legacy sample is removed from image-repair and
    # later replaced by the supervised rule constructor.  It remains a valid
    # text-repair sample.
    retained_images: list[dict] = []
    for record in images:
        instance_id = str(record["instance_id"])
        if instance_id in results:
            result = results[instance_id]
            if not result["eligible"]:
                continue
            record["input_images"] = [result["defect"]["path"]]
            record["src_screenshot"] = [result["defect"]["path"]]
            record["dst_screenshot"] = [result["clean"]["path"]]
            metadata = record.setdefault("metadata", {})
            metadata.update({
                "bug_injection_method": "llm",
                "bug_injection_engine": metadata.get("construction_model", ""),
                "screenshot_viewport": "desktop_1920_full_page",
                "screenshot_protocol": "desktop_1920_full_page",
                "clean_image_shared_with": "image-generation",
                "visual_difference": result["visual"],
            })
        elif instance_id in errors:
            continue
        retained_images.append(record)

    result_ids = set(results) | set(errors)
    texts = load_jsonl(text_path)
    for record in texts:
        instance_id = str(record["instance_id"])
        if instance_id not in result_ids:
            continue
        metadata = record.setdefault("metadata", {})
        metadata.update({
            "bug_injection_method": "llm",
            "bug_injection_engine": metadata.get("construction_model", ""),
            "image_repair_eligible": bool(results.get(instance_id, {}).get("eligible", False)),
        })
        if instance_id in results:
            metadata["visual_difference"] = results[instance_id]["visual"]

    raw = load_jsonl(raw_path)
    for record in raw:
        instance_id = str(record.get("instance_id", ""))
        if instance_id not in result_ids:
            continue
        if instance_id in results:
            result = results[instance_id]
            record["images"] = {
                "src_screenshot": [result["defect"]],
                "dst_screenshot": [result["clean"]],
            }
            record["visual_difference"] = result["visual"]
            record["image_repair_eligible"] = result["eligible"]
        else:
            record["image_repair_eligible"] = False

    atomic_jsonl(image_path, retained_images)
    atomic_jsonl(text_path, texts)
    atomic_jsonl(raw_path, raw)
    summary = {
        "legacy_input": len(legacy),
        "rendered": len(results),
        "eligible": sum(item["eligible"] for item in results.values()),
        "subthreshold": sum(not item["eligible"] for item in results.values()),
        "errors": len(errors),
        "image_repair_after": len(retained_images),
        "error_examples": dict(list(errors.items())[:20]),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
