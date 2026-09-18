#!/usr/bin/env python3
"""在**不抓 axTree** 的前提下，从全部 WebChain 轨迹里筛出「交互面最宽」的候选。

动机：axTree 是从 `data.imean.tech` 逐个抓的，成本高；要挑候选先得有个便宜的代理。
WebChain 的轨迹步里其实已经带了被执行元素的元信息：

    step["attributes"]["data"]["role"]              -> 该元素的 ARIA role（combobox/tab/slider…）
    step["attributes"]["data"]["node"]["name"]      -> 该元素的 HTML 标签（INPUT/SELECT/BUTTON…）
    step["type"]                                    -> 动作类型（type/select/drag/hover…）

于是「这条轨迹唤醒过多少种前端交互」可以在本地全量算出来。

**这是筛选代理，不是研究结论。** 它只用来决定「给哪些轨迹抓 axTree」；真正的交互广度
用 `measure_webchain_interaction_breadth.py` 在 axTree 上复算。

排序口径（不做加权，按元组从宽到窄）：
    (有信号的 role 种类数, 有信号的标签种类数, 非点击动作种类数, 交互步数)

用法：
  uv run python inspiration_library/utils/rank_webchain_candidates.py \\
      --raw-dir datasets/webchain_explore/raw/extracted/all_json_files \\
      --out datasets/webchain_explore/candidates_all.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inspiration_library.trajectory_capability_adapter import INTERACTIVE_ROLES

# 有信息量的 HTML 标签：能体现「表单/媒体/富组件」这类超出纯点击的功能设计。
# BUTTON/A/SPAN/DIV/IMG 到处都是，区分度低，不计入信号。
SIGNAL_TAGS = {
    "input", "select", "textarea", "option", "label", "form", "canvas", "video",
    "audio", "dialog", "details", "summary", "progress", "meter", "output", "datalist",
}
CLICK_LIKE = {"click", "double_click", "right_click", "launchApp"}


def step_metadata(step: dict) -> tuple[str, str]:
    """取一步动作被执行元素的 (aria role, html tag)，都归一化成小写。"""
    data = (step.get("attributes") or {}).get("data") or {}
    role = str(data.get("role") or "").strip().lower()
    tag = str((data.get("node") or {}).get("name") or "").strip().lower()
    return role, tag


def candidate_signals(trajectory: dict) -> dict[str, Any]:
    """算一条轨迹的候选信号。纯函数，不读磁盘。"""
    steps = trajectory.get("steps") or []
    roles: set[str] = set()
    tags: set[str] = set()
    signal_tags: set[str] = set()
    action_types: dict[str, int] = {}
    focused_roles: set[str] = set()          # 状态化动作（type/select）打到的控件

    for step in steps:
        action = str(step.get("type") or "unknown")
        action_types[action] = action_types.get(action, 0) + 1
        if step.get("axtId") is None and not (step.get("attributes") or {}).get("data"):
            continue
        role, tag = step_metadata(step)
        if role in INTERACTIVE_ROLES:
            roles.add(role)
            if action not in CLICK_LIKE:
                focused_roles.add(role)
        if tag:
            tags.add(tag)
            if tag in SIGNAL_TAGS:
                signal_tags.add(tag)

    non_click = {key for key in action_types if key not in CLICK_LIKE}
    return {
        "roles_touched": sorted(roles),
        "signal_tags_touched": sorted(signal_tags),
        "tags_touched": sorted(tags),
        "stateful_roles_touched": sorted(focused_roles),
        "action_types": action_types,
        "n_roles_touched": len(roles),
        "n_signal_tags_touched": len(signal_tags),
        "n_non_click_actions": len(non_click),
        "n_interaction_steps": sum(value for key, value in action_types.items() if key != "launchApp"),
    }


def rank_key(row: dict) -> tuple[int, int, int, int]:
    return (row["n_roles_touched"], row["n_signal_tags_touched"],
            row["n_non_click_actions"], row["n_interaction_steps"])


def iter_trajectories(raw_dir: Path) -> Iterable[dict]:
    for path in sorted(raw_dir.glob("*.json")):
        for trajectory in json.loads(path.read_text(encoding="utf-8")):
            trajectory.setdefault("_src_file", path.name)
            yield trajectory


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--top", type=int, default=40, help="打印前 N 条的摘要")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with args.out.open("w", encoding="utf-8") as fh:
        for trajectory in iter_trajectories(args.raw_dir):
            steps = trajectory.get("steps") or []
            record = {
                "traj_id": trajectory.get("id"),
                "title": str(trajectory.get("title") or "").strip(),
                "src_file": trajectory.get("_src_file"),
                "primary_host": next((str(s["host"]) for s in steps if s.get("host")), ""),
                "n_steps": len(steps),
                **candidate_signals(trajectory),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows.append(record)

    rows.sort(key=rank_key, reverse=True)
    print(f"{len(rows)} trajectories -> {args.out}")
    print()
    print(f"=== 交互面最宽的前 {args.top} 条 ===")
    for row in rows[: args.top]:
        print(f"[{row['n_roles_touched']}role {row['n_signal_tags_touched']}标签 "
              f"{row['n_non_click_actions']}非点击 {row['n_interaction_steps']}步] {row['primary_host']}")
        print(f"    {row['title'][:88]}")
        print(f"    role{row['roles_touched']} 标签{row['signal_tags_touched']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
