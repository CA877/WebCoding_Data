"""Reclassify captured homepage aliases, preserving all HTML and audit history."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

from .main import document_fingerprint, write_json


def audit(manifest, apply=False):
    rows = {r['source_url']:r for r in
            (json.loads(line) for line in manifest.read_text().splitlines() if line.strip())}
    findings = []
    for row in rows.values():
        if row['status'] != 'pass':
            continue
        project, seen, duplicates = Path(row['project']), {}, []
        for page in row['pages']:
            fingerprint = document_fingerprint((project/page['file']).read_text(),page['render_validation'])
            if fingerprint in seen:
                duplicates.append({'first':seen[fingerprint],'duplicate':page['file']})
            seen[fingerprint] = page['file']
        if not duplicates:
            continue
        findings.append({'source_url':row['source_url'],'project':str(project),'duplicates':duplicates})
        if apply:
            metadata = project/'metadata.json'
            backup = project/'metadata_before_page_dedup.json'
            if metadata.exists() and not backup.exists():
                shutil.copyfile(metadata,backup)
            revised = {**row,'status':'needs_recrawl','quality_status':'candidate',
                       'reason':'duplicate_captured_page','duplicate_pages':duplicates,
                       'reclassified_at':time.time()}
            write_json(metadata,revised)
            with manifest.open('a') as handle:
                handle.write(json.dumps(revised,ensure_ascii=False)+'\n')
                handle.flush()
                os.fsync(handle.fileno())
    return {'applied':apply,'affected':len(findings),'findings':findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    with args.report.open('x') as report:
        result = audit(args.manifest,args.apply)
        report.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
