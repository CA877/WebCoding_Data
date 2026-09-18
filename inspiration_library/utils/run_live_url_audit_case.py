#!/usr/bin/env python3
"""Run one bounded case of the online miner with process-group cleanup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def supervise(command, *, cwd, run_dir, seconds, env=None):
    run_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    status, code = 'error', None
    proc = None
    with (run_dir/'stdout.log').open('w') as log, (run_dir/'events.jsonl').open('a') as events:
        def event(kind, **fields):
            row = dict(time=datetime.now(timezone.utc).isoformat(), event=kind,
                       elapsed=round(time.monotonic()-started, 2), **fields)
            events.write(json.dumps(row)+'\n')
            events.flush()
            print(json.dumps(row), flush=True)
        try:
            proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            event('started', pid=proc.pid, hard_timeout_seconds=seconds, attempts=1, concurrency=1)
            while proc.poll() is None:
                remaining = seconds - (time.monotonic()-started)
                if remaining <= 0:
                    status = 'timeout'
                    break
                try:
                    proc.wait(timeout=min(15, remaining))
                except subprocess.TimeoutExpired:
                    event('heartbeat', pid=proc.pid)
            else:
                code = proc.returncode
                status = 'ok' if code == 0 else 'error'
        except (KeyboardInterrupt, SystemExit, BrokenPipeError):
            status = 'interrupted'
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                code = proc.returncode
            result = dict(status=status, returncode=code, elapsed_seconds=round(time.monotonic()-started, 2),
                          attempts=1, command=command)
            (run_dir/'supervisor_result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['url','local_project'], default='url')
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--seed-id', required=True)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--stage', choices=['scan','full','extract'], default='full')
    p.add_argument('--observation', type=Path)
    p.add_argument('--resume-miner-dir', type=Path, help='Resume a matching miner identity; supervisor writes new logs')
    p.add_argument('--extract-worker', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--browser-proxy', help='Browser-only proxy passed to the production miner')
    p.add_argument('--source-mode', choices=['reference', 'examples', 'none'], default='reference')
    p.add_argument('--max-source-regions', type=int, choices=range(1, 9), default=4)
    p.add_argument('--seconds', type=int, default=480)
    p.add_argument('--key-stdin', action='store_true')
    args = p.parse_args()
    if not 1 <= args.seconds <= 600:
        p.error('single-case deadline must be 1-600 seconds')
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    env = os.environ.copy()
    for name in ['ALL_PROXY','HTTPS_PROXY','HTTP_PROXY','all_proxy','https_proxy','http_proxy']:
        env.pop(name, None)
    if args.key_stdin:
        env['DOC_API_KEY'] = sys.stdin.read().strip()
    if args.stage in {'full','extract'} and not env.get('DOC_API_KEY'):
        p.error('full mining requires a protected DOC_API_KEY or --key-stdin')
    if args.stage == 'extract' and (not args.observation or not args.observation.is_file()):
        p.error('extract-only diagnostic requires a real saved browser observation')
    if args.resume_miner_dir and (args.stage != 'full' or not (args.resume_miner_dir/'run_identity.json').is_file()):
        p.error('resume requires full stage and an existing miner identity')
    env.update(PYTHONPATH=str(root), PYTHONUNBUFFERED='1')
    if args.extract_worker:
        from inspiration_library.utils.mine_live_url_capability_pool import load_sources
        from inspiration_library.doc_api import DocApiClient
        from inspiration_library.dynamic_capability_retrieval import extract_seed_capabilities
        source = next(r for r in load_sources(args.sources, args.mode) if r['seed_id']==args.seed_id)
        observation = json.loads(args.observation.read_text())
        args.run_dir.mkdir(parents=True, exist_ok=False)
        with DocApiClient(api_key=env['DOC_API_KEY'], log_dir=args.run_dir/'provider', timeout_seconds=90) as client:
            extraction = extract_seed_capabilities(seed=source, observation=observation, client=client,
                                                   request_id='diagnostic_baseline_extract')
        (args.run_dir/'extraction.json').write_text(json.dumps(extraction, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(dict(stage='extract_only', cards=len(extraction['capabilities']),
                              observation=str(args.observation))), flush=True)
        return 0
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    for sig in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, interrupted)
    command = [sys.executable, str(root/'inspiration_library/utils/mine_live_url_capability_pool.py'),
               '--mode', args.mode,
               '--sources', str(args.sources.resolve()), '--seed-id', args.seed_id,
               '--run-dir', str(args.resume_miner_dir.resolve() if args.resume_miner_dir else args.run_dir.resolve()/'miner'), '--stage', args.stage,
               '--exploration-rounds','1','--max-paths','3','--max-actions','4',
               '--api-timeout-seconds','90']
    command.extend(['--source-mode', args.source_mode, '--max-source-regions', str(args.max_source_regions)])
    if args.stage == 'extract':
        command = [sys.executable, str(Path(__file__).resolve()), '--extract-worker', '--stage','extract',
                   '--mode', args.mode,
                   '--sources', str(args.sources.resolve()), '--seed-id', args.seed_id,
                   '--observation', str(args.observation.resolve()),
                   '--run-dir', str(args.run_dir.resolve()/'extractor')]
    elif args.browser_proxy:
        command.extend(['--browser-proxy', args.browser_proxy])
    result = supervise(command, cwd=root, run_dir=args.run_dir.resolve(), seconds=args.seconds, env=env)
    print(json.dumps(result), flush=True)
    return 0 if result['status']=='ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
