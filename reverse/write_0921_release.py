"""Materialize current instruction runs directly into the canonical 0921 release."""
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
import signal
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reverse.edit.query import regenerate as generator

SHARD='text-edit/train-00000-of-00001.jsonl.gz'


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()


def read_rows(path):
    with gzip.open(path,'rt') as stream:
        return [json.loads(line) for line in stream]


def load_jobs(runs):
    jobs=[]; seen=set()
    for root in runs:
        plan=generator.read_json(root/'plan.json')
        if generator.digest(dict(config=plan['config'],jobs=plan['jobs']))!=plan['fingerprint']:
            raise ValueError('run plan fingerprint mismatch')
        for job in plan['jobs']:
            case=generator.read_json(root/'cases'/f'{job["job_id"]}.json')
            if generator.digest(case)!=job['case_sha256'] or case['instance_id'] in seen:
                raise ValueError('case changed or duplicate output ID')
            if not 4<=len(case['task_types'])<=12:
                raise ValueError('unexpected task count')
            seen.add(case['instance_id'])
            jobs.append((root,job,case))
    if not jobs or len(jobs)>4000:
        raise ValueError('expected 1..4000 scoped instruction cases')
    return jobs


def build_rows(original,jobs,prototypes=()):
    source={r['instance_id']:r for r in [*original,*prototypes]}
    output=[]; counts=dict(query_ready=0,awaiting_query=0,query_failed=0)
    for root,job,case in jobs:
        prototype=case.get('source_record_template') or source.get(case['instance_id'],source.get(case.get('source_instance_id')))
        if prototype is None:
            raise ValueError('missing source metadata: '+case['instance_id'])
        row=copy.deepcopy(prototype)
        row['instance_id']=case['instance_id']
        row['task_type']=case['task_types']
        row['instruction']=dict(src_code=case['source_code'],description=[])
        row.pop('response',None); row.pop('patches',None)
        metadata=row.setdefault('metadata',{})
        for key in ('patch_count','patch_count_by_task'):
            metadata.pop(key,None)
        metadata.update(task_count=len(case['task_types']),gt_status='not_generated')
        result_path=root/'jobs'/job['job_id']/'result.json'
        state='awaiting_query'
        if result_path.exists():
            result=generator.read_json(result_path)
            if result.get('status')=='ok':
                descriptions=result['descriptions']
                # Reuse the producer's full output schema/type validation.
                generator.parse_output('<description>'+json.dumps(descriptions)+'</description>',case['task_types'])
                row['instruction']['description']=descriptions
                state='query_ready'
            else:
                state='query_failed'
        metadata.update(instruction_status=state,instruction_job_id=job['job_id'])
        counts[state]+=1
        output.append(row)
    return output,counts


def html_count(row):
    return sum(str(item.get('path','')).lower().endswith(('.html','.htm'))
               for item in (row.get('instruction') or {}).get('src_code',[])
               if isinstance(item,dict))


def stage(source,output,jobs,prototype_rows=(),preserve_existing=False):
    original=read_rows(source/SHARD)
    generated,counts=build_rows(original,jobs,prototype_rows)
    if preserve_existing:
        original_ids={row['instance_id'] for row in original}
        generated_ids={row['instance_id'] for row in generated}
        if len(original_ids)!=len(original) or len(generated_ids)!=len(generated):
            raise ValueError('duplicate instance ID in existing or generated rows')
        overlap=original_ids & generated_ids
        if overlap:
            raise ValueError('generated rows overlap existing release IDs')
        rows=[*copy.deepcopy(original),*generated]
        counts=dict(collections.Counter(
            (row.get('metadata') or {}).get('instruction_status','missing') for row in rows
        ))
    else:
        rows=generated
    output.mkdir(parents=True,exist_ok=True)
    shard=output/SHARD
    shard.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(shard,'wt',compresslevel=1,encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    if read_rows(shard)!=rows:
        raise ValueError('formal output round-trip failed')
    index=generator.read_json(source/'dataset_index.json')
    index.update(name='0921',status='in_progress',canonical_write_target='0921',parent_version='0905')
    entry=index['tasks']['text-edit']
    for key in ('base_samples','added_samples'):
        entry.pop(key,None)
    physical_counts=dict(single_html=sum(html_count(row)==1 for row in rows),
                         multi_html=sum(html_count(row)>=2 for row in rows))
    entry.update(num_samples=len(rows),sha256=sha(shard),compressed_gib=round(shard.stat().st_size/1024**3,6),
                 gt_records=0,instruction_status_counts=counts,
                 physical_html_counts=physical_counts,
                 record_state='query_ready_gt_pending' if counts=={'query_ready':len(rows)} else 'query_only_generation_in_progress')
    optimization=dict(runs=[str(p) for p in dict.fromkeys(r for r,_,_ in jobs)],
        exclude_1_to_3=True,old_gt_retained=False,preserved_existing=len(original) if preserve_existing else 0,
        newly_generated=len(generated),**counts)
    if entry.get('removed_declared_mp_single_html') is not None:
        optimization['removed_declared_mp_single_html']=entry['removed_declared_mp_single_html']
    index['current_optimization']=dict(text_edit=optimization)
    generator.write_json(output/'dataset_index.json',index)
    total=sum(t['num_samples'] for t in index['tasks'].values())
    table='\n'.join(f'| {k} | {v["num_samples"]} |' for k,v in index['tasks'].items())
    (output/'README.md').write_text(f'# 0921\n\nCanonical working dataset for this optimization round. All new optimization outputs belong here.\n\n| Task | Records |\n|---|---:|\n{table}\n\nTotal: {total:,}. Text Edit excludes 1–3-subtask rows and contains no old GT. Text Edit rows carry `metadata.instruction_status`: `query_ready`, `awaiting_query`, or `query_failed`; pending/failed rows have an empty description list. Only query-ready rows may be used for subsequent GT generation. This Text Edit shard is not a completed SFT input/GT dataset. Other task shards are preserved as recorded in the index. Image Edit must derive from the current Text Edit code/query/GT and matching canonical source screenshots; obsolete Image Edit records must not be retained alongside regenerated Text Edit.\n\nRead `dataset_index.json` for current counts and `manifest.json` for hashes. During updates, obey `.0921-write.lock` or retry when index/shard hashes differ. ModelScope 0905 remains unchanged; 0921 is not uploaded.\n')
    manifest=generator.read_json(source/'manifest.json')
    for name in (SHARD,'dataset_index.json','README.md'):
        manifest[name]=dict(size=(output/name).stat().st_size,sha256=sha(output/name))
    generator.write_json(output/'manifest.json',manifest)
    return dict(total=total,text_edit=len(rows),preserved_existing=len(original) if preserve_existing else 0,
                newly_generated=len(generated),physical_html_counts=physical_counts,**counts)


def install(staged,release):
    for name in (SHARD,'dataset_index.json','README.md','manifest.json'):
        target=release/name
        temporary=target.with_name(target.name+'.0921.tmp')
        shutil.copy2(staged/name,temporary)
        os.replace(temporary,target)


def initialize(source,release,runs,control):
    if source.is_symlink() or release.exists() or control.exists():
        raise ValueError('initialize requires the original physical directory and new target/control paths')
    if source.parent!=release.parent:
        raise ValueError('rename must remain in the same release root')
    control.mkdir(parents=True)
    jobs=load_jobs(runs)
    counts=stage(source,control/'staged',jobs)
    # Isolated real-data staging precedes any modification of the formal release.
    for name in (SHARD,'dataset_index.json','README.md','manifest.json'):
        target=control/'backup'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,target)
    source.rename(release)
    try:
        source.symlink_to(release,target_is_directory=True)
        install(control/'staged',release)
    except BaseException:
        for name in (SHARD,'dataset_index.json','README.md','manifest.json'):
            shutil.copy2(control/'backup'/name,release/name)
        if source.is_symlink():source.unlink()
        release.rename(source)
        raise
    for name in (SHARD,'dataset_index.json','README.md','manifest.json'):
        if sha(release/name)!=sha(control/'staged'/name):
            raise ValueError('post-install hash mismatch')
    generator.write_json(control/'config.json',dict(release=str(release),compatibility_alias=str(source),runs=[str(p) for p in runs]))
    generator.write_json(control/'state.json',dict(status='initialized',time=time.time(),**counts))
    print(json.dumps(counts),flush=True)


def watch(control,once=False):
    config=generator.read_json(control/'config.json')
    release=Path(config['release']); runs=[Path(p) for p in config['runs']]
    jobs=load_jobs(runs)
    last=None
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    def timeout(*_):
        raise TimeoutError('0921 materialization unit exceeded 180 seconds')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGALRM,timeout)
    with (control/'writer.lock').open('a') as owner:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not stopped:
            signature=[]
            for root,job,_ in jobs:
                path=root/'jobs'/job['job_id']/'result.json'
                if path.exists():signature.append((job['job_id'],path.stat().st_mtime_ns))
            if signature!=last:
                signal.alarm(180)
                try:
                    with (release/'.0921-write.lock').open('a') as lock:
                        fcntl.flock(lock,fcntl.LOCK_EX)
                        counts=stage(release,control/'staged',jobs)
                        install(control/'staged',release)
                    last=signature
                    generator.write_json(control/'state.json',dict(status='writing_through',time=time.time(),**counts))
                    print(json.dumps(counts),flush=True)
                finally:
                    signal.alarm(0)
            if once or len(signature)==len(jobs):
                break
            for _ in range(15):
                if stopped:break
                time.sleep(1)
        state=generator.read_json(control/'state.json')
        state.update(status='stopped' if stopped else 'up_to_date' if once else 'completed',time=time.time())
        generator.write_json(control/'state.json',state)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['initialize','watch','once','stage'])
    parser.add_argument('--source',type=Path)
    parser.add_argument('--release',type=Path)
    parser.add_argument('--run',type=Path,action='append',default=[])
    parser.add_argument('--prototype-shard',type=Path,action='append',default=[])
    parser.add_argument('--preserve-existing',action='store_true')
    parser.add_argument('--control',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='initialize':
        initialize(args.source,args.release,args.run,args.control)
    elif args.action=='stage':
        prototypes=[]
        for path in args.prototype_shard:
            prototypes.extend(read_rows(path))
        print(stage(args.source,args.control,load_jobs(args.run),prototypes,args.preserve_existing))
    else:
        watch(args.control,once=args.action=='once')
