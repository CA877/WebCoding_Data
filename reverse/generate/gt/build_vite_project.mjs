#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import vue from '@vitejs/plugin-vue';

const [projectArg, outArg] = process.argv.slice(2);
if (!projectArg || !outArg) throw new Error('project and output directories are required');
const project = path.resolve(projectArg);
const outDir = path.resolve(outArg);
const pkg = JSON.parse(fs.readFileSync(path.join(project, 'package.json'), 'utf8'));
const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
const plugins = [{
  name: 'webcoding-strip-empty-data-css-import',
  enforce: 'pre',
  transform(code, id) {
    if (!/\.css(?:\?|$)/i.test(id)) return null;
    const cleaned = code.replaceAll('@import url("data:text/css,");', '');
    return cleaned === code ? null : { code: cleaned, map: null };
  },
}];
if (deps.react || deps['react-dom']) plugins.push(react());
if (deps.vue) plugins.push(vue());

function htmlEntries(root) {
  const entries = {};
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(absolute);
      else if (/\.html?$/i.test(entry.name)) {
        const relative = path.relative(root, absolute).replaceAll(path.sep, '/');
        entries[relative.replace(/\.html?$/i, '').replaceAll('/', '_') || 'index'] = absolute;
      }
    }
  }
  walk(root);
  return entries;
}

const input = htmlEntries(project);
if (!Object.keys(input).length) throw new Error('framework project has no HTML entry');
await build({
  root: project,
  base: './',
  configFile: false,
  plugins,
  css: { postcss: { plugins: [] } },
  build: {
    outDir,
    emptyOutDir: true,
    rollupOptions: { input },
    minify: false,
    sourcemap: false,
  },
  logLevel: 'error',
});
process.stdout.write(JSON.stringify({ status: 'ok', entries: Object.keys(input) }) + '\n');
