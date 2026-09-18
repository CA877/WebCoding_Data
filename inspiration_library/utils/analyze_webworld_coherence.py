#!/usr/bin/env python3
"""度量 WebWorldData 轨迹的「站点连贯性」，判断长度分层是否是可用的分层代理。

动机：论文把 Level 1（规则爬虫随机采样动作）和 Level 2（LLM agent 自生成目标）
分开，但发布文件里没有 level 字段。`fetch_webworld_subset.py` 先用动作数做了
代理切分；本脚本检验该切分是否有语义依据。

判据：一次**有目标的**会话应该在少数站点内推进，并在同一站点内反复出现相近标题；
**随机爬取**则会在无关站点之间跳跃。因此对每条轨迹计算：

  n_states            状态数（= 动作数 + 1）
  n_titles            不同 RootWebArea 标题数
  n_domains           从状态文本里抽出的不同站点域数
  domain_coherence    相邻状态停在同一域的转移占比（1.0 = 全程不换站）
  title_novelty       n_titles / n_states（越高越像一路走马观花）

只在 world_model_a11y 记录上统计。输出特征 jsonl 供后续分层与报告引用。

用法：
  uv run python inspiration_library/utils/analyze_webworld_coherence.py \\
      --url https://hf-mirror.com/datasets/Qwen/WebWorldData/resolve/main/WebWorld_Training.jsonl \\
      --out datasets/webworld_explore/coherence_features.jsonl --scan-gb 1.0
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from .fetch_webworld_subset import ACTION_RE, ACTION_FN_RE, NON_INTERACTION_ACTIONS, fetch_range, parse_chunk
except ImportError:  # Direct CLI execution.
    from fetch_webworld_subset import ACTION_RE, ACTION_FN_RE, NON_INTERACTION_ACTIONS, fetch_range, parse_chunk

TITLE_RE = re.compile(r"RootWebArea '([^']*)'")
# 状态文本里的绝对 URL（链接节点、跳转动作都可能带）
ABS_URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
COMMON_SUFFIXES = (
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "co.uk", "co.jp", "com.au", "co.kr",
)


def registrable(host: str) -> str:
    """粗略取可注册域：去掉 www. 等前缀，保留常见二级后缀。"""
    host = host.lower().lstrip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in COMMON_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def trajectory_features(rec: dict) -> dict | None:
    convs = rec.get("conversations")
    if not isinstance(convs, list) or not convs:
        return None
    if not str(convs[0].get("value", "")).startswith("You are a web world model"):
        return None

    # 状态序列：初始状态 + 每个 gpt 回合给出的 next_state
    states: list[str] = []
    actions: list[str] = []
    for conv in convs:
        value = conv.get("value", "")
        if conv.get("from") == "gpt":
            states.append(value)
        else:
            actions.extend(ACTION_RE.findall(value))

    if not states:
        return None

    titles = [TITLE_RE.search(s).group(1) if TITLE_RE.search(s) else "" for s in states]
    domains: list[str] = []
    for state in states:
        found = [registrable(h) for h in ABS_URL_RE.findall(state)]
        domains.append(collections.Counter(found).most_common(1)[0][0] if found else "")

    same = sum(1 for a, b in zip(domains, domains[1:]) if a and a == b)
    transitions = max(len(domains) - 1, 1)

    action_types = [m.group(1) for a in actions if (m := ACTION_FN_RE.match(a))]
    meaningful = [t for t in action_types if t not in NON_INTERACTION_ACTIONS]
    return {
        "n_actions": len(meaningful),
        "n_states": len(states),
        "n_titles": len({t for t in titles if t}),
        "n_domains": len({d for d in domains if d}),
        "empty_domain_states": sum(1 for d in domains if not d),
        "domain_coherence": round(same / transitions, 4),
        "title_novelty": round(len({t for t in titles if t}) / max(len(states), 1), 4),
        "n_goto": sum(1 for t in action_types if t == "goto"),
        "state_chars": sum(len(s) for s in states),
        "action_types": dict(collections.Counter(action_types)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--chunk-mb", type=int, default=8)
    ap.add_argument("--scan-gb", type=float, default=1.0)
    ap.add_argument("--start-gb", type=float, default=0.0)
    args = ap.parse_args()

    chunk = args.chunk_mb << 20
    base = int(args.start_gb * (1 << 30))
    chunks = [base + i * chunk for i in range(int(args.scan_gb * (1 << 30) / chunk))]

    rows: list[dict] = []
    failures = 0
    lock_started = time.time()

    def work(chunk_start: int) -> list[dict]:
        raw = fetch_range(args.url, chunk_start, chunk_start + chunk - 1)
        out = []
        for key, offset, rec in parse_chunk(raw, chunk_start):
            feats = trajectory_features(rec)
            if feats is not None:
                feats["record_key"] = key
                out.append(feats)
        return out

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(work, cs) for cs in chunks]
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                rows.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"chunk failed: {exc}", file=sys.stderr)
            if i % 24 == 0:
                print(f"  {i}/{len(chunks)} chunks, {len(rows)} trajectories, "
                      f"{time.time()-lock_started:.0f}s", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in sorted(rows, key=lambda r: -r["n_actions"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n=== {len(rows)} world-model trajectories, {failures} chunk failures ===")
    hist = collections.Counter(r["n_actions"] for r in rows)
    print("\nn_actions histogram:")
    for k in sorted(hist):
        print(f"  {k:3d} actions: {hist[k]:5d}  {'#'*min(hist[k]//max(len(rows)//200,1),70)}")
    total = len(rows)
    cum = 0
    for k in sorted(hist):
        cum += hist[k]
        if k in (3, 5, 9, 10, 16):
            print(f"  <= {k}: {cum/total:.1%}")

    print("\ndomain_coherence by action bucket:")
    for lo, hi, label in [(1, 2, "1-2"), (3, 5, "3-5"), (6, 9, "6-9"), (10, 99, ">=10")]:
        grp = [r for r in rows if lo <= r["n_actions"] <= hi]
        if not grp:
            continue
        coh = statistics.mean(r["domain_coherence"] for r in grp)
        nov = statistics.mean(r["title_novelty"] for r in grp)
        nd = statistics.mean(r["n_domains"] for r in grp)
        nc = statistics.mean(r["domain_coherence"] >= 0.99 for r in grp)
        print(f"  {label:5s} n={len(grp):5d}  mean_coherence={coh:.3f}  "
              f"mean_title_novelty={nov:.3f}  mean_n_domains={nd:.2f}  frac_fully_coherent={nc:.1%}")

    coh_vals = sorted(r["domain_coherence"] for r in rows)
    print(f"\ndomain_coherence quantiles: "
          f"p10={coh_vals[len(coh_vals)//10]:.2f} p50={statistics.median(coh_vals):.2f} "
          f"p90={coh_vals[9*len(coh_vals)//10]:.2f} max={coh_vals[-1]:.2f}")
    print(f"fully coherent (==1.0): {sum(1 for v in coh_vals if v >= 0.999)/total:.1%}")
    print(f"\nwrote -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
