import ast
import gzip
import json
import os
import re
import signal
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from reverse.edit.query import regenerate as m


TYPES = ['Data Table', 'Tree View', 'Real-time Dashboard', 'Skeleton Loading']
CODE = [{'path':'index.html', 'code':'<main>Example existing webpage</main>'}]


def config(tmp_path, **changes):
    values = dict(output_dir=tmp_path/'out', cases_dir=tmp_path/'cases', source_release=None,
                  limit=10, seed=42, model='test-local-fixture', base_url='http://127.0.0.1:1/v1',
                  max_tokens=8192, max_attempts=3, request_timeout=5, case_timeout=10)
    values.update(changes)
    return SimpleNamespace(**values)


def put_case(root, identity, types):
    root.mkdir(parents=True, exist_ok=True)
    with gzip.open(root/f'{identity}.json.gz','wt') as stream:
        json.dump(dict(instance_id=identity,task_types=types,source_code=CODE,
                       descriptions=[{'description':'OLD_SENTINEL'}],response='OLD_GT'),stream)


def aligned_description():
    return ' '.join(['behavior'] * 100)


def test_keep_all_valid_and_resample_entire_invalid_group():
    assert m.select_types(TYPES,42,'id') == (TYPES,'reuse_all')
    old = ['Carousel',*TYPES[1:]]
    selected,strategy=m.select_types(old,42,'id')
    assert strategy=='resample_all'
    assert selected==m.random.Random('42:id').sample(m.edit_catalog()[0],len(old))
    assert len(set(selected))==4 and all(t in m.edit_catalog()[0] for t in selected)
    assert m.select_types(old,42,'id')[0]==selected
    with pytest.raises(ValueError):
        m.select_types(['Data Table']*4,42,'id')


def test_text_only_filter_and_source_preservation(tmp_path):
    source=tmp_path/'release'
    (source/'text-edit').mkdir(parents=True)
    shard=source/'text-edit'/'train-00000-of-00001.jsonl.gz'
    with gzip.open(shard,'wt') as stream:
        for i in range(1,5):
            stream.write(json.dumps(dict(instance_id=str(i),task_type=TYPES[:i],
                instruction=dict(src_code=CODE,description='OLD_SENTINEL'),response='OLD_GT'))+'\n')
    before=m.sha256(shard)
    m.write_json(source/'dataset_index.json',dict(tasks={'text-edit':{'sha256':before}}))
    # No image-edit shard or index entry exists: a text-only run must work.
    args=config(tmp_path,source_release=source,cases_dir=None)
    m.prepare(args)
    plan=m.read_json(args.output_dir/'plan.json')
    assert len(plan['jobs'])==1 and len(plan['excluded'])==3
    assert {x['task_count'] for x in plan['excluded']}=={1,2,3}
    assert plan['jobs'][0]['origins'][0]['modality']=='text'
    assert m.sha256(shard)==before
    contents=(args.output_dir/'cases'/f'{plan["jobs"][0]["job_id"]}.json').read_text()
    assert 'OLD_SENTINEL' not in contents and 'OLD_GT' not in contents


def test_bad_shard_hash_prevents_preparation(tmp_path):
    source=tmp_path/'release'
    (source/'text-edit').mkdir(parents=True)
    (source/'text-edit'/'train-00000-of-00001.jsonl.gz').write_bytes(b'wrong')
    m.write_json(source/'dataset_index.json',{'tasks':{'text-edit':{'sha256':'wrong'}}})
    with pytest.raises(ValueError,match='hash mismatch'):
        m.prepare(config(tmp_path,source_release=source,cases_dir=None))


def test_original_prompt_plus_webcompass_difficulty_alignment():
    _,catalog=m.edit_catalog()
    tree=ast.parse((m.ROOT/'reverse/web_coding_demo/synthetic/edit.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='generate_forward_task')
    node=next(n for n in ast.walk(method) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prompt' for t in n.targets))
    context='<code_context>\n<file path="index.html">\n'+CODE[0]['code']+'\n</file>\n</code_context>'
    guidelines=''.join(f'Task {i}: {task}\n  Guideline: {catalog[task]}\n\n' for i,task in enumerate(TYPES,1))
    namespace=dict(task_types=TYPES,task_descriptions_str=guidelines,
                   task_types_json=json.dumps(TYPES),src_code_context=context)
    expected=eval(compile(ast.Expression(node.value),'<demo>','eval'),{'len':len},namespace)
    prompt=m.make_prompt(CODE,TYPES)
    assert prompt.startswith(expected)
    assert 'WEBCompass DIFFICULTY ALIGNMENT' in prompt
    assert 'one coherent feature' in prompt


@pytest.mark.parametrize('wrapper',['<description>{}</description>','<description><![CDATA[{}]]></description>',
                                    '```xml\n<description>{}</description>\n```'])
def test_response_parser(wrapper):
    values=[dict(task_type=t,description='Requested behavior') for t in TYPES]
    assert m.parse_output(wrapper.format(json.dumps(values)),TYPES)==values
    with pytest.raises(ValueError):
        m.parse_output(wrapper.format(json.dumps(values))+'<search_replace/>',TYPES)
    with pytest.raises(ValueError):
        m.parse_output(wrapper.format(json.dumps(values)),list(reversed(TYPES)))


def test_webcompass_difficulty_band_validation():
    values=[dict(task_type=t,description=aligned_description()) for t in TYPES]
    assert m.validate_webcompass_difficulty(values)==values
    values[0]['description']=' '.join(['too']*136)
    with pytest.raises(ValueError,match='outside WebCompass 4-task band'):
        m.validate_webcompass_difficulty(values)


def test_gateway_concurrency_error_is_retryable():
    assert m.classify_api_error('gateway_concurrency_limit') == ('api_error', True)
    assert m.classify_api_error('insufficient_quota') == ('blocked', False)


def test_worker_bounded_retry_and_paid_response_recovery(tmp_path,monkeypatch):
    args=config(tmp_path)
    put_case(args.cases_dir,'one',TYPES)
    m.prepare(args)
    job=m.read_json(args.output_dir/'plan.json')['jobs'][0]
    monkeypatch.setenv('LOCAL_TEST_KEY','not-a-real-key')
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    calls=[]
    def fail(payload,config,key,path):
        calls.append(1)
        r=dict(status='transport_error',retryable=True,usage=None)
        m.write_json(path,r)
        return r
    monkeypatch.setattr(m,'request_once',fail)
    m.worker(args.output_dir,job['job_id'],'LOCAL_TEST_KEY')
    m.worker(args.output_dir,job['job_id'],'LOCAL_TEST_KEY')
    assert len(calls)==3  # Cumulative across restarts, not three more each time.
    values=[dict(task_type=t,description=aligned_description()) for t in TYPES]
    m.write_json(args.output_dir/'jobs'/job['job_id']/'attempt-03.json',dict(status='complete',usage={'total_tokens':12},
                 content='<description>'+json.dumps(values)+'</description>',elapsed_seconds=1))
    m.worker(args.output_dir,job['job_id'],'LOCAL_TEST_KEY')
    assert len(calls)==3
    assert m.read_json(args.output_dir/'jobs'/job['job_id']/'result.json')['status']=='ok'


def test_retry_invalid_paid_output_preserves_receipt(tmp_path,monkeypatch):
    args=config(tmp_path);put_case(args.cases_dir,'one',TYPES);m.prepare(args)
    job=m.read_json(args.output_dir/'plan.json')['jobs'][0]
    folder=args.output_dir/'jobs'/job['job_id']
    old=dict(status='complete',content='<description>broken</description>',usage=None,elapsed_seconds=1)
    m.write_json(folder/'attempt-01.json',old)
    monkeypatch.setenv('LOCAL_TEST_KEY','not-a-real-key')
    calls=[]
    def good(payload,config,key,path):
        calls.append(path.name)
        r=dict(status='complete',content='<description>'+json.dumps([dict(task_type=t,description=aligned_description()) for t in TYPES])+'</description>',usage={'total_tokens':10},elapsed_seconds=1)
        m.write_json(path,r);return r
    monkeypatch.setattr(m,'request_once',good)
    m.worker(args.output_dir,job['job_id'],'LOCAL_TEST_KEY')
    assert calls==['attempt-02.json']
    assert m.read_json(folder/'attempt-01.json')==old
    assert m.read_json(folder/'result.json')['status']=='ok'


def test_escaped_document_and_literal_newline_recovery():
    import html
    raw='[{"task_type":"Data Table","description":"first\nsecond &amp;"}]'
    assert m.parse_output('<description>'+raw+'</description>',['Data Table'])[0]['description']=='first\nsecond &amp;'
    assert m.parse_output('<description>'+html.escape(raw,quote=True)+'</description>',['Data Table'])[0]['description']=='first\nsecond &amp;'


def test_format_recovery_preserves_description():
    raw = '<description>[{"task_type":"Drag &amp; Drop Interface","description":"Keep &amp; and ,} and \\\"quoted\\\" text",},]</description>'
    assert m.parse_output(raw, ['Drag & Drop Interface']) == [dict(
        task_type='Drag & Drop Interface', description='Keep &amp; and ,} and "quoted" text')]
    with pytest.raises(ValueError):
        m.parse_output(raw, ['Data Table'])
    with pytest.raises(ValueError):
        m.parse_output('<description>[{"task_type":"Data Table",,"description":"x"}]</description>', ['Data Table'])


def test_offline_format_recovery_retains_receipts(tmp_path):
    from reverse.edit.query.recover_formats import recover
    args=config(tmp_path)
    put_case(args.cases_dir,'one',TYPES)
    m.prepare(args)
    job=m.read_json(args.output_dir/'plan.json')['jobs'][0]
    folder=args.output_dir/'jobs'/job['job_id']
    original=dict(job_id=job['job_id'],status='error',error_type='invalid_output',
                  error='trailing comma',task_types=TYPES,attempts=1)
    m.write_json(folder/'result.json',original)
    raw=json.dumps([dict(task_type=t,description='Keep ,} verbatim') for t in TYPES])
    m.write_json(folder/'attempt-01.json',dict(status='complete',
        content='<description>'+raw[:-1]+',]</description>',elapsed_seconds=2))
    before=(folder/'attempt-01.json').read_bytes()
    recover(args.output_dir)
    assert m.read_json(folder/'result.json')['status']=='ok'
    assert m.read_json(folder/'result.before-format-recovery.json')==original
    assert (folder/'attempt-01.json').read_bytes()==before
    recover(args.output_dir)
    assert m.read_json(folder/'result.json')['attempts']==1


@pytest.fixture
def local_api():
    state={'requests':[], 'delay':0, 'status':200, 'invalid_first':False, 'paths':[], 'actors':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(payload)
            state['paths'].append(self.path)
            state['actors'].append(self.headers.get('x-openai-actor-authorization'))
            time.sleep(state['delay'])
            self.send_response(state['status'])
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            prompt=payload['input'][0]['content'] if 'input' in payload else payload['messages'][-1]['content']
            requested=re.findall(r'^Task \d+: (.+)$',prompt,re.M)
            values=[dict(task_type=t,description=aligned_description()) for t in requested]
            chunk={'choices':[{'delta':{'content':'<description>'+json.dumps(values)+'</description>'},'finish_reason':'stop'}],
                   'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
            if state['invalid_first'] and len(state['requests'])==1:
                chunk['choices'][0]['delta']['content']='not valid XML'
            try:
                if self.path.endswith('/responses'):
                    events=[dict(type='response.output_text.delta',delta=chunk['choices'][0]['delta']['content']),
                            dict(type='response.completed',response=dict(status='completed',output=[],
                                 usage=dict(input_tokens=10,output_tokens=10,total_tokens=20)))]
                    self.wfile.write(''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode())
                else:
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode())
            except (BrokenPipeError,ConnectionResetError):
                pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1',state
    server.shutdown()
    server.server_close()


def cli(root,*flags,key=True):
    env=dict(os.environ)
    env.pop('EDIT_INSTRUCTION_API_KEY',None)
    if key:
        env['EDIT_INSTRUCTION_API_KEY']='local-protocol-test-key'
    return subprocess.run([sys.executable,str(Path(m.__file__)),'run','--output-dir',str(root),
                           '--max-load-per-cpu','10000','--min-free-memory-mb','0',*flags],
                          env=env,text=True,capture_output=True,timeout=20)


def test_real_supervisor_local_protocol_resume_and_export(tmp_path,local_api):
    url,state=local_api
    args=config(tmp_path,base_url=url)
    for name in ['a','b','c']:
        put_case(args.cases_dir,name,TYPES)
    m.prepare(args)
    assert cli(args.output_dir,'--workers','1','--limit','1',key=False).returncode!=0
    assert not state['requests']
    assert cli(args.output_dir,'--workers','10','--limit','3').returncode!=0
    assert not state['requests']
    first=cli(args.output_dir,'--workers','1','--limit','1')
    assert first.returncode==0,first.stderr
    rest=cli(args.output_dir,'--workers','10','--limit','3')
    assert rest.returncode==0,rest.stderr
    assert len(state['requests'])==3
    assert cli(args.output_dir,'--workers','10','--limit','3').returncode==0
    assert len(state['requests'])==3
    exported=[json.loads(s) for s in (args.output_dir/'instructions.jsonl').read_text().splitlines()]
    assert len(exported)==3 and all('response' not in r and 'patches' not in r for r in exported)
    assert all('OLD_SENTINEL' not in json.dumps(r) for r in exported)
    assert m.read_json(args.output_dir/'summary.json')['reported_total_tokens']==60
    assert m.read_json(args.output_dir/'progress.json')['active']=={}


def test_hard_case_timeout_kills_worker(tmp_path,local_api):
    url,state=local_api
    state['delay']=3
    args=config(tmp_path,base_url=url,case_timeout=1)
    put_case(args.cases_dir,'a',TYPES)
    m.prepare(args)
    result=cli(args.output_dir,'--workers','1','--limit','1')
    assert result.returncode==0,result.stderr
    assert m.read_json(args.output_dir/'progress.json')['counts']=={'timeout':1}
    assert m.read_json(args.output_dir/'progress.json')['active']=={}


def test_auth_blocks_further_dispatch(tmp_path,local_api):
    url,state=local_api
    state['status']=401
    args=config(tmp_path,base_url=url)
    for name in ['a','b']:
        put_case(args.cases_dir,name,TYPES)
    m.prepare(args)
    result=cli(args.output_dir,'--workers','1','--limit','2')
    assert result.returncode==2,result.stderr
    assert len(state['requests'])==1
    assert m.read_json(args.output_dir/'progress.json')['active']=={}


def test_sample_failure_does_not_stop_batch(tmp_path,local_api):
    url,state=local_api
    state['invalid_first']=True
    args=config(tmp_path,base_url=url)
    for name in ['a','b']:
        put_case(args.cases_dir,name,TYPES)
    m.prepare(args)
    result=cli(args.output_dir,'--workers','1','--limit','2')
    assert result.returncode==0,result.stderr
    assert len(state['requests'])==2
    assert m.read_json(args.output_dir/'progress.json')['counts']=={'error':1,'ok':1}


def test_sigterm_cleans_inflight_worker(tmp_path,local_api):
    url,state=local_api
    state['delay']=3
    args=config(tmp_path,base_url=url)
    put_case(args.cases_dir,'a',TYPES)
    m.prepare(args)
    env=dict(os.environ,EDIT_INSTRUCTION_API_KEY='local-protocol-test-key')
    process=subprocess.Popen([sys.executable,str(Path(m.__file__)),'run','--output-dir',str(args.output_dir),
        '--workers','1','--limit','1','--max-load-per-cpu','10000','--min-free-memory-mb','0'],
        env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+5
        while not state['requests'] and time.monotonic()<deadline:
            time.sleep(.02)
        assert state['requests']
        process.send_signal(signal.SIGTERM)
        _,stderr=process.communicate(timeout=5)
        assert process.returncode==2,stderr
        assert m.read_json(args.output_dir/'progress.json')['active']=={}
        # Interrupted request remains counted, so restart cannot reset the budget.
        attempts=list((args.output_dir/'jobs').glob('*/attempt-*.json'))
        assert len(attempts)==1
        assert m.read_json(attempts[0])['status']=='started'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_responses_protocol_and_no_storage(tmp_path,local_api):
    url,state=local_api
    args=config(tmp_path,base_url=url,wire_api='responses',actor_authorization='local-image-extension')
    put_case(args.cases_dir,'a',TYPES)
    m.prepare(args)
    result=cli(args.output_dir,'--workers','1','--limit','1')
    assert result.returncode==0,result.stderr
    assert state['paths']==['/v1/responses']
    assert state['actors']==['local-image-extension']
    request=state['requests'][0]
    assert request['store'] is False and request['stream'] is True
    assert request['instructions']==m.EDIT_SYSTEM_PROMPT
    assert request['input'][0]['content']==m.make_prompt(CODE,TYPES)
    assert 'messages' not in request and 'max_tokens' not in request
    assert m.read_json(args.output_dir/'progress.json')['counts']=={'ok':1}
