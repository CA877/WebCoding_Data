#!/usr/bin/env python3
"""量「页面上的交互，有多少真的送到了 LLM 面前」——把容量上限扫一遍。

动机：轨迹本身记录了整页 axTree，但从 axTree 到送进 prompt 的证据之间有四道仓库
自己设的上限，每一道都会丢东西：

  1. `a11y_text_to_state` 每帧最多渲染 `max_controls`（默认 150）个控件
  2. 同函数把 `visible_text` 截到 `max_visible_chars`（默认 4000）、aria 截到 12000
  3. `compact_live_browser_evidence_for_llm` 的 `control_limit`（默认 64），
     在**全部状态去重后**的控件里再抽 64 行
  4. `page.visible_text_coverage` 只保留 80 行文本摘要

本脚本对每条轨迹、每档配置各算一遍，产出「原始 → 送达」的漏斗，用来回答
「把上限调高，唤醒率能从多少提到多少，以及代价（证据字符数）是多少」。

口径：
- `raw_controls`：把 axTree 逐帧展开，按 `(role, 归一化标签)` 去重后的控件数——
  「页面上真实存在多少个不同的可交互控件」，是漏斗的分母。
- `adapter_controls`：adapter 渲染后、跨全部状态去重的控件数（上限 1 生效处）。
- `delivered_controls`：证据里 `observed_controls` 的行数（上限 3 生效处）。
- role 只数 `INTERACTIVE_ROLES` 里的种类，代表「模型能看出页面上有哪几类交互」。

用法：
  uv run python inspiration_library/utils/measure_observation_coverage.py \\
      --subset datasets/webchain_explore/candidates_48.jsonl \\
      --axtrees-dir datasets/webchain_explore/axtrees_candidates \\
      --out runs/capability_study/coverage/candidates_48.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inspiration_library.deep_browser_exploration import (
    _online_control_rows,
    compact_live_browser_evidence_for_llm,
)
from inspiration_library.trajectory_capability_adapter import (
    INTERACTIVE_ROLES,
    ObservationLimits,
    UNLIMITED_LIMITS,
    a11y_text_to_state,
    load_axtrees,
    webchain_to_observation,
    webchain_tree_to_text,
)


@dataclass(frozen=True)
class CapConfig:
    """一档上限组合：三道转换上限 + 证据层的 control_limit。"""

    name: str
    limits: ObservationLimits
    control_limit: int | None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, **self.limits.as_dict(),
                "control_limit": self.control_limit}


# 现状 = 仓库沿用至今的默认值；其余档位用于看「加多少、换多少」
CAP_CONFIGS: tuple[CapConfig, ...] = (
    CapConfig("current", ObservationLimits(), 64),
    CapConfig("x2", ObservationLimits(max_controls=300, max_visible_chars=12000,
                                      max_aria_chars=36000), 128),
    CapConfig("x4", ObservationLimits(max_controls=600, max_visible_chars=48000,
                                      max_aria_chars=144000), 256),
    CapConfig("unlimited", UNLIMITED_LIMITS, None),
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def raw_controls(tree: Any) -> dict[str, str]:
    """把一棵 axTree 里的可交互控件收成 `node_id -> role`。

    按 **node id** 去重才是「页面上有多少个控件」的正解：同一个控件在多个状态下重复
    出现只算一次。aid 缺失的节点用角色+标签兜底，避免整类控件被漏掉。
    """
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        role = str(node.get("role") or "").strip()
        if role in INTERACTIVE_ROLES:
            attrs = node.get("attributes") or {}
            name = node.get("name") or node.get("value") or attrs.get("html_text") or ""
            node_id = str(attrs.get("data-imean-axt-id") or "").strip()
            found[node_id or f"{role}:{_norm(name)}"] = role
        for child in node.get("children") or []:
            walk(child)

    walk(tree)
    return found


def adapter_control_keys(observation: dict[str, Any]) -> set[tuple[str, str]]:
    """adapter 渲染后、跨全部状态去重的控件集合。"""
    keys: set[tuple[str, str]] = set()
    for snapshot in iter_snapshots(observation):
        for row in snapshot.get("interactive") or []:
            if not isinstance(row, dict):
                continue
            keys.add((str(row.get("role") or ""),
                      _norm(row.get("aria_label") or row.get("text"))))
    return keys


def iter_snapshots(observation: dict[str, Any]):
    for key in ("baseline", "mobile_baseline"):
        value = observation.get(key)
        if isinstance(value, dict):
            yield value
    for path in observation.get("exploration_paths") or []:
        if not isinstance(path, dict):
            continue
        for step in path.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("state"), dict):
                yield step["state"]
        if isinstance(path.get("after"), dict):
            yield path["after"]


def measure_case(traj: dict, axtrees: dict[str, dict],
                 config: CapConfig) -> dict[str, Any]:
    """对一条轨迹、一档配置算漏斗。"""
    _, observation = webchain_to_observation(traj, axtrees, seed_id="coverage",
                                             limits=config.limits)
    evidence = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, include_action_steps=True,
        control_limit=config.control_limit)

    raw: dict[str, str] = {}
    raw_a11y_chars = 0
    for payload in axtrees.values():
        tree = payload.get("ax_tree") if isinstance(payload, dict) else None
        if tree is None:
            continue
        raw |= raw_controls(tree)
        text, _ = webchain_tree_to_text(tree, title="")
        raw_a11y_chars += len(text)

    adapter_keys = adapter_control_keys(observation)
    # 关掉 control_limit 时的行数 = 「pattern 折叠 + 每组最多 2 个」之后的天花板。
    # 这一层不随 control_limit 变化，是独立于它的第二道上限。
    ceiling = len(_online_control_rows(observation, include_selectors=False, limit=None))
    delivered = [row for row in (evidence.get("observed_controls") or []) if isinstance(row, dict)]
    delivered_roles = {str(row.get("role") or "") for row in delivered}

    baseline = observation.get("baseline") or {}
    page = evidence.get("page") or {}

    return {
        "traj_id": traj.get("id"),
        "primary_host": next((str(s["host"]) for s in (traj.get("steps") or []) if s.get("host")), ""),
        "n_states": len(axtrees),
        "config": config.as_dict(),
        "raw_controls": len(raw),
        "adapter_controls": len(adapter_keys),
        "ceiling_controls": ceiling,
        "delivered_controls": len(delivered),
        "observed_control_total": evidence.get("observed_control_total"),
        "raw_roles": len(set(raw.values())),
        "adapter_roles": len({role for role, _ in adapter_keys}),
        "delivered_roles": len(delivered_roles),
        "roles_delivered_list": sorted(delivered_roles),
        "raw_a11y_chars": raw_a11y_chars,
        "baseline_visible_chars": len(baseline.get("visible_text") or ""),
        "visible_text_lines": len(page.get("visible_text_coverage") or []),
        "accessibility_lines": len(page.get("accessibility_coverage") or []),
        "evidence_chars": len(json.dumps(evidence, ensure_ascii=False)),
        "transitions": len(evidence.get("transitions") or []),
        "state_delta_catalog": len(evidence.get("state_delta_catalog") or []),
    }


def render_report(records: list[dict], *, top: int = 0) -> str:
    """把逐 case × 逐配置的记录汇总成漏斗表。纯函数，便于单测。"""
    by_config: dict[str, list[dict]] = {}
    for row in records:
        by_config.setdefault(row["config"]["name"], []).append(row)

    order = [config.name for config in CAP_CONFIGS]
    header = (f"{'配置':<11}{'① 原始控件':>11}{'② adapter':>10}{'③ 折叠上限':>11}"
              f"{'④ 送达':>8}{'④/①':>8}{'role 原始':>10}{'role 送达':>10}"
              f"{'证据字符':>10}")
    lines = [header, "-" * len(header)]
    for name in order:
        rows = by_config.get(name)
        if not rows:
            continue
        raw = sum(r["raw_controls"] for r in rows)
        adap = sum(r["adapter_controls"] for r in rows)
        ceiling = sum(r["ceiling_controls"] for r in rows)
        delivered = sum(r["delivered_controls"] for r in rows)
        raw_roles = max(r["raw_roles"] for r in rows)
        delivered_roles = max(r["delivered_roles"] for r in rows)
        chars = sum(r["evidence_chars"] for r in rows) / max(len(rows), 1)
        lines.append(
            f"{name:<11}{raw:>11}{adap:>10}{ceiling:>11}{delivered:>8}"
            f"{100 * delivered / max(raw, 1):>7.1f}%{raw_roles:>10}{delivered_roles:>10}"
            f"{chars:>10.0f}")
    lines.append("")
    lines.append("① 原始控件 = 全部状态的 axTree 里按 node id 去重后的可交互控件（每控件算一次）")
    lines.append("② adapter  = 渲染成 observation 后跨状态去重（`max_controls` 每帧上限在这一步生效）")
    lines.append("③ 折叠上限 = 关掉 control_limit 时的行数；受 `(tag,role,type,语义)` 折叠 + 每组最多 2 个限制")
    lines.append("④ 送达     = 证据里 `observed_controls` 的实际行数")

    if top:
        lines.append("")
        lines.append(f"=== 每条 case 的送达率（按 {order[0]} 配置排序，前 {top}）===")
        first = sorted(by_config.get(order[0], []),
                       key=lambda r: r["delivered_controls"] / max(r["raw_controls"], 1))
        for row in first[:top]:
            lines.append(f"  {row['primary_host'][:30]:<32}{row['raw_controls']:>6}"
                         f" -> {row['delivered_controls']:>4}  "
                         f"{100 * row['delivered_controls'] / max(row['raw_controls'], 1):>5.1f}%"
                         f"  [{row['traj_id']}]")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subset", type=Path, required=True)
    ap.add_argument("--axtrees-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--top", type=int, default=0, help="额外打印送达率最低的 N 条")
    ap.add_argument("--configs", default="", help="只跑指定配置名，逗号分隔")
    args = ap.parse_args()

    configs = CAP_CONFIGS
    if args.configs:
        wanted = {name.strip() for name in args.configs.split(",") if name.strip()}
        configs = tuple(config for config in CAP_CONFIGS if config.name in wanted)
        if not configs:
            raise SystemExit(f"no config matched: {args.configs}")

    rows = [json.loads(line) for line in args.subset.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if args.limit:
        rows = rows[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    missing = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            traj = row["trajectory"]
            path = args.axtrees_dir / f"{traj['id']}.json.gz"
            if not path.exists():
                missing += 1
                continue
            axtrees = load_axtrees(path)
            for config in configs:
                record = measure_case(traj, axtrees, config)
                record["status"] = "ok"
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                records.append(record)

    print(f"{len(rows)} trajectories, {missing} without axtree, "
          f"{len(records)} records -> {args.out}")
    print()
    print(render_report(records, top=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
