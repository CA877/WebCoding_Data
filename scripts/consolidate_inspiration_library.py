"""Archive exact pool files and build an ID-indexed, source-portable library view."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from inspiration_library.one_shot_capability_retrieval import compact_planner_card


def consolidate(inventories, output, published_root, supersessions=None):
    output, published_root = Path(output), Path(published_root)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ['archives','sources','modes']:
        (output/folder).mkdir()
    def write(name, value):
        with (output/name).open('x') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
    def jsonl(name, rows):
        with (output/name).open('x') as handle:
            for row in rows:
                handle.write(json.dumps(row,ensure_ascii=False)+'\n')
    by_hash, origins = {}, defaultdict(list)
    for inv in inventories:
        for item in inv['files']:
            path = Path(item['path'])
            if path.is_file():
                by_hash[item['sha256']] = path
            origins[item['sha256']].append({'host':inv['host'],'path':item['path']})
    variants, entries = {}, defaultdict(set)
    for inv in inventories:
        for item in inv['files']:
            digest = item['sha256']
            archive = output/'archives'/f'{digest}.jsonl'
            if not archive.exists():
                source = by_hash.get(digest)
                if source is None or sha256(source.read_bytes()).hexdigest() != digest:
                    raise ValueError(f'missing or changed original pool: {item["path"]}')
                shutil.copyfile(source, archive)
            lines = archive.read_text().splitlines()
            for meta in item['cards']:
                row = json.loads(lines[meta['line']-1])
                key = (meta['mode'],meta['capability_id'])
                version = meta['record_sha256']
                entries[key].add(version)
                if version not in variants:
                    variants[version] = {'card':row, 'origins':[], 'mode':key[0]}
                reference = {'host':inv['host'],'path':item['path'],'line':meta['line'],
                    'archive':str(published_root/'archives'/f'{digest}.jsonl')}
                if reference not in variants[version]['origins']:
                    variants[version]['origins'].append(reference)
    supersessions = supersessions or {}
    cards, index = [], []
    for (mode, capability_id), versions in sorted(entries.items()):
        def rank(version):
            item = variants[version]
            dates = [int(x) for origin in item['origins'] for x in re.findall(r'20\d{6}',origin['path'])]
            return (bool(item['card'].get('source_slices')), max(dates,default=0), version)
        selected = max(versions,key=rank)
        row = variants[selected]['card']
        slices = []
        for source in row.get('source_slices') or []:
            if not isinstance(source.get('content'),str) or not source['content']:
                continue
            content = source['content']
            digest = sha256(content.encode()).hexdigest()
            language = source.get('language','txt')
            if language not in {'html','css','js','ts','tsx','jsx','vue','svelte','astro','scss','sass','less'}:
                language = 'txt'
            relative = Path('sources')/f'{digest}.{language}'
            target = output/relative
            if not target.exists():
                target.write_text(content,encoding='utf-8')
            slices.append({**source,'original_path':source.get('path'),
                'original_start_line':source.get('start_line'),'original_end_line':source.get('end_line'),
                'path':str(published_root/relative),'start_line':1,'end_line':len(content.splitlines()),'sha256':digest})
        card = {**compact_planner_card(row,source_slices=slices), 'mode':mode,
            'source_kind':'live_url' if mode=='url' else 'local_project',
            'source_seed_id':row.get('source_seed_id'), 'library_record_id':selected}
        if row.get('source_url'):
            card['source_url'] = row['source_url']
        if row.get('observation_evidence'):
            card['observation_evidence'] = row['observation_evidence']
        replacement = supersessions.get(capability_id)
        if replacement and (mode,replacement) not in entries:
            raise ValueError('supersession replacement absent')
        index.append({'mode':mode,'capability_id':capability_id,'selected_record_id':selected,
            'record_ids':sorted(versions),'superseded_by':replacement})
        if not replacement:
            cards.append(card)
    jsonl('capability_pool.jsonl',cards)
    for mode in ['url','local_project']:
        jsonl(f'modes/{mode}.jsonl',[c for c in cards if c['mode']==mode])
    write('index.json',index)
    write('versions.json',{key:value['origins'] for key,value in variants.items()})
    host_ids = {inv['host']:{(c['mode'],c['capability_id']) for f in inv['files'] for c in f['cards']}
                for inv in inventories}
    manifest = {'status':'ok','intended_use':'inspiration_reference_collection',
        'unique_ids_including_superseded':len(entries),'active_card_count':len(cards),
        'active_cards_by_mode':dict(Counter(c['mode'] for c in cards)),
        'cards_with_code':sum(bool(c['source_slices']) for c in cards),
        'cards_with_code_by_mode':dict(Counter(c['mode'] for c in cards if c['source_slices'])),
        'unique_record_versions':len(variants),'archived_pool_files':len(origins),
        'supersessions':supersessions,'pool_sha256':sha256((output/'capability_pool.jsonl').read_bytes()).hexdigest(),
        'input_hosts':{inv['host']:{k:inv[k] for k in ['file_count','row_count','unique_ids','total_bytes']} for inv in inventories},
        'overlap_ids':len(set.intersection(*host_ids.values())),
        'selection_policy':'Prefer recorded code, then dated run, then stable hash; semantic variants remain archived.',
        'scope':'Materialized pool/candidate-card files; not URL lists, extraction-only responses, full projects or browser-run directories.'}
    write('manifest.json',manifest)
    return manifest


def verify_snapshot(snapshot, published_root=None):
    snapshot = Path(snapshot)
    published_root = Path(published_root or snapshot)
    manifest = json.loads((snapshot/'manifest.json').read_text())
    data = (snapshot/'capability_pool.jsonl').read_bytes()
    if sha256(data).hexdigest() != manifest['pool_sha256']:
        raise ValueError('pool hash mismatch')
    cards = [json.loads(line) for line in data.decode().splitlines()]
    if len(cards) != manifest['active_card_count'] or len({c['capability_id'] for c in cards}) != len(cards):
        raise ValueError('card count or ID uniqueness mismatch')
    for card in cards:
        for source in card['source_slices']:
            path = snapshot / Path(source['path']).relative_to(published_root)
            if path.read_text() != source['content'] or sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise ValueError('materialized source differs from card')
    for path in (snapshot/'archives').glob('*.jsonl'):
        if sha256(path.read_bytes()).hexdigest() != path.stem:
            raise ValueError('archive hash mismatch')
    return {'status':'ok','cards':len(cards),'sources':len(list((snapshot/'sources').iterdir())),
            'archives':len(list((snapshot/'archives').iterdir()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--published-root',type=Path,required=True)
    parser.add_argument('--supersession-manifest',type=Path)
    args = parser.parse_args()
    supersessions = {}
    if args.supersession_manifest:
        lineage = json.loads(args.supersession_manifest.read_text())['lineage']
        supersessions[lineage['superseded_sort_card']] = lineage['replacement_sort_card']
    print(json.dumps(consolidate([json.loads(p.read_text()) for p in args.inventory],
        args.output,args.published_root,supersessions),ensure_ascii=False))


if __name__ == '__main__':
    main()
