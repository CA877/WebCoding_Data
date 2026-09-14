"""Bounded whole-page resource capture and localhost replay."""
from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright, Error as BrowserError
import tinycss2

from crawl.pipeline_d.main import (
    disable_motion, evaluate_replay_admission, newly_introduced_errors, project_id,
    screenshot_edge_density, screenshot_similarity, viewport_interactive_element_count,
    viewport_visible_text_chars,
)
from .resources import absolutize_html
from .code_assets import external_library
from crawl.pipeline_c.qwen_token_gate import count_project_tokens


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def browser_session(proxy, existing=None):
    if existing is not None:
        yield existing
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            proxy={'server':proxy,'bypass':'localhost,127.0.0.1'} if proxy else None)
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def serve_project(directory: Path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(directory)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


SCAN_JS = """async () => {
  const visible = el => {
    const r=el.getBoundingClientRect(), s=getComputedStyle(el);
    return r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight &&
      r.right>0 && r.left<innerWidth && s.display!=='none' &&
      s.visibility!=='hidden' && s.opacity!=='0';
  };
  const images=[...document.images].filter(visible);
  await Promise.all(images.map(img => Promise.race([
    img.decode().catch(()=>{}), new Promise(r=>setTimeout(r,2000))])));
  const broken=images.filter(i=>!i.complete || i.naturalWidth===0)
    .map(i=>i.currentSrc || i.src || '(empty image)');
  const css=[];
  for (const el of document.querySelectorAll('*')) {
    if (!visible(el)) continue;
    for (const pseudo of [null,'::before','::after']) {
      const s=getComputedStyle(el,pseudo);
      for(const prop of ['backgroundImage','maskImage','borderImageSource','listStyleImage','content']) {
        const v=s[prop]; if(v && (v.includes('url(') || v.includes('image-set('))) css.push(v);
      }
    }
  }
  return {broken, css:[...new Set(css)], images:images.length,
    y:scrollY, height:document.documentElement.scrollHeight};
}"""


def css_urls(values):
    result = set()
    def visit(tokens):
        for token in tokens:
            if token.type == 'url':
                result.add(token.value)
            elif token.type == 'function':
                if token.lower_name == 'url':
                    result.update(x.value for x in token.arguments if x.type == 'string')
                else:
                    if token.lower_name in {'image-set','-webkit-image-set'}:
                        result.update(x.value for x in token.arguments if x.type == 'string')
                    visit(token.arguments)
    for value in values:
        visit(tinycss2.parse_component_value_list(value))
    return {x for x in result if not x.startswith('#')}


def sweep(page, max_steps: int = 80) -> dict:
    seen_css, broken, positions = set(), set(), []
    images = 0
    stable_bottom = 0
    for _ in range(max_steps):
        page.wait_for_timeout(200)
        result = page.evaluate(SCAN_JS)
        images += result['images']
        broken.update(result['broken'])
        urls = {x for x in css_urls(result['css']) if x.split('#')[0] != page.url.split('#')[0]} - seen_css
        seen_css.update(urls)
        if urls:
            failed = page.evaluate("""async urls => (await Promise.all(urls.map(url =>
              new Promise(resolve => {
                if(url.startsWith('blob:')) return resolve(url);
                const img=new Image(); const timer=setTimeout(()=>resolve(url),5000);
                img.onload=()=>{clearTimeout(timer);resolve(img.naturalWidth?null:url)};
                img.onerror=()=>{clearTimeout(timer);resolve(url)}; img.src=url;
              })))).filter(Boolean)""", sorted(urls))
            broken.update(failed)
        positions.append(result['y'])
        bottom = page.evaluate('scrollY + innerHeight >= document.documentElement.scrollHeight - 2')
        stable_bottom = stable_bottom + 1 if bottom else 0
        if stable_bottom >= 2:
            break
        page.evaluate('scrollBy(0, Math.max(200, innerHeight * 0.75))')
    else:
        raise ValueError('full_page_scroll_limit')
    page.evaluate('scrollTo(0,0)')
    page.wait_for_timeout(200)
    if broken:
        raise ValueError('full_page_broken_resource:' + json.dumps(sorted(broken)[:20]))
    return {'scroll_positions': positions, 'image_observations': images,
            'css_image_urls': sorted(seen_css), 'broken_resources': []}


def observe(page):
    errors, failures = [], []
    kinds = {'document', 'stylesheet', 'script', 'font', 'image', 'media', 'xhr', 'fetch'}
    page.on('pageerror', lambda exc: errors.append(str(exc)[:400]))
    page.on('response', lambda response: failures.append(
        f'{response.status}:{response.request.resource_type}:{response.url}')
        if response.status >= 400 and response.request.resource_type in kinds else None)
    page.on('requestfailed', lambda req: failures.append(f'failed:{req.resource_type}:{req.url}')
            if req.resource_type in kinds else None)
    return errors, failures


def capture_page(url: str, output: Path, proxy: str, wait_ms: int,
                 *, assets=None, target_name='index.html', browser=None,
                 inspect_source=None) -> dict:
    pid = project_id(url)
    project = output / 'projects' / pid
    project.mkdir(parents=True, exist_ok=True)
    evidence = output / 'render_evidence'
    evidence.mkdir(exist_ok=True)
    record = {'source_url': url, 'project_id': pid, 'status': 'rejected'}
    try:
        with browser_session(proxy, browser) as active_browser:
            contexts = []
            try:
                context = active_browser.new_context(viewport={'width':1280,'height':800}, service_workers='block')
                contexts.append(context)
                page = context.new_page()
                access_failures = []
                if assets is not None:
                    def guard_document(route):
                        if route.request.is_navigation_request():
                            try:
                                assets.check_access(route.request.url)
                            except ValueError as exc:
                                access_failures.append(str(exc))
                                route.abort()
                                return
                        route.continue_()
                    page.route('**/*', guard_document)
                source_errors, source_failures = observe(page)
                response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                if response is None or response.status >= 400 or access_failures:
                    raise ValueError('source_http_error:' + str(response.status if response else None)
                                     + ':' + ';'.join(access_failures))
                if 'html' not in response.headers.get('content-type','').lower():
                    raise ValueError('source_not_html')
                page.wait_for_timeout(wait_ms)
                raw = page.content()
                (evidence / f'{pid}_raw.html').write_text(raw, encoding='utf-8')
                if assets is not None:
                    # Fail oversized code before the expensive full-page sweep.
                    early, _ = absolutize_html(raw, page.url)
                    (assets.project / target_name).write_text(early, encoding='utf-8')
                    if count_project_tokens(assets.project, assets.tokenizer) > assets.limit:
                        raise ValueError('saved_code_tokens_over_limit')
                    early = assets.html(early, page.url, context.request)
                    (assets.project / target_name).write_text(early, encoding='utf-8')
                    if count_project_tokens(assets.project, assets.tokenizer) > assets.limit:
                        raise ValueError('saved_code_tokens_over_limit')
                source_sweep = sweep(page)
                # Freeze post-scroll DOM so lazily assigned URLs are materialized.
                raw = page.content()
                (evidence / f'{pid}_scrolled.html').write_text(raw, encoding='utf-8')
                final_url = page.url
                saved, transform = absolutize_html(raw, final_url)
                if inspect_source is not None:
                    inspect_source(saved, final_url, source_sweep)
                if assets is not None:
                    assets.check_access(final_url)
                    saved = assets.html(saved, final_url, context.request)
                    (assets.project / target_name).write_text(saved, encoding='utf-8')
                (project / 'index.html').write_text(saved, encoding='utf-8')
                text_chars = len(page.locator('body').inner_text().strip())
                disable_motion(page)
                source_shot = page.screenshot(full_page=False)
                source_full = page.screenshot(full_page=True)
                source_visible = viewport_visible_text_chars(page)
                source_interactive = viewport_interactive_element_count(page)
                replay_context = active_browser.new_context(viewport={'width':1280,'height':800}, service_workers='block')
                contexts.append(replay_context)
                replay = replay_context.new_page()
                errors, failures = observe(replay)
                remote_code = []
                if assets is not None:
                    replay.on('request', lambda req: remote_code.append(req.url)
                        if req.resource_type in {'script','stylesheet'}
                        and req.url.startswith(('http://','https://'))
                        and not req.url.startswith(origin + '/') and not external_library(req.url)
                        and req.url not in assets.external else None)
                with serve_project(assets.project if assets is not None else project) as origin:
                    response = replay.goto(origin + '/' + target_name, wait_until='domcontentloaded', timeout=30000)
                    replay.wait_for_timeout(wait_ms)
                    replay_sweep = sweep(replay)
                    replay_chars = len(replay.locator('body').inner_text().strip())
                    disable_motion(replay)
                    replay_shot = replay.screenshot(full_page=False)
                    replay_full = replay.screenshot(full_page=True)
                    metrics = {
                        'mode':'localhost_absolute_resources', 'http_status':response.status,
                        'final_url':final_url, 'source_viewport_visible_text_chars':source_visible,
                        'source_screenshot_edge_density':screenshot_edge_density(source_shot),
                        'viewport_visible_text_chars':viewport_visible_text_chars(replay),
                        'screenshot_edge_density':screenshot_edge_density(replay_shot),
                        'source_viewport_interactive_elements':source_interactive,
                        'viewport_interactive_elements':viewport_interactive_element_count(replay),
                        'text_chars':replay_chars, 'source_text_chars':text_chars,
                        'text_retention_ratio':replay_chars/text_chars if text_chars else (1.0 if replay_chars == 0 else 2.0),
                        'screenshot_similarity':screenshot_similarity(source_shot,replay_shot),
                        'full_page_similarity':screenshot_similarity(source_full,replay_full),
                        'source_critical_resource_failures':sorted(set(source_failures)),
                        'critical_resource_failures':sorted(set(failures)),
                        'page_errors':newly_introduced_errors(source_errors,errors),
                        'source_page_errors':source_errors,
                        'source_sweep':source_sweep, 'replay_sweep':replay_sweep,
                        'unsaved_remote_code':sorted(set(remote_code)),
                    }
                for label, shot in [('source', source_full), ('replay', replay_full)]:
                    (evidence / f'{pid}_{label}.png').write_bytes(shot)
                record.update(final_url=final_url, transform=transform, render_validation=metrics,
                    render_evidence={label:f'render_evidence/{pid}_{label}.png' for label in ['source','replay']})
                # A short real page is not missing content when its source is equally short.
                verdict = evaluate_replay_admission(metrics, 'strict', min_text_chars=0)
                if not verdict['accepted']:
                    raise ValueError(';'.join(verdict['failure_reasons']))
                if metrics['full_page_similarity'] < 0.85:
                    raise ValueError('full_page_visual_mismatch')
                if metrics['page_errors']:
                    raise ValueError('localhost_introduced_page_errors')
                if remote_code:
                    raise ValueError('unsaved_dynamic_code:' + json.dumps(sorted(set(remote_code))[:10]))
                record['status'] = 'pass'
            finally:
                for context in reversed(contexts):
                    context.close()
    except (ValueError, BrowserError) as exc:
        record['reason'] = str(exc)[:1500]
    (project / 'capture.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
