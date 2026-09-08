"""Bounded inventory of existing pool files; does not crawl or invoke an LLM."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time


POOL_NAMES = {'capability_pool.jsonl', 'embedded_capability_pool.jsonl', 'candidate_cards.jsonl'}
PRUNE = {'.git', '.venv', 'node_modules', 'code', 'provider', 'provider_mining',
         'browser_scan', 'browser_deep', 'screenshots', 'components'}


def inventory(roots, *, host, max_files=300, max_bytes=128*1024*1024, seconds=45):
    started = time.monotonic()
    files, errors, total_bytes = [], [], 0
    seen = set()
    for root in roots:
        root = Path(root).resolve()
        if not root.exists():
            errors.append({'path':str(root), 'error':'root_missing'})
            continue
        for directory, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in PRUNE and not Path(directory, d).is_symlink()]
            if time.monotonic() - started > seconds:
                raise TimeoutError('inventory deadline reached; no complete inventory produced')
            for name in sorted(names):
                if name not in POOL_NAMES:
                    continue
                path = Path(directory, name)
                if path.is_symlink() or str(path) in seen:
                    continue
                seen.add(str(path))
                total_bytes += path.stat().st_size
                if len(files) >= max_files or total_bytes > max_bytes:
                    raise ValueError('inventory file/byte bound exceeded')
                data = path.read_bytes()
                cards = []
                for line_no, line in enumerate(data.decode('utf-8').splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        card = json.loads(line)
                        if not isinstance(card, dict) or not card.get('capability_id') or not card.get('summary'):
                            raise ValueError('not a capability card with summary')
                        # Only remove vector representations for exact record comparison.
                        record = {k:v for k,v in card.items() if k not in {'embedding','embedding_model','embedding_dimensions'}}
                        fingerprint = sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                        mode = 'url' if card.get('source_url') or card.get('source_kind') == 'live_url' else 'local_project'
                        cards.append({'line':line_no, 'capability_id':card['capability_id'],
                            'mode':mode, 'record_sha256':fingerprint,
                            'has_code':bool(card.get('source_slices')),
                            'slice_count':len(card.get('source_slices') or [])})
                    except (ValueError, TypeError) as exc:
                        errors.append({'path':str(path),'line':line_no,'error':str(exc)})
                files.append({'path':str(path),'relative_path':str(path.relative_to(root)),
                    'root':str(root),'bytes':len(data),'sha256':sha256(data).hexdigest(),'cards':cards})
    cards = [c for f in files for c in f['cards']]
    return {'host':host,'roots':[str(Path(r).resolve()) for r in roots], 'files':files,'errors':errors,
        'file_count':len(files),'row_count':len(cards),'total_bytes':total_bytes,
        'unique_ids':len({(c['mode'],c['capability_id']) for c in cards}),
        'unique_records':len({c['record_sha256'] for c in cards}),
        'elapsed_seconds':round(time.monotonic()-started,2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root, host=args.host)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in {'files','roots','errors'}},ensure_ascii=False))
    if result['errors']:
        print(json.dumps({'errors':result['errors']},ensure_ascii=False))


if __name__ == '__main__':
    main()
