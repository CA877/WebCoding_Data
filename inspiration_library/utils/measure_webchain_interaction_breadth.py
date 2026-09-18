#!/usr/bin/env python3
"""量一条 WebChain 轨迹「唤醒了多少种前端交互、又漏掉了多少」。

口径（结构指标，不是语义判定；语义判定交给后续 LLM）：
- 每步的 axTree 渲染成 A11y 文本后，解析出 `[id] role 'name'` 映射。快照与动作的对应关系
  实测为 **`axTree[i]` ↔ `step[i].axtId`**（Hotwire 样本 26/26 命中），即 tree[i] 是执行第 i 步
  动作时的页面状态。
- `roles_present`：该轨迹所有快照里出现过的可交互 role 全集（`INTERACTIVE_ROLES`），
  代表**页面上能被观察到的交互种类**。
- `roles_touched`：轨迹实际点过的控件（按 `axtId` 反查）的 role 集合，代表**被唤醒的交互种类**。
- `roles_untouched = roles_present - roles_touched`：看到了但没被触发的种类——就是
  「没有被唤醒或者观察到的交互」。

排序目的只有一个：挑「交互面最完整」的轨迹给人看，不做任何跨数据集的结论。

用法：
  uv run python inspiration_library/utils/measure_webchain_interaction_breadth.py \\
      --subset datasets/webchain_explore/subset_100.jsonl \\
      --axtrees-dir datasets/webchain_explore/axtrees_sample \\
      --out runs/webchain_breadth_sample.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inspiration_library.trajectory_capability_adapter import (
    INTERACTIVE_ROLES,
    load_axtrees,
    parse_a11y_text,
    webchain_tree_to_text,
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def interactive_nodes(tree: Any) -> dict[str, dict[str, str]]:
    """遍历一棵 WebChain AX 树，返回 node_id -> {role, tag}（只收可交互 role）。

    直接走树而不是先渲染成文本再解析，一是快，二是能顺手取到 `html_tag`
    （`<input>` / `<select>` / `<button>` 这种，比 ARIA role 粒度更细）。
    """
    found: dict[str, dict[str, str]] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        attrs = node.get("attributes") or {}
        role = str(node.get("role") or "").strip()
        node_id = str(attrs.get("data-imean-axt-id") or "").strip()
        if role in INTERACTIVE_ROLES and node_id:
            found[node_id] = {"role": role, "tag": str(attrs.get("html_tag") or "").lower()}
        for child in node.get("children") or []:
            walk(child)

    walk(tree)
    return found


def breadth_stats(traj: dict, axtrees: dict[str, dict]) -> dict[str, Any]:
    """算一条轨迹的交互广度。`axtrees` 是 `load_axtrees` 的返回值（下标字符串 → 步）。

    动作 → 控件节点的对应优先级：
    1. `step["axtId"]`（权威）。实测只有 3/10 个站点填了这个字段（子集内 205/775 个交互步），
       所以不能只靠它。
    2. 退回到**同状态内标签完全相等**的节点（归一化后比较）。在 Hotwire 上与 axtId 真值
       一致率 20/23。这是对已记录字段做同一性对齐，不是语义推断。

    两种方式的命中数分别记在 `n_matched_by_axtid` / `n_matched_by_label`，结果可审计。
    """
    steps = traj.get("steps") or []
    trees = {int(key): value["ax_tree"] for key, value in axtrees.items()
             if isinstance(value, dict) and value.get("ax_tree") is not None}

    nodes_by_state = {index: interactive_nodes(tree) for index, tree in trees.items()}
    label_maps: dict[int, dict[str, list[str]]] = {}

    def labels_for(index: int) -> dict[str, list[str]]:
        """标签 -> 节点 id 列表（仅在需要 fallback 的状态上惰性计算）。"""
        if index not in label_maps:
            text, _ = webchain_tree_to_text(trees[index], title="")
            table: dict[str, list[str]] = {}
            for row in parse_a11y_text(text):
                if row["role"] not in INTERACTIVE_ROLES:
                    continue
                label = _norm(row["name"] or row["static_text"])
                if label:
                    table.setdefault(label, []).append(row["id"])
            label_maps[index] = table
        return label_maps[index]

    roles_present: set[str] = set()
    tags_present: set[str] = set()
    n_controls = 0
    for nodes in nodes_by_state.values():
        n_controls += len(nodes)
        roles_present.update(node["role"] for node in nodes.values())
        tags_present.update(node["tag"] for node in nodes.values() if node["tag"])

    # trees[i] 配 steps[i]：tree[i] 是执行第 i 步动作时的页面状态（实测 26/26 命中）
    roles_touched: set[str] = set()
    tags_touched: set[str] = set()
    by_axtid = by_label = unmatched = ambiguous = 0
    for index, step in enumerate(steps):
        if index not in nodes_by_state:
            continue
        node = None
        node_id = step.get("axtId")
        if node_id is not None and str(node_id) in nodes_by_state[index]:
            node = nodes_by_state[index][str(node_id)]
            by_axtid += 1
        else:
            candidates = labels_for(index).get(_norm(step.get("value")), [])
            if len(candidates) > 1:
                ambiguous += 1
            if candidates:
                node = nodes_by_state[index].get(candidates[0])
                if node is not None:
                    by_label += 1
        if node is None:
            unmatched += 1
            continue
        roles_touched.add(node["role"])
        tag = (((step.get("attributes") or {}).get("data") or {}).get("node") or {}).get("name")
        if tag:
            tags_touched.add(str(tag).lower())

    action_types: dict[str, int] = {}
    for step in steps:
        action = str(step.get("type") or "unknown")
        action_types[action] = action_types.get(action, 0) + 1

    return {
        "traj_id": traj.get("id"),
        "title": str(traj.get("title") or "").strip(),
        "primary_host": next((str(s["host"]) for s in steps if s.get("host")), ""),
        "n_steps": len(steps),
        "n_states": len(trees),
        "n_controls_observed": n_controls,
        "n_matched_by_axtid": by_axtid,
        "n_matched_by_label": by_label,
        "n_actions_unmatched": unmatched,
        "n_actions_ambiguous": ambiguous,
        "roles_present": sorted(roles_present),
        "roles_touched": sorted(roles_touched),
        "roles_untouched": sorted(roles_present - roles_touched),
        "n_roles_present": len(roles_present),
        "n_roles_touched": len(roles_touched),
        "n_roles_untouched": len(roles_present - roles_touched),
        "tags_present": sorted(tags_present),
        "tags_touched": sorted(tags_touched),
        "n_tags_touched": len(tags_touched),
        "action_types": action_types,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subset", type=Path, required=True)
    ap.add_argument("--axtrees-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(line) for line in args.subset.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if args.limit:
        rows = rows[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    missing = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            traj = row["trajectory"]
            path = args.axtrees_dir / f"{traj['id']}.json.gz"
            if not path.exists():
                missing += 1
                continue
            record = breadth_stats(traj, load_axtrees(path))
            record["status"] = "ok"
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
    print(f"{len(rows)} trajectories, {missing} without axtree -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
