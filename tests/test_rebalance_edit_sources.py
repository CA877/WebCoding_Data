import copy
import gzip
import json
from reverse import rebalance_edit_sources as b
from reverse import write_0921_release as w


def test_balance_freezes_every_attempt_and_preserves_types(tmp_path):
    types=b.g.edit_catalog()[0][:4]
    entries=[]
    for i in range(12):
        code=[dict(path='index.html',code=f'<h1>site {i}</h1>')]
        case=dict(instance_id=str(i),job_id=str(i),source_code=code,task_types=types,original_types=types,strategy='reuse_all')
        entries.append((tmp_path,dict(job_id=str(i)),case))
    folder=tmp_path/'jobs/0';folder.mkdir(parents=True);(folder/'request.json').write_text('{}')
    donors={}
    for kind in ('react','vue'):
        for i in range(4):
            code=[dict(path='package.json',code='{"dependencies":{"'+kind+'":"*"}}'),dict(path='index.html',code=str(i))]
            donors[b.code_key(code)]=dict(kind=kind,source_code=code,identity=kind+str(i),template={'metadata':{'source_project':kind+str(i)}})
    original=copy.deepcopy(entries)
    changes,counts,targets=b.allocate(entries,donors)
    assert counts==targets==dict(vanilla=4,react=4,vue=4)
    assert entries==original
    assert all(j['job_id']!='0' and c['task_types']==types for r,j,n,c in changes)
    assert len({b.code_key(c['source_code']) for r,j,n,c in changes})==8


def test_writer_uses_new_mother_metadata_not_old_project(tmp_path):
    template=dict(task='text-editing',page_type='mp',resources=[],file_manifest=[{'path':'new.vue'}],metadata={'source_project':'NEW'})
    case=dict(instance_id='stable-id',source_record_template=template,source_code=[{'path':'new.vue','code':'ok'}],task_types=['Data Table']*4)
    rows,counts=w.build_rows([dict(instance_id='stable-id',metadata={'source_project':'OLD'},response='GT')],[(tmp_path,{'job_id':'changed'},case)])
    assert rows[0]['metadata']['source_project']=='NEW'
    assert rows[0]['file_manifest']==template['file_manifest']
    assert rows[0]['page_type']=='mp' and 'response' not in rows[0]
    assert rows[0]['metadata']['instruction_status']=='awaiting_query'


def test_half_multi_page_keeps_frameworks_and_started_cases(tmp_path):
    types=b.g.edit_catalog()[0][:4];entries=[];rows=[];donors={}
    for kind in b.KINDS:
        for i in range(4):
            identity=kind+str(i)
            code=[dict(path='index.html',code=identity)]
            if kind!='vanilla':code.append(dict(path='package.json',code=json.dumps({'dependencies':{kind:'*'}})))
            c=dict(instance_id=identity,job_id=identity,source_code=code,task_types=types)
            entries.append((tmp_path,dict(instance_id=identity,job_id=identity),c))
            rows.append(dict(instance_id=identity,page_type='sp',instruction={'src_code':code}))
            mp=code+[dict(path='about.html',code=identity+' about')]
            donors[b.code_key(mp)]=dict(kind=kind,identity=identity+'mp',source_code=mp,template=dict(page_type='mp',metadata={}))
    shard=tmp_path/'text-edit/train-00000-of-00001.jsonl.gz';shard.parent.mkdir()
    with gzip.open(shard,'wt') as f:
        for row in rows:f.write(json.dumps(row)+'\n')
    frozen=tmp_path/'jobs/vanilla0';frozen.mkdir(parents=True);(frozen/'request.json').write_text('{}')
    changes,counts,_=b.allocate_pages(entries,donors,tmp_path,shard)
    assert len(changes)==6 and counts==dict(vanilla=4,react=4,vue=4)
    assert all(j['job_id']!='vanilla0' and c['source_record_template']['page_type']=='mp' for r,j,n,c in changes)
    originals={j['job_id']:c for r,j,c in entries}
    assert all(b.stack(c['source_code'])==b.stack(originals[j['job_id']]['source_code']) for r,j,n,c in changes)
