#!/usr/bin/env python3
"""Create deterministic edit and repair project orders from the 40K gate."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path


def read_list(path: Path) -> list[str]:
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(values) != len(set(values)):
        raise ValueError("eligible list contains duplicate projects")
    return values


def write_list(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(value + "\n" for value in values), encoding="utf-8")


def distribution(size: int, seed: int) -> dict[str, int]:
    return dict(Counter(str(1 + ((index + seed) % 7)) for index in range(size)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eligible-list", type=Path, required=True)
    parser.add_argument("--edit-list", type=Path, required=True)
    parser.add_argument("--repair-list", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--edit-count", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=20260805)
    args = parser.parse_args()

    eligible = read_list(args.eligible_list)
    if not 0 < args.edit_count <= len(eligible):
        parser.error("edit-count must be within the eligible population")
    ordered = eligible.copy()
    random.Random(args.seed).shuffle(ordered)
    edit = ordered[: args.edit_count]
    repair = ordered
    write_list(args.edit_list, edit)
    write_list(args.repair_list, repair)
    manifest = {
        "source": str(args.eligible_list.resolve()),
        "seed": args.seed,
        "eligible_count": len(eligible),
        "edit_count": len(edit),
        "repair_candidate_count": len(repair),
        "edit_repair_overlap": len(set(edit) & set(repair)),
        "edit_task_count_distribution": distribution(len(edit), args.seed),
        "repair_task_count_distribution": distribution(len(repair), args.seed),
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
