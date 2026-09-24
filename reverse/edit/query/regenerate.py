"""Text-Edit instruction regeneration, excluding 1-3 subtasks from new output.

Prepare is offline. Run requires a dedicated key environment variable and a verified
one-case smoke receipt before concurrency > 1. Each case runs in a killable process.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import fcntl
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import random
import re
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from reverse.web_coding_demo.synthetic.official_catalog import edit_catalog
from reverse.web_coding_demo.synthetic.official_prompts import EDIT_SYSTEM_PROMPT, edit_prompt
from reverse.edit.gt.prepare_0905 import records, source_code, sha256

VERSION = 4

# Central 80% word-count bands measured from the frozen official WebCompass
# Edit snapshot. Four-task rows are predominantly labelled easy; individual
# descriptions become shorter as the compound task grows.
WEBCOMPASS_WORD_BANDS = {
    4: (95, 135),
    5: (90, 125),
    6: (85, 125),
    7: (80, 115),
    8: (75, 110),
    9: (75, 105),
    10: (70, 105),
    11: (70, 100),
    12: (65, 95),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def event(root, kind, **fields):
    with (root/'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(time=time.time(), event=kind, **fields), ensure_ascii=False)+'\n')


def select_types(original, seed, identity):
    catalog, _ = edit_catalog()
    if not isinstance(original, list) or not original or any(not isinstance(t, str) or not t for t in original):
        raise ValueError('missing/invalid task_type list')
    if len(original) > len(catalog) or len(set(original)) != len(original):
        raise ValueError('task count exceeds 16 or original types contain duplicates')
    if all(t in catalog for t in original):
        return list(original), 'reuse_all'
    # Latest user rule: ANY invalid type means resample the ENTIRE group.
    return random.Random(f'{seed}:{identity}').sample(catalog, len(original)), 'resample_all'


def make_prompt(code, types):
    _, catalog = edit_catalog()
    if not code or any(set(('path','code')) - f.keys() or not isinstance(f['code'], str) for f in code):
        raise ValueError('missing/invalid source code')
    if any(t not in catalog for t in types):
        raise ValueError('unsupported task type')
    guidelines = ''.join(f'Task {i}: {t}\n  Guideline: {catalog[t]}\n\n' for i,t in enumerate(types,1))
    context = '<code_context>\n' + ''.join(f'<file path="{f["path"]}">\n{f["code"]}\n</file>\n' for f in code) + '</code_context>'
    low, high = WEBCOMPASS_WORD_BANDS[len(types)]
    alignment = f"""

WEBCompass DIFFICULTY ALIGNMENT:
- Match the scope of official WebCompass Edit rows with {len(types)} task types.
- Write {low}-{high} English words for EACH requirement.
- Treat each task type as one coherent feature. Cover its core UI, interaction,
  state change, and persistence/loading behavior only when the category calls for it.
- Do not expand one task type into adjacent product systems, extra roles, secondary
  workflows, or multiple independent analytics/views.
- The combined difficulty comes from implementing all {len(types)} requested features;
  do not make every individual feature an end-to-end product redesign.
"""
    return edit_prompt(
        guidelines, json.dumps(types, ensure_ascii=False), context, len(types)
    ) + alignment


def description_word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def validate_webcompass_difficulty(values):
    low, high = WEBCOMPASS_WORD_BANDS[len(values)]
    counts = [description_word_count(item['description']) for item in values]
    if any(not low <= count <= high for count in counts):
        raise ValueError(
            f'description word counts {counts} outside WebCompass {len(values)}-task '
            f'band {low}-{high}'
        )
    return values


def strip_trailing_commas(text):
    """Remove only commas before closing JSON containers, never inside strings."""
    out = []
    quoted = escaped = False
    for i, char in enumerate(text):
        if quoted:
            out.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        else:
            if char == '"':
                quoted = True
            if char == ',' and text[i+1:].lstrip().startswith(('}', ']')):
                continue
            out.append(char)
    return ''.join(out)


def parse_output(raw, types):
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:xml|json)?\s*', '', text, count=1)
        text = re.sub(r'\s*```$', '', text, count=1)
    match = re.fullmatch(r'<description>\s*(.*?)\s*</description>', text, re.S)
    if not match:
        raise ValueError('expected description-only XML; code/GT/extra text rejected')
    body = match[1].strip()
    if body.startswith('<![CDATA[') and body.endswith(']]>'):
        body = body[9:-3].strip()
    # A whole JSON document may be HTML-escaped; decode only when its keys are
    # escaped, not descriptions in an otherwise valid JSON document.
    if re.match(r'^\[\s*\{\s*&quot;task_type&quot;\s*:',body):
        body=html.unescape(body)
    values = json.loads(strip_trailing_commas(body),strict=False)
    if not isinstance(values, list) or len(values) != len(types):
        raise ValueError('description count mismatch')
    if any(not isinstance(d, dict) or set(d) != {'task_type', 'description'} or
           not isinstance(d['description'], str) or not d['description'].strip() for d in values):
        raise ValueError('invalid instruction schema')
    for d, expected in zip(values, types):
        if isinstance(d['task_type'], str) and html.unescape(d['task_type']) == expected:
            d['task_type'] = expected
    if [d['task_type'] for d in values] != types:
        raise ValueError('task type/order mismatch')
    return values


def input_rows(args):
    if args.cases_dir:
        for path in sorted(args.cases_dir.glob('*.json.gz')):
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                row = json.load(stream)
            yield row.get('instance_id'), row.get('task_types'), row.get('source_code'), dict(path=str(path.resolve()), sha256=sha256(path), modality='prepared')
        return
    index = read_json(args.source_release/'dataset_index.json')
    for task, modality in (('text-edit','text'),):
        path = args.source_release/task/'train-00000-of-00001.jsonl.gz'
        actual = sha256(path)
        if actual != index['tasks'][task]['sha256']:
            raise ValueError(f'source hash mismatch: {task}')
        for line, row in enumerate(records(path),1):
            yield row.get('instance_id'), row.get('task_type'), source_code(row, modality), dict(
                path=str(path.resolve()), sha256=actual, row=line, modality=modality)


def prepare(args):
    out = args.output_dir.resolve()
    if (out/'plan.json').exists():
        raise FileExistsError('plan already exists; use run to resume or a new output directory')
    out.mkdir(parents=True, exist_ok=True)
    jobs, rejected, excluded = {}, [], []
    for identity, original, code, origin in input_rows(args):
        try:
            if not isinstance(identity, str) or not identity:
                raise ValueError('missing instance_id')
            if isinstance(original, list) and 1 <= len(original) <= 3:
                excluded.append(dict(instance_id=identity, task_count=len(original),
                                     origin=origin, reason='exclude_1_to_3_subtasks_from_new_version'))
                continue
            key = digest(dict(instance_id=identity, original_types=original, source_code=code))
            selected, strategy = select_types(original, args.seed, key)
            prompt = make_prompt(code, selected)
            if key not in jobs:
                # Limit unique generation units; retain provenance for duplicates.
                if len(jobs) >= args.limit:
                    continue
                case = dict(job_id=key, instance_id=identity, original_types=original,
                            task_types=selected, strategy=strategy, source_code=code,
                            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
                write_json(out/'cases'/f'{key}.json', case)
                jobs[key] = dict(job_id=key, instance_id=identity, task_count=len(selected),
                                 strategy=strategy, origins=[], case_sha256=digest(case))
            jobs[key]['origins'].append(origin)
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append(dict(instance_id=identity, origin=origin, error=str(exc)))
    config = dict(version=VERSION, model=args.model, base_url=args.base_url.rstrip('/'),
                  wire_api=getattr(args,'wire_api','chat-completions'),
                  actor_authorization=getattr(args,'actor_authorization',None),
                  task='text-edit', min_subtasks=4,
                  seed=args.seed, max_tokens=args.max_tokens, max_attempts=args.max_attempts,
                  request_timeout=args.request_timeout, case_timeout=args.case_timeout,
                  catalog=edit_catalog()[1], system_prompt=EDIT_SYSTEM_PROMPT,
                  prompt_template=edit_prompt('GUIDELINES','TYPES','SOURCE',1),
                  webcompass_word_bands={
                      str(key): list(value)
                      for key, value in WEBCOMPASS_WORD_BANDS.items()
                  })
    plan = dict(config=config, jobs=list(jobs.values()), rejected=rejected, excluded=excluded,
                source_release=str(args.source_release.resolve()) if args.source_release else None,
                cases_dir=str(args.cases_dir.resolve()) if args.cases_dir else None,
                limit=args.limit, created=time.time())
    plan['fingerprint'] = digest(dict(config=config, jobs=plan['jobs']))
    write_json(out/'plan.json', plan)
    print(json.dumps(dict(prepared=len(jobs), rejected=len(rejected), excluded_1_to_3=len(excluded),
                         strategies=dict(collections.Counter(j['strategy'] for j in jobs.values())),
                         task_counts=dict(collections.Counter(j['task_count'] for j in jobs.values())))))


def request_once(payload, config, key, receipt_path):
    import httpx
    receipt = dict(status='started', started=time.time(), usage=None, content='', finish_reason=None)
    write_json(receipt_path, receipt)  # Counts even an interrupted/unknown billed request.
    chunks = []
    try:
        headers={'Authorization':'Bearer '+key}
        if config.get('actor_authorization'):
            headers['x-openai-actor-authorization']=config['actor_authorization']
        endpoint='/responses' if config.get('wire_api')=='responses' else '/chat/completions'
        with httpx.Client(timeout=config['request_timeout']) as client:
            with client.stream('POST', config['base_url']+endpoint,
                               headers=headers, json=payload) as response:
                if response.status_code != 200:
                    body = response.read().decode(errors='replace')
                    fatal = response.status_code in (401,402,403) or any(t in body.lower() for t in ('insufficient_quota','quota_exceeded','credit balance'))
                    receipt.update(status='blocked' if fatal else 'http_error', http_status=response.status_code,
                                   retryable=not fatal and (response.status_code==429 or response.status_code>=500))
                    # No body/headers in logs: upstream responses may echo credentials.
                    return receipt
                for line in response.iter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    chunk = json.loads(data)
                    if config.get('wire_api')=='responses':
                        kind=chunk.get('type')
                        if kind=='response.output_text.delta':
                            chunks.append(chunk.get('delta') or '')
                        elif kind in ('response.completed','response.incomplete','response.failed'):
                            final=chunk.get('response',{})
                            receipt['usage']=final.get('usage') or receipt['usage']
                            receipt['finish_reason']='stop' if kind=='response.completed' and final.get('status')=='completed' else kind
                            if not chunks:
                                chunks.extend(part.get('text','') for item in final.get('output',[])
                                              for part in item.get('content',[]) if part.get('type')=='output_text')
                            if kind=='response.failed':
                                code=str((final.get('error') or {}).get('code',''))
                                status, retryable = classify_api_error(code)
                                receipt.update(status=status, error_code=code,
                                               retryable=retryable)
                                return receipt
                        elif kind=='error':
                            code=str(chunk.get('code',''))
                            status, retryable = classify_api_error(code)
                            receipt.update(status=status, error_code=code,
                                           retryable=retryable)
                            return receipt
                        continue
                    if chunk.get('usage'):
                        receipt['usage'] = chunk['usage']
                    for choice in chunk.get('choices', []):
                        chunks.append(choice.get('delta', {}).get('content') or '')
                        receipt['finish_reason'] = choice.get('finish_reason') or receipt['finish_reason']
                receipt['content'] = ''.join(chunks)
                receipt.update(status='complete' if receipt['finish_reason']=='stop' else 'incomplete',
                               retryable=not chunks)
                return receipt
    except (httpx.HTTPError, ValueError) as exc:
        receipt.update(status='transport_error', error_type=type(exc).__name__, retryable=True)
        return receipt
    finally:
        receipt['content'] = ''.join(chunks)
        receipt['elapsed_seconds'] = round(time.time()-receipt['started'],3)
        write_json(receipt_path, receipt)


def classify_api_error(code):
    lowered = str(code).lower()
    if any(part in lowered for part in ('quota', 'auth', 'credit')):
        return 'blocked', False
    retryable = any(part in lowered for part in (
        'concurrency', 'rate_limit', 'ratelimit', 'overload', 'timeout',
        'temporar', 'unavailable', 'gateway',
    ))
    return 'api_error', retryable


def worker(root, job_id, key_env):
    plan = read_json(root/'plan.json')
    config = plan['config']
    case = read_json(root/'cases'/f'{job_id}.json')
    folder = root/'jobs'/job_id
    folder.mkdir(parents=True, exist_ok=True)
    prompt = make_prompt(case['source_code'], case['task_types'])
    if hashlib.sha256(prompt.encode()).hexdigest() != case['prompt_sha256']:
        raise ValueError('prompt changed since prepare')
    payload = make_payload(config,prompt)
    write_json(folder/'request.json', payload)
    result = dict(job_id=job_id, instance_id=case['instance_id'], task_types=case['task_types'],
                  strategy=case['strategy'], status='error')
    # Recover an already-paid completed response after interruption before result commit.
    old = sorted(folder.glob('attempt-*.json'))
    complete = None
    for receipt in reversed([read_json(p) for p in old]):
        if receipt['status']!='complete':
            continue
        try:
            validate_webcompass_difficulty(
                parse_output(receipt['content'],case['task_types'])
            )
        except (ValueError,KeyError,TypeError):
            # Preserve the paid receipt, but do not repeatedly reuse invalid output.
            continue
        complete=receipt
        break
    if complete is None:
        for attempt in range(len(old)+1, config['max_attempts']+1):
            receipt = request_once(payload, config, os.environ[key_env], folder/f'attempt-{attempt:02}.json')
            if receipt['status']=='blocked':
                result['status']='blocked'
                break
            if receipt['status']=='complete':
                complete=receipt
                break
            if not receipt.get('retryable') or attempt==config['max_attempts']:
                break
            time.sleep(5*attempt)
    if complete is not None:
        try:
            result['descriptions'] = validate_webcompass_difficulty(
                parse_output(complete['content'],case['task_types'])
            )
            result.update(status='ok', generation_seconds=complete['elapsed_seconds'])
        except (ValueError, KeyError, TypeError) as exc:
            result.update(error_type='invalid_output', error=str(exc))
    attempts = [read_json(p) for p in sorted(folder.glob('attempt-*.json'))]
    result.update(attempts=len(attempts), usage_reported_tokens=sum((a.get('usage') or {}).get('total_tokens',0) for a in attempts),
                  usage_unknown_attempts=sum(a.get('usage') is None for a in attempts))
    write_json(folder/'result.json', result)
    return 75 if result['status']=='blocked' else 0


def make_payload(config,prompt):
    if config.get('wire_api')=='responses':
        return dict(model=config['model'],max_output_tokens=config['max_tokens'],stream=True,store=False,
                    instructions=EDIT_SYSTEM_PROMPT,input=[dict(role='user',content=prompt)])
    return dict(model=config['model'], max_tokens=config['max_tokens'], stream=True,store=False,
                stream_options={'include_usage':True}, messages=[dict(role='system',content=EDIT_SYSTEM_PROMPT),dict(role='user',content=prompt)])


async def terminate(process):
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        await asyncio.wait_for(process.wait(),3)
    except asyncio.TimeoutError:
        os.killpg(process.pid,signal.SIGKILL)
        await process.wait()
    except ProcessLookupError:
        await process.wait()


def resource_ok(args):
    if os.getloadavg()[0] > (os.cpu_count() or 1)*args.max_load_per_cpu:
        return False
    if Path('/proc/meminfo').exists():
        fields = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        if int(fields['MemAvailable'].split()[0]) < args.min_free_memory_mb*1024:
            return False
    return True


async def run(args):
    root = args.output_dir.resolve()
    plan = read_json(root/'plan.json')
    config=plan['config']
    expected_bands = {
        str(key): list(value) for key, value in WEBCOMPASS_WORD_BANDS.items()
    }
    if (config['version']!=VERSION or config['catalog']!=edit_catalog()[1] or
            config['system_prompt']!=EDIT_SYSTEM_PROMPT or
            config['prompt_template']!=edit_prompt('GUIDELINES','TYPES','SOURCE',1) or
            config.get('webcompass_word_bands')!=expected_bands):
        raise ValueError('generator changed since prepare; use a new output directory')
    if digest(dict(config=config,jobs=plan['jobs']))!=plan['fingerprint']:
        raise ValueError('plan fingerprint mismatch')
    for job in plan['jobs']:
        if digest(read_json(root/'cases'/f'{job["job_id"]}.json')) != job['case_sha256']:
            raise ValueError('prepared case content changed')
    if getattr(args,'api_key_file',None):
        if args.api_key_file.stat().st_mode & 0o077:
            raise ValueError('credential file must have owner-only permissions')
        os.environ[args.api_key_env]=args.api_key_file.read_text().strip()
    if not os.environ.get(args.api_key_env):
        raise ValueError(f'set the dedicated {args.api_key_env} environment variable; no fallback key is used')
    known = {j['job_id']: read_json(root/'jobs'/j['job_id']/'result.json') for j in plan['jobs']
             if (root/'jobs'/j['job_id']/'result.json').exists()}
    if args.workers>1 and not any(r['status']=='ok' for r in known.values()):
        raise ValueError('first run --workers 1 --limit 1 with this plan; then resume with --workers 10')
    selected_ids=set(getattr(args,'job_id',None) or [])
    if selected_ids-set(j['job_id'] for j in plan['jobs']):
        raise ValueError('requested job is not in the frozen plan')
    pending = [j for j in plan['jobs'] if (not selected_ids or j['job_id'] in selected_ids) and
               (j['job_id'] not in known or (args.retry_failed and known[j['job_id']]['status']!='ok'))][:args.limit]
    stop=asyncio.Event()
    active={}
    tasks=[]
    loop=asyncio.get_running_loop()
    def cancel():
        stop.set()
        for task in tasks:
            task.cancel()
    for sig in (signal.SIGINT,signal.SIGTERM):
        loop.add_signal_handler(sig,cancel)
    iterator=iter(pending)
    start=time.time()
    def progress():
        counts=collections.Counter(r['status'] for r in known.values())
        write_json(root/'progress.json',dict(time=time.time(),elapsed_seconds=round(time.time()-start,2),
            planned=len(plan['jobs']), selected=len(pending), counts=dict(counts), active=active, stopping=stop.is_set()))
    async def dispatch():
        while not stop.is_set():
            while not resource_ok(args):
                await asyncio.sleep(5)
                if stop.is_set():
                    return
            job=next(iterator,None)
            if job is None:
                return
            job_id=job['job_id']
            folder=root/'jobs'/job_id
            folder.mkdir(parents=True,exist_ok=True)
            if (folder/'result.json').exists():
                (folder/'result.json').rename(folder/f'result.previous-{time.time_ns()}.json')
            process=None
            event(root,'case_start',job_id=job_id)
            try:
                with (folder/'worker.log').open('a') as logfile:
                    process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).resolve()),
                        'worker','--output-dir',str(root),'--job-id',job_id,'--api-key-env',args.api_key_env,
                        stdout=logfile,stderr=logfile,start_new_session=True)
                    active[job_id]=process.pid
                    try:
                        await asyncio.wait_for(process.wait(), config['case_timeout'])
                    except asyncio.TimeoutError:
                        await terminate(process)
                        if not (folder/'result.json').exists():
                            write_json(folder/'result.json',dict(job_id=job_id,status='timeout'))
                    if (folder/'result.json').exists():
                        known[job_id]=read_json(folder/'result.json')
                    else:
                        known[job_id]=dict(job_id=job_id,status='error',error_type='worker_exit',returncode=process.returncode)
                        write_json(folder/'result.json',known[job_id])
                    event(root,'case_done',job_id=job_id,status=known[job_id]['status'])
                    if known[job_id]['status']=='blocked':
                        cancel()
            finally:
                if process is not None:
                    await terminate(process)
                active.pop(job_id,None)
                progress()
    async def heartbeat():
        while True:
            progress()
            print(json.dumps(dict(heartbeat=time.time(),active=len(active),statuses=dict(collections.Counter(r['status'] for r in known.values())))),flush=True)
            await asyncio.sleep(15)
    watcher=asyncio.create_task(heartbeat())
    tasks.extend(asyncio.create_task(dispatch()) for _ in range(args.workers))
    try:
        await asyncio.gather(*tasks,return_exceptions=False)
    except asyncio.CancelledError:
        await asyncio.gather(*tasks,return_exceptions=True)
    except BaseException:
        cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher,return_exceptions=True)
        progress()
        event(root,'run_end',stopped=stop.is_set(),counts=dict(collections.Counter(r['status'] for r in known.values())))
        export_results(root,plan,known)
    return 2 if stop.is_set() else 0


def export_results(root, plan, known):
    """Export instructions only, atomically. Never carry stale GT into new records."""
    output=root/'instructions.jsonl'
    temporary=output.with_suffix('.jsonl.tmp')
    tokens, unknown, attempts = 0, 0, 0
    with temporary.open('w',encoding='utf-8') as stream:
        for job in plan['jobs']:
            job_id=job['job_id']
            for path in (root/'jobs'/job_id).glob('attempt-*.json'):
                receipt=read_json(path)
                attempts += 1
                tokens += (receipt.get('usage') or {}).get('total_tokens',0)
                unknown += receipt.get('usage') is None
            result=known.get(job_id,{})
            if result.get('status')!='ok':
                continue
            case=read_json(root/'cases'/f'{job_id}.json')
            record=dict(instance_id=case['instance_id'], job_id=job_id, task='text-edit',
                        task_type=case['task_types'], instruction=dict(src_code=case['source_code'],
                        description=result['descriptions']), origins=job['origins'])
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    temporary.replace(output)
    write_json(root/'summary.json',dict(status_counts=dict(collections.Counter(r['status'] for r in known.values())),
        excluded_1_to_3=len(plan['excluded']), rejected=len(plan['rejected']),
        llm_attempts=attempts, reported_total_tokens=tokens, usage_unknown_attempts=unknown))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='action',required=True)
    prep=subs.add_parser('prepare')
    source=prep.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-release',type=Path)
    source.add_argument('--cases-dir',type=Path,help='Explicitly scoped prepared-case input, e.g. pilot only')
    prep.add_argument('--output-dir',type=Path,required=True)
    prep.add_argument('--limit',type=int,required=True,help='Maximum unique cases, not source records')
    prep.add_argument('--seed',type=int,default=20260921)
    prep.add_argument('--model',default='gpt-5.6-luna')
    prep.add_argument('--base-url',default='https://api.nju-link.com/v1')
    prep.add_argument('--wire-api',choices=('chat-completions','responses'),default='chat-completions')
    prep.add_argument('--actor-authorization',help='Non-secret x-openai-actor-authorization header value')
    prep.add_argument('--max-tokens',type=int,default=8192)
    prep.add_argument('--max-attempts',type=int,choices=range(1,4),default=3)
    prep.add_argument('--request-timeout',type=int,default=180)
    prep.add_argument('--case-timeout',type=int,default=600)
    runner=subs.add_parser('run')
    runner.add_argument('--output-dir',type=Path,required=True)
    runner.add_argument('--workers',type=int,choices=range(1,11),default=10)
    runner.add_argument('--limit',type=int,required=True,help='Maximum cases attempted this invocation')
    runner.add_argument('--api-key-env',default='EDIT_INSTRUCTION_API_KEY')
    runner.add_argument('--api-key-file',type=Path,help='Owner-only credential file; overrides only the dedicated worker environment key')
    runner.add_argument('--retry-failed',action='store_true',help='Retry failed cases within the original cumulative attempt cap')
    runner.add_argument('--job-id',action='append',help='Restrict dispatch to these existing plan jobs')
    runner.add_argument('--max-load-per-cpu',type=float,default=1.5)
    runner.add_argument('--min-free-memory-mb',type=int,default=1024)
    child=subs.add_parser('worker',help=argparse.SUPPRESS)
    child.add_argument('--output-dir',type=Path,required=True)
    child.add_argument('--job-id',required=True)
    child.add_argument('--api-key-env',required=True)
    args=parser.parse_args()
    if hasattr(args,'limit') and args.limit<1:
        parser.error('--limit must be positive')
    if args.action=='run' and (args.max_load_per_cpu<=0 or args.min_free_memory_mb<0):
        parser.error('resource limits must be nonnegative; max-load-per-cpu must be positive')
    if args.action=='worker':
        return worker(args.output_dir,args.job_id,args.api_key_env)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    with (args.output_dir/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='prepare':
            if min(args.request_timeout,args.case_timeout,args.max_tokens)<1:
                parser.error('timeouts and token limit must be positive')
            prepare(args)
            return 0
        return asyncio.run(run(args))


if __name__=='__main__':
    raise SystemExit(main())
