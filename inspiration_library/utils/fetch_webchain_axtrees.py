#!/usr/bin/env python3
"""抓取 WebChain 轨迹每一步的远端 Accessibility tree。

WebChain 的 `raw/json/*.json` 只在每一步给出 `axTree` / `html` / `img` 的**远端 URL**
（data.imean.tech），结构上下文并不在 zip 里。本脚本按子集逐轨迹下载 axTree 原始 JSON，
gzip 后按轨迹存一个文件，供 `trajectory_capability_adapter` 渲染成 A11y 文本。

依赖子集文件（`build_webchain_subset.py select` 的产物），每条记录形如
`{"summary": {...}, "trajectory": {..., "steps": [...]}}`。

特性：并发、单步超时与重试、逐轨迹落盘、按已有文件断点续跑（不覆盖已有结果）。

用法：
  uv run python inspiration_library/utils/fetch_webchain_axtrees.py \\
      --subset datasets/webchain_explore/subset_100.jsonl \\
      --out-dir datasets/webchain_explore/axtrees --concurrency 6
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

# 记录抓取失败原因，便于事后筛选重跑
FAILURE_CATEGORIES = ("connection_error", "timeout", "http_error", "decode_error", "no_url")


def fetch_one(client: httpx.Client, url: str, *, retries: int, timeout: float) -> tuple[object, str]:
    last = ("unknown", "error")
    for attempt in range(retries):
        try:
            resp = client.get(url, timeout=timeout)
            if resp.status_code != 200:
                last = (f"http_error_{resp.status_code}", "http_error")
            else:
                try:
                    return resp.json(), "ok"
                except ValueError as exc:
                    last = (f"decode_error: {exc}", "decode_error")
        except httpx.TimeoutException as exc:
            last = (f"timeout: {exc}", "timeout")
        except httpx.HTTPError as exc:
            last = (f"connection_error: {exc}", "connection_error")
        time.sleep(1.5 * (attempt + 1))
    return None, last[1]


def process_trajectory(
    client: httpx.Client, row: dict, out_dir: Path, *, retries: int, timeout: float
) -> dict:
    traj = row["trajectory"]
    traj_id = traj["id"]
    out_path = out_dir / f"{traj_id}.json.gz"
    if out_path.exists():
        return {"traj_id": traj_id, "status": "skipped_existing"}

    steps_payload: dict[str, dict] = {}
    statuses: list[str] = []
    for index, step in enumerate(traj.get("steps") or []):
        url = step.get("axTree")
        if not url:
            statuses.append("no_url")
            continue
        tree, status = fetch_one(client, url, retries=retries, timeout=timeout)
        statuses.append(status)
        if tree is None:
            continue
        steps_payload[str(index)] = {
            "ax_tree": tree,
            "step_type": step.get("type"),
            "step_title": step.get("title"),
            "step_value": step.get("value"),
            "selector": step.get("selector"),
            "host": step.get("host"),
            "href": step.get("href"),
        }

    payload = {
        "traj_id": traj_id,
        "title": traj.get("title"),
        "primary_host": row["summary"].get("primary_host"),
        "n_steps": len(traj.get("steps") or []),
        "step_statuses": statuses,
        "steps": steps_payload,
    }
    tmp = out_path.with_suffix(".json.gz.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(out_path)

    attempted = [s for s in statuses if s != "no_url"]
    ok = sum(1 for s in attempted if s == "ok")
    if not attempted:
        status = "no_url"
    elif ok == len(attempted):
        status = "ok"
    elif ok:
        status = "partial"
    else:
        status = "failed"
    return {
        "traj_id": traj_id,
        "status": status,
        "steps_ok": ok,
        "steps_total": len(statuses),
        "first_failure": next((s for s in attempted if s != "ok"), None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条轨迹（0=全部），用于 pilot")
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.subset).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "fetch_manifest.jsonl"

    results: list[dict] = []
    lock = threading.Lock()
    started = time.time()
    with httpx.Client(follow_redirects=True, headers={"User-Agent": "curl/8"}) as client:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futs = {
                pool.submit(process_trajectory, client, row, out_dir,
                            retries=args.retries, timeout=args.timeout): row
                for row in rows
            }
            for i, fut in enumerate(as_completed(futs), 1):
                row = futs[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001 - 单条异常不阻断整批
                    res = {"traj_id": row["trajectory"]["id"], "status": "error", "error": str(exc)}
                res["host"] = row["summary"].get("primary_host")
                with lock:
                    results.append(res)
                    with manifest_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                print(f"[{i}/{len(rows)}] {res['traj_id']} {res['status']} "
                      f"steps_ok={res.get('steps_ok')}/{res.get('steps_total')} "
                      f"elapsed={time.time()-started:.0f}s", file=sys.stderr)

    ok = sum(1 for r in results if r["status"] in {"ok", "partial", "skipped_existing"})
    print(f"\ndone: {ok}/{len(results)} usable in {time.time()-started:.0f}s -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
