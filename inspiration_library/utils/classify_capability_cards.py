#!/usr/bin/env python3
"""给每张 capability card 判定「导航/信息获取 vs 可迁移产品交互」。

为什么单独做这一步：抽取器自带的 16 类 taxonomy（`edit_taxonomy.WEBCOMPASS_EDIT_FUNCTIONS`）
全部是**产品交互**类，没有「导航」这一类；而且抽取器的 prompt 明确要求省略
navigation / search / theme / support 行为。所以卡片里已经看不到大部分导航行为，
**卡片层面的占比只能反映残差**，这个偏置必须在报告里写明。分类本身是语义判断，
按仓库约定交给 LLM，不用正则/关键词。

为了让分类不受来源影响，prompt 只送卡片字段，**不送数据集名与站点名**；来源只写在
结果里用于事后分组。判定分三档，其中 `presentation_only` 单列，从而二分类
（导航 vs 可迁移交互）仍可从结果推出。

支持断点续跑（按 card_uid 跳过）、并发、每 case 超时、逐条 append 落盘。

用法：
  uv run python inspiration_library/utils/classify_capability_cards.py \\
      --runs-dir runs/capability_study/pilot --out runs/capability_study/pilot/card_kinds.jsonl \\
      --workers 6 --api-timeout-seconds 120
"""

from __future__ import annotations

import argparse
import json
import os
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

KINDS = ("navigation_or_information_gathering", "transferable_product_interaction", "presentation_only")

# 示例刻意取自与研究数据无关的领域（日历预订 / 天气小组件），避免泄漏当前数据
SYSTEM_PROMPT = (
    "You classify one capability card extracted from a web page into exactly one kind. "
    "A capability card describes an observed feature with its summary, the user actions that "
    "drive it, the state it reads and writes, and its visible result.\n"
    "Kinds:\n"
    "- transferable_product_interaction: a complete component-level functional system that "
    "changes state in response to user action and could be re-implemented in a different "
    "product, e.g. a booking flow that validates dates and confirms a reservation, a cart that "
    "recomputes totals, an editor that persists formatting.\n"
    "- navigation_or_information_gathering: behavior whose only purpose is reaching another "
    "view or obtaining information, e.g. moving between pages or sections, searching, "
    "table-of-contents jumps, paging through a list, or expanding content purely to read it. "
    "It does not maintain product state of its own.\n"
    "- presentation_only: visual or static behavior with no user-driven state change, e.g. an "
    "animation, a scroll effect, theming, typography or layout.\n"
    "Decide by what the capability does, not by which controls it mentions. If a card bundles "
    "several behaviors, classify by the dominant stateful behavior and say so in the rationale.\n"
    "Return compact JSON: {\"kind\": one of the three exact strings, "
    "\"confidence\": \"high\"|\"medium\"|\"low\", \"rationale\": one short factual clause}."
)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
            if row.get("card_uid") and row.get("status") == "ok":
                done.add(row["card_uid"])
    return done


def card_view(card: dict) -> dict[str, Any]:
    """只保留判定所需字段；不含数据集名、站点名、state id。"""
    return {
        "name": card.get("name"),
        "family": card.get("family"),
        "change_type": card.get("change_type"),
        "summary": card.get("summary"),
        "user_actions": card.get("user_actions"),
        "state_reads": card.get("state_reads"),
        "state_writes": card.get("state_writes"),
        "visible_result": card.get("visible_result"),
        "prerequisites": card.get("prerequisites"),
    }


def collect_cards(runs_dir: Path) -> list[dict]:
    """从三个 bucket 的抽取结果里收集所有卡片，附带来源元信息。"""
    cards: list[dict] = []
    for path in sorted(runs_dir.glob("*.jsonl")):
        if path.name in {"card_kinds.jsonl", "capability_clusters.jsonl"}:
            continue
        for row in read_jsonl(path):
            if row.get("status") != "ok":
                continue
            bucket = row.get("bucket") or path.stem
            extraction = row.get("extraction") or {}
            for card in extraction.get("capabilities") or []:
                cards.append({
                    "card_uid": f"{bucket}::{row.get('seed_id')}::{card.get('capability_id')}",
                    "bucket": bucket,
                    "seed_id": row.get("seed_id"),
                    "entry_url": row.get("entry_url"),
                    "card": card,
                })
    return cards


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--api-timeout-seconds", type=float, default=120.0)
    ap.add_argument("--retries", type=int, default=2, choices=(1, 2, 3))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cards = collect_cards(args.runs_dir)
    if args.limit:
        cards = cards[: args.limit]
    if not cards:
        raise SystemExit(f"no capability cards found under {args.runs_dir}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(args.out)
    print(f"{len(cards)} cards, {len(done)} already classified -> {args.out}")

    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise SystemExit("DOC_API_KEY is required")

    lock = threading.Lock()
    started = time.time()
    out_fh = args.out.open("a", encoding="utf-8")
    client = DocApiClient(api_key=key, log_dir=args.out.parent / "provider_classify",
                          timeout_seconds=args.api_timeout_seconds, request_attempts=args.retries)

    def process(item: dict) -> dict:
        if item["card_uid"] in done:
            return {"status": "skipped_existing"}
        task = "CAPABILITY CARD\n" + json.dumps(card_view(item["card"]), ensure_ascii=False)
        record: dict[str, Any] = {"card_uid": item["card_uid"], "bucket": item["bucket"],
                                  "seed_id": item["seed_id"], "entry_url": item["entry_url"],
                                  "capability_id": item["card"].get("capability_id"),
                                  "family": item["card"].get("family")}
        try:
            payload, _ = client.chat_json(
                request_id=f"classify__{item['card_uid']}"[:180],
                system_prompt=SYSTEM_PROMPT, stable_context="", task=task,
                max_tokens=400, stream=False)
            kind = str(payload.get("kind") or "").strip()
            if kind not in KINDS:
                record["status"] = "invalid_kind"
                record["error"] = f"model returned kind={kind!r}"
            else:
                record["status"] = "ok"
                record["interaction_kind"] = kind
                record["confidence"] = payload.get("confidence")
                record["rationale"] = payload.get("rationale")
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["error"] = f"{type(exc).__name__}: {exc}"[:400]
        with lock:
            out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_fh.flush()
        return record

    counts: dict[str, int] = {}
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(process, item) for item in cards]
            for index, fut in enumerate(as_completed(futs), 1):
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001
                    res = {"status": "error", "error": str(exc)[:200]}
                counts[res["status"]] = counts.get(res["status"], 0) + 1
                if index % 25 == 0 or index == len(cards):
                    print(f"  {index}/{len(cards)} {counts} elapsed={time.time()-started:.0f}s",
                          file=sys.stderr)
    finally:
        out_fh.close()
        client.close()

    print(f"done in {time.time()-started:.0f}s: {counts} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
