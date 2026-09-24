"""Recoverably remove obsolete Image Edit from 0921 without stopping generation."""
import argparse
import copy
import fcntl
import gzip
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reverse import merge_0905_historical_text_edit as io

SHARD='image-edit/train-00000-of-00001.jsonl.gz'


def strings(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,list):
        for item in value:yield from strings(item)
    elif isinstance(value,dict):
        for item in value.values():yield from strings(item)


def audit(release):
    if release.name!='0921' or release.is_symlink():
        raise ValueError('only physical 0921 is in scope')
    target=release/'image-edit'
    index=io.read(release/'dataset_index.json')
    manifest=io.read(release/'manifest.json')
    if index['name']!='0921' or target.is_symlink():
        raise ValueError('wrong release or linked target')
    digest=io.sha(release/SHARD)
    if digest!=index['tasks']['image-edit']['sha256'] or digest!=manifest[SHARD]['sha256']:
        raise ValueError('image-edit shard hash mismatch')
    with gzip.open(release/SHARD,'rt') as stream:
        count=sum(1 for line in stream if line.strip())
    if count!=index['tasks']['image-edit']['num_samples'] or count>5000:
        raise ValueError('unexpected removal count')
    files=list(p for p in target.rglob('*') if p.is_file())
    if len(files)>15000 or any(p.is_symlink() for p in target.rglob('*')):
        raise ValueError('unbounded or symlinked removal target')
    for task,entry in index['tasks'].items():
        if task=='image-edit':continue
        for name in entry.get('data_files',[]):
            with gzip.open(release/name,'rt') as stream:
                for line in stream:
                    for value in strings(json.loads(line)):
                        if len(value)>4096 or '\n' in value:continue
                        candidates=[]
                        if value.startswith('/'):candidates=[Path(value)]
                        elif value.startswith(('../','image-edit/')):
                            candidates=[release/task/value,release/value]
                        if any(p.resolve().is_relative_to(target.resolve()) for p in candidates):
                            raise ValueError(f'{task} references image-edit: {value}')
    return dict(records=count,files=len(files),images=len(files)-1,bytes=sum(p.stat().st_size for p in files),
                shard_sha256=digest)


def run(release,control,apply=False):
    with (release/'.0921-write.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        report=audit(release)
        if not apply:
            print(json.dumps(dict(status='dry_run_passed',**report)),flush=True)
            return report
        if report['records']==0 or control.exists():
            raise ValueError('already empty or removal control exists')
        control.mkdir(parents=True)
        before={name:io.sha(release/name) for name in ('dataset_index.json','manifest.json','README.md')}
        for name in before:shutil.copy2(release/name,control/name)
        index=io.read(release/'dataset_index.json');manifest=io.read(release/'manifest.json')
        preserved={k:v['sha256'] for k,v in index['tasks'].items() if k!='image-edit'}
        stage=control/'staged';(stage/'image-edit').mkdir(parents=True)
        with gzip.open(stage/SHARD,'wb'):pass
        entry=index['tasks']['image-edit']
        entry.clear()
        entry.update(jsonl=SHARD,data_files=[SHARD],num_samples=0,image_files=0,image_root=None,
                     sha256=io.sha(stage/SHARD),compressed_gib=0,derived_from='text-edit',
                     status='awaiting_regeneration_from_current_text_edit')
        index.setdefault('notes',[]).append('0921: obsolete Image Edit removed; regenerate only from current Text Edit code/query/GT and canonical source screenshots.')
        io.write(stage/'dataset_index.json',index)
        readme=(release/'README.md').read_text()
        table='\n'.join(f'| {k} | {v["num_samples"]} |' for k,v in index['tasks'].items())
        total=sum(v['num_samples'] for v in index['tasks'].values())
        (stage/'README.md').write_text(f'# 0921\n\n| Task | Records |\n|---|---:|\n{table}\n\nTotal: {total:,}. Obsolete Image Edit has been removed. Image Edit must derive from the current Text Edit source code, query and GT, with matching canonical source screenshots. Text Edit query generation continues; old GT is absent. ModelScope is unchanged.\n')
        manifest={k:v for k,v in manifest.items() if not k.startswith('image-edit/')}
        for name in (SHARD,'dataset_index.json','README.md'):
            manifest[name]=dict(size=(stage/name).stat().st_size,sha256=io.sha(stage/name))
        io.write(stage/'manifest.json',manifest)
        archive=control/'image-edit'
        (release/'image-edit').rename(archive)
        try:
            (stage/'image-edit').rename(release/'image-edit')
            for name in ('dataset_index.json','README.md','manifest.json'):
                os.replace(stage/name,release/name)
            after=io.read(release/'dataset_index.json')
            if any(after['tasks'][k]['sha256']!=v for k,v in preserved.items()):
                raise ValueError('unrelated task metadata changed')
            if io.sha(release/SHARD)!=entry['sha256'] or io.sha(archive/'train-00000-of-00001.jsonl.gz')!=report['shard_sha256']:
                raise ValueError('post-removal hash mismatch')
        except BaseException:
            empty=release/SHARD
            if empty.exists():empty.unlink()
            if (release/'image-edit').exists():(release/'image-edit').rmdir()
            archive.rename(release/'image-edit')
            for name in before:shutil.copy2(control/name,release/name)
            raise
        report.update(status='removed_from_0921',archive=str(archive),total=total,remaining_image_edit=0,
                      other_task_hashes=preserved)
        io.write(control/'result.json',report)
        print(json.dumps(report),flush=True)
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--control',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    run(args.release,args.control,args.apply)
