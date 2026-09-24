import sys

import pytest

from scripts.run_codex_cli_edit_batch import (
    MAX_SUBTASK_TIMEOUT_SECONDS,
    code_sha256,
    run_bounded,
    snapshot_code,
)


def test_snapshot_code_is_stable_and_ignores_runtime_files(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "app.js").write_text("const state = 1;\n")
    (frontend / "index.html").write_text("<main>ready</main>\n")
    (frontend / "worker.log").write_text("ignored")
    (frontend / "node_modules" / "pkg").mkdir(parents=True)
    (frontend / "node_modules" / "pkg" / "index.js").write_text("ignored")

    code = snapshot_code(frontend)

    assert [item["path"] for item in code] == ["index.html", "src/app.js"]
    assert code_sha256(code) == code_sha256(list(code))


def test_run_bounded_kills_timed_out_process_group(tmp_path):
    with (tmp_path / "process.log").open("w") as stream:
        status, returncode = run_bounded(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
            stream=stream,
            timeout=1,
            env={},
        )

    assert status == "timeout"
    assert returncode is None


def test_subtask_timeout_cap_is_two_minutes():
    assert MAX_SUBTASK_TIMEOUT_SECONDS == 120
