"""Validated task contracts for interaction-rich Edit and evidence-backed Repair.

The existing v2 records remain the training/export view.  This module defines
the hidden construction contract used to create and evaluate richer 0805
samples before they are projected into a training view.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any


SCHEMA_VERSION = "webcoding-task-spec-v3"

INTERACTION_TYPES = (
    "click",
    "hover",
    "focus",
    "input",
    "select",
    "toggle",
    "tab_switch",
    "accordion",
    "dropdown",
    "modal",
    "tooltip",
    "carousel",
    "drag_drop",
    "sort",
    "filter",
    "pagination",
    "navigation",
    "form_validation",
    "conditional_rendering",
    "loading_state",
    "toast",
    "animation",
)

INTERACTION_GUIDELINES: dict[str, str] = {
    "click": "Add a click target whose activation causes an immediate, observable state change.",
    "hover": "Add a hover state that visibly changes or reveals meaningful contextual content.",
    "focus": "Add a keyboard-reachable focus state with a clear visual and semantic response.",
    "input": "Add an input-driven update whose visible result changes as the user types.",
    "select": "Add a selection control whose chosen value visibly updates related content.",
    "toggle": "Add a binary control with distinct on/off states and persistent visible feedback.",
    "tab_switch": "Add tabs with distinct panels, active styling, and keyboard-operable switching.",
    "accordion": "Add expandable panels with visible open/closed states and ARIA state updates.",
    "dropdown": "Add an openable option/menu surface with selection and dismiss behavior.",
    "modal": "Add a modal with backdrop, focus handling, close controls, and visible open state.",
    "tooltip": "Add contextual content visible on hover and keyboard focus, with a stable target state.",
    "carousel": "Add deterministic previous/next slide changes with an observable active item.",
    "drag_drop": "Add direct manipulation whose completed drop changes item order or ownership.",
    "sort": "Add ascending/descending ordering with a visible order and active-direction indicator.",
    "filter": "Add a filter that changes visible results and exposes the active filter state.",
    "pagination": "Add page controls that change the visible result slice and current page state.",
    "navigation": "Add same-origin navigation with an observable destination and valid return path.",
    "form_validation": "Add valid and invalid form states with inline, accessible feedback.",
    "conditional_rendering": "Add a user-triggered condition that inserts, removes, or replaces content.",
    "loading_state": "Add a deterministic transient loading state followed by a settled result.",
    "toast": "Add a user-triggered status message with a capturable visible state.",
    "animation": "Add a deterministic user-triggered animation with stable before/after keyframes.",
}

# These are provenance/capability references for construction.  They are not
# claims that a generated sample is copied from, or evaluated by, each source.
BENCHMARK_SOURCES_BY_INTERACTION: dict[str, tuple[str, ...]] = {
    "click": ("Interaction2Code", "ArtifactsBench", "WebCompass"),
    "hover": ("Interaction2Code", "FrontendBench", "WebCompass"),
    "focus": ("FrontendBench", "WebCompass"),
    "input": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "select": ("Interaction2Code", "ArtifactsBench", "WebCompass"),
    "toggle": ("Interaction2Code", "FrontendBench", "WebCompass"),
    "tab_switch": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "accordion": ("FrontendBench", "WebCompass"),
    "dropdown": ("Interaction2Code", "FrontendBench", "WebCompass"),
    "modal": ("Interaction2Code", "ArtifactsBench", "WebCompass"),
    "tooltip": ("Interaction2Code", "FrontendBench", "WebCompass"),
    "carousel": ("Interaction2Code", "FrontendBench", "WebCompass"),
    "drag_drop": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "sort": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "filter": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "pagination": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "navigation": ("Interaction2Code", "ArtifactsBench", "WebCompass"),
    "form_validation": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "conditional_rendering": ("Interaction2Code", "ArtifactsBench", "FrontendBench"),
    "loading_state": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "toast": ("ArtifactsBench", "FrontendBench", "WebCompass"),
    "animation": ("Interaction2Code", "FrontendBench", "WebCompass"),
}

INTERACTION_TASK_TYPE_BY_INTERACTION = {
    "click": "Click State",
    "hover": "Hover State",
    "focus": "Focus State",
    "input": "Input-driven Update",
    "select": "Select Control",
    "toggle": "Toggle Control",
    "tab_switch": "Tab Switch",
    "accordion": "Accordion",
    "dropdown": "Dropdown",
    "modal": "Modal Dialog",
    "tooltip": "Tooltip",
    "carousel": "Carousel",
    "drag_drop": "Drag & Drop Interface",
    "sort": "Sort Control",
    "filter": "Filter Control",
    "pagination": "Pagination",
    "navigation": "Navigation Flow",
    "form_validation": "Form Validation",
    "conditional_rendering": "Conditional Rendering",
    "loading_state": "Loading State",
    "toast": "Toast Notifications",
    "animation": "Animation State",
}


def interaction_types_for_tasks(task_types: list[str]) -> list[str]:
    reverse = {task: interaction for interaction, task in INTERACTION_TASK_TYPE_BY_INTERACTION.items()}
    return [reverse[task] for task in task_types if task in reverse]

REPAIR_FAMILIES = (
    "runtime_repair",
    "visual_repair",
    "interaction_repair",
    "quality_refinement",
)

# Leaf-level controlled-repair taxonomy.  ``benchmark_alignment`` records the
# capability/evaluator that motivated a mutation; it never claims that the
# generated row is an official sample from that benchmark.
REPAIR_DEFECT_TAXONOMY: dict[str, dict[str, Any]] = {
    "compile_syntax": {"family": "runtime_repair", "subfamily": "build_compile", "benchmarks": ("DesignBench",)},
    "module_dependency": {"family": "runtime_repair", "subfamily": "build_compile", "benchmarks": ("DesignBench", "WebGen-Bench")},
    "framework_component_api": {"family": "runtime_repair", "subfamily": "build_compile", "benchmarks": ("DesignBench", "Flame-VLM-Code")},
    "type_build_config": {"family": "runtime_repair", "subfamily": "build_compile", "benchmarks": ("DesignBench",)},
    "bootstrap_render_crash": {"family": "runtime_repair", "subfamily": "boot_render", "benchmarks": ("ArtifactsBench", "WebGen-Bench")},
    "event_runtime_exception": {"family": "runtime_repair", "subfamily": "event_runtime", "benchmarks": ("ArtifactsBench", "WebGen-Bench")},
    "route_resource_failure": {"family": "runtime_repair", "subfamily": "route_resource", "benchmarks": ("Vision2Web", "WebGen-Bench")},
    "async_lifecycle_failure": {"family": "runtime_repair", "subfamily": "async_lifecycle", "benchmarks": ("ArtifactsBench", "WebGen-Bench")},
    "storage_persistence_failure": {"family": "runtime_repair", "subfamily": "state_persistence", "benchmarks": ("Vision2Web", "WebGen-Bench")},
    "occlusion": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "crowding": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "text_overlap": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "alignment": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "overflow": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "sizing_proportion": {"family": "visual_repair", "subfamily": "layout_geometry", "benchmarks": ("WebCompass", "DesignBench")},
    "color_contrast": {"family": "visual_repair", "subfamily": "appearance_style", "benchmarks": ("WebCompass", "DesignBench")},
    "missing_or_extra_element": {"family": "visual_repair", "subfamily": "content_presence", "benchmarks": ("Design2Code", "Web2Code")},
    "responsive_layout": {"family": "visual_repair", "subfamily": "responsive", "benchmarks": ("Vision2Web",)},
    "dynamic_visual_state": {"family": "visual_repair", "subfamily": "dynamic_state", "benchmarks": ("Interaction2Code", "FullFront")},
    "overlay_layering": {"family": "visual_repair", "subfamily": "overlay", "benchmarks": ("Interaction2Code", "WebCompass")},
    "animation_transition_visual": {"family": "visual_repair", "subfamily": "animation", "benchmarks": ("Interaction2Code", "ArtifactsBench")},
    "cross_page_visual_consistency": {"family": "visual_repair", "subfamily": "cross_page", "benchmarks": ("Vision2Web", "ComUIBench")},
    "missing_handler": {"family": "interaction_repair", "subfamily": "trigger_execution", "benchmarks": ("WebCompass", "Interaction2Code")},
    "trigger_unreachable": {"family": "interaction_repair", "subfamily": "trigger_execution", "benchmarks": ("WebCompass", "Interaction2Code")},
    "wrong_target": {"family": "interaction_repair", "subfamily": "state_transition", "benchmarks": ("Interaction2Code", "FullFront")},
    "wrong_state_transition": {"family": "interaction_repair", "subfamily": "state_transition", "benchmarks": ("Interaction2Code", "FullFront")},
    "state_sync_failure": {"family": "interaction_repair", "subfamily": "state_transition", "benchmarks": ("Vision2Web", "WebGen-Bench")},
    "transient_feedback_failure": {"family": "interaction_repair", "subfamily": "feedback", "benchmarks": ("ArtifactsBench", "WebCompass")},
    "overlay_behavior_failure": {"family": "interaction_repair", "subfamily": "overlay", "benchmarks": ("Interaction2Code", "ArtifactsBench")},
    "input_validation_failure": {"family": "interaction_repair", "subfamily": "forms", "benchmarks": ("ArtifactsBench", "WebGen-Bench")},
    "navigation_history_failure": {"family": "interaction_repair", "subfamily": "navigation", "benchmarks": ("Vision2Web", "WebGen-Bench")},
    "ordering_manipulation_failure": {"family": "interaction_repair", "subfamily": "direct_manipulation", "benchmarks": ("ArtifactsBench", "Interaction2Code")},
    "focus_keyboard_failure": {"family": "interaction_repair", "subfamily": "keyboard_focus", "benchmarks": ("WebCompass", "FullFront")},
    "semantic_structure": {"family": "quality_refinement", "subfamily": "semantic_accessibility", "benchmarks": ("WebCompass", "WebUIBench")},
    "missing_attributes": {"family": "quality_refinement", "subfamily": "semantic_accessibility", "benchmarks": ("WebCompass", "WebUIBench")},
    "accessibility_regression": {"family": "quality_refinement", "subfamily": "semantic_accessibility", "benchmarks": ("WebUIBench", "FullFront")},
    "component_reuse_regression": {"family": "quality_refinement", "subfamily": "reuse_consistency", "benchmarks": ("ComUIBench",)},
    "cross_page_component_consistency": {"family": "quality_refinement", "subfamily": "reuse_consistency", "benchmarks": ("ComUIBench", "Vision2Web")},
    "preservation_regression": {"family": "quality_refinement", "subfamily": "regression_control", "benchmarks": ("WebCompass", "FronTalk")},
    "history_forgetting": {"family": "quality_refinement", "subfamily": "regression_control", "benchmarks": ("FronTalk",)},
    "minimal_patch_violation": {"family": "quality_refinement", "subfamily": "maintainability", "benchmarks": ("FullFront", "WebUIBench")},
    "code_maintainability": {"family": "quality_refinement", "subfamily": "maintainability", "benchmarks": ("FullFront", "ComUIBench")},
    "requirement_alignment_regression": {"family": "quality_refinement", "subfamily": "requirement_alignment", "benchmarks": ("InteractWeb-Bench", "FronTalk")},
}


def repair_defect_metadata(defect_types: list[str]) -> dict[str, list[str]]:
    """Return normalized family/subfamily/benchmark labels for leaf defects."""
    unknown = sorted(set(defect_types) - set(REPAIR_DEFECT_TAXONOMY))
    if unknown:
        raise TaskSpecError(f"unknown repair defect types: {unknown}")
    rows = [REPAIR_DEFECT_TAXONOMY[item] for item in defect_types]
    return {
        "repair_family": sorted({str(row["family"]) for row in rows}),
        "repair_subfamily": sorted({str(row["subfamily"]) for row in rows}),
        "benchmark_alignment": sorted(
            {str(name) for row in rows for name in row["benchmarks"]}
        ),
    }

EDIT_INPUT_VARIANTS = (
    "code_instruction",
    "code_instruction_source_image",
    "code_instruction_target_image",
    "code_instruction_source_target_images",
)

SUPPORTED_ACTIONS = frozenset(
    {
        "click",
        "drag_and_drop",
        "fill",
        "focus",
        "hover",
        "key_press",
        "scroll",
        "select_option",
        "set_viewport",
        "wait_for",
    }
)

SUPPORTED_ASSERTIONS = frozenset(
    {
        "attribute",
        "count",
        "hidden",
        "text",
        "url",
        "value",
        "visible",
    }
)

EVIDENCE_KINDS_BY_REPAIR_FAMILY = {
    "runtime_repair": frozenset(
        {"console_error", "page_error", "request_failure", "build_error"}
    ),
    "visual_repair": frozenset({"screenshot_diff", "layout_assertion"}),
    "interaction_repair": frozenset(
        {"action_trace", "assertion_failure", "state_transition_failure"}
    ),
    "quality_refinement": frozenset(
        {
            "accessibility_audit",
            "performance_audit",
            "responsive_audit",
            "quality_audit",
        }
    ),
}


class TaskSpecError(ValueError):
    """The construction contract is incomplete or internally inconsistent."""


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskSpecError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise TaskSpecError(f"{field} must be {qualifier}")
    result = [_non_empty_string(item, field) for item in value]
    if len(set(result)) != len(result):
        raise TaskSpecError(f"{field} contains duplicates")
    return result


def _page_path(value: Any, field: str) -> str:
    page = _non_empty_string(value, field).replace("\\", "/")
    path = PurePosixPath(page)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in {".html", ".htm"}:
        raise TaskSpecError(f"{field} must be a safe relative HTML path")
    return path.as_posix()


def infer_edit_input_variant(visual_references: dict[str, Any]) -> str:
    """Return the training input shape without inspecting image contents."""
    source = bool(visual_references.get("source_images"))
    target = bool(visual_references.get("target_images"))
    if source and target:
        return "code_instruction_source_target_images"
    if source:
        return "code_instruction_source_image"
    if target:
        return "code_instruction_target_image"
    return "code_instruction"


def interaction_catalog() -> tuple[list[str], dict[str, str]]:
    """Return the interaction-first Edit catalog used by new 0805 supplements."""
    return list(INTERACTION_TYPES), dict(INTERACTION_GUIDELINES)


def benchmark_sources_for(interaction_types: list[str]) -> list[str]:
    sources = {
        source
        for interaction_type in interaction_types
        for source in BENCHMARK_SOURCES_BY_INTERACTION.get(interaction_type, ())
    }
    return sorted(sources)


def _validate_action(action: Any, field: str) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise TaskSpecError(f"{field} must be an object")
    name = _non_empty_string(action.get("action"), f"{field}.action")
    if name not in SUPPORTED_ACTIONS:
        raise TaskSpecError(f"{field}.action is unsupported: {name}")
    result = dict(action)
    selector_actions = {
        "click",
        "drag_and_drop",
        "fill",
        "focus",
        "hover",
        "select_option",
        "wait_for",
    }
    if name in selector_actions:
        if name == "drag_and_drop":
            _non_empty_string(action.get("source_selector"), f"{field}.source_selector")
            _non_empty_string(action.get("target_selector"), f"{field}.target_selector")
        else:
            _non_empty_string(action.get("selector"), f"{field}.selector")
    if name in {"fill", "select_option"} and not isinstance(
        action.get("value"), (str, int, float)
    ):
        raise TaskSpecError(f"{field}.value must be scalar")
    if name == "key_press":
        _non_empty_string(action.get("key"), f"{field}.key")
    if name == "set_viewport":
        width, height = action.get("width"), action.get("height")
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or not 240 <= width <= 4096
            or not 200 <= height <= 4096
        ):
            raise TaskSpecError(f"{field} has an invalid viewport")
    return result


def _validate_assertion(assertion: Any, field: str) -> dict[str, Any]:
    if not isinstance(assertion, dict):
        raise TaskSpecError(f"{field} must be an object")
    kind = _non_empty_string(assertion.get("type"), f"{field}.type")
    if kind not in SUPPORTED_ASSERTIONS:
        raise TaskSpecError(f"{field}.type is unsupported: {kind}")
    if kind != "url":
        _non_empty_string(assertion.get("selector"), f"{field}.selector")
    if kind in {"attribute", "count", "text", "url", "value"} and "expected" not in assertion:
        raise TaskSpecError(f"{field}.expected is required for {kind}")
    if kind == "attribute":
        _non_empty_string(assertion.get("name"), f"{field}.name")
    return dict(assertion)


def _validate_checkpoint(
    checkpoint: Any, index: int, project_pages: set[str]
) -> dict[str, Any]:
    field = f"browser_contract.checkpoints[{index}]"
    if not isinstance(checkpoint, dict):
        raise TaskSpecError(f"{field} must be an object")
    result = dict(checkpoint)
    result["id"] = _non_empty_string(checkpoint.get("id"), f"{field}.id")
    role = _non_empty_string(checkpoint.get("state_role"), f"{field}.state_role")
    if role not in {"source", "target", "transient", "reference"}:
        raise TaskSpecError(f"{field}.state_role is unsupported: {role}")
    result["route"] = _page_path(checkpoint.get("route"), f"{field}.route")
    if result["route"] not in project_pages:
        raise TaskSpecError(f"{field}.route is not listed in project_pages")
    actions = checkpoint.get("actions", [])
    assertions = checkpoint.get("assertions", [])
    if not isinstance(actions, list) or not isinstance(assertions, list):
        raise TaskSpecError(f"{field}.actions and assertions must be lists")
    result["actions"] = [
        _validate_action(action, f"{field}.actions[{action_index}]")
        for action_index, action in enumerate(actions)
    ]
    result["assertions"] = [
        _validate_assertion(assertion, f"{field}.assertions[{assertion_index}]")
        for assertion_index, assertion in enumerate(assertions)
    ]
    if not isinstance(checkpoint.get("capture", False), bool):
        raise TaskSpecError(f"{field}.capture must be boolean")
    result["capture"] = bool(checkpoint.get("capture", False))
    return result


def _validate_difference_contract(
    contract: Any, index: int, checkpoint_ids: set[str]
) -> dict[str, Any]:
    field = f"difference_contracts[{index}]"
    if not isinstance(contract, dict):
        raise TaskSpecError(f"{field} must be an object")
    before = _non_empty_string(contract.get("before_checkpoint"), f"{field}.before_checkpoint")
    after = _non_empty_string(contract.get("after_checkpoint"), f"{field}.after_checkpoint")
    if before not in checkpoint_ids or after not in checkpoint_ids or before == after:
        raise TaskSpecError(f"{field} must reference two distinct checkpoints")
    region = _non_empty_string(contract.get("region_selector"), f"{field}.region_selector")
    pixels = contract.get("minimum_changed_pixels")
    ratio = contract.get("minimum_region_changed_ratio")
    if isinstance(pixels, bool) or not isinstance(pixels, int) or pixels < 1:
        raise TaskSpecError(f"{field}.minimum_changed_pixels must be a positive integer")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
        raise TaskSpecError(f"{field}.minimum_region_changed_ratio must be in (0, 1]")
    return {
        **contract,
        "before_checkpoint": before,
        "after_checkpoint": after,
        "region_selector": region,
        "minimum_changed_pixels": pixels,
        "minimum_region_changed_ratio": float(ratio),
    }


def validate_task_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one hidden Edit/Repair construction contract."""
    if not isinstance(spec, dict):
        raise TaskSpecError("task spec must be an object")
    result = deepcopy(spec)
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise TaskSpecError(f"schema_version must be {SCHEMA_VERSION}")
    task_family = _non_empty_string(spec.get("task_family"), "task_family")
    if task_family not in {"edit", "repair"}:
        raise TaskSpecError("task_family must be edit or repair")
    result["instruction"] = _non_empty_string(spec.get("instruction"), "instruction")

    page_scope = _non_empty_string(spec.get("page_scope"), "page_scope")
    if page_scope not in {"sp", "mp"}:
        raise TaskSpecError("page_scope must be sp or mp")
    project_pages = [
        _page_path(page, "project_pages")
        for page in _string_list(spec.get("project_pages"), "project_pages")
    ]
    if page_scope == "sp" and len(project_pages) != 1:
        raise TaskSpecError("sp tasks must list exactly one project page")
    if page_scope == "mp" and len(project_pages) < 2:
        raise TaskSpecError("mp tasks must list at least two project pages")
    result["project_pages"] = project_pages
    affected_pages = [
        _page_path(page, "affected_pages")
        for page in _string_list(spec.get("affected_pages"), "affected_pages")
    ]
    if not set(affected_pages) <= set(project_pages):
        raise TaskSpecError("affected_pages must be a subset of project_pages")
    result["affected_pages"] = affected_pages

    interaction_types = _string_list(
        spec.get("interaction_types", []), "interaction_types", allow_empty=True
    )
    unknown_interactions = sorted(set(interaction_types) - set(INTERACTION_TYPES))
    if unknown_interactions:
        raise TaskSpecError(f"unknown interaction_types: {unknown_interactions}")
    result["interaction_types"] = interaction_types

    visual_references = spec.get("visual_references", {})
    if not isinstance(visual_references, dict):
        raise TaskSpecError("visual_references must be an object")
    source_images = _string_list(
        visual_references.get("source_images", []),
        "visual_references.source_images",
        allow_empty=True,
    )
    target_images = _string_list(
        visual_references.get("target_images", []),
        "visual_references.target_images",
        allow_empty=True,
    )
    result["visual_references"] = {
        **visual_references,
        "source_images": source_images,
        "target_images": target_images,
    }
    result["input_variant"] = infer_edit_input_variant(result["visual_references"])
    if result["input_variant"] not in EDIT_INPUT_VARIANTS:
        raise TaskSpecError("invalid edit input variant")

    browser_contract = spec.get("browser_contract")
    if not isinstance(browser_contract, dict):
        raise TaskSpecError("browser_contract must be an object")
    checkpoints = browser_contract.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise TaskSpecError("browser_contract.checkpoints must be a non-empty list")
    normalized_checkpoints = [
        _validate_checkpoint(checkpoint, index, set(project_pages))
        for index, checkpoint in enumerate(checkpoints)
    ]
    checkpoint_ids = [item["id"] for item in normalized_checkpoints]
    if len(set(checkpoint_ids)) != len(checkpoint_ids):
        raise TaskSpecError("browser checkpoint ids must be unique")
    result["browser_contract"] = {**browser_contract, "checkpoints": normalized_checkpoints}

    differences = spec.get("difference_contracts", [])
    if not isinstance(differences, list):
        raise TaskSpecError("difference_contracts must be a list")
    result["difference_contracts"] = [
        _validate_difference_contract(contract, index, set(checkpoint_ids))
        for index, contract in enumerate(differences)
    ]
    captured_roles = {
        checkpoint["state_role"] for checkpoint in normalized_checkpoints if checkpoint["capture"]
    }
    if interaction_types:
        if not {"source", "target"} <= captured_roles:
            raise TaskSpecError(
                "interaction tasks require captured source and target checkpoints"
            )
        if (source_images or target_images) and not result["difference_contracts"]:
            raise TaskSpecError(
                "interaction image tasks require a region-level difference contract"
            )

    construction_route = _non_empty_string(
        spec.get("construction_route"), "construction_route"
    )
    if construction_route not in {"forward_edit", "natural_failure", "controlled_mutation"}:
        raise TaskSpecError("unsupported construction_route")
    if task_family == "edit":
        if construction_route != "forward_edit":
            raise TaskSpecError("edit tasks must use the forward_edit construction route")
        if spec.get("repair_family") not in {None, ""}:
            raise TaskSpecError("edit tasks cannot set repair_family")
        result["failure_evidence"] = []
    else:
        repair_family = _non_empty_string(spec.get("repair_family"), "repair_family")
        if repair_family not in REPAIR_FAMILIES:
            raise TaskSpecError(f"unknown repair_family: {repair_family}")
        defect_types = _string_list(spec.get("defect_types"), "defect_types")
        defect_metadata = repair_defect_metadata(defect_types)
        if defect_metadata["repair_family"] != [repair_family]:
            raise TaskSpecError(
                "all defect_types in one repair task must belong to repair_family"
            )
        result["defect_types"] = defect_types
        result["repair_subfamily"] = defect_metadata["repair_subfamily"]
        result["benchmark_alignment"] = defect_metadata["benchmark_alignment"]
        if construction_route == "forward_edit":
            raise TaskSpecError("repair tasks require a failure construction route")
        evidence = spec.get("failure_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise TaskSpecError("repair tasks require failure_evidence")
        allowed_kinds = EVIDENCE_KINDS_BY_REPAIR_FAMILY[repair_family]
        normalized_evidence = []
        for index, item in enumerate(evidence):
            field = f"failure_evidence[{index}]"
            if not isinstance(item, dict):
                raise TaskSpecError(f"{field} must be an object")
            kind = _non_empty_string(item.get("kind"), f"{field}.kind")
            if kind not in allowed_kinds:
                raise TaskSpecError(
                    f"{field}.kind {kind!r} does not prove {repair_family}"
                )
            if item.get("status") != "reproduced":
                raise TaskSpecError(f"{field}.status must be reproduced")
            artifact_refs = _string_list(
                item.get("artifact_refs"), f"{field}.artifact_refs"
            )
            normalized_evidence.append({**item, "kind": kind, "artifact_refs": artifact_refs})
        result["repair_family"] = repair_family
        result["failure_evidence"] = normalized_evidence

    training_view = spec.get("training_view")
    if not isinstance(training_view, dict):
        raise TaskSpecError("training_view must be an object")
    if training_view.get("output") != "patch":
        raise TaskSpecError("training_view.output must be patch")
    hidden = set(
        _string_list(training_view.get("hidden_fields"), "training_view.hidden_fields")
    )
    required_hidden = {"browser_contract", "difference_contracts", "failure_evidence"}
    if not required_hidden <= hidden:
        raise TaskSpecError(
            "training_view.hidden_fields must hide evaluator and failure evidence"
        )
    result["training_view"] = dict(training_view)
    return result


__all__ = [
    "EDIT_INPUT_VARIANTS",
    "BENCHMARK_SOURCES_BY_INTERACTION",
    "EVIDENCE_KINDS_BY_REPAIR_FAMILY",
    "INTERACTION_TYPES",
    "INTERACTION_GUIDELINES",
    "INTERACTION_TASK_TYPE_BY_INTERACTION",
    "REPAIR_DEFECT_TAXONOMY",
    "REPAIR_FAMILIES",
    "SCHEMA_VERSION",
    "TaskSpecError",
    "infer_edit_input_variant",
    "benchmark_sources_for",
    "interaction_catalog",
    "interaction_types_for_tasks",
    "repair_defect_metadata",
    "validate_task_spec",
]
