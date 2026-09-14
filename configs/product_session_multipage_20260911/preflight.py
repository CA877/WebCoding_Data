"""One CCSleep multi-page Seed navigation/reload check using existing browser tests."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inspiration_library.production_browser import verify_project
from scripts.run_live_url_audit_case import supervise
from scripts.run_product_edit_session import ResourceMonitor

RUN = Path('/data2/adminweihunj/webcoding/inspiration_library/runs/product_session_multipage_20260911')
if '--worker' in sys.argv:
    result = verify_project(RUN/'seed', json.loads(Path(__file__).with_name('checks.json').read_text()),
                            RUN/'preflight', label='seed')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']),
                      'page_errors': result['page_errors'], 'console_errors': result['console_errors']}))
    raise SystemExit(0 if result['status'] == 'ok' else 1)
env = os.environ.copy()
for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
    env.pop(key, None)
result = supervise([sys.executable, str(Path(__file__).resolve()), '--worker'], cwd=ROOT,
                   run_dir=RUN/'preflight_unit', seconds=300, env=env, monitor=ResourceMonitor())
print(json.dumps(result))
raise SystemExit(0 if result['status'] == 'ok' else 1)
