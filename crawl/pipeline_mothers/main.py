"""Capture two to four documents with absolute online resource references."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import shutil
from collections import Counter
from contextlib import ExitStack
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from bs4 import BeautifulSoup
from playwright.sync_api import Error as BrowserError

from crawl.pipeline_c.main import discover_same_site_pages, PREFLIGHT_DENY_RE, PREFLIGHT_HOSTING_RE
from crawl.pipeline_c.policy import assess_html
from crawl.pipeline_c.qwen_token_gate import count_project_tokens
from crawl.pipeline_d.main import project_id
from .capture import capture_page, serve_project, browser_session
from .resources import localize_navigation
from .code_assets import CodeAssets


def sample_preflight(url, timeout, proxy=''):
    """Bounded transport check with the same proxy and TLS policy as capture."""
    parts = urlsplit(url)
    if (parts.scheme not in {'http','https'} or not parts.hostname
            or PREFLIGHT_DENY_RE.search(url) or PREFLIGHT_HOSTING_RE.search(parts.hostname)):
        return False, url, 'static_url_reject'
    try:
        with httpx.Client(proxy=proxy or None, trust_env=False, timeout=timeout,
                          follow_redirects=False) as client:
            with client.stream('GET', url) as response:
                if response.status_code in {301,302,303,307,308}:
                    return True, url, 'redirect_checked_by_capture'
                if response.status_code != 200:
                    return False, url, 'http_' + str(response.status_code)
                if 'html' not in response.headers.get('content-type','').lower():
                    return False, url, 'not_html'
                return True, url, 'pass'
    except httpx.HTTPError as exc:
        return False, url, type(exc).__name__


def check_access(url, proxy, cache):
    parts = urlsplit(url)
    origin = f'{parts.scheme}://{parts.netloc}'
    if origin not in cache:
        with httpx.Client(proxy=proxy or None, trust_env=False, follow_redirects=True, timeout=12) as client:
            try:
                response = client.get(origin + '/robots.txt')
            except httpx.HTTPError as exc:
                raise ValueError('robots_unavailable:' + type(exc).__name__) from exc
        if response.status_code == 404:
            lines = []
        elif response.status_code != 200:
            raise ValueError('robots_http_' + str(response.status_code))
        else:
            lines = response.text.splitlines()
            if any('ai-train=no' in x.lower() for x in lines):
                raise ValueError('source_disallows_ai_training')
        robot = RobotFileParser(origin + '/robots.txt')
        robot.parse(lines)
        cache[origin] = robot
    robot = cache[origin]
    if not robot.can_fetch('WebCodingMotherCrawler', url):
        raise ValueError('robots_disallowed')
    delay = robot.crawl_delay('WebCodingMotherCrawler') or 0
    if delay:
        time.sleep(delay)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def document_fingerprint(html, metrics):
    """Detect captured homepage aliases without scoring child-page semantics."""
    soup = BeautifulSoup(html, 'html.parser')
    body = soup.body or soup
    text = ' '.join(body.get_text(' ', strip=True).split())
    media = [(x.get('src',''), x.get('srcset','')) for x in body.find_all('img')]
    backgrounds = sorted(metrics.get('source_sweep',{}).get('css_image_urls',[]))
    return hashlib.sha256(json.dumps([text,media,backgrounds],ensure_ascii=False).encode()).hexdigest()


def document_routes(project: Path) -> dict[str, str]:
    metadata = json.loads((project / "metadata.json").read_text())
    routes = {}
    for item in metadata["pages"]:
        html = (project / item["file"]).read_text(encoding="utf-8")
        routes[urldefrag(item["final_url"])[0]] = html
        routes[urldefrag(item["source_url"])[0]] = html
    return routes


def install_replay(context, routes: dict[str, str], served: list[str]) -> None:
    def route_request(route):
        request = route.request
        url = urldefrag(request.url)[0]
        if request.is_navigation_request() and request.frame == request.frame.page.main_frame:
            if url in routes:
                served.append(url)
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=routes[url])
            else:
                # A saved-page redirect must not silently pass by loading live HTML.
                route.abort()
        else:
            route.continue_()
    context.route("**/*", route_request)


def check_navigation(project: Path, proxy: str, wait_ms: int, *, browser=None) -> dict:
    metadata = json.loads((project / "metadata.json").read_text())
    results = []
    with serve_project(project) as origin, browser_session(proxy, browser) as active_browser:
        home = origin + '/index.html'
        context = active_browser.new_context(service_workers="block", viewport={"width":1280,"height":800})
        served = []
        def note_document(response):
            if response.request.is_navigation_request() and response.status == 200:
                served.append(response.url)
        context.on('response', note_document)
        try:
            for child in metadata["pages"][1:]:
                page = context.new_page()
                try:
                    page.goto(home, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(wait_ms)
                    links = page.locator("a[href]")
                    target = origin + '/' + child['file']
                    matched = False
                    for i in range(links.count()):
                        link = links.nth(i)
                        if link.evaluate("el => el.href.split('#')[0]") != target or not link.is_visible():
                            continue
                        before = len(served)
                        link.click(timeout=10000)
                        page.wait_for_timeout(wait_ms)
                        reached = urldefrag(page.url)[0] == target
                        loaded_saved = target in served[before:]
                        # Same-document SPA navigation alone cannot verify the saved child HTML.
                        matched = reached and loaded_saved
                        break
                    results.append({"target":target,"ok":matched})
                except Exception as exc:
                    results.append({"target":child["source_url"],"ok":False,"error":str(exc)[:300]})
                finally:
                    page.close()
        finally:
            context.close()
    return {"ok":bool(results) and all(x["ok"] for x in results),"links":results}


def discover_mother_pages(html, page_url, limit):
    # Filter only non-page links; leave the saved source DOM untouched.
    soup = BeautifulSoup(html, 'html.parser')
    base = soup.find('base', href=True)
    page_url = urljoin(page_url, base['href']) if base else page_url
    for anchor in list(soup.find_all('a', href=True)):
        suffix = Path(urlsplit(urljoin(page_url,anchor['href'])).path).suffix.lower()
        if (anchor.has_attr('download') or anchor.find_parent(['noscript','template'])
                or suffix in {'.xml','.rss','.atom','.json','.txt','.svg','.webp','.gif',
                              '.jpeg','.ico','.woff','.woff2','.mp4','.mp3','.gz','.tar'}):
            anchor.decompose()
    return discover_same_site_pages(str(soup),page_url,limit)


def crawl_site(args, url: str) -> dict:
    pid = project_id(url)
    root = args.output / "candidates" / pid
    root.mkdir(parents=True, exist_ok=True)
    project = root / "project"
    project.mkdir(exist_ok=True)
    result = {"source_url":url,"project_id":pid,"status":"rejected",
              "quality_status":"candidate","resource_policy":"saved_business_code__absolute_online_media_and_verified_libraries",
              "project":str(project),"pages":[],"child_failures":[]}
    minimum = getattr(args, 'min_pages', 2)
    result['page_count_policy'] = {'minimum':minimum,'preferred':4,'maximum':4}
    access_cache = {}
    assets = CodeAssets(project, args.qwen_tokenizer, args.max_code_tokens,
                        lambda source: check_access(source, args.browser_proxy, access_cache),
                        render_only_min_bytes=(getattr(args,'render_only_min_bytes',100_000)
                            if getattr(args,'context_policy','full_code') == 'image_render_assisted' else 0))
    result['context_policy'] = getattr(args,'context_policy','full_code')
    try:
        check_access(url, args.browser_proxy, access_cache)
    except ValueError as exc:
        result['reason'] = str(exc)
        return result
    accepted, final, reason = sample_preflight(url, 12, args.browser_proxy)
    if not accepted:
        result["reason"] = "preflight_" + reason
        return result

    def capture(source: str, name: str) -> dict:
        def inspect_source(html, final_url, sweep):
            if name == 'index.html':
                assessment = assess_html(html)
                if not assessment.passed:
                    raise ValueError('html_quality:' + ';'.join(assessment.reasons))
                targets = discover_mother_pages(html,final_url,getattr(args,'child_attempts',12))
                if len(targets) < minimum-1:
                    raise ValueError('insufficient_page_candidates')
            elif (urlsplit(final_url).hostname != urlsplit(result['pages'][0]['final_url']).hostname
                    or final_url in {p['final_url'] for p in result['pages']}
                    or document_fingerprint(html,{'source_sweep':sweep}) in
                        {p['content_sha256'] for p in result['pages']}):
                raise ValueError('duplicate_page_or_offsite_redirect')
        check_access(source, args.browser_proxy, access_cache)
        record = capture_page(source, root / "captures", args.browser_proxy, args.wait_ms,
                              assets=assets, target_name=name, browser=browser,
                              inspect_source=inspect_source)
        if record["status"] != "pass":
            raise ValueError(record.get("reason", record["status"]))
        raw = (root / "captures" / "projects" / record["project_id"] / "index.html").read_text()
        (project / name).write_text(raw, encoding="utf-8")
        return {"source_url":source,"final_url":record["final_url"],"file":name,
                "sha256":hashlib.sha256(raw.encode()).hexdigest(),
                'content_sha256':document_fingerprint(raw,record['render_validation']),
                "render_validation":record["render_validation"],
                "transform":record['transform'],
                "evidence":record["render_evidence"]}

    session = ExitStack()
    try:
        browser = session.enter_context(browser_session(args.browser_proxy))
        home = capture(final, "index.html")
        home["source_url"] = url
        result["pages"].append(home)
        if count_project_tokens(project, args.qwen_tokenizer) > args.max_code_tokens:
            raise ValueError('homepage_code_tokens_over_limit')
        html = (project / "index.html").read_text()
        soup = BeautifulSoup(html, "html.parser")
        base = soup.find("base", href=True)
        discovery_base = urljoin(home["final_url"], base["href"]) if base else home["final_url"]
        targets = discover_mother_pages(html, discovery_base, getattr(args, 'child_attempts', 12))
        for child in targets:
            if len(result['pages']) == 4:
                break
            checkpoint = assets.checkpoint()
            child_name = f"page_{project_id(child)}.html"
            try:
                if urlsplit(child).hostname != urlsplit(home['final_url']).hostname:
                    continue
                # Prevent off-site redirects from being admitted as children.
                record = capture(child, child_name)
                allowed = discover_same_site_pages(
                    '<a href="' + record["final_url"].replace('"', '&quot;') + '">page</a>',
                    home["final_url"], 1)
                if (record["final_url"] in {x["final_url"] for x in result["pages"]} or not allowed
                    or record['content_sha256'] in {x['content_sha256'] for x in result['pages']}
                    or urlsplit(record['final_url']).hostname != urlsplit(home['final_url']).hostname):
                    (project / record["file"]).unlink()
                    raise ValueError("duplicate_page_or_offsite_redirect")
                if count_project_tokens(project, args.qwen_tokenizer) > args.max_code_tokens:
                    raise ValueError('saved_code_tokens_over_limit')
                result["pages"].append(record)
            except ValueError as exc:
                assets.rollback(checkpoint)
                if (project / child_name).exists():
                    (project / child_name).unlink()
                result["child_failures"].append({"url":child,"reason":str(exc)[:500]})
        mapping = {u: row['file'] for row in result['pages'] for u in (row['source_url'],row['final_url'])}
        for row in result['pages']:
            path = project / row['file']
            path.write_text(localize_navigation(path.read_text(encoding='utf-8'), mapping), encoding='utf-8')
            row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result['url_to_file'] = mapping
        result["code_tokens"] = count_project_tokens(project, args.qwen_tokenizer)
        result['all_saved_code_tokens'] = count_project_tokens(project,args.qwen_tokenizer,include_render_only=True)
        result["token_basis"] = "serialized model-visible files; shared files once; explicit render-only dependencies and external library bodies excluded"
        result['code_assets'] = assets.manifest()
        from crawl.pipeline_c.qwen_token_gate import (
            iter_training_code_files, read_render_dependencies, serialize_training_project)
        dependencies = read_render_dependencies(project,verify_hashes=True)
        inputs = [{'path':p.relative_to(project).as_posix(),'code':p.read_text(encoding='utf-8')}
                  for p in iter_training_code_files(project)]
        context = serialize_training_project(project)
        (root/'training_context.txt').write_text(context,encoding='utf-8')
        write_json(root/'input_files.json',inputs)
        result['model_input_files'] = [x['path'] for x in inputs]
        result['render_only_files'] = dependencies
        result['usage_constraints'] = {'image_based_only':bool(dependencies),
            'render_dependencies_read_only':True,'excluded_files_are_model_input':False,
            'excluded_files_are_patch_or_defect_targets':False}
        write_json(root/'training_context_manifest.json',{
            'context_policy':result['context_policy'],'model_input_files':result['model_input_files'],
            'code_tokens':result['code_tokens'],'all_saved_code_tokens':result['all_saved_code_tokens'],
            'render_only_files':dependencies,'external_libraries':result['code_assets']['external_libraries'],
            'usage_constraints':result['usage_constraints'],
            'context_sha256':hashlib.sha256(context.encode()).hexdigest()})
        write_json(project / "metadata.json", result)
        if not minimum <= len(result["pages"]) <= 4 or len(list(project.glob('*.html'))) != len(result['pages']):
            raise ValueError("requires_minimum_pages")
        if result["code_tokens"] > args.max_code_tokens:
            raise ValueError("saved_code_tokens_over_limit")
        if getattr(args, "visual_review", False):
            from crawl.pipeline_c.visual_review import review_screenshot
            result["visual_review"] = []
            for record in result["pages"]:
                verdict = review_screenshot(root / "captures" / record["evidence"]["replay"])
                result["visual_review"].append({"file":record["file"], **verdict})
                if verdict["status"] != "pass":
                    raise ValueError("visual_review_failed:" + record["file"])
        result["navigation"] = check_navigation(project, args.browser_proxy, args.wait_ms, browser=browser)
        if not result["navigation"]["ok"]:
            raise ValueError("saved_page_navigation_failed")
        result.update(status="pass", quality_status="online_mother_candidate")
    except (ValueError, BrowserError) as exc:
        result["reason"] = str(exc)[:1000]
    finally:
        session.close()
    write_json(project / "metadata.json", result)
    return result


def main() -> None:
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qwen-tokenizer", type=Path, required=True)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--max-child-pages", type=int, choices=[3], default=3)
    parser.add_argument('--min-pages', type=int, choices=[2,3,4], default=2)
    parser.add_argument("--child-attempts", type=int, default=12)
    parser.add_argument("--target", type=int, default=1, help="Cumulative successful multipage projects")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument('--fixed-concurrency', action='store_true',
                        help='Explicitly authorized: do not throttle/stop on aggregate host load')
    parser.add_argument("--total-timeout", type=int, default=0,
                        help="Batch wall-clock limit in seconds; 0 disables the limit")
    parser.add_argument('--lease-file', type=Path)
    parser.add_argument('--lease-max-age', type=int, default=300)
    parser.add_argument("--max-code-tokens", type=int, default=40000)
    parser.add_argument('--context-policy',choices=['full_code','image_render_assisted'],
                        default='image_render_assisted')
    parser.add_argument('--render-only-min-bytes',type=int,default=100_000)
    parser.add_argument("--wait-ms", type=int, default=1500)
    parser.add_argument("--visual-review", action=argparse.BooleanOptionalAction, default=False,
                        help="Optional existing Pipeline C paid screenshot review; default off.")
    parser.add_argument("--site-timeout", type=int, default=240)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--child-url", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (args.limit < 1 or args.site_timeout < 1 or not 1 <= args.max_code_tokens <= 40000
            or not 1 <= args.workers <= 8 or args.target < 1 or args.child_attempts < 3
            or args.total_timeout < 0 or args.lease_max_age < 1 or args.render_only_min_bytes < 1):
        parser.error("positive limits, 1-8 workers, at least 3 child attempts, at most 40000 tokens required")
    if not args.qwen_tokenizer.is_file():
        parser.error('Qwen tokenizer file missing')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.child_url:
        write_json(args.output / "receipt.json", crawl_site(args, args.child_url))
        return
    urls = list(dict.fromkeys(x.strip() for x in args.urls.read_text().splitlines() if x.strip()))[:args.limit]
    manifest = args.output / "manifest.jsonl"
    history = [json.loads(x) for x in manifest.read_text().splitlines() if x.strip()] if manifest.exists() else []
    rows = list({x['source_url']:x for x in history}.values())
    write_json(args.output / "run_config.json", {k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()})
    run_batch(args, urls, rows, manifest)


def stop_worker(worker):
    process = worker['process']
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()
    worker['log'].close()


def run_batch(args, urls, rows, manifest):
    done = {x['source_url'] for x in rows if x['status'] != 'needs_recrawl'}
    passed_sites = {(urlsplit(x['pages'][0]['final_url']).hostname or '').removeprefix('www.')
                    for x in rows if x['status'] == 'pass'}
    pending = iter(x for x in urls if x not in done)
    passed = sum(x['status'] == 'pass' for x in rows)
    attempts_dir = args.output / 'attempts'
    attempted = sum(x.is_dir() for x in attempts_dir.iterdir()) if attempts_dir.exists() else len(rows)
    attempt_limit = getattr(args, 'limit', len(urls))
    active = {}
    exhausted = False
    started = time.monotonic()
    heartbeat = 0
    status = 'running'
    reasons = Counter(x.get('reason','pass').split(':')[0] for x in rows)
    try:
        with manifest.open('a', encoding='utf-8') as handle:
            while passed < args.target:
                lease = getattr(args, 'lease_file', None)
                if lease is not None and (not lease.exists() or time.time()-lease.stat().st_mtime > args.lease_max_age):
                    raise RuntimeError('monitor_lease_expired')
                if args.total_timeout > 0 and time.monotonic()-started > args.total_timeout:
                    raise RuntimeError('total_time_limit')
                if shutil.disk_usage(args.output).free < 10 * 1024**3:
                    raise RuntimeError('disk_space_low')
                load = os.getloadavg()[0]
                host_cpus = os.cpu_count() or 1
                fixed = getattr(args, 'fixed_concurrency', False)
                if not fixed and load > host_cpus * .8:
                    raise RuntimeError('shared_host_load_high')
                # Reserve capacity for other users; each new browser gets two load units.
                effective_workers = args.workers if fixed else max(1, min(args.workers, int((host_cpus*.7-load)/2)))
                dispatch_paused = lease is not None and Path(str(lease) + '.pause').exists()
                if dispatch_paused:
                    effective_workers = 0
                meminfo = Path('/proc/meminfo')
                if meminfo.exists():
                    values = {x.split(':')[0]:int(x.split()[1]) for x in meminfo.read_text().splitlines()}
                    if values['MemAvailable'] < 16*1024**2:
                        raise RuntimeError('shared_host_memory_low')
                while not exhausted and len(active) < min(effective_workers, args.target-passed):
                    if attempted >= attempt_limit:
                        exhausted = True
                        break
                    url = next(pending, None)
                    if url is None:
                        exhausted = True
                        break
                    site = args.output / 'attempts' / project_id(url)
                    # Keep interrupted attempts for diagnosis and restart in a fresh directory.
                    if site.exists():
                        site = site.with_name(site.name + '-' + str(time.time_ns()))
                    site.mkdir(parents=True)
                    command = [sys.executable,'-m','crawl.pipeline_mothers.main',*sys.argv[1:],
                               '--output',str(site),'--child-url',url]
                    log = (site/'worker.log').open('a')
                    process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                    active[url] = {'process':process,'log':log,'site':site,'start':time.monotonic()}
                    attempted += 1
                    write_json(site/'attempt.json', {'source_url':url,'pid':process.pid,
                               'status':'running','started_at':time.time(),'attempt_number':attempted})
                for url, worker in list(active.items()):
                    process = worker['process']
                    timeout = time.monotonic()-worker['start'] >= args.site_timeout
                    if process.poll() is None and not timeout:
                        continue
                    stop_worker(worker)
                    write_json(worker['site']/'attempt.json', {'source_url':url,
                        'status':'timeout' if timeout else 'exited','returncode':process.returncode,
                        'elapsed_seconds':round(time.monotonic()-worker['start'],2),'finished_at':time.time()})
                    del active[url]
                    receipt = worker['site']/'receipt.json'
                    if timeout:
                        row = {'source_url':url,'status':'rejected','reason':'site_timeout'}
                    elif process.returncode != 0 or not receipt.exists():
                        raise RuntimeError('worker_error:' + str(worker['site']))
                    else:
                        row = json.loads(receipt.read_text())
                    if row['status'] == 'pass':
                        final_site = (urlsplit(row['pages'][0]['final_url']).hostname or '').removeprefix('www.')
                        if final_site in passed_sites:
                            row.update(status='rejected', reason='duplicate_final_site',
                                       quality_status='duplicate_candidate')
                            write_json(Path(row['project'])/'metadata.json', row)
                            write_json(receipt, row)
                        else:
                            passed_sites.add(final_site)
                    handle.write(json.dumps(row,ensure_ascii=False)+'\n')
                    handle.flush()
                    os.fsync(handle.fileno())
                    passed += row['status'] == 'pass'
                    reasons[row.get('reason','pass').split(':')[0]] += 1
                    print(json.dumps({'source_url':url,'status':row['status'],'passed':passed,
                                      'reason':row.get('reason')},ensure_ascii=False),flush=True)
                now = time.monotonic()
                if now-heartbeat >= 20:
                    snapshot = {'status':'running','passed':passed,'target':args.target,
                        'attempted':attempted,'in_flight':len(active),'workers':args.workers,
                        'effective_workers':effective_workers,
                        'dispatch_paused':dispatch_paused,
                        'elapsed_seconds':round(now-started),'load1':load,
                        'updated_at':time.time(),'reasons':dict(reasons)}
                    write_json(args.output/'progress.json',snapshot)
                    print(json.dumps(snapshot),flush=True)
                    heartbeat = now
                if exhausted and not active:
                    status = ('attempt_budget_exhausted' if attempted >= attempt_limit else 'queue_exhausted') if passed < args.target else 'complete'
                    break
                time.sleep(.5)
            else:
                status = 'complete'
    except BaseException as exc:
        status = 'stopped:' + str(exc)
        raise
    finally:
        for url, worker in active.items():
            stop_worker(worker)
            write_json(worker['site']/'attempt.json', {'source_url':url,'status':'interrupted',
                       'reason':status,'finished_at':time.time()})
        write_json(args.output/'progress.json',{'status':status,'passed':passed,'target':args.target,
            'attempted':attempted,'in_flight':0,'updated_at':time.time(),'reasons':dict(reasons)})


if __name__ == "__main__":
    main()
