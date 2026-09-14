"""One bounded retry for prior two/three-page candidates under the new minimum.

Run only with production stopped. Preserve original rows; do not mark a result
passed without capture and saved-page navigation under the current policy.
"""
import argparse
import json
import os
from pathlib import Path
import time

VERSION='minimum_two_pages_20260908_v1'


def requeue(manifest,report):
    history=[json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    latest={row['source_url']:row for row in history}
    scheduled={row['source_url'] for row in history if row.get('retry_version')==VERSION}
    selected=[]
    for row in latest.values():
        if (row['source_url'] in scheduled or row.get('status')!='rejected'
                or row.get('reason')!='requires_exactly_four_pages'
                or not 2<=len(row.get('pages',[]))<=3):
            continue
        selected.append(dict(row,status='needs_recrawl',reason=VERSION,
            previous_reason=row['reason'],retry_version=VERSION,retry_scheduled_at=time.time()))
    summary={'version':VERSION,'scheduled':len(selected),'source_urls':[r['source_url'] for r in selected]}
    with report.open('x') as handle:
        json.dump(summary,handle,indent=2)
    with manifest.open('a') as handle:
        for row in selected:
            handle.write(json.dumps(row,ensure_ascii=False)+'\n')
        handle.flush()
        os.fsync(handle.fileno())
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(requeue(args.manifest,args.report)))
