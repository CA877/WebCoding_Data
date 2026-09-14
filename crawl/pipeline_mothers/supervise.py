"""Batch supervision independent of chat scheduling; never restarts jobs.

Renew the crawler lease after checking its fresh heartbeat and resources,
including during bounded network recovery. Both processes stay inside one systemd
cgroup. A dead supervisor therefore still expires the crawler's lease.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import httpx


class NetworkWatch:
    def __init__(self, pause_after=3, outage_timeout=300):
        self.pause_after = pause_after
        self.outage_timeout = outage_timeout
        self.failures = 0
        self.failed_since = None
        self.last_error = ''

    def check(self, client, url):
        began = time.monotonic()
        try:
            response = client.head(url)
            error = '' if 200 <= response.status_code < 400 else 'http_' + str(response.status_code)
        except httpx.RequestError as exc:
            error = type(exc).__name__
        if not error:
            self.failures = 0
            self.failed_since = None
            self.last_error = ''
            return 'healthy'
        self.failures += 1
        self.last_error = error
        if self.failed_since is None:
            self.failed_since = began
        if self.failures >= self.pause_after:
            if time.monotonic() - self.failed_since >= self.outage_timeout:
                raise RuntimeError('network_outage_persistent:' + error)
            return 'paused'
        return 'retrying'


def check_heartbeat(snapshot, now, started, stale_after):
    if snapshot.get('updated_at', 0) < started:
        raise RuntimeError('no_current_run_heartbeat')
    if now - snapshot['updated_at'] > stale_after:
        raise RuntimeError('crawler_heartbeat_stale')
    if snapshot.get('status') not in {'running','complete'}:
        raise RuntimeError('crawler_stopped:' + str(snapshot.get('status')))
    if snapshot.get('in_flight', 0) > 8:
        raise RuntimeError('crawler_concurrency_exceeded')


def check_resources(output, *, ignore_host_load=False):
    load = os.getloadavg()[0]
    if not ignore_host_load and load > (os.cpu_count() or 1) * .8:
        raise RuntimeError('shared_host_load_high')
    meminfo = Path('/proc/meminfo')
    available = None
    if meminfo.exists():
        values = {line.split(':')[0]:int(line.split()[1])
                  for line in meminfo.read_text().splitlines()}
        available = values['MemAvailable']
        if available < 16 * 1024**2:
            raise RuntimeError('shared_host_memory_low')
    free = shutil.disk_usage(output).free
    if free < 10 * 1024**3:
        raise RuntimeError('disk_space_low')
    return {'load1':load, 'available_memory_kib':available, 'disk_free_bytes':free}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--lease-file',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--proxy',default='')
    parser.add_argument('--ignore-host-load',action='store_true',
                        help='Explicit authorization only; retain memory/disk/heartbeat protections')
    parser.add_argument('--probe-url',required=True)
    parser.add_argument('--total-timeout',type=float,default=0,
                        help='Batch wall-clock limit in seconds; 0 disables the limit')
    parser.add_argument('--interval',type=float,default=20)
    parser.add_argument('--stale-after',type=float,default=60)
    parser.add_argument('--startup-grace',type=float,default=30)
    parser.add_argument('--network-retry-interval',type=float,default=5)
    parser.add_argument('--network-pause-after',type=int,default=3)
    parser.add_argument('--network-outage-timeout',type=float,default=300)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if (not command or not 0 < args.interval < args.stale_after
            or args.total_timeout < 0 or args.startup_grace <= 0
            or not 0 < args.network_retry_interval < args.stale_after
            or args.network_pause_after < 2 or args.network_outage_timeout <= 0):
        parser.error('command, nonnegative total timeout and positive protection timings required')
    args.output.mkdir(parents=True,exist_ok=True)
    args.lease_file.parent.mkdir(parents=True,exist_ok=True)
    args.log.parent.mkdir(parents=True,exist_ok=True)
    process = None
    pause_file = Path(str(args.lease_file) + '.pause')
    network = NetworkWatch(args.network_pause_after, args.network_outage_timeout)

    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)

    with args.log.open('x') as log, httpx.Client(proxy=args.proxy or None,
            trust_env=False,timeout=10,follow_redirects=False) as client:
        def record(event, **details):
            row = {'event':event,'at':time.time(),**details}
            log.write(json.dumps(row)+'\n')
            log.flush()
            os.fsync(log.fileno())
            print(json.dumps(row),flush=True)

        try:
            deadline = time.monotonic() + args.total_timeout if args.total_timeout else float('inf')
            started = None
            while process is None or process.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError('supervisor_deadline')
                resources = check_resources(args.output,ignore_host_load=args.ignore_host_load)
                now = time.time()
                path = args.output/'progress.json'
                snapshot = json.loads(path.read_text()) if process is not None and path.exists() else {}
                awaiting = (process is not None and now-started <= args.startup_grace
                            and snapshot.get('updated_at',0) < started)
                if process is not None and not awaiting:
                    check_heartbeat(snapshot,now,started,args.stale_after)
                state = network.check(client,args.probe_url)
                if time.monotonic() >= deadline:
                    raise RuntimeError('supervisor_deadline')
                if state == 'healthy':
                    if pause_file.exists():
                        pause_file.unlink()
                        record('dispatch_resumed')
                elif state == 'paused':
                    if not pause_file.exists():
                        pause_file.touch()
                        record('dispatch_paused')
                if process is None and state == 'healthy':
                    started = time.time()
                    args.lease_file.touch()
                    process = subprocess.Popen(command,start_new_session=True)
                    record('started',pid=process.pid,ignore_host_load=args.ignore_host_load,**resources)
                elif process is not None and not awaiting:
                    # Fetch again after the probe: keep monitoring during recovery,
                    # but never extend a stale/dead crawler's lease.
                    snapshot = json.loads(path.read_text())
                    check_heartbeat(snapshot,time.time(),started,args.stale_after)
                    args.lease_file.touch()
                    record(state,pid=process.pid,passed=snapshot.get('passed'),
                           attempted=snapshot.get('attempted'),
                           in_flight=snapshot.get('in_flight'),**resources)
                elif awaiting:
                    record('awaiting_first_heartbeat',pid=process.pid)
                if state != 'healthy':
                    record('network_probe_failed',state=state,failures=network.failures,
                           error=network.last_error,
                           outage_seconds=round(time.monotonic()-network.failed_since,2))
                delay = args.interval if state == 'healthy' else args.network_retry_interval
                delay = min(delay,max(.01,deadline-time.monotonic()))
                if process is None:
                    time.sleep(delay)
                else:
                    try:
                        process.wait(timeout=delay)
                    except subprocess.TimeoutExpired:
                        pass
            record('child_exited',returncode=process.returncode)
            if process.returncode:
                raise RuntimeError('crawler_exit_' + str(process.returncode))
        except BaseException as exc:
            record('supervisor_stopped',reason=type(exc).__name__+':'+str(exc)[:400])
            raise
        finally:
            if process is not None and process.poll() is None:
                # The crawler's SIGTERM handler cleans its per-site process groups.
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
                record('child_cleaned',returncode=process.returncode)


if __name__ == '__main__':
    main()
