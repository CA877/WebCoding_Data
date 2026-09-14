#!/usr/bin/env python3
"""按字节偏移采样 Qwen/WebWorldData 的单文件 JSONL，推断数据在文件内的排布。

背景：WebWorldData 只发布一个 `WebWorld_Training.jsonl`（~52 GB），记录内没有
level/source 字段。README 说明该数据集由 6 个来源合成（Level 1 随机爬取 293K、
Level 2 自主探索 38K、Level 3 任务执行 94K、开源轨迹 38K、多格式 48K、通用 QA 548K），
但未说明这些来源在文件中的顺序。本脚本用 HTTP Range 稀疏采样整个文件，按记录格式
签名分类，给出各格式在文件字节轴上的分布，用于判断能否直接按偏移切出目标子集。

只读探测，不写数据集本体；结果写入 --out 指定的 jsonl。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_URL = (
    "https://hf-mirror.com/datasets/Qwen/WebWorldData/resolve/main/WebWorld_Training.jsonl"
)
DEFAULT_SIZE = 52_243_347_728  # bytes, checked via HEAD Content-Length

ACTION_RE = re.compile(r"Action:\s*'(.+?)'\s*\n")
ACTION_FN_RE = re.compile(r"^\s*([a-z_]+)\s*\(")

WEBDEV_HEAD_RE = re.compile(
    r"^\s*(Create|Generate|Build|Design|Make)\b.{0,120}\b(page|site|website|homepage|app|dashboard|blog|interface|ui)\b",
    re.IGNORECASE | re.DOTALL,
)


def classify(first_human: str, n_turns: int, n_actions: int) -> str:
    """按首个人类消息的格式签名给记录归类。"""
    head = first_human.lstrip()

    if head.startswith("You are a web world model"):
        return "world_model_a11y"
    if head.startswith("Current observation:") or head.startswith("Agent:"):
        return "agent_observation"
    if "Current observation:" in head[:400] or head[:200].startswith("Agent:"):
        return "agent_observation"
    if WEBDEV_HEAD_RE.match(head):
        return "webdev_spec"
    if n_actions == 0:
        return "no_action_other"
    return "other_with_action"


def fetch_chunk(url: str, offset: int, length: int, retries: int = 3) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": "curl/8"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - 网络抖动需重试
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed at offset {offset}: {last_err}")


def probe_offset(url: str, offset: int, size: int, chunk: int) -> list[dict]:
    raw = fetch_chunk(url, offset, chunk)
    # 首个换行前的片段可能被截断，丢弃
    pieces = raw.split(b"\n")[1:]
    rows: list[dict] = []
    for piece in pieces:
        if not piece.strip():
            continue
        try:
            rec = json.loads(piece)
        except json.JSONDecodeError:
            continue
        convs = rec.get("conversations") or []
        if not convs:
            continue
        first_human = convs[0].get("value", "") if convs[0].get("from") == "human" else ""
        humans = [c for c in convs if c.get("from") == "human"]
        actions: list[str] = []
        for h in humans:
            actions.extend(ACTION_RE.findall(h.get("value", "")))
        fmt = classify(first_human, len(convs), len(actions))
        action_types = sorted({m.group(1) for a in actions if (m := ACTION_FN_RE.match(a))})
        rows.append(
            {
                "offset": offset,
                "pct": round(offset / size, 5),
                "n_turns": len(convs),
                "n_actions": len(actions),
                "format": fmt,
                "action_types": action_types,
                "head": first_human[:200],
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE)
    ap.add_argument("--n-probes", type=int, default=100, help="采样点数（均匀分布在文件字节轴）")
    ap.add_argument("--chunk", type=int, default=400_000, help="每个采样点抓取的字节数")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", required=True, help="输出 jsonl 路径")
    args = ap.parse_args()

    offsets = [int(args.size * i / args.n_probes) for i in range(args.n_probes)]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {
            pool.submit(probe_offset, args.url, off, args.size, args.chunk): off for off in offsets
        }
        for i, fut in enumerate(as_completed(futs), 1):
            off = futs[fut]
            try:
                rows = fut.result()
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[{i}/{len(offsets)}] offset {off} FAILED: {exc}", file=sys.stderr)
                continue
            all_rows.extend(rows)
            print(
                f"[{i}/{len(offsets)}] offset {off} ({off / args.size:.2%}) -> {len(rows)} records",
                file=sys.stderr,
            )

    all_rows.sort(key=lambda r: (r["offset"], r["n_turns"]))
    with out_path.open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 概览：每个采样点的主导格式
    by_off: dict[int, dict[str, int]] = {}
    for row in all_rows:
        by_off.setdefault(row["offset"], {})
        by_off[row["offset"]][row["format"]] = by_off[row["offset"]].get(row["format"], 0) + 1

    print(f"\n=== format share by byte offset (n_probes={args.n_probes}, failures={failures}) ===")
    for off in sorted(by_off):
        counts = by_off[off]
        top = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
        print(f"  {off / args.size:6.1%}  n={sum(counts.values()):3d}  {top}")

    overall: dict[str, int] = {}
    for row in all_rows:
        overall[row["format"]] = overall.get(row["format"], 0) + 1
    print("\n=== overall format share ===")
    total = max(sum(overall.values()), 1)
    for fmt, cnt in sorted(overall.items(), key=lambda x: -x[1]):
        print(f"  {fmt:22s} {cnt:5d}  {cnt / total:6.1%}")

    print(f"\nwrote {len(all_rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
