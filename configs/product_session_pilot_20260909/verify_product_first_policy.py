"""One real next-Edit probe from the pilot's accepted state; keep its live session intact."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

code, run = map(Path, sys.argv[1:3])
sys.path.insert(0, str(code))
from inspiration_library.utils.run_live_url_audit_case import supervise

credentials = json.load(sys.stdin)
if set(credentials) != {"TOKENWAVE_OPENAI_API_KEY"} or not isinstance(credentials["TOKENWAVE_OPENAI_API_KEY"], str):
    raise ValueError("expected one protected TokenWave setting")
env = os.environ.copy()
env.update(credentials, PYTHONUNBUFFERED="1", PLAYWRIGHT_HEADLESS="1")
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env.pop(name, None)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

live_path = run / "session_v3/session.json"
original = live_path.read_bytes()
session = json.loads(original)
if len(session["edits"]) != 3 or any(e["execution"]["status"] != "completed" for e in session["edits"][:2]):
    raise ValueError("probe requires the two accepted pilot edits and pending q3")
if session["edits"][-1]["execution"]["status"] == "completed":
    raise ValueError("never revise an accepted q3")
requests = list((run / "session_v3/provider/requests").glob("*.json"))
requests += list(run.glob("policy_product_first_*/provider/requests/*.json"))
if len(requests) >= 14:
    raise ValueError("pilot instruction request ceiling reached")
attempt = int(sys.argv[3]) if len(sys.argv) > 3 else 1
if attempt not in (1, 2):
    raise ValueError("at most two diagnosed policy probes")
output = run / ("policy_product_first_20260910" if attempt == 1 else "policy_product_first_20260910_retry2")
output.mkdir(exist_ok=False)
old_edit = session["edits"].pop()
session["status"] = "ready_for_next"
feedback = {
    "edit_id": "q3",
    "diagnostics": [
        "Apply the confirmed product-first design order to the remaining plan: identify each needed capability from the fixed product direction, prefer a naturally suitable family's functional design, then instantiate and classify the next Edit.",
        "The prior sequence defaulted to extension designs. Reconsider their actual behavior rather than changing labels. Do not add unrelated scope or cosmetic effects to force a type. Keep already accepted capabilities, total length, and product direction unchanged.",
        "Keep all producer state references exact, and each increment independently useful. Describe why each capability advances the product and the user actions, state changes and results it enables.",
    ],
    "rejected_result": {"remaining_steps": copy.deepcopy(session["steps"][2:]),
        "edit": {k: old_edit[k] for k in ("instruction", "classification", "target_routes")}},
}
if attempt == 2:
    previous = json.loads((run / "policy_product_first_20260910/session.json").read_text())
    if len(previous["edits"]) != 3:
        raise ValueError("the second probe requires the completed first response")
    feedback["rejected_result"] = {"remaining_steps": previous["steps"][2:],
        "edit": {k: previous["edits"][-1][k] for k in ("instruction", "classification", "target_routes")}}
    feedback["diagnostics"].append(
        "The first probe retained the old interaction mechanisms and justified extensions by saying those unchanged mechanisms lack family behavior. That is circular. Keep the product needs fixed, but genuinely reconsider unexecuted interaction designs. Choose a natural family realization when it performs the same needed job; reject it only for a concrete conflict with that job, not simply because it differs from the old proposal. A review-only bridge may remain an extension; do not force the next step's label or a coverage quota."
    )
for name, data in (("session.json", session), ("revision_feedback.json", feedback),
                   ("probe_identity.json", {"live_session_sha256": hashlib.sha256(original).hexdigest(),
                    "source_state": session["current_state"], "max_new_calls": 1, "model": "gpt-5.5"})):
    (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
command = [sys.executable, str(code / "scripts/run_product_edit_session.py"),
    "--worker", "next", "--seed", str(run / "seed.json"),
    "--library", str(run / "product_library_v1"), "--run-dir", str(output),
    "--harness-root", str(code / "harness"), "--revision-feedback", str(output / "revision_feedback.json")]
result = supervise(command, cwd=code, run_dir=output / "unit", seconds=600, env=env)
if live_path.read_bytes() != original:
    raise RuntimeError("live Session changed during the isolated probe")
print(json.dumps(result))
raise SystemExit(0 if result["status"] == "ok" else 1)
