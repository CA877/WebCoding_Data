#!/usr/bin/env python3
"""把三组卡片聚成「同一个 capability」的等价类，供重合率与 unique 数使用。

口径（经用户确认）：**embedding 召回 + LLM 判定**。
1. 用 `capability_embedding_text` 生成卡片向量，取余弦相似度不低于 `--candidate-threshold`
   的卡片对作为候选。该阈值**只影响召回**，最终判定由 LLM 给出，因此可以放宽；
   `--candidate-threshold` 做敏感性分析用。
2. 对每个候选对，把两张卡片的精简视图送给 LLM 判定「是否同一个 capability」，并要求
   说明依据。跨数据集的对也要判——这正是重合率的基础。
3. 用并查集把确认的对合并成等价类，输出每个 card_uid 的 cluster_id。

候选对数量用 `--max-pairs` 截断（按相似度从高到低），避免批量成本失控；被截断的数量
写进 summary，便于判断结果是否受截断影响。

结果 append 落盘，按 pair_key 断点续跑。

用法：
  uv run python inspiration_library/utils/cluster_capabilities.py \\
      --runs-dir runs/capability_study/full \\
      --out runs/capability_study/full/capability_clusters.jsonl \\
      --pairs-out runs/capability_study/full/capability_pairs.jsonl \\
      --workers 6 --candidate-threshold 0.75 --max-pairs 3000
"""

from __future__ import annotations

import argparse
import json
import math
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
from inspiration_library.dynamic_capability_retrieval import capability_embedding_text

SYSTEM_PROMPT = (
    "You decide whether two capability cards describe the SAME reusable capability, or two "
    "different ones. Same means a developer could implement one component to cover both: the "
    "same kind of state is created, changed and presented through the same interaction pattern. "
    "A different product, brand, language, wording, page, or data content does NOT make them "
    "different. Cards that only share a generic control (a button, a list) are different unless "
    "the same stateful behavior is described. Judge the described behavior, not the phrasing.\n"
    "Return compact JSON: {\"same\": true|false, \"confidence\": \"high\"|\"medium\"|\"low\", "
    "\"rationale\": one short factual clause naming the shared or differing behavior}."
)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        fh.flush()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def card_view(card: dict) -> dict[str, Any]:
    """判定用的精简视图：行为字段，不含站点、不含 state id、不含数据集名。"""
    return {
        "name": card.get("name"),
        "change_type": card.get("change_type", card.get("family")),
        "summary": card.get("summary"),
        "user_actions": card.get("user_actions"),
        "state_reads": card.get("state_reads"),
        "state_writes": card.get("state_writes"),
        "visible_result": card.get("visible_result"),
        "future_uses": card.get("future_uses"),
    }


def collect_cards(runs_dir: Path) -> list[dict]:
    from inspiration_library.utils.classify_capability_cards import collect_cards as _collect
    return _collect(runs_dir)


class UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != root:
            self.parent[key], key = root, self.parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[max(root_left, root_right)] = min(root_left, root_right)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="每个 card_uid 的 cluster 归属")
    ap.add_argument("--pairs-out", type=Path, required=True, help="候选对及其判定结果")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--candidate-threshold", type=float, default=0.75)
    ap.add_argument("--max-pairs", type=int, default=3000)
    ap.add_argument("--embed-batch", type=int, default=10)
    ap.add_argument("--embed-dim", type=int, default=1024)
    ap.add_argument("--api-timeout-seconds", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2, choices=(1, 2, 3))
    args = ap.parse_args()

    cards = collect_cards(args.runs_dir)
    if len(cards) < 2:
        raise SystemExit(f"need at least two cards to cluster, found {len(cards)}")
    print(f"{len(cards)} cards from {args.runs_dir}")

    key = os.environ.get("DOC_API_KEY")
    if not key:
        raise SystemExit("DOC_API_KEY is required")
    client = DocApiClient(api_key=key, log_dir=args.out.parent / "provider_cluster",
                          timeout_seconds=args.api_timeout_seconds, request_attempts=args.retries)

    started = time.time()
    vectors: dict[str, list[float]] = {}
    try:
        for start in range(0, len(cards), args.embed_batch):
            batch = cards[start:start + args.embed_batch]
            texts = [capability_embedding_text(item["card"]) for item in batch]
            vecs, _ = client.embeddings(
                request_id=f"embed__{start:05d}", inputs=texts, dimensions=args.embed_dim)
            for item, vec in zip(batch, vecs):
                vectors[item["card_uid"]] = vec
            if (start // args.embed_batch) % 5 == 0:
                print(f"  embedded {len(vectors)}/{len(cards)} elapsed={time.time()-started:.0f}s",
                      file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        client.close()
        raise SystemExit(f"embedding failed: {type(exc).__name__}: {exc}")

    candidates: list[tuple[float, str, str]] = []
    uids = [item["card_uid"] for item in cards]
    for i, left in enumerate(uids):
        for right in uids[i + 1:]:
            score = cosine(vectors[left], vectors[right])
            if score >= args.candidate_threshold:
                candidates.append((score, left, right))
    candidates.sort(key=lambda row: -row[0])
    truncated = max(0, len(candidates) - args.max_pairs)
    candidates = candidates[: args.max_pairs]
    print(f"{len(candidates)} candidate pairs (threshold={args.candidate_threshold}), "
          f"truncated={truncated}")

    by_uid = {item["card_uid"]: item for item in cards}
    done_pairs = {row["pair_key"]: row for row in read_jsonl(args.pairs_out) if row.get("status") == "ok"}
    lock = threading.Lock()

    def judge(score: float, left: str, right: str) -> dict:
        pair_key = f"{left}||{right}"
        existing = done_pairs.get(pair_key)
        if existing is not None:
            return existing
        task = ("CARD A\n" + json.dumps(card_view(by_uid[left]["card"]), ensure_ascii=False)
                + "\nCARD B\n" + json.dumps(card_view(by_uid[right]["card"]), ensure_ascii=False))
        record: dict[str, Any] = {"pair_key": pair_key, "similarity": round(score, 4),
                                  "left": left, "right": right,
                                  "left_bucket": by_uid[left]["bucket"],
                                  "right_bucket": by_uid[right]["bucket"]}
        try:
            payload, _ = client.chat_json(
                request_id=f"pair__{abs(hash(pair_key)) % (10**12):012d}",
                system_prompt=SYSTEM_PROMPT, stable_context="", task=task,
                max_tokens=400, stream=False)
            record["status"] = "ok"
            record["same"] = bool(payload.get("same"))
            record["confidence"] = payload.get("confidence")
            record["rationale"] = payload.get("rationale")
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["error"] = f"{type(exc).__name__}: {exc}"[:400]
        with lock:
            append_jsonl(args.pairs_out, record)
        return record

    judged: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(judge, score, left, right) for score, left, right in candidates]
            for index, fut in enumerate(as_completed(futs), 1):
                try:
                    judged.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    judged.append({"status": "error", "error": str(exc)[:200]})
                if index % 25 == 0 or index == len(candidates):
                    same = sum(1 for row in judged if row.get("same"))
                    print(f"  {index}/{len(candidates)} pairs, same={same} "
                          f"elapsed={time.time()-started:.0f}s", file=sys.stderr)
    finally:
        client.close()

    uf = UnionFind([item["card_uid"] for item in cards])
    confirmed = 0
    for row in judged:
        if row.get("status") == "ok" and row.get("same"):
            uf.union(row["left"], row["right"])
            confirmed += 1

    clusters: dict[str, list[str]] = {}
    for item in cards:
        clusters.setdefault(uf.find(item["card_uid"]), []).append(item["card_uid"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for root, members in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
            for uid in members:
                fh.write(json.dumps({
                    "card_uid": uid,
                    "cluster_id": root,
                    "cluster_size": len(members),
                    "bucket": by_uid[uid]["bucket"],
                    "seed_id": by_uid[uid]["seed_id"],
                    "entry_url": by_uid[uid]["entry_url"],
                }, ensure_ascii=False) + "\n")

    summary = {
        "n_cards": len(cards),
        "n_candidate_pairs": len(candidates),
        "n_candidate_pairs_truncated": truncated,
        "candidate_threshold": args.candidate_threshold,
        "n_confirmed_same_pairs": confirmed,
        "n_clusters": len(clusters),
        "largest_clusters": [{"cluster_id": root, "size": len(members),
                              "buckets": sorted({by_uid[u]["bucket"] for u in members})}
                             for root, members in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:10]],
        "elapsed_sec": round(time.time() - started, 1),
    }
    (args.out.parent / "cluster_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
