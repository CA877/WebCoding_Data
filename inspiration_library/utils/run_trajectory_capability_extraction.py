#!/usr/bin/env python3
"""用同一套抽取器把两条轨迹数据集的轨迹转成 capability cards。

对每条轨迹：adapter 转出 `(seed, observation)` → `extract_seed_capabilities` →
逐条 append 落盘。抽取器、卡片 schema、prompt 全部不变，因此两组结果可比。

输入：
  --dataset webchain   需要 --axtrees-dir（`fetch_webchain_axtrees.py` 的产物目录）
  --dataset webworld   WebWorldData world-model 记录（需要记录内的 conversations）

产物每行一条轨迹，含 `status`、卡片原文与观测统计，供后续分类与聚合脚本使用。
支持断点续跑（按 seed_id 跳过已有结果）、并发、每 case 超时（由 `--api-timeout-seconds`
约束单次请求）、结果实时落盘。

用法：
  uv run python inspiration_library/utils/run_trajectory_capability_extraction.py \\
      --dataset webworld --input datasets/webworld_explore/autonomous_100.jsonl \\
      --bucket webworld_autonomous --out runs/capability_study/webworld_autonomous.jsonl \\
      --limit 10 --workers 4 --api-timeout-seconds 300
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inspiration_library.doc_api import DocApiClient
from inspiration_library.trajectory_capability_adapter import (
    NoTrajectoryEvidence,
    load_axtrees,
    webchain_to_observation,
    webworld_record_to_observation,
)

SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_id(value: str) -> str:
    return SAFE_ID_RE.sub("_", value).strip("_")


def load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("seed_id") and row.get("status") == "ok":
                done.add(row["seed_id"])
    return done


def build_case(dataset: str, row: dict, axtrees_dir: Path | None) -> tuple[str, dict, dict, dict]:
    """返回 (seed_id, seed, observation, 观测统计)。"""
    if dataset == "webworld":
        bucket = row.get("bucket") or "unknown"
        seed_id = f"webworld_{bucket}__{safe_id(row['record_key'])}"
        seed, observation = webworld_record_to_observation(
            row, seed_id=seed_id, host=(row.get("features") or {}).get("primary_host", ""))
    else:
        traj = row["trajectory"]
        traj_id = traj["id"]
        seed_id = f"webchain__{safe_id(traj_id)}"
        axtrees = load_axtrees(axtrees_dir / f"{traj_id}.json.gz") if axtrees_dir else {}
        seed, observation = webchain_to_observation(traj, axtrees, seed_id=seed_id)
    path = observation["exploration_paths"][0]
    stats = {
        "n_steps": len(path["steps"]),
        "n_controls_baseline": len(observation["baseline"].get("interactive") or []),
        "action_types": {},
    }
    for step in path["steps"]:
        action = step["action"]["action"]
        stats["action_types"][action] = stats["action_types"].get(action, 0) + 1
    return seed_id, seed, observation, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=("webchain", "webworld"), required=True)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--bucket", required=True, help="结果里记录的数据集分层标签")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--axtrees-dir", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--api-timeout-seconds", type=float, default=300.0)
    ap.add_argument("--retries", type=int, default=2, choices=(1, 2, 3))
    ap.add_argument("--dry-run", action="store_true", help="只做 adapter 转换与证据统计，不调用 LLM")
    args = ap.parse_args()

    if args.dataset == "webchain" and not args.axtrees_dir:
        ap.error("--axtrees-dir is required for the webchain dataset")

    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(args.out)
    print(f"{len(rows)} input rows, {len(done)} already done -> {args.out}")

    lock = threading.Lock()
    started = time.time()

    if args.dry_run:
        summary: dict[str, Any] = {"cases": 0, "failed": 0, "steps": [], "evidence_chars": []}
        from inspiration_library.deep_browser_exploration import compact_live_browser_evidence_for_llm
        for index, row in enumerate(rows, 1):
            try:
                seed_id, seed, observation, stats = build_case(args.dataset, row, args.axtrees_dir)
            except NoTrajectoryEvidence as exc:
                summary["no_evidence"] = summary.get("no_evidence", 0) + 1
                print(f"  [{index}] NO EVIDENCE: {exc}", file=sys.stderr)
                continue
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                print(f"  [{index}] FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            evidence = compact_live_browser_evidence_for_llm(
                observation, include_selectors=False, include_action_steps=True)
            summary["cases"] += 1
            summary["steps"].append(stats["n_steps"])
            summary["evidence_chars"].append(len(json.dumps(evidence, ensure_ascii=False)))
        if summary["steps"]:
            import statistics
            print(f"dry-run: {summary['cases']} ok, {summary['failed']} failed, "
                  f"{summary.get('no_evidence', 0)} no_evidence | "
                  f"steps med={statistics.median(summary['steps']):.0f} max={max(summary['steps'])} | "
                  f"evidence chars med={statistics.median(summary['evidence_chars'])/1000:.0f}k "
                  f"max={max(summary['evidence_chars'])/1000:.0f}k")
        else:
            print(f"dry-run: 0 ok, {summary['failed']} failed")
        return 1 if summary["failed"] else 0

    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise SystemExit("DOC_API_KEY is required")

    out_fh = args.out.open("a", encoding="utf-8")
    client = DocApiClient(api_key=key, log_dir=args.out.parent / "provider",
                          timeout_seconds=args.api_timeout_seconds, request_attempts=args.retries)

    def process(index: int, row: dict) -> dict:
        try:
            seed_id, seed, observation, stats = build_case(args.dataset, row, args.axtrees_dir)
        except NoTrajectoryEvidence as exc:
            # 轨迹本身没有结构证据，不是代码问题，单列状态
            with lock:
                out_fh.write(json.dumps({"status": "no_evidence", "bucket": args.bucket,
                                         "seed_id": f"{args.bucket}__row_{index}",
                                         "error": str(exc)[:400]}, ensure_ascii=False) + "\n")
                out_fh.flush()
            return {"status": "no_evidence", "index": index}
        except Exception as exc:  # noqa: BLE001 - 单条数据问题不阻断整批
            with lock:
                out_fh.write(json.dumps({"status": "adapter_error", "bucket": args.bucket,
                                         "seed_id": f"{args.bucket}__row_{index}",
                                         "error": f"{type(exc).__name__}: {exc}"[:400]},
                                        ensure_ascii=False) + "\n")
                out_fh.flush()
            return {"status": "adapter_error", "index": index}
        if seed_id in done:
            return {"status": "skipped_existing", "index": index}

        from inspiration_library.dynamic_capability_retrieval import extract_seed_capabilities

        request_id = f"{args.bucket}__{safe_id(seed_id)}"
        started_case = time.time()
        record: dict[str, Any] = {"seed_id": seed_id, "dataset": args.dataset,
                                  "bucket": args.bucket, "entry_url": seed["entry_url"],
                                  "observation_stats": stats}
        try:
            extraction = extract_seed_capabilities(
                seed=seed, observation=observation, client=client, request_id=request_id)
            record["status"] = "ok"
            record["extraction"] = extraction
            record["n_capabilities"] = len(extraction.get("capabilities") or [])
            record["n_business_objects"] = len(extraction.get("business_objects") or [])
            record["abstention_reason"] = extraction.get("abstention_reason")
        except TimeoutError as exc:
            record["status"] = "timeout"
            record["error"] = str(exc)[:400]
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["error"] = f"{type(exc).__name__}: {exc}"[:400]
        record["elapsed_sec"] = round(time.time() - started_case, 1)
        with lock:
            out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fh.flush()
        return {"status": record["status"], "index": index,
                "seed_id": seed_id, "n_capabilities": record.get("n_capabilities"),
                "elapsed_sec": record["elapsed_sec"]}

    results: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(process, i, row) for i, row in enumerate(rows, 1)]
            for fut in as_completed(futs):
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001
                    res = {"status": "error", "error": str(exc)[:200]}
                results.append(res)
                print(f"[{len(results)}/{len(rows)}] {res.get('seed_id','?')} {res['status']} "
                      f"cards={res.get('n_capabilities','-')} {res.get('elapsed_sec','-')}s "
                      f"elapsed={time.time()-started:.0f}s", file=sys.stderr)
    finally:
        out_fh.close()
        client.close()

    counts: dict[str, int] = {}
    for res in results:
        counts[res["status"]] = counts.get(res["status"], 0) + 1
    print(f"\ndone in {time.time()-started:.0f}s: {counts} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
