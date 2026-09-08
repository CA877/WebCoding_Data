"""Derive target-blind hidden tests from an accepted source and normal Edit.

The module does not create defects.  It translates semantic signals already
produced by the Edit Planner, together with the accepted source UI inventory,
into a small set of WebCompass-shaped risk assertions.  Those assertions are
frozen before Build and can only yield Repair data when a normal candidate
actually fails and is later recovered in the same Sprint.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.orchestration.atomic_edit_plan import read_atomic_edit_plan
from src.orchestration.edit_task_contract import read_edit_task_contract
from src.orchestration.hidden_oracle_checks import (
    read_hidden_oracle_checks,
    write_hidden_oracle_checks,
)
from src.orchestration.ui_action_contracts import TYPED_ASSERTION_ACTIONS
from src.orchestration.webcompass_protocol import REPAIR_TYPES


ARTIFACT_NAME = "edit_risk_tests.json"
SCHEMA_VERSION = "edit-risk-tests-v1"
DEFAULT_MAX_RISK_CHECKS = 11

_SETUP_ACTIONS = {
    "click",
    "drag_and_drop",
    "emulate_media",
    "fill",
    "hover",
    "key_press",
    "reload",
    "scroll",
    "select_option",
    "set_hash",
    "set_input_files",
    "set_storage_value",
    "set_viewport",
    "wait_for",
}
_INTERACTION_ACTIONS = {
    "click",
    "drag_and_drop",
    "fill",
    "hover",
    "key_press",
    "select_option",
    "set_input_files",
}

# These are risk triggers, not defect labels.  The semantic interpretation is
# primarily supplied by planner-authored categories, impact tags and typed
# actions; instruction terms add evidence when the planner uses generic tags.
_TRIGGERS: dict[str, tuple[str, ...]] = {
    "Occlusion": (
        "modal", "dialog", "drawer", "overlay", "popover", "dropdown", "menu",
        "tooltip", "toast", "notification", "fixed", "sticky", "浮层", "弹窗",
        "抽屉", "下拉", "通知",
    ),
    "Crowding": (
        "layout", "responsive", "mobile", "grid", "table", "card", "list",
        "dashboard", "toolbar", "spacing", "布局", "响应式", "表格", "卡片", "间距",
    ),
    "Text Overlap": (
        "text", "label", "title", "description", "table", "card", "tooltip",
        "notification", "responsive", "文本", "标题", "标签", "表格", "响应式",
    ),
    "Alignment": (
        "align", "layout", "grid", "table", "form", "dashboard", "card", "row",
        "column", "对齐", "布局", "网格", "表格", "表单", "卡片",
    ),
    "Color Contrast": (
        "color", "colour", "theme", "dark", "light", "background", "foreground",
        "contrast", "颜色", "主题", "深色", "浅色", "背景", "对比度",
    ),
    "Overflow": (
        "responsive", "mobile", "table", "grid", "carousel", "sidebar", "text",
        "list", "dashboard", "scroll", "width", "响应式", "移动端", "表格", "滚动",
        "宽度", "溢出",
    ),
    "Sizing Proportion": (
        "image", "avatar", "logo", "video", "canvas", "icon", "chart", "ratio",
        "width", "height", "size", "图片", "头像", "视频", "图标", "图表", "尺寸",
        "宽度", "高度", "比例",
    ),
    "Loss of Interactivity": (
        "interaction", "interactive", "button", "link", "filter", "sort", "drag",
        "upload", "form", "wizard", "cart", "auth", "click", "交互", "按钮", "链接",
        "筛选", "排序", "拖拽", "上传", "表单", "购物车", "登录",
    ),
    "Semantic Error": (
        "accessibility", "semantic", "aria", "navigation", "nav", "form", "table",
        "list", "button", "link", "dialog", "可访问", "语义", "导航", "表单", "表格",
        "列表", "按钮", "链接",
    ),
    "Nesting Error": (
        "markup", "structure", "wrap", "nest", "navigation", "form", "table", "list",
        "dialog", "结构", "嵌套", "导航", "表单", "表格", "列表",
    ),
    "Missing Attributes": (
        "accessibility", "aria", "image", "avatar", "logo", "form", "input", "upload",
        "auth", "link", "validation", "可访问", "图片", "头像", "表单", "输入", "上传",
        "链接", "校验",
    ),
}

_SOURCE_TAG_RISKS = {
    "form": {"Loss of Interactivity", "Semantic Error", "Nesting Error", "Missing Attributes"},
    "table": {"Crowding", "Text Overlap", "Alignment", "Overflow", "Semantic Error", "Nesting Error"},
    "img": {"Sizing Proportion", "Missing Attributes"},
    "video": {"Sizing Proportion", "Missing Attributes"},
    "canvas": {"Sizing Proportion"},
    "nav": {"Semantic Error", "Nesting Error", "Missing Attributes"},
    "button": {"Loss of Interactivity", "Semantic Error", "Missing Attributes"},
    "input": {"Loss of Interactivity", "Semantic Error", "Missing Attributes"},
    "select": {"Loss of Interactivity", "Semantic Error", "Missing Attributes"},
}


def artifact_path(harness_dir: Path) -> Path:
    return Path(harness_dir) / ARTIFACT_NAME


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_seed_manifest(workdir: Path) -> dict[str, Any]:
    try:
        payload = json.loads((Path(workdir) / "seed_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_signals(workdir: Path, seed: dict[str, Any]) -> dict[str, Any]:
    """Return bounded facts from the immutable accepted source, never a candidate."""
    contract = seed.get("source_ui_contract")
    if not isinstance(contract, dict):
        contract = {}
    tags: set[str] = set()
    selectors: set[str] = set()
    routes: set[str] = set()
    for page in contract.get("pages") or []:
        if not isinstance(page, dict):
            continue
        routes.add(str(page.get("route") or "/"))
        for group in ("surfaces", "controls", "outputs", "addressable_items"):
            for item in page.get(group) or []:
                if not isinstance(item, dict):
                    continue
                tag = str(item.get("tag") or "").casefold()
                selector = str(item.get("selector") or "").strip()
                if tag:
                    tags.add(tag)
                if selector:
                    selectors.add(selector)
    for item in contract.get("observed_controls") or []:
        if isinstance(item, dict):
            tag = str(item.get("tag") or "").casefold()
            selector = str(item.get("selector") or "").strip()
            if tag:
                tags.add(tag)
            if selector:
                selectors.add(selector)

    # Explicit Edit workdirs made without prepare_forward_edit_seed may not yet
    # have the compact contract.  A bounded tag inventory keeps risk selection
    # source-aware without exposing full source to the implementation model.
    frontend = Path(workdir) / "frontend"
    scanned_files = 0
    scanned_bytes = 0
    for path in sorted(frontend.rglob("*.html"))[:20]:
        if ".git" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            continue
        scanned_files += 1
        scanned_bytes += len(source.encode("utf-8"))
        tags.update(match.casefold() for match in re.findall(r"<\s*([A-Za-z][\w:-]*)\b", source))
        relative = path.relative_to(frontend).as_posix()
        routes.add("/" if relative == "index.html" else "/" + relative)
    return {
        "contract_schema_version": contract.get("schema_version"),
        "routes": sorted(routes),
        "semantic_tags": sorted(tags & set(_SOURCE_TAG_RISKS)),
        "known_selector_count": len(selectors),
        "fallback_html_files_scanned": scanned_files,
        "fallback_html_bytes_scanned": scanned_bytes,
    }


def _check_route(check: dict[str, Any]) -> str:
    return str(check.get("route") or "/")


def _setup_prefix(check: dict[str, Any]) -> list[dict[str, Any]]:
    prefix: list[dict[str, Any]] = []
    for action in check.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if action.get("action") in TYPED_ASSERTION_ACTIONS:
            break
        if action.get("action") in _SETUP_ACTIONS:
            prefix.append(json.loads(json.dumps(action)))
    return prefix


def _target_selector(check: dict[str, Any]) -> str:
    for action in reversed(check.get("actions") or []):
        if not isinstance(action, dict):
            continue
        if action.get("action") in TYPED_ASSERTION_ACTIONS:
            selector = str(action.get("selector") or "").strip()
            if selector:
                return selector
    return "body"


def _interactive_selector(check: dict[str, Any]) -> str:
    for action in check.get("actions") or []:
        if isinstance(action, dict) and action.get("action") in _INTERACTION_ACTIONS:
            selector = str(action.get("selector") or action.get("source_selector") or "").strip()
            if selector:
                return selector
    return _target_selector(check)


def _term_hits(text: str, terms: Iterable[str]) -> list[str]:
    lowered = text.casefold()
    hits: list[str] = []
    for term in terms:
        token = term.casefold()
        if re.search(r"[\u4e00-\u9fff]", token):
            matched = token in lowered
        else:
            matched = re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered) is not None
        if matched:
            hits.append(term)
    return hits[:5]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _ranked_candidates(
    *, instruction_delta: str, plan: dict[str, Any], source: dict[str, Any], routes: list[str]
) -> list[dict[str, Any]]:
    checks = [item for item in plan.get("checks") or [] if isinstance(item, dict)]
    plan_text = " ".join(
        [instruction_delta, str(plan.get("title") or ""), str(plan.get("goal") or "")]
        + [str(item) for item in plan.get("deliverables") or []]
        + [str(item) for item in plan.get("exit_criteria") or []]
        + [str(item) for item in plan.get("impact_tags") or []]
        + [str(item.get("category") or "") for item in checks]
        + [str(item.get("task") or "") for item in checks]
        + [str(item.get("expected_result") or "") for item in checks]
    )
    source_tags = set(source.get("semantic_tags") or [])
    candidates: list[dict[str, Any]] = []
    scenes = [
        (route, check) for route in routes
        for check in ([item for item in checks if _check_route(item) == route] or [{}])
    ]
    for route, representative in scenes:
        action_kinds = {str(action.get("action") or "")
                        for action in representative.get("actions") or []
                        if isinstance(action, dict)}
        setup = _setup_prefix(representative)
        target_selector = _target_selector(representative)
        for repair_type in sorted(REPAIR_TYPES):
            # Taxonomy-first: missing words in the Edit must not suppress an
            # entire defect class. Signals prioritize checks, not enable them.
            score = 2
            reasons: list[str] = ["WebCompass defect audit of the changed surface"]
            hits = _term_hits(plan_text, _TRIGGERS[repair_type])
            if hits:
                score += min(3, len(hits))
                reasons.append("planner semantic signals: " + ", ".join(hits))
            matching_tags = sorted(
                tag for tag in source_tags if repair_type in _SOURCE_TAG_RISKS.get(tag, set())
            )
            if matching_tags and hits:
                score += 1
                reasons.append("accepted source contains: " + ", ".join(matching_tags[:4]))
            if repair_type == "Loss of Interactivity" and action_kinds & _INTERACTION_ACTIONS:
                score += 4
                reasons.append(
                    "planned user actions: "
                    + ", ".join(sorted(action_kinds & _INTERACTION_ACTIONS))
                )
            if repair_type in {"Crowding", "Text Overlap", "Alignment", "Overflow", "Sizing Proportion"} and "set_viewport" in action_kinds:
                score += 3
                reasons.append("planner requires a bounded viewport transition")
            if repair_type == "Color Contrast" and "emulate_media" in action_kinds:
                score += 3
                reasons.append("planner requires a color-scheme transition")
            if repair_type == "Overflow" and target_selector != "body":
                score += 1
                reasons.append("target-local container can regress after this Edit")
            if repair_type in {"Semantic Error", "Missing Attributes"} and target_selector != "body":
                score += 1
                reasons.append("new or changed target DOM is explicitly addressable")
            if repair_type == "Loss of Interactivity" and not (
                action_kinds & _INTERACTION_ACTIONS or hits
            ):
                # A text-only surface is not an intended interactive control.
                continue
            selector = (
                _interactive_selector(representative)
                if repair_type == "Loss of Interactivity"
                else target_selector
            )
            candidates.append(
                {
                    "repair_type": repair_type,
                    "route": route,
                    "selector": selector,
                    "score": score,
                    "reasons": reasons,
                    "setup_actions": setup,
                }
            )
    return sorted(
        candidates,
        key=lambda item: (-int(item["score"]), routes.index(str(item["route"])), str(item["repair_type"])),
    )


def _select_with_route_coverage(
    candidates: list[dict[str, Any]], routes: list[str], limit: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    def identity(item: dict[str, Any]) -> str:
        return json.dumps([item["route"], item["repair_type"], item["selector"],
                           item["setup_actions"]], sort_keys=True)

    used: set[str] = set()
    for route in routes:
        candidate = next((item for item in candidates if item["route"] == route), None)
        if candidate is not None and len(selected) < limit:
            selected.append(candidate)
            used.add(identity(candidate))
    for candidate in candidates:
        key = identity(candidate)
        if key not in used and len(selected) < limit:
            selected.append(candidate)
            used.add(key)
    return selected


def materialize_edit_risk_tests(
    *,
    workdir: Path,
    instruction_delta: str,
    max_checks: int | None = None,
) -> dict[str, Any]:
    """Create and stage relevant hidden risk tests before candidate generation."""
    if max_checks is not None and not 1 <= int(max_checks) <= 11:
        raise ValueError("max_checks must be between 1 and 11")
    workdir = Path(workdir)
    harness_dir = workdir / ".harness"
    plan = read_atomic_edit_plan(harness_dir)
    contract = read_edit_task_contract(workdir)
    if plan is None or contract is None:
        raise ValueError("Edit risk tests require an atomic plan and Edit task contract")
    seed = _read_seed_manifest(workdir)
    source = _source_signals(workdir, seed)
    routes = list(contract.get("requested_target_routes") or [])
    if not routes:
        routes = list(dict.fromkeys(_check_route(item) for item in plan.get("checks") or []))
    if not routes:
        routes = ["/"]
    candidates = _ranked_candidates(
        instruction_delta=instruction_delta,
        plan=plan,
        source=source,
        routes=routes,
    )
    scene_count = sum(max(1, sum(_check_route(check) == route
                                  for check in plan.get("checks") or [])) for route in routes)
    limit = int(max_checks) if max_checks is not None else DEFAULT_MAX_RISK_CHECKS * scene_count
    selected = _select_with_route_coverage(candidates, routes, limit)
    if not selected:
        # A changed, explicitly addressed surface always has one conservative
        # target-local layout risk.  This provides one extra falsifiable check
        # without pretending all 11 defect types are relevant.
        first_check = next(
            (item for item in plan.get("checks") or [] if isinstance(item, dict)), {}
        )
        selected = [{
            "repair_type": "Overflow",
            "route": routes[0],
            "selector": _target_selector(first_check),
            "score": 1,
            "reasons": ["fallback audit for the explicitly changed target surface"],
            "setup_actions": _setup_prefix(first_check),
        }]

    generated: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    for index, risk in enumerate(selected, start=1):
        check_id = f"RISK-{index:02d}-{_slug(str(risk['repair_type'])).upper()}"
        selected_keys.add((str(risk["route"]), str(risk["repair_type"])))
        generated.append({
            "id": check_id,
            "route": risk["route"],
            "origin": "source_edit_risk_analysis",
            "repair_type": risk["repair_type"],
            "risk_reason": "; ".join(risk["reasons"]),
            "actions": [
                *risk["setup_actions"],
                {
                    "action": "assert_webcompass_risk",
                    "selector": risk["selector"],
                    "defect_type": risk["repair_type"],
                },
            ],
        })

    existing = read_hidden_oracle_checks(harness_dir)
    retained = [
        item for item in existing
        if str(item.get("origin") or "") != "source_edit_risk_analysis"
    ]
    visible_ids = {
        str(check.get("id") or "")
        for check in plan.get("checks") or []
        if isinstance(check, dict)
    }
    generated = [
        {**item, "id": item["id"] + "-AUTO"}
        if item["id"] in visible_ids or any(old.get("id") == item["id"] for old in retained)
        else item
        for item in generated
    ]
    write_hidden_oracle_checks(
        harness_dir,
        [*retained, *generated],
        target_routes=routes,
    )

    all_decisions: list[dict[str, Any]] = []
    candidate_map = {
        (str(item["route"]), str(item["repair_type"])): item for item in candidates
    }
    for route in routes:
        for repair_type in sorted(REPAIR_TYPES):
            item = candidate_map.get((route, repair_type))
            all_decisions.append({
                "route": route,
                "repair_type": repair_type,
                "selected": (route, repair_type) in selected_keys,
                "score": int(item["score"]) if item else 0,
                "reasons": list(item["reasons"]) if item else [],
            })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "owner": "harness",
        "prompt_visibility": "hidden",
        "status": "authored_before_build",
        "instruction_sha256": _sha256_text(instruction_delta),
        "baseline_commit": str(contract.get("baseline_commit") or ""),
        "source_signals": source,
        "target_routes": routes,
        "max_generated_checks": limit,
        "test_policy": "webcompass_defects_first",
        "risk_decisions": all_decisions,
        "generated_check_ids": [str(item["id"]) for item in generated],
    }
    path = artifact_path(harness_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def read_edit_risk_tests(harness_dir: Path) -> dict[str, Any] | None:
    path = artifact_path(harness_dir)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("owner") != "harness"
        or payload.get("prompt_visibility") != "hidden"
        or payload.get("status") != "authored_before_build"
    ):
        raise ValueError(f"invalid Edit risk test artifact: {path}")
    return payload


__all__ = [
    "ARTIFACT_NAME",
    "DEFAULT_MAX_RISK_CHECKS",
    "materialize_edit_risk_tests",
    "read_edit_risk_tests",
]
