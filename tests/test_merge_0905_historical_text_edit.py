import gzip
import json

import pytest

from reverse import merge_0905_historical_text_edit as m


def test_stage_commit_preserves_rows_and_backs_up(tmp_path):
    release=tmp_path/'release'
    source=tmp_path/'source'/'lane'
    source.mkdir(parents=True)
    (release/'text-edit').mkdir(parents=True)
    def row(identity, count):
        return dict(instance_id=identity,task='text-editing',task_type=[f'Type {i}' for i in range(count)],
                    instruction=dict(src_code=[dict(path='index.html',code='old')],
                        description=[dict(task_type=f'Type {i}',description='Requirement') for i in range(count)]),
                    response=[dict(path='index.html',search='old',replace='new')])
    old=row('old',4)
    new=row('new',8)
    with gzip.open(release/m.SHARD,'wt') as stream:
        stream.write(json.dumps(old)+'\n')
    original=(release/m.SHARD).read_bytes()
    m.write(release/'dataset_index.json',dict(tasks={'text-edit':dict(num_samples=1,sha256=m.sha(release/m.SHARD))}))
    (release/'README.md').write_text('original documentation')
    (source/'text-edit.v2.jsonl').write_text(json.dumps(new)+'\n')
    baseline=tmp_path/'manifest.json'
    m.write(baseline,{m.SHARD:dict(sha256=m.sha(release/m.SHARD))})
    output=tmp_path/'out'
    assert m.prepare(release,source.parent,baseline,output,580)==0
    assert (release/m.SHARD).read_bytes()==original
    m.commit(output)
    assert (output/'backup'/m.SHARD).read_bytes()==original
    with gzip.open(release/m.SHARD,'rt') as stream:
        assert [json.loads(s) for s in stream]==[old,new]
    assert m.read(release/'dataset_index.json')['tasks']['text-edit']['num_samples']==2
    assert m.read(output/'result.json')['status']=='merged_local_verified'
    with pytest.raises(ValueError):
        m.commit(output)
