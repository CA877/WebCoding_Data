"""Inventory source framework evidence; never classify by website prose."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re


def stack(code):
    evidence=set()
    unknown=False
    for item in code:
        name=item.get('path','').lower()
        text=item.get('code','')
        if name.endswith('package.json'):
            try:
                package=json.loads(text)
                deps={**package.get('dependencies',{}),**package.get('devDependencies',{})}
                for key in ('react','vue'):
                    if key in deps:evidence.add(key)
            except (ValueError,TypeError):unknown=True
        if name.endswith('.vue'):evidence.add('vue')
        if re.search(r'''(?:from\s*|require\s*\(\s*|import\s*)["'](?:react|react-dom)(?:[/"'])''',text):evidence.add('react')
        if re.search(r'''(?:from\s*|require\s*\(\s*|import\s*)["']vue(?:[/"'])''',text):evidence.add('vue')
        # Browser runtime/CDN use must include the runtime API, not just a named asset.
        if re.search(r'\bReactDOM\s*\.\s*(?:render|createRoot|hydrateRoot)\s*\(',text):evidence.add('react')
        if re.search(r'\b(?:Vue\s*\.\s*createApp\s*\(|new\s+Vue\s*\()',text):evidence.add('vue')
        if name.endswith(('.jsx','.tsx')) and not evidence:unknown=True
    if len(evidence)==1:return next(iter(evidence))
    if evidence:return 'mixed'
    return 'unknown' if unknown else 'vanilla'


def main(root):
    for name in ('0905_text_edit_instructions_luna_20260921','0905_text_edit_instructions_8to12_combined_luna_20260921'):
        run=root/'runs'/name
        plan=json.loads((run/'plan.json').read_text())
        counts=collections.Counter()
        examples={}
        for job in plan['jobs']:
            case=json.loads((run/'cases'/f'{job["job_id"]}.json').read_text())
            kind=stack(case['source_code'])
            attempted=bool(list((run/'jobs'/job['job_id']).glob('attempt-*.json')))
            counts[('attempted' if attempted else 'unstarted',kind)]+=1
            examples.setdefault(kind,case['instance_id'])
        print(name,json.dumps({f'{a}/{b}':n for (a,b),n in counts.items()}),examples,flush=True)
    release=root/'releases/0921'
    for task in ('text-generate','image-generate'):
        counts=collections.Counter(); examples={}
        with gzip.open(release/task/'train-00000-of-00001.jsonl.gz','rt') as stream:
            for line in stream:
                row=json.loads(line)
                code=row.get('response')
                if isinstance(code,dict):code=code.get('files')
                if not isinstance(code,list) or any(not isinstance(f,dict) or 'code' not in f for f in code):
                    counts['unsupported_schema']+=1
                    examples.setdefault('schema', {k:type(v).__name__ for k,v in row.items()})
                    continue
                kind=stack(code);counts[kind]+=1
                examples.setdefault(kind,row.get('instance_id'))
        print(task,dict(counts),examples,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    main(parser.parse_args().root)
