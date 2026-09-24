"""Rebalance only unstarted instruction cases, preserving paid work and source lineage."""
import argparse
import collections
import copy
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reverse.edit.query import regenerate as g
from reverse.audit_edit_stacks import stack

KINDS=('vanilla','react','vue')
TEXT_EXT={'.html','.htm','.css','.js','.jsx','.ts','.tsx','.vue','.json','.svg','.md','.txt','.mjs','.cjs','.scss','.sass','.less'}


def code_key(code):
    return g.digest(sorted(code,key=lambda x:x['path']))


def collect(release, physical, output):
    """Use existing complete source projects, not defective Repair inputs."""
    donors={};counts=collections.Counter()
    def add(code, identity, origin, page_type='sp'):
        kind=stack(code)
        if kind not in ('react','vue'):return
        if not code or sum(len(f['code']) for f in code)>120000:return
        names=[f['path'] for f in code]
        if len(names)!=len(set(names)) or any(Path(n).is_absolute() or '..' in Path(n).parts for n in names):return
        key=code_key(code)
        if key in donors:return
        template=dict(task='text-editing',page_type=page_type,resources=[],
            file_manifest=[dict(path=f['path'],type='code',size_bytes=len(f['code'].encode())) for f in code],
            metadata=dict(release_schema_reference='webcoding-sft-v2',source_project=origin,
                          source_instance_id=identity,source_code_sha256=key,source_framework=kind,
                          source_pool='physical_existing_projects',source_validation='inherited_not_revalidated'))
        donors[key]=dict(source_code=code,kind=kind,identity=identity,template=template)
        counts[kind]+=1
    # Formal Generate projects first, then additional physical mother projects.
    with gzip.open(release/'text-generate/train-00000-of-00001.jsonl.gz','rt') as stream:
        for line in stream:
            row=json.loads(line);code=row.get('response')
            if not isinstance(code,list) or any(not isinstance(f,dict) or 'code' not in f for f in code):continue
            code=[dict(path=f['path'],code=f['code']) for f in code]
            if stack(code) not in ('react','vue'):continue
            origin=row.get('metadata',{}).get('source_project','')
            # Select self-contained text-file projects; never drop local binary dependencies.
            folder=Path(origin)
            if not origin or not folder.is_dir():continue
            disk=[p for p in folder.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '.git' not in p.parts]
            if any(p.suffix.lower() not in TEXT_EXT and not p.name.endswith('_clean.png') for p in disk):continue
            add(code,row['instance_id'],origin,row.get('page_type','sp'))
    with (physical/'results.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('status')!='ok' or row.get('framework') not in ('react','vue'):continue
            folder=physical/'projects'/row['project_id']
            files=sorted(p for p in folder.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '.git' not in p.parts)
            if not files or any(p.is_symlink() or p.suffix.lower() not in TEXT_EXT for p in files):continue
            if sum(p.stat().st_size for p in files)>480000:continue
            try:code=[dict(path=p.relative_to(folder).as_posix(),code=p.read_text()) for p in files]
            except UnicodeError:continue
            add(code,row['project_id'],str(folder),'mp' if row.get('page_mode')=='multi_page' else 'sp')
    g.write_json(output,donors)
    print(json.dumps(dict(distinct_donors=dict(counts),output=str(output))),flush=True)


def allocate(entries,donors):
    counts=collections.Counter(stack(case['source_code']) for _,_,case in entries)
    total=len(entries)
    targets={kind:total//3+(i<total%3) for i,kind in enumerate(KINDS)}
    used=collections.Counter(code_key(case['source_code']) for _,_,case in entries)
    combinations={(code_key(case['source_code']),tuple(sorted(case['task_types']))) for _,_,case in entries}
    changes=[]
    pools={k:sorted(h for h,d in donors.items() if d['kind']==k) for k in ('react','vue')}
    for root,job,case in entries:
        old_kind=stack(case['source_code'])
        if old_kind!='vanilla' or counts['vanilla']<=targets['vanilla']:continue
        # Any worker artifact freezes the case, including interrupted/failed requests.
        folder=root/'jobs'/job['job_id']
        if folder.exists() and any(folder.iterdir()):continue
        needs=[k for k in ('react','vue') if counts[k]<targets[k] and pools[k]]
        if not needs:break
        kind=max(needs,key=lambda k:targets[k]-counts[k])
        types=tuple(sorted(case['task_types']))
        choices=[h for h in pools[kind] if (h,types) not in combinations]
        if not choices:raise ValueError('no distinct source/type combination remains')
        key=min(choices,key=lambda h:(used[h],h))
        donor=donors[key]
        new=copy.deepcopy(case)
        new.update(source_code=donor['source_code'],source_instance_id=donor['identity'],
                   source_record_template=donor['template'],source_framework=kind,
                   replaced_job_id=job['job_id'])
        new['job_id']=g.digest(dict(instance_id=case['instance_id'],source_code=new['source_code'],task_types=new['task_types']))
        new['prompt_sha256']=hashlib.sha256(g.make_prompt(new['source_code'],new['task_types']).encode()).hexdigest()
        new_job=dict(job,job_id=new['job_id'],case_sha256=g.digest(new),
                     origins=[dict(source_project=donor['template']['metadata']['source_project'],source_instance_id=donor['identity'],replaces_job=job['job_id'])])
        changes.append((root,job,new_job,new))
        used[code_key(case['source_code'])]-=1;used[key]+=1
        combinations.add((key,types))
        counts[old_kind]-=1;counts[kind]+=1
    return changes,dict(counts),targets


def allocate_pages(entries,donors,release,source_shard):
    with gzip.open(release/'text-edit/train-00000-of-00001.jsonl.gz','rt') as stream:
        rows={r['instance_id']:r for r in map(json.loads,stream)}
    # Reuse intact, previously selected multi-page Vanilla mothers as well.
    with gzip.open(source_shard,'rt') as stream:
        for row in map(json.loads,stream):
            if row.get('page_type')!='mp':continue
            code=row['instruction']['src_code'];key=code_key(code)
            template={k:copy.deepcopy(row[k]) for k in ('task','page_type','file_manifest','resources','metadata') if k in row}
            metadata=template.setdefault('metadata',{})
            for k in ('instruction_job_id','instruction_status','prompt_tokens','patch_count','patch_count_by_task'):
                metadata.pop(k,None)
            metadata.update(source_instance_id=row['instance_id'],source_code_sha256=key,source_framework=stack(code))
            donors.setdefault(key,dict(source_code=code,kind=stack(code),identity=row['instance_id'],template=template))
    templates={j['job_id']:c.get('source_record_template') or rows[c['instance_id']] for r,j,c in entries}
    pages=collections.Counter(templates[j['job_id']]['page_type'] for r,j,c in entries)
    needed=len(entries)//2-pages['mp']
    if needed<0:raise ValueError('already above half multi-page; do not discard existing work')
    used=collections.Counter(code_key(c['source_code']) for r,j,c in entries)
    combinations={(code_key(c['source_code']),tuple(sorted(c['task_types']))) for r,j,c in entries}
    pools={k:sorted(h for h,d in donors.items() if d['kind']==k and d['template']['page_type']=='mp') for k in KINDS}
    pending={k:[] for k in KINDS}
    for r,j,c in entries:
        folder=r/'jobs'/j['job_id']
        if templates[j['job_id']]['page_type']=='sp' and not (folder.exists() and any(folder.iterdir())):
            pending[stack(c['source_code'])].append((r,j,c))
    changes=[]
    for _ in range(needed):
        choices=[]
        for kind in KINDS:
            if not pending[kind]:continue
            r,j,c=pending[kind][0];types=tuple(sorted(c['task_types']))
            keys=[h for h in pools[kind] if (h,types) not in combinations]
            if keys:
                key=min(keys,key=lambda h:(used[h],h))
                choices.append((used[key],kind,key))
        if not choices:raise ValueError('not enough unstarted cases / multi-page donors')
        _,kind,key=min(choices)
        root,job,case=pending[kind].pop(0);donor=donors[key]
        new=copy.deepcopy(case)
        new.update(source_code=donor['source_code'],source_instance_id=donor['identity'],
                   source_record_template=donor['template'],source_framework=kind,replaced_job_id=job['job_id'])
        new['job_id']=g.digest(dict(instance_id=case['instance_id'],source_code=new['source_code'],task_types=new['task_types']))
        new['prompt_sha256']=hashlib.sha256(g.make_prompt(new['source_code'],new['task_types']).encode()).hexdigest()
        new_job=dict(job,job_id=new['job_id'],case_sha256=g.digest(new),origins=[dict(source_instance_id=donor['identity'],source_project=donor['template']['metadata'].get('source_project'),replaces_job=job['job_id'])])
        changes.append((root,job,new_job,new));used[key]+=1;used[code_key(case['source_code'])]-=1
        combinations.add((key,tuple(sorted(case['task_types']))))
    counts=dict(collections.Counter(stack(c['source_code']) for r,j,c in entries))
    return changes,counts,counts


def rebalance(runs,donor_file,backup,apply=False,release=None,source_shard=None):
    locks=[]
    try:
        for root in runs:
            for name in ('run.lock','queue.lock'):
                lock=(root/name).open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
        plans={r:g.read_json(r/'plan.json') for r in runs}
        entries=[]
        for root,plan in plans.items():
            if g.digest(dict(config=plan['config'],jobs=plan['jobs']))!=plan['fingerprint']:raise ValueError('plan checksum')
            for job in plan['jobs']:
                case=g.read_json(root/'cases'/f'{job["job_id"]}.json')
                if g.digest(case)!=job['case_sha256']:raise ValueError('case checksum')
                entries.append((root,job,case))
        donors=g.read_json(donor_file)
        changes,counts,targets=(allocate_pages(entries,donors,release,source_shard) if release else allocate(entries,donors))
        changed={(r,j['job_id']):(nj,nc) for r,j,nj,nc in changes}
        final_cases=[changed.get((r,j['job_id']),(j,c))[1] for r,j,c in entries]
        uses=collections.Counter(code_key(c['source_code']) for c in final_cases)
        smoke_jobs=[]
        for kind in KINDS:
            first=next(((r,nj,nc) for r,j,nj,nc in changes if nc['source_framework']==kind),None)
            if first:
                r,nj,nc=first
                smoke_jobs.append(dict(run=str(r),job_id=nj['job_id'],framework=kind))
        report=dict(changed=len(changes),final_stack_counts=counts,targets=targets,
            frozen=sum((r/'jobs'/j['job_id']).exists() and any((r/'jobs'/j['job_id']).iterdir()) for r,j,c in entries),
            distinct_sources=len(uses),max_source_reuse=max(uses.values()),
            smoke_jobs=smoke_jobs)
        if release:
            with gzip.open(release/'text-edit/train-00000-of-00001.jsonl.gz','rt') as stream:
                original_pages={r['instance_id']:r['page_type'] for r in map(json.loads,stream)}
            report['final_page_counts']=dict(collections.Counter(c.get('source_record_template',{}).get('page_type') or original_pages[c['instance_id']] for c in final_cases))
            report['framework_page_counts']=dict(collections.Counter(stack(c['source_code'])+'/'+(c.get('source_record_template',{}).get('page_type') or original_pages[c['instance_id']]) for c in final_cases))
        if apply:
            if backup.exists():raise FileExistsError('backup already exists')
            backup.mkdir(parents=True)
            for root,plan in plans.items():
                shutil.copy2(root/'plan.json',backup/(root.name+'.plan.json'))
                jobs=[]
                for job in plan['jobs']:
                    replacement=changed.get((root,job['job_id']))
                    if replacement:
                        nj,nc=replacement
                        g.write_json(root/'cases'/f'{nj["job_id"]}.json',nc)
                        jobs.append(nj)
                    else:jobs.append(job)
                # Put the two changed real cases first so smoke consumes actual planned work.
                smoke={j['job_id']:i for i,j in enumerate(j for j in report['smoke_jobs'] if j['run']==str(root))}
                jobs.sort(key=lambda j:smoke.get(j['job_id'],len(smoke)))
                plan['jobs']=jobs
                plan['fingerprint']=g.digest(dict(config=plan['config'],jobs=jobs))
                source_counts=collections.Counter(code_key(g.read_json(root/'cases'/f'{j["job_id"]}.json')['source_code']) for j in jobs)
                plan.update(distinct_sources=len(source_counts),source_reuse_across_levels=max(source_counts.values())>1,
                            source_balance=dict(targets=targets,combined_counts=counts,backup=str(backup)))
                if release:plan['source_balance']['combined_page_counts']=report['final_page_counts']
                if 'predecessor' in plan:plan['predecessor_fingerprint']=plans[Path(plan['predecessor'])]['fingerprint']
                g.write_json(root/'plan.json',plan)
            g.write_json(backup/'report.json',report)
        print(json.dumps(report),flush=True)
        return report
    finally:
        for lock in locks:lock.close()


def verify(runs,backup):
    frozen=changed=0
    counts=collections.Counter()
    for root in runs:
        old=g.read_json(backup/(root.name+'.plan.json'))
        current=g.read_json(root/'plan.json')
        assert old['config']==current['config']
        assert g.digest(dict(config=current['config'],jobs=current['jobs']))==current['fingerprint']
        by_id={j['instance_id']:j for j in current['jobs']}
        assert len(by_id)==len(old['jobs'])
        for prior in old['jobs']:
            job=by_id[prior['instance_id']]
            case=g.read_json(root/'cases'/f'{job["job_id"]}.json')
            previous=g.read_json(root/'cases'/f'{prior["job_id"]}.json')
            assert g.digest(previous)==prior['case_sha256']
            assert g.digest(case)==job['case_sha256']
            assert case['task_types']==previous['task_types']
            counts[stack(case['source_code'])]+=1
            folder=root/'jobs'/prior['job_id']
            if folder.exists() and any(folder.iterdir()):
                assert job==prior and case==previous
                frozen+=1
            elif job['job_id']!=prior['job_id']:
                changed+=1
        if 'predecessor' in current:
            assert current['predecessor_fingerprint']==g.read_json(Path(current['predecessor'])/'plan.json')['fingerprint']
    report=dict(frozen_verified=frozen,replaced_unstarted=changed,counts=dict(counts),configs_and_types_preserved=True)
    g.write_json(backup/'verification.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='action',required=True)
    c=s.add_parser('collect');c.add_argument('--release',type=Path,required=True);c.add_argument('--physical',type=Path,required=True);c.add_argument('--output',type=Path,required=True)
    b=s.add_parser('rebalance');b.add_argument('--run',type=Path,action='append',required=True);b.add_argument('--donors',type=Path,required=True);b.add_argument('--backup',type=Path,required=True);b.add_argument('--apply',action='store_true')
    b.add_argument('--release',type=Path,help='Balance half multi-page without changing framework totals')
    b.add_argument('--source-shard',type=Path,help='Preserved original Edit sources for Vanilla multi-page donors')
    v=s.add_parser('verify');v.add_argument('--run',type=Path,action='append',required=True);v.add_argument('--backup',type=Path,required=True)
    a=p.parse_args()
    if a.action=='collect':collect(a.release,a.physical,a.output)
    elif a.action=='rebalance':rebalance(a.run,a.donors,a.backup,a.apply,a.release,a.source_shard)
    else:verify(a.run,a.backup)
