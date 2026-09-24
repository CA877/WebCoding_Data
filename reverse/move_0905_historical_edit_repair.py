"""Move the scoped historical 8–12-task records into the physical 0905 release.

prepare is isolated; commit uses backed-up, hash-checked replacement; cleanup
removes only verified migrated source records and unshared local screenshots.
"""
import argparse
import collections
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reverse import merge_0905_historical_text_edit as base
from reverse.web_coding_demo.synthetic.search_replace import apply_search_replace

TASKS = ('text-edit', 'image-edit', 'text-repair', 'image-repair')
FIELDS = ('input_images', 'src_screenshot', 'dst_screenshot', 'target_reference_images')
EXPECTED = {'text-edit':580, 'image-edit':580, 'text-repair':1289, 'image-repair':1127}
SHARD = 'train-00000-of-00001.jsonl.gz'


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def selected(source, task):
    seen = set()
    for path in sorted((source/task.split('-')[1]).glob(f'*/{task}.v2.jsonl')):
        for row in rows(path):
            if not 8 <= len(row.get('task_type', [])) <= 12:
                continue
            if row['instance_id'] in seen:
                raise ValueError('duplicate source ID: '+row['instance_id'])
            seen.add(row['instance_id'])
            yield path, row


def template(release):
    row = next(rows(release/'text-repair'/SHARD))
    suffix = f'\nYou have only {len(row["task_type"])} issues to fix, and you can not fix more than {len(row["task_type"])} issues.'
    if not row['repair_instruction'].endswith(suffix):
        raise ValueError('unknown official repair prompt template')
    return row['repair_instruction'][:-len(suffix)]


def convert(row, task, glossary, image_map):
    result = copy.deepcopy(row)
    if task.endswith('repair'):
        n = len(row['task_type'])
        result['repair_instruction'] = glossary+f'\nYou have only {n} issues to fix, and you can not fix more than {n} issues.'
        if task == 'image-repair':
            result['instruction'] = result['repair_instruction']
    for field in FIELDS:
        if field in result:
            result[field] = [image_map[(task, path)]['relative'] for path in result[field]]
    return result


def prepare(release, source, output, limit):
    output.mkdir(parents=True, exist_ok=False)
    stage = output/'staged'
    stage.mkdir()
    index = base.read(release/'dataset_index.json')
    manifest = base.read(release/'manifest.json')
    glossary = template(release)
    before = {name:base.sha(release/name) for name in ('dataset_index.json','README.md','manifest.json')}
    image_map, image_targets, origins, failures, counts = {}, {}, [], [], {}
    added = 0
    for task in TASKS:
        name = f'{task}/{SHARD}'
        before[name] = base.sha(release/name)
        if before[name] != index['tasks'][task]['sha256'] or before[name] != manifest[name]['sha256']:
            raise ValueError('release hash mismatch: '+task)
        old = list(rows(release/name))
        old_map = {r['instance_id']:r for r in old}
        if len(old_map) != len(old) or len(old) != index['tasks'][task]['num_samples']:
            raise ValueError('invalid target counts/IDs')
        appended, scanned = [], 0
        for path, row in selected(source, task):
            if scanned >= limit:
                break
            scanned += 1
            signal.alarm(120)
            try:
                code = (row['instruction']['src_code'] if task=='text-edit' else
                        row['instruction'] if task=='text-repair' else row['input_files'])
                changed, errors = apply_search_replace(code, row['response'])
                if errors or changed == code:
                    raise ValueError('patch replay failed or unchanged')
                if task.startswith('image') and not row.get('input_images'):
                    raise ValueError('missing input images')
                if row.get('patches', row['response']) != row['response']:
                    raise ValueError('patches/response mismatch')
                for field in FIELDS:
                    for value in row.get(field, []):
                        key = (task, value)
                        if key in image_map:
                            continue
                        image = Path(value)
                        if not image.is_absolute() or not image.is_file():
                            raise ValueError('missing/ambiguous image: '+value)
                        digest = base.sha(image)
                        relative = f'images/historical_8to12_20260921/{digest}{image.suffix.lower()}'
                        target = f'{task}/{relative}'
                        info = dict(source=value,task=task,relative=relative,target=target,
                                    sha256=digest,size=image.stat().st_size)
                        if len(image_targets)>=20000 or sum(v['size'] for v in image_targets.values())>20*1024**3:
                            raise ValueError('image inventory exceeds migration bounds')
                        if target not in image_targets:
                            (stage/target).parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(image, stage/target)
                            if base.sha(stage/target)!=digest:
                                raise ValueError('image copy hash mismatch')
                        image_targets[target] = info
                        image_map[key] = info
                normalized = convert(row,task,glossary,image_map)
                if row['instance_id'] in old_map:
                    if old_map[row['instance_id']] != normalized:
                        raise ValueError('conflicting existing ID: '+row['instance_id'])
                else:
                    appended.append(normalized)
                origins.append(dict(task=task,instance_id=row['instance_id'],source=str(path),
                                    source_row_hash=base.digest(row) if hasattr(base,'digest') else hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                failures.append(dict(task=task,instance_id=row['instance_id'],error=str(exc)))
            finally:
                signal.alarm(0)
            if scanned % 50 == 0:
                print(json.dumps(dict(task=task,checked=scanned,errors=len(failures))),flush=True)
        if limit>=1289 and scanned!=EXPECTED[task]:
            raise ValueError('source count changed: '+task)
        counts[task] = dict(selected=scanned,existing=scanned-len(appended),added=len(appended),after=len(old)+len(appended))
        if appended:
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(release/name,'rb') as src, gzip.open(target,'wb') as dst:
                shutil.copyfileobj(src,dst)
                for row in appended:
                    dst.write((json.dumps(row,ensure_ascii=False)+'\n').encode())
            if list(rows(target)) != old+appended:
                raise ValueError('row preservation failed')
            entry = index['tasks'][task]
            entry.update(num_samples=len(old)+len(appended),added_samples=entry.get('added_samples',0)+len(appended),
                         sha256=base.sha(target),compressed_gib=round(target.stat().st_size/1024**3,6))
            if task.startswith('image'):
                entry['image_files'] += sum(v['task']==task for v in image_targets.values())
            if task == 'image-repair':
                modes=entry.setdefault('image_input_modes',{})
                for row in appended:
                    mode='current_and_target' if any(p in row.get('input_images',[]) for p in row.get('dst_screenshot',[])) else 'current_only'
                    modes[mode]=modes.get(mode,0)+1
            added += len(appended)
    report=dict(release=str(release),source=str(source),status='validation_failed' if failures else 'staged',
                before_hashes=before,counts=counts,failures=failures,origins=origins,images=list(image_map.values()),
                added=added,after_count=index['tasks']['text-edit']['num_samples'],
                total=sum(v['num_samples'] for v in index['tasks'].values()))
    base.write(output/'result.json',report)
    if failures:
        print(json.dumps(dict(failures=failures,counts=counts),ensure_ascii=False),flush=True)
        return 2
    index.setdefault('notes',[]).append('historical_8to12_move_20260921: existing Edit/Repair text and image records consolidated; code/GT preserved; repair public prompt uses current release template.')
    base.write(stage/'dataset_index.json',index)
    table='\n'.join(f'| {k} | {v["num_samples"]} |' for k,v in index['tasks'].items())
    (stage/'README.md').write_text(f'# 0905 — historical 8–12-subtask consolidation 2026-09-21\n\nCurrent total: **{report["total"]:,} records**. Existing historical Text/Image Edit and Repair records are consolidated into this release. Original code and GT are preserved. Repair public instructions use the existing release template with the issue count; task labels and metadata remain hidden from model inputs. Image roles/order are preserved and all referenced screenshots are physical release files.\n\n| Task | Records |\n|---|---:|\n{table}\n\nValidation: exact patch replay, unique IDs, original-row preservation, image hashes and release manifest. Local update; ModelScope is unchanged.\n\n## Prior release documentation\n\n'+(release/'README.md').read_text())
    for path in stage.rglob('*'):
        if path.is_file():
            manifest[str(path.relative_to(stage))]=dict(size=path.stat().st_size,sha256=base.sha(path))
    base.write(stage/'manifest.json',manifest)
    report['after_hashes']={str(p.relative_to(stage)):base.sha(p) for p in stage.rglob('*') if p.is_file()}
    base.write(output/'result.json',report)
    print(json.dumps(dict(status='staged',counts=counts,unique_images=len(image_targets),total=report['total'])),flush=True)
    return 0


def strings(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,list):
        for item in value:
            yield from strings(item)
    elif isinstance(value,dict):
        for item in value.values():
            yield from strings(item)


def cleanup(output):
    report=base.read(output/'result.json')
    if report['status']!='merged_local_verified':
        raise ValueError('cleanup requires committed migration')
    source, release = Path(report['source']), Path(report['release'])
    if source.name!='new_gt_webcompass_task_count_supplements_20260822_v1':
        raise ValueError('unexpected cleanup scope')
    if (output/'cleanup.json').exists():
        raise ValueError('cleanup already planned; inspect receipt before resuming')
    for name,digest in report['after_hashes'].items():
        if base.sha(release/name)!=digest:
            raise ValueError('release changed before cleanup')
    image_map={(x['task'],x['source']):x for x in report['images']}
    glossary=template(release)
    moved={}
    for task in TASKS:
        targets={r['instance_id']:r for r in rows(release/task/SHARD)}
        selected_rows=list(selected(source,task))
        if len(selected_rows)!=EXPECTED[task]:
            raise ValueError('source count changed before cleanup')
        for _,row in selected_rows:
            if targets.get(row['instance_id'])!=convert(row,task,glossary,image_map):
                raise ValueError('source row not fully preserved: '+row['instance_id'])
        moved[task]={r['instance_id'] for _,r in selected_rows}
    actions, protected = [], set()
    for family in ('edit','repair'):
        for path in sorted((source/family).glob('*/*.jsonl')):
            if path.name not in (f'text-{family}.v2.jsonl',f'image-{family}.v2.jsonl','records.jsonl'):
                raise ValueError('unhandled source JSONL: '+str(path))
            original=path.read_bytes().splitlines(keepends=True)
            kept, removed, positions = [], [], []
            for i,line in enumerate(original):
                row=json.loads(line)
                task = f'text-{family}' if path.name=='records.jsonl' else path.name.split('.v2')[0]
                remove = row.get('instance_id') in moved[task] and 8<=len(row.get('task_type',[]))<=12
                if path.name=='records.jsonl':
                    remove = remove and row.get('status')=='ok'
                if remove:
                    removed.append(line); positions.append(i)
                else:
                    kept.append(line); protected.update(strings(row))
            if removed:
                if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
                    raise ValueError('source shard escapes cleanup scope')
                actions.append(dict(path=str(path),relative=str(path.relative_to(source)),
                    before=base.sha(path),after=hashlib.sha256(b''.join(kept)).hexdigest(),
                    positions=positions,kept=kept,removed=removed))
    images={x['source']:x for x in report['images'] if Path(x['source']).is_relative_to(source)}
    delete_images=[]
    for name,info in images.items():
        if name not in protected:
            if Path(name).is_symlink() or not Path(name).resolve().is_relative_to(source.resolve()) or base.sha(Path(name))!=info['sha256']:
                raise ValueError('source image changed or is a symlink')
            delete_images.append(info)
    archive=output/'source-rollback.tar.gz'
    with tarfile.open(archive,'x:gz',compresslevel=1) as tar:
        for action in actions:
            data=b''.join(action['removed'])
            member=tarfile.TarInfo('removed/'+action['relative']);member.size=len(data)
            tar.addfile(member,io.BytesIO(data))
        for info in delete_images:
            tar.add(info['source'],arcname='images/'+str(Path(info['source']).relative_to(source)),recursive=False)
    with tarfile.open(archive,'r:gz') as tar:
        for action in actions:
            if tar.extractfile('removed/'+action['relative']).read()!=b''.join(action['removed']):
                raise ValueError('recovery archive mismatch')
        for info in delete_images:
            content=tar.extractfile('images/'+str(Path(info['source']).relative_to(source))).read()
            if hashlib.sha256(content).hexdigest()!=info['sha256']:
                raise ValueError('recovery image mismatch')
    receipt=dict(status='verified_ready',source=str(source),archive=str(archive),archive_sha256=base.sha(archive),
        files=[{k:v for k,v in a.items() if k not in ('kept','removed')} for a in actions],
        removed_rows=sum(len(a['removed']) for a in actions),deleted_images=delete_images,completed=[])
    base.write(output/'cleanup.json',receipt)
    for action in actions:
        path=Path(action['path'])
        if base.sha(path)!=action['before']:
            raise ValueError('source file changed before deletion')
        if action['kept']:
            temporary=path.with_name(path.name+'.move.tmp')
            temporary.write_bytes(b''.join(action['kept']))
            os.replace(temporary,path)
        else:
            path.unlink()
        receipt['completed'].append(str(path))
        base.write(output/'cleanup.json',receipt)
    for info in delete_images:
        path=Path(info['source'])
        if base.sha(path)!=info['sha256']:
            raise ValueError('image changed before deletion')
        path.unlink()
    # Staged release copies are redundant after commit; backups remain centralized.
    for name,digest in report['after_hashes'].items():
        path=output/'staged'/name
        if path.is_file() and base.sha(path)==digest:
            path.unlink()
    remaining={task:len(list(selected(source,task))) for task in TASKS}
    if any(remaining.values()):
        raise ValueError('migration source still has selected rows')
    receipt.update(status='source_cleaned',remaining_8to12=remaining)
    base.write(output/'cleanup.json',receipt)
    print(json.dumps(dict(status=receipt['status'],removed_rows=receipt['removed_rows'],
                         deleted_images=len(delete_images),remaining=remaining,archive=str(archive))),flush=True)


def prune_staging(output):
    """Remove only hash-identified transient staging files from this migration."""
    report=base.read(output/'result.json')
    if base.read(output/'cleanup.json')['status']!='source_cleaned':
        raise ValueError('finish migration before pruning staging')
    removed=[]
    for name in ('0905_historical_text_edit_8to12_merge_smoke_20260921',
                 '0905_historical_text_edit_8to12_merge_20260921',
                 '0905_historical_edit_repair_move_smoke_20260921'):
        root=output.parent/name
        if not (root/'result.json').exists():
            continue
        prior=base.read(root/'result.json')
        if prior['release']!=report['release']:
            raise ValueError('staging belongs to another release')
        for relative,digest in prior.get('after_hashes',{}).items():
            path=root/'staged'/relative
            if path.is_file():
                if path.is_symlink() or not path.resolve().is_relative_to((root/'staged').resolve()) or base.sha(path)!=digest:
                    raise ValueError('unexpected staging file')
                path.unlink()
                removed.append(str(path))
    base.write(output/'staging_cleanup.json',dict(removed=removed))
    print(json.dumps(dict(pruned_staging_files=len(removed))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','commit','cleanup','prune-staging'])
    parser.add_argument('--release',type=Path)
    parser.add_argument('--source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=1289)
    args=parser.parse_args()
    if args.action=='prepare':
        if not args.release or not args.source or not 1<=args.limit<=1289:
            parser.error('prepare requires source/release and limit 1..1289')
        sys.exit(prepare(args.release,args.source,args.output,args.limit))
    elif args.action=='commit':
        base.commit(args.output)
    elif args.action=='cleanup':
        cleanup(args.output)
    else:
        prune_staging(args.output)
