#!/usr/bin/env python3
"""挑一条真实轨迹，把「抽取器实际收到的输入」原样打印出来，不调用 LLM。

走的是和 `run_trajectory_capability_extraction.py` 完全相同的代码路径（复用其
`build_case`），所以这里看到的就是正式跑批时送进 prompt 的东西，而不是另写一份近似物。

输出四段：
1. seed             —— 抽取器看到的任务信息（WebChain 有自然语言题目，WebWorld 没有）。
2. observation 概览 —— 入口 URL、baseline 控件数、逐步动作及其目标描述。
3. 证据文本         —— `compact_live_browser_evidence_for_llm` 的真实输出（可截断）。
4. 结构自检         —— 证据里实际出现了哪些 state_id，以及能否反解出 `<path>__step_<i>`。

用法：
  uv run python inspiration_library/utils/inspect_capability_inputs.py --bucket webchain --index 0
  uv run python inspiration_library/utils/inspect_capability_inputs.py --bucket autonomous --index 0
  uv run python inspiration_library/utils/inspect_capability_inputs.py --bucket random --index 3 --full
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

from inspiration_library.utils.run_trajectory_capability_extraction import build_case

BUCKETS: dict[str, dict[str, str]] = {
    "webchain": {
        "dataset": "webchain",
        "input": "datasets/webchain_explore/subset_100.jsonl",
        "axtrees_dir": "datasets/webchain_explore/axtrees_sample",
    },
    "autonomous": {
        "dataset": "webworld",
        "input": "datasets/webworld_explore/autonomous_100.jsonl",
        "axtrees_dir": "",
    },
    "random": {
        "dataset": "webworld",
        "input": "datasets/webworld_explore/random_100.jsonl",
        "axtrees_dir": "",
    },
}


def resolve_source(*, bucket: str | None, subset: Path | None,
                   axtrees_dir: Path | None) -> tuple[str, Path, Path | None, str]:
    """把命令行参数解成 (dataset, 输入文件, axTree 目录, 标签)。纯函数，便于单测。"""
    if bucket and subset:
        raise SystemExit("--bucket 与 --subset 只能给一个")
    if not bucket and not subset:
        raise SystemExit("必须给 --bucket 或 --subset")
    if subset:
        if axtrees_dir is None:
            raise SystemExit("--subset 需要同时给 --axtrees-dir")
        return "webchain", subset, axtrees_dir, subset.stem
    spec = BUCKETS[bucket]
    directory = PROJECT_ROOT / spec["axtrees_dir"] if spec["axtrees_dir"] else None
    return spec["dataset"], PROJECT_ROOT / spec["input"], directory, bucket


def find_row(rows: list[dict], *, index: int | None, contains: str | None) -> tuple[int, dict]:
    if contains:
        for position, row in enumerate(rows):
            if contains in json.dumps(row, ensure_ascii=False):
                return position, row
        raise SystemExit(f"no row contains {contains!r}")
    position = index or 0
    if not 0 <= position < len(rows):
        raise SystemExit(f"index {position} out of range (0..{len(rows) - 1})")
    return position, rows[position]


def render_case(
    seed: dict[str, Any],
    observation: dict[str, Any],
    stats: dict[str, Any],
    evidence: dict[str, Any],
    *,
    max_evidence_chars: int | None,
) -> str:
    """把一次转换结果渲染成可读文本。纯函数，便于单测。"""
    path = observation["exploration_paths"][0]
    baseline = observation["baseline"]
    out: list[str] = []

    out.append("=" * 78)
    out.append("1. SEED（抽取器看到的任务信息）")
    out.append("=" * 78)
    for key, value in seed.items():
        out.append(f"  {key}: {value}")

    out.append("")
    out.append("=" * 78)
    out.append("2. OBSERVATION 概览")
    out.append("=" * 78)
    out.append(f"  entry_url        : {observation['entry_url']}")
    out.append(f"  baseline.title   : {baseline.get('title')}")
    out.append(f"  baseline.visible : {len(baseline.get('visible_text') or '')} 字符")
    out.append(f"  baseline.aria    : {len(baseline.get('aria_snapshot') or '')} 字符")
    out.append(f"  baseline 控件数  : {len(baseline.get('interactive') or [])}")
    out.append(f"  步数             : {stats['n_steps']}  动作分布: {stats['action_types']}")
    out.append("")
    out.append("  逐步动作：")
    for step in path["steps"]:
        action = step["action"]
        target = action.get("target_description") or action.get("target") or ""
        out.append(f"    [{step['index']:>2}] {step['state_id']:<22} "
                   f"{action['action']:<14} {str(target)[:60]}")
        out.append(f"         状态: title={step['state'].get('title')!r} "
                   f"控件 {len(step['state'].get('interactive') or [])} 个 "
                   f"可见文本 {len(step['state'].get('visible_text') or '')} 字符")

    rendered = json.dumps(evidence, ensure_ascii=False, indent=2)
    out.append("")
    out.append("=" * 78)
    out.append("3. 证据字典（compact_live_browser_evidence_for_llm 的真实输出）")
    out.append("=" * 78)
    out.append("  key / 类型 / 大小：")
    for key, value in evidence.items():
        size = len(value) if hasattr(value, "__len__") else "-"
        out.append(f"    {key:24s} {type(value).__name__:6s} {size}")
    out.append("")
    out.append(f"  JSON 序列化后 {len(rendered)} 字符，内容：")
    if max_evidence_chars is not None and len(rendered) > max_evidence_chars:
        out.append(rendered[:max_evidence_chars])
        out.append(f"\n... [截断，共 {len(rendered)} 字符，加 --full 看全部]")
    else:
        out.append(rendered)

    out.append("")
    out.append("=" * 78)
    out.append("4. 结构自检")
    out.append("=" * 78)
    state_ids = [step["state_id"] for step in path["steps"]]
    present = [sid for sid in state_ids if sid in rendered]
    out.append(f"  evidence_state_ids 字段: {evidence.get('evidence_state_ids')}")
    out.append(f"  action_steps 条数: {len(evidence.get('action_steps') or [])}")
    out.append(f"  我的 state_id 出现在证据里: {len(present)}/{len(state_ids)} -> {present}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bucket", choices=tuple(BUCKETS), default=None, help="预置数据源")
    ap.add_argument("--subset", type=Path, default=None,
                    help="任意候选池（需配 --axtrees-dir），用于看新挑的 case")
    ap.add_argument("--axtrees-dir", type=Path, default=None)
    ap.add_argument("--index", type=int, default=None, help="取该池的第几条（从 0 起）")
    ap.add_argument("--contains", default=None, help="按子串找第一个匹配的行")
    ap.add_argument("--max-evidence-chars", type=int, default=6000)
    ap.add_argument("--full", action="store_true", help="打印完整证据文本")
    args = ap.parse_args()

    dataset, input_path, axtrees_dir, label = resolve_source(
        bucket=args.bucket, subset=args.subset, axtrees_dir=args.axtrees_dir)
    if not input_path.exists():
        raise SystemExit(f"missing input: {input_path}")
    rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    position, row = find_row(rows, index=args.index, contains=args.contains)

    seed_id, seed, observation, stats = build_case(dataset, row, axtrees_dir)

    from inspiration_library.deep_browser_exploration import compact_live_browser_evidence_for_llm
    evidence = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, include_action_steps=True)

    print(f"### {label} index={position} seed_id={seed_id}\n")
    print(render_case(seed, observation, stats, evidence,
                      max_evidence_chars=None if args.full else args.max_evidence_chars))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
