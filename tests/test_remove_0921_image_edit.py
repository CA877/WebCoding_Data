import gzip
import json

import pytest

from reverse import remove_0921_image_edit as m


def make_release(tmp_path,shared=False):
    release=tmp_path/'0921';index=dict(name='0921',tasks={});manifest={}
    for task in ('image-edit','text-edit'):
        p=release/task/'train-00000-of-00001.jsonl.gz';p.parent.mkdir(parents=True)
        row=dict(instance_id=task)
        if shared and task=='text-edit':row['image']='../image-edit/images/source.jpg'
        with gzip.open(p,'wt') as stream:stream.write(json.dumps(row)+'\n')
        relative=str(p.relative_to(release))
        index['tasks'][task]=dict(num_samples=1,sha256=m.io.sha(p),data_files=[relative])
        manifest[relative]=dict(sha256=m.io.sha(p),size=p.stat().st_size)
    image=release/'image-edit/images/source.jpg';image.parent.mkdir();image.write_bytes(b'image')
    manifest['image-edit/images/source.jpg']=dict(sha256=m.io.sha(image),size=image.stat().st_size)
    m.io.write(release/'dataset_index.json',index);m.io.write(release/'manifest.json',manifest)
    (release/'README.md').write_text('fixture')
    return release


def test_removal_is_recoverable_and_preserves_text(tmp_path):
    release=make_release(tmp_path)
    text_hash=m.io.sha(release/'text-edit/train-00000-of-00001.jsonl.gz')
    control=tmp_path/'removal'
    assert m.run(release,control)['records']==1
    report=m.run(release,control,apply=True)
    assert report['remaining_image_edit']==0
    assert (control/'image-edit/images/source.jpg').read_bytes()==b'image'
    with gzip.open(release/m.SHARD,'rt') as stream:assert stream.read()==''
    assert m.io.sha(release/'text-edit/train-00000-of-00001.jsonl.gz')==text_hash
    assert not (release/'image-edit/images').exists()
    assert m.io.read(release/'dataset_index.json')['tasks']['image-edit']['num_samples']==0


def test_shared_reference_prevents_removal(tmp_path):
    release=make_release(tmp_path,shared=True)
    with pytest.raises(ValueError,match='references image-edit'):
        m.run(release,tmp_path/'removal',apply=True)
    assert (release/'image-edit/images/source.jpg').exists()
