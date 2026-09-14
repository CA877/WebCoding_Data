"""Product directions and state-grounded, one-at-a-time capability sessions."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import secrets
import importlib.util

from inspiration_library.edit_taxonomy import PRODUCT_EDIT_POLICY, validate_classification


_BROWSER_ACTIONS = {
    "click", "drag_and_drop", "emulate_media", "fill", "hover", "key_press",
    "reload", "scroll", "select_option", "set_hash", "set_input_files",
    "set_storage_value", "set_viewport", "wait_for",
    "assert_aria", "assert_attribute", "assert_count", "assert_computed_style",
    "assert_focus", "assert_form_valid", "assert_hash", "assert_hidden",
    "assert_in_view", "assert_property", "assert_scroll", "assert_storage_value",
    "assert_text", "assert_url", "assert_value", "assert_visible",
}
_BROWSER_ASSERTIONS = {name for name in _BROWSER_ACTIONS if name.startswith("assert_")}


def load_browser_protocol(harness_root):
    """Use the selected Harness's actual action protocol without a second copy."""
    path = Path(harness_root) / "src/orchestration/ui_action_contracts.py"
    spec = importlib.util.spec_from_file_location("product_browser_protocol", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def texts(value, name, *, empty=False):
    if not isinstance(value, list) or (not value and not empty):
        raise ValueError(f"{name} must be a {'possibly empty ' if empty else ''}list")
    for item in value:
        text(item, name)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _local_route(value, name):
    route = text(value, name)
    if "://" in route or "\\" in route:
        raise ValueError(f"{name} must be local")
    if not route.startswith("/"):
        route = "/" + route
    if route.startswith("//") or "?" in route or "#" in route or ".." in route.split("/"):
        raise ValueError(f"{name} must be local")
    return route


def validate_browser_check(value, target_routes, existing_routes=()):
    if not isinstance(value, dict) or set(value) != {"id", "route", "actions"}:
        raise ValueError("browser_check must contain exactly id, route, and actions")
    check_id = text(value.get("id"), "browser check id")
    route = _local_route(value.get("route"), "browser check route")
    if route not in set(target_routes) | set(existing_routes):
        raise ValueError("browser check route must be an existing page or an Edit target route")
    actions = value.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 64:
        raise ValueError("browser check requires 1 to 64 actions")
    assertion_count = 0
    normalized = []
    for raw_action in actions:
        if not isinstance(raw_action, dict):
            raise ValueError("browser check contains an unsupported action")
        action = dict(raw_action)
        if len(action) == 1:
            name, fields = next(iter(action.items()))
            if name in _BROWSER_ACTIONS and isinstance(fields, dict):
                if "action" in fields or "type" in fields:
                    raise ValueError("conflicting nested browser action fields")
                action = {"action": name, **fields}
        if "action" not in action and isinstance(action.get("type"), str):
            action["action"] = action.pop("type")
        if action.get("action") not in _BROWSER_ACTIONS:
            raise ValueError("browser check contains an unsupported action")
        if action["action"] == "drag_and_drop":
            for alias, canonical in (("source", "source_selector"), ("target", "target_selector"),
                                     ("destination", "target_selector")):
                if alias in action:
                    if canonical in action and action[canonical] != action[alias]:
                        raise ValueError("conflicting drag endpoint fields")
                    action[canonical] = action.pop(alias)
        if action["action"] == "assert_storage_value" and "contains" in action and "value" not in action:
            action["value"] = action.pop("contains")
            action.setdefault("match", "contains")
        if action["action"] == "assert_storage_value":
            action.setdefault("storage", "local")
        if action["action"] == "assert_count" and "value" in action and "count" not in action:
            action["count"] = action.pop("value")
        if action["action"] == "assert_aria":
            aria_aliases = {"label": "aria-label", "live": "aria-live", "modal": "aria-modal"}
            action["attribute"] = aria_aliases.get(action.get("attribute"), action.get("attribute"))
        if action["action"] == "assert_url" and isinstance(action.get("value"), str):
            expected = action["value"].strip()
            if "://" not in expected and not expected.startswith("/"):
                action["value"] = "/" + expected
        assertion_count += action["action"] in _BROWSER_ASSERTIONS
        normalized.append(action)
    if not 1 <= assertion_count <= 64:
        raise ValueError("browser check requires at least one typed assertion")
    if normalized[-1]["action"] not in _BROWSER_ASSERTIONS:
        raise ValueError("browser check must end with a typed assertion")
    return {"id": check_id, "route": route, "actions": normalized}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _read_saved_response(path, log_dir, request_id):
    from inspiration_library.production import parse_json_object
    raw = path.read_text()
    try:
        return parse_json_object(raw)
    except ValueError:
        # A complete object with one surplus closing delimiter is recoverable
        # without changing any key/value or asking the model again.
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter" or raw[exc.pos:exc.pos+1] not in {"}", "]"}:
                raise ValueError("saved response has non-recoverable JSON syntax") from exc
            normalized = raw[:exc.pos] + raw[exc.pos+1:]
            result = parse_json_object(normalized)
            write_json(log_dir / "format_normalizations" / f"{request_id}.json", {
                "response": str(path), "operation": "remove_surplus_closing_delimiter",
                "offset": exc.pos, "removed": raw[exc.pos], "normalized_result": result,
            })
            return result
        raise


def ask(client, request_id, system, context, task, max_tokens=9000, *, compact_evidence=False):
    # Recover a completed paid response after a local validation/interruption failure.
    response_path = client.log_dir / "responses" / f"{request_id}.txt"
    from inspiration_library.production import parse_json_object
    identity_path = client.log_dir / "context_identities" / f"{request_id}.json"
    identity = {"sha256": digest([system, context, task, max_tokens])}
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("saved request context changed; use a new run directory")
    write_json(identity_path, identity)
    if response_path.is_file():
        return _read_saved_response(response_path, client.log_dir, request_id)
    # A recovered worker must retain the failed request and use a distinct ID.
    # Reuse any completed recovery response before making another paid call.
    recovered = sorted((client.log_dir / "responses").glob(f"{request_id}__transport_*.txt"))
    if recovered:
        return _read_saved_response(recovered[-1], client.log_dir, request_id)
    if (client.log_dir / "requests" / f"{request_id}.json").exists():
        import os
        attempt = os.environ.get("PRODUCT_SESSION_RECOVERY_ATTEMPT")
        if not attempt:
            raise ValueError("incomplete request requires diagnosed worker recovery")
        request_id += f"__transport_{attempt}"
        write_json(client.log_dir / "context_identities" / f"{request_id}.json", identity)
    try:
        from inspiration_library.prompt_evidence import evidence_json
        payload, _ = client.chat_json(request_id=request_id, system_prompt=system,
            stable_context=evidence_json(context) if compact_evidence else json.dumps(context, ensure_ascii=False), task=task,
            max_tokens=max_tokens, stream=True, cache_stable_context=False, json_output=True)
        return payload
    except ValueError:
        saved = client.log_dir / "responses" / f"{request_id}.txt"
        if not saved.is_file():
            raise
        return _read_saved_response(saved, client.log_dir, request_id)


def extract_product_pattern(source, extraction, client, request_id):
    cards = extraction["capabilities"]
    if not cards:
        return None, {}
    card_ids = {c["capability_id"] for c in cards}
    # Product synthesis needs observed behavior, not copied runtime bundles.
    # Keep full reference artifacts in the persisted extraction for downstream use.
    behavior_fields = {
        "capability_id", "name", "family", "change_type", "summary", "prerequisites",
        "requires", "user_actions", "state_reads", "state_writes", "state_write_status",
        "produces", "visible_result", "future_uses", "observation_evidence", "source_anchors",
    }
    prompt_cards = [{key: value for key, value in card.items() if key in behavior_fields}
                    for card in cards]
    # Pool bookkeeping is not product evidence. Keep the original source in output.
    prompt_source = {key: value for key, value in source.items() if key not in {
        'target_weight', 'protected_priority', 'added_in', 'checked_date',
    }}
    payload = ask(client, request_id + "__taxonomy_v4",
        "Describe the product purpose and connected user workflows supported by observed capability cards. "
        "Do not invent source features, combine unrelated demos into an observed workflow, or mistake "
        "documentation navigation for the demonstrated product. Mark inferred transfer opportunities "
        "separately. This is product-pattern extraction, not quality judging.\n" + PRODUCT_EDIT_POLICY,
        {"source": prompt_source, "seed_summary": extraction.get("seed_summary"),
         "business_objects": extraction.get("business_objects"), "capabilities": prompt_cards},
        'Return a JSON object {product_purpose, user_goals:[string], core_objects:[string], '
        'workflows:[{goal, steps:[{action,capability_ids:[existing ID]}], visible_result}], '
        'transfer_opportunities:[string], classifications:[{capability_id,classification:{'
        'primary:{taxonomy,type},secondary:[],reason}}]}. Describe only workflows supported by supplied '
        'cards; a partial demonstration can yield a short workflow without fabricating unobserved steps. '
        'Classify every card exactly once; extension categories are allowed. '
        'Write compact JSON with concise factual prose: one short sentence per purpose, goal, visible result, '
        'transfer opportunity and classification reason; one short action per step. Avoid repeating card '
        'descriptions or page copy. Preserve every supported workflow, necessary step, capability reference '
        'and observed-versus-inferred limitation; do not reduce coverage for brevity.', compact_evidence=True)
    for key in ("user_goals", "core_objects"):
        texts(payload.get(key), key)
    text(payload.get("product_purpose"), "product_purpose")
    texts(payload.get("transfer_opportunities"), "transfer_opportunities", empty=True)
    workflows = payload.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("product pattern needs workflows")
    for workflow in workflows:
        text(workflow.get("goal"), "workflow goal")
        text(workflow.get("visible_result"), "workflow result")
        if not isinstance(workflow.get("steps"), list) or not workflow["steps"]:
            raise ValueError("workflow needs steps")
        for step in workflow["steps"]:
            text(step.get("action"), "workflow action")
            ids = texts(step.get("capability_ids"), "workflow capability_ids")
            if not set(ids) <= card_ids:
                raise ValueError("workflow references an unknown capability")
    classifications = payload.pop("classifications", [])
    if len(classifications) != len(cards) or {x.get("capability_id") for x in classifications} != card_ids:
        raise ValueError("classify each observed capability exactly once")
    for item in classifications:
        validate_classification(item["classification"])
    pattern = {"schema_version": "product_pattern_v1", "product_id": source["seed_id"],
        "source_refs": [source], "capability_ids": sorted(card_ids), **payload,
        "evidence_refs": [{"capability_id": c["capability_id"],
                           "observations": c.get("observation_evidence", [])} for c in cards]}
    return pattern, {x["capability_id"]: x["classification"] for x in classifications}


def load_library(path):
    path = Path(path)
    patterns = [json.loads(line) for line in (path / "product_patterns.jsonl").read_text().splitlines() if line.strip()]
    cards = [json.loads(line) for line in (path / "capability_pool.jsonl").read_text().splitlines() if line.strip()]
    if not patterns or not cards or len(patterns) > 32 or len(cards) > 128:
        raise ValueError("pilot library requires 1-32 product patterns and 1-128 cards")
    ids = {c["capability_id"] for c in cards}
    if len(ids) != len(cards) or len({p["product_id"] for p in patterns}) != len(patterns):
        raise ValueError("duplicate library identities")
    for pattern in patterns:
        if not set(pattern["capability_ids"]) <= ids:
            raise ValueError("product pattern has missing cards")
    return {"patterns": patterns, "cards": cards, "version": digest([patterns, cards])}


def assemble_library(inputs, output):
    """Keep source records intact while joining explicitly selected product snapshots."""
    libraries = [load_library(p) for p in inputs]
    output = Path(output)
    patterns = [p for lib in libraries for p in lib["patterns"]]
    cards = [c for lib in libraries for c in lib["cards"]]
    if len({p["product_id"] for p in patterns}) != len(patterns) or len({c["capability_id"] for c in cards}) != len(cards):
        raise ValueError("selected snapshots overlap; select one version per source")
    output.mkdir(parents=True, exist_ok=False)
    for filename, values in (("product_patterns.jsonl", patterns), ("capability_pool.jsonl", cards)):
        (output / filename).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in values))
    joined = load_library(output)
    write_json(output / "manifest.json", {"schema_version":"product_inspiration_library_v1",
        "status":"ok", "version":joined["version"], "source_count":len(patterns), "card_count":len(cards),
        "sources":[{"path":str(Path(p).resolve()),"version":lib["version"]} for p,lib in zip(inputs,libraries)]})
    return joined


def source_snapshot(project):
    project = Path(project).resolve()
    if (project / "render_dependencies.json").exists():
        raise ValueError("render-only dependency projects require a model-input manifest adapter")
    files = []
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.is_symlink() or set(path.relative_to(project).parts) & {"node_modules", ".git", ".harness", "dist", ".venv"}:
            continue
        if path.suffix.lower() in {".html", ".htm", ".css", ".js", ".mjs", ".json", ".jsx", ".tsx", ".ts", ".vue"} and path.name not in {"package-lock.json", "pnpm-lock.yaml"}:
            files.append({"path": path.relative_to(project).as_posix(), "code": path.read_text()})
    if not files or sum(len(f["code"]) for f in files) > 250000:
        raise ValueError("source must be nonempty and fit the 250000-character pilot context; never truncate")
    return {"files": files, "sha256": digest(files)}


def generate_state_query(session, host, client):
    """Describe one accepted prefix state as a standalone Generate task."""
    edits = session["edits"]
    if not edits or len(edits) > session["selection"]["edit_count"] or any(
        edit["execution"]["status"] != "completed" for edit in edits
    ):
        raise ValueError("state query requires a nonempty accepted prefix")
    if session["current_state"]["state_id"] != edits[-1]["target_version"]:
        raise ValueError("state query must describe the last accepted prefix state")
    if host["source"]["sha256"] != session["current_state"]["sha256"]:
        raise ValueError("state query source changed after acceptance")
    payload = ask(client, f"generate_query_{session['current_state']['state_id']}_v1",
        "Write a self-contained English website creation request for the supplied current product. "
        "Describe the actual pages, content, visual layout and working user workflows from the complete "
        "accepted source and browser evidence. Include retained original features and implemented additions. "
        "Code and observed behavior are authoritative; omit unimplemented intentions. Do not mention an "
        "existing website, edit history, benchmark, tests, donor, implementation instructions or source code. "
        "Do not invent external services, live backends or authentication. This is requirement synthesis, "
        "not an extra evaluation or quality gate.",
        {"host": host, "original_query": session.get("seed", {}).get("original_query"),
         "accepted_instructions": [edit["instruction"] for edit in edits]},
        'Return {"instruction": "A complete standalone request to create this website."}.', 7000)
    return {"schema_version": "product-state-query-v1", "instruction": text(payload.get("instruction"), "instruction"),
            "source_sha256": host["source"]["sha256"], "state_id": session["current_state"]["state_id"],
            "edit_ids": [edit["edit_id"] for edit in edits], "model": "gpt-5.5"}


def generate_final_query(session, host, client):
    """Compatibility entry point for callers explicitly requesting the final state."""
    if len(session["edits"]) != session["selection"]["edit_count"] or any(
        edit["execution"]["status"] != "completed" for edit in session["edits"]
    ):
        raise ValueError("final query requires the complete accepted Session")
    return {**generate_state_query(session, host, client), "schema_version": "product-final-query-v1"}


def validate_plan(steps, count, completed=()):
    if not isinstance(steps, list) or len(steps) != count:
        raise ValueError("plan must preserve the sampled session length")
    prior = {}
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) - {"edit_id", "capability", "contribution_to_goal",
                "depends_on", "requires", "produces", "completion_criteria", "inspiration_refs"}:
            raise ValueError("capability plan must not contain future instructions or execution results")
        if step.get("edit_id") != f"q{index}":
            raise ValueError("plan edit IDs must be in linear order")
        for key in ("capability", "contribution_to_goal"):
            text(step.get(key), key)
        dependencies = texts(step.get("depends_on"), "depends_on", empty=True)
        if len(dependencies) != len(set(dependencies)) or not set(dependencies) <= set(prior):
            raise ValueError("dependencies must be unique preceding edits")
        produces = step.get("produces")
        requires = step.get("requires")
        if not isinstance(produces, list) or not produces or not isinstance(requires, list) or not requires:
            raise ValueError("capability needs requires and produces")
        for state in produces:
            text(state.get("state"), "produced state")
        consumed = set()
        for item in requires:
            text(item.get("state"), "required state")
            source = item.get("source")
            if source == "seed":
                continue
            if source not in dependencies or source not in prior:
                raise ValueError("required state must name its actual planned producer: "
                    f"consumer={step['edit_id']}, source={source}, required={item['state']!r}, "
                    f"declared_dependencies={dependencies!r}, "
                    f"producer_outputs={prior.get(source, {}).get('produces', [])!r}")
            consumed.add(source)
        if consumed != set(dependencies):
            raise ValueError("every declared dependency must name a consumed state")
        texts(step.get("completion_criteria"), "completion criteria")
        texts(step.get("inspiration_refs"), "inspiration refs", empty=True)
        prior[step["edit_id"]] = step
    for old, new in zip(completed, steps):
        if old != new:
            raise ValueError("replanning cannot rewrite completed steps")
    return steps


STEP_FIELDS = ('The step has edit_id qK, capability, contribution_to_goal, depends_on:[completed edit IDs], '
    'requires:[{source:"seed" or an earlier edit ID,state}], produces:[{state}], '
    'completion_criteria:[string], inspiration_refs:[capability IDs]. A requires state from an earlier '
    'edit must name the completed producer ID; state describes the required behavior and may paraphrase it. Multiple prior producers are allowed. '
    'Capabilities are user-visible increments, not coding subtasks. All increments serve the product goal. '
    'For each increment, first identify the product need and its contribution, then prefer a suitable '
    'capability-family design for that need. Express its actual user actions, state changes and results '
    'in completion_criteria. Do not choose a type before identifying the need or merely attach a type '
    'to a vague feature name. Keep family guidance internal; no additional plan fields are required. '
    'Each step must already let a user complete a useful action or answer a useful question at that step. '
    'One Edit must have ONE independently useful user capability, not a miniature product release. '
    'If an operation would still be useful on its own without the chosen operation, leave it out of '
    'this Edit. Include only supporting controls and state necessary for this one action to work. '
    'Sharing a page, object, or product goal does not make independent operations one capability. '
    'Do not bundle object creation, editing, reordering, review and publication into one step; choose '
    'only the next useful action grounded in available data. Do not invent a full data-management '
    'system as a prerequisite for one interaction. Apply this scope limit to the first and final '
    'steps too; remaining goals never justify a catch-all Edit. '
    'Keep its data, controls, state transitions and visible result together. Never allocate separate steps '
    'to an empty shell, container, individual button, field wiring, responsive styling, accessibility '
    'or generic polish; these belong inside each functional increment. Every added control must work now, '
    'not promise functionality in a later step. Do not subdivide implementation chores merely because '
    'later steps remain. '
    'Do not force independent steps or a fixed number of dependencies. Allow new objects with real '
    'creation/editing UI instead of inventing their presence in the source. '
    'Use source data and frontend-only workflows; do not assume accounts or unavailable external services. ')


def build_product_context(direction, details):
    return {"seed_introduction": text(details.get("seed_introduction"), "seed introduction"),
            "task_transformation": {
                "original_primary_task": text(details.get("original_primary_task"), "original primary task"),
                "target_product": text(direction.get("target_product"), "target product"),
                "target_primary_task": text(direction.get("user_goal"), "target primary task"),
                "task_reversal": text(details.get("task_reversal"), "task reversal")}}


def restore_product_context(session, seed_browser, client):
    """Backfill old Sessions once from the original Seed, retaining the chosen goal."""
    if session.get("product_context"):
        return session
    details = ask(client, "seed_product_context_v1",
        "Briefly describe the ORIGINAL Seed website and its primary user task from its browser facts. "
        "Then explain the main-task transformation from that Seed to the already selected target. "
        "Use the Seed's original task, not the inspiration donor's task, as the starting point. "
        "Preserve the selected target exactly. Do not invent implemented target features, plan Edits, "
        "or evaluate the website. Use one or two short natural-language sentences per field, no code.",
        {"original_seed_browser": seed_browser, "selected_direction": session["direction"]},
        'Return JSON {"seed_introduction":string,"original_primary_task":string,"task_reversal":string}.', 1500)
    updated = copy.deepcopy(session)
    updated["product_context"] = build_product_context(session["direction"], details)
    return updated


def product_context_for_prompt(session):
    stored = session["product_context"]
    transformation = stored["task_transformation"]
    return build_product_context(session["direction"], {
        "seed_introduction": stored["seed_introduction"],
        "original_primary_task": transformation["original_primary_task"],
        "task_reversal": transformation["task_reversal"]})


def initialize_session(seed, library, host, client, run_dir, length_seed=None):
    run_dir = Path(run_dir)
    selection_path = run_dir / "edit_count_selection.json"
    if selection_path.exists():
        selection = json.loads(selection_path.read_text())
        if length_seed is not None and length_seed != selection["length_seed"]:
            raise ValueError("cannot change persisted length seed")
    else:
        length_seed = secrets.randbits(64) if length_seed is None else length_seed
        selection = {"length_seed": length_seed, "edit_count": random.Random(length_seed).randint(4, 12),
                     "method": "uniform_integer_4_12"}
        write_json(selection_path, selection)
    direction = ask(client, "direction", PRODUCT_EDIT_POLICY +
        '\nRetrieve one distant but reachable product direction from the supplied product-pattern library. '
        'Distance means a changed user purpose/workflow, not an unrelated name or lowest lexical similarity. '
        'Prioritize a substantial main-task reversal and product leap: change what users come to '
        'accomplish and the useful outcome they leave with. Connect changed primary task to changed '
        'user actions, interaction organization, main interface structure and resulting product identity. '
        'Renaming the site, adding convenience features, or switching visitors to owners who manage '
        'the same site content is not sufficient transformation. Do not choose the original website '
        'plus a separate administration dashboard, content-management workspace or generic CRUD board. '
        'Choose a new primary job that repurposes the Seed objects; its core user journey must become '
        'the main experience of the evolving product, not an optional side tool. '
        'Transfer object-action-state relationships; retain recognizable source objects. '
        'The library is inspiration, not a ceiling on the target: source workflows may be partial, but '
        'the descendant must support a complete useful product job, including meaningful results from '
        'user changes. You may synthesize new frontend capabilities and browser-local persistence; '
        'keep these proposed target capabilities distinct from claims about what the source demonstrated. '
        'The supplied edit_count is already sampled and fixed. Choose a substantive new primary job '
        'whose useful outcome is reachable within that many single-capability Edits. Scale the target '
        'scope to this budget without weakening the task transformation, bundling independent features '
        'or padding the chain with trivial chores. '
        'Do not plan the concrete Edit chain yet.',
        {"seed": seed, "host": host, "product_patterns": library["patterns"],
         "edit_count": selection["edit_count"]},
        'Return JSON {target_product,user_goal,retained_objects:[string],new_workflow:[string],'
        'completion_conditions:[string],inspiration_refs:[product_id],transfer_reason,'
        'seed_introduction,original_primary_task,task_reversal}. '
        'In one or two short natural-language sentences per added field, introduce the ORIGINAL Seed, '
        'state its original primary user task, and explain how that task changes into the target task. '
        'Use task_reversal to state the substantive before/after task and outcome, not merely a role '
        'switch. In new_workflow and completion_conditions describe the new primary journey and how '
        'the main entry, object interactions and result surfaces support it. These are target product '
        'behaviors, not a future sequence of Edits. '
        'The starting task is the Seed task, not the donor task. Do not include code or selectors. '
        'Recommend exactly one direction grounded in available source data and frontend capabilities.', 4000)
    for key in ("target_product", "user_goal", "transfer_reason"):
        text(direction.get(key), key)
    for key in ("retained_objects", "new_workflow", "completion_conditions", "inspiration_refs"):
        texts(direction.get(key), key)
    if not set(direction["inspiration_refs"]) <= {p["product_id"] for p in library["patterns"]}:
        raise ValueError("direction must reference retrieved product patterns")
    write_json(run_dir / "direction.json", direction)
    return {"schema_version": "product_edit_session_v1", "session_id": seed["seed_id"],
        "generation_policy": "each_accepted_state",
        "seed": seed, "library_version": library["version"], "selection": selection,
        "direction": direction, "product_context": build_product_context(direction, direction),
        "steps": [], "edits": [], "plan_version": 0,
        "status": "planned", "retrieval_method": "llm_product_pattern_selection",
        "current_state": {"state_id": "s0", "sha256": host["source"]["sha256"],
                          "project_path": seed["project_path"], "evaluation": seed["evaluation"]}}


def edit_history_for_prompt(session):
    """Reuse the existing capability summary; never send full instructions or code."""
    return [{"edit_id": step["edit_id"],
             "summary": text(edit.get("capability") or step["capability"], "capability summary")}
            for step, edit in zip(session["steps"], session["edits"])]


def inspiration_code_for_edit(edit, library):
    """Resolve only the chosen Edit's references at the Harness handoff."""
    cards = {c["capability_id"]: c for c in library["cards"]}
    refs = list(dict.fromkeys(edit.get("inspiration_refs", [])))
    if not set(refs) <= cards.keys():
        raise ValueError("unknown inspiration at Harness handoff")
    snippets = {}
    unavailable = []
    for ref in refs:
        found = False
        for source in cards[ref].get("source_slices", []):
            content = source.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            found = True
            sha = hashlib.sha256(content.encode()).hexdigest()
            if sha not in snippets:
                snippets[sha] = {"sha256": sha, "capability_ids": [], "content": content,
                    **{k: source[k] for k in ("path", "language", "start_line", "end_line") if k in source}}
            if ref not in snippets[sha]["capability_ids"]:
                snippets[sha]["capability_ids"].append(ref)
        if not found:
            unavailable.append(ref)
    return {"schema_version": "inspiration-code-v1", "selected_capability_ids": refs,
            "unavailable_capability_ids": unavailable, "snippets": list(snippets.values())}


def retrieve_next_inspirations(session, library, browser, records, client, top_k=3):
    """Semantically rank behavior cards before the single Edit-generation call."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be an integer from 1 to 20")
    fields = {"capability_id", "change_type", "summary", "requires", "user_actions",
              "produces", "visible_result", "future_uses", "classification"}
    cards = [{key: value for key, value in card.items() if key in fields}
             for card in library["cards"]]
    by_id = {card["capability_id"]: card for card in cards}
    if not cards or len(by_id) != len(cards):
        raise ValueError("retrieval requires nonempty unique capability cards")
    k = min(top_k, len(cards))
    request_id = f"retrieve_q{len(records)+1}_v3"
    selected = ask(client, request_id,
        "Retrieve behavior inspirations for the next step of a product evolution. Rank candidates "
        "by their usefulness given the product direction, actual browser facts and accepted edits. "
        "Prefer capabilities that advance an unmet product need; related prior inspiration may be "
        "reused for a different increment. Select existing integer candidate_index values only. Explain their relevance to the "
        "product direction, without inventing source behavior. Do not plan a capability session, "
        "write an Edit instruction or evaluate the webpage.",
        {"direction": session["direction"], **product_context_for_prompt(session),
         "remaining_steps": session["selection"]["edit_count"]-len(records),
         "browser": browser, "edit_records": records,
         "candidates": [{"candidate_index": index, **card} for index, card in enumerate(cards)]},
        f'Return JSON {{"matches":[{{"candidate_index":integer,"relevance":string}}]}} with exactly {k} '
        f'distinct indices from 0 to {len(cards)-1} in descending relevance order. Do not reproduce capability IDs.', 3000)
    if not isinstance(selected, dict) or set(selected) != {"matches"}:
        raise ValueError("retrieval must return only matches")
    matches = selected["matches"]
    if not isinstance(matches, list) or len(matches) != k:
        raise ValueError("retrieval must return exactly min(top_k, pool_size) matches")
    ids = []
    inspirations = []
    for match in matches:
        if not isinstance(match, dict) or set(match) != {"candidate_index", "relevance"}:
            raise ValueError("invalid retrieval match")
        index = match["candidate_index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(cards):
            raise ValueError("retrieval returned an invalid candidate index")
        key = cards[index]["capability_id"]
        if key in ids:
            raise ValueError("retrieval returned unknown or duplicate capability ID")
        ids.append(key)
        inspirations.append({**by_id[key], "retrieval_relevance": text(match["relevance"], "relevance")})
    write_json(client.log_dir / "retrieval" / f"q{len(records)+1}.json", {
        "method": "llm_semantic_top_k", "model": "gpt-5.5", "requested_top_k": top_k,
        "effective_top_k": k, "pool_size": len(cards), "library_sha256": digest(library),
        "state_id": session["current_state"]["state_id"], "selected_ids": ids,
        "inspirations": inspirations})
    return inspirations


def instantiate_next(session, library, host, client, revision_feedback=None, browser_protocol=None, top_k=3):
    done = len(session["edits"])
    if any(e["execution"]["status"] != "completed" for e in session["edits"]):
        raise ValueError("finish or explicitly resume the current Edit before generating another")
    count = session["selection"]["edit_count"]
    if done >= count:
        raise ValueError("session already reached its sampled length")
    if host["source"]["sha256"] != session["current_state"]["sha256"]:
        raise ValueError("current source changed outside the accepted state transition")
    if len(session.get("steps", [])) != done:
        raise ValueError("session must contain only capabilities already instantiated as Edits")
    request_id = f"next_q{done+1}"
    browser = host.get("browser")
    if not isinstance(browser, dict) or not browser:
        raise ValueError("next Edit requires current browser information")
    records = edit_history_for_prompt(session)
    if not session.get("product_context"):
        raise ValueError("original Seed introduction and task transformation must be initialized")
    inspirations = retrieve_next_inspirations(session, library, browser, records, client, top_k)
    context = {**product_context_for_prompt(session), "retrieved_inspirations": inspirations,
               "browser": browser, "edit_records": records}
    protocol_task = ""
    if browser_protocol is not None:
        protocol_task = (' Browser action allowed fields (plus action and optional settle_ms 0..5000): ' +
            json.dumps({name: sorted(browser_protocol._ACTION_FIELDS[name]) for name in sorted(_BROWSER_ACTIONS)}) +
            ' Selectors are required for element actions. fill/select_option require string value; '
            'key_press requires key. wait_for state is visible/hidden/attached/detached, timeout_ms 1..10000. '
            'set_storage_value requires storage local/session, key, value; encoding string/json. '
            'assert_value requires value or snapshot, or match nonempty; capture_as alone is invalid. '
            'Snapshots must be captured earlier in this same flow. assert_count requires integer count. '
            'set_input_files files is a list of objects {name,mime_type,content}; content is a text string. ')
    revision_task = ""
    if revision_feedback is not None:
        if revision_feedback.get("edit_id") != f"q{done+1}":
            raise ValueError("revision feedback must target the next unexecuted Edit")
        texts(revision_feedback.get("diagnostics"), "revision diagnostics")
        request_id += "__revision_" + digest(revision_feedback)[:12]
        rejected = revision_feedback.get("rejected_result") or {}
        rejected_edit = rejected.get("edit") or {}
        context["edit_records"] = records + [{"edit_id": revision_feedback["edit_id"],
            "status": "rejected_attempt", "diagnostics": revision_feedback["diagnostics"],
            **{key: value for key, value in rejected_edit.items()
               if key in {"instruction", "classification", "target_routes"}}}]
        revision_task = ('Correct the explicitly recorded rejected attempt using its diagnostics; '
                         'it is not an accepted Edit or an implemented capability. ')
    result = ask(client, request_id, PRODUCT_EDIT_POLICY +
        '\nCreate only the next capability and its concrete feature Edit from the ACTUAL current browser facts '
        'and accepted Edit records, using the retrieved inspirations. seed_introduction describes the '
        'original starting product; task_transformation explicitly states its original primary task, '
        'fixed target task and the intended task reversal. Advance that fixed product direction '
        'through the next functional increment; do not replace it with the donor product identity. '
        'Make the main-task reversal tangible in what users do with Seed objects and the results '
        'they obtain. contribution_to_goal must explain this step-specific change from the original '
        'task toward the new primary job, not just say it supports the target. '
        'Each historical summary briefly states an already completed capability; '
        'use its edit_id when that capability is a dependency. Write the new capability as one short '
        'functional sentence, without code, selectors or implementation details. '
        'Browser information is authoritative for the current visible interface; '
        'do not infer existing source implementations or hidden storage keys. '
        'There is no precomputed or hidden future Capability plan. Do not outline, name, reserve, order, '
        'revise, or commit any future capability. Preserve the sampled total length, completed prefix and '
        'product direction. Choose the single best next product capability now, based on what the accepted '
        'webpage actually supports and what still advances the direction. Do not manufacture dependencies '
        'or completed behavior. Absorb layout and accessibility work into this functional increment. '
        'If this is the final sampled step, choose ONE most important remaining product-direction '
        'capability; do not bundle all unfinished conditions into it or claim unimplemented completion. '
        'Otherwise create a complete useful increment without promising its functionality in a later step. '
        'Describe new local objects explicitly when needed. Instructions must be complete English user '
        'requests for one functional change. Evolve the core product through the whole session: '
        'integrate the new task into existing primary entry points, object interactions and result '
        'surfaces. Adapt or replace the old task-specific interaction or layout when this increment '
        'requires it; retain reusable Seed content and working capabilities outside that scope. '
        'Do not keep the original site as the main experience and append an owner/admin workspace. '
        'A new page is allowed when it belongs to the new primary user journey, not as a detached '
        'management destination. Do not make a wholesale homepage rewrite, cosmetic rebrand or '
        'unrelated restructuring stand in for a functional increment. The product leap must emerge '
        'from successive single-capability changes, not one overloaded step or an empty shell. '
        'Ground requests in visible product objects and states, without q IDs, internal state IDs, '
        'donor/source references, benchmark/category metadata or hidden implementation answers. '
        'Natural feature names such as data table are allowed when they describe the requested UI. '
        'Do not pad each Edit with an identical quality checklist.',
        context,
        revision_task + protocol_task + f' This is step {done+1} of {count}; {count-done} steps remain including this one. '
        'Return {step:{edit_id,capability,contribution_to_goal,depends_on,requires,'
        'produces,completion_criteria,inspiration_refs}, edit:{instruction,'
        'classification:{primary:{taxonomy,type},secondary:[],reason}, target_routes:[string],'
        'browser_check:{id,route,actions:[typed browser actions and assertions]}}}. '
        f'The single step must be q{done+1}; do not return remaining_steps, a future plan, or later capabilities. ' +
        STEP_FIELDS + 'The edit implements exactly this newly chosen step. Its requirements must be stated '
        'in the instruction, not only completion_criteria. target_routes name current pages to modify '
        'and any new local page created by this Edit. '
        'Produce exactly one continuous browser_check for the concrete Edit. Harness also checks '
        'applicable WebCompass defects in the related observed UI states, without another model. '
        'Use stable CSS selectors and only bounded typed actions such as '
        'click, fill, select_option, key_press, drag_and_drop, reload, set_viewport, set_hash, '
        'assert_visible, assert_hidden, assert_text, assert_value, assert_count, assert_url, '
        'assert_hash, assert_storage_value, assert_in_view, assert_focus, assert_attribute, or '
        'assert_property. For drag_and_drop use exactly source_selector and target_selector. For '
        'assert_storage_value use storage, key, value and match exact/contains. End with an assertion. '
        'Follow the browser action field rules exactly, including required fields and allowed enum values. '
        'Use one minimal causal journey: perform the new operation and assert its changed visible '
        'result once. Add only the linked-consumer operation/result or reload/result explicitly '
        'required by this Edit. Prefer one decisive assertion per distinct state change; do not '
        'check each copied field or restate one result as text, visibility, count and storage checks. '
        'Start at the target route; navigate only when navigation itself is required behavior. '
        'A successful click already establishes that its control was actionable: omit preparatory '
        'visibility and URL assertions. Omit unchanged titles, dates, labels, placeholder text and '
        'seed metadata; inspect them only if changing that value is the new behavior. '
        'Do not turn completion_criteria into one assertion per line or exercise unrelated variants. '
        'Use the actual UI for the behavior under test; initialize only unrelated prerequisite data, '
        'never its desired result. Where linkage is required, observe the actual consumer rather '
        'than only a toast or storage value. Persistence is checked only when explicitly requested. '
        'For text matching explicitly choose match contains or exact. If data must be counted, use count. '
        'Use assert_value for a known input/textarea value or select option value; use assert_text '
        'for displayed text. If the instruction permits either a text region or a text control, '
        'assert_text reads the actual control value (or selected option label) for that control. '
        'Check selectors must uniquely identify controls; use scoped selectors for repeated rows/cards. '
        'Cover the requested functional state transition; '
        'do not add generic console, visual-quality, overflow, overlap, or regression checks. '
        'Classify the concrete behavior after designing the needed capability with the product-first '
        'guidance. If it remains an extension, explain in classification.reason why a family-shaped '
        'design would distort this increment or add unrelated scope. Do not rename unchanged behavior '
        'to obtain an official label.')
    result = copy.deepcopy(result)
    if isinstance(result, dict) and isinstance(result.get("edit"), dict):
        relocated = {}
        for field in ("target_routes", "browser_check"):
            if field in result:
                if field in result["edit"] and result["edit"][field] != result[field]:
                    raise ValueError(f"conflicting Edit field placement: {field}")
                relocated[field] = result.pop(field)
                result["edit"][field] = relocated[field]
        if relocated:
            write_json(client.log_dir / "field_normalizations" / f"next_q{done+1}_placement.json",
                       {"operation": "move_top_level_fields_into_edit", "fields": relocated})
    if not isinstance(result, dict) or set(result) != {"step", "edit"}:
        raise ValueError("next generation must contain exactly one step and one Edit")
    step = result["step"]
    if isinstance(step, dict):
        original_metadata = {key: step.get(key) for key in ("edit_id", "depends_on")}
        step["edit_id"] = f"q{done+1}"
        if isinstance(step.get("requires"), list):
            step["depends_on"] = [prior["edit_id"] for prior in session["steps"]
                if any(isinstance(item, dict) and item.get("source") == prior["edit_id"]
                       for item in step["requires"])]
        normalized_metadata = {key: step.get(key) for key in original_metadata}
        if original_metadata != normalized_metadata:
            write_json(client.log_dir / "field_normalizations" / f"next_q{done+1}.json",
                {"source": "completed_prefix_and_requires", "original": original_metadata,
                 "normalized": normalized_metadata})
    steps = session["steps"] + [result["step"]]
    try:
        validate_plan(steps, done + 1, session["steps"])
    except ValueError as exc:
        feedback = {'edit_id': f'q{done+1}', 'diagnostics': [str(exc)], 'rejected_result': result}
        write_json(client.log_dir / 'diagnosed_revisions' / f'next_q{done+1}.json', feedback)
        raise
    allowed = {c["capability_id"] for c in inspirations}
    original_refs = list(step["inspiration_refs"])
    completed_refs = {prior["edit_id"]: prior["inspiration_refs"] for prior in session["steps"]}
    allowed.update(ref for refs in completed_refs.values() for ref in refs)
    resolved_refs = []
    for ref in original_refs:
        if ref in allowed:
            resolved_refs.append(ref)
        elif ref in completed_refs:
            resolved_refs.extend(completed_refs[ref])
        else:
            raise ValueError("unknown capability reference")
    if not set(resolved_refs) <= allowed:
        raise ValueError("unknown capability reference")
    step["inspiration_refs"] = list(dict.fromkeys(resolved_refs))
    if step["inspiration_refs"] != original_refs:
        write_json(client.log_dir / "inspiration_ref_normalizations" / f"next_q{done+1}.json",
                   {"original": original_refs, "normalized": step["inspiration_refs"],
                    "inherited_from_completed_steps": {ref: completed_refs[ref] for ref in original_refs
                                                      if ref not in allowed and ref in completed_refs}})
    edit = result["edit"]
    if not isinstance(edit, dict) or set(edit) != {
        "instruction", "classification", "target_routes", "browser_check"
    }:
        raise ValueError("single Edit output must not override validated plan or state metadata")
    text(edit.get("instruction"), "instruction")
    validate_classification(edit.get("classification"))
    texts(edit.get("target_routes"), "target routes")
    normalized_routes = [_local_route(route, "target routes") for route in edit["target_routes"]]
    edit["target_routes"] = normalized_routes
    existing_routes = {"/"} | {
        "/" + item["path"] for item in host["source"]["files"]
        if item["path"].endswith((".html", ".htm"))
    }
    edit["browser_check"] = validate_browser_check(edit["browser_check"], normalized_routes, existing_routes)
    if browser_protocol is not None:
        for action in edit["browser_check"]["actions"]:
            browser_protocol.validate_ui_action(action)
        browser_protocol.validate_ui_action_sequence(edit["browser_check"]["actions"])
    updated = copy.deepcopy(session)
    updated["plan_version"] += 1
    updated["steps"] = steps
    updated["last_revision_reason"] = "state_grounded_next_capability"
    updated["edits"].append({**result["step"], **edit, "edit_index": done + 1,
        "source_version": f"s{done}", "target_version": f"s{done+1}",
        "state_basis": {"kind": "observed", **session["current_state"]},
        "acceptance": result["step"]["completion_criteria"], "preserve": [],
        "execution": {"status": "pending"}})
    updated["status"] = "awaiting_execution"
    return updated
