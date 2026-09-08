"""Transport/cache tests; real semantic acceptance is exercised separately on the physical host."""
import json
import io
from types import SimpleNamespace

import pytest

from scripts import run_linear_edit_query_augmentation as runner
from scripts.embed_capability_pool import embed_pool
from instruction_augmentation.one_shot_capability_retrieval import generate_seed_retrieval_plan
from test_one_shot_capability_retrieval import _retrieval_plan_payload
from test_linear_edit_query_augmentation import _accepted_quality_audit
from instruction_augmentation.linear_edit_queries import validate_quality_audit


def test_case_wrapper_passes_protected_settings_without_logging_secrets(tmp_path, monkeypatch, capsys):
    from scripts import run_edit_instruction_case as case
    settings = dict(TOKENWAVE_API_KEY='test-chat-secret',
                    DOC_EMBEDDING_API_KEY='test-vector-secret',
                    DOC_EMBEDDING_BASE_URL='https://example.invalid/v1')
    monkeypatch.setattr(case.sys, 'stdin', io.StringIO(json.dumps(settings)))
    monkeypatch.setattr(case.sys, 'argv', ['case', '--credentials-stdin',
        '--chat-model', 'gpt-5.5', '--sampled-seeds', str(tmp_path/'seed.jsonl'),
        '--run-dir', str(tmp_path/'run')])
    monkeypatch.setattr(case.signal, 'signal', lambda *a: None)
    def check(command, **kwargs):
        env = kwargs['env']
        assert env['DOC_API_KEY'] == settings['TOKENWAVE_API_KEY']
        assert env['DOC_EMBEDDING_API_KEY'] == settings['DOC_EMBEDDING_API_KEY']
        assert env['DOC_API_BASE_URL'] == 'https://api.tokenwave.us/v1'
        assert kwargs['seconds'] == 600
        assert command[command.index('--edit-count')+1] == 'random'
        assert not any(value in ' '.join(command) for value in settings.values())
        return {'status': 'ok'}
    monkeypatch.setattr(case, 'supervise', check)
    assert case.main() == 0
    assert 'secret' not in capsys.readouterr().out


def test_random_chain_lengths_cover_inclusive_range_and_reproduce(tmp_path):
    ids = [f'host-{index}' for index in range(200)]
    kwargs = dict(seed_ids=ids, requested='random', length_seed=37)
    first = runner.select_edit_counts(**kwargs, run_dir=tmp_path/'first')
    second = runner.select_edit_counts(**{**kwargs, 'seed_ids':list(reversed(ids))}, run_dir=tmp_path/'second')
    assert first == second
    assert set(first.values()) == set(range(4,13))
    assert runner.select_edit_counts(**kwargs, run_dir=tmp_path/'first') == first
    with pytest.raises(ValueError, match='selection settings differ'):
        runner.select_edit_counts(**{**kwargs, 'length_seed':38}, run_dir=tmp_path/'first')


def test_random_resume_does_not_draw_new_seed(tmp_path, monkeypatch):
    kwargs = dict(seed_ids=['host'], requested='random', run_dir=tmp_path)
    selected = runner.select_edit_counts(**kwargs)
    monkeypatch.setattr(runner.random, 'SystemRandom', lambda: pytest.fail('resume must reuse saved randomness'))
    assert runner.select_edit_counts(**kwargs) == selected


@pytest.mark.parametrize('count', range(4,13))
def test_fixed_and_replayed_lengths_are_preserved(tmp_path, count):
    assert runner.parse_edit_count_argument(str(count)) == count
    fixed = runner.select_edit_counts(seed_ids=['host'], requested=count, run_dir=tmp_path/'fixed')
    replay = runner.select_edit_counts(seed_ids=['host'], requested='random',
        preserved_count=count, run_dir=tmp_path/'replay')
    assert fixed == replay == {'host':count}


def test_random_count_argument_and_legacy_auto():
    import argparse
    assert runner.parse_edit_count_argument('random') == 'random'
    assert runner.parse_edit_count_argument('auto') is None
    for value in ['3','13','eight']:
        with pytest.raises(argparse.ArgumentTypeError):
            runner.parse_edit_count_argument(value)


def test_retrieval_precedes_count_controlled_planning(tmp_path, monkeypatch):
    events = []
    query = _retrieval_plan_payload()['retrieval_query']
    card = dict(capability_id='inspiration', source_seed_id='donor', change_type='compare',
                summary='Compare selected objects.', visible_result='Comparison shown.', embedding=[1.0])
    client = SimpleNamespace(log_dir=tmp_path / 'provider')
    def make_query(**kw):
        events.append('query')
        return query
    def embed(**kw):
        events.append('embedding')
        return [[1.0]], {}
    def retrieve(**kw):
        events.append('retrieve')
        return [card]
    def plan(**kw):
        assert events == ['query', 'embedding', 'retrieve']
        assert kw['edit_count'] == 4
        assert kw['retrieved_cards'][0]['capability_id'] == 'inspiration'
        events.append('plan')
        payload = _retrieval_plan_payload()
        payload['module_plan'] = payload['module_plan'][:4]
        payload['dependency_plan'] = ['q3']
        return payload
    client.embeddings = embed
    monkeypatch.setattr(runner, 'generate_seed_retrieval_query', make_query)
    monkeypatch.setattr(runner, 'retrieve_top_k_cards', retrieve)
    monkeypatch.setattr(runner, 'generate_seed_retrieval_plan', plan)
    kwargs = dict(seed={'seed_id':'host', 'original_instruction':'Browse items'}, observation={},
                  embedded_pool=[card], top_k=1, max_per_family=1, run_dir=tmp_path,
                  query_client=client, embedding_client=client, edit_count=4)
    result = runner.load_or_retrieve(**kwargs)
    assert len(result['module_plan']) == 4
    assert runner.load_or_retrieve(**kwargs) == result
    assert events == ['query','embedding','retrieve','plan']
    with pytest.raises(ValueError, match='different requested edit count'):
        runner.load_or_retrieve(**{**kwargs, 'edit_count':6})


def test_planner_rejects_wrong_count_and_accepts_readable_state():
    payload = _retrieval_plan_payload()
    payload['module_plan'][2]['reverse_failure'] = 'Without visible saved items, the user cannot complete the downstream workflow.'
    client = SimpleNamespace(chat_json=lambda **kw: (payload, {}))
    with pytest.raises(ValueError, match='requested edit_count'):
        generate_seed_retrieval_plan(seed={'original_instruction':'Browse items'}, observation={},
            client=client, request_id='unit', edit_count=4)
    result = generate_seed_retrieval_plan(seed={'original_instruction':'Browse items'}, observation={},
        client=client, request_id='unit', edit_count=8)
    assert len(result['module_plan']) == 8


def test_embedding_identity_prevents_stale_cache_and_obeys_bounds(tmp_path):
    pool = tmp_path / 'pool.jsonl'
    row = dict(capability_id='a', summary='Select rows', visible_result='Selected rows shown')
    pool.write_text(json.dumps(row)+'\n')
    calls=[]
    def embeddings(**kw):
        calls.append(kw)
        return [[1.0, 0.0]], {}
    client = SimpleNamespace(embedding_model='model', base_url='https://example.invalid',
        log_dir=tmp_path/'provider', embeddings=embeddings)
    kwargs=dict(pool_path=pool,run_dir=tmp_path/'vectors',client=client,dimensions=2)
    assert len(embed_pool(**kwargs)) == 1
    assert len(embed_pool(**kwargs)) == 1
    assert len(calls) == 1
    pool.write_text(json.dumps({**row,'summary':'Changed content'})+'\n')
    with pytest.raises(ValueError, match='immutable output differs'):
        embed_pool(**kwargs)
    with pytest.raises(ValueError, match='bound'):
        embed_pool(**{**kwargs,'run_dir':tmp_path/'bounded','max_cards':0})


def test_generation_saves_without_an_independent_review_call(tmp_path, monkeypatch):
    monkeypatch.setattr(runner,'generate_edit_sequence',lambda **kw: {'edit_count':4,'edits':[]})
    client = SimpleNamespace(chat_json=lambda **kw: pytest.fail('Unexpected extra LLM call'))
    result = runner.load_or_generate(seed={'seed_id':'host'},observation={},
        retrieval=dict(cards=[],module_plan=[{}]*4,pool_snapshot_sha256='hash',
                       retrieval_query_sha256='query',top_k=1,retrieved_capability_ids=[],dependency_plan=[]),
        run_dir=tmp_path,client=client,edit_count=4)
    assert (tmp_path/'candidates/host.json').exists()
    assert (tmp_path/'sequences/host.json').exists()
    assert 'instruction_review' not in result
    assert not (tmp_path/'quality').exists()


def test_cached_sequence_does_not_require_review(tmp_path, monkeypatch):
    saved = {'edit_count': 4, 'edits': [], 'retrieval': {}}
    (tmp_path/'sequences').mkdir()
    (tmp_path/'sequences/host.json').write_text(json.dumps(saved))
    monkeypatch.setattr(runner, 'validate_edit_sequence', lambda value, **kw: value)
    client = SimpleNamespace(chat_json=lambda **kw: pytest.fail('Unexpected LLM call'))
    result = runner.load_or_generate(seed={'seed_id':'host', 'files': {}}, observation={},
        retrieval=dict(cards=[], module_plan=[{}]*4), run_dir=tmp_path,
        client=client, edit_count=4)
    assert result == saved


def test_audit_uses_semantic_decision_without_requiring_category_labels():
    payload = _accepted_quality_audit()
    assert validate_quality_audit(payload, seed_id='seed-a')['sequence_decision']=='accept'
    payload['edits'][0]['decision']='reject'
    with pytest.raises(ValueError,match='contains a rejected Edit'):
        validate_quality_audit(payload, seed_id='seed-a')


def test_depth_guidance_reaches_planning_and_audit_requests():
    """Request wiring only; real-model depth discrimination is a separate remote experiment."""
    from instruction_augmentation import linear_edit_queries as queries
    calls = []
    def planning(**kwargs):
        calls.append(kwargs)
        return _retrieval_plan_payload(), {}
    generate_seed_retrieval_plan(seed={'original_instruction': 'Browse items'}, observation={},
        client=SimpleNamespace(chat_json=planning), request_id='depth-plan', edit_count=8)
    def auditing(**kwargs):
        calls.append(kwargs)
        return _accepted_quality_audit(), {}
    queries.audit_edit_sequence(seed={'seed_id': 'seed-a', 'files': {}}, observation={},
        sequence={'edit_count': len(_accepted_quality_audit()['edits'])},
        client=SimpleNamespace(chat_json=auditing), request_id='depth-audit')
    assert all(queries.WEBCOMPASS_EDIT_POLICY in call['system_prompt'] for call in calls)
    assert queries.WEBCOMPASS_EDIT_POLICY in queries.GENERATION_SYSTEM
    assert 'Before freezing' in calls[0]['task']
    assert 'needs_replanning' in calls[1]['task']
    assert 'prior approval' in calls[1]['task']


def test_named_depth_evidence_preserves_verdict_and_canonical_list():
    payload = _accepted_quality_audit()
    evidence = dict(family_fit='Fits the family.', interaction_depth='Shared state changes.',
                    observable_acceptance='Observe the resulting update.')
    payload['edits'][0]['evidence'] = evidence
    result = validate_quality_audit(payload, seed_id='seed-a')
    assert result['edits'][0]['evidence'] == [f'{k}: {v}' for k, v in evidence.items()]
    payload['edits'][0].update(decision='reject', issues=['Shallow capability.'])
    payload['sequence_decision'] = 'reject'
    payload['sequence_issues'] = [{'edit_id': 'q1', 'issue': 'Needs replanning.'}]
    result = validate_quality_audit(payload, seed_id='seed-a')
    assert result['sequence_decision'] == 'reject'
    assert result['sequence_issues'] == ['q1: Needs replanning.']
    payload['edits'][0]['evidence'] = {'family_fit': 'Incomplete evidence object'}
    with pytest.raises(ValueError, match='three depth judgments'):
        validate_quality_audit(payload, seed_id='seed-a')


def test_diagnosed_revision_reuses_candidate_in_one_generation_call(monkeypatch):
    from instruction_augmentation import linear_edit_queries as queries
    captured = []
    candidate = {'edits': [{'edit_id': 'q1', 'instruction': 'Existing complete capability'}]}
    client = SimpleNamespace(chat_json=lambda **kw: (captured.append(kw) or candidate, {}))
    monkeypatch.setattr(queries, 'generation_stable_prefix', lambda *a, **kw: 'Shared rules')
    monkeypatch.setattr(queries, 'generation_task', lambda *a, **kw: 'Host evidence and frozen plan')
    monkeypatch.setattr(queries, 'planner_host_evidence_corpus', lambda *a: 'Host evidence')
    monkeypatch.setattr(queries, 'normalize_repeated_instruction_openings', lambda x: x)
    monkeypatch.setattr(queries, 'validate_edit_sequence', lambda payload, **kw: payload)
    result = queries.generate_edit_sequence(seed={'seed_id':'host'}, observation={},
        capability_bank={'capabilities':[]}, client=client, request_id='revision', edit_count=4,
        revision_candidate=candidate, revision_feedback='Replace the assembled quote with a real excerpt.')
    assert result == candidate
    assert len(captured) == 1
    assert json.dumps(candidate) in captured[0]['task']
    assert 'Replace the assembled quote' in captured[0]['task']
