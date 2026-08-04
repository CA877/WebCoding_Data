#!/usr/bin/env python3
"""Sample image-repair before/after screenshot differences.

The script compares referenced src_screenshot and dst_screenshot pairs. It does
not evaluate semantic repair quality; it only measures pixel-level visual change.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from statistics import mean, median
from typing import Any

from PIL import Image, ImageChops, ImageStat


def read_jsonl(path: Path):
    with path.open("rb") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if raw.strip():
                yield line_no, json.loads(raw)


def first_path(record: dict[str, Any], key: str) -> str:
    values = record.get(key) or []
    return values[0] if values and isinstance(values[0], str) else ""


def resolve_image(release_root: Path, rel: str) -> Path:
    # In this release, image-repair records store paths like
    # images/{instance_id}/src_screenshots/screenshot_index.jpg, relative to
    # images/image-repair.
    return release_root / "images" / "image-repair" / rel


def diff_metrics(src_path: Path, dst_path: Path, resize: int) -> dict[str, float | int | str]:
    with Image.open(src_path) as src_raw, Image.open(dst_path) as dst_raw:
        src_size = src_raw.size
        dst_size = dst_raw.size
        src = src_raw.convert("RGB").resize((resize, resize))
        dst = dst_raw.convert("RGB").resize((resize, resize))
        diff = ImageChops.difference(src, dst)
        stat = ImageStat.Stat(diff)
        mean_abs = sum(stat.mean) / (len(stat.mean) * 255.0)
        rms = (sum(v * v for v in stat.rms) / len(stat.rms)) ** 0.5 / 255.0
        extrema = diff.getextrema()
        changed = 0
        total = resize * resize
        # Count a pixel as changed if any RGB channel changes by at least 8/255.
        for pixel in diff.getdata():
            if max(pixel) >= 8:
                changed += 1
        return {
            "src_width": src_size[0],
            "src_height": src_size[1],
            "dst_width": dst_size[0],
            "dst_height": dst_size[1],
            "mean_abs_diff": float(mean_abs),
            "rms_diff": float(rms),
            "changed_pixel_ratio": changed / total,
            "max_channel_diff": max(high for _low, high in extrema),
        }


def bucket(score: float) -> str:
    if score < 0.005:
        return "near_identical_lt_0.005"
    if score < 0.01:
        return "very_low_0.005_0.01"
    if score < 0.02:
        return "low_0.01_0.02"
    if score < 0.05:
        return "moderate_0.02_0.05"
    if score < 0.10:
        return "clear_0.05_0.10"
    return "large_ge_0.10"


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def pct(q: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
        return ordered[index]

    return {
        "min": ordered[0],
        "p10": pct(0.10),
        "p25": pct(0.25),
        "median": median(ordered),
        "mean": mean(ordered),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "max": ordered[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260630)
    parser.add_argument("--resize", type=int, default=256)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    jsonl_path = args.release_root / "jsonl" / "image-repair.jsonl"
    eligible: list[tuple[int, dict[str, Any]]] = []
    missing_dst = 0
    total = 0
    for line_no, record in read_jsonl(jsonl_path):
        total += 1
        if first_path(record, "src_screenshot") and first_path(record, "dst_screenshot"):
            eligible.append((line_no, record))
        else:
            missing_dst += 1

    rng = random.Random(args.seed)
    sampled = eligible[:]
    rng.shuffle(sampled)
    sampled = sampled[: args.sample_size]

    rows = []
    status_counts: dict[str, int] = {}
    for line_no, record in sampled:
        instance_id = record.get("instance_id") or f"line_{line_no}"
        src_rel = first_path(record, "src_screenshot")
        dst_rel = first_path(record, "dst_screenshot")
        src_path = resolve_image(args.release_root, src_rel)
        dst_path = resolve_image(args.release_root, dst_rel)
        row: dict[str, Any] = {
            "line": line_no,
            "instance_id": instance_id,
            "src_screenshot": src_rel,
            "dst_screenshot": dst_rel,
        }
        if not src_path.exists():
            row["status"] = "src_missing"
        elif not dst_path.exists():
            row["status"] = "dst_missing"
        elif src_path.stat().st_size == 0:
            row["status"] = "src_empty"
        elif dst_path.stat().st_size == 0:
            row["status"] = "dst_empty"
        else:
            try:
                row.update(diff_metrics(src_path, dst_path, args.resize))
                row["bucket"] = bucket(float(row["rms_diff"]))
                row["status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                row["status"] = "decode_or_diff_failed"
                row["error"] = f"{type(exc).__name__}: {exc}"
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        rows.append(row)

    ok_rows = [row for row in rows if row.get("status") == "ok"]
    rms_values = [float(row["rms_diff"]) for row in ok_rows]
    mean_values = [float(row["mean_abs_diff"]) for row in ok_rows]
    changed_values = [float(row["changed_pixel_ratio"]) for row in ok_rows]
    bucket_counts: dict[str, int] = {}
    for row in ok_rows:
        key = str(row["bucket"])
        bucket_counts[key] = bucket_counts.get(key, 0) + 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "release_root": str(args.release_root),
        "jsonl": str(jsonl_path),
        "total_records": total,
        "eligible_with_src_and_dst": len(eligible),
        "missing_src_or_dst": total - len(eligible),
        "missing_dst_screenshot": missing_dst,
        "sample_size_requested": args.sample_size,
        "sample_size_actual": len(sampled),
        "seed": args.seed,
        "resize": args.resize,
        "status_counts": status_counts,
        "bucket_counts_by_rms": bucket_counts,
        "rms_diff_summary": summarize(rms_values),
        "mean_abs_diff_summary": summarize(mean_values),
        "changed_pixel_ratio_summary": summarize(changed_values),
        "lowest_rms_examples": sorted(ok_rows, key=lambda x: float(x["rms_diff"]))[:30],
        "highest_rms_examples": sorted(ok_rows, key=lambda x: float(x["rms_diff"]), reverse=True)[:10],
    }
    (args.out_dir / "image_repair_diff_sample_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "image_repair_diff_sample_rows.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [
        "# Image Repair Diff Sample",
        "",
        f"- release root: `{args.release_root}`",
        f"- total records: {total}",
        f"- eligible with src/dst: {len(eligible)}",
        f"- sampled: {len(sampled)}",
        f"- seed: {args.seed}",
        "",
        "## Status",
        "",
        "| status | count | ratio in sample |",
        "|---|---:|---:|",
    ]
    for key, value in sorted(status_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| `{key}` | {value} | {value / max(1, len(sampled)):.2%} |")
    lines.extend(["", "## RMS Diff Buckets", "", "| bucket | count | ratio among ok |", "|---|---:|---:|"])
    for key, value in sorted(bucket_counts.items()):
        lines.append(f"| `{key}` | {value} | {value / max(1, len(ok_rows)):.2%} |")
    lines.extend(["", "## Numeric Summary", ""])
    for name, values in [
        ("rms_diff", summary["rms_diff_summary"]),
        ("mean_abs_diff", summary["mean_abs_diff_summary"]),
        ("changed_pixel_ratio", summary["changed_pixel_ratio_summary"]),
    ]:
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| min | p10 | p25 | median | mean | p75 | p90 | max |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        if values:
            lines.append(
                f"| {values['min']:.6f} | {values['p10']:.6f} | {values['p25']:.6f} | "
                f"{values['median']:.6f} | {values['mean']:.6f} | {values['p75']:.6f} | "
                f"{values['p90']:.6f} | {values['max']:.6f} |"
            )
        lines.append("")
    lines.extend(["## Lowest RMS Examples", "", "| instance_id | rms | mean_abs | changed_pixels | bucket |", "|---|---:|---:|---:|---|"])
    for row in summary["lowest_rms_examples"][:20]:
        lines.append(
            f"| `{row['instance_id']}` | {row['rms_diff']:.6f} | {row['mean_abs_diff']:.6f} | "
            f"{row['changed_pixel_ratio']:.2%} | `{row['bucket']}` |"
        )
    (args.out_dir / "image_repair_diff_sample.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "sampled": len(sampled), "ok": len(ok_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
