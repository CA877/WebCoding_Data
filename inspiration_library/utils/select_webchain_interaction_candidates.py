#!/usr/bin/env python3
"""从**全部 31,675 条** WebChain 轨迹里挑一批「交互面宽」的候选，供抓 axTree 后复测。

为什么不用 `attributes.data.role` 那个代理：实测它与 axTree 上的真实交互广度
Pearson r = 0.076（n=100），排序不可信，已弃用。

改用**权威字段** `step.type`（轨迹自己记录的动作类型）：
- `stateful`：`type` / `select` / `drag` / `press_enter` / `paste` / `double_click`，
  即「需要跟控件来回交互才做得出来」的动作，而不是纯点击。
- 排序按 (stateful 种类数, 交互步数)，再按站点轮转取样，保证候选不集中在少数站。

这是**抓取目标筛选**，不是研究结论；真实广度用
`measure_webchain_interaction_breadth.py` 在 axTree 上复算。

用法：
  uv run python inspiration_library/utils/select_webchain_interaction_candidates.py \\
      --index datasets/webchain_explore/trajectory_index.jsonl \\
      --raw-dir datasets/webchain_explore/raw/extracted/all_json_files \\
      --count 48 --out datasets/webchain_explore/candidates_48.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STATEFUL_ACTIONS = {"type", "select", "drag", "press_enter", "paste", "double_click"}


def richness(row: dict) -> tuple[int, int]:
    """(状态化动作种类数, 交互步数)。"""
    types = set((row.get("action_types") or {})) - {"launchApp"}
    return len(types & STATEFUL_ACTIONS), int(row.get("n_interaction_steps") or 0)


def rank_candidates(rows: Iterable[dict], *, min_stateful: int = 2, min_steps: int = 10) -> list[dict]:
    """按丰富度降序排，并过滤掉状态化动作太少的。"""
    kept = [row for row in rows if richness(row)[0] >= min_stateful and richness(row)[1] >= min_steps]
    return sorted(kept, key=lambda row: (richness(row), row.get("n_interaction_steps") or 0),
                  reverse=True)


def round_robin_by_host(rows: list[dict], count: int) -> list[dict]:
    """按站点轮转取 count 条，避免候选挤在少数站。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("primary_host") or "")].append(row)
    picked: list[dict] = []
    while len(picked) < count:
        progressed = False
        for host in sorted(buckets):
            if not buckets[host]:
                continue
            picked.append(buckets[host].pop(0))
            progressed = True
            if len(picked) >= count:
                break
        if not progressed:
            break
    return picked


def load_trajectory(raw_dir: Path, src_file: str, traj_id: str, cache: dict) -> dict | None:
    if src_file not in cache:
        path = raw_dir / src_file
        cache[src_file] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if len(cache) > 4:                      # 只缓存少量文件，避免把 934 MB 全读进内存
            cache.pop(next(iter(cache)))
    return next((t for t in cache[src_file] if t.get("id") == traj_id), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--count", type=int, default=48)
    ap.add_argument("--min-stateful", type=int, default=2)
    ap.add_argument("--min-steps", type=int, default=10)
    args = ap.parse_args()

    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    ranked = rank_candidates(rows, min_stateful=args.min_stateful, min_steps=args.min_steps)
    picked = round_robin_by_host(ranked, args.count)
    print(f"{len(rows)} total -> {len(ranked)} pass filter -> {len(picked)} picked")

    cache: dict[str, Any] = {}
    written = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in picked:
            trajectory = load_trajectory(args.raw_dir, row["src_file"], row["traj_id"], cache)
            if trajectory is None:
                print(f"  MISSING {row['traj_id']} in {row['src_file']}", file=sys.stderr)
                continue
            fh.write(json.dumps({"summary": row, "trajectory": trajectory},
                                ensure_ascii=False) + "\n")
            written += 1
    print(f"{written} candidates -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
