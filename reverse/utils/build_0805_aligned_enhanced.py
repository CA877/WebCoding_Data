"""Select whole supplement tasks and materialize a bounded 0805 enhancement."""
import argparse
import collections
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reverse.utils.build_0805_combined_training_view import TASKS, IMAGE_FIELDS, SHARD_NAME, sha256, _safe_relative_path

EDIT_TYPES = ('Async Form Validation', 'Data Table', 'Drag & Drop Interface',
              'File Upload with Progress', 'Infinite Scroll', 'Multi-step Wizard',
              'Notification Center', 'Page Transitions', 'Parallax Scrolling',
              'Particle Effects', 'Real-time Dashboard', 'Rich Text Editor',
              'Shopping Cart', 'Skeleton Loading', 'Tree View', 'User Authentication')
REPAIR_TYPES = ('Alignment', 'Color Contrast', 'Crowding', 'Loss of Interactivity',
                'Missing Attributes', 'Nesting Error', 'Occlusion', 'Overflow',
                'Semantic Error', 'Sizing Proportion', 'Text Overlap')


def normalized(value):
    return ' '.join(value.strip().casefold().replace('_', ' ').split())


def files_for(row, task):
    if task == 'text-edit':
        return row['instruction']['src_code']
    if task == 'text-repair':
        return row['instruction']
    return row['input_files']


def select(row, task):
    labels = row['task_type']
    allowed = {normalized(s) for s in (EDIT_TYPES if task.endswith('edit') else REPAIR_TYPES)}
    bad = [s for s in labels if normalized(s) not in allowed]
    n = len(labels)
    if row.get('metadata', {}).get('task_count', n) != n:
        raise ValueError('task count mismatch: ' + row['instance_id'])
    html = sum(f['path'].lower().endswith('.html') for f in files_for(row, task))
    reasons = []
    if 8 <= n <= 12:
        reasons.append('8_to_12_tasks')
    if html >= 2:
        reasons.append('at_least_2_html')
    return {'selected': bool(labels and not bad and reasons), 'reasons': reasons,
            'excluded_types': bad, 'task_count': n, 'html_count': html}


def repair_prompt(glossary, n):
    if n < 1:
        raise ValueError('empty defect count')
    return glossary + f'\nYou have only {n} issues to fix, and you can not fix more than {n} issues.'


def normalize_record(row, task, glossary):
    row = copy.deepcopy(row)
    if task.endswith('repair'):
        row['repair_instruction'] = repair_prompt(glossary, len(row['task_type']))
        if task == 'image-repair':
            row['instruction'] = row['repair_instruction']
    return row


def rows(root, task):
    with gzip.open(root/task/SHARD_NAME, 'rt') as f:
        for line in f:
            yield json.loads(line)


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def run(args):
    for key in ('base', 'supplement', 'refreshed', 'protocol', 'output'):
        setattr(args, key, getattr(args, key).resolve())
    output = args.output
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    state = {'status': 'starting', 'rows': 0, 'phase': args.mode}
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(15):
            print(json.dumps({'heartbeat': time.time(), **state}), flush=True)
    threading.Thread(target=heartbeat, daemon=True).start()
    signal.alarm(args.timeout)
    prompt_path = args.protocol if args.protocol.is_file() else args.protocol/'editing_repair/llm/mllm/prompt.py'
    glossary = runpy.run_path(str(prompt_path))['Repair_Instruction_Prompt']
    selected = {}
    summary = {'mode': args.mode, 'sources': {}, 'tasks': {}, 'taxonomy': {'edit': EDIT_TYPES, 'repair': REPAIR_TYPES},
               'selection': '(8 <= declared_task_count <= 12 OR input_html_count >= 2) AND every_type_in_whitelist',
               'glossary_source_sha256': sha256(prompt_path)}
    with (output/'selection.jsonl').open('w') as audit:
        for task in TASKS:
            if task.endswith('generate'):
                selected[task] = set()
                continue
            chosen = set()
            counter = collections.Counter()
            excluded = collections.Counter()
            for row in rows(args.supplement, task):
                state['rows'] += 1
                if state['rows'] > args.max_scan:
                    raise ValueError('max_scan reached')
                decision = select(row, task)
                counter['scanned'] += 1
                if decision['reasons']:
                    counter['scope_candidates'] += 1
                if decision['selected']:
                    chosen.add(row['instance_id'])
                    counter['selected'] += 1
                    for reason in decision['reasons']:
                        counter[reason] += 1
                    if len(decision['reasons']) == 2:
                        counter['both'] += 1
                elif decision['reasons']:
                    counter['rejected_type'] += 1
                    excluded.update(decision['excluded_types'])
                audit.write(json.dumps({'status': 'selected' if decision['selected'] else 'not_selected',
                                        'task': task, 'instance_id': row['instance_id'], **decision}, ensure_ascii=False)+'\n')
                audit.flush()
            selected[task] = chosen
            summary['tasks'][task] = {**counter, 'excluded_type_counts': dict(excluded)}
            print(json.dumps({'status': 'selection_done', 'task': task, **counter}), flush=True)
    for label, root in [('0805', args.base), ('supplement', args.supplement), ('reversed_v4', args.refreshed)]:
        idx = json.loads((root/'dataset_index.json').read_text())
        summary['sources'][label] = {'root': str(root), 'index_sha256': sha256(root/'dataset_index.json'),
                                     'tasks': idx['tasks']}
    dump(output/'selection_summary.json', summary)
    if args.mode == 'audit':
        stop.set()
        return
    if shutil.disk_usage(output).free < 20 * 1024**3:
        raise OSError('requires at least 20 GiB free')
    tasks = {}
    total = 0
    with (output/'lineage.jsonl').open('w') as lineage:
        for task in TASKS:
            state['task'] = task
            dest = output/task
            dest.mkdir()
            copied = set()
            ids = set()
            n = 0
            base_count = added_count = 0
            refreshed = {}
            if task == 'image-edit':
                refreshed = {r['instance_id']: r for r in rows(args.refreshed, task) if r['instance_id'] in selected[task]}
            with gzip.open(dest/SHARD_NAME, 'wt', compresslevel=6) as writer:
                for label, root in [('0805', args.base), ('supplement', args.supplement)]:
                    written_from_source = 0
                    for row in rows(root, task):
                        if label == 'supplement' and row['instance_id'] not in selected[task]:
                            continue
                        if args.mode == 'pilot' and written_from_source >= 1:
                            break
                        key = row['instance_id']
                        if key in ids:
                            raise ValueError('ID collision: ' + key)
                        ids.add(key)
                        source_root = root
                        if label == 'supplement' and task == 'image-edit':
                            updated = refreshed[key]
                            for field in ('input_files', 'instruction', 'response', 'task_type'):
                                if updated.get(field) != row.get(field):
                                    raise ValueError('unexpected v4 code/query change: '+key)
                            row = updated
                            source_root = args.refreshed
                        raw_digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        result = normalize_record(row, task, glossary)
                        for field in IMAGE_FIELDS:
                            for raw in result.get(field, []):
                                rel = _safe_relative_path(raw, expected_first='images')
                                source = source_root/task/str(rel)
                                target = dest/str(rel)
                                if not source.is_file():
                                    raise FileNotFoundError(source)
                                if raw in copied:
                                    if sha256(source) != sha256(target):
                                        raise ValueError('image collision: '+raw)
                                else:
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(source, target)
                                    copied.add(raw)
                        writer.write(json.dumps(result, ensure_ascii=False)+'\n')
                        lineage.write(json.dumps({'status': 'ok', 'task': task, 'instance_id': key,
                                                  'source': label, 'source_root': str(source_root),
                                                  'source_record_sha256': raw_digest,
                                                  'repair_prompt_updated': task.endswith('repair')})+'\n')
                        lineage.flush()
                        n += 1
                        total += 1
                        written_from_source += 1
                        base_count += label == '0805'
                        added_count += label == 'supplement'
                        state['written'] = total
                        if total > args.max_output:
                            raise ValueError('max_output reached')
            # Re-read serialized records to verify prompt, IDs and image closure.
            read_ids = set()
            for row in rows(output, task):
                read_ids.add(row['instance_id'])
                if task.endswith('repair'):
                    assert row['repair_instruction'] == repair_prompt(glossary, len(row['task_type']))
                    if task == 'image-repair':
                        assert row['instruction'] == row['repair_instruction']
                for field in IMAGE_FIELDS:
                    assert all((dest/p).is_file() for p in row.get(field, []))
            assert ids == read_ids
            tasks[task] = {'jsonl': f'{task}/{SHARD_NAME}', 'data_files': [f'{task}/{SHARD_NAME}'],
                           'num_samples': n, 'base_samples': base_count, 'added_samples': added_count,
                           'image_files': len(copied), 'image_root': f'{task}/images' if copied else None,
                           'sha256': sha256(dest/SHARD_NAME)}
            print(json.dumps({'status': 'task_done', 'task': task, **tasks[task]}), flush=True)
    index = {'name': output.name, 'schema_version': 'webcoding-sft-v2-aligned-enhanced-v1',
             'materialization': 'full_copy_no_links', 'tasks': tasks,
             'model_input_contract': {
                 'text-repair': {'text_field': 'repair_instruction', 'code_field': 'instruction', 'hidden_metadata_fields': ['task_type', 'metadata']},
                 'image-repair': {'text_field': 'repair_instruction', 'code_field': 'input_files', 'image_fields': ['src_screenshot', 'dst_screenshot'], 'hidden_metadata_fields': ['task_type', 'metadata']},
                 'repair_prompt': 'Complete official Repair_Instruction_Prompt including XML search_replace output requirements + N; per-instance labels remain hidden; stored JSON patches are preserved.'}}
    dump(output/'dataset_index.json', index)
    dump(output/'validation.json', {'status': 'packaging_pass', 'total_samples': total,
                                    'scope': 'whole-task whitelist selection, IDs, prompt serialization, image closure',
                                    'browser_quality': 'inherits selected source records; no new browser assessment'})
    (output/'README.md').write_text('# 0805 aligned enhancement\n\n0805 base plus the union of supplement 8–12-task and >=2-HTML records whose every type is in the official whitelist.\n\nRepair: read repair_instruction (11 public definitions + N), code and relevant images; task_type/metadata are hidden. Existing response schema is preserved.\n\nSee selection_summary.json, lineage.jsonl and dataset_index.json.\n')
    stop.set()
    signal.alarm(0)
    print(json.dumps({'status': 'complete', 'total_samples': total, 'output': str(output)}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['audit', 'pilot', 'build'], required=True)
    for key in ('base', 'supplement', 'refreshed', 'protocol', 'output'):
        p.add_argument('--'+key, type=Path, required=True)
    p.add_argument('--max-scan', type=int, default=20000)
    p.add_argument('--max-output', type=int, default=40000)
    p.add_argument('--timeout', type=int, default=900)
    run(p.parse_args())
