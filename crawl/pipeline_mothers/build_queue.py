"""Merge existing site pools, preserving ordered provenance and unique hosts."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def build(pools, ranking=None):
    seen, rows, sources = set(), [], []
    estimates = {}
    if ranking:
        body = ranking.read_bytes()
        sources.append({'path':str(ranking),'sha256':hashlib.sha256(body).hexdigest(),
                        'role':'historical_cost_order_only'})
        for line in body.decode().splitlines():
            item = json.loads(line)
            for key in ['url','final_url']:
                host = (urlsplit(item.get(key,'')).hostname or '').removeprefix('www.')
                if host:
                    estimates[host] = item
    for pool in pools:
        body = pool.read_bytes()
        sources.append({'path':str(pool),'sha256':hashlib.sha256(body).hexdigest()})
        candidates = body.decode().splitlines()
        if estimates:
            def cost(original):
                host = (urlsplit(original.strip()).hostname or '').removeprefix('www.')
                item = estimates.get(host)
                if not item:
                    return (1,0,0,0,0)
                return (0, not item.get('historical_multi_page',False),
                        item.get('html_bytes',0) > 60000,
                        item.get('script_tag_count',0), item.get('html_bytes',0))
            candidates.sort(key=cost)
        for original in candidates:
            original = original.strip()
            parts = urlsplit(original)
            if parts.scheme not in {'http','https'} or not parts.hostname:
                continue
            host = parts.hostname.lower().removeprefix('www.')
            if host in seen:
                continue
            seen.add(host)
            rows.append({'url':urlunsplit((parts.scheme,parts.netloc,'/','','')),
                         'original_url':original,'source_pool':str(pool),'host':host})
    return rows, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ranking', type=Path,
                        help='Historical preflight JSONL; order only, never an admission gate')
    args = parser.parse_args()
    # Do not overwrite an input snapshot or an already-used queue.
    args.output.mkdir(parents=True, exist_ok=False)
    rows, sources = build(args.pool,args.ranking)
    (args.output/'urls.txt').write_text(''.join(x['url']+'\n' for x in rows))
    (args.output/'manifest.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
    summary = {'count':len(rows),'sources':sources,'status':'url_candidates_only',
               'order':'pool_priority_then_historical_multipage_html_script_cost' if args.ranking else 'pool_priority'}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__ == '__main__':
    main()
