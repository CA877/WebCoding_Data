import gzip
import json

from reverse import write_0921_release as w
from test_regenerate_edit_instructions import config,put_case,TYPES,CODE


def test_initialize_and_incremental_formal_write_without_old_gt(tmp_path):
    args=config(tmp_path)
    put_case(args.cases_dir,'sample',TYPES)
    w.generator.prepare(args)
    job=w.generator.read_json(args.output_dir/'plan.json')['jobs'][0]
    source=tmp_path/'releases'/'old'
    (source/'text-edit').mkdir(parents=True)
    original=dict(instance_id='sample',task_type=TYPES,task='text-editing',metadata={},
                  instruction=dict(src_code=CODE,description=['OLD_QUERY']),response=['OLD_GT'])
    with gzip.open(source/w.SHARD,'wt') as stream:stream.write(json.dumps(original)+'\n')
    w.generator.write_json(source/'dataset_index.json',dict(name='old',tasks={'text-edit':dict(num_samples=1)}))
    w.generator.write_json(source/'manifest.json',{})
    (source/'README.md').write_text('old')
    target=source.parent/'0921'; control=tmp_path/'writer'
    w.initialize(source,target,[args.output_dir],control)
    assert source.is_symlink() and source.resolve()==target
    rows=w.read_rows(target/w.SHARD)
    assert len(rows)==1 and 'response' not in rows[0]
    assert rows[0]['instruction']['description']==[]
    assert rows[0]['metadata']['instruction_status']=='awaiting_query'
    values=[dict(task_type=t,description='Local fixture requested behavior') for t in TYPES]
    w.generator.write_json(args.output_dir/'jobs'/job['job_id']/'result.json',dict(status='ok',descriptions=values))
    w.watch(control,once=True)
    ready=w.read_rows(target/w.SHARD)[0]
    assert ready['instruction']['description']==values
    assert ready['metadata']['instruction_status']=='query_ready' and 'response' not in ready
    index=w.generator.read_json(target/'dataset_index.json')
    assert index['name']=='0921' and index['tasks']['text-edit']['gt_records']==0
    assert w.sha(target/w.SHARD)==index['tasks']['text-edit']['sha256']


def test_stage_preserves_current_rows_and_uses_removed_prototype_for_replacement(tmp_path):
    args=config(tmp_path)
    args.cases_dir.mkdir(parents=True)
    replacement_code=[
        {'path':'index.html','code':'<main>Home</main>'},
        {'path':'about.html','code':'<main>About</main>'},
        {'path':'styles.css','code':'main { display: block; }'},
    ]
    with gzip.open(args.cases_dir/'replacement.json.gz','wt') as stream:
        json.dump(dict(instance_id='replacement',task_types=TYPES,source_code=replacement_code),stream)
    w.generator.prepare(args)
    job=w.generator.read_json(args.output_dir/'plan.json')['jobs'][0]
    descriptions=[dict(task_type=t,description=' '.join(['behavior']*100)) for t in TYPES]
    w.generator.write_json(args.output_dir/'jobs'/job['job_id']/'result.json',
                           dict(status='ok',descriptions=descriptions))

    source=tmp_path/'release'
    (source/'text-edit').mkdir(parents=True)
    existing=dict(instance_id='existing',task_type=TYPES,task='text-editing',page_type='sp',
                  metadata={'instruction_status':'query_ready'},
                  instruction=dict(src_code=CODE,description=descriptions))
    with gzip.open(source/w.SHARD,'wt') as stream:
        stream.write(json.dumps(existing)+'\n')
    w.generator.write_json(source/'dataset_index.json',dict(name='0921',tasks={'text-edit':dict(num_samples=1)}))
    w.generator.write_json(source/'manifest.json',{})
    (source/'README.md').write_text('old')
    prototype=dict(instance_id='replacement',task_type=TYPES,task='text-editing',page_type='mp',
                   metadata={},instruction=dict(src_code=CODE,description=[]),response=['OLD_GT'])

    output=tmp_path/'staged'
    result=w.stage(source,output,w.load_jobs([args.output_dir]),[prototype],True)
    rows=w.read_rows(output/w.SHARD)
    assert [row['instance_id'] for row in rows]==['existing','replacement']
    assert rows[1]['instruction']['src_code']==replacement_code
    assert rows[1]['instruction']['description']==descriptions
    assert 'response' not in rows[1]
    assert result['preserved_existing']==1 and result['newly_generated']==1
    assert result['physical_html_counts']=={'single_html':1,'multi_html':1}
    index=w.generator.read_json(output/'dataset_index.json')
    assert index['tasks']['text-edit']['num_samples']==2
    assert index['tasks']['text-edit']['record_state']=='query_ready_gt_pending'
