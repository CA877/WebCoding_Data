#!/usr/bin/env python3
"""Select promising strict-crawl candidates from real complexity measurements."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path


UNSAFE_PAGE_RE = re.compile(
    r"porn|adult|escort|casino|gambl|betting|sportsbook|poker|slots?|"
    r"payday loan|mail[ -]?order bride|dating site|mod apk|crack download", re.I
)


def is_technically_crawlable(row: dict) -> bool:
    return (
        row.get("status") == "ok"
        and (row.get("http_status") or 0) < 400
        and not row.get("challenge")
        and not UNSAFE_PAGE_RE.search(row.get("page_title", ""))
        and row.get("text_chars", 0) >= 300
        and row.get("request_count", 10**9) <= 180
        and row.get("third_party_request_count", 10**9) <= 50
        and row.get("js_css_transfer_bytes", 10**9) <= 250_000
        and row.get(
            "code_transfer_proxy_bytes",
            row.get("html_bytes", 0) + row.get("js_css_transfer_bytes", 10**9),
        ) <= 350_000
        and row.get("total_transfer_bytes", 10**9) <= 20_000_000
    )


def is_promising(row: dict) -> bool:
    """Keep pages that are both bounded enough to crawl and structurally rich."""
    return (
        is_technically_crawlable(row)
        and row.get("richness_score", 0) >= 8.0
        and len(row.get("component_types", [])) >= 4
        and row.get("interactive_control_count", 0) >= 1
    )


def score(row: dict) -> tuple:
    return (
        -row.get("richness_score", 0),
        -len(row.get("named_ui_patterns", [])),
        -row.get("interactive_control_count", 0),
        row.get("third_party_request_count", 10**9),
        row.get("js_css_transfer_bytes", 10**12),
        row.get("request_count", 10**9),
        row["url"],
    )


def structural_archetype(row: dict) -> str:
    counts = row.get("component_counts", {})
    patterns = set(row.get("named_ui_patterns", []))
    if counts.get("forms", 0) and counts.get("inputs", 0) >= 2:
        return "form_or_tool"
    if counts.get("tables", 0):
        return "data_or_table"
    if counts.get("images", 0) >= 8 or patterns & {"gallery", "portfolio", "product", "carousel", "slider"}:
        return "visual_gallery"
    if row.get("interactive_control_count", 0) >= 3 or patterns & {"tabs", "accordion", "dropdown", "modal"}:
        return "interactive_ui"
    if counts.get("sections", 0) >= 3 and counts.get("navigation", 0):
        return "sectioned_landing"
    return "structured_content"


def select_balanced(measured: list[dict], provenance: dict[str, dict], limit: int) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    promising = [row for row in measured if is_promising(row)]
    capability_frequency = Counter(
        capability
        for row in promising
        for capability in row.get("webcompass_edit_capabilities", [])
    )
    atomic_frequency = Counter(
        feature
        for row in promising
        for feature in row.get("atomic_ui_features", [])
    )
    for row in promising:
        archetype = structural_archetype(row)
        source = provenance.get(row["url"], {}).get("site_family", "unknown")
        capabilities = row.get("webcompass_edit_capabilities", [])
        if capabilities:
            fine_bucket = min(capabilities, key=lambda name: (capability_frequency[name], name))
        elif row.get("atomic_ui_features"):
            feature = min(row["atomic_ui_features"], key=lambda name: (atomic_frequency[name], name))
            fine_bucket = f"atomic:{feature}"
        else:
            fine_bucket = f"structure:{archetype}"
        candidate = {
            **row,
            "structural_archetype": archetype,
            "fine_capability_bucket": fine_bucket,
        }
        groups.setdefault((fine_bucket, source), []).append(candidate)
    for rows in groups.values():
        rows.sort(key=score)
    keys = sorted(groups)
    selected: list[dict] = []
    cursor = 0
    while len(selected) < limit and keys:
        key = keys[cursor % len(keys)]
        selected.append(groups[key].pop(0))
        if not groups[key]:
            keys.remove(key)
            cursor = 0
        else:
            cursor += 1
    return selected


def select_control(measured: list[dict], provenance: dict[str, dict], selected_urls: set[str],
                   limit: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_source: dict[str, list[dict]] = {}
    for row in measured:
        if row["url"] in selected_urls:
            continue
        source = provenance.get(row["url"], {}).get("source", "unknown")
        by_source.setdefault(source, []).append(row)
    for rows in by_source.values():
        rng.shuffle(rows)
    sources = sorted(by_source)
    selected: list[dict] = []
    while len(selected) < limit and any(by_source.values()):
        for source in sources:
            if by_source[source] and len(selected) < limit:
                selected.append(by_source[source].pop())
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-results", type=Path, required=True)
    parser.add_argument("--probe-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--control-limit", type=int, default=0)
    parser.add_argument("--control-seed", type=int, default=20260822)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    provenance: dict[str, dict] = {}
    for row in map(json.loads, args.probe_manifest.read_text(encoding="utf-8").splitlines()):
        provenance[row["url"]] = row
        if row.get("final_url"):
            provenance[row["final_url"]] = row
    measured = [json.loads(line) for line in args.probe_results.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted = select_balanced(measured, provenance, args.limit)
    control = select_control(
        measured, provenance, {row["url"] for row in accepted}, args.control_limit, args.control_seed
    )
    with (args.output_dir / "selected_manifest.jsonl").open("x", encoding="utf-8") as handle:
        for row in accepted:
            combined = {**provenance.get(row["url"], {}), "probe": row}
            handle.write(json.dumps(combined, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    with (args.output_dir / "selected_urls.txt").open("x", encoding="utf-8") as handle:
        for row in accepted:
            handle.write(row["url"] + "\n")
            handle.flush()
    if args.control_limit:
        with (args.output_dir / "control_manifest.jsonl").open("x", encoding="utf-8") as handle:
            for row in control:
                handle.write(json.dumps({**provenance.get(row["url"], {}), "probe": row}, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
        with (args.output_dir / "control_urls.txt").open("x", encoding="utf-8") as handle:
            for row in control:
                handle.write(row["url"] + "\n")
                handle.flush()
    summary = {
        "measured": len(measured),
        "probe_ok": sum(row.get("status") == "ok" for row in measured),
        "promising": sum(is_promising(row) for row in measured),
        "selected": len(accepted),
        "fine_capability_buckets": dict(Counter(row["fine_capability_bucket"] for row in accepted)),
        "webcompass_edit_capability_coverage": dict(Counter(
            capability for row in accepted for capability in row.get("webcompass_edit_capabilities", [])
        )),
        "atomic_ui_feature_coverage": dict(Counter(
            feature for row in accepted for feature in row.get("atomic_ui_features", [])
        )),
        "control_selected": len(control),
        "control_seed": args.control_seed if args.control_limit else None,
        "thresholds": {
            "min_text_chars": 300,
            "min_richness_score": 8.0,
            "min_component_types": 4,
            "min_interactive_controls": 1,
            "max_requests": 180,
            "max_third_party_requests": 50,
            "max_js_css_transfer_bytes": 250000,
            "max_code_transfer_proxy_bytes": 350000,
            "max_total_transfer_bytes": 20000000,
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
