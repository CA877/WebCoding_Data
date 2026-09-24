import copy
import gzip
import json

from reverse import move_0905_historical_edit_repair as m


def test_move_and_cleanup_preserves_other_rows_and_shared_images(tmp_path,monkeypatch):
    source=tmp_path/'new_gt_webcompass_task_count_supplements_20260822_v1'
    release=tmp_path/'release'
    release.mkdir()
    source.mkdir()
    shared=tmp_path/'shared.jpg'; shared.write_bytes(b'shared-image')
    private=source/'defect.jpg'; private.write_bytes(b'defect-image')
    code=[dict(path='index.html',code='old')]
    patch=[dict(path='index.html',search='old',replace='new')]
    selected={}
    for task in m.TASKS:
        r=dict(instance_id=task,task_type=[f'T{i}' for i in range(8)],response=patch,task=task)
        if task=='text-edit':
            r['instruction']=dict(src_code=code,description=[dict(task_type=t,description='edit') for t in r['task_type']])
        elif task=='text-repair':
            r['instruction']=code
        else:
            r.update(instruction='original',input_files=code,input_images=[str(private if task=='image-repair' else shared)],
                     src_screenshot=[str(private if task=='image-repair' else shared)],dst_screenshot=[str(shared)] if task=='image-repair' else [],patches=patch)
        # Pair IDs match between text/image rows, as in the real source.
        r['instance_id']=task.split('-')[1]+'-selected'
        selected[task]=r
        lower=copy.deepcopy(r);lower['instance_id']=task+'-retained';lower['task_type']=lower['task_type'][:4]
        if task=='image-repair':
            lower['input_images']=[str(shared)];lower['src_screenshot']=[str(shared)]
        lane=source/task.split('-')[1]/'lane'
        lane.mkdir(parents=True,exist_ok=True)
        (lane/f'{task}.v2.jsonl').write_text(json.dumps(r)+'\n'+json.dumps(lower)+'\n')
    for family in ('edit','repair'):
        (source/family/'lane'/'records.jsonl').write_text(json.dumps(dict(instance_id=family+'-selected',task_type=list(range(8)),status='ok'))+'\n')
    index=dict(tasks={});manifest={}
    for task in m.TASKS:
        old=copy.deepcopy(selected[task])
        if task!='text-edit':
            old['instance_id']='existing-'+task
        if task.endswith('repair'):
            old['repair_instruction']='Official glossary\nYou have only 8 issues to fix, and you can not fix more than 8 issues.'
        path=release/task/m.SHARD;path.parent.mkdir()
        with gzip.open(path,'wt') as stream:stream.write(json.dumps(old)+'\n')
        entry=dict(num_samples=1,sha256=m.base.sha(path),image_files=0)
        index['tasks'][task]=entry
        manifest[f'{task}/{m.SHARD}']=dict(sha256=entry['sha256'],size=path.stat().st_size)
    m.base.write(release/'dataset_index.json',index)
    m.base.write(release/'manifest.json',manifest)
    (release/'README.md').write_text('Original')
    monkeypatch.setattr(m,'EXPECTED',{task:1 for task in m.TASKS})
    output=tmp_path/'run'
    assert m.prepare(release,source,output,1289)==0
    assert private.exists()
    m.base.commit(output)
    m.cleanup(output)
    assert not private.exists() and shared.exists()
    for task in m.TASKS:
        remaining=list(m.rows(source/task.split('-')[1]/'lane'/f'{task}.v2.jsonl'))
        assert len(remaining)==1 and len(remaining[0]['task_type'])==4
    assert m.base.read(output/'cleanup.json')['status']=='source_cleaned'
    assert (output/'source-rollback.tar.gz').exists()
