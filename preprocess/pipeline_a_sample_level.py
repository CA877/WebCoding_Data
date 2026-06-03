#!/usr/bin/env python3
"""Sample-level Pipeline A preprocessing for WebRenderBench.

For each input project:
1. Try to expand it to multiple pages.
2. Always clean the original → single_page/{project}/ (1 sample).
3. If expansion succeeds, also clean expanded → multi_page/{project}/ (+1 sample).
4. Each sample gets JS features via LLM (default; disable with --no-js).

Output structure:
    output/
    ├── single_page/   # every project (1 sample each)
    ├── multi_page/    # only expand-success projects (1 extra sample each)
    └── sample_pipeline_results.jsonl

This keeps concurrency at the sample level instead of running all expand work
before all clean work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import queue
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from playwright_crawl import build_requests_session, clean_project, expand_project

# Add repo root to path so we can import from construct/
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Also add construct/ so fallback absolute imports (e.g. in add_js.py) work in subprocess workers
_CONSTRUCT_DIR = str(_REPO_ROOT / "construct")
if _CONSTRUCT_DIR not in sys.path:
    sys.path.insert(0, _CONSTRUCT_DIR)


def _copy_fresh(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _add_js_to_project(project_out: Path, add_js_config: dict) -> dict[str, Any]:
    """Add JS features to a cleaned project via LLM."""
    from construct.add_js import generate_js, select_features

    model = add_js_config["model"]
    seed = add_js_config.get("seed", 42)

    from openai import OpenAI
    import httpx
    client = OpenAI(
        api_key=add_js_config["api_key"],
        base_url=add_js_config.get("base_url"),
        timeout=40.0,
        http_client=httpx.Client(proxy=None),  # LLM API 直连，不走代理
    )

    features = select_features(project_out.name, seed=seed)
    js_content = generate_js(project_out, model, client, features)
    if not js_content:
        return {"status": "generation_failed", "features": features}

    (project_out / "main.js").write_text(js_content, encoding="utf-8")

    # Inject <script src="main.js"> into all HTML files
    for html_file in project_out.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        if '<script src="main.js">' not in html:
            if "</body>" in html:
                html = html.replace("</body>", '  <script src="main.js"></script>\n</body>')
            else:
                html += '\n<script src="main.js"></script>'
            html_file.write_text(html, encoding="utf-8")

    return {
        "status": "ok",
        "features": features,
        "js_lines": len(js_content.splitlines()),
    }


def _add_js_single(add_js_config: dict | None, result: dict[str, Any],
                    project_name: str, started: float) -> None:
    """Run add_js on the single output before expand, so timeout can't lose it."""
    if not add_js_config or not result["outputs"]:
        return

    ratio = add_js_config.get("ratio", 1.0)
    if ratio < 1.0:
        h = int(hashlib.md5(project_name.encode()).hexdigest(), 16) % 10000
        if h >= ratio * 10000:
            for o in result["outputs"]:
                if o.get("variant") == "single":
                    o["add_js_status"] = "skipped_by_ratio"
            return

    for output_info in result["outputs"]:
        if output_info.get("variant") != "single":
            continue
        out_path = Path(output_info["path"])
        if out_path.exists() and (out_path / "index.html").exists():
            try:
                js_result = _add_js_to_project(out_path, add_js_config)
                output_info["add_js_status"] = js_result["status"]
                output_info["add_js_features"] = js_result.get("features", [])
                output_info["add_js_lines"] = js_result.get("js_lines", 0)
            except Exception as exc:  # noqa: BLE001
                output_info["add_js_status"] = "error"
                result["errors"].append({
                    "stage": "add_js_single",
                    "error": f"{type(exc).__name__}: {exc}",
                })


def process_sample(payload: tuple[str, str, str, str, int, int],
                    add_js_config: dict | None = None,
                    no_expand: bool = False) -> dict[str, Any]:
    project_path, output_root, browser_proxy, requests_proxy, max_pages, wait_ms = payload
    project_dir = Path(project_path)
    output_dir = Path(output_root)
    single_root = output_dir / "single_page"
    multi_root = output_dir / "multi_page"
    expand_tmp_root = output_dir / "_expand_tmp"
    single_root.mkdir(parents=True, exist_ok=True)
    multi_root.mkdir(parents=True, exist_ok=True)
    expand_tmp_root.mkdir(parents=True, exist_ok=True)

    started = time.time()
    result: dict[str, Any] = {
        "project": project_dir.name,
        "status": "ok",
        "expand_status": None,
        "outputs": [],
        "errors": [],
    }

    session = build_requests_session(requests_proxy)

    # ============================================================
    # Step 1: Clean original → single_page sample (ALWAYS, no Playwright)
    # ============================================================
    single_out = single_root / project_dir.name
    try:
        _copy_fresh(project_dir, single_out)
        clean_result = clean_project(single_out, session)
        result["outputs"].append(
            {
                "variant": "single",
                "path": str(single_out),
                "clean_status": clean_result.get("status"),
                "remaining_remote_refs": clean_result.get("remaining_remote_refs"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(single_out, ignore_errors=True)
        result["errors"].append({"stage": "clean_single", "error": f"{type(exc).__name__}: {exc}"})

    # ============================================================
    # Step 1b: add_js on single NOW (before expand, so timeout doesn't lose it)
    # ============================================================
    _add_js_single(add_js_config, result, project_dir.name, started)

    # ============================================================
    # --no-expand: skip expand entirely, single-page is enough
    # ============================================================
    if no_expand:
        result["expand_status"] = "skipped"
        result["elapsed"] = round(time.time() - started, 1)
        return result

    # ============================================================
    # Step 2: Quick nav-link check + domain preflight → skip expand if dead
    # ============================================================
    index_html_path = project_dir / "index.html"
    nav_links: list[str] = []
    domain_alive = False
    if index_html_path.exists():
        try:
            html = index_html_path.read_text(encoding="utf-8", errors="replace")
            # Extract domain
            all_urls = re.findall(r'https?://([^/\s"\'<>]+)', html)
            noise = {"google", "facebook", "twitter", "cdn", "fonts.g", "jquery",
                     "bootstrap", "cloudflare", "gstatic", "w3.org", "schema.org",
                     "gravatar", "youtube", "vimeo", "instagram", "linkedin", "pinterest"}
            real_domains = [d for d in all_urls if not any(n in d.lower() for n in noise)]
            if real_domains:
                from collections import Counter as _Counter
                from playwright_crawl import extract_nav_links as _extract_nav_links
                main_domain = _Counter(real_domains).most_common(1)[0][0]
                base_url = f"https://{main_domain}/"
                # --- Preflight: quick HTTP check before expensive Playwright expand ---
                try:
                    r = session.get(base_url, timeout=(3, 5), allow_redirects=True)
                    domain_alive = r.status_code < 500
                except Exception:
                    domain_alive = False
                if domain_alive:
                    nav_links = _extract_nav_links(html, base_url, max_links=max_pages)
        except Exception:
            pass

    # ============================================================
    # Step 3: Try expand → multi_page sample (BONUS, only if links exist AND domain alive)
    # ============================================================
    if nav_links and domain_alive:
        expanded_project = expand_tmp_root / project_dir.name
        if expanded_project.exists():
            shutil.rmtree(expanded_project)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    proxy={"server": browser_proxy} if browser_proxy else None,
                )
                try:
                    expand_result = expand_project(
                        project_dir,
                        expand_tmp_root,
                        browser,
                        session,
                        max_pages=max_pages,
                        wait_ms=wait_ms,
                    )
                except Exception as exc:  # noqa: BLE001
                    expand_result = {
                        "status": "error",
                        "project": project_dir.name,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            expand_result = {
                "status": "error",
                "project": project_dir.name,
                "error": f"{type(exc).__name__}: {exc}",
            }

        result["expand_status"] = expand_result.get("status")
        result["expand_result"] = expand_result

        if expand_result.get("status") == "expanded" and expanded_project.exists():
            multi_out = multi_root / project_dir.name
            try:
                _copy_fresh(expanded_project, multi_out)
                clean_result = clean_project(multi_out, session)
                result["outputs"].append(
                    {
                        "variant": "multi",
                        "path": str(multi_out),
                        "clean_status": clean_result.get("status"),
                        "remaining_remote_refs": clean_result.get("remaining_remote_refs"),
                        "pages_added": expand_result.get("pages_added"),
                        "total_pages": expand_result.get("total_pages"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                shutil.rmtree(multi_out, ignore_errors=True)
                result["errors"].append({"stage": "clean_multi", "error": f"{type(exc).__name__}: {exc}"})

        shutil.rmtree(expanded_project, ignore_errors=True)
    elif not domain_alive:
        result["expand_status"] = "domain_dead"
        result["expand_result"] = {"status": "domain_dead", "project": project_dir.name}
    else:
        result["expand_status"] = "no_nav_links"
        result["expand_result"] = {"status": "no_nav_links", "project": project_dir.name}

    # --- add_js on multi output (single was already done before expand) ---
    if add_js_config and result["outputs"]:
        ratio = add_js_config.get("ratio", 1.0)
        if ratio < 1.0:
            h = int(hashlib.md5(project_dir.name.encode()).hexdigest(), 16) % 10000
            if h >= ratio * 10000:
                for output_info in result["outputs"]:
                    if output_info.get("add_js_status") is None:
                        output_info["add_js_status"] = "skipped_by_ratio"
                result["elapsed"] = round(time.time() - started, 1)
                return result

    if add_js_config and result["outputs"]:
        for output_info in result["outputs"]:
            if output_info.get("add_js_status") is not None:
                continue  # already processed (single was done before expand)
            out_path = Path(output_info["path"])
            if out_path.exists() and (out_path / "index.html").exists():
                try:
                    js_result = _add_js_to_project(out_path, add_js_config)
                    output_info["add_js_status"] = js_result["status"]
                    output_info["add_js_features"] = js_result.get("features", [])
                    output_info["add_js_lines"] = js_result.get("js_lines", 0)
                except Exception as exc:  # noqa: BLE001
                    output_info["add_js_status"] = "error"
                    result["errors"].append({
                        "stage": f"add_js_{output_info['variant']}",
                        "error": f"{type(exc).__name__}: {exc}",
                    })

    if result["errors"]:
        result["status"] = "partial" if result["outputs"] else "error"
    result["elapsed"] = round(time.time() - started, 1)
    return result


def process_sample_entry(payload: tuple[str, str, str, str, int, int], result_queue: mp.Queue,
                         add_js_config: dict | None = None, no_expand: bool = False) -> None:
    result_queue.put(process_sample(payload, add_js_config=add_js_config, no_expand=no_expand))


def timeout_result(payload: tuple[str, str, str, str, int, int], elapsed: float, site_timeout: int) -> dict[str, Any]:
    project = Path(payload[0]).name
    output_dir = Path(payload[1])
    # Check if single_page output was already written to disk before timeout
    outputs: list[dict[str, Any]] = []
    single_out = output_dir / "single_page" / project
    if (single_out / "index.html").exists():
        js_file = single_out / "main.js"
        add_js_info: dict[str, Any] = {}
        if js_file.exists():
            add_js_info = {
                "add_js_status": "ok",
                "add_js_lines": len(js_file.read_text(encoding="utf-8").splitlines()),
            }
        else:
            add_js_info = {"add_js_status": "skipped_by_ratio"}
        outputs.append({
            "variant": "single",
            "path": str(single_out),
            "clean_status": "recovered_after_timeout",
            "remaining_remote_refs": None,
            **add_js_info,
        })
    return {
        "project": project,
        "status": "site_timeout",
        "expand_status": "site_timeout",
        "outputs": outputs,
        "errors": [{"stage": "expand", "error": f"site_timeout after {site_timeout}s (single preserved)"}],
        "elapsed": round(elapsed, 1),
        "site_timeout": site_timeout,
    }


def cleanup_sample_outputs(payload: tuple[str, str, str, str, int, int]) -> None:
    project = Path(payload[0]).name
    output_dir = Path(payload[1])
    shutil.rmtree(output_dir / "_expand_tmp" / project, ignore_errors=True)
    shutil.rmtree(output_dir / "multi_page" / project, ignore_errors=True)
    # Note: do NOT delete single_page — it was saved before expand


def existing_outputs_for_project(project: str, output_dir: Path) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for variant, root_name in [("single", "single_page"), ("multi", "multi_page")]:
        out_path = output_dir / root_name / project
        if (out_path / "index.html").exists():
            outputs.append(
                {
                    "variant": variant,
                    "path": str(out_path),
                    "clean_status": "existing_output",
                    "remaining_remote_refs": None,
                }
            )
    return outputs


def load_done_projects(manifest: Path, output_dir: Path) -> set[str]:
    done_projects: set[str] = set()
    if not manifest.exists():
        return done_projects

    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        project = entry.get("project", "")
        if project and existing_outputs_for_project(project, output_dir):
            done_projects.add(project)
    return done_projects


def existing_pipeline_a_result(project: str, output_dir: Path) -> dict[str, Any] | None:
    outputs = existing_outputs_for_project(project, output_dir)
    if not outputs:
        return None
    return {
        "project": project,
        "status": "existing_output",
        "expand_status": "existing_output",
        "outputs": outputs,
        "errors": [],
        "elapsed": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sample-level WebRenderBench expand/clean preprocessing")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=7)
    parser.add_argument("--wait", type=int, default=3000)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--requests-proxy", default="")
    parser.add_argument(
        "--site-timeout",
        type=int,
        default=0,
        help="Hard wall-clock timeout per sample in seconds. When set, stuck workers are terminated.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-js", action="store_true",
                        help="Skip JS feature generation (default: add JS via LLM)")
    parser.add_argument("--js-model", default=None,
                        help="Override LLM model for JS generation (default: from env)")
    parser.add_argument("--js-seed", type=int, default=42,
                        help="Seed for JS feature selection")
    parser.add_argument("--js-ratio", type=float, default=1.0,
                        help="Fraction of projects to add JS (0.0-1.0, default: 1.0 = all)")
    parser.add_argument("--no-expand", action="store_true",
                        help="Skip expand step, only produce single-page samples")
    parser.add_argument("--fast-clean", action="store_true",
                        help="Skip image downloads during clean, only download CSS/JS")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    single_root = args.output_dir / "single_page"
    multi_root = args.output_dir / "multi_page"
    if args.overwrite:
        shutil.rmtree(single_root, ignore_errors=True)
        shutil.rmtree(multi_root, ignore_errors=True)
        shutil.rmtree(args.output_dir / "_expand_tmp", ignore_errors=True)
    single_root.mkdir(parents=True, exist_ok=True)
    multi_root.mkdir(parents=True, exist_ok=True)

    # --- add-js config (enabled by default) ---
    add_js_config = None
    if not args.no_js:
        from construct.construct_common import ensure_api_env, maybe_load_env
        maybe_load_env()
        api_key, base_url, env_model = ensure_api_env()
        add_js_config = {
            "api_key": api_key,
            "base_url": base_url,
            "model": args.js_model or env_model,
            "seed": args.js_seed,
            "ratio": args.js_ratio,
        }
        print(f"Add-JS enabled: model={add_js_config['model']}, ratio={args.js_ratio}")

    projects = sorted(d for d in args.input_dir.iterdir() if d.is_dir() and (d / "index.html").exists())
    if args.limit:
        projects = projects[: args.limit]

    manifest = args.output_dir / "sample_pipeline_results.jsonl"
    done_projects: set[str] = set()
    if args.overwrite:
        manifest.write_text("", encoding="utf-8")
    else:
        if not manifest.exists():
            manifest.write_text("", encoding="utf-8")
        done_projects = load_done_projects(manifest, args.output_dir)
        recovered = []
        for project in projects:
            if project.name in done_projects:
                continue
            result = existing_pipeline_a_result(project.name, args.output_dir)
            if result is not None:
                recovered.append(result)
                done_projects.add(project.name)
        if recovered:
            with manifest.open("a", encoding="utf-8") as f:
                for result in recovered:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"Recovered {len(recovered)} existing Pipeline A projects into manifest", flush=True)
        if done_projects:
            print(f"Resuming: {len(done_projects)} projects already processed, skipping", flush=True)

    payloads = [
        (
            str(project),
            str(args.output_dir),
            args.browser_proxy or "",
            args.requests_proxy or "",
            args.max_pages,
            args.wait,
        )
        for project in projects
        if project.name not in done_projects
    ]

    total_inputs = len(projects)
    initial_done = len(done_projects)
    print(
        f"Processing {len(payloads)} samples with concurrency={args.concurrency}"
        f"{' (with add-js)' if add_js_config else ' (no-js)'}; "
        f"resume_done={initial_done}, total_inputs={total_inputs}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    progress_statuses: Counter[str] = Counter({"resumed": initial_done})
    sample_count = initial_done  # single-page samples always produced; multi-page count as extra
    failed_count = 0

    def record_result(i: int, result: dict[str, Any]) -> None:
        nonlocal sample_count, failed_count
        results.append(result)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        status = result.get("status", "?")
        progress_statuses[status] += 1
        outputs_count = len(result.get("outputs", []))
        if outputs_count > 0:
            sample_count += outputs_count  # single=1, single+multi=2
        else:
            failed_count += 1
        overall_done = initial_done + i
        success_rate = sample_count / (sample_count + failed_count) if (sample_count + failed_count) else 0.0
        print(
            f"[{i}/{len(payloads)}] {result['project']}: {result['status']} "
            f"(expand={result.get('expand_status')}, samples={outputs_count}, "
            f"{result.get('elapsed', 0)}s) "
            f"progress={overall_done}/{total_inputs} samples={sample_count} "
            f"failed={failed_count} success_rate={success_rate:.2%} "
            f"statuses={dict(progress_statuses)}",
            flush=True,
        )

    if args.site_timeout and args.site_timeout > 0:
        ctx = mp.get_context()
        pending = list(payloads)
        active: dict[mp.Process, tuple[tuple[str, str, str, str, int, int], float, mp.Queue]] = {}
        completed = 0

        def start_next() -> None:
            payload = pending.pop(0)
            result_queue = ctx.Queue(maxsize=1)
            proc = ctx.Process(target=process_sample_entry, args=(payload, result_queue, add_js_config, args.no_expand))
            proc.start()
            active[proc] = (payload, time.time(), result_queue)

        while pending or active:
            while pending and len(active) < args.concurrency:
                start_next()

            for proc, (payload, started, result_queue) in list(active.items()):
                try:
                    result = result_queue.get_nowait()
                except queue.Empty:
                    result = None

                if result is not None:
                    proc.join(timeout=2)
                    active.pop(proc, None)
                    completed += 1
                    record_result(completed, result)
                    continue

                elapsed = time.time() - started
                if elapsed > args.site_timeout:
                    proc.terminate()
                    proc.join(timeout=5)
                    if proc.is_alive():
                        proc.kill()
                        proc.join(timeout=5)
                    cleanup_sample_outputs(payload)
                    active.pop(proc, None)
                    completed += 1
                    record_result(completed, timeout_result(payload, elapsed, args.site_timeout))
                elif not proc.is_alive():
                    proc.join(timeout=2)
                    active.pop(proc, None)
                    completed += 1
                    # Check if single_page was already saved before worker crashed
                    _proj = Path(payload[0]).name
                    _out_dir = Path(payload[1])
                    _outputs: list[dict[str, Any]] = []
                    _single_out = _out_dir / "single_page" / _proj
                    if (_single_out / "index.html").exists():
                        _outputs.append({
                            "variant": "single",
                            "path": str(_single_out),
                            "clean_status": "recovered_after_crash",
                            "remaining_remote_refs": None,
                        })
                    result = {
                        "project": _proj,
                        "status": "worker_exited",
                        "expand_status": "worker_exited",
                        "outputs": _outputs,
                        "errors": [{"stage": "expand", "error": "worker exited without result (single preserved)"}],
                        "elapsed": round(elapsed, 1),
                    }
                    record_result(completed, result)

            time.sleep(0.5)
    else:
        with ProcessPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(process_sample, payload, add_js_config, args.no_expand): payload for payload in payloads}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result(timeout=600 if add_js_config else 300)
                except TimeoutError:
                    result = {
                        "project": Path(futures[future][0]).name,
                        "status": "future_timeout",
                        "outputs": [],
                        "errors": [{"stage": "sample", "error": "future.result() timeout after 300s"}],
                    }
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "project": Path(futures[future][0]).name,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "outputs": [],
                    }
                record_result(i, result)

    statuses = Counter(r.get("status", "?") for r in results)
    expand_statuses = Counter(r.get("expand_status", "?") for r in results)
    total_outputs = sum(len(r.get("outputs", [])) for r in results)
    single_count = sum(1 for r in results for o in r.get("outputs", []) if o.get("variant") == "single")
    multi_count = sum(1 for r in results for o in r.get("outputs", []) if o.get("variant") == "multi")
    print(f"Done: statuses={dict(statuses)}, expand={dict(expand_statuses)}, "
          f"total_samples={total_outputs} (single={single_count}, multi={multi_count})", flush=True)


if __name__ == "__main__":
    main()
