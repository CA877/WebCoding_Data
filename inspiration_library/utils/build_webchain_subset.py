#!/usr/bin/env python3
"""WebChain 轨迹索引与子集抽取。

WebChain 原始发布（webagentlab/webchain-legacy）把 31,725 条轨迹分散在
`raw/json/all_json_files/*.json` 的 680 个文件里，每个文件是一个轨迹列表。
本脚本先扫全量建索引（一行一条轨迹的摘要），再按站点分层抽子集。

分层抽样的理由：要度量"同一网站不同 trajectory 的 capability 重合率"，
必须保证每个站点有 >= 2 条轨迹；纯随机抽样会让 428 个站点各只有零星几条。

用法：
  uv run python inspiration_library/utils/build_webchain_subset.py index  --src <dir> --out <index.jsonl>
  uv run python inspiration_library/utils/build_webchain_subset.py select --index <index.jsonl> \\
      --src <dir> --n 100 --per-host 10 --out <subset.jsonl>
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

# 打开浏览器等非页面交互动作，不计入轨迹的真实操作步数
NON_INTERACTION_TYPES = {"launchApp"}


def traj_summary(traj: dict, src_file: str) -> dict:
    steps = traj.get("steps") or []
    hosts: collections.Counter[str] = collections.Counter()
    action_types: collections.Counter[str] = collections.Counter()
    for step in steps:
        host = (step.get("host") or "").strip()
        if host:
            hosts[host] += 1
        stype = (step.get("type") or "").strip()
        if stype:
            action_types[stype] += 1

    real_steps = [s for s in steps if (s.get("type") or "") not in NON_INTERACTION_TYPES]
    primary_host = hosts.most_common(1)[0][0] if hosts else ""
    return {
        "traj_id": traj.get("id"),
        "src_file": src_file,
        "title": (traj.get("title") or "").strip(),
        "description": traj.get("description"),
        "created_at": traj.get("createdAt"),
        "n_steps": len(steps),
        "n_interaction_steps": len(real_steps),
        "primary_host": primary_host,
        "hosts": sorted(hosts),
        "action_types": {k: v for k, v in action_types.most_common()},
    }


def cmd_index(args: argparse.Namespace) -> int:
    src = Path(args.src)
    files = sorted(src.glob("*.json"))
    if not files:
        print(f"no json files under {src}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_traj = 0
    host_counter: collections.Counter[str] = collections.Counter()
    with out_path.open("w", encoding="utf-8") as fh:
        for i, path in enumerate(files, 1):
            try:
                trajs = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"skip {path.name}: {exc}", file=sys.stderr)
                continue
            if not isinstance(trajs, list):
                continue
            for traj in trajs:
                if not isinstance(traj, dict) or not traj.get("id"):
                    continue
                row = traj_summary(traj, path.name)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_traj += 1
                if row["primary_host"]:
                    host_counter[row["primary_host"]] += 1
            if i % 100 == 0:
                print(f"  indexed {i}/{len(files)} files, {n_traj} trajectories", file=sys.stderr)

    print(f"indexed {n_traj} trajectories from {len(files)} files -> {out_path}")
    print(f"distinct primary hosts: {len(host_counter)}")
    print("top hosts:")
    for host, cnt in host_counter.most_common(20):
        print(f"  {cnt:5d}  {host}")
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(args.seed)

    by_host: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["primary_host"] and row["n_interaction_steps"] >= args.min_steps:
            by_host[row["primary_host"]].append(row)

    eligible = [(h, rs) for h, rs in by_host.items() if len(rs) >= args.per_host]
    eligible.sort(key=lambda kv: -len(kv[1]))

    picked: list[dict] = []
    for host, rs in eligible:
        if len(picked) >= args.n:
            break
        take = min(args.per_host, args.n - len(picked))
        picked.extend(rng.sample(rs, take))

    # 站点不足时用其余轨迹补齐
    if len(picked) < args.n:
        chosen_ids = {r["traj_id"] for r in picked}
        rest = [r for r in rows if r["traj_id"] not in chosen_ids and r["n_interaction_steps"] >= args.min_steps]
        rng.shuffle(rest)
        picked.extend(rest[: args.n - len(picked)])

    # 回填完整轨迹内容
    need: dict[str, set[str]] = collections.defaultdict(set)
    for row in picked:
        need[row["src_file"]].add(row["traj_id"])

    src = Path(args.src)
    full_by_id: dict[str, dict] = {}
    for fname, ids in need.items():
        trajs = json.loads((src / fname).read_text(encoding="utf-8"))
        for traj in trajs:
            if isinstance(traj, dict) and traj.get("id") in ids:
                full_by_id[traj["id"]] = traj

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for row in picked:
            traj = full_by_id.get(row["traj_id"])
            if traj is None:
                print(f"missing content for {row['traj_id']}", file=sys.stderr)
                continue
            fh.write(json.dumps({"summary": row, "trajectory": traj}, ensure_ascii=False) + "\n")
            written += 1

    host_dist = collections.Counter(r["primary_host"] for r in picked)
    print(f"selected {written} trajectories over {len(host_dist)} hosts -> {out_path}")
    for host, cnt in host_dist.most_common():
        print(f"  {cnt:4d}  {host}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser("index", help="扫描全部 json 建轨迹索引")
    p_idx.add_argument("--src", required=True, help="all_json_files 目录")
    p_idx.add_argument("--out", required=True)
    p_idx.set_defaults(func=cmd_index)

    p_sel = sub.add_parser("select", help="按站点分层抽子集")
    p_sel.add_argument("--index", required=True)
    p_sel.add_argument("--src", required=True)
    p_sel.add_argument("--out", required=True)
    p_sel.add_argument("--n", type=int, default=100)
    p_sel.add_argument("--per-host", type=int, default=10, help="每个站点最多抽几条")
    p_sel.add_argument("--min-steps", type=int, default=3, help="真实交互步数下限")
    p_sel.add_argument("--seed", type=int, default=20260914)
    p_sel.set_defaults(func=cmd_select)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
