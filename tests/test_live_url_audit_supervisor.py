from pathlib import Path
import sys

from inspiration_library.utils.run_live_url_audit_case import supervise


def test_success_is_logged(tmp_path):
    result = supervise([sys.executable,'-c','print("test")'], cwd=tmp_path,
                       run_dir=tmp_path/'case', seconds=3)
    assert result['status']=='ok'
    assert (tmp_path/'case/stdout.log').read_text().strip()=='test'


def test_hard_timeout_stops_child(tmp_path):
    result = supervise([sys.executable,'-c','import time;time.sleep(20)'], cwd=tmp_path,
                       run_dir=tmp_path/'case', seconds=1)
    assert result['status']=='timeout'
    assert result['elapsed_seconds']<5
    assert (tmp_path/'case/supervisor_result.json').is_file()
