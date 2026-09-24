"""Prepare balanced 8-12-subtask instructions and queue them after an existing run.

No API call is made by prepare or while waiting. Generation uses the existing runner,
including its process timeouts, cumulative request caps and original demo prompt.
"""
from __future__ import annotations

import argparse
import collections
import fcntl
import hashlib
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from reverse.edit.query import regenerate as runner


def prepare(predecessor, output, per_level=260, seed=20260922, existing_release=None):
    if per_level<1:
        raise ValueError('per-level must be positive')
    if (output/'plan.json').exists():
        raise FileExistsError('supplement plan exists; do not overwrite')
    parent=runner.read_json(predecessor/'plan.json')
    if runner.digest(dict(config=parent['config'],jobs=parent['jobs']))!=parent['fingerprint']:
        raise ValueError('predecessor plan fingerprint mismatch')
    if parent['config'].get('task')!='text-edit':
        raise ValueError('supplement requires text-edit sources')
    sources={}
    for job in parent['jobs']:
        case=runner.read_json(predecessor/'cases'/f'{job["job_id"]}.json')
        if runner.digest(case)!=job['case_sha256']:
            raise ValueError('predecessor case modified')
        source_hash=runner.digest(case['source_code'])
        sources.setdefault(source_hash,(job,case))
    if len(sources)<per_level:
        raise ValueError('not enough distinct source webpages for one difficulty level')
    pool=sorted(sources)
    random.Random(seed).shuffle(pool)
    output.mkdir(parents=True,exist_ok=True)
    names,_=runner.edit_catalog()
    jobs=[]
    used_sources=set()
    existing_counts=collections.Counter()
    if existing_release:
        seen=set()
        for identity,original,code,origin in runner.input_rows(SimpleNamespace(cases_dir=None,source_release=existing_release)):
            if not isinstance(original,list) or not 8<=len(original)<=12:
                continue
            if identity in seen:
                raise ValueError('duplicate historical instance ID')
            seen.add(identity)
            job_id=runner.digest(dict(instance_id=identity,original_types=original,source_code=code))
            types,strategy=runner.select_types(original,seed,job_id)
            prompt=runner.make_prompt(code,types)
            case=dict(job_id=job_id,instance_id=identity,original_types=original,task_types=types,
                      strategy=strategy,source_code=code,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
            runner.write_json(output/'cases'/f'{job_id}.json',case)
            jobs.append(dict(job_id=job_id,instance_id=identity,task_count=len(types),strategy=strategy,
                             origins=[origin],case_sha256=runner.digest(case)))
            existing_counts[len(types)]+=1
            used_sources.add(runner.digest(code))
        if any(n>per_level for n in existing_counts.values()):
            raise ValueError('historical rows exceed the requested per-level quota')
        pool=[source_hash for source_hash in pool if source_hash not in used_sources]
        if len(pool)<sum(per_level-existing_counts[n] for n in range(8,13)):
            raise ValueError('not enough distinct additional sources after historical reuse')
    offset=0
    for group,count in enumerate(range(8,13)):
        # Prefer distinct sources across all five levels; otherwise reuse only across levels.
        needed=per_level-existing_counts[count]
        selected=[pool[(offset+i)%len(pool)] for i in range(needed)]
        offset+=needed
        assert len(set(selected))==needed
        for source_hash in selected:
            old_job,old_case=sources[source_hash]
            instance_id=f'0905edit8to12-{count}-{source_hash[:20]}'
            types=random.Random(f'{seed}:{instance_id}').sample(names,count)
            job_id=runner.digest(dict(instance_id=instance_id,source_hash=source_hash,task_types=types))
            prompt=runner.make_prompt(old_case['source_code'],types)
            case=dict(job_id=job_id,instance_id=instance_id,source_instance_id=old_case['instance_id'],
                      original_types=old_case['original_types'],task_types=types,
                      strategy='new_8_to_12',source_code=old_case['source_code'],
                      prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
            runner.write_json(output/'cases'/f'{job_id}.json',case)
            origins=[dict(origin,source_instance_id=old_case['instance_id'],parent_job_id=old_job['job_id'])
                     for origin in old_job['origins']]
            jobs.append(dict(job_id=job_id,instance_id=instance_id,task_count=count,
                             strategy='new_8_to_12',origins=origins,case_sha256=runner.digest(case)))
    # Test the hardest requested level first; this sample counts toward the 1,300 total.
    hardest=next(i for i,j in enumerate(jobs) if j['task_count']==12)
    jobs.insert(0,jobs.pop(hardest))
    config=dict(parent['config'])
    config['seed']=seed
    plan=dict(config=config,jobs=jobs,rejected=[],excluded=[],source_release=parent.get('source_release'),
              cases_dir=None,limit=len(jobs),created=time.time(),predecessor=str(predecessor.resolve()),
              predecessor_fingerprint=parent['fingerprint'],per_level=per_level,
              distinct_sources=min(len(pool),len(jobs)),source_pool_size=len(pool),
              source_reuse_across_levels=len(pool)<len(jobs))
    if existing_release:
        plan.update(existing_release=str(existing_release.resolve()),existing_count=sum(existing_counts.values()),
                    additional_count=offset,existing_task_counts=dict(existing_counts),
                    distinct_sources=len(used_sources)+offset,source_reuse_across_levels=False)
    plan['fingerprint']=runner.digest(dict(config=config,jobs=jobs))
    runner.write_json(output/'plan.json',plan)
    return dict(prepared=len(jobs),counts=dict(collections.Counter(j['task_count'] for j in jobs)),
                distinct_sources=plan['distinct_sources'],first_sample_subtasks=jobs[0]['task_count'])


def predecessor_complete(root, expected):
    plan=runner.read_json(root/'plan.json')
    if plan['fingerprint']!=expected:
        raise ValueError('predecessor changed')
    progress=runner.read_json(root/'progress.json')
    counts=progress.get('counts',{})
    # Isolated sample failures do not prevent the next batch; cancellation/quota/crash do.
    return (not progress.get('stopping') and not progress.get('active') and
            not counts.get('blocked',0) and sum(counts.values())==len(plan['jobs']))


def queue(output, key_file, workers=10, poll_seconds=15):
    plan=runner.read_json(output/'plan.json')
    parent=Path(plan['predecessor'])
    halted=False
    child=None
    def stop(*_):
        nonlocal halted
        halted=True
        if child is not None and child.poll() is None:
            # Signal the generation supervisor, allowing it to clean all worker groups.
            child.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    def state(name,**extra):
        runner.write_json(output/'queue_state.json',dict(state=name,time=time.time(),
            predecessor=str(parent),planned=len(plan['jobs']),workers=workers,**extra))
    with (output/'queue.lock').open('a') as own_lock, (parent/'run.lock').open('a') as parent_lock:
        fcntl.flock(own_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not halted:
            try:
                fcntl.flock(parent_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                state('waiting_for_predecessor')
                time.sleep(poll_seconds)
        if halted:
            state('cancelled')
            return 2
        if not predecessor_complete(parent,plan['predecessor_fingerprint']):
            state('blocked_predecessor_not_completed')
            return 2
        # Retain predecessor lock through supplement execution: no overlapping retries.
        def launch(parallel,limit):
            nonlocal child
            command=[sys.executable,str(Path(runner.__file__).resolve()),'run','--output-dir',str(output),
                     '--workers',str(parallel),'--limit',str(limit),'--api-key-file',str(key_file)]
            with (output/'batch.log').open('a') as log:
                child=subprocess.Popen(command,stdout=log,stderr=log)
                while child.poll() is None:
                    state('stopping' if halted else ('validating_first_sample' if parallel==1 else 'running'),
                          supervisor_pid=child.pid)
                    time.sleep(min(poll_seconds,5))
                return child.returncode
        # A failed individual sample must not abort the queue: try the next, within total cap.
        while not halted:
            results=[runner.read_json(p) for p in (output/'jobs').glob('*/result.json')]
            if any(r.get('status')=='ok' for r in results):
                break
            if len(results)>=len(plan['jobs']):
                state('completed_with_errors')
                return 0
            if launch(1,1)!=0:
                state('cancelled' if halted else 'blocked_generation')
                return 2
        if not halted and launch(workers,len(plan['jobs']))==0:
            state('completed')
            return 0
        state('cancelled' if halted else 'blocked_generation')
        return 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    prep=sub.add_parser('prepare')
    prep.add_argument('--predecessor',type=Path,required=True)
    prep.add_argument('--output-dir',type=Path,required=True)
    prep.add_argument('--per-level',type=int,default=260)
    prep.add_argument('--seed',type=int,default=20260922)
    prep.add_argument('--existing-release',type=Path,help='Reuse historical 8–12 task types where valid; fill remaining per-level quotas')
    wait=sub.add_parser('queue')
    wait.add_argument('--output-dir',type=Path,required=True)
    wait.add_argument('--api-key-file',type=Path,required=True)
    wait.add_argument('--workers',type=int,choices=range(1,11),default=10)
    args=parser.parse_args()
    if args.action=='prepare':
        print(prepare(args.predecessor,args.output_dir,args.per_level,args.seed,args.existing_release))
        return 0
    return queue(args.output_dir,args.api_key_file,args.workers)


if __name__=='__main__':
    raise SystemExit(main())
