#!/usr/bin/env python3
"""Audit legacy Pipeline-B sites and optionally purge rejected whole sites.

The unit of retention is a site directory.  Every top-level HTML page must pass
the static content policy and have a healthy matching screenshot; one rejected
page rejects the entire site.  Audit output is written before any deletion.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from preprocess.pipeline_c.policy import assess_html


MIN_HTML_BYTES = 500
MIN_VISIBLE_TEXT = 40
MIN_SCREENSHOT_BYTES = 2_048
MIN_SCREENSHOT_WIDTH = 320
MIN_SCREENSHOT_HEIGHT = 180
STRONG_UNAVAILABLE_MARKERS = (
    "account has been suspended", "domain is for sale", "buy this domain",
    "domain has expired", "the domain has expired", "parked domain",
    "welcome to nginx", "apache2 default page", "expired domain",
    "site not found", "service has ended", "service is no longer available",
    "upload your website files", "this domain may be for sale",
    "there has been a critical error on this website",
    "verify you are human", "checking your browser", "robot challenge",
    "cf-challenge",
)


def strong_adult_content(html: str) -> bool:
    """Avoid treating policy/legal/safety prose or placeholder Xs as adult pages."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True).lower()
    adult_text = text.replace("child pornography", "")
    explicit_phrases = (
        "porn video", "amateur porn", "gay porn", "porn discount",
        "porn offer", "porn archive", "watch porn", "sex cam",
        "adult video", "escort service", "性爱", "色情", "裸体",
    )
    contextual_markers = (
        "except files with", "forgiveness guilt/shame", "combat child",
        "prohibited content", "content is prohibited", "terms of service",
    )
    repeated_porn = adult_text.count("porn") >= 2 and not any(
        marker in adult_text for marker in contextual_markers
    )
    return repeated_porn or any(phrase in adult_text for phrase in explicit_phrases)


def strong_gambling_content(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text(" ", strip=True).lower()
    if "do not provide links" in text and "sports betting" in text:
        return False
    markers = ("online casino", "sports betting", "slot machine", "赌博", "博彩")
    return sum(text.count(marker) for marker in markers) >= 2


def screenshot_for(page: Path) -> Path:
    return page.parent / ("screenshot.png" if page.name == "index.html" else f"{page.stem}_screenshot.png")


def inspect_screenshot(path: Path, text_chars: int) -> list[str]:
    if not path.is_file():
        return ["missing_screenshot"]
    if path.stat().st_size < MIN_SCREENSHOT_BYTES:
        return ["tiny_screenshot_file"]
    try:
        # Full-page captures can legitimately exceed Pillow's decompression
        # bomb threshold.  Read only their header and skip pixel statistics;
        # decoding a 200M-pixel page would waste memory without improving the
        # blank-page decision.
        old_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as image:
            width, height = image.size
        Image.MAX_IMAGE_PIXELS = old_limit
        if width < MIN_SCREENSHOT_WIDTH or height < MIN_SCREENSHOT_HEIGHT:
            return [f"tiny_screenshot_dimensions:{width}x{height}"]
        if width * height > 50_000_000:
            return []
        with Image.open(path) as image:
            thumb = image.convert("L")
            thumb.thumbnail((256, 256))
            stat = ImageStat.Stat(thumb)
            stddev = float(stat.stddev[0]) if stat.stddev else 0.0
            # Near-uniform captures paired with almost no visible text are
            # blank/error shells, not minimalist pages.
            if math.isfinite(stddev) and stddev < 2.0 and text_chars < 120:
                return [f"near_blank_screenshot:std={stddev:.2f}"]
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return [f"invalid_screenshot:{type(exc).__name__}"]
    return []


def inspect_page(page: Path) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    try:
        raw = page.read_bytes()
        html = raw.decode("utf-8", errors="replace")
    except OSError as exc:
        return {"page": page.name, "reasons": [f"read_error:{type(exc).__name__}"]}
    if len(raw) < MIN_HTML_BYTES:
        reasons.append(f"tiny_html:{len(raw)}")
    assessment = assess_html(html)
    lowered = html.lower()
    for reason in assessment.reasons:
        if reason == "unsupported_language":
            # Language is a downstream dataset-selection dimension, not a
            # quality or safety failure.  Do not destroy healthy foreign sites.
            warnings.append(reason)
            continue
        if reason == "link_farm_or_directory_page":
            # Link density alone also catches galleries, recipe indexes,
            # schools, and government sites.  Preserve it for later visual
            # review, but never use it as an irreversible deletion gate.
            warnings.append(reason)
            continue
        if reason == "unsafe_content:adult" and not strong_adult_content(html):
            warnings.append("contextual_adult_term")
            continue
        if reason == "unsafe_content:gambling" and not strong_gambling_content(html):
            warnings.append("contextual_gambling_term")
            continue
        if reason == "unsafe_content:drugs" and "illegal drugs" in lowered and not any(
            marker in lowered for marker in ("buy cocaine", "buy heroin", "购买毒品")
        ):
            warnings.append("contextual_drug_term")
            continue
        if reason == "unavailable_or_challenge_page" and not any(
            marker in lowered for marker in STRONG_UNAVAILABLE_MARKERS
        ):
            # Phrases such as "access denied" are normal vocabulary on IAM
            # product pages.  Keep them for review instead of deleting a
            # substantial, healthy-looking site on a context-free match.
            continue
        reasons.append(reason)
    if assessment.text_chars < MIN_VISIBLE_TEXT:
        reasons.append(f"insufficient_visible_text:{assessment.text_chars}")
    screenshot = screenshot_for(page)
    reasons.extend(inspect_screenshot(screenshot, assessment.text_chars))
    return {
        "page": page.name,
        "html_bytes": len(raw),
        "text_chars": assessment.text_chars,
        "language": assessment.language,
        "screenshot": screenshot.name,
        "reasons": sorted(set(reasons)),
        "warnings": sorted(set(warnings)),
    }


def inspect_site(site: Path) -> dict:
    pages = sorted([*site.glob("*.html"), *site.glob("*.htm")])
    if not pages:
        return {"site": site.name, "path": str(site), "status": "reject", "reasons": ["no_html_pages"], "pages": []}
    page_results = [inspect_page(page) for page in pages]
    failed = [item for item in page_results if item["reasons"]]
    reasons = Counter(reason.split(":", 1)[0] for item in failed for reason in item["reasons"])
    warnings = Counter(
        warning.split(":", 1)[0] for item in page_results for warning in item.get("warnings", [])
    )
    return {
        "site": site.name,
        "path": str(site),
        "status": "reject" if failed else "pass",
        "page_count": len(page_results),
        "failed_page_count": len(failed),
        "reasons": dict(reasons),
        "warnings": dict(warnings),
        "failed_pages": failed,
    }


def load_sites(root: Path, offset: int, limit: int) -> list[Path]:
    sites = sorted(path for path in root.iterdir() if path.is_dir())
    sites = sites[offset:]
    return sites[:limit] if limit else sites


def apply_audit(root: Path, audit_path: Path, deletion_log: Path) -> dict:
    root = root.resolve()
    rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    current_sites = {path.name for path in root.iterdir() if path.is_dir()}
    audited_sites = [str(row.get("site", "")) for row in rows]
    if len(audited_sites) != len(set(audited_sites)):
        raise ValueError("audit contains duplicate site rows")
    if set(audited_sites) != current_sites:
        missing = sorted(current_sites - set(audited_sites))[:10]
        stale = sorted(set(audited_sites) - current_sites)[:10]
        raise ValueError(f"audit/site mismatch: unaudited={missing}, missing_on_disk={stale}")
    rejected = [row for row in rows if row.get("status") == "reject"]
    deletion_log.parent.mkdir(parents=True, exist_ok=True)
    reclaimed = 0
    with deletion_log.open("w", encoding="utf-8") as handle:
        for row in rejected:
            site = (root / row["site"]).resolve()
            if site.parent != root or not site.is_dir():
                raise ValueError(f"unsafe or missing deletion path: {site}")
            size = sum(path.stat().st_size for path in site.rglob("*") if path.is_file())
            record = {"site": row["site"], "path": str(site), "bytes": size,
                      "reasons": row.get("reasons", {})}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            shutil.rmtree(site)
            reclaimed += size
    return {"audited": len(rows), "deleted": len(rejected), "reclaimed_bytes": reclaimed,
            "remaining": len(rows) - len(rejected), "deletion_log": str(deletion_log)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--purge", action="store_true", help="Delete rejected site directories after writing their audit row.")
    parser.add_argument("--apply-audit", type=Path,
                        help="Apply a previously completed full audit instead of rescanning.")
    parser.add_argument("--deletion-log", type=Path,
                        help="Required with --apply-audit; written before each site deletion.")
    args = parser.parse_args()
    if args.apply_audit:
        if not args.deletion_log:
            parser.error("--deletion-log is required with --apply-audit")
        print(json.dumps(apply_audit(args.root, args.apply_audit, args.deletion_log), ensure_ascii=False))
        return
    sites = load_sites(args.root, args.offset, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    reclaimed = 0
    with args.output.open("w", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for number, result in enumerate(pool.map(inspect_site, sites, chunksize=8), 1):
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                handle.flush()
                counts[result["status"]] += 1
                reason_counts.update(result.get("reasons", {}))
                if args.purge and result["status"] == "reject":
                    site = Path(result["path"])
                    reclaimed += sum(path.stat().st_size for path in site.rglob("*") if path.is_file())
                    shutil.rmtree(site)
                if number % 100 == 0 or number == len(sites):
                    print(f"[{number}/{len(sites)}] {dict(counts)}", flush=True)
    print(json.dumps({"sites": len(sites), "counts": counts, "reasons": reason_counts,
                      "purge": args.purge, "reclaimed_bytes": reclaimed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
