"""Stage and commit the existing 8–12-task Text Edit rows; never generate data."""
import argparse
import collections
import copy
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reverse.web_coding_demo.synthetic.search_replace import apply_search_replace

SHARD = 'text-edit/train-00000-of-00001.jsonl.gz'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def prepare(release, source, baseline, output, limit):
    output.mkdir(parents=True, exist_ok=False)
    index = read(release/'dataset_index.json')
    manifest = read(baseline)
    before = {name: sha(release/name) for name in (SHARD, 'dataset_index.json', 'README.md')}
    if before[SHARD] != manifest[SHARD]['sha256'] or before[SHARD] != index['tasks']['text-edit']['sha256']:
        raise ValueError('target shard does not match the selected release manifest/index')
    with gzip.open(release/SHARD, 'rt') as stream:
        old = [json.loads(line) for line in stream]
    if len(old) != index['tasks']['text-edit']['num_samples']:
        raise ValueError('target count mismatch')
    ids = {row['instance_id'] for row in old}
    if len(ids) != len(old):
        raise ValueError('target IDs are not unique')
    additions, origins, failures, seen = [], [], [], set()
    for path in sorted(source.glob('*/text-edit.v2.jsonl')):
        for lineno, line in enumerate(path.open(), 1):
            row = json.loads(line)
            types = row.get('task_type')
            if not isinstance(types, list) or not 8 <= len(types) <= 12:
                continue
            if len(additions)+len(failures) >= limit:
                break
            identity = row['instance_id']
            if identity in ids or identity in seen:
                raise ValueError(f'duplicate/colliding ID: {identity}')
            seen.add(identity)
            try:
                if set(row) != set(old[0]) or row['task'] != 'text-editing':
                    raise ValueError('incompatible top-level schema')
                descriptions = row['instruction']['description']
                if len(descriptions) != len(types) or collections.Counter(d['task_type'] for d in descriptions) != collections.Counter(types):
                    raise ValueError('instruction/type mismatch')
                if not row['response'] or any(not d.get('description') for d in descriptions):
                    raise ValueError('empty instruction or GT')
                changed, errors = apply_search_replace(row['instruction']['src_code'], row['response'])
                if errors or changed == row['instruction']['src_code']:
                    raise ValueError('patch errors or unchanged result')
            except (ValueError, KeyError, TypeError) as exc:
                failures.append(dict(instance_id=identity, source=str(path), line=lineno, error=str(exc)))
                continue
            additions.append(row)
            origins.append(dict(instance_id=identity, source=str(path), line=lineno,
                                row_sha256=hashlib.sha256(line.encode()).hexdigest()))
    report = dict(release=str(release), source=str(source), before_hashes=before,
                  before_count=len(old), selected=len(additions)+len(failures),
                  added=len(additions), task_counts=dict(collections.Counter(len(r['task_type']) for r in additions)),
                  failures=failures, origins=origins, status='validation_failed' if failures else 'staged')
    write(output/'result.json', report)
    if failures or not additions:
        print(json.dumps({k:v for k,v in report.items() if k!='origins'}, ensure_ascii=False), flush=True)
        return 2
    stage = output/'staged'
    (stage/'text-edit').mkdir(parents=True)
    # Preserve the complete decompressed old shard verbatim, appending only new rows.
    with gzip.open(release/SHARD, 'rb') as original, gzip.open(stage/SHARD, 'wb') as merged:
        shutil.copyfileobj(original, merged)
        for row in additions:
            merged.write((json.dumps(row, ensure_ascii=False)+'\n').encode())
    with gzip.open(stage/SHARD, 'rt') as stream:
        rows = [json.loads(line) for line in stream]
    if rows != old+additions:
        raise ValueError('staged rows changed')
    entry = index['tasks']['text-edit']
    entry.update(num_samples=len(rows), added_samples=entry.get('added_samples',0)+len(additions),
                 sha256=sha(stage/SHARD), compressed_gib=round((stage/SHARD).stat().st_size/1024**3,6))
    index.setdefault('notes', []).append(f'historical_text_edit_8to12_20260921: appended {len(additions)} existing rows; original instructions and GT preserved.')
    write(stage/'dataset_index.json', index)
    total = sum(task['num_samples'] for task in index['tasks'].values())
    table = '\n'.join(f'| {name} | {task["num_samples"]} |' for name,task in index['tasks'].items())
    (stage/'README.md').write_text(f'# 0905 — historical Text Edit update 2026-09-21\n\nCurrent total: **{total:,} records**. Added {len(additions)} existing 8–12-subtask Text Edit records. Original rows, instructions and GT are preserved.\n\n| Task | Records |\n|---|---:|\n{table}\n\nValidation: unique IDs, matching schema and task counts, exact patch replay, original-row preservation and shard hashes. This local update is not yet uploaded to ModelScope.\n\n## Previous release documentation\n\n'+(release/'README.md').read_text())
    for name in (SHARD,'dataset_index.json','README.md'):
        manifest[name] = dict(size=(stage/name).stat().st_size, sha256=sha(stage/name))
    write(stage/'manifest.json', manifest)
    report.update(after_count=len(rows), total=total, after_hashes={name:sha(stage/name) for name in (SHARD,'dataset_index.json','README.md','manifest.json')})
    write(output/'result.json', report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('origins','before_hashes','after_hashes')},ensure_ascii=False),flush=True)
    return 0


def commit(output):
    report = read(output/'result.json')
    if report['status'] != 'staged' or report['failures']:
        raise ValueError('no valid staged merge')
    release = Path(report['release'])
    with (release.parent/f'.{release.name}.historical-text-edit-merge.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name, expected in report['before_hashes'].items():
            if sha(release/name) != expected:
                raise ValueError('release changed during staging')
        for name, expected in report['after_hashes'].items():
            if sha(output/'staged'/name) != expected:
                raise ValueError('staged file changed')
        backup = output/'backup'
        backup.mkdir(exist_ok=False)
        existing = []
        names = sorted(report['after_hashes'], key=lambda name: (2 if name in ('dataset_index.json','README.md','manifest.json') else 0 if '/images/' in name else 1, name))
        for name in names:
            if (release/name).exists():
                (backup/name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(release/name, backup/name)
                existing.append(name)
        replaced = []
        try:
            for name in names:
                target = release/name
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name+'.historical-merge.tmp')
                shutil.copy2(output/'staged'/name, temp)
                os.replace(temp, target)
                replaced.append(name)
            for name, expected in report['after_hashes'].items():
                if sha(release/name) != expected:
                    raise ValueError('post-commit hash mismatch')
        except BaseException:
            for name in reversed(replaced):
                if name in existing:
                    shutil.copy2(backup/name, release/name)
                else:
                    (release/name).unlink()
            raise
        report.update(status='merged_local_verified', backup=str(backup), uploaded=False)
        write(output/'result.json', report)
        print(json.dumps(dict(status=report['status'], added=report['added'], text_edit=report['after_count'],total=report['total'],backup=str(backup))),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare','commit'])
    parser.add_argument('--release',type=Path)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--baseline-manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=580)
    args = parser.parse_args()
    if args.action == 'prepare':
        if not all((args.release,args.source,args.baseline_manifest)) or not 1<=args.limit<=580:
            parser.error('prepare requires release/source/baseline-manifest and limit 1..580')
        sys.exit(prepare(args.release,args.source,args.baseline_manifest,args.output,args.limit))
    commit(args.output)
