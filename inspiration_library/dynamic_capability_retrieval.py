"""Mine frontend capabilities and retrieve again before every linear Edit."""

from __future__ import annotations

from hashlib import sha256
import base64
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from inspiration_library.doc_api import DocApiClient
from inspiration_library.edit_taxonomy import WEBCOMPASS_EDIT_FUNCTIONS
from inspiration_library.prompt_evidence import evidence_json
from inspiration_library.deep_browser_exploration import (
    compact_live_browser_evidence_for_llm,
)
from inspiration_library.linear_edit_queries import (
    compact_browser_evidence_for_llm,
)
from inspiration_library.production import (
    validate_browser_checks,
    validate_source_gap_checks,
)


# One extraction call owns semantic grouping; no additional reviewer or per-card model call.
CAPABILITY_EXTRACTION_SYSTEM = """Extract complete reusable frontend features from saved real-browser evidence.
One card must support one substantial standalone Edit task: a coherent user goal, its related controls,
the observed action-to-result path, shared state and visible feedback. Merge supporting controls, initial
presentation, accessibility semantics and responsive behavior into their owning feature. Never split them
into separate cards merely because triggers, states, viewport or result shapes differ. Group all observed
operations on the same component and business-object collection into one feature card, even when an operation
could be used independently. For example, one data-table card may contain row selection, add/remove, sorting,
filtering and pagination; one editor card contains its observed formatting operations; one notification-center
card contains read, delete and unread-count behavior; one wizard card contains its observed step flow.
Create separate cards only for distinct component systems or distinct end-to-end workflows, at the scope of
the reference families below. A single add, select, toggle, sort, field or button action is not a card by itself.
Use these families as granularity references, not quotas or labels to force onto unrelated behavior.
An equally complete extension is allowed. Do not invent missing behavior to satisfy a family definition.
For interaction features require an observed successful user action AND its meaningful visible result.
Control presence, ARIA roles, documentation text and code examples do not prove an interaction.
For visual effects require the actual observed temporal/scroll transition, not an initial still image.
Omit isolated styles, accessibility attributes, static demo variants, empty mounts, installation recipes,
documentation shell/reflow, code toolbars and incidental header/support/privacy UI. Such peripheral features
are relevant only if explicitly requested as the target and demonstrated as a complete feature themselves.
If only fragments or an inaccessible demo are observed, return capabilities=[], business_objects=[] and a
concise abstention_reason; never fall back to fragment cards to make the source succeed.
Describe only demonstrated behavior and scope. Do not infer persistence, reset, validation, backend or
keyboard behavior from documentation. Preserve exact trigger/result evidence references. Keep the existing
JSON schema and concise descriptions. Return one JSON object only.
FUNCTION SCOPE REFERENCES:\n""" + "\n".join(
    f"- {name}: {description}" for name, description in WEBCOMPASS_EDIT_FUNCTIONS.items()
)


ROUND_SELECTION_SYSTEM = """You select and write exactly one incremental Edit instruction for the current version of an
existing local frontend. The candidate list was freshly retrieved from the full capability pool for this Edit round.
Choose only a capability from that supplied list. The list is an idea library, not code or a behavior donor. Adapt the
capability by structural analogy: the host may use different business objects, fields, identifiers, data shapes, and UI,
as long as it has or can naturally support the same dependency roles and component-group behavior. Map dependencies to
current browser evidence or a named state produced by a prior Edit. The natural instruction must describe user-visible behavior and preservation requirements,
without mentioning donors, retrieval, datasets, CSS/DOM selectors, source code, state graphs, or internal production details.
A dependency is real only when this Edit reads a named state produced by the cited earlier Edit. Also provide one or two
positive browser checks for the requested behavior. Those checks will first run on the current source, which must fail,
and later on the target, which must pass. Return one JSON object."""


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,79}$")
_FORBIDDEN_INSTRUCTION = re.compile(
    r"\b(?:donor|retriev(?:al|ed)|dataset|benchmark|DOM|AX tree|state graph|JSON)\b|"
    r"\b(?:CSS|DOM)\s+selectors?\b",
    re.I,
)


def _text(value: Any, label: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, label: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} rows")
    rows = [_text(item, label) for item in value]
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label} contains duplicates")
    return rows


def _extraction_text_list(
    value: Any, label: str, *, minimum: int = 1
) -> list[str]:
    """Normalize a provider's one-item scalar without weakening other schemas."""

    return _text_list([value] if isinstance(value, str) else value, label, minimum=minimum)


def _extraction_description(value: Any, label: str, *, minimum: int = 1) -> str:
    """Preserve provider prose returned as paragraphs; reject structured guesses."""
    if isinstance(value, list):
        value = "\n".join(_text(item, label) for item in value)
    return _text(value, label, minimum=minimum)


def _safe_source_path(value: Any) -> str:
    rendered = _text(value, "source evidence path")
    path = PurePosixPath(rendered)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe source evidence path: {rendered}")
    return path.as_posix()


def _safe_seed_prefix(seed_id: str) -> str:
    rendered = re.sub(r"[^a-zA-Z0-9_-]+", "_", seed_id).strip("_")
    if not rendered:
        raise ValueError("seed id cannot form a capability prefix")
    return rendered


def validate_live_card_evidence(extraction: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Check provenance/references, not the semantic truth of an LLM claim."""
    if extraction.get("source_url") != observation.get("entry_url"):
        raise ValueError("live observation URL does not match extraction")
    allowed = set(compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, include_action_steps=True)["evidence_state_ids"])
    action_states: set[str] = set()
    for path in observation.get("exploration_paths", []):
        for index, step in enumerate(path.get("steps", []), 1):
            if (step.get("status") == "ok" and isinstance(step.get("state"), dict)
                    and step.get("action", {}).get("action") not in {"wait", "scroll_into_view"}):
                action_states.add(f"{path['id']}__step_{index}")
    for card in extraction["capabilities"]:
        refs = {row["state_id"] for row in card.get("observation_evidence", [])}
        if not refs or refs - allowed:
            raise ValueError(f"{card['capability_id']}: unknown or missing observation state IDs: {sorted(refs - allowed)}")
        if card.get("user_actions") and not refs.intersection(action_states):
            raise ValueError(f"{card['capability_id']}: interactive claim lacks a successful action state")
        card["evidence_reference_status"] = "validated"
        for key in ("behavior_validation_status", "visual_evidence_status", "browser_check_status"):
            card.pop(key, None)
    extraction["admission_status"] = "available"
    return extraction


def validate_capability_extraction(
    payload: dict[str, Any],
    *,
    seed_id: str,
    source_project: str | None = None,
    source_url: str | None = None,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if bool(source_project) == bool(source_url):
        raise ValueError("provide exactly one of source_project or source_url")
    source_kind = "local_project" if source_project else "live_url"
    source_fields = (
        {"source_project": str(source_project)}
        if source_project
        else {"source_url": str(source_url)}
    )
    summary = _text(payload.get("seed_summary"), "seed_summary", minimum=30)
    if payload.get("capabilities") == []:
        return {"schema_version": "webcoding-seed-capability-extraction-v1",
                "seed_id": seed_id, "source_kind": source_kind, **source_fields,
                "seed_summary": summary, "business_objects": [], "capabilities": [],
                "admission_status": "abstained",
                "abstention_reason": _text(payload.get("abstention_reason"), "abstention_reason", minimum=10)}
    objects = payload.get("business_objects")
    if not isinstance(objects, list) or not objects:
        raise ValueError("business_objects must be non-empty")
    normalized_objects: list[dict[str, str]] = []
    for row in objects:
        if not isinstance(row, dict):
            raise ValueError("business object must be an object")
        normalized_objects.append(
            {
                "name": _text(row.get("name"), "business object name"),
                "evidence": _extraction_description(
                    row.get("evidence"), "business object evidence", minimum=20
                ),
            }
        )
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("capability extraction requires at least one capability")
    prefix = _safe_seed_prefix(seed_id)
    normalized: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    for row in capabilities:
        if not isinstance(row, dict):
            raise ValueError("capability must be an object")
        local_id = _text(row.get("local_id"), "capability local_id")
        change_type = _text(
            row.get("change_type", row.get("family")), "capability change_type"
        )
        family = _text(row.get("family", change_type), "capability family")
        if not _ID_RE.fullmatch(local_id):
            raise ValueError(f"invalid capability local_id: {local_id}")
        if not _ID_RE.fullmatch(family):
            raise ValueError(f"invalid capability family: {family}")
        if local_id in local_ids:
            raise ValueError(f"duplicate capability local_id: {local_id}")
        local_ids.add(local_id)
        observation_rows = row.get("observation_evidence")
        evidence_rows = row.get("source_evidence")
        source_evidence: list[dict[str, str]] = []
        observation_evidence: list[dict[str, str]] = []
        if isinstance(observation_rows, list) and observation_rows:
            for evidence in observation_rows:
                if not isinstance(evidence, dict):
                    raise ValueError(
                        f"{local_id} observation evidence must be an object"
                    )
                observation_evidence.append(
                    {
                        "state_id": _text(
                            evidence.get("state_id"),
                            f"{local_id} observation state id",
                        ),
                        "evidence": _extraction_description(
                            evidence.get("evidence"),
                            f"{local_id} observation evidence",
                            minimum=20,
                        ),
                    }
                )
        elif isinstance(evidence_rows, list) and evidence_rows:
            # Backward compatibility for already-paid historical responses.
            for evidence in evidence_rows:
                if not isinstance(evidence, dict):
                    raise ValueError(f"{local_id} source evidence must be an object")
                source_evidence.append(
                    {
                        "path": _safe_source_path(evidence.get("path")),
                        "evidence": _extraction_description(
                            evidence.get("evidence"),
                            f"{local_id} source evidence",
                            minimum=20,
                        ),
                    }
                )
        else:
            raise ValueError(f"{local_id} requires browser observation evidence")
        browser_checks = row.get("browser_checks", [])
        if isinstance(browser_checks, dict):
            browser_checks = [browser_checks]
        if not isinstance(browser_checks, list):
            raise ValueError(f"{local_id} browser_checks must be a list")
        reported_browser_checks: list[dict[str, Any]] = []
        browser_check_status = "not_provided"
        if browser_checks:
            is_executable_shape = all(
                isinstance(check, dict)
                and isinstance(check.get("id"), str)
                and isinstance(check.get("actions"), list)
                and isinstance(check.get("assertions"), list)
                for check in browser_checks
            )
            if is_executable_shape:
                browser_checks = validate_browser_checks(browser_checks, max_checks=2)
                browser_check_status = "ready"
            else:
                # Providers sometimes return useful prose such as
                # {selector, assertion}. Preserve that evidence, but never
                # promote it to an executable browser check by guessing the
                # missing action/assertion semantics.
                reported_browser_checks = browser_checks
                browser_checks = []
                browser_check_status = "needs_compilation"
        state_writes = _extraction_text_list(
            row.get("state_writes"), f"{local_id} state_writes", minimum=0
        )
        prerequisites = row.get("prerequisites")
        source_anchors = row.get("source_anchors", [])
        if isinstance(source_anchors, list) and all(isinstance(item, str) for item in source_anchors):
            source_anchors = list(dict.fromkeys(item.strip() for item in source_anchors))
        if isinstance(prerequisites, list):
            # Some providers wrap the exact structural-role string; unwrap only
            # this lossless shape, never guess prose from an arbitrary object.
            prerequisites = [item["role"] if isinstance(item, dict) and set(item) == {"role"}
                             else item for item in prerequisites]
        normalized.append(
            {
                "capability_id": f"{prefix}__{local_id}",
                "source_seed_id": seed_id,
                "source_kind": source_kind,
                **source_fields,
                "name": _text(row.get("name"), f"{local_id} name"),
                "family": family,
                "change_type": change_type,
                "summary": _text(row.get("summary"), f"{local_id} summary", minimum=30),
                "prerequisites": _extraction_text_list(
                    prerequisites, f"{local_id} prerequisites"
                ),
                "user_actions": _extraction_text_list(
                    row.get("user_actions", []),
                    f"{local_id} user_actions",
                    minimum=0,
                ),
                "state_reads": _extraction_text_list(
                    row.get("state_reads"), f"{local_id} state_reads", minimum=0
                ),
                "state_writes": state_writes,
                "state_write_status": (
                    "reported" if state_writes else "visible_effect_only"
                ),
                "visible_result": _extraction_description(
                    row.get("visible_result"), f"{local_id} visible_result", minimum=20
                ),
                "future_uses": _extraction_text_list(
                    row.get("future_uses", []),
                    f"{local_id} future_uses",
                    minimum=0,
                ),
                "source_anchors": _extraction_text_list(
                    source_anchors,
                    f"{local_id} source_anchors",
                    minimum=0,
                ),
                "source_evidence": source_evidence,
                "observation_evidence": observation_evidence,
                "library_role": "capability_inspiration",
                "library_origin": "observed_seed_capability",
                "browser_checks": browser_checks,
                "reported_browser_checks": reported_browser_checks,
                "browser_check_status": browser_check_status,
            }
        )
    browser_only = all(row["observation_evidence"] for row in normalized)
    if source_url:
        for row in normalized:
            row.pop("browser_check_status", None)
    result = {
        "schema_version": "webcoding-seed-capability-extraction-v1",
        "seed_id": seed_id,
        "source_kind": source_kind,
        **source_fields,
        "evidence_basis": (
            "browser_dom_ax_states" if browser_only else "legacy_source_evidence"
        ),
        "seed_summary": summary,
        "business_objects": normalized_objects,
        "capabilities": normalized,
    }
    return validate_live_card_evidence(result, observation) if source_url and observation is not None else result


def merge_capability_pool(
    extractions: Iterable[dict[str, Any]], historical_bank: dict[str, Any]
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for extraction in extractions:
        pool.extend(dict(row) for row in extraction["capabilities"])
    for row in historical_bank.get("capabilities", []):
        evidence = row.get("donor_evidence") or {}
        case_id = _text(evidence.get("case_id"), "historical case_id")
        source_project = _text(
            evidence.get("source_project"), "historical source_project"
        )
        outputs = _text_list(row.get("outputs"), "historical outputs")
        pool.append(
            {
                "capability_id": _text(row.get("id"), "historical capability id"),
                "source_seed_id": f"historical__{case_id}",
                "source_project": source_project,
                "name": _text(
                    row.get("name", row.get("id")), "historical capability name"
                ),
                "family": _text(
                    row.get("family", "historical_capability"), "historical family"
                ),
                "summary": _text(
                    row.get("summary"), "historical summary", minimum=30
                ),
                "prerequisites": _text_list(
                    row.get("prerequisites"), "historical prerequisites"
                ),
                "user_actions": _text_list(
                    row.get("user_actions"), "historical user actions"
                ),
                "state_reads": _text_list(
                    row.get("state_reads", row.get("prerequisites")),
                    "historical state reads",
                ),
                "state_writes": outputs,
                "state_write_status": "reported",
                "visible_result": _text(
                    row.get("visible_result", "; ".join(outputs)),
                    "historical visible result",
                    minimum=10,
                ),
                "source_evidence": [],
                "observation_evidence": [],
                "library_role": "capability_inspiration",
                "library_origin": "historical_capability_card",
                "browser_checks": [],
                "reported_browser_checks": [],
                "browser_check_status": "historical_record_only",
                "source_lineage": {
                    "path": _text(
                        evidence.get("verification"), "historical evidence path"
                    ),
                    "case_id": case_id,
                },
            }
        )
    pool.sort(key=lambda item: item["capability_id"])
    ids = [row["capability_id"] for row in pool]
    if len(ids) != len(set(ids)):
        raise ValueError("capability pool contains duplicate ids")
    return pool


def capability_embedding_text(card: dict[str, Any]) -> str:
    change_type = card.get("change_type", card.get("family", ""))
    requires = card.get("requires", card.get("prerequisites", []))
    produces = card.get("produces", card.get("state_writes", []))
    return "\n".join(
        [
            f"CHANGE TYPE: {change_type}",
            f"SUMMARY: {card.get('summary', '')}",
            "REQUIRES: " + "; ".join(requires),
            "USER ACTIONS: " + "; ".join(card.get("user_actions", [])),
            "PRODUCES: " + "; ".join(produces),
            f"VISIBLE RESULT: {card.get('visible_result', '')}",
            "FUTURE USES: " + "; ".join(card.get("future_uses", [])),
        ]
    )


def pool_snapshot_sha256(pool: Iterable[dict[str, Any]]) -> str:
    stable: list[dict[str, Any]] = []
    for row in sorted(pool, key=lambda item: item["capability_id"]):
        stable.append(
            {
                key: value
                for key, value in row.items()
                if key not in {"embedding", "similarity"}
            }
        )
    rendered = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode("utf-8")).hexdigest()


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding dimensions do not match")
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        raise ValueError("embedding vector has zero norm")
    return numerator / (left_norm * right_norm)


def rank_capabilities(
    *,
    query_vector: list[float],
    embedded_pool: Iterable[dict[str, Any]],
    host_seed_id: str,
    used_capability_ids: set[str],
    top_k: int,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    ranked: list[dict[str, Any]] = []
    for row in embedded_pool:
        if row.get("source_seed_id") == host_seed_id:
            continue
        if row["capability_id"] in used_capability_ids:
            continue
        vector = row.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise ValueError(f"capability embedding is missing: {row['capability_id']}")
        ranked.append({**row, "similarity": _cosine(query_vector, vector)})
    ranked.sort(key=lambda item: (-item["similarity"], item["capability_id"]))
    return ranked[:top_k]


def resolve_round_source(
    *, seed_project: Path, accepted_versions_dir: Path, edit_index: int
) -> Path | None:
    """Return the real source directory for one linear Edit round."""

    if not 1 <= edit_index <= 5:
        raise ValueError("edit_index must be from 1 to 5")
    source = seed_project if edit_index == 1 else accepted_versions_dir / f"s{edit_index - 1}"
    return source.resolve() if source.is_dir() else None


def build_round_retrieval_query(
    *, host_profile: dict[str, Any], prior_edits: list[dict[str, Any]], edit_index: int
) -> str:
    if not 1 <= edit_index <= 5 or len(prior_edits) != edit_index - 1:
        raise ValueError("round retrieval query does not match the linear history")
    outputs = [
        {
            "edit_id": row["edit_id"],
            "family": row["selected_family"],
            "capability_id": row["selected_capability_id"],
            "produces": row["produces"],
        }
        for row in prior_edits
    ]
    current_capabilities = [
        {"name": row["name"], "family": row["family"], "summary": row["summary"]}
        for row in host_profile["capabilities"]
    ]
    return (
        f"CURRENT SOURCE VERSION: s{edit_index - 1}\n"
        f"HOST SUMMARY: {host_profile['seed_summary']}\n"
        "BUSINESS OBJECTS: "
        + json.dumps(host_profile["business_objects"], ensure_ascii=False)
        + "\nCURRENT CAPABILITIES: "
        + json.dumps(current_capabilities, ensure_ascii=False)
        + "\nPRIOR EDIT OUTPUTS: "
        + json.dumps(outputs, ensure_ascii=False)
        + "\nRETRIEVAL GOAL: Find a different, natural frontend capability whose prerequisites can "
        "be mapped to the current source. Prefer a new capability family unless a real state dependency "
        "requires extending an earlier Edit."
    )


def _normalize_state_rows(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be non-empty")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{label} row must be an object")
        rows.append(
            {
                "state": _text(item.get("state"), f"{label}.state"),
                "source": _text(item.get("source"), f"{label}.source"),
                "evidence": _text(
                    item.get("evidence"), f"{label}.evidence", minimum=20
                ),
            }
        )
    return rows


def validate_round_selection(
    payload: dict[str, Any],
    *,
    edit_index: int,
    pool_snapshot: str,
    retrieved_capability_ids: list[str],
    prior_edits: list[dict[str, Any]],
    require_source_gap_checks: bool = False,
) -> dict[str, Any]:
    edit_id = f"q{edit_index}"
    # The round number and id are scheduler-owned control fields. Providers may
    # decorate them with a semantic label even when every substantive field is
    # aligned. Preserve the reported values for provenance and canonicalize the
    # control fields; source/target versions and the pool snapshot remain strict.
    provider_control_fields = {
        "edit_index": payload.get("edit_index"),
        "edit_id": payload.get("edit_id"),
    }
    if payload.get("source_version") != f"s{edit_index - 1}":
        raise ValueError("round output has the wrong linear source")
    if payload.get("target_version") != f"s{edit_index}":
        raise ValueError("round output has the wrong linear target")
    if payload.get("pool_snapshot_sha256") != pool_snapshot:
        raise ValueError("round output cites a different capability pool snapshot")
    selected = _text(payload.get("selected_capability_id"), "selected capability")
    if selected not in retrieved_capability_ids:
        raise ValueError("selected capability was not retrieved in this round")
    instruction = _text(payload.get("instruction"), "instruction", minimum=80)
    if len(instruction) > 1800:
        raise ValueError("instruction is too long")
    if _FORBIDDEN_INSTRUCTION.search(instruction):
        raise ValueError("instruction exposes production details")
    dependencies = payload.get("depends_on")
    if dependencies is None:
        dependencies = []
    dependencies = _text_list(dependencies, "depends_on", minimum=0)
    prior_ids = {row["edit_id"] for row in prior_edits}
    if not set(dependencies).issubset(prior_ids):
        raise ValueError("round output depends on a non-prior Edit")
    if edit_index == 1 and dependencies:
        raise ValueError("q1 cannot depend on an earlier Edit")
    requirements = _normalize_state_rows(payload.get("requires"), "requires")
    prior_by_id = {row["edit_id"]: row for row in prior_edits}
    state_owners: dict[str, list[str]] = {}
    for prior_id, prior in prior_by_id.items():
        for produced in prior.get("produces", []):
            state_owners.setdefault(produced["state"], []).append(prior_id)
    for dependency in dependencies:
        declared = [row for row in requirements if row["source"] == dependency]
        available = {
            state["state"] for state in prior_by_id[dependency].get("produces", [])
        }
        if not declared:
            exact_state_rows = [
                row
                for row in requirements
                if row["state"] in available
                and state_owners.get(row["state"]) == [dependency]
            ]
            for row in exact_state_rows:
                row["provider_source"] = row["source"]
                row["source"] = dependency
            declared = exact_state_rows
        if not declared:
            raise ValueError(f"dependency {dependency} has no required state")
        if not any(row["state"] in available for row in declared):
            raise ValueError(f"dependency {dependency} does not consume an exact prior output")
    productions = payload.get("produces")
    if not isinstance(productions, list) or not productions:
        raise ValueError("produces must be non-empty")
    normalized_productions: list[dict[str, str]] = []
    for row in productions:
        if not isinstance(row, dict):
            raise ValueError("produced state must be an object")
        normalized_productions.append(
            {
                "state": _text(row.get("state"), "produces.state"),
                "value_shape": _text(row.get("value_shape"), "produces.value_shape"),
                "scope": _text(row.get("scope"), "produces.scope"),
                "persistence": _text(row.get("persistence"), "produces.persistence"),
                "observable": _text(row.get("observable"), "produces.observable"),
            }
        )
    mapping = payload.get("prerequisite_mapping")
    if not isinstance(mapping, list) or not mapping:
        raise ValueError("prerequisite_mapping must be non-empty")
    normalized_mapping = [
        {
            "prerequisite": _text(row.get("prerequisite"), "prerequisite"),
            "host_evidence": _text(
                row.get("host_evidence"), "prerequisite host evidence", minimum=20
            ),
            "correspondence": _text(
                row.get("correspondence", "structural_or_component_group_analogy"),
                "prerequisite correspondence",
            ),
        }
        for row in mapping
        if isinstance(row, dict)
    ]
    if len(normalized_mapping) != len(mapping):
        raise ValueError("prerequisite mapping row must be an object")
    raw_source_gap_checks = payload.get("source_gap_checks")
    if raw_source_gap_checks is None:
        if require_source_gap_checks:
            raise ValueError("source_gap_checks are required")
        source_gap_checks: list[dict[str, Any]] = []
    else:
        source_gap_checks = validate_source_gap_checks(raw_source_gap_checks)
    return {
        "edit_index": edit_index,
        "edit_id": edit_id,
        "source_version": f"s{edit_index - 1}",
        "target_version": f"s{edit_index}",
        "pool_snapshot_sha256": pool_snapshot,
        "retrieved_capability_ids": list(retrieved_capability_ids),
        "selected_capability_id": selected,
        "selected_family": _text(payload.get("selected_family"), "selected family"),
        "selection_reason": _text(
            payload.get("selection_reason"), "selection reason", minimum=30
        ),
        "prerequisite_mapping": normalized_mapping,
        "instruction": instruction,
        "depends_on": dependencies,
        "requires": requirements,
        "produces": normalized_productions,
        "preserve": _text_list(payload.get("preserve"), "preserve"),
        "acceptance": _text_list(payload.get("acceptance"), "acceptance"),
        "source_gap_checks": source_gap_checks,
        "provider_control_fields": provider_control_fields,
    }


def validate_dynamic_sequence(payload: dict[str, Any]) -> dict[str, Any]:
    seed_id = _text(payload.get("seed_id"), "seed_id")
    pool_snapshot = _text(payload.get("pool_snapshot_sha256"), "pool snapshot")
    edits = payload.get("edits")
    if not isinstance(edits, list) or len(edits) != 5:
        raise ValueError("dynamic sequence requires five Edits")
    selected_ids: list[str] = []
    families: list[str] = []
    retrieval_ids: list[str] = []
    query_hashes: list[str] = []
    dependent = 0
    later_independent = 0
    for index, row in enumerate(edits, 1):
        if row.get("edit_id") != f"q{index}":
            raise ValueError("dynamic sequence Edit ids are not linear")
        if row.get("source_version") != f"s{index - 1}" or row.get(
            "target_version"
        ) != f"s{index}":
            raise ValueError("dynamic sequence page versions are not linear")
        if row.get("pool_snapshot_sha256") != pool_snapshot:
            raise ValueError("dynamic sequence mixes capability pool snapshots")
        selected_ids.append(row["selected_capability_id"])
        families.append(row["selected_family"])
        if row.get("depends_on"):
            dependent += 1
        elif index > 1:
            later_independent += 1
        retrieval = row.get("retrieval")
        if not isinstance(retrieval, dict):
            raise ValueError("each Edit requires a retrieval event")
        if retrieval.get("pool_snapshot_sha256") != pool_snapshot:
            raise ValueError("retrieval event uses the wrong pool snapshot")
        retrieval_ids.append(_text(retrieval.get("request_id"), "retrieval request id"))
        query_hashes.append(_text(retrieval.get("query_sha256"), "retrieval query hash"))
    if len(set(selected_ids)) != 5:
        raise ValueError("each Edit must select a different capability")
    if len(set(retrieval_ids)) != 5 or len(set(query_hashes)) != 5:
        raise ValueError("each Edit must have a distinct retrieval event")
    if len(set(families)) < 3:
        raise ValueError("five Edits must cover at least three capability families")
    if max(families.count(family) for family in set(families)) > 2:
        raise ValueError("one capability family appears more than twice")
    if not 1 <= dependent <= 3:
        raise ValueError("sequence requires one to three dependent Edits")
    if later_independent < 1:
        raise ValueError("sequence requires one later independent Edit")
    return {
        **payload,
        "schema_version": "webcoding-dynamic-capability-edit-sequence-v1",
        "seed_id": seed_id,
        "edit_count": 5,
        "retrieval_event_count": 5,
        "dependent_edit_count": dependent,
        "independent_later_edit_count": later_independent,
        "distinct_family_count": len(set(families)),
    }


def live_screenshot_inputs(observation, *, limit=8):
    """Use only existing state-bound screenshots, bounded to eight and 12 MiB total."""
    allowed = set(compact_live_browser_evidence_for_llm(observation, include_selectors=False)["evidence_state_ids"])
    states = [(key, observation.get(key, {})) for key in ("baseline", "mobile_baseline")]
    groups = [[(f"{p['id']}__before", p.get("before", {}))] +
              [(f"{p['id']}__step_{i}", s.get("state", {}))
               for i, s in enumerate(p.get("steps", []), 1) if s.get("status") == "ok"]
              for p in observation.get("exploration_paths", [])]
    # Reserve before/after views across paths, then add intermediate states.
    for group in groups:
        states.extend([group[0], group[-1]] if len(group) > 1 else group)
    states.extend(row for group in groups for row in group[1:-1])
    images, seen, total, content_images = [], set(), 0, {}
    for state_id, state in states:
        if state_id not in allowed or state_id in seen or not state.get("screenshot_path"):
            continue
        path = Path(state["screenshot_path"])
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        content = path.read_bytes()
        if not content.startswith(b'\x89PNG\r\n\x1a\n'):
            continue
        digest = sha256(content).hexdigest()
        if digest in content_images:
            content_images[digest]['state_ids'].append(state_id)
            seen.add(state_id)
            continue
        if len(images) >= limit or total + len(content) > 12 * 1024 * 1024:
            continue
        item = {"state_id":state_id, "state_ids":[state_id],
                "url":"data:image/png;base64," + base64.b64encode(content).decode()}
        images.append(item)
        content_images[digest] = item
        seen.add(state_id)
        total += len(content)
    return images


def extract_seed_capabilities(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    client: DocApiClient,
    request_id: str,
) -> dict[str, Any]:
    source_project = seed.get("project_path")
    source_url = seed.get("entry_url")
    if bool(source_project) == bool(source_url):
        raise ValueError("Seed requires exactly one project_path or entry_url")
    images = live_screenshot_inputs(observation) if source_url else []
    if "open.bigmodel.cn/api/coding/" in client.base_url:
        images = []
    stable = (
        "CAPABILITY CARD FIELDS\n"
        "Return seed_summary, business_objects[{name,evidence}], and capabilities (empty if no complete feature is supported). "
        "Each capability needs local_id, name, change_type, family, summary, prerequisites, user_actions, "
        "state_reads, state_writes, visible_result, future_uses, source_anchors, "
        "observation_evidence[{state_id,evidence}], and browser_checks. source_anchors are exact literal values "
        "already visible in the supplied browser facts, such as an id value, label, storage key, or route fragment; "
        "prefer post-action success/error text, changed storage keys, or changed route fragments over a generic "
        "control label, because the resulting slice should reach event and state logic; do not invent a source path. "
        "change_type, family and local_id use lowercase snake_case. Every plural field is a JSON array "
        "even when it contains one item; prerequisites is an array of role STRINGS, not objects. "
        "seed_summary, evidence, summary and visible_result are prose STRINGS. "
        "It must contain at least one reusable structural role. "
        "Only record observed changes. Return one card per complete component-level functional system with no fixed count target, "
        "merging all observed operations over the same business objects. Diversify change_type only across distinct systems, "
        "not across controls or actions. A capability must package one complete "
        "workflow or component family, its related controls or regions, full observed action paths or visual transformation, meaningful states, "
        "task-specific feedback, and visible result; do not emit cards for isolated controls or style tokens."
        " Write compact JSON and concise factual prose. Use one short sentence for each summary and visible_result, "
        "and one short factual clause per evidence entry. Do not repeat full page copy, source code, profile "
        "biographies or the same explanation across fields. Retain exact necessary labels, anchors, state IDs, "
        "trigger/result pairs, distinct steps, important values and limitations. Keep every supported capability "
        "and all required fields; brevity must not remove behavior or evidence. Use only the smallest sufficient "
        "evidence set per card: normally one or two source_anchors, observation_evidence entries, future_uses, "
        "state_reads and state_writes. Do not restate user_actions in summary, visible_result or evidence."
    )
    if source_url:
        stable += (
            " This is a live webpage, which may be a business site, gallery, demo or documentation. "
            "Extract observed visual, responsive, interaction, state and accessibility behavior. "
            "Distinguish demonstrated components from the documentation interface. Navigation, search, "
            "theme, support, code-copy and table-of-contents behavior should be omitted unless the requested "
            "target explicitly concerns them. Absence of a demonstrated feature means abstention. Attribute "
            "each retained capability to the actual owning region. Requested types are observation questions, "
            "not proof: report only the behavior supported by supplied browser evidence."
            " Cite only exact IDs from evidence_state_ids; baseline and mobile_baseline are static states. "
            "For interactive cards cite the successful trigger action step (click, hover, fill, key press, etc.) "
            "as well as any later result step. Citing only scrolling or waiting does not establish the trigger. "
            "Initial presentation and viewport comparisons only supplement their owning complete feature. "
            "Each claimed effect must belong to the operated component, not a different demo elsewhere on the page. "
            "Do not complete an unobserved interaction cycle: two clicks do not establish a third click or reset. "
            "A sorter tooltip/icon change alone does not establish reordered rows: omit that incomplete feature. "
            "Do not emit analytics/session tracking, background loading, isolated design tokens or inferred API behavior. "
            "Storage changes alone do not establish a user-visible capability or causal effect. "
            "Use attached screenshots only for their labelled states. A static image cannot establish animation, "
            "Describe colors qualitatively unless an exact CSS value is present in measured facts. "
            "timing, an unobserved state or backend behavior. Without attached images, use measured DOM/layout "
            "facts only, not inferred graphical changes. Do not equate overflow with usable scrolling. "
            "If no coherent user-visible capability is supported, return capabilities=[], business_objects=[] "
            "and abstention_reason. A failed or shell-only page should yield abstention, not invented behavior."
        )
    task = (
        "DOM AND ACCESSIBILITY STATES\n"
        + evidence_json(
            (
                compact_live_browser_evidence_for_llm(
                    observation,
                    include_selectors=False,
                    include_action_steps=True,
                )
                if source_url
                else compact_browser_evidence_for_llm(observation)
            ),
            preserve_states=True,
        )
    )
    if source_url:
        task += "\nATTACHED SCREENSHOT STATE IDS (identical images share all listed IDs):\n" + json.dumps([i['state_ids'] for i in images])
        stable += " For this live crawl, return browser_checks=[]; evidence describes observed behavior, not future tests."
        targets = {key:seed[key] for key in ("target_edit_types", "mining_focus", "expected_observations") if key in seed}
        if targets:
            task += "\nREQUESTED OBSERVATIONS (not browser facts):\n" + json.dumps(targets, ensure_ascii=False)
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=CAPABILITY_EXTRACTION_SYSTEM,
        stable_context=stable,
        task=task,
        max_tokens=8000,
        stream=True,
        **({"images":images} if images else {}),
    )
    return validate_capability_extraction(
        payload,
        seed_id=str(seed["seed_id"]),
        source_project=str(source_project) if source_project else None,
        source_url=str(source_url) if source_url else None,
        observation=observation if source_url else None,
    )


def round_stable_context(seed: dict[str, Any], observation: dict[str, Any]) -> str:
    del seed  # Browser evidence is deliberately the only model-visible Seed input.
    return "HOST DOM AND ACCESSIBILITY STATES\n" + json.dumps(
        compact_browser_evidence_for_llm(observation), ensure_ascii=False
    )


def select_round_edit(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    host_profile: dict[str, Any],
    prior_edits: list[dict[str, Any]],
    retrieved_cards: list[dict[str, Any]],
    retrieval_query: str,
    pool_snapshot: str,
    edit_index: int,
    client: DocApiClient,
    request_id: str,
) -> dict[str, Any]:
    stable = round_stable_context(seed, observation)
    compact_cards = [
        {
            key: row[key]
            for key in (
                "capability_id",
                "name",
                "family",
                "summary",
                "prerequisites",
                "state_reads",
                "state_writes",
                "visible_result",
            )
        }
        for row in retrieved_cards
    ]
    task = (
        f"POOL SNAPSHOT: {pool_snapshot}\n"
        f"ROUND: q{edit_index}, s{edit_index - 1} to s{edit_index}\n"
        f"Set edit_index exactly to {edit_index}, edit_id exactly to q{edit_index}, "
        f"source_version exactly to s{edit_index - 1}, and target_version exactly to s{edit_index}.\n"
        "FRESH RETRIEVAL QUERY\n"
        + retrieval_query
        + "\n\nFRESHLY RETRIEVED CAPABILITIES\n"
        + json.dumps(compact_cards, ensure_ascii=False)
        + "\n\nPRIOR ACCEPTED OR PLANNED EDITS\n"
        + json.dumps(prior_edits, ensure_ascii=False)
        + "\n\nReturn edit_index, edit_id, source_version, target_version, pool_snapshot_sha256, "
        "selected_capability_id, selected_family, selection_reason, "
        "prerequisite_mapping[{prerequisite,host_evidence,correspondence}], instruction, depends_on, "
        "requires[{state,source,evidence}], produces[{state,value_shape,scope,persistence,observable}], "
        "preserve, acceptance, and source_gap_checks[{id,setup_action_count,actions,assertions}]. "
        "The checks describe the desired positive behavior: source should fail them and target should pass them. "
        "Choose exactly one supplied capability. Exact business fields are not required; structural correspondence is enough."
    )
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=ROUND_SELECTION_SYSTEM,
        stable_context=stable,
        task=task,
        max_tokens=7000,
        stream=True,
        cache_stable_context=False,
    )
    return validate_round_selection(
        payload,
        edit_index=edit_index,
        pool_snapshot=pool_snapshot,
        retrieved_capability_ids=[row["capability_id"] for row in retrieved_cards],
        prior_edits=prior_edits,
        require_source_gap_checks=True,
    )


__all__ = [
    "build_round_retrieval_query",
    "capability_embedding_text",
    "extract_seed_capabilities",
    "merge_capability_pool",
    "pool_snapshot_sha256",
    "rank_capabilities",
    "resolve_round_source",
    "round_stable_context",
    "select_round_edit",
    "validate_capability_extraction",
    "validate_dynamic_sequence",
    "validate_round_selection",
]
