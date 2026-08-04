#!/usr/bin/env python3
"""Expand sparse-page review decisions into a complete safe apply-audit file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--training-value-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decisions = {
        row["site"]: row for row in map(json.loads, args.training_value_audit.open())
        if row.get("status") == "reject"
    }
    sites = sorted(path.name for path in args.root.iterdir() if path.is_dir())
    with args.output.open("w", encoding="utf-8") as handle:
        for site in sites:
            decision = decisions.get(site)
            handle.write(json.dumps({
                "site": site,
                "status": "reject" if decision else "pass",
                "reasons": decision.get("reasons", []) if decision else [],
                "features": decision.get("features", {}) if decision else {},
            }, ensure_ascii=False) + "\n")
    print(json.dumps({"sites": len(sites), "reject": len(decisions), "pass": len(sites) - len(decisions)}))


if __name__ == "__main__":
    main()
