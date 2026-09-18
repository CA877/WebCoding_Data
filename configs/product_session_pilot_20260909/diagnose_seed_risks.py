"""Replay existing body-only risk checks on this pilot's unchanged Seed."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys

code, run = map(Path, sys.argv[1:3])
sys.path[:0] = [str(code), str(code / "harness")]
from inspiration_library.utils.run_live_url_audit_case import supervise

mode = next((flag for flag in ("--compare", "--filter-retention", "--q3-risk") if flag in sys.argv), None)
output = run / "session_v3" / {"--compare": "risk_fix_diagnostic", "--filter-retention": "q3_filter_retention", "--q3-risk": "q3_risk_diagnostic"}.get(mode, "seed_risk_diagnostic")
if "--worker" not in sys.argv:
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    env = os.environ.copy()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(name, None)
    result = supervise([sys.executable, __file__, str(code), str(run), "--worker", *([mode] if mode else [])],
                       cwd=code, run_dir=output / "unit", seconds=120, env=env)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "ok" else 1)

from inspiration_library.production_browser import serve_project
from src.orchestration.browser_evidence import collect_browser_evidence

if mode == "--q3-risk":
    import io
    import shutil
    import subprocess
    import tarfile
    import tempfile
    from src.orchestration.edit_risk_tests import materialize_edit_risk_tests, collect_source_risk_baseline, distinguish_preexisting_risks
    workdir = run / "session_v3/steps/q3"
    contract = json.loads((workdir / ".harness/edit_task_contract.json").read_text())
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        (scratch / ".harness").mkdir()
        (scratch / "frontend").mkdir()
        for name in ("atomic_edit_plan.json", "edit_task_contract.json"):
            shutil.copy2(workdir / ".harness" / name, scratch / ".harness" / name)
        shutil.copy2(workdir / "seed_manifest.json", scratch / "seed_manifest.json")
        archive = subprocess.check_output(["git", "archive", contract["baseline_commit"]], cwd=workdir / "frontend")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(scratch / "frontend", filter="data")
        instruction = json.loads((run / "session_v3/step_inputs/q3.json").read_text())["edit"]["instruction"]
        materialize_edit_risk_tests(workdir=scratch, instruction_delta=instruction)
        payload = json.loads((scratch / ".harness/hidden_oracle_checks.json").read_text())
        checks = payload if isinstance(payload, list) else payload["checks"]
        (output / "checks.json").write_text(json.dumps(checks, indent=2))
    baseline = asyncio.run(asyncio.wait_for(collect_source_risk_baseline(workdir, checks, headless=True), 45))
    with serve_project(workdir / "frontend") as url:
        evidence = asyncio.run(asyncio.wait_for(collect_browser_evidence(app_url=url, checks=checks,
            output_path=output / "evidence.json", headless=True), 65))
    distinguish_preexisting_risks(evidence, baseline)
    (output / "compared.json").write_text(json.dumps(evidence, indent=2))
    failed = [c for c in evidence["checks"] if c["status"] != "ok"]
    print(json.dumps({"checks": len(checks), "failures": failed}))
    raise SystemExit(0 if not failed else 1)

if mode == "--filter-retention":
    actions = [
        {"action": "click", "selector": "#staffOperationsOpen"},
        {"action": "click", "selector": "#staffFilterCategory"},
        {"action": "key_press", "selector": "#staffFilterCategory", "key": "ArrowDown"},
        {"action": "key_press", "selector": "#staffFilterCategory", "key": "Enter"},
        {"action": "assert_value", "selector": "#staffFilterCategory", "match": "nonempty", "capture_as": "selected-category"},
        {"action": "click", "selector": ".staff-card"},
        {"action": "assert_visible", "selector": "#modalBackdrop"},
        {"action": "click", "selector": "#modalClose"},
        {"action": "assert_hidden", "selector": "#modalBackdrop"},
        {"action": "assert_value", "selector": "#staffFilterCategory", "snapshot": "selected-category"},
        {"action": "assert_visible", "selector": ".staff-card"},
    ]
    with serve_project(run / "session_v3/steps/q3/frontend") as url:
        evidence = asyncio.run(asyncio.wait_for(collect_browser_evidence(
            app_url=url, checks=[{"id": "filter-retention", "route": "/index.html", "actions": actions}],
            output_path=output / "evidence.json", headless=True), 90))
    print(json.dumps(evidence))
    raise SystemExit(0 if all(check["status"] == "ok" for check in evidence["checks"]) else 1)

checks_path = run / "session_v3/steps/q1/.harness/hidden_oracle_checks.json"
payload = json.loads(checks_path.read_text())
checks = payload if isinstance(payload, list) else payload["checks"]
selected = [c for c in checks if len(c.get("actions", [])) == 1
            and c["actions"][0].get("action") == "assert_webcompass_risk"
            and c["actions"][0].get("selector") == "body"]
assert 1 <= len(selected) <= 44
if "--compare" in sys.argv:
    from src.orchestration.edit_risk_tests import collect_source_risk_baseline, distinguish_preexisting_risks
    workdir = run / "session_v3/steps/q1"
    baseline = asyncio.run(asyncio.wait_for(collect_source_risk_baseline(workdir, checks, headless=True), 60))
    selected = checks
else:
    baseline = None
with serve_project(workdir / "frontend" if baseline is not None else run / "seed") as url:
    evidence = asyncio.run(asyncio.wait_for(collect_browser_evidence(
        app_url=url, checks=selected, output_path=output / "evidence.json", headless=True), 90))
if baseline is not None:
    distinguish_preexisting_risks(evidence, baseline)
    (output / "compared.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
print(json.dumps({"source": "candidate_vs_frozen_seed" if baseline is not None else "unchanged_seed", "checks": [
    {"id": c["check_id"], "status": c["status"]} for c in evidence["checks"]]}))
