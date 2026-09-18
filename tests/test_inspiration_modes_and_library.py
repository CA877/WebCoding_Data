import json
from pathlib import Path
import sys

import pytest

from inspiration_library.utils.inventory_inspiration_library import inventory
from inspiration_library.utils.consolidate_inspiration_library import consolidate, verify_snapshot
from inspiration_library.utils import mine_live_url_capability_pool as miner


def test_mode_rejects_mixed_or_wrong_source_type(tmp_path):
    path = tmp_path/'input.jsonl'
    path.write_text(json.dumps({'seed_id':'x','entry_url':'https://example.org'}))
    assert miner.load_sources(path,'url')[0]['entry_url'] == 'https://example.org'
    with pytest.raises(ValueError): miner.load_sources(path,'local_project')
    path.write_text(json.dumps({'seed_id':'x','project_path':str(tmp_path)}))
    assert miner.load_sources(path,'local_project')[0]['project_path'] == str(tmp_path)
    with pytest.raises(ValueError): miner.load_sources(path,'url')
    path.write_text(json.dumps({'seed_id':'x','project_path':str(tmp_path),'entry_url':'https://example.org'}))
    for mode in ['url','local_project']:
        with pytest.raises(ValueError): miner.load_sources(path,mode)


def test_local_mode_uses_cached_extraction_and_real_project_slice(tmp_path, monkeypatch):
    """Routing/source-file test, not a simulated LLM semantic test."""
    project = tmp_path/'project'
    project.mkdir()
    (project/'index.html').write_text('<section id="demo"><button>Choose</button></section>')
    manifest, run = tmp_path/'sources.jsonl', tmp_path/'run'
    manifest.write_text(json.dumps({'seed_id':'demo','project_path':str(project)}))
    monkeypatch.setenv('DOC_API_KEY','unused-no-network')
    monkeypatch.setattr(sys,'argv',['miner','--mode','local_project','--sources',str(manifest),'--run-dir',str(run)])
    def cached(**kwargs):
        assert kwargs['project'] == project
        extraction = {'capabilities':[{'capability_id':'demo__choose','source_seed_id':'demo',
            'source_project':str(project),'summary':'Choose an item','visible_result':'Selected item is visible',
            'source_anchors':['demo'],'source_evidence':[{'path':'index.html','anchor':'id="demo"'}]}]}
        path = run/'extractions/demo.json'
        path.parent.mkdir()
        path.write_text(json.dumps(extraction))
        return {'baseline':{},'exploration_paths':[]}
    monkeypatch.setattr(miner,'deep_explore_project',cached)
    def forbidden(**kwargs): raise AssertionError('Wrong route or unexpected API call')
    monkeypatch.setattr(miner,'deep_explore_url',forbidden)
    monkeypatch.setattr(miner,'extract_seed_capabilities',forbidden)
    assert miner.main() == 0
    card = json.loads((run/'capability_pool.jsonl').read_text())
    assert card['mode'] == 'local_project'
    assert 'Choose' in card['source_slices'][0]['content']
    assert json.loads((run/'run_identity.json').read_text())['mode'] == 'local_project'


def test_archive_union_keeps_versions_and_materializes_source(tmp_path):
    roots = [tmp_path/'mac',tmp_path/'remote']
    old = {'capability_id':'same','source_seed_id':'p','summary':'Old reference',
           'visible_result':'Old visible result'}
    new = {**old,'summary':'New reference','source_slices':[{'path':'/old/machine/app.js',
           'language':'js','start_line':15,'end_line':15,'content':'function choose() {}'}]}
    for root in roots: root.mkdir()
    (roots[0]/'capability_pool.jsonl').write_text(json.dumps(old)+'\n'+json.dumps(new)+'\n')
    (roots[1]/'capability_pool.jsonl').write_text(json.dumps(old)+'\n')
    invs = [inventory([root],host=host) for root,host in zip(roots,['mac','remote'])]
    out = tmp_path/'library'
    result = consolidate(invs,out,out)
    assert result['unique_ids_including_superseded'] == 1
    assert result['unique_record_versions'] == 2 and result['overlap_ids'] == 1
    card = json.loads((out/'capability_pool.jsonl').read_text())
    assert card['summary'] == 'New reference'
    source = card['source_slices'][0]
    assert Path(source['path']).read_text() == source['content']
    assert source['original_start_line'] == 15 and source['start_line'] == 1
    assert len(list((out/'archives').glob('*.jsonl'))) == 2
    assert (roots[0]/'capability_pool.jsonl').read_text().count('\n') == 2
    assert verify_snapshot(out)['status'] == 'ok'
    Path(source['path']).write_text('changed')
    with pytest.raises(ValueError,match='differs'):
        verify_snapshot(out)
