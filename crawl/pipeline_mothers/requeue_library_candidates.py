"""Schedule one bounded retry after the verified-library identity fix.

Run only with the producer stopped. Original attempts and manifest rows stay
intact. A banner identifies a retry candidate, never a public-library verdict.
"""
import argparse
import json
import os
from pathlib import Path
import re
import time


VERSION = 'library_identity_variants_20260908_v2'
BANNER = re.compile(rb'jQuery(?: JavaScript Library)? v\d+\.\d+\.\d+|Bootstrap\s+v\d+\.\d+\.\d+')


def requeue(manifest, report):
    history = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    latest = {r['source_url']:r for r in history}
    scheduled = {r['source_url'] for r in history if r.get('retry_version') == VERSION}
    selected = []
    for row in latest.values():
        if (row['source_url'] in scheduled or row.get('status') != 'rejected'
                or not row.get('reason','').startswith('saved_code_tokens_over_limit')):
            continue
        files = list((Path(row['project'])/'code').glob('*'))
        if not any(p.is_file() and p.suffix in {'.js','.css'}
                   and BANNER.search(p.read_bytes()[:1500]) for p in files):
            continue
        selected.append(dict(row, status='needs_recrawl', reason=VERSION,
                             previous_reason=row['reason'], retry_version=VERSION,
                             retry_scheduled_at=time.time()))
    summary = {'version':VERSION,'scheduled':len(selected),
               'source_urls':[r['source_url'] for r in selected]}
    # Exclusive report creation also prevents accidentally reusing an invocation.
    with report.open('x') as handle:
        json.dump(summary,handle,indent=2)
    with manifest.open('a') as handle:
        for row in selected:
            handle.write(json.dumps(row,ensure_ascii=False)+'\n')
        handle.flush()
        os.fsync(handle.fileno())
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(requeue(args.manifest,args.report),ensure_ascii=False))
