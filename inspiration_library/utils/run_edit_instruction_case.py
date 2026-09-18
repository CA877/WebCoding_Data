#!/usr/bin/env python3
"""One physical-host instruction-only case: hard deadline, heartbeat, zero retries."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspiration_library.utils.run_live_url_audit_case import supervise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sampled-seeds', type=Path, required=True)
    p.add_argument('--evidence-run-dir', type=Path)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--capability-pool', type=Path, default=Path(
        '/data2/adminweihunj/webcoding/inspiration_library/current/capability_pool.jsonl'))
    p.add_argument('--embedding-dir', type=Path)
    p.add_argument('--revision-candidate', type=Path)
    p.add_argument('--revision-feedback', type=Path)
    p.add_argument('--candidate-response', type=Path)
    p.add_argument('--edit-count', choices=['random', 'auto'] + [str(n) for n in range(4,13)], default='random')
    p.add_argument('--length-seed', type=int)
    p.add_argument('--stage', choices=['retrieval','full'], default='full')
    p.add_argument('--seconds', type=int, default=600)
    credentials = p.add_mutually_exclusive_group()
    credentials.add_argument('--key-stdin', action='store_true')
    credentials.add_argument('--credentials-stdin', action='store_true',
                             help='Read protected provider settings as JSON over stdin')
    p.add_argument('--chat-model', help='TokenWave model; otherwise TOKENWAVE_CHAT_MODEL is required')
    a = p.parse_args()
    if not 1 <= a.seconds <= 600:
        p.error('deadline must be 1-600 seconds')
    env = os.environ.copy()
    for name in ['ALL_PROXY','HTTPS_PROXY','HTTP_PROXY','all_proxy','https_proxy','http_proxy']:
        env.pop(name, None)
    if a.credentials_stdin:
        settings = json.load(sys.stdin)
        allowed = {'TOKENWAVE_API_KEY', 'TOKENWAVE_CHAT_MODEL',
                   'DOC_EMBEDDING_BASE_URL', 'DOC_EMBEDDING_API_KEY'}
        if not isinstance(settings, dict) or set(settings) - allowed or any(
                not isinstance(value, str) for value in settings.values()):
            p.error('invalid protected provider settings')
        env.update(settings)
    if a.key_stdin:
        env['DOC_API_KEY'] = sys.stdin.read().strip()
    else:
        env['DOC_API_KEY'] = env.get('TOKENWAVE_API_KEY') or env.get('TOKENWAVE_OPENAI_API_KEY', '')
    if not env.get('DOC_API_KEY'):
        p.error('protected TOKENWAVE_API_KEY or --key-stdin required')
    env['DOC_API_BASE_URL'] = 'https://api.tokenwave.us/v1'
    env['DOC_API_CHAT_MODEL'] = a.chat_model or env.get('TOKENWAVE_CHAT_MODEL', '')
    if not env['DOC_API_CHAT_MODEL']:
        p.error('--chat-model or TOKENWAVE_CHAT_MODEL is required; no silent model substitution')
    if not env.get('DOC_EMBEDDING_BASE_URL') or not env.get('DOC_EMBEDDING_API_KEY'):
        p.error('explicit embedding provider settings required; keep the existing vector space')
    env.update(PYTHONPATH=str(ROOT), PYTHONUNBUFFERED='1')
    command=[sys.executable,str(ROOT/'inspiration_library/utils/run_linear_edit_query_augmentation.py'),
        '--run-dir',str(a.run_dir.resolve()/'miner'),'--sampled-seeds',str(a.sampled_seeds.resolve()),
        '--expected-total','1','--limit','1','--exploration-rounds','0','--api-timeout-seconds','90',
        '--edit-count',str(a.edit_count),'--stage',a.stage,
        '--capability-pool',str(a.capability_pool.resolve()),
        '--max-pool-cards','123','--max-embedding-requests','13']
    if a.evidence_run_dir:
        command += ['--evidence-run-dir',str(a.evidence_run_dir.resolve())]
    if a.embedding_dir:
        command += ['--embedding-dir',str(a.embedding_dir.resolve())]
    if a.length_seed is not None:
        command += ['--length-seed',str(a.length_seed)]
    if bool(a.revision_candidate) != bool(a.revision_feedback):
        p.error('revision requires both candidate and diagnosed feedback files')
    if a.revision_candidate:
        command += ['--revision-candidate',str(a.revision_candidate.resolve()),
                    '--revision-feedback',str(a.revision_feedback.resolve())]
    if a.candidate_response:
        if a.revision_candidate:
            p.error('candidate replay excludes revision')
        command += ['--candidate-response',str(a.candidate_response.resolve())]
    def interrupted(*_):
        raise KeyboardInterrupt
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig,interrupted)
    result=supervise(command,cwd=ROOT,run_dir=a.run_dir.resolve(),seconds=a.seconds,env=env)
    print(result,flush=True)
    return 0 if result['status']=='ok' else 1


if __name__=='__main__':
    raise SystemExit(main())
