#!/usr/bin/env node
/** G7 low-cost browser validation for generated static projects. */
const fs = require('fs');
const http = require('http');
const path = require('path');
const childProcess = require('child_process');

function argsOf(argv) {
  const out = { workers: 4, limit: 0, timeout: 30000, port: 0, watch: 0, poll_ms: 5000,
    build_timeout: 120000 };
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '').replaceAll('-', '_');
    if (argv[i + 1] === undefined) throw new Error(`missing value for ${argv[i]}`);
    out[key] = argv[i + 1];
  }
  for (const key of ['workers', 'limit', 'timeout', 'port', 'watch', 'poll_ms', 'build_timeout']) {
    out[key] = Number(out[key]);
  }
  if (!out.projects_dir || !out.out) throw new Error('--projects-dir and --out are required');
  return out;
}

function safeFile(root, renderRoots, requestPath) {
  const decoded = decodeURIComponent(requestPath.split('?')[0]);
  const parts = decoded.split('/').filter(Boolean);
  if (parts.length < 2 || parts.some(p => p === '..')) return null;
  const project = parts.shift();
  const projectRoot = renderRoots.get(project) || path.resolve(root, project);
  let target = path.resolve(projectRoot, parts.join('/'));
  if (!target.startsWith(projectRoot + path.sep)) return null;
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
  return { project, target };
}

function contentType(file) {
  return ({ '.html': 'text/html', '.htm': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
    '.mjs': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' })[path.extname(file).toLowerCase()]
    || 'application/octet-stream';
}

function startServer(root, renderRoots, port) {
  const server = http.createServer((req, res) => {
    const found = safeFile(root, renderRoots, req.url || '/');
    if (!found || !fs.existsSync(found.target) || !fs.statSync(found.target).isFile()) {
      res.writeHead(404); res.end('not found'); return;
    }
    res.writeHead(200, { 'content-type': contentType(found.target), 'cache-control': 'no-store' });
    fs.createReadStream(found.target).pipe(res);
  });
  return new Promise(resolve => server.listen(port, '127.0.0.1', () => resolve(server)));
}

function isViteProject(projectDir) {
  const pkgPath = path.join(projectDir, 'package.json');
  if (!fs.existsSync(pkgPath)) return false;
  try {
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
    return Boolean(deps.vite || /\bvite\b/.test((pkg.scripts || {}).build || ''));
  } catch (_) { return false; }
}

function prepareRenderRoot(args, projectsDir, projectId) {
  const projectDir = path.join(projectsDir, projectId);
  if (!isViteProject(projectDir)) return { root: projectDir, runtime: 'static', cleanup: () => {} };
  if (!args.framework_builder || !args.build_root) {
    throw new Error('Vite project requires --framework-builder and --build-root');
  }
  const output = path.resolve(args.build_root, projectId);
  fs.rmSync(output, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const built = childProcess.spawnSync(process.execPath, [path.resolve(args.framework_builder), projectDir, output], {
    cwd: projectDir,
    encoding: 'utf8',
    timeout: args.build_timeout,
    env: { ...process.env, NODE_ENV: 'production' },
  });
  if (built.error || built.status !== 0) {
    const detail = (built.stderr || built.stdout || built.error?.message || 'unknown build error').slice(-4000);
    fs.rmSync(output, { recursive: true, force: true });
    throw new Error(`Vite build failed: ${detail}`);
  }
  return { root: output, runtime: 'vite_build', cleanup: () => fs.rmSync(output, { recursive: true, force: true }) };
}

function htmlFiles(projectDir) {
  const found = [];
  function walk(dir, prefix = '') {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const relative = path.posix.join(prefix, entry.name);
      if (entry.isDirectory()) walk(path.join(dir, entry.name), relative);
      else if (/\.html?$/i.test(entry.name)) found.push(relative);
    }
  }
  walk(projectDir);
  found.sort((a, b) => (a === 'index.html' ? -1 : b === 'index.html' ? 1 : a.localeCompare(b)));
  return found.slice(0, 12);
}

async function validateProject(browser, baseUrl, projectsDir, renderRoots, projectId, timeout, args) {
  const started = Date.now();
  const projectDir = path.join(projectsDir, projectId);
  let prepared;
  try {
    prepared = prepareRenderRoot(args, projectsDir, projectId);
    renderRoots.set(projectId, prepared.root);
  } catch (error) {
    return { project_id: projectId, status: 'needs_repair', reasons: ['framework_build_failed'],
      error: error.message, pages: [], duration_seconds: (Date.now() - started) / 1000 };
  }
  const pages = [];
  let decision = 'accept';
  const html = htmlFiles(prepared.root);
  if (!html.length) {
    renderRoots.delete(projectId); prepared.cleanup();
    return { project_id: projectId, status: 'needs_repair', reasons: ['missing_html'], pages: [] };
  }
  try { for (const relative of html) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const pageErrors = [], consoleErrors = [], essentialFailures = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('requestfailed', request => {
      if (['document', 'script', 'stylesheet'].includes(request.resourceType())) {
        essentialFailures.push(`${request.resourceType()}:${request.url()}:${request.failure()?.errorText || ''}`);
      }
    });
    page.on('response', response => {
      const request = response.request();
      if (response.status() >= 400 && ['document', 'script', 'stylesheet'].includes(request.resourceType())) {
        essentialFailures.push(`${request.resourceType()}:${response.status()}:${response.url()}`);
      }
    });
    let httpStatus = null, facts = null, navigationError = null;
    try {
      const response = await page.goto(`${baseUrl}/${encodeURIComponent(projectId)}/${relative}`, {
        waitUntil: 'networkidle', timeout,
      });
      httpStatus = response ? response.status() : null;
      facts = await page.evaluate(() => {
        const visibleGraphic = [...document.querySelectorAll('canvas,svg,img,video')].some(el => {
          const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
          return r.width >= 80 && r.height >= 60 && s.display !== 'none' && s.visibility !== 'hidden';
        });
        return {
          title: document.title,
          body_text_chars: (document.body?.innerText || '').trim().length,
          body_children: document.body?.children.length || 0,
          visible_graphic: visibleGraphic,
          scroll_width: document.documentElement.scrollWidth,
          client_width: document.documentElement.clientWidth,
        };
      });
    } catch (error) { navigationError = error.message; }
    await page.close();
    const blank = !facts || (facts.body_text_chars < 20 && !facts.visible_graphic);
    const severeOverflow = facts && facts.scroll_width > facts.client_width * 1.5;
    const severe = Boolean(navigationError || (httpStatus !== null && httpStatus >= 400) || blank
      || pageErrors.length || essentialFailures.length || severeOverflow);
    if (severe) decision = 'needs_repair';
    else if (consoleErrors.length && decision === 'accept') decision = 'review';
    pages.push({ path: relative, http_status: httpStatus, facts, navigation_error: navigationError,
      page_errors: pageErrors, console_errors: consoleErrors, essential_failures: essentialFailures,
      blank, severe_overflow: Boolean(severeOverflow) });
  } } finally {
    renderRoots.delete(projectId);
    prepared.cleanup();
  }
  return { project_id: projectId, status: decision, runtime: prepared.runtime, pages,
    duration_seconds: (Date.now() - started) / 1000 };
}

async function main() {
  const args = argsOf(process.argv);
  const projectsDir = path.resolve(args.projects_dir), outPath = path.resolve(args.out);
  const done = new Set();
  const latest = new Map();
  if (fs.existsSync(outPath)) for (const line of fs.readFileSync(outPath, 'utf8').split('\n')) {
    if (line.trim()) {
      const row = JSON.parse(line);
      latest.set(row.project_id, row.status);
    }
  }
  for (const [projectId, status] of latest) {
    if (!args.retry_status || status !== args.retry_status) done.add(projectId);
  }
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const renderRoots = new Map();
  const server = await startServer(projectsDir, renderRoots, args.port);
  const address = server.address();
  const modulePath = process.env.PLAYWRIGHT_MODULE || 'playwright';
  const { chromium } = require(modulePath);
  const launch = { headless: true, args: ['--no-sandbox'] };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch);
  const stream = fs.createWriteStream(outPath, { flags: 'a' });
  let completed = 0;
  do {
    let projects = fs.readdirSync(projectsDir).filter(name =>
      fs.existsSync(path.join(projectsDir, name, '.generation.json')) && !done.has(name)
      && (!args.project_id || name === args.project_id)).sort();
    if (args.limit) projects = projects.slice(0, args.limit);
    let cursor = 0;
    async function worker() {
      while (cursor < projects.length) {
        const projectId = projects[cursor++];
        let result;
        try { result = await validateProject(browser, `http://127.0.0.1:${address.port}`, projectsDir,
          renderRoots, projectId, args.timeout, args); }
        catch (error) { result = { project_id: projectId, status: 'validator_error', error: error.stack || String(error) }; }
        stream.write(JSON.stringify(result) + '\n'); done.add(projectId); completed += 1;
        process.stdout.write(JSON.stringify({ progress: completed, project_id: projectId, status: result.status }) + '\n');
      }
    }
    await Promise.all(Array.from({ length: Math.max(1, args.workers) }, worker));
    if (!args.watch || args.project_id) break;
    await new Promise(resolve => setTimeout(resolve, Math.max(250, args.poll_ms)));
  } while (true);
  stream.end(); await new Promise(resolve => stream.on('finish', resolve));
  await browser.close(); await new Promise(resolve => server.close(resolve));
}

main().catch(error => { console.error(error.stack || error); process.exit(1); });
