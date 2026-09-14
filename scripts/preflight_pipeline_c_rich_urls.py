#!/usr/bin/env python3
"""Live HTTP preflight and structural-diversity selection for Pipeline C."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import threading
import time
import urllib.robotparser
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}
CHALLENGE_RE = re.compile(
    r"verify you are human|checking your browser|just a moment|cf-challenge|"
    r"turnstile|hcaptcha|recaptcha|captcha|access denied|enable javascript and cookies", re.I
)
PARKED_RE = re.compile(
    r"domain (?:is )?for sale|buy this domain|domain parking|sedo|afternic|hugedomains|"
    r"website coming soon|under construction|account suspended|index of /", re.I
)
UNSAFE_COMPOUND_RE = re.compile(
    r"porn|sexy|escort|casino|gambl|slots?|mailorderbride|brides?|"
    r"dating|hookup|camgirl|nude|erotic|girlsof|duelbits|sportsbook|poker|"
    r"jackpot|bingo|modapk|apkmod|payday|cashnow|torrent|warez|requestcrack|"
    r"(?:^|[.-])jav|hentai|missav|xnxx|xvideos|xhamster|pornhub|redtube|"
    r"tube8|spankbang|erome|onlyfans|chaturbate|brazzers|rule34|nhentai|"
    r"hanime|fapello|bet365|stake\.com|1xbet|draftkings|fanduel|toto\d|"
    r"satta|matka|orgasm", re.I
)
UNSAFE_CONTENT_RE = re.compile(
    r"online casino|casino games|sports betting|sportsbook|slot games|"
    r"adult videos?|free porn|live sex|satta matka|matka result|"
    r"betting odds|real money gambling",
    re.I,
)
RICH_CLASS_RE = re.compile(
    r"(?:^|[-_ ])(hero|card|carousel|slider|gallery|modal|dialog|tabs?|accordion|"
    r"dropdown|menu|navbar|sidebar|breadcrumb|pagination|toast|tooltip|popover|"
    r"timeline|pricing|testimonial|feature|portfolio|product)(?:$|[-_ ])", re.I
)


class Thresholds:
    def __init__(self, max_bytes: int = 786_432, min_html_bytes: int = 4_000,
                 min_text_chars: int = 250, min_component_types: int = 3,
                 min_richness_score: float = 7.0) -> None:
        self.max_bytes = max_bytes
        self.min_html_bytes = min_html_bytes
        self.min_text_chars = min_text_chars
        self.min_component_types = min_component_types
        self.min_richness_score = min_richness_score

    def as_dict(self) -> dict:
        return dict(vars(self))


def visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)


def component_metrics(html: str, final_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text_chars = len(visible_text(BeautifulSoup(html, "html.parser")))
    selectors = {
        "navigation": "nav, [role=navigation]",
        "forms": "form",
        "controls": "button, input, select, textarea, [role=button], [role=checkbox], [role=radio], [role=switch]",
        "disclosure": "details, summary, [aria-expanded]",
        "dialog": "dialog, [role=dialog]",
        "tabs": "[role=tab], [role=tablist]",
        "tables": "table, [role=grid]",
        "media": "img, picture, video, audio, canvas, svg",
        "content_sections": "main, section, article",
        "lists": "ul, ol, dl",
    }
    counts = {name: len(soup.select(selector)) for name, selector in selectors.items()}
    rich_classes = set()
    for tag in soup.find_all(class_=True):
        for value in tag.get("class", []):
            match = RICH_CLASS_RE.search(str(value))
            if match:
                rich_classes.add(match.group(1).lower())
    script_count = len(soup.find_all("script"))
    stylesheet_count = len(soup.select('link[rel~="stylesheet"]'))
    interactive = counts["controls"] + counts["disclosure"] + counts["dialog"] + counts["tabs"]
    component_types = sorted(name for name, count in counts.items() if count)
    if rich_classes:
        component_types.append("named_ui_patterns")
    image_count = len(soup.find_all("img")) + len(soup.find_all("picture"))
    same_site_links = 0
    root_host = urlsplit(final_url).hostname
    for anchor in soup.find_all("a", href=True):
        target = urlsplit(anchor["href"])
        if not target.hostname or target.hostname == root_host:
            same_site_links += 1
    score = (
        min(len(component_types), 8) * 1.4
        + min(interactive, 12) * 0.45
        + min(len(rich_classes), 8) * 0.8
        + min(image_count, 12) * 0.18
        + min(script_count, 10) * 0.12
        + (1.0 if counts["content_sections"] >= 3 else 0.0)
        + (0.8 if same_site_links >= 5 else 0.0)
    )
    if text_chars > 80_000 or len(html.encode("utf-8")) > 650_000:
        score -= 2.0
    return {
        "text_chars": text_chars,
        "component_counts": counts,
        "component_types": component_types,
        "named_ui_patterns": sorted(rich_classes),
        "interactive_control_count": interactive,
        "image_count": image_count,
        "script_tag_count": script_count,
        "stylesheet_link_count": stylesheet_count,
        "same_site_link_count": same_site_links,
        "richness_score": round(score, 3),
    }


def structural_archetype(metrics: dict) -> str:
    counts = metrics["component_counts"]
    patterns = set(metrics["named_ui_patterns"])
    if counts["forms"] and metrics["interactive_control_count"] >= 4:
        return "form_or_tool"
    if counts["tables"]:
        return "data_or_table"
    if metrics["image_count"] >= 8 or patterns & {"gallery", "portfolio", "product", "carousel", "slider"}:
        return "visual_gallery"
    if metrics["interactive_control_count"] >= 3 or patterns & {"tabs", "accordion", "dropdown", "modal"}:
        return "interactive_ui"
    if counts["content_sections"] >= 3 and counts["navigation"]:
        return "sectioned_landing"
    return "structured_content"


def policy_safe_url(url: str) -> bool:
    """Reject high-confidence adult/gambling/spam compounds in hostnames."""
    return not UNSAFE_COMPOUND_RE.search(urlsplit(url).hostname or "")


def fetch_limited(response: httpx.Response, max_bytes: int, max_seconds: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + max_seconds
    for chunk in response.iter_bytes(32_768):
        if time.monotonic() > deadline:
            raise httpx.ReadTimeout("response body exceeded total preflight deadline", request=response.request)
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += len(chunks[-1])
    return b"".join(chunks)


_CLIENT_LOCAL = threading.local()


def http_client(proxy: str, timeout: float) -> httpx.Client:
    key = (proxy, timeout)
    client = getattr(_CLIENT_LOCAL, "client", None)
    if client is None or getattr(_CLIENT_LOCAL, "key", None) != key:
        if client is not None:
            client.close()
        client = httpx.Client(
            headers=HEADERS, proxy=proxy or None, follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 8)),
            verify=False, trust_env=not bool(proxy),
        )
        _CLIENT_LOCAL.client = client
        _CLIENT_LOCAL.key = key
    return client


def check_one(index: int, row: dict, proxy: str, timeout: float, thresholds: Thresholds) -> dict:
    started = time.monotonic()
    try:
        with http_client(proxy, timeout).stream("GET", row["url"]) as response:
            body = fetch_limited(response, thresholds.max_bytes, timeout)
            content_type = response.headers.get("content-type", "").lower()
            encoding = response.encoding or "utf-8"
            final_url = str(response.url)
            status_code = response.status_code
        text = body.decode(encoding, errors="replace")
        base = {
            **row, "input_index": index, "checked_at_unix": int(time.time()),
            "http_status": status_code, "final_url": final_url,
            "content_type": content_type, "html_bytes": len(body),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        if status_code >= 400:
            return {**base, "preflight_status": "reject", "reason": f"http_{status_code}"}
        if "html" not in content_type:
            return {**base, "preflight_status": "reject", "reason": "non_html"}
        head = text[:120_000]
        if CHALLENGE_RE.search(head):
            return {**base, "preflight_status": "reject", "reason": "challenge_page"}
        if PARKED_RE.search(head):
            return {**base, "preflight_status": "reject", "reason": "parked_or_dead"}
        if UNSAFE_CONTENT_RE.search(head):
            return {**base, "preflight_status": "reject", "reason": "unsafe_content"}
        metrics = component_metrics(text, final_url)
        base.update(metrics)
        reasons = []
        if len(body) < thresholds.min_html_bytes:
            reasons.append("html_too_small")
        if metrics["text_chars"] < thresholds.min_text_chars:
            reasons.append("too_little_text")
        if len(metrics["component_types"]) < thresholds.min_component_types:
            reasons.append("too_few_component_types")
        if metrics["richness_score"] < thresholds.min_richness_score:
            reasons.append("low_structural_richness")
        if reasons:
            return {**base, "preflight_status": "reject", "reason": ";".join(reasons)}
        return {
            **base, "preflight_status": "pass", "reason": "pass",
            "structural_archetype": structural_archetype(metrics),
        }
    except httpx.HTTPError as exc:
        return {
            **row, "input_index": index, "preflight_status": "retryable",
            "reason": f"request_error:{type(exc).__name__}",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def robots_decision(text: str, page_url: str) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(page_url)
    parser.parse(text.splitlines())
    return parser.can_fetch("*", page_url)


def check_robots(row: dict, proxy: str, timeout: float) -> dict:
    parsed = urlsplit(row["final_url"])
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        with http_client(proxy, timeout).stream("GET", robots_url) as response:
            status_code = response.status_code
            body = fetch_limited(response, 262_144, timeout)
            encoding = response.encoding or "utf-8"
        if status_code == 404:
            return {"url": row["url"], "robots_allowed": True, "robots_status": "missing"}
        if status_code >= 400:
            return {
                "url": row["url"], "robots_allowed": False,
                "robots_status": f"unavailable_http_{status_code}",
            }
        allowed = robots_decision(body.decode(encoding, errors="replace"), row["final_url"])
        return {
            "url": row["url"], "robots_allowed": allowed,
            "robots_status": "allowed" if allowed else "explicitly_disallowed",
        }
    except httpx.HTTPError as exc:
        return {
            "url": row["url"], "robots_allowed": False,
            "robots_status": f"unavailable_{type(exc).__name__}",
        }


def select_balanced(rows: list[dict], target: int) -> list[dict]:
    strata: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["structural_archetype"], row.get("site_family", "unknown"), row.get("rank_band", "unknown"))
        strata[key].append(row)
    for values in strata.values():
        values.sort(key=lambda row: (-row["richness_score"], row["html_bytes"], row["url"]))
    keys = sorted(strata)
    selected: list[dict] = []
    cursor = 0
    while len(selected) < target and keys:
        key = keys[cursor % len(keys)]
        selected.append(strata[key].pop(0))
        if not strata[key]:
            keys.remove(key)
            cursor = 0
        else:
            cursor += 1
    return selected


def deduplicate_final_hosts(rows: list[dict]) -> list[dict]:
    """Keep the strongest candidate when several source domains converge."""
    best: dict[str, dict] = {}
    for row in rows:
        host = (urlsplit(row["final_url"]).hostname or "").lower()
        prior = best.get(host)
        score = (row["richness_score"], -row["html_bytes"])
        if host and (prior is None or score > (prior["richness_score"], -prior["html_bytes"])):
            best[host] = row
    return list(best.values())


def write_jsonl(path: Path, rows: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", type=int, default=4_000)
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--proxy", default="")
    parser.add_argument("--max-bytes", type=int, default=786_432)
    parser.add_argument("--min-html-bytes", type=int, default=4_000)
    parser.add_argument("--min-text-chars", type=int, default=250)
    parser.add_argument("--min-component-types", type=int, default=3)
    parser.add_argument("--min-richness-score", type=float, default=7.0)
    parser.add_argument("--check-robots", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--limit", type=int, default=None, help="Optional candidate prefix for bounded pilots/resume.")
    args = parser.parse_args()
    if min(args.target, args.concurrency, args.min_html_bytes, args.min_text_chars,
           args.min_component_types) < 1 or args.min_richness_score <= 0:
        parser.error("target, concurrency and structural thresholds must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = [json.loads(line) for line in args.candidate_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        candidates = candidates[:args.limit]
    thresholds = Thresholds(
        max_bytes=args.max_bytes,
        min_html_bytes=args.min_html_bytes,
        min_text_chars=args.min_text_chars,
        min_component_types=args.min_component_types,
        min_richness_score=args.min_richness_score,
    )
    result_path = args.output_dir / "preflight_results.jsonl"
    results: list[dict] = []
    if result_path.exists():
        results = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        # A resumed pilot may intentionally lower --limit after enough live
        # passes have accumulated.  Keep only rows in the current candidate
        # slice so the reported denominator and selection remain reproducible.
        candidate_urls = {row["url"] for row in candidates}
        results = [row for row in results if row["url"] in candidate_urls]
    completed_urls = {row["url"] for row in results}
    pending_inputs = [(index, row) for index, row in enumerate(candidates) if row["url"] not in completed_urls]
    started = time.monotonic()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency)
    futures = {}
    source = iter(pending_inputs)

    def submit_one() -> bool:
        try:
            index, row = next(source)
        except StopIteration:
            return False
        future = pool.submit(check_one, index, row, args.proxy, args.timeout, thresholds)
        futures[future] = row["url"]
        return True

    completed = 0
    try:
        with result_path.open("a", encoding="utf-8") as result_handle:
            for _ in range(args.concurrency):
                if not submit_one():
                    break
            while futures:
                finished, _ = concurrent.futures.wait(
                    futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in finished:
                    futures.pop(future)
                    row = future.result()
                    completed += 1
                    results.append(row)
                    result_handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    result_handle.flush()
                if completed and completed % 500 < len(finished):
                    passed_so_far = sum(item["preflight_status"] == "pass" for item in results)
                    print(
                        f"checked={len(results)}/{len(candidates)} new={completed}/{len(pending_inputs)} passed={passed_so_far}",
                        flush=True,
                    )
                while len(futures) < args.concurrency and submit_one():
                    pass
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    results.sort(key=lambda row: row["input_index"])
    policy_filtered = [
        row for row in results
        if row["preflight_status"] == "pass"
        and not (policy_safe_url(row["url"]) and policy_safe_url(row["final_url"]))
    ]
    passed = [
        row for row in results
        if row["preflight_status"] == "pass"
        and policy_safe_url(row["url"]) and policy_safe_url(row["final_url"])
    ]
    robots_rows: list[dict] = []
    if args.check_robots:
        robots_path = args.output_dir / "robots_results.jsonl"
        if robots_path.exists():
            robots_rows = [json.loads(line) for line in robots_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        robots_done = {row["url"] for row in robots_rows}
        # Check a structurally balanced order and stop as soon as the target is
        # satisfied.  Do not spend thousands of extra requests auditing
        # candidates that cannot enter this queue.
        robots_pending = [
            row for row in select_balanced(passed, len(passed))
            if row["url"] not in robots_done
        ]
        with robots_path.open("a", encoding="utf-8") as robots_handle:
            for batch_start in range(0, len(robots_pending), 500):
                allowed_so_far = sum(row.get("robots_allowed") for row in robots_rows)
                if allowed_so_far >= args.target:
                    break
                batch = robots_pending[batch_start:batch_start + 500]
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                    futures = [pool.submit(check_robots, row, args.proxy, args.timeout) for row in batch]
                    for future in concurrent.futures.as_completed(futures):
                        robot_row = future.result()
                        robots_rows.append(robot_row)
                        robots_handle.write(json.dumps(robot_row, ensure_ascii=False, sort_keys=True) + "\n")
                        robots_handle.flush()
                print(
                    f"robots_checked={len(robots_rows)}/{len(passed)} "
                    f"robots_allowed={sum(row.get('robots_allowed') for row in robots_rows)}",
                    flush=True,
                )
        robots_by_url = {row["url"]: row for row in robots_rows}
        eligible = [
            {**row, **robots_by_url[row["url"]]}
            for row in passed
            if robots_by_url.get(row["url"], {}).get("robots_status") in {"allowed", "missing"}
        ]
    else:
        eligible = passed
    eligible = deduplicate_final_hosts(eligible)
    selected = select_balanced(eligible, args.target)
    write_jsonl(args.output_dir / "selected_manifest.jsonl", selected)
    selected_urls_tmp = args.output_dir / "selected_urls.txt.tmp"
    selected_urls_tmp.write_text(
        "".join(row["final_url"] + "\n" for row in selected), encoding="utf-8"
    )
    selected_urls_tmp.replace(args.output_dir / "selected_urls.txt")
    status_counts = Counter(row["preflight_status"] for row in results)
    reason_counts = Counter(row["reason"] for row in results)
    summary = {
        "status": "live_http_preflight_complete" if len(selected) >= args.target else "insufficient_passes",
        "checked": len(results), "passed": len(passed), "robots_eligible": len(eligible),
        "policy_filtered_passes": len(policy_filtered),
        "robots_statuses": dict(Counter(row["robots_status"] for row in robots_rows)),
        "selected": len(selected),
        "unique_source_domains": len({row["pay_level_domain"] for row in selected}),
        "unique_final_hosts": len({urlsplit(row["final_url"]).hostname for row in selected}),
        "status_counts": dict(status_counts), "reason_counts": dict(reason_counts),
        "archetypes": dict(Counter(row["structural_archetype"] for row in selected)),
        "component_type_coverage": dict(Counter(kind for row in selected for kind in row["component_types"])),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "thresholds": thresholds.as_dict(),
        "qualification": "entry-page HTTP, structural and explicit robots preflight only; strict crawl is still required",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if len(selected) < args.target:
        raise SystemExit(f"only {len(selected)} live rich candidates for target {args.target}")


if __name__ == "__main__":
    main()
