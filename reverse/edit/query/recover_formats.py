"""Reuse completed LLM receipts without requests; retain original failure evidence."""
import argparse
import collections
import fcntl
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from reverse.edit.query import regenerate as m


def recover(root):
    recovered = []
    plan = m.read_json(root/'plan.json')
    for job in plan['jobs']:
        folder = root/'jobs'/job['job_id']
        path = folder/'result.json'
        if not path.exists():
            continue
        result = m.read_json(path)
        if result.get('error_type') != 'invalid_output' or result['status'] != 'error':
            continue
        for receipt_path in sorted(folder.glob('attempt-*.json'), reverse=True):
            receipt = m.read_json(receipt_path)
            if receipt['status'] != 'complete':
                continue
            try:
                values = m.parse_output(receipt['content'], result['task_types'])
            except (ValueError, KeyError, TypeError):
                break
            backup = folder/'result.before-format-recovery.json'
            if not backup.exists():
                m.write_json(backup, result)
            result = dict(result)
            result.pop('error_type', None)
            result.pop('error', None)
            result.update(status='ok', descriptions=values,
                          generation_seconds=receipt['elapsed_seconds'],
                          format_recovery=dict(receipt=receipt_path.name, time=time.time(),
                                               additional_llm_calls=0))
            m.write_json(path, result)
            recovered.append(job['job_id'])
            break
    m.event(root, 'format_recovery', recovered=recovered, additional_llm_calls=0)
    print(dict(recovered=len(recovered), additional_llm_calls=0), flush=True)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--wait-for-pid', type=int,
                        help='Reconcile exports after this running supervisor exits')
    args = parser.parse_args()
    root = args.output_dir
    lock = (root/'run.lock').open('a')
    if not args.wait_for_pid:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pidfile = Path(f'/proc/{args.wait_for_pid}/stat') if args.wait_for_pid else None
    identity = pidfile.read_text().split(')')[-1].split()[19] if pidfile and pidfile.exists() else None
    plan = recover(root)
    # Never compete with the active supervisor's export or progress writer.
    while identity and pidfile.exists():
        try:
            current = pidfile.read_text().split(')')[-1].split()
        except FileNotFoundError:
            break
        if current[19] != identity or current[0] == 'Z':
            break
        time.sleep(15)
    recover(root)
    known = {job['job_id']: m.read_json(root/'jobs'/job['job_id']/'result.json')
             for job in plan['jobs'] if (root/'jobs'/job['job_id']/'result.json').exists()}
    m.export_results(root, plan, known)
    print(dict(final_counts=dict(collections.Counter(r['status'] for r in known.values()))), flush=True)


if __name__ == '__main__':
    main()
