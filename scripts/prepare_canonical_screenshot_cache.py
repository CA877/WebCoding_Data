#!/usr/bin/env python3
"""Render one reusable canonical clean screenshot pack per selected mother."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.construct_common import (
    TRAIN_CODE_EXTS,
    discover_browser_routes,
    screenshot_project_to_dir,
)


CANONICAL_QUALITY_GATE_VERSION = "canonical-route-quality-v6"
MIN_ROUTE_CHANGED_RATIO = 0.002


class CanonicalQualityError(RuntimeError):
    """A deterministic project/screenshot rejection that retries cannot fix."""


def _pixels(image: Image.Image):
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


def _tree_digest(project: Path, *, code: bool) -> str:
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.name == ".generation.json":
            continue
        is_code = path.suffix.lower() in TRAIN_CODE_EXTS
        if is_code != code:
            continue
        digest.update(path.relative_to(project).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def project_paths(path: Path) -> list[Path]:
    rows: list[Path] = []
    seen: set[Path] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value:
            continue
        project = Path(value).resolve()
        if not project.is_dir():
            raise FileNotFoundError(project)
        if project not in seen:
            rows.append(project)
            seen.add(project)
    return rows


def completed_ids(ledger: Path) -> set[str]:
    latest: dict[str, dict[str, Any]] = {}
    if not ledger.is_file():
        return set()
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        instance_id = str(row.get("instance_id") or "")
        if instance_id:
            latest[instance_id] = row
    return {
        instance_id for instance_id, row in latest.items()
        if (
            row.get("status") in {"ok", "rejected"}
            or str(row.get("error", "")).startswith(
                "RuntimeError: canonical_quality_failed:"
            )
        )
        and row.get("quality_gate_version") == CANONICAL_QUALITY_GATE_VERSION
    }


def _changed_ratio(left: Image.Image, right: Image.Image, threshold: int = 8) -> float:
    """Compare full-page images on a shared white canvas."""
    a = left.convert("RGB")
    b = right.convert("RGB")
    width, height = max(a.width, b.width), max(a.height, b.height)
    if a.size != (width, height):
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(a, (0, 0)); a = canvas
    if b.size != (width, height):
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(b, (0, 0)); b = canvas
    diff = ImageChops.difference(a, b)
    red, green, blue = diff.split()
    max_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    histogram = max_channel.histogram()
    changed = sum(histogram[threshold:])
    return changed / max(width * height, 1)


def _direct_route_was_preserved(expected_route: str, final_url: str) -> bool:
    """Require a directly opened document/hash route to remain addressable."""
    expected_path, _, expected_fragment = expected_route.partition("#")
    expected_path = unquote(expected_path.split("?", 1)[0].lstrip("/"))
    parsed = urlparse(final_url)
    final_path = unquote(parsed.path.lstrip("/"))
    if final_path != expected_path:
        return False
    if expected_fragment:
        return parsed.fragment.strip("/") == expected_fragment.strip("/")
    return True


def validate_canonical_pack(
    screens: list[dict[str, Any]], expected_routes: list[str]
) -> dict[str, Any]:
    """Decode screenshots and fail closed when multi-route states collapse.

    Low visual entropy is retained as a warning because sparse designs can be
    valid.  Route/manifest mismatch, undecodable images, duplicate route names,
    identical DOM states, or an effectively identical multipage pack are hard
    failures.
    """
    errors: list[str] = []
    warnings: list[str] = []
    actual_routes = [str(item.get("page") or "") for item in screens]
    if len(actual_routes) != len(set(actual_routes)):
        errors.append("duplicate_route_entries")
    if set(actual_routes) != set(expected_routes) or len(actual_routes) != len(expected_routes):
        errors.append("route_manifest_mismatch")
    for item in screens:
        page_name = str(item.get("page") or "")
        final_url = str(item.get("final_url") or "")
        if final_url and not _direct_route_was_preserved(page_name, final_url):
            errors.append(f"direct_route_redirected:{page_name}")
        if item.get("page_errors"):
            errors.append(f"page_runtime_error:{page_name}")
        if item.get("console_errors"):
            errors.append(f"console_error:{page_name}")
        if item.get("failed_requests"):
            errors.append(f"failed_request:{page_name}")
        if item.get("bad_responses"):
            errors.append(f"bad_http_response:{page_name}")
        if item.get("unsettled_loading_texts"):
            errors.append(f"unsettled_loading_state:{page_name}")
        if item.get("visible_hidden_elements"):
            errors.append(f"hidden_element_visible:{page_name}")
        if item.get("initial_hard_failure_texts"):
            errors.append(f"initial_route_failure:{page_name}")
        if item.get("initial_empty_state_texts"):
            warnings.append(f"initial_empty_or_error_state:{page_name}")
        for dialog in item.get("visible_dialogs") or []:
            text = str(dialog.get("text") or "").strip()
            if not text or text in {"×", "x", "X"}:
                errors.append(f"empty_visible_dialog:{page_name}")
            else:
                warnings.append(f"initial_visible_dialog:{page_name}")

    decoded: list[Image.Image] = []
    metrics: list[dict[str, Any]] = []
    hashes: list[str] = []
    try:
        for item in screens:
            path = Path(str(item.get("path") or ""))
            try:
                raw = Image.open(path)
                raw.load()
                image = raw.convert("RGB")
            except (OSError, UnidentifiedImageError):
                errors.append(f"undecodable_image:{item.get('page', '')}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes.append(digest)
            preview = image.copy()
            preview.thumbnail((320, 320))
            gray = preview.convert("L")
            entropy = float(gray.entropy())
            pixels = list(_pixels(gray))
            near_white = sum(value >= 248 for value in pixels) / max(len(pixels), 1)
            if entropy < 1.0 and near_white >= 0.85:
                warnings.append(f"low_information_image:{item.get('page', '')}")
            metrics.append({
                "page": item.get("page"), "sha256": digest,
                "width": image.width, "height": image.height,
                "entropy": round(entropy, 4), "near_white_ratio": round(near_white, 6),
            })
            decoded.append(image)

        distinct_indexes: list[int] = []
        max_changed_ratio = 0.0
        for index, image in enumerate(decoded):
            is_new_state = True
            for representative in distinct_indexes:
                ratio = _changed_ratio(image, decoded[representative])
                max_changed_ratio = max(max_changed_ratio, ratio)
                if ratio < MIN_ROUTE_CHANGED_RATIO:
                    is_new_state = False
                    break
            if is_new_state:
                distinct_indexes.append(index)

        multipage = len(expected_routes) >= 2
        if multipage and len(hashes) == len(expected_routes):
            if len(set(hashes)) == 1:
                errors.append("all_routes_visually_identical")
            elif len(distinct_indexes) < 2:
                errors.append("route_states_not_visually_distinct")
            dom_hashes = [str(item.get("dom_sha256") or "") for item in screens]
            if (
                len(distinct_indexes) < 2
                and all(dom_hashes)
                and len(set(dom_hashes)) == 1
            ):
                errors.append("all_routes_dom_identical")
        return {
            "status": "error" if errors else "ok",
            "quality_gate_version": CANONICAL_QUALITY_GATE_VERSION,
            "errors": sorted(set(errors)), "warnings": warnings,
            "route_count": len(expected_routes),
            "distinct_visual_states": len(distinct_indexes),
            "max_changed_ratio": round(max_changed_ratio, 6),
            "screens": metrics,
        }
    finally:
        for image in decoded:
            image.close()


def _reuse_screens(
    project: Path, reuse_root: Path | None, staging: Path
) -> tuple[list[dict[str, Any]], str] | None:
    """Hard-link a previously rendered pack only when v2 revalidation passes."""
    if reuse_root is None:
        return None
    source_manifest = reuse_root / project.name / "screens.json"
    if not source_manifest.is_file():
        return None
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_screens = payload.get("screens") if isinstance(payload, dict) else None
    if not isinstance(source_screens, list) or not source_screens:
        return None
    if payload.get("code_sha256") != _tree_digest(project, code=True):
        return None
    if payload.get("resource_manifest_sha256") != _tree_digest(project, code=False):
        return None
    resolved: list[dict[str, Any]] = []
    for item in source_screens:
        source = Path(str(item.get("path") or ""))
        if not source.is_absolute():
            source = reuse_root / source
        if not source.is_file():
            return None
        resolved.append({**item, "path": str(source)})
    quality = validate_canonical_pack(resolved, discover_browser_routes(project))
    if quality["status"] != "ok":
        return None
    reused: list[dict[str, Any]] = []
    for item in resolved:
        source = Path(str(item["path"]))
        destination = staging / source.name
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        reused.append({**item, "path": str(destination)})
    return reused, str(source_manifest)


def capture_one(
    project: Path, cache_root: Path, browser_proxy: str,
    reuse_cache_root: Path | None = None,
) -> dict[str, Any]:
    instance_id = project.name
    final_dir = cache_root / instance_id
    manifest = final_dir / "screens.json"
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("quality_gate_version") == CANONICAL_QUALITY_GATE_VERSION:
            return {
                "instance_id": instance_id, "status": "ok", "resume": True,
                "quality_gate_version": CANONICAL_QUALITY_GATE_VERSION,
            }
        raise RuntimeError(f"canonical_cache_requires_new_version:{final_dir}")
    if final_dir.exists():
        raise FileExistsError(f"refusing to replace incomplete canonical cache: {final_dir}")
    staging_root = cache_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{instance_id}.", dir=staging_root))
    try:
        reused = _reuse_screens(project, reuse_cache_root, staging)
        if reused is None:
            raw = screenshot_project_to_dir(
                project, staging, browser_proxy,
                viewports=[("desktop", 1920, 1080)], full_page=True,
            )
            reused_from = ""
        else:
            raw, reused_from = reused
        expected_routes = discover_browser_routes(project)
        quality_input = [
            {**item, "path": str(staging / Path(str(item["path"])).name)}
            for item in raw
        ]
        quality = validate_canonical_pack(quality_input, expected_routes)
        if quality["status"] != "ok":
            raise CanonicalQualityError(
                "canonical_quality_failed:" + ",".join(quality["errors"])
            )
        screens = []
        for item in raw:
            source = staging / Path(str(item["path"])).name
            with Image.open(source) as image:
                width, height = image.size
            screens.append({
                **item,
                "path": f"{instance_id}/{source.name}",
                "state": "canonical_clean",
                "full_page": True,
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            })
        (staging / "screens.json").write_text(
            json.dumps({
                "status": "ok", "instance_id": instance_id,
                "quality_gate_version": CANONICAL_QUALITY_GATE_VERSION,
                "source_project": str(project),
                "code_sha256": _tree_digest(project, code=True),
                "resource_manifest_sha256": _tree_digest(project, code=False),
                "routes": expected_routes,
                "quality": quality,
                "reused_from": reused_from or None,
                "screens": screens,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, final_dir)
        return {
            "instance_id": instance_id, "status": "ok", "resume": False,
            "screen_count": len(screens),
            "quality_gate_version": CANONICAL_QUALITY_GATE_VERSION,
            "cache_mode": "hardlink_reuse" if reused_from else "rendered",
            "quality": quality,
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-list", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument(
        "--reuse-cache-root", type=Path,
        help="Hard-link packs from an older cache only after current route/visual validation",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be in 1..32")
    args.cache_root.mkdir(parents=True, exist_ok=True)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    done = completed_ids(args.ledger)
    projects = [p for p in project_paths(args.project_list) if p.name not in done]
    if args.limit:
        projects = projects[:args.limit]
    lock = threading.Lock()
    with args.ledger.open("a", encoding="utf-8") as ledger, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                capture_one, project, args.cache_root, args.browser_proxy,
                args.reuse_cache_root,
            ): project
            for project in projects
        }
        for index, future in enumerate(as_completed(futures), 1):
            project = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                rejected = isinstance(exc, CanonicalQualityError)
                row = {
                    "instance_id": project.name,
                    "status": "rejected" if rejected else "error",
                    "quality_gate_version": CANONICAL_QUALITY_GATE_VERSION,
                    "error_type": (
                        "quality_rejected" if rejected else
                        "timeout" if "timeout" in str(exc).lower() else "render_error"
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            with lock:
                ledger.write(json.dumps(row, ensure_ascii=False) + "\n")
                ledger.flush()
            print(f"[{index}/{len(projects)}] {project.name}: {row['status']}", flush=True)


if __name__ == "__main__":
    main()
