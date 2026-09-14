"""Collect public directory links as candidates, never as accepted mothers.

Bounded directory downloads, no member-site crawling and no paid API.
Only URLs are retained from the /now TSV, not names or location fields.
"""
import argparse
import csv
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
import httpx

from .main import check_access


SOURCES = {
    '512kb': 'https://512kb.club/',
    '250kb': 'https://250kb.club/',
    '1mb': 'https://1mb.club/',
    'personal': 'https://personalsit.es/',
    'now': 'https://nownownow.com/nownownow.txt',
    'smallweb': 'https://api.github.com/repos/kagisearch/smallweb/contents/smallweb.txt?ref=main',
}
LIGHT = {'512kb','250kb','1mb'}


def extract(kind, text):
    if kind == 'smallweb':
        return [line.strip() for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    if kind == 'now':
        return [row['url'].strip() for row in csv.DictReader(io.StringIO(text),delimiter='\t')]
    soup = BeautifulSoup(text,'html.parser')
    if kind in {'512kb','1mb'}:
        links=soup.select('a.site[href]')
    elif kind == 'personal':
        links=soup.select('a.item-tray__url[href]')
    else:
        links=[a for a in soup.select('a[href]') if a.get_text(strip=True)=='open']
    return [a['href'].strip() for a in links]


def root_candidate(url, kind):
    p=urlsplit(url)
    host=(p.hostname or '').lower()
    if p.scheme not in {'http','https'} or not host or p.username or p.password:
        return None
    if '.' not in host or host.endswith(('.localhost','.local','.internal','.neocities.org')):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    # Do not turn a directory's deep-page recommendation into a different site.
    # /now and Small Web feeds provide discovery signals, not verified homepages.
    if kind not in {'now','smallweb'} and p.path not in {'','/','/index.html','/index.htm'}:
        return None
    if kind in {'now','smallweb'} and '/~' in p.path:
        return None
    if kind == 'smallweb' and host in {
        'feeds.feedburner.com','feeds.feedblitz.com','feedpress.me',
        'www.youtube.com','youtube.com','medium.com','www.medium.com',
        'buttondown.email','buttondown.com','www.reddit.com','reddit.com',
    }:
        return None
    return urlunsplit((p.scheme,p.netloc,'/','',''))


def merge(entries):
    rows={}
    for kind, urls in entries:
        for original in urls:
            url=root_candidate(original,kind)
            if not url:
                continue
            host=(urlsplit(url).hostname or '').removeprefix('www.')
            row=rows.setdefault(host,{'url':url,'host':host,'sources':[]})
            source={'directory':SOURCES[kind],'kind':kind,'listed_url':original}
            if source not in row['sources']:
                row['sources'].append(source)
    def priority(row):
        memberships={s['kind'] for s in row['sources']}
        light=bool(memberships & LIGHT)
        return (not (light and 'now' in memberships),not light,
                not ('now' in memberships),'personal' not in memberships)
    return sorted(rows.values(),key=priority)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--proxy',default='')
    parser.add_argument('--source',action='append',choices=list(SOURCES),
                        help='Fetch only selected sources; repeat to combine')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    cache={}; entries=[]; evidence=[]; start=time.monotonic()
    with httpx.Client(proxy=args.proxy or None,trust_env=False,timeout=20,
                      follow_redirects=False) as client:
        for kind in dict.fromkeys(args.source or SOURCES):
            url=SOURCES[kind]
            if time.monotonic()-start>180:
                raise TimeoutError('directory_collection_deadline')
            check_access(url,args.proxy,cache)
            headers={'Accept':'application/vnd.github.raw+json'} if kind=='smallweb' else {}
            with client.stream('GET',url,headers=headers) as response:
                response.raise_for_status()
                parts=[]; size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>8_000_000:
                        raise ValueError('directory_response_too_large')
                    parts.append(chunk)
                body=b''.join(parts)
            urls=extract(kind,body.decode('utf-8-sig'))
            if not urls:
                raise ValueError('empty_directory:'+url)
            entries.append((kind,urls))
            evidence.append({'url':url,'kind':kind,'bytes':len(body),
                'sha256':hashlib.sha256(body).hexdigest(),'listed_entries':len(urls)})
            print(json.dumps(evidence[-1]),flush=True)
    rows=merge(entries)
    (args.output/'urls.txt').write_text(''.join(r['url']+'\n' for r in rows))
    (args.output/'manifest.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    summary={'count':len(rows),'status':'url_candidates_only','sources':evidence,
             'fetched_at':time.time(),'target_sites_not_probed':True,
             'ordering':'lightweight_and_now_overlap_then_lightweight_then_now_then_personal'}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
