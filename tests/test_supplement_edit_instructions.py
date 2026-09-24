import collections
import fcntl
import gzip
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from reverse.edit.query import supplement as s
from test_regenerate_edit_instructions import config, TYPES, local_api


def parent_run(tmp_path,count=10,**options):
    args=config(tmp_path,**options)
    args.cases_dir.mkdir()
    for i in range(count):
        with gzip.open(args.cases_dir/f'{i}.json.gz','wt') as stream:
            json.dump(dict(instance_id=f'source-{i}',task_types=TYPES,
                           source_code=[dict(path='index.html',code=f'<main>Site {i}</main>')]),stream)
    s.runner.prepare(args)
    return args.output_dir


def test_balanced_sampling_and_distinct_sources(tmp_path):
    parent=parent_run(tmp_path)
    out=tmp_path/'supplement'
    result=s.prepare(parent,out,per_level=2)
    assert result['prepared']==10 and result['distinct_sources']==10
    plan=s.runner.read_json(out/'plan.json')
    assert collections.Counter(j['task_count'] for j in plan['jobs'])=={8:2,9:2,10:2,11:2,12:2}
    assert plan['jobs'][0]['task_count']==12
    sources=set()
    for job in plan['jobs']:
        case=s.runner.read_json(out/'cases'/f'{job["job_id"]}.json')
        assert len(set(case['task_types']))==len(case['task_types'])==job['task_count']
        assert set(case['task_types'])<=set(s.runner.edit_catalog()[0])
        assert case['instance_id']!=case['source_instance_id']
        assert job['origins'][0]['source_instance_id']==case['source_instance_id']
        sources.add(s.runner.digest(case['source_code']))
    assert len(sources)==10


def test_parent_completion_boundary(tmp_path):
    parent=parent_run(tmp_path,2)
    plan=s.runner.read_json(parent/'plan.json')
    for counts,stopping,expected in [({'ok':2},False,True),({'ok':1,'error':1},False,True),
                                    ({'ok':1},False,False),({'ok':1,'blocked':1},False,False),
                                    ({'ok':2},True,False)]:
        s.runner.write_json(parent/'progress.json',dict(counts=counts,stopping=stopping,active={}))
        assert s.predecessor_complete(parent,plan['fingerprint']) is expected


def test_historical_types_reused_or_fully_resampled_without_gt(tmp_path):
    parent=parent_run(tmp_path)
    release=tmp_path/'release'
    shard=release/'text-edit'/'train-00000-of-00001.jsonl.gz'
    shard.parent.mkdir(parents=True)
    valid=s.runner.edit_catalog()[0][:8]
    with gzip.open(shard,'wt') as stream:
        for i,types in enumerate((valid,['Carousel',*valid[1:]])):
            stream.write(json.dumps(dict(instance_id=f'history-{i}',task_type=types,
                instruction=dict(src_code=[dict(path='index.html',code=f'<main>Historical {i}</main>')],
                                 description='OLD_QUERY_SENTINEL'),response='OLD_GT_SENTINEL'))+'\n')
    s.runner.write_json(release/'dataset_index.json',dict(tasks={'text-edit':dict(sha256=s.runner.sha256(shard))}))
    out=tmp_path/'combined'
    s.prepare(parent,out,per_level=2,existing_release=release)
    plan=s.runner.read_json(out/'plan.json')
    assert plan['existing_count']==2 and plan['additional_count']==8
    assert collections.Counter(j['task_count'] for j in plan['jobs'])=={8:2,9:2,10:2,11:2,12:2}
    cases={c['instance_id']:c for c in (s.runner.read_json(p) for p in (out/'cases').glob('*.json'))}
    assert cases['history-0']['task_types']==valid
    assert cases['history-0']['strategy']=='reuse_all'
    assert cases['history-1']['strategy']=='resample_all'
    assert set(cases['history-1']['task_types'])<=set(s.runner.edit_catalog()[0])
    assert 'OLD_GT_SENTINEL' not in json.dumps(cases) and 'OLD_QUERY_SENTINEL' not in json.dumps(cases)


def test_queue_wait_then_single_smoke_then_remaining(tmp_path,local_api):
    url,state=local_api
    parent=parent_run(tmp_path,5,base_url=url)
    out=tmp_path/'supplement'
    s.prepare(parent,out,per_level=1)
    credential=tmp_path/'local-test.key'
    credential.write_text('local-test-only')
    credential.chmod(0o600)
    lock=(parent/'run.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    command='from pathlib import Path; from reverse.edit.query.supplement import queue; import sys; sys.exit(queue(Path(sys.argv[1]),Path(sys.argv[2]),workers=2,poll_seconds=.05))'
    process=subprocess.Popen([sys.executable,'-c',command,str(out),str(credential)],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+5
        while not (out/'queue_state.json').exists() and time.monotonic()<deadline:
            time.sleep(.02)
        assert s.runner.read_json(out/'queue_state.json')['state']=='waiting_for_predecessor'
        assert state['requests']==[]
        s.runner.write_json(parent/'progress.json',dict(counts={'ok':5},stopping=False,active={}))
        fcntl.flock(lock,fcntl.LOCK_UN)
        _,stderr=process.communicate(timeout=20)
        assert process.returncode==0,stderr
        assert s.runner.read_json(out/'queue_state.json')['state']=='completed'
        assert len(state['requests'])==5
        assert s.runner.read_json(out/'progress.json')['counts']=={'ok':5}
    finally:
        lock.close()
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=10)
