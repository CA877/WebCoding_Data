#!/usr/bin/env python3
"""从 Qwen/WebWorldData 的单个 52 GB JSONL 中抽取长度分层的子集。

背景：WebWorldData 只发布一个 `WebWorld_Training.jsonl`，记录内没有 level/source
字段，无法按元数据切出论文里的 Level 1（随机爬取）与 Level 2（自主探索）。
论文给出的可观测差异是轨迹长度：Level 1 为 3-10 步，Level 2 为 up to 30 步。
因此这里按「记录内的有效动作数」做代理切分：

  autonomous  : n_actions >= --min-auto （默认 10，对应论文 Level 2 的长程特征）
  random      : --min-rand <= n_actions <= --max-rand （默认 3-10，对应 Level 1）

**这是代理指标，不是官方标注**，统计口径必须在报告里写明。

实现要点（实测决定）：
- 直连单连接吞吐约 0.48 MB/s（16 MB / 33 s），8 并发约 3.7 MB/s，服务端按连接限速；
  因此采用 curl 子进程做**并行 range 拉取**，而不是单流顺序读。
- 记录在文件内分布均匀、与字节位置无关（100 点 × 400 KB 稀疏采样已验证 0-88% 区间
  格式单一），所以扫描任意连续区间都可用于收集，无需定位特定分层区域。
- 跨 chunk 边界的记录会被丢弃（各 chunk 首行截断即丢），对配额收集无影响。

每命中一条立即 append 落盘并 flush，支持断点续跑（读取已有文件的 record_key 去重）。

用法：
  uv run python scripts/fetch_webworld_subset.py \\
      --url https://hf-mirror.com/datasets/Qwen/WebWorldData/resolve/main/WebWorld_Training.jsonl \\
      --out-dir datasets/webworld_explore \\
      --n-autonomous 100 --n-random 100
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ACTION_RE = re.compile(r"Action:\s*'(.+?)'\s*\n")
ACTION_FN_RE = re.compile(r"^\s*([a-z_]+)\s*\(")
URL_RE = re.compile(r"https?://([^\s/'\"]+)")

# 与 Level 1 的 3-10 步对齐：这些不是页面交互动作
NON_INTERACTION_ACTIONS = {"launch_app", "noop", "send_msg_to_user"}


def fetch_range(url: str, start: int, end: int, *, retries: int = 3, timeout: float = 120.0) -> bytes:
    """用 curl 拉取 [start, end] 字节区间，含重试。"""
    last_err = ""
    for attempt in range(retries):
        proc = subprocess.run(
            ["curl", "-sL", "--fail", "--max-time", str(int(timeout)),
             "-r", f"{start}-{end}", url],
            capture_output=True,
        )
        if proc.returncode == 0:
            return proc.stdout
        last_err = proc.stderr.decode("utf-8", "replace")[:200] or f"curl exit {proc.returncode}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"range {start}-{end} failed: {last_err}")


def record_features(rec: dict) -> dict | None:
    """抽取一条 WebWorld 训练记录的可度量特征；非 world-model 记录返回 None。"""
    convs = rec.get("conversations")
    if not isinstance(convs, list) or not convs:
        return None
    if not str(convs[0].get("value", "")).startswith("You are a web world model"):
        return None

    actions: list[str] = []
    hosts: collections.Counter[str] = collections.Counter()
    for conv in convs:
        if conv.get("from") != "human":
            continue
        value = conv.get("value", "")
        actions.extend(ACTION_RE.findall(value))
        for host in URL_RE.findall(value):
            hosts[host] += 1

    action_types = [m.group(1) for a in actions if (m := ACTION_FN_RE.match(a))]
    meaningful = [t for t in action_types if t not in NON_INTERACTION_ACTIONS]
    return {
        "n_actions": len(meaningful),
        "n_raw_actions": len(actions),
        "action_types": dict(collections.Counter(action_types)),
        "hosts": sorted(hosts),
        "primary_host": hosts.most_common(1)[0][0] if hosts else "",
        "n_turns": len(convs),
    }


def parse_chunk(raw: bytes, chunk_start: int) -> list[tuple[str, int, dict]]:
    """解析一个 chunk 的完整行。首行与末行都可能被截断，一并丢弃。"""
    out: list[tuple[str, int, dict]] = []
    for line_no, line in enumerate(raw.split(b"\n")[1:-1]):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # chunk 尾部可能截断在多字节字符中间，只丢这一行，不丢整块
            continue
        out.append((f"{chunk_start}:{line_no}", chunk_start, rec))
    return out


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
                done.add(json.loads(line)["record_key"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--n-autonomous", type=int, default=100)
    ap.add_argument("--n-random", type=int, default=100)
    ap.add_argument("--min-auto", type=int, default=10)
    ap.add_argument("--min-rand", type=int, default=3)
    ap.add_argument("--max-rand", type=int, default=10)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--chunk-mb", type=int, default=16)
    ap.add_argument("--scan-gb", type=float, default=2.0, help="扫描总量上限")
    ap.add_argument("--start-gb", type=float, default=0.0, help="从文件的第几 GB 开始扫")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    auto_path = out_dir / f"autonomous_{args.n_autonomous}.jsonl"
    rand_path = out_dir / f"random_{args.n_random}.jsonl"

    done = load_done(auto_path) | load_done(rand_path)
    n_auto = sum(1 for _ in auto_path.open(encoding="utf-8")) if auto_path.exists() else 0
    n_rand = sum(1 for _ in rand_path.open(encoding="utf-8")) if rand_path.exists() else 0
    print(f"resume: auto={n_auto}/{args.n_autonomous} rand={n_rand}/{args.n_random} done={len(done)}")

    if n_auto >= args.n_autonomous and n_rand >= args.n_random:
        print("both quotas already satisfied")
        return 0

    chunk = args.chunk_mb << 20
    base = int(args.start_gb * (1 << 30))
    n_chunks = int(args.scan_gb * (1 << 30) / chunk)

    stats = collections.Counter()
    started = time.time()
    scanned = 0
    lock = threading.Lock()
    auto_fh = auto_path.open("a", encoding="utf-8")
    rand_fh = rand_path.open("a", encoding="utf-8")

    def consume(chunk_start: int) -> None:
        nonlocal n_auto, n_rand, scanned
        raw = fetch_range(args.url, chunk_start, chunk_start + chunk - 1)
        rows = parse_chunk(raw, chunk_start)
        with lock:
            scanned += len(raw)
            for key, offset, rec in rows:
                if key in done:
                    continue
                feats = record_features(rec)
                if feats is None:
                    stats["non_interaction"] += 1
                    continue
                stats["interaction"] += 1
                n = feats["n_actions"]
                bucket = None
                if n >= args.min_auto and n_auto < args.n_autonomous:
                    bucket = "autonomous"
                elif args.min_rand <= n <= args.max_rand and n_rand < args.n_random:
                    bucket = "random"
                if bucket is None:
                    stats["skipped_quota_or_band"] += 1
                    continue
                row = {"record_key": key, "byte_offset": offset, "bucket": bucket,
                       "features": feats, "conversations": rec["conversations"]}
                fh = auto_fh if bucket == "autonomous" else rand_fh
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                done.add(key)
                if bucket == "autonomous":
                    n_auto += 1
                else:
                    n_rand += 1
                stats[f"collected_{bucket}"] += 1
                print(f"  [{bucket}] {key} actions={n} turns={feats['n_turns']} "
                      f"host={feats['primary_host']} -> auto={n_auto} rand={n_rand}", file=sys.stderr)

    # 提交全部 chunk 交给线程池连续调度，避免按波次等待造成的屏障停顿
    try:
        all_chunks = [base + i * chunk for i in range(n_chunks)]
        pending = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(consume, cs) for cs in all_chunks]
            for fut in as_completed(futs):
                pending += 1
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001 - 单 chunk 失败不阻断整批
                    stats["chunk_failed"] += 1
                    print(f"  chunk failed: {exc}", file=sys.stderr)
                if pending % args.workers == 0:
                    elapsed = time.time() - started
                    print(f"  ... {scanned/1e6:.0f} MB scanned ({scanned/1e6/max(elapsed,1e-9):.1f} MB/s), "
                          f"auto={n_auto} rand={n_rand}, elapsed={elapsed:.0f}s", file=sys.stderr)
                if n_auto >= args.n_autonomous and n_rand >= args.n_random:
                    for f in futs:
                        f.cancel()
                    break
    finally:
        auto_fh.close()
        rand_fh.close()

    summary = {
        "url": args.url,
        "scanned_mb": round(scanned / 1e6, 1),
        "elapsed_sec": round(time.time() - started, 1),
        "throughput_mbps": round(scanned / 1e6 / max(time.time() - started, 1e-9), 2),
        "counts": dict(stats),
        "n_autonomous": n_auto,
        "n_random": n_rand,
        "bands": {"autonomous": f">= {args.min_auto} actions",
                  "random": f"{args.min_rand}-{args.max_rand} actions"},
        "caveat": "长度分层是论文 Level 1/Level 2 的代理指标，非官方标注",
    }
    (out_dir / "subset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
