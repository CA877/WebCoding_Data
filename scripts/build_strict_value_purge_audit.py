#!/usr/bin/env python3
"""Build a deliberately strict frontend-value purge audit."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    score_rows = {row["site"]: row for row in map(json.loads, args.scores.open())}
    names = {path.name for path in args.root.iterdir() if path.is_dir()}
    duplicate_www = {"www." + name for name in names if not name.startswith("www.") and "www." + name in names}
    counts: Counter[str] = Counter()
    rows = []
    for site in sorted(names):
        item = score_rows[site]
        features = item["features"]
        rich = (
            (features["media"] >= 5 and features["components"] >= 8)
            or (features["media"] >= 3 and features["components"] >= 20)
            or features["interactive"] >= 6
        )
        reasons = []
        if item["score"] <= 10 and not rich:
            reasons.append("below_strict_frontend_value_gate")
        if item["score"] <= 10 and item["prior_warnings"].get("link_farm_or_directory_page", 0) >= 4:
            reasons.append("low_value_link_directory_or_seo_page")
        if item["penalty_signals"].get("broken_resource_marker", 0) >= 2:
            reasons.append("repeated_broken_resources")
        if site in duplicate_www:
            reasons.append("duplicate_www_copy")
        reasons = sorted(set(reasons))
        counts.update(reasons)
        rows.append({
            "site": site, "status": "reject" if reasons else "pass", "reasons": reasons,
            "score": item["score"], "features": features,
        })
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"sites": len(rows), "reject": sum(row["status"] == "reject" for row in rows),
                      "pass": sum(row["status"] == "pass" for row in rows), "reasons": counts},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
