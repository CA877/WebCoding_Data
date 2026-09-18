"""Bounded LLM-guided multi-step browser exploration for capability mining."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from inspiration_library.doc_api import DocApiClient
from inspiration_library.linear_edit_queries import (
    compact_browser_evidence_for_llm,
)
from inspiration_library.production import validate_exploration_plan
from inspiration_library.production_browser import observe_project, observe_url


DEEP_EXPLORATION_SYSTEM = """You plan bounded, safe browser paths that reveal different states of a
frontend page. Use only selectors present in the saved browser states. Every path starts from a fresh
page, so include the earlier navigation actions needed to reach a deeper control. Prefer paths that
reveal validation, selection limits, state shared by components, persistence after reload, keyboard,
drag, hover, empty/error/recovery states, responsive or accessibility behavior. Do not read or request
source code, execute JavaScript, access external services, or invent selectors. On a live URL, do not
attempt login, payment, upload, download, deletion, publication, or server-side form submission. Return
one JSON object. On component documentation pages, distinguish the demonstrated component from the
documentation interface. Prioritize controls inside the demonstrated component or example region.
Use header, support, theme, search, copy and documentation navigation only when the requested target
explicitly concerns them or no target-component control is available. On business
sites or visual galleries, explore their actual interface rather than treating them as documentation.
Requested Edit types and observation questions are exploration priorities, never evidence of capability."""


def _parse_exploration_plan_text(text: str) -> dict[str, Any]:
    rendered = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", rendered, re.DOTALL)
    if fenced:
        rendered = fenced.group(1)
    payload = json.loads(rendered)
    if isinstance(payload, list):
        return {"paths": payload}
    if not isinstance(payload, dict):
        raise ValueError("exploration response must be a JSON object or path array")
    return payload


def _validate_model_paths(
    payload: dict[str, Any],
    known_selectors: set[str],
    *,
    max_paths: int,
    max_actions: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list):
        raise ValueError("exploration response requires a paths list")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for index, path in enumerate(raw_paths[:max_paths], 1):
        try:
            normalized = validate_exploration_plan(
                {"paths": [path]},
                known_selectors,
                max_paths=1,
                max_actions=max_actions,
            )
            accepted.extend(normalized["paths"])
        except Exception as exc:
            rejected.append(
                {
                    "path_id": str(path.get("id") if isinstance(path, dict) else index),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return {"paths": accepted}, rejected


def _snapshot_selectors(snapshot: Any) -> set[str]:
    if not isinstance(snapshot, dict):
        return set()
    return {
        str(row["selector"])
        for collection in (
            snapshot.get("interactive", []),
            snapshot.get("landmark_layouts", []),
            snapshot.get("visual_surfaces", []),
        )
        for row in collection
        if isinstance(row, dict) and isinstance(row.get("selector"), str)
    }


def observed_selectors(observation: dict[str, Any]) -> set[str]:
    selectors = _snapshot_selectors(observation.get("baseline"))
    if isinstance(observation.get("baseline"), dict):
        selectors.add("body")
    selectors.update(_snapshot_selectors(observation.get("mobile_baseline")))
    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict):
            continue
        selectors.update(_snapshot_selectors(path.get("before")))
        for step in path.get("steps", []):
            if isinstance(step, dict):
                selectors.update(_snapshot_selectors(step.get("state")))
        selectors.update(_snapshot_selectors(path.get("after")))
    return selectors


def _spread_indices(size: int, count: int | None) -> list[int]:
    if size <= 0:
        return []
    if count is None:            # 不抽样，全量返回
        return list(range(size))
    if count <= 0:
        return []
    if size <= count:
        return list(range(size))
    if count == 1:
        return [size // 2]
    return sorted(
        {
            round(index * (size - 1) / (count - 1))
            for index in range(count)
        }
    )


def _browser_action_for_control(
    control: Any, *, allow_navigation: bool = True
) -> dict[str, Any] | None:
    if not isinstance(control, dict):
        return None
    selector = control.get("selector")
    if not isinstance(selector, str) or not selector or control.get("disabled") is True:
        return None
    if control.get("visible") is False or control.get("horizontally_reachable") is False:
        return None
    tag = str(control.get("tag") or "").lower()
    role = str(control.get("role") or "").lower()
    input_type = str(control.get("type") or "").lower()
    href = str(control.get("href") or "").strip().lower()
    if tag == "a" and not allow_navigation:
        return None
    if tag == "a" and href.startswith(("http://", "https://", "mailto:", "tel:")):
        return None
    if control.get("readonly") is True:
        return {"action": "click", "selector": selector} if role == "combobox" else None
    if tag == "select":
        options = control.get("options") if isinstance(control.get("options"), list) else []
        current = str(control.get("value") or "")
        alternative = next(
            (
                str(option.get("value"))
                for option in options
                if isinstance(option, dict)
                and option.get("value") not in (None, "")
                and str(option.get("value")) != current
            ),
            None,
        )
        return (
            {"action": "select_option", "selector": selector, "value": alternative}
            if alternative is not None
            else None
        )
    if tag == "textarea" or control.get("contenteditable") is True:
        return {"action": "fill", "selector": selector, "value": "Example note"}
    if tag == "input":
        if input_type == "checkbox":
            return {
                "action": "uncheck" if control.get("checked") else "check",
                "selector": selector,
            }
        if input_type in {"radio", "button", "submit", "reset"}:
            return {"action": "click", "selector": selector}
        fill_values = {
            "": "example",
            "text": "example",
            "search": "example",
            "email": "example@example.com",
            "url": "https://example.com",
            "tel": "1234567890",
            "number": "1",
            "date": "2026-01-15",
        }
        if input_type in fill_values:
            return {
                "action": "fill",
                "selector": selector,
                "value": fill_values[input_type],
            }
        return None
    if tag in {"button", "a"} or role in {"button", "tab"}:
        return {"action": "click", "selector": selector}
    events = set(control.get("event_types") or [])
    if "click" in events:
        return {"action": "click", "selector": selector}
    if events.intersection({"mouseenter", "mouseover", "pointerenter", "pointerover"}):
        return {"action": "hover", "selector": selector}
    if control.get("title"):
        return {"action": "hover", "selector": selector}
    return None


def _snapshot_action_candidates(
    snapshot: Any,
    *,
    max_paths: int,
    max_per_pattern: int = 2,
    allow_navigation: bool = True,
    target_text: str = "",
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Inspect every control, then sample within structural action patterns."""

    controls = snapshot.get("interactive") if isinstance(snapshot, dict) else []
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for control in controls if isinstance(controls, list) else []:
        action = _browser_action_for_control(
            control,
            allow_navigation=allow_navigation,
        )
        if action is None:
            continue
        semantic_label = str(
            control.get("aria_label")
            or control.get("data_action")
            or control.get("data_command")
            or control.get("text")
            or control.get("name")
            or control.get("title")
            or control.get("href")
            or ""
        )
        semantic_label = re.sub(r"\d+", "#", " ".join(semantic_label.lower().split()))[:120]
        semantic_tokens = re.findall(r"\w+", semantic_label, flags=re.UNICODE)
        semantic_label = " ".join(semantic_tokens[:3]) or semantic_label
        pattern = json.dumps(
            {
                "action": action["action"],
                "tag": control.get("tag"),
                "role": control.get("role"),
                "type": control.get("type"),
                "checked": control.get("checked"),
                "in_main": control.get("in_main"),
                "semantic_label": semantic_label,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        groups.setdefault(pattern, []).append((control, action))
    draggable = [
        control
        for control in controls if isinstance(controls, list) and isinstance(control, dict)
        if control.get("draggable") is True
        and control.get("visible") is not False
        and control.get("disabled") is not True
        and isinstance(control.get("selector"), str)
    ]
    if len(draggable) >= 2:
        drag_pairs = [
            (
                source,
                {
                    "action": "drag_to",
                    "selector": source["selector"],
                    "target_selector": draggable[index + 1]["selector"],
                },
            )
            for index, source in enumerate(draggable[:-1])
        ]
        groups.setdefault(
            json.dumps({"action": "drag_to", "tag": "draggable"}, sort_keys=True),
            drag_pairs,
        )
    # Long pages may lazy-render or append content near the bottom; pressing End
    # on the page body reaches that region and triggers intersection-based loading.
    try:
        scroll_height = int((snapshot.get("body_size") or {}).get("scroll_height") or 0)
        viewport_height = int((snapshot.get("viewport") or {}).get("height") or 0)
    except (TypeError, ValueError):
        scroll_height = viewport_height = 0
    if scroll_height > 2.5 * max(viewport_height, 1):
        groups.setdefault(
            json.dumps({"action": "key_press", "tag": "page_end"}, sort_keys=True),
            [
                (
                    {"selector": "body", "tag": "body", "in_main": True, "in_component": True},
                    {"action": "key_press", "selector": "body", "key": "End"},
                )
            ],
        )
    target_tokens = {token for token in re.findall(r"[a-z0-9]+", target_text.lower()) if len(token) >= 3}

    def priority(row: tuple[dict[str, Any], dict[str, Any]]) -> int:
        control, action = row
        direct_corpus = " ".join(str(control.get(key) or "") for key in (
            "aria_label", "data_action", "data_command", "text", "name", "title",
        )).lower()
        role_corpus = " ".join(str(control.get(key) or "") for key in ("role", "type", "tag")).lower()
        region_corpus = str(control.get("region_text") or "").lower()
        corpus = f"{direct_corpus} {role_corpus} {region_corpus}"
        score = 8 if control.get("in_component") else 0
        score += 4 if control.get("in_main") else 0
        score += min(12, 6 * sum(token in f"{direct_corpus} {role_corpus}" for token in target_tokens))
        score += min(3, sum(token in region_corpus for token in target_tokens))
        if action.get("action") in {"fill", "select_option", "check", "uncheck"}:
            score += 2
        if control.get("event_types") or control.get("data_action") or control.get("data_command"):
            score += 1
        if any(control.get(key) for key in ("in_header", "in_nav", "in_aside", "in_footer")):
            score -= 10
        if control.get("in_code_region"):
            score -= 12
        if control.get("in_table") and not target_tokens.intersection({"table", "grid"}):
            score -= 8
        if not control.get("in_component") and re.search(
            r"\b(?:support|github|theme|search|documentation|docs|sign in|log in|contact|copy code)\b",
            corpus,
        ):
            score -= 6
        return score

    chosen_by_group: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for pattern, rows in groups.items():
        ordered = sorted(rows, key=priority, reverse=True)
        chosen_by_group[pattern] = [
            ordered[index]
            for index in _spread_indices(len(ordered), max_per_pattern)
        ]
    patterns = sorted(chosen_by_group, key=lambda pattern: max(priority(row) for row in chosen_by_group[pattern]), reverse=True)
    if target_tokens:
        patterns = [
            pattern for pattern in patterns
            if max(priority(row) for row in chosen_by_group[pattern]) >= 6
        ]
    patterns = patterns[:max_paths]
    selected = [chosen_by_group[pattern][0] for pattern in patterns]
    remaining = max_paths - len(selected)
    if remaining > 0:
        second_rows = [
            chosen_by_group[pattern][1]
            for pattern in patterns
            if len(chosen_by_group[pattern]) > 1
        ]
        selected.extend(
            second_rows[index]
            for index in _spread_indices(len(second_rows), remaining)
        )
    return selected


def build_browser_first_exploration_plan(
    observation: dict[str, Any],
    *,
    followup_only: bool = False,
    max_paths: int = 12,
    max_actions: int = 8,
    exploration_targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build safe browser paths without a model call.

    Every observed control is considered. Repeated controls are grouped by
    action-relevant structure and representatives are spread across each group,
    so DOM order never decides a front-N prefix.
    """

    if max_paths < 1 or max_actions < 1:
        raise ValueError("max_paths and max_actions must be positive")
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    target_text = json.dumps(exploration_targets or {}, ensure_ascii=False)
    allow_navigation = observation.get("source_kind") != "live_url"
    if not followup_only:
        baseline = observation.get("baseline")
        for control, action in _snapshot_action_candidates(
            baseline,
            max_paths=max_paths,
            allow_navigation=allow_navigation,
            target_text=target_text,
        ):
            label = str(
                control.get("aria_label")
                or control.get("data_action")
                or control.get("data_command")
                or control.get("text")
                or control.get("name")
                or action.get("selector")
            ).strip()
            candidates.append((f"Try {action['action']} on {label}", [action]))
    else:
        baseline = observation.get("baseline")
        baseline_rows = (
            baseline.get("interactive", []) if isinstance(baseline, dict) else []
        )
        baseline_visible = {
            str(row.get("selector"))
            for row in baseline_rows
            if isinstance(row, dict)
            and row.get("visible") is not False
            and row.get("horizontally_reachable") is not False
            and row.get("selector")
        }
        for path in observation.get("exploration_paths", []):
            if not isinstance(path, dict) or path.get("status") != "ok":
                continue
            steps = path.get("steps") if isinstance(path.get("steps"), list) else []
            prefix = [
                step["action"]
                for step in steps
                if isinstance(step, dict)
                and step.get("status", "ok") == "ok"
                and isinstance(step.get("action"), dict)
            ]
            if not prefix or len(prefix) >= max_actions:
                continue
            final_state = (
                steps[-1].get("state")
                if isinstance(steps[-1], dict)
                else None
            )
            if not isinstance(final_state, dict):
                final_state = path.get("after")
            acted_selectors = {
                str(action.get("selector"))
                for action in prefix
                if action.get("selector")
            }
            for control, action in _snapshot_action_candidates(
                final_state,
                max_paths=max_paths,
                allow_navigation=allow_navigation,
                target_text=target_text,
            ):
                selector = str(action.get("selector") or "")
                baseline_control = next((row for row in baseline_rows if row.get("selector") == selector), {})
                changed = any(control.get(key) != baseline_control.get(key)
                              for key in ("disabled", "checked", "expanded", "selected", "sort", "value", "text", "event_types"))
                if not selector or (selector in baseline_visible and not changed):
                    continue
                if selector in acted_selectors and not changed:
                    continue
                label = str(
                    control.get("aria_label")
                    or control.get("data_action")
                    or control.get("data_command")
                    or control.get("text")
                    or control.get("name")
                    or selector
                ).strip()
                candidates.append(
                    (f"Reach the revealed control and try {action['action']} on {label}", prefix + [action])
                )
    unique: list[tuple[str, list[dict[str, Any]]]] = []
    seen: set[str] = {
        json.dumps([step["action"] for step in path.get("steps", []) if step.get("status") == "ok"],
                   ensure_ascii=False, sort_keys=True)
        for path in observation.get("exploration_paths", []) if path.get("status") == "ok"
    }
    for purpose, actions in candidates:
        signature = json.dumps(actions, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((purpose, actions))
    if len(unique) > max_paths:
        unique = [unique[index] for index in _spread_indices(len(unique), max_paths)]
    return {
        "paths": [
            {"id": f"browser_{index}", "purpose": purpose, "actions": actions}
            for index, (purpose, actions) in enumerate(unique, 1)
        ]
    }


def exploration_planning_context(observation: dict[str, Any]) -> str:
    """Serialize browser facts only; source files never enter exploration planning."""

    from inspiration_library.prompt_evidence import evidence_json
    if observation.get("source_kind") == "live_url":
        payload = compact_live_browser_evidence_for_llm(
            observation,
            include_selectors=True,
            control_limit=48,
        )
        return "SAVED BROWSER STATES\n" + evidence_json(payload, preserve_selectors=True) + (
            '\nCopy action selectors literally from supplied selector fields. Do not invent generic '
            'or deeper-state selectors, even after opening a dialog; omit unsupported actions.')
    payload = compact_browser_evidence_for_llm(
        observation, include_known_selectors=True
    )
    return "SAVED BROWSER STATES\n" + evidence_json(payload, preserve_selectors=True) + (
        '\nCopy action selectors literally from supplied selector fields. Do not invent generic '
        'or deeper-state selectors, even after opening a dialog; omit unsupported actions.')


def _coverage_rows(rows: list[Any], limit: int | None) -> list[Any]:
    """按「尽量分散」的策略抽 limit 行；`limit=None` 表示全取。"""
    return [rows[index] for index in _spread_indices(len(rows), limit)]


def _coverage_text(value: Any, limit: int) -> list[str]:
    rows: list[str] = []
    for line in str(value or "").splitlines():
        normalized = " ".join(line.split())
        if normalized and normalized not in rows:
            rows.append(normalized[:500])
    return _coverage_rows(rows, limit)


def _online_control_rows(
    observation: dict[str, Any],
    *,
    include_selectors: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for key in ("baseline", "mobile_baseline"):
        value = observation.get(key)
        if isinstance(value, dict):
            snapshots.append(value)
    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict):
            continue
        for step in path.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("state"), dict):
                snapshots.append(step["state"])
        if isinstance(path.get("after"), dict):
            snapshots.append(path["after"])

    groups: dict[str, list[dict[str, Any]]] = {}
    for snapshot in snapshots:
        controls = snapshot.get("interactive", [])
        main_controls = [
            row
            for row in controls
            if isinstance(row, dict)
            and row.get("in_main")
            and row.get("visible") is not False
        ]
        eligible = main_controls or [
            row
            for row in controls
            if isinstance(row, dict) and row.get("visible") is not False
        ]
        for row in eligible:
            semantic = str(
                row.get("aria_label")
                or row.get("data_action")
                or row.get("data_command")
                or row.get("text")
                or row.get("name")
                or row.get("title")
                or ""
            )
            pattern = json.dumps(
                {
                    "tag": row.get("tag"),
                    "role": row.get("role"),
                    "type": row.get("type"),
                    "semantic": re.sub(r"\d+", "#", " ".join(semantic.lower().split()))[:100],
                },
                sort_keys=True,
            )
            compact = {
                key: row[key]
                for key in (
                    "selector",
                    "tag",
                    "role",
                    "type",
                    "text",
                    "aria_label",
                    "name",
                    "value",
                    "checked",
                    "disabled",
                    "readonly",
                    "draggable",
                    "options",
                )
                if row.get(key) not in (None, "", [], {})
                and (include_selectors or key != "selector")
            }
            signature = json.dumps(compact, ensure_ascii=False, sort_keys=True)
            if all(
                json.dumps(existing, ensure_ascii=False, sort_keys=True) != signature
                for existing in groups.setdefault(pattern, [])
            ):
                groups[pattern].append(compact)
    selected: list[dict[str, Any]] = []
    for pattern in sorted(groups):
        selected.extend(_coverage_rows(groups[pattern], 2))
    return _coverage_rows(selected, limit)


def _style_patterns(snapshot: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    counts: dict[str, tuple[dict[str, Any], int]] = {}
    for row in snapshot.get("style_samples", []):
        if not isinstance(row, dict):
            continue
        pattern = {
            key: row[key]
            for key in (
                "tag",
                "role",
                "font_family",
                "font_size",
                "font_weight",
                "color",
                "background_color",
                "border_radius",
                "border_width",
                "box_shadow",
                "letter_spacing",
            )
            if row.get(key) not in (None, "", [], {})
        }
        signature = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
        previous = counts.get(signature)
        counts[signature] = (pattern, 1 if previous is None else previous[1] + 1)
    rows = [{**pattern, "count": count} for pattern, count in counts.values()]
    rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    return _coverage_rows(rows, limit)


def _layout_patterns(snapshot: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    rows = []
    for row in snapshot.get("landmark_layouts", []):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                key: row[key]
                for key in (
                    "tag",
                    "role",
                    "display",
                    "position",
                    "overflow_x",
                    "overflow_y",
                    "grid_columns",
                    "flex_direction",
                    "width",
                    "height",
                )
                if row.get(key) not in (None, "", [], {})
            }
        )
    unique = {
        json.dumps(row, ensure_ascii=False, sort_keys=True): row for row in rows
    }
    return _coverage_rows([unique[key] for key in sorted(unique)], limit)


def _flatten_live_facts(value: Any, prefix: str = "") -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            child = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_live_facts(item, child))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_flatten_live_facts(item, prefix))
    elif value not in (None, ""):
        rows.append(f"{prefix}={str(value)[:240]}")
    return rows


def _bounded_live_delta(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, value in row.items():
        if value in (None, "", [], {}):
            continue
        rendered = json.dumps(value, ensure_ascii=False)
        if len(rendered) <= 800:
            compact[key] = value
            continue
        facts = sorted(set(_flatten_live_facts(value)))
        compact[key] = {
            "fact_count": len(facts),
            "fact_coverage": _coverage_rows(facts, 6),
        }
    return compact


def compact_live_browser_evidence_for_llm(
    observation: dict[str, Any],
    *,
    include_selectors: bool,
    control_limit: int | None = 64,
    include_action_steps: bool = False,
) -> dict[str, Any]:
    """Bound a live docs page while retaining spread component evidence.

    `control_limit=None` 表示不抽样，把全部去重后的控件都交给模型（用于量化上限损失）。
    """

    baseline = observation.get("baseline")
    mobile = observation.get("mobile_baseline")
    baseline = baseline if isinstance(baseline, dict) else {}
    mobile = mobile if isinstance(mobile, dict) else {}
    compact = compact_browser_evidence_for_llm(
        observation,
        include_known_selectors=False,
        max_transition_states=32,
    )
    transition_catalog = [
        _bounded_live_delta(row)
        for row in _coverage_rows(compact.get("state_delta_catalog", []), 16)
    ]
    kept_delta_ids = {row["delta_id"] for row in transition_catalog}
    transitions = [
        {**row, "state_delta_refs": [ref for ref in row.get("state_delta_refs", []) if ref in kept_delta_ids]}
        for row in compact.get("transitions", [])
    ]
    origins = sorted(
        {
            f"{parsed.scheme}://{parsed.netloc}"
            for value in observation.get("remote_requests", [])
            if (parsed := urlsplit(str(value))).scheme and parsed.netloc
        }
    )
    controls = _online_control_rows(
        observation,
        include_selectors=include_selectors,
        limit=control_limit,
    )
    # A trigger may not change the DOM until a later wait. Keep the complete
    # action chain even when the existing visual-delta view omitted that state.
    action_steps = [
        {'state_id': f"{path['id']}__step_{index}", 'status': step.get('status'),
         'action': step.get('action')}
        for path in observation.get('exploration_paths', [])
        for index, step in enumerate(path.get('steps', []), 1)
    ]
    return {
        "status": observation.get("status"),
        "source_kind": "live_url",
        "evidence_state_ids": [key for key, state in (("baseline", baseline), ("mobile_baseline", mobile)) if state]
        + list(dict.fromkeys(row["state_id"] for row in transition_catalog))
        + [f"{path['id']}__before" for path in observation.get("exploration_paths", []) if path.get("before")]
        + ([row['state_id'] for row in action_steps if row['status'] == 'ok'] if include_action_steps else []),
        **({'action_steps': action_steps} if include_action_steps else {}),
        "visual_routing": observation.get("visual_routing", {}),
        "image_input": "selected_state_screenshots_when_available",
        "observation_limits": ["top_document_only", "readonly_network", "bounded_exploration"],
        "page": {
            "url": baseline.get("url"),
            "title": baseline.get("title"),
            "visible_text_coverage": _coverage_text(baseline.get("visible_text"), 80),
            "accessibility_coverage": _coverage_text(baseline.get("aria_snapshot"), 80),
            "viewport": baseline.get("viewport"),
            "horizontal_overflow": baseline.get("horizontal_overflow"),
        },
        "mobile": {
            "viewport": mobile.get("viewport"),
            "horizontal_overflow": mobile.get("horizontal_overflow"),
            "visible_text_coverage": _coverage_text(mobile.get("visible_text"), 40),
        },
        "observed_controls": controls,
        "embedded_documents": baseline.get("embedded_documents", []),
        "observed_control_total": len(baseline.get("interactive", [])),
        "desktop_layout_patterns": _layout_patterns(baseline, 10),
        "mobile_layout_patterns": _layout_patterns(mobile, 10),
        "style_patterns": _style_patterns(baseline, 12),
        "transitions": transitions,
        "state_delta_catalog": transition_catalog,
        "remote_origins": origins,
        "console_errors": observation.get("console_errors", [])[:8],
        "page_errors": observation.get("page_errors", [])[:8],
        "dialog_events": observation.get("dialog_events", [])[:8],
    }


def _state_signatures(observation: dict[str, Any]) -> set[str]:
    signatures: set[str] = set()
    for key in ("baseline", "mobile_baseline"):
        snapshot = observation.get(key)
        if isinstance(snapshot, dict) and snapshot.get("state_sha256"):
            signatures.add(str(snapshot["state_sha256"]))
    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict):
            continue
        for step in path.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("state"), dict):
                signature = step["state"].get("state_sha256")
                if signature:
                    signatures.add(str(signature))
        if isinstance(path.get("after"), dict) and path["after"].get("state_sha256"):
            signatures.add(str(path["after"]["state_sha256"]))
    return signatures


def merge_observations(
    previous: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    paths: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for observation in (previous, current):
        for path in observation.get("exploration_paths", []):
            if not isinstance(path, dict):
                continue
            path_id = str(path.get("id", ""))
            if not path_id or path_id in seen_ids:
                continue
            seen_ids.add(path_id)
            paths.append(path)
    return {
        **previous,
        "schema_version": "webcoding-browser-deep-observation-v1",
        "status": (
            "ok"
            if previous.get("status") == "ok" and current.get("status") == "ok"
            else "partial" if previous.get("source_kind") == "live_url" else "error"
        ),
        "mobile_baseline": previous.get("mobile_baseline")
        or current.get("mobile_baseline"),
        "exploration_paths": paths,
        "remote_requests": sorted(
            set(previous.get("remote_requests", []))
            | set(current.get("remote_requests", []))
        ),
        "console_errors": previous.get("console_errors", [])
        + current.get("console_errors", []),
        "page_errors": previous.get("page_errors", []) + current.get("page_errors", []),
        "dialog_events": previous.get("dialog_events", [])
        + current.get("dialog_events", []),
    }


def _deep_explore(
    *,
    observe: Callable[..., dict[str, Any]],
    output_dir: Path,
    client: DocApiClient,
    request_prefix: str,
    max_rounds: int = 2,
    max_paths: int = 12,
    max_actions: int = 8,
    exploration_targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run browser-made paths first, then optional model-planned rounds."""

    if not 0 <= max_rounds <= 2:
        raise ValueError("max_rounds must be from 0 to 2")
    output_dir.mkdir(parents=True, exist_ok=True)
    targets_path = output_dir / "exploration_targets.json"
    requested_targets = exploration_targets or {}
    if targets_path.exists():
        if json.loads(targets_path.read_text(encoding="utf-8")) != requested_targets:
            raise ValueError("Exploration targets changed; use a fresh run directory")
    elif requested_targets and any(output_dir.iterdir()):
        raise ValueError("Existing exploration has no matching target manifest; use a fresh run directory")
    targets_path.write_text(json.dumps(requested_targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    final_path = output_dir / "observation.json"
    if final_path.exists():
        return json.loads(final_path.read_text(encoding="utf-8"))

    def observe_or_resume(
        destination: Path,
        *,
        exploration_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        saved = destination / "observation.json"
        if saved.exists():
            return json.loads(saved.read_text(encoding="utf-8"))
        return observe(destination, exploration_plan=exploration_plan)

    combined = observe_or_resume(output_dir / "baseline")
    browser_first_rows: list[dict[str, Any]] = []
    remaining_paths = 2 * max_paths
    auto_rounds = min(4, max_actions + 1)
    for browser_round in range(1, auto_rounds + 1):
        followup_only = browser_round > 1
        round_paths = max_paths if browser_round == 1 else max(1, remaining_paths // (auto_rounds - browser_round + 1))
        if remaining_paths <= 0:
            break
        plan = build_browser_first_exploration_plan(
            combined,
            followup_only=followup_only,
            max_paths=min(remaining_paths, round_paths),
            max_actions=max_actions,
            exploration_targets=exploration_targets,
        )
        if not plan["paths"]:
            break
        remaining_paths -= len(plan["paths"])
        for path in plan["paths"]:
            path["id"] = f"b{browser_round}_{path['id']}"
        known_selectors = observed_selectors(combined)
        normalized_plan = validate_exploration_plan(
            plan,
            known_selectors,
            max_paths=max_paths,
            max_actions=max_actions,
        )
        plan_path = output_dir / f"browser_plan_round_{browser_round}.json"
        plan_path.write_text(
            json.dumps(normalized_plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        before_states = _state_signatures(combined)
        before_selectors = observed_selectors(combined)
        observed = observe_or_resume(
            output_dir / f"browser_round_{browser_round}",
            exploration_plan=normalized_plan,
        )
        combined = merge_observations(combined, observed)
        browser_first_rows.append(
            {
                "round": browser_round,
                "path_count": len(normalized_plan["paths"]),
                "new_state_count": len(_state_signatures(combined) - before_states),
                "new_selector_count": len(
                    observed_selectors(combined) - before_selectors
                ),
            }
        )
        if not browser_first_rows[-1]["new_state_count"] and not browser_first_rows[-1]["new_selector_count"]:
            break
    planning_rows: list[dict[str, Any]] = []
    for round_index in range(1, max_rounds + 1):
        known_selectors = observed_selectors(combined)
        if not known_selectors:
            break
        request_id = f"{request_prefix}__explore_{round_index}"
        response_path = client.log_dir / "responses" / f"{request_id}.txt"
        if response_path.exists():
            payload = _parse_exploration_plan_text(
                response_path.read_text(encoding="utf-8")
            )
        else:
            response_text, _ = client.chat_text(
                request_id=request_id,
                system_prompt=DEEP_EXPLORATION_SYSTEM,
                stable_context=exploration_planning_context(combined),
                task=(
                    f"Return exactly one JSON object shaped as {{\"paths\":[...]}} with 1-{max_paths} "
                    f"paths; every path has id, purpose and 1-{max_actions} actions. "
                    "Allowed actions: click, drag_to, fill, hover, select_option, check, uncheck, "
                    "key_press, reload, scroll_into_view, wait. Use these exact action shapes: "
                    "click/hover/check/uncheck/scroll_into_view={action,selector}; "
                    "fill/select_option={action,selector,value}; "
                    "drag_to={action,selector,target_selector}; "
                    "key_press={action,selector,key}; reload={action}; "
                    "wait={action,milliseconds}, where milliseconds is an integer from 0 to 5000. "
                    "Never substitute value for key or milliseconds. The selector body is allowed "
                    "only for testing a page-level keyboard shortcut. For a deeper-state selector, "
                    "repeat the full navigation prefix from the baseline."
                    + ("\nREQUESTED OBSERVATIONS (questions, not observed facts):\n"
                       + json.dumps(exploration_targets, ensure_ascii=False) if exploration_targets else "")
                ),
                max_tokens=4000,
                stream=True,
                cache_stable_context=False,
            )
            payload = _parse_exploration_plan_text(response_text)
        plan, rejected_paths = _validate_model_paths(
            payload,
            known_selectors,
            max_paths=max_paths,
            max_actions=max_actions,
        )
        if not plan["paths"]:
            planning_rows.append(
                {
                    "round": round_index,
                    "path_count": 0,
                    "rejected_path_count": len(rejected_paths),
                    "rejected_paths": rejected_paths,
                    "new_state_count": 0,
                    "new_selector_count": 0,
                }
            )
            break
        for path in plan["paths"]:
            path["id"] = f"r{round_index}_{path['id']}"
        plan_path = output_dir / f"exploration_plan_round_{round_index}.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        before_states = _state_signatures(combined)
        before_selectors = observed_selectors(combined)
        observed = observe_or_resume(
            output_dir / f"round_{round_index}",
            exploration_plan=plan,
        )
        combined = merge_observations(combined, observed)
        new_state_count = len(_state_signatures(combined) - before_states)
        new_selector_count = len(observed_selectors(combined) - before_selectors)
        planning_rows.append(
            {
                "round": round_index,
                "path_count": len(plan["paths"]),
                "new_state_count": new_state_count,
                "new_selector_count": new_selector_count,
                "rejected_path_count": len(rejected_paths),
                "rejected_paths": rejected_paths,
            }
        )
        if new_state_count == 0 and new_selector_count == 0:
            break
    combined["deep_search"] = {
        "method": "browser_generated_paths_then_optional_llm_paths",
        "source_code_visible_to_planner": False,
        "browser_first_rounds": browser_first_rows,
        "requested_llm_rounds": max_rounds,
        "completed_llm_rounds": planning_rows,
        "llm_planning_calls": len(planning_rows),
        "exploration_targets": exploration_targets or {},
    }
    final_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return combined


def deep_explore_project(
    *,
    project: Path,
    output_dir: Path,
    client: DocApiClient,
    request_prefix: str,
    max_rounds: int = 2,
    max_paths: int = 12,
    max_actions: int = 8,
) -> dict[str, Any]:
    return _deep_explore(
        observe=lambda destination, exploration_plan=None: observe_project(
            project,
            destination,
            exploration_plan=exploration_plan,
        ),
        output_dir=output_dir,
        client=client,
        request_prefix=request_prefix,
        max_rounds=max_rounds,
        max_paths=max_paths,
        max_actions=max_actions,
    )


def deep_explore_url(
    *,
    entry_url: str,
    output_dir: Path,
    client: DocApiClient,
    request_prefix: str,
    max_rounds: int = 2,
    max_paths: int = 12,
    max_actions: int = 8,
    exploration_targets: dict[str, Any] | None = None,
    ready_selector: str | None = None,
) -> dict[str, Any]:
    return _deep_explore(
        observe=lambda destination, exploration_plan=None: observe_url(
            entry_url,
            destination,
            exploration_plan=exploration_plan,
            ready_selector=ready_selector,
        ),
        output_dir=output_dir,
        client=client,
        request_prefix=request_prefix,
        max_rounds=max_rounds,
        max_paths=max_paths,
        max_actions=max_actions,
        exploration_targets=exploration_targets,
    )


__all__ = [
    "DEEP_EXPLORATION_SYSTEM",
    "build_browser_first_exploration_plan",
    "compact_live_browser_evidence_for_llm",
    "deep_explore_project",
    "deep_explore_url",
    "exploration_planning_context",
    "merge_observations",
    "observed_selectors",
]
