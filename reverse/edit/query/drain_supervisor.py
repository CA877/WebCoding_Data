"""Drain an older supervisor without cancelling paid worker requests (Linux only)."""
import argparse
import json
import os
from pathlib import Path
import signal
import time


def process(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()
        return fields
    except FileNotFoundError:
        return None


def drain(pid, run):
    cmd=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    if b'run' not in cmd or str(run).encode() not in cmd or not any(b'reverse/edit/query/regenerate.py' in x for x in cmd):
        raise ValueError('not the expected generation supervisor')
    timeout=json.loads((run/'plan.json').read_text())['config']['case_timeout']
    stopped=False
    try:
        os.kill(pid,signal.SIGSTOP); stopped=True
        children={}
        for p in Path('/proc').iterdir():
            if not p.name.isdigit(): continue
            stat=process(int(p.name))
            if stat and int(stat[1])==pid and stat[0]!='Z':
                args=(p/'cmdline').read_bytes().split(b'\0')
                if b'worker' not in args or str(run).encode() not in args:
                    raise ValueError('unexpected child')
                job=args[args.index(b'--job-id')+1].decode()
                children[int(p.name)]=(job,int(stat[19])/os.sysconf('SC_CLK_TCK'))
        print(json.dumps({'draining_pid':pid,'workers':children}),flush=True)
        while children:
            uptime=float(Path('/proc/uptime').read_text().split()[0])
            for child,(job,start) in list(children.items()):
                stat=process(child)
                if not stat or stat[0]=='Z':
                    result=run/'jobs'/job/'result.json'
                    if not result.exists():
                        result.write_text(json.dumps(dict(job_id=job,status='error',error_type='worker_exit_during_drain')))
                    del children[child]
                elif uptime-start>timeout:
                    os.killpg(child,signal.SIGKILL)
                    print(json.dumps({'case_timeout':job}),flush=True)
            print(json.dumps({'remaining_workers':len(children)}),flush=True)
            if children: time.sleep(5)
        # Children have exited and their durable results are retained. No dispatch race.
        os.kill(pid,signal.SIGKILL); stopped=False
        print(json.dumps({'drained':True,'pid':pid}),flush=True)
    finally:
        if stopped:
            os.kill(pid,signal.SIGCONT)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--run',type=Path,required=True)
    a=p.parse_args();drain(a.pid,a.run)
