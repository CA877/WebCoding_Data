#!/usr/bin/env python3
"""从三份子集里抽一个可复现的小规模 pilot。

目的：在全量之前用最小单元验证「adapter → 抽取器 → 卡片 schema 校验」这条链路，并
用真实卡片判断质量（是否成体系、abstention 比例、导航类占比）。pilot 必须**有代表性**：
单纯取前 N 条会集中在同一站点、同一长度段，看不出问题。

抽样规则（确定性，同 seed 结果一致）：
  webchain   在 primary_host 上轮转取样，避免集中于单一站点；要求该轨迹的 axTree 可用
  webworld   按 n_actions 分位取样，覆盖长中短三档

用法：
  uv run python inspiration_library/utils/select_capability_study_pilot.py \\
      --webchain-subset datasets/webchain_explore/subset_100.jsonl \\
      --axtrees-dir datasets/webchain_explore/axtrees \\
      --webworld-autonomous datasets/webworld_explore/autonomous_100.jsonl \\
      --webworld-random datasets/webworld_explore/random_100.jsonl \\
      --out-dir datasets/capability_study_pilot --n-webchain 4 --n-webworld 3 --seed 20260914
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def pick_by_host_round_robin(rows: list[dict], count: int, hosts: dict[str, list[dict]]) -> list[dict]:
    """按主机轮转取样：每次从当前样本最多的主机里取一条，保证主机分散。"""
    order = sorted(hosts)
    picked: list[dict] = []
    cursors = {host: 0 for host in order}
    while len(picked) < count:
        progressed = False
        for host in order:
            if len(picked) >= count:
                break
            cursor = cursors[host]
            if cursor < len(hosts[host]):
                picked.append(hosts[host][cursor])
                cursors[host] = cursor + 1
                progressed = True
        if not progressed:
            break
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--webchain-subset", type=Path, required=True)
    ap.add_argument("--axtrees-dir", type=Path, required=True)
    ap.add_argument("--webworld-autonomous", type=Path, required=True)
    ap.add_argument("--webworld-random", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--n-webchain", type=int, default=4)
    ap.add_argument("--n-webworld", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260914)
    args = ap.parse_args()

    # WebChain：只保留 axTree 可用的轨迹，按主机分组后轮转取样
    hosts: dict[str, list[dict]] = {}
    unusable = 0
    for row in read_jsonl(args.webchain_subset):
        traj_id = row["trajectory"]["id"]
        if not (args.axtrees_dir / f"{traj_id}.json.gz").exists():
            unusable += 1
            continue
        host = str(row["summary"].get("primary_host") or "unknown")
        hosts.setdefault(host, []).append(row)
    webchain_pilot = pick_by_host_round_robin([], args.n_webchain, hosts)

    # WebWorld：按指定的轴分散取样。
    # - autonomous 段动作数实测几乎全为 10（数据在 10 处截断），动作数不具区分度，
    #   所以按主机分散；
    # - random 段多数记录没有主机（hosts 为空），按动作数分散。
    # 指定轴取不到值时退回另一轴，避免退化成「取前 N 条」。
    def diverse_pick(path: Path, count: int, primary: str) -> list[dict]:
        def key_of(row: dict) -> str:
            feats = row["features"]
            host = str(feats.get("primary_host") or "")
            actions = str(feats.get("n_actions"))
            return host if primary == "host" else actions

        def alt_of(row: dict) -> str:
            feats = row["features"]
            host = str(feats.get("primary_host") or "")
            actions = str(feats.get("n_actions"))
            return actions if primary == "host" else host

        rows = sorted(read_jsonl(path), key=lambda r: r["features"]["n_actions"])
        picked: list[dict] = []
        seen: set[str] = set()
        for getter in (key_of, alt_of):
            for row in rows:
                if row in picked:
                    continue
                marker = getter(row) or key_of(row)
                if marker in seen:
                    continue
                picked.append(row)
                seen.add(marker)
                if len(picked) >= count:
                    return picked
        return picked

    auto_pilot = diverse_pick(args.webworld_autonomous, args.n_webworld, "host")
    rand_pilot = diverse_pick(args.webworld_random, args.n_webworld, "actions")

    write_jsonl(args.out_dir / "webchain_pilot.jsonl", webchain_pilot)
    write_jsonl(args.out_dir / "webworld_autonomous_pilot.jsonl", auto_pilot)
    write_jsonl(args.out_dir / "webworld_random_pilot.jsonl", rand_pilot)

    manifest = {
        "seed": args.seed,
        "webchain": {
            "picked": [{"id": r["trajectory"]["id"], "host": r["summary"].get("primary_host"),
                        "steps": len(r["trajectory"].get("steps") or []),
                        "title": str(r["trajectory"].get("title"))[:120]} for r in webchain_pilot],
            "hosts_available": len(hosts),
            "skipped_without_axtree": unusable,
        },
        "webworld_autonomous": [{"record_key": r["record_key"], "n_actions": r["features"]["n_actions"],
                                 "host": r["features"].get("primary_host")} for r in auto_pilot],
        "webworld_random": [{"record_key": r["record_key"], "n_actions": r["features"]["n_actions"],
                             "host": r["features"].get("primary_host")} for r in rand_pilot],
    }
    (args.out_dir / "pilot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
