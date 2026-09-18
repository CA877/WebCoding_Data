#!/usr/bin/env python3
"""汇总能力抽取对比研究，回答预先约定的六个统计问题。

统计口径（写进报告，避免事后解释）：
- 每条轨迹的卡片数：只统计 `status == "ok"` 的轨迹；abstention（模型明确弃权、返回空卡片）
  单列，不计入平均，否则会把「弃权」和「抽到 0 张」混为一谈。
- 每张卡片的关联动作数：取该卡片 `observation_evidence` 引用的 state_id，反解出
  `<path>__step_<i>` 的 i，去重后的步数即关联动作数；同时记录 `user_actions` 的长度。
- 导航 vs 可迁移产品交互：来自 `classify_capability_cards.py` 的 LLM 判定（卡片层）。
  **注意抽取器 prompt 要求省略 navigation/search 行为，因此卡片层的导航占比是残差，
  不代表轨迹真实的导航占比**——报告里必须带上这句。
- 同站重合率：同一 host 下每两条轨迹的 cluster 集合做 Jaccard，取该站所有轨迹对的均值，
  再按 bucket 汇总。任一条轨迹 0 张卡片时该对不计入，并单独计数。
- unique capability 数：`cluster_capabilities.py` 的等价类数量。

用法：
  uv run python inspiration_library/utils/summarize_capability_study.py \\
      --runs-dir runs/capability_study/full --out-dir runs/capability_study/report
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STEP_REF_RE = re.compile(r"__step_(\d+)$")

NAV_KIND = "navigation_or_information_gathering"
PRODUCT_KIND = "transferable_product_interaction"
PRESENTATION_KIND = "presentation_only"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def site_of(url: str) -> str:
    return urlsplit(str(url or "")).netloc.lower()


def extraction_rows(runs_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(runs_dir.glob("*.jsonl")):
        if path.name in {"card_kinds.jsonl", "capability_clusters.jsonl", "capability_pairs.jsonl"}:
            continue
        for row in read_jsonl(path):
            row.setdefault("bucket", path.stem)
            rows.append(row)
    return rows


def step_count(card: dict, observation_stats: dict | None = None) -> int:
    """卡片 evidence 引用的不同步数。"""
    steps = set()
    for entry in card.get("observation_evidence") or []:
        match = STEP_REF_RE.search(str(entry.get("state_id") or ""))
        if match:
            steps.add(int(match.group(1)))
    return len(steps)


def per_bucket_stats(rows: list[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row["bucket"]].append(row)

    out: dict[str, Any] = {}
    for bucket, items in buckets.items():
        ok = [row for row in items if row.get("status") == "ok"]
        cards = [card for row in ok for card in (row.get("extraction") or {}).get("capabilities") or []]
        per_traj = [len((row.get("extraction") or {}).get("capabilities") or []) for row in ok]
        abstained = [row for row in ok
                     if not ((row.get("extraction") or {}).get("capabilities") or [])]
        status_counts: dict[str, int] = defaultdict(int)
        for row in items:
            status_counts[str(row.get("status"))] += 1
        actions_per_card = [step_count(card) for card in cards]
        user_actions_per_card = [len(card.get("user_actions") or []) for card in cards]
        out[bucket] = {
            "n_rows": len(items),
            "status_counts": dict(status_counts),
            "n_ok_trajectories": len(ok),
            "n_cards": len(cards),
            "cards_per_trajectory_mean": round(statistics.mean(per_traj), 2) if per_traj else None,
            "cards_per_trajectory_median": statistics.median(per_traj) if per_traj else None,
            "trajectories_with_zero_cards": len(abstained),
            "zero_card_rate": round(len(abstained) / len(ok), 3) if ok else None,
            "evidence_steps_per_card_mean": round(statistics.mean(actions_per_card), 2) if actions_per_card else None,
            "evidence_steps_per_card_median": statistics.median(actions_per_card) if actions_per_card else None,
            "user_actions_per_card_mean": round(statistics.mean(user_actions_per_card), 2) if user_actions_per_card else None,
        }
    return out


def kind_stats(runs_dir: Path, rows: list[dict]) -> dict[str, Any]:
    kinds = read_jsonl(runs_dir / "card_kinds.jsonl")
    if not kinds:
        return {"available": False, "note": "card_kinds.jsonl 不存在，先跑 classify_capability_cards.py"}
    ok = [row for row in kinds if row.get("status") == "ok"]
    per_bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in ok:
        per_bucket[row["bucket"]][row["interaction_kind"]] += 1
    out: dict[str, Any] = {"available": True, "n_classified": len(ok),
                           "n_unclassified": len(kinds) - len(ok), "per_bucket": {}}
    for bucket, counts in per_bucket.items():
        total = sum(counts.values())
        out["per_bucket"][bucket] = {
            "total": total,
            "navigation_or_information_gathering": counts.get(NAV_KIND, 0),
            "transferable_product_interaction": counts.get(PRODUCT_KIND, 0),
            "presentation_only": counts.get(PRESENTATION_KIND, 0),
            "product_share": round(counts.get(PRODUCT_KIND, 0) / total, 3) if total else None,
            "navigation_share": round(counts.get(NAV_KIND, 0) / total, 3) if total else None,
        }
    # 卡片 family 与判定结果的交叉表，便于看 taxonomy 的覆盖情况
    cross: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in ok:
        cross[str(row.get("family"))][row["interaction_kind"]] += 1
    out["family_cross_tab"] = {family: dict(counts) for family, counts in sorted(cross.items())}
    return out


def overlap_stats(runs_dir: Path, rows: list[dict]) -> dict[str, Any]:
    """同一网站不同轨迹之间的 capability 重合率。"""
    clusters = read_jsonl(runs_dir / "capability_clusters.jsonl")
    if not clusters:
        return {"available": False,
                "note": "capability_clusters.jsonl 不存在，先跑 cluster_capabilities.py"}
    cluster_by_seed: dict[str, set[str]] = defaultdict(set)
    bucket_by_seed: dict[str, str] = {}
    for row in clusters:
        cluster_by_seed[row["seed_id"]].add(row["cluster_id"])
        bucket_by_seed[row["seed_id"]] = row["bucket"]

    site_by_seed = {row["seed_id"]: site_of(row.get("entry_url")) for row in rows if row.get("seed_id")}
    sites: dict[str, list[str]] = defaultdict(list)
    for seed_id, site in site_by_seed.items():
        if site:
            sites[site].append(seed_id)

    pair_rows: list[dict[str, Any]] = []
    for site, seeds in sites.items():
        for i, left in enumerate(sorted(seeds)):
            for right in sorted(seeds)[i + 1:]:
                a, b = cluster_by_seed.get(left, set()), cluster_by_seed.get(right, set())
                if not a or not b:
                    continue
                pair_rows.append({
                    "site": site, "left": left, "right": right,
                    "bucket_left": bucket_by_seed.get(left), "bucket_right": bucket_by_seed.get(right),
                    "jaccard": round(len(a & b) / len(a | b), 4),
                    "shared": len(a & b), "left_size": len(a), "right_size": len(b),
                })
    def agg(subset: list[dict]) -> dict[str, Any]:
        if not subset:
            return {"n_pairs": 0, "mean_jaccard": None, "shared_any_rate": None}
        return {
            "n_pairs": len(subset),
            "mean_jaccard": round(statistics.mean(row["jaccard"] for row in subset), 4),
            "median_jaccard": round(statistics.median(row["jaccard"] for row in subset), 4),
            "shared_any_rate": round(sum(1 for row in subset if row["shared"]) / len(subset), 3),
        }
    same_site = [row for row in pair_rows if row["bucket_left"] == row["bucket_right"]]
    return {
        "available": True,
        "n_sites_with_multiple_trajectories": sum(1 for seeds in sites.values() if len(seeds) > 1),
        "overall": agg(pair_rows),
        "within_bucket": {bucket: agg([row for row in same_site if row["bucket_left"] == bucket])
                          for bucket in sorted({row["bucket_left"] for row in same_site})},
        "top_shared_pairs": sorted(pair_rows, key=lambda row: -row["jaccard"])[:10],
        "per_site": {site: agg([row for row in pair_rows if row["site"] == site])
                     for site in sorted(sites) if len(sites[site]) > 1},
    }


def unique_stats(runs_dir: Path) -> dict[str, Any]:
    summary_path = runs_dir / "cluster_summary.json"
    if not summary_path.exists():
        return {"available": False, "note": "cluster_summary.json 不存在，先跑 cluster_capabilities.py"}
    return {"available": True, **json.loads(summary_path.read_text(encoding="utf-8"))}


def render_report(payload: dict[str, Any]) -> str:
    lines = ["# 能力抽取对比研究", ""]
    lines.append("## 1-2. 每条轨迹的卡片数 / 每张卡片的关联动作数")
    lines.append("")
    lines.append("| bucket | 输入 | 成功 | 卡片总数 | 卡片/轨迹(均值) | 卡片/轨迹(中位) | 零卡片轨迹 | 关联步数/卡片 | user_actions/卡片 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for bucket, stats in payload["per_bucket"].items():
        lines.append(
            f"| {bucket} | {stats['n_rows']} | {stats['n_ok_trajectories']} | {stats['n_cards']} | "
            f"{stats['cards_per_trajectory_mean']} | {stats['cards_per_trajectory_median']} | "
            f"{stats['trajectories_with_zero_cards']} ({stats['zero_card_rate']}) | "
            f"{stats['evidence_steps_per_card_mean']} | {stats['user_actions_per_card_mean']} |")
    lines.append("")
    lines.append("状态明细：")
    for bucket, stats in payload["per_bucket"].items():
        lines.append(f"- {bucket}: {stats['status_counts']}")
    lines.append("")
    lines.append("## 3-4. 导航/信息获取 vs 可迁移产品交互")
    kinds = payload["kinds"]
    if not kinds.get("available"):
        lines.append(f"- 未生成：{kinds.get('note')}")
    else:
        lines.append("| bucket | 已判定 | 导航/信息获取 | 可迁移产品交互 | 仅表现层 | 产品交互占比 |")
        lines.append("|---|---|---|---|---|---|")
        for bucket, stats in kinds["per_bucket"].items():
            lines.append(
                f"| {bucket} | {stats['total']} | {stats['navigation_or_information_gathering']} | "
                f"{stats['transferable_product_interaction']} | {stats['presentation_only']} | "
                f"{stats['product_share']} |")
        lines.append("")
        lines.append("⚠️ 抽取器 prompt 明确要求省略 navigation / search / theme / support 行为，"
                     "因此**卡片层的导航占比是残差**，不等于轨迹本身的导航占比。")
        lines.append("")
        lines.append("family 交叉表：")
        for family, counts in kinds.get("family_cross_tab", {}).items():
            lines.append(f"- {family}: {counts}")
    lines.append("")
    lines.append("## 5. 同一网站不同轨迹的 capability 重合率")
    overlap = payload["overlap"]
    if not overlap.get("available"):
        lines.append(f"- 未生成：{overlap.get('note')}")
    else:
        lines.append(f"- 有多条轨迹的站点数：{overlap['n_sites_with_multiple_trajectories']}")
        lines.append(f"- 总体：{overlap['overall']}")
        for bucket, stats in overlap["within_bucket"].items():
            lines.append(f"- {bucket} 组内：{stats}")
    lines.append("")
    lines.append("## 6. unique capability 数")
    unique = payload["unique"]
    if not unique.get("available"):
        lines.append(f"- 未生成：{unique.get('note')}")
    else:
        lines.append(f"- 卡片总数 {unique['n_cards']} → 等价类 {unique['n_clusters']} 个")
        lines.append(f"- 候选对 {unique['n_candidate_pairs']}（阈值 {unique['candidate_threshold']}，"
                     f"截断 {unique['n_candidate_pairs_truncated']}），确认同一 {unique['n_confirmed_same_pairs']} 对")
    lines.append("")
    lines.append("## 口径与已知偏置")
    for note in payload["caveats"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    rows = extraction_rows(args.runs_dir)
    if not rows:
        raise SystemExit(f"no extraction results under {args.runs_dir}")
    payload = {
        "runs_dir": str(args.runs_dir),
        "per_bucket": per_bucket_stats(rows),
        "kinds": kind_stats(args.runs_dir, rows),
        "overlap": overlap_stats(args.runs_dir, rows),
        "unique": unique_stats(args.runs_dir),
        "caveats": [
            "WebWorld 的 Level 1/Level 2 不可从发布文件恢复（记录内无 level 字段），"
            "本研究的 autonomous/random 是按有效动作数做的**代理切分**，不是官方标注；"
            "实测动作数在 10 处截断（10 条动作的记录占绝大多数），因此 autonomous 段长度几乎同质。",
            "WebChain 子集 100 条中有 5 条无任何 axTree（远端结构证据缺失），无法参与抽取，"
            "已在结果里单列为 no_evidence；另有 38 条部分步的 axTree 缺失，其状态序列有缺口。",
            "WebWorld 记录内**没有任务目标**，只有动作序列；WebChain 每题有自然语言任务标题。"
            "两者在「有无意图」这一点上不可比，解释卡片质量差异时必须考虑。",
            "抽取器 prompt 要求省略 navigation/search/theme/support 行为，卡片层的导航占比是残差。",
            "卡片由 LLM 生成，单次抽样，未做重复采样；卡片数与质量的差异含模型随机性。",
        ],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "study_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = render_report(payload)
    (args.out_dir / "study_report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
