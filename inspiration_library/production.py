"""Fail-closed contracts for the full WebCoding Edit production workflow.

The functions in this module are provider-free. They validate semantic outputs,
rank already-created embeddings, replay exact patches, and decide whether a
materialized Edit has enough evidence to enter training.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from inspiration_library.state_hypergraph import CapabilityEdge, SeedProfile


TEXT_SUFFIXES = {".html", ".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}
EXPLORATION_ACTIONS = {
    "click",
    "drag_to",
    "mouse_drag",
    "fill",
    "hover",
    "select_option",
    "check",
    "uncheck",
    "key_press",
    "reload",
    "scroll_into_view",
    "wait",
}
BROWSER_ACTIONS = EXPLORATION_ACTIONS
ASSERTION_TYPES = {
    "visible",
    "hidden",
    "text_contains",
    "text_equals",
    "count_equals",
    "count_at_least",
    "attribute_equals",
    "property_equals",
    "storage_json_contains",
    "url_contains",
}
ADMISSION_FIELDS = (
    "source_verified",
    "target_generated",
    "target_browser_passed",
    "regression_passed",
    "resource_closure_passed",
    "patch_replay_passed",
    "order_audit_passed",
)


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of non-empty strings")
    result = list(dict.fromkeys(item.strip() for item in value))
    if len(result) < minimum:
        raise ValueError(f"{field} requires at least {minimum} values")
    return result


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse one JSON object, allowing only a surrounding Markdown JSON fence."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("model response is empty")
    rendered = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", rendered, re.DOTALL)
    if fenced:
        rendered = fenced.group(1)
    if not (rendered.startswith("{") and rendered.endswith("}")):
        raise ValueError("model response must contain only one JSON object")
    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON response: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


def _validate_action(action: Any, *, known_selectors: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ValueError("browser action must be an object")
    kind = action.get("action")
    if kind not in BROWSER_ACTIONS:
        raise ValueError(f"unsupported browser action: {kind!r}")
    result = dict(action)
    if kind not in {"reload", "wait"}:
        selector = _non_empty(action.get("selector"), f"{kind}.selector")
        if known_selectors is not None and selector not in known_selectors:
            raise ValueError(f"unknown selector in exploration action: {selector}")
    if kind in {"drag_to", "mouse_drag"}:
        target_selector = _non_empty(
            action.get("target_selector"), f"{kind}.target_selector"
        )
        if known_selectors is not None and target_selector not in known_selectors:
            raise ValueError(
                f"unknown target selector in exploration action: {target_selector}"
            )
    if kind in {"fill", "select_option"} and not isinstance(
        action.get("value"), (str, int, float)
    ):
        raise ValueError(f"{kind} requires a scalar value")
    if kind == "key_press":
        _non_empty(action.get("key"), "key_press.key")
    if kind == "wait":
        milliseconds = action.get("milliseconds", 200)
        if isinstance(milliseconds, bool) or not isinstance(milliseconds, int) or not 0 <= milliseconds <= 5000:
            raise ValueError("wait.milliseconds must be an integer from 0 to 5000")
    return result


def validate_exploration_plan(
    payload: dict[str, Any], known_selectors: set[str], *, max_paths: int = 4, max_actions: int = 6
) -> dict[str, Any]:
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, list) or not 1 <= len(paths) <= max_paths:
        raise ValueError(f"exploration plan requires 1 to {max_paths} paths")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in paths:
        if not isinstance(item, dict):
            raise ValueError("exploration path must be an object")
        path_id = _non_empty(item.get("id"), "exploration path id")
        if path_id in seen:
            raise ValueError(f"duplicate exploration path id: {path_id}")
        seen.add(path_id)
        actions = item.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= max_actions:
            raise ValueError(f"exploration path {path_id} requires 1 to {max_actions} actions")
        normalized.append(
            {
                "id": path_id,
                "purpose": str(item.get("purpose", "")).strip(),
                "actions": [
                    _validate_action(action, known_selectors=known_selectors)
                    for action in actions
                ],
            }
        )
    return {"paths": normalized}


def _validate_assertion(assertion: Any) -> dict[str, Any]:
    if not isinstance(assertion, dict):
        raise ValueError("browser assertion must be an object")
    assertion_type = assertion.get("type")
    if assertion_type not in ASSERTION_TYPES:
        raise ValueError(f"unsupported assertion: {assertion_type!r}")
    result = dict(assertion)
    if assertion_type in {"attribute_equals", "property_equals"}:
        if "name" not in result and isinstance(result.get("property"), str):
            result["name"] = result.pop("property")
    if assertion_type != "url_contains":
        _non_empty(assertion.get("selector") if assertion_type != "storage_json_contains" else assertion.get("key"), f"{assertion_type}.selector_or_key")
    if assertion_type in {
        "text_contains",
        "text_equals",
        "count_equals",
        "count_at_least",
        "attribute_equals",
        "property_equals",
        "storage_json_contains",
        "url_contains",
    } and "value" not in assertion:
        raise ValueError(f"{assertion_type} requires value")
    if assertion_type in {"attribute_equals", "property_equals"}:
        _non_empty(result.get("name"), f"{assertion_type}.name")
    if assertion_type == "storage_json_contains" and assertion.get("storage", "local") not in {"local", "session"}:
        raise ValueError("storage_json_contains.storage must be local or session")
    return result


def validate_browser_checks(
    checks: Any, *, max_checks: int = 8, max_actions: int = 12, max_assertions: int = 12
) -> list[dict[str, Any]]:
    if not isinstance(checks, list) or not 1 <= len(checks) <= max_checks:
        raise ValueError(f"browser_checks requires 1 to {max_checks} checks")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("browser check must be an object")
        check_id = _non_empty(check.get("id"), "browser check id")
        if check_id in seen:
            raise ValueError(f"duplicate browser check id: {check_id}")
        seen.add(check_id)
        actions = check.get("actions", [])
        assertions = check.get("assertions")
        if not isinstance(actions, list) or len(actions) > max_actions:
            raise ValueError(f"browser check {check_id} has too many actions")
        if not isinstance(assertions, list) or not 1 <= len(assertions) <= max_assertions:
            raise ValueError(f"browser check {check_id} requires 1 to {max_assertions} assertions")
        normalized.append(
            {
                "id": check_id,
                "actions": [_validate_action(action) for action in actions],
                "assertions": [_validate_assertion(item) for item in assertions],
            }
        )
    return normalized


def validate_source_gap_checks(
    checks: Any, *, max_checks: int = 2, max_actions: int = 12, max_assertions: int = 12
) -> list[dict[str, Any]]:
    """Validate positive target checks that must fail on the current source.

    ``setup_action_count`` separates actions that only reach the relevant
    existing page/state from actions that exercise the proposed capability.
    Setup actions must succeed on the source; a later action or assertion must
    fail for the source gap to be established.
    """
    normalized = validate_browser_checks(
        checks,
        max_checks=max_checks,
        max_actions=max_actions,
        max_assertions=max_assertions,
    )
    result: list[dict[str, Any]] = []
    for raw, check in zip(checks, normalized, strict=True):
        setup_count = raw.get("setup_action_count", 0)
        if (
            isinstance(setup_count, bool)
            or not isinstance(setup_count, int)
            or not 0 <= setup_count <= len(check["actions"])
        ):
            raise ValueError(
                f"source gap check {check['id']} has invalid setup_action_count"
            )
        result.append({**check, "setup_action_count": setup_count})
    return result


def validate_seed_profile_payload(
    payload: dict[str, Any], *, project_path: str, observation_path: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("seed profile response must be an object")
    raw_grounding = payload.get("grounding_facts")
    if isinstance(raw_grounding, dict):
        grounding_facts = [
            f"{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}"
            for key, value in raw_grounding.items()
        ]
    else:
        grounding_facts = _string_list(raw_grounding, "grounding_facts", minimum=1)
    profile = {
        "schema_version": "webcoding-seed-state-profile-v2",
        "id": _non_empty(payload.get("id"), "profile.id"),
        "project_path": _non_empty(project_path, "project_path"),
        "domain": _non_empty(payload.get("domain"), "profile.domain"),
        "available_states": _string_list(payload.get("available_states"), "available_states", minimum=1),
        "state_specs": payload.get("state_specs"),
        "current_features": _string_list(payload.get("current_features"), "current_features", minimum=1),
        "preserve": _string_list(payload.get("preserve"), "preserve", minimum=1),
        "bindings": payload.get("bindings", {}),
        "grounding_facts": grounding_facts,
        "natural_gaps": _string_list(payload.get("natural_gaps"), "natural_gaps", minimum=1),
        "core_regression_checks": validate_browser_checks(payload.get("core_regression_checks")),
        "profile_evidence": {
            "observation": _non_empty(observation_path, "observation_path"),
            "semantic_model": "qwen3.8-max",
        },
    }
    if not isinstance(profile["bindings"], dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in profile["bindings"].items()
    ):
        raise ValueError("bindings must map strings to strings")
    specs = profile["state_specs"]
    if not isinstance(specs, dict):
        raise ValueError("state_specs must be an object")
    missing = sorted(set(profile["available_states"]) - set(specs))
    if missing:
        raise ValueError("untyped states: " + ", ".join(missing))
    for state_id in profile["available_states"]:
        spec = specs[state_id]
        if not isinstance(spec, dict):
            raise ValueError(f"state spec {state_id} must be an object")
        for field in ("kind", "value_shape", "scope", "persistence"):
            _non_empty(spec.get(field), f"state_specs.{state_id}.{field}")
        _string_list(spec.get("observables"), f"state_specs.{state_id}.observables", minimum=1)
    # Reuse the planner's complete schema validation before accepting the profile.
    SeedProfile.from_dict(profile)
    return profile


@dataclass(frozen=True)
class CapabilityCard:
    id: str
    summary: str
    prerequisites: tuple[str, ...]
    outputs: tuple[str, ...]
    user_actions: tuple[str, ...]
    verification: tuple[str, ...]
    donor_evidence: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityCard":
        if not isinstance(data, dict):
            raise ValueError("capability card must be an object")
        evidence = data.get("donor_evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("capability card requires donor_evidence")
        return cls(
            id=_non_empty(data.get("id"), "capability card id"),
            summary=_non_empty(data.get("summary"), "capability card summary"),
            prerequisites=tuple(_string_list(data.get("prerequisites"), "prerequisites", minimum=1)),
            outputs=tuple(_string_list(data.get("outputs"), "outputs", minimum=1)),
            user_actions=tuple(_string_list(data.get("user_actions"), "user_actions", minimum=1)),
            verification=tuple(_string_list(data.get("verification"), "verification", minimum=1)),
            donor_evidence=dict(evidence),
        )

    def embedding_text(self) -> str:
        return "\n".join(
            (
                f"Capability: {self.summary}",
                "Prerequisites: " + "; ".join(self.prerequisites),
                "Outputs: " + "; ".join(self.outputs),
                "User actions: " + "; ".join(self.user_actions),
                "Verification: " + "; ".join(self.verification),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "prerequisites": list(self.prerequisites),
            "outputs": list(self.outputs),
            "user_actions": list(self.user_actions),
            "verification": list(self.verification),
            "donor_evidence": dict(self.donor_evidence),
        }


def load_capability_cards(payload: dict[str, Any]) -> tuple[CapabilityCard, ...]:
    rows = payload.get("capabilities") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("capability bank requires a non-empty capabilities list")
    cards = tuple(CapabilityCard.from_dict(item) for item in rows)
    if len({card.id for card in cards}) != len(cards):
        raise ValueError("capability card ids must be unique")
    return cards


def audit_capability_card_references(
    cards: Iterable[CapabilityCard], project_root: Path
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        evidence = card.donor_evidence
        source_value = evidence.get("source_project")
        verification_value = evidence.get("verification")
        case_id = evidence.get("case_id")
        source = (
            (project_root / source_value).resolve()
            if isinstance(source_value, str) and source_value
            else None
        )
        verification = (
            (project_root / verification_value).resolve()
            if isinstance(verification_value, str) and verification_value
            else None
        )
        case_ok = False
        if verification and verification.is_file() and isinstance(case_id, str):
            try:
                if verification.suffix == ".jsonl":
                    payloads = [
                        json.loads(line)
                        for line in verification.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                else:
                    data = json.loads(verification.read_text(encoding="utf-8"))
                    payloads = data if isinstance(data, list) else [data]
                case_ok = any(
                    isinstance(item, dict)
                    and item.get("case_id") == case_id
                    and item.get("status") == "ok"
                    for item in payloads
                )
            except (OSError, json.JSONDecodeError, TypeError):
                case_ok = False
        row = {
            "capability_id": card.id,
            "source_project": str(source) if source else None,
            "verification": str(verification) if verification else None,
            "case_id": case_id,
            "source_exists": bool(source and source.is_dir()),
            "verification_exists": bool(verification and verification.is_file()),
            "verified_case_status_ok": case_ok,
        }
        row["pass"] = all(
            row[key]
            for key in ("source_exists", "verification_exists", "verified_case_status_ok")
        )
        rows.append(row)
    return {"pass": bool(rows) and all(row["pass"] for row in rows), "capabilities": rows}


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("embedding dimensions must be equal and non-empty")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embedding vectors must have non-zero norm")
    return dot / (left_norm * right_norm)


def rank_capability_cards(
    query_vector: list[float],
    cards: Iterable[CapabilityCard],
    vectors: dict[str, list[float]],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    rows: list[dict[str, Any]] = []
    for card in cards:
        vector = vectors.get(card.id)
        if vector is None:
            raise ValueError(f"missing embedding for capability {card.id}")
        rows.append(
            {
                "capability_id": card.id,
                "score": round(_cosine(query_vector, vector), 8),
                "card": card,
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["capability_id"]))
    return rows[:top_k]


def validate_adapted_plan(
    payload: dict[str, Any], retrieved_cards: tuple[CapabilityCard, ...], seed: SeedProfile
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("adapted plan must be an object")
    rows = payload.get("capabilities")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValueError("adapted plan requires 1 to 5 capabilities")
    retrieved = {card.id: card for card in retrieved_cards}
    capabilities: list[CapabilityEdge] = []
    donor_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("adapted capability must be an object")
        donor_id = _non_empty(row.get("donor_capability_id"), "donor_capability_id")
        if donor_id not in retrieved:
            raise ValueError(f"donor capability was not retrieved: {donor_id}")
        checks = validate_browser_checks(row.get("browser_checks"))
        enriched = dict(row)
        enriched["browser_checks"] = checks
        cost_scale = {"low": 0.8, "medium": 1.4, "high": 2.2}
        value_scale = {"low": 1.0, "medium": 2.0, "high": 3.0}
        if isinstance(enriched.get("estimated_cost"), str):
            cost_label = enriched["estimated_cost"].strip().lower()
            if cost_label not in cost_scale:
                raise ValueError(f"unsupported estimated_cost label: {cost_label}")
            enriched["estimated_cost"] = cost_scale[cost_label]
        if isinstance(enriched.get("target_value"), str):
            value_label = enriched["target_value"].strip().lower()
            # Qwen sometimes explains the user value instead of assigning a score.
            # Keep the explanation in the goal/clauses and use the middle score.
            enriched["target_value"] = value_scale.get(value_label, 2.0)
        enriched["donor_evidence"] = {
            **retrieved[donor_id].donor_evidence,
            "capability_id": donor_id,
            "adaptation_relation": _non_empty(
                row.get("adaptation_relation"), "adaptation_relation"
            ) if "adaptation_relation" in row else retrieved[donor_id].summary,
        }
        edge = CapabilityEdge.from_dict(enriched)
        if not edge.compatible_with(seed.domain):
            raise ValueError(f"adapted capability {edge.id} is incompatible with {seed.domain}")
        capabilities.append(edge)
        donor_ids.append(donor_id)
    if len({edge.id for edge in capabilities}) != len(capabilities):
        raise ValueError("adapted capability ids must be unique")
    requested_target_id = _non_empty(
        payload.get("target_capability_id"), "target_capability_id"
    )
    capability_ids = {edge.id for edge in capabilities}
    target_id = requested_target_id
    if target_id not in capability_ids:
        produced_by: dict[str, str] = {}
        for edge in capabilities:
            for state in (*edge.produces, *edge.mutates):
                produced_by[state] = edge.id
        incoming_counts = {
            edge.id: len(
                {
                    produced_by[state]
                    for state in edge.requires
                    if state in produced_by and produced_by[state] != edge.id
                }
            )
            for edge in capabilities
        }
        best_count = max(incoming_counts.values(), default=0)
        structural_targets = [
            capability_id
            for capability_id, count in incoming_counts.items()
            if count == best_count and count > 0
        ]
        if len(structural_targets) != 1:
            raise ValueError("target_capability_id must name an adapted capability")
        target_id = structural_targets[0]
    # Complete typing and graph reachability are checked by the planner stage.
    return {
        "target_capability_id": target_id,
        "requested_target_capability_id": requested_target_id,
        "capabilities": tuple(capabilities),
        "donor_capability_ids": tuple(donor_ids),
    }


def _safe_file(value: Any) -> str:
    name = _non_empty(value, "patch.file").replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe patch path: {name}")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError(f"unsupported patch file: {name}")
    return path.as_posix()


def apply_exact_patches(
    source_files: dict[str, str], patches: list[dict[str, Any]]
) -> dict[str, str]:
    if not isinstance(patches, list) or not 1 <= len(patches) <= 20:
        raise ValueError("patches requires 1 to 20 exact replacements")
    files = dict(source_files)
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("patch must be an object")
        name = _safe_file(patch.get("file"))
        if name not in files:
            raise ValueError(f"patch file does not exist: {name}")
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(search, str) or not search:
            raise ValueError("patch.search must be non-empty text")
        if not isinstance(replace, str):
            raise ValueError("patch.replace must be text")
        count = files[name].count(search)
        if count != 1:
            raise ValueError(
                f"patch search must occur exactly once in {name}; found {count}"
            )
        files[name] = files[name].replace(search, replace, 1)
    return files


def invert_exact_patches(patches: list[dict[str, Any]]) -> list[dict[str, str]]:
    inverse: list[dict[str, str]] = []
    for patch in reversed(patches):
        name = _safe_file(patch.get("file"))
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(search, str) or not search or not isinstance(replace, str):
            raise ValueError("cannot invert malformed exact patch")
        inverse.append({"file": name, "search": replace, "replace": search})
    return inverse


def admission_decision(evidence: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in ADMISSION_FIELDS if evidence.get(field) is not True]
    return {
        "status": "eligible" if not missing else "not_eligible",
        "missing": missing,
        "evidence": {field: evidence.get(field) is True for field in ADMISSION_FIELDS},
    }


__all__ = [
    "CapabilityCard",
    "admission_decision",
    "apply_exact_patches",
    "audit_capability_card_references",
    "invert_exact_patches",
    "load_capability_cards",
    "parse_json_object",
    "rank_capability_cards",
    "validate_adapted_plan",
    "validate_browser_checks",
    "validate_exploration_plan",
    "validate_seed_profile_payload",
]
