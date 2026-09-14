"""Validate the completed multi-page Product Session once, after its controller exits."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

DATA_ROOT = Path('/data2/adminweihunj/webcoding/inspiration_library/code/product_session_20260909')
RUN = Path('/data2/adminweihunj/webcoding/inspiration_library/runs/product_session_multipage_20260911')
sys.path.insert(0, str(DATA_ROOT))
from inspiration_library.production_browser import verify_project

spec = importlib.util.spec_from_file_location(
    'trajectory_exporter', DATA_ROOT/'harness/scripts/export_trajectory_dataset.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)

result = {'schema_version': 'multipage-product-session-postrun-v1', 'status': 'error'}
try:
    batch = json.loads((RUN/'batch/batch_state.json').read_text())
    session = json.loads((RUN/'session/session.json').read_text())
    if batch['status'] != 'completed' or session['status'] != 'session_executed':
        raise RuntimeError(f"controller stopped: batch={batch['status']} session={session['status']}")
    records = [json.loads(line) for line in (RUN/'session/dataset/records.jsonl').read_text().splitlines() if line]
    counts = dict(Counter(row['task'] for row in records))
    edits = [row for row in records if row['task'] == 'text-editing']
    repairs = [row for row in records if row['task'] == 'text-repair']
    generates = [row for row in records if row['task'] == 'text-generation']
    if len(edits) != session['selection']['edit_count'] or len(generates) != 1:
        raise RuntimeError(f"incomplete exports: {counts}")
    for previous, current in zip(edits, edits[1:]):
        if previous['reference']['dst_code'] != current['instruction']['src_code']:
            raise RuntimeError('Edit source/target chain is discontinuous')
    for row in edits + repairs:
        if exporter.apply_patches(row['instruction']['src_code'], row['label_modified_files']) != row['reference']['dst_code']:
            raise RuntimeError(f"patch replay failed: {row['instance_id']}")
    final_code = edits[-1]['reference']['dst_code']
    if generates[0]['reference']['dst_code'] != final_code or generates[0]['instruction']['src_code']:
        raise RuntimeError('final Generate record is not bound to the accepted descendant')
    query = json.loads((RUN/'session/dataset/final_query.json').read_text())
    source_hash = hashlib.sha256(json.dumps(final_code, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if query['source_sha256'] != source_hash or query['state_id'] != session['current_state']['state_id']:
        raise RuntimeError('final Generate query does not match the final state')
    browser = verify_project(Path(session['current_state']['project_path']),
        json.loads((DATA_ROOT/'configs/product_session_multipage_20260911/checks.json').read_text()),
        RUN/'postflight', label='final')
    if browser['status'] != 'ok':
        raise RuntimeError('final project failed retained multi-page navigation checks')
    result.update(status='ok', edit_count=len(edits), generate_count=1,
                  natural_repair_count=len(repairs), exact_patch_replays=len(edits)+len(repairs),
                  consecutive_edit_links=max(0, len(edits)-1), retained_page_checks=len(browser['checks']),
                  final_state_id=session['current_state']['state_id'])
except Exception as exc:
    result['error'] = f'{type(exc).__name__}: {exc}'
(RUN/'postrun_validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result['status'] == 'ok' else 1)
