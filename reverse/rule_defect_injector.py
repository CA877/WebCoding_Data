#!/usr/bin/env python3
"""Deterministic, LLM-free defect injection for repair construction.

Every rule adds one conspicuous and uniquely tagged defect to an existing HTML
file.  The returned labels point in the repair direction (defective -> clean),
and are proven to round-trip exactly on both the model-visible and full source.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .construct_common import validate_patch_round_trip


RULE_DESCRIPTIONS = {
    "Occlusion": "Remove the oversized fixed overlay that obscures the upper page content.",
    "Crowding": "Restore spacing between page elements whose margins, padding, and gaps were collapsed.",
    "Text Overlap": "Restore readable line height and letter spacing so adjacent lines no longer overlap.",
    "Alignment": "Realign the main structural regions that were shifted horizontally out of the layout grid.",
    "Color Contrast": "Restore foreground and background colors so page text is readable again.",
    "Overflow": "Restore normal content widths so the layout no longer overflows far beyond the viewport.",
    "Sizing Proportion": "Restore normal media and section proportions after extreme distortion.",
    "Loss of Interactivity": "Re-enable interactive controls and restore their normal enabled appearance.",
    "Semantic Error": "Remove the visually prominent heading-like element that was injected without heading semantics.",
    "Nesting Error": "Remove the conspicuous control whose anchor and block containers are invalidly nested.",
    "Missing Attributes": "Remove the injected form control that lacks an accessible name and required attributes.",
}

TAXONOMY_RULE_ALIASES = {
    "bootstrap_render_crash": "Bootstrap Render Crash",
    "event_runtime_exception": "Event Runtime Exception",
    "route_resource_failure": "Route Resource Failure",
    "occlusion": "Occlusion",
    "crowding": "Crowding",
    "text_overlap": "Text Overlap",
    "alignment": "Alignment",
    "color_contrast": "Color Contrast",
    "overflow": "Overflow",
    "sizing_proportion": "Sizing Proportion",
    "trigger_unreachable": "Trigger Unreachable",
    "missing_handler": "Trigger Unreachable",
    "wrong_target": "Trigger Unreachable",
    "semantic_structure": "Semantic Error",
    "missing_attributes": "Missing Attributes",
    "accessibility_regression": "Missing Attributes",
}

TAXONOMY_RULE_DESCRIPTIONS = {
    "bootstrap_render_crash": "Restore application bootstrap so the primary page renders.",
    "event_runtime_exception": "Remove the injected runtime exception and restore the rendered application.",
    "route_resource_failure": "Restore route bootstrap resources so the requested view renders.",
    "trigger_unreachable": "Restore pointer activation for the existing primary control.",
    "missing_handler": "Restore the missing activation behavior for the existing primary control.",
    "wrong_target": "Restore the primary control so it activates the intended target.",
    **{name: RULE_DESCRIPTIONS[alias] for name, alias in TAXONOMY_RULE_ALIASES.items()
       if alias in RULE_DESCRIPTIONS},
}


_STYLE_VARIANTS: dict[str, tuple[str, ...]] = {
    "Occlusion": (
        "body::before{content:' ';position:fixed;inset:0 0 42% 0;background:rgba(8,12,20,.94);z-index:2147483647;}",
        "body::after{content:' ';position:fixed;inset:18% 5%;background:rgba(20,20,20,.96);z-index:2147483647;}",
    ),
    "Crowding": (
        "body *{margin:0!important;padding:0!important;gap:0!important;}",
        "main,section,article,header,footer,nav{margin:0!important;padding:0!important;gap:0!important;}",
    ),
    "Alignment": (
        "main,section,header,footer,nav{transform:translateX(18vw)!important;}",
        "main,section,article{position:relative!important;left:22vw!important;}",
    ),
    "Color Contrast": (
        "body,body *{color:#f8f8f8!important;background-color:#fff!important;border-color:#fafafa!important;}",
        "body,body *{color:#111!important;background-color:#080808!important;border-color:#101010!important;}",
    ),
    "Overflow": (
        "html,body{overflow-x:visible!important;}main,section,article{width:165vw!important;max-width:none!important;}",
        "body{width:58vw!important;overflow:visible!important;}main,section{min-width:150vw!important;}",
    ),
}


_HTML_DEFECTS = {
    "Text Overlap": (
        "<div data-rule-defect='text-overlap' style='position:fixed;left:8%;right:8%;top:30%;height:180px;z-index:2147483646;background:#fff;color:#111;font-size:42px;line-height:.28;overflow:visible'>Multiple lines of prominent text are forced onto the same vertical position.<br>Adjacent text overlaps this line and becomes unreadable.<br>A third line occupies the identical visual region.</div>",
        "<div data-rule-defect='text-overlap' style='position:fixed;left:6%;right:6%;top:34%;height:150px;z-index:2147483646;background:#fff;color:#111;font-size:38px'><span style='position:absolute;inset:20px'>First prominent text layer overlaps the region</span><span style='position:absolute;inset:20px'>Second prominent text layer overlaps the region</span></div>",
    ),
    "Sizing Proportion": (
        "<div data-rule-defect='sizing-proportion' style='position:fixed;left:4%;top:8%;width:92%;height:76%;z-index:2147483646;background:#1677ff;border:28px solid #ffec3d;border-radius:2px;color:white;font-size:18px'>A normally compact component is stretched to extreme page proportions</div>",
        "<div data-rule-defect='sizing-proportion' style='position:fixed;left:42%;top:4%;width:220px;height:88%;z-index:2147483646;background:#722ed1;border:28px solid #ffec3d;color:white;font-size:32px;word-break:break-all'>Severely distorted aspect ratio</div>",
    ),
    "Loss of Interactivity": (
        "<div data-rule-defect='loss-of-interactivity' style='position:fixed;left:4%;right:4%;top:36%;z-index:2147483646;padding:42px;background:#bfbfbf;opacity:.94;filter:grayscale(1)'><button disabled style='width:32%;padding:28px;font-size:28px'>Disabled action</button><a style='pointer-events:none;display:inline-block;width:32%;padding:28px;font-size:28px'>Blocked link</a><input disabled style='width:30%;padding:28px;font-size:28px'></div>",
        "<fieldset data-rule-defect='loss-of-interactivity' disabled style='position:fixed;left:6%;right:6%;bottom:30%;z-index:2147483646;padding:48px;background:#d9d9d9;opacity:.9'><button style='width:45%;padding:30px;font-size:30px'>Unavailable control</button><input style='width:45%;padding:30px;font-size:30px'></fieldset>",
    ),
    "Semantic Error": (
        "<div data-rule-defect='semantic-error' style='position:fixed;top:8px;left:8%;right:8%;z-index:2147483646;padding:28px;background:#ffe45c;color:#111;font-size:42px;font-weight:800'>Visually styled as the primary heading but exposed only as a generic container</div>",
        "<span data-rule-defect='semantic-error' style='display:block;position:fixed;top:6%;left:5%;right:5%;z-index:2147483646;padding:24px;background:#ffdb4d;color:#111;font-size:38px;font-weight:800'>Prominent heading-like content without heading semantics</span>",
    ),
    "Nesting Error": (
        "<a data-rule-defect='nesting-error' href='#'><div style='position:fixed;left:5%;right:5%;bottom:8%;z-index:2147483646;padding:34px;background:#ff4d4f;color:white;font-size:30px'>Invalidly nested block control</a></div>",
        "<button data-rule-defect='nesting-error' style='position:fixed;left:8%;right:8%;bottom:6%;z-index:2147483646;padding:30px;background:#d9363e;color:white'><a href='#'><div>Invalid interactive nesting</button></div></a>",
    ),
    "Missing Attributes": (
        "<input data-rule-defect='missing-attributes' style='position:fixed;left:10%;right:10%;top:42%;width:80%;z-index:2147483646;padding:30px;font-size:30px;border:12px solid #fa541c'>",
        "<textarea data-rule-defect='missing-attributes' style='position:fixed;left:12%;right:12%;top:38%;width:76%;height:180px;z-index:2147483646;border:12px solid #fa541c'></textarea>",
    ),
}


def available_rule_types() -> list[str]:
    return [*RULE_DESCRIPTIONS, *TAXONOMY_RULE_ALIASES]


def _variant(instance_id: str, task_type: str, options: tuple[str, ...]) -> str:
    digest = hashlib.sha256(f"{instance_id}:{task_type}".encode()).digest()
    return options[int.from_bytes(digest[:2], "big") % len(options)]


def _html_target(code: list[dict[str, str]]) -> tuple[str, str, str]:
    candidates = sorted(
        (item for item in code if item["path"].lower().endswith((".html", ".htm"))),
        key=lambda item: (item["path"] != "index.html", item["path"]),
    )
    for item in candidates:
        lower = item["code"].lower()
        if lower.count("</head>") == 1:
            pos = lower.index("</head>")
            return item["path"], item["code"][pos:pos + 7], "head"
    for item in candidates:
        lower = item["code"].lower()
        if lower.count("</body>") == 1:
            pos = lower.index("</body>")
            return item["path"], item["code"][pos:pos + 7], "body"
    raise ValueError("rule injection requires one uniquely occurring </head> or </body> marker")


def build_rule_defect_task(
    generation_data: dict[str, Any], defect_types: list[str]
) -> dict[str, Any]:
    """Inject selected rules and return the normal repair synthesizer contract."""
    unknown = [task_type for task_type in defect_types if task_type not in available_rule_types()]
    if unknown:
        raise ValueError(f"unsupported rule defect types: {unknown}")
    if not 1 <= len(defect_types) <= 12 or len(defect_types) != len(set(defect_types)):
        raise ValueError("rule defect types must contain 1--12 distinct values")

    clean_visible = generation_data["dst_code"]
    clean_full = generation_data.get("full_code", clean_visible)
    path, marker, location = _html_target(clean_visible)
    forward: list[dict[str, str]] = []
    instance_id = str(generation_data.get("instance_id", ""))
    for ordinal, task_type in enumerate(defect_types):
        rule_id = hashlib.sha256(
            f"{instance_id}:{task_type}:{ordinal}".encode()
        ).hexdigest()[:12]
        rule_type = TAXONOMY_RULE_ALIASES.get(task_type, task_type)
        if task_type in {"bootstrap_render_crash", "event_runtime_exception", "route_resource_failure"}:
            defect = (
                f"<style data-rule-defect='{rule_id}'>body{{visibility:hidden!important}}</style>"
                f"<script data-rule-defect-script='{rule_id}'>throw new Error('controlled-{task_type}-{rule_id}')</script>"
            )
        elif task_type in {"trigger_unreachable", "missing_handler", "wrong_target"}:
            defect = (
                f"<style data-rule-defect='{rule_id}'>"
                "button:not([disabled]){pointer-events:none!important;filter:grayscale(1)!important;opacity:.35!important}"
                "body::after{content:'Interaction unavailable';position:fixed;left:10%;right:10%;bottom:8%;"
                "padding:32px;background:#b42318;color:white;z-index:2147483647;text-align:center;font-size:28px}"
                "</style>"
            )
        elif rule_type in _STYLE_VARIANTS:
            css = _variant(instance_id, rule_type, _STYLE_VARIANTS[rule_type])
            defect = f"<style data-rule-defect='{rule_id}' data-task-type='{task_type}'>{css}</style>"
        else:
            defect = _variant(instance_id, rule_type, _HTML_DEFECTS[rule_type])
            defect = defect.replace("data-rule-defect='", f"data-rule-id='{rule_id}' data-rule-defect='")
        separator = "\n"
        replacement = f"{defect}{separator}{marker}"
        forward.append({
            "path": path,
            "task_type": task_type,
            "search": marker,
            "replace": replacement,
        })

    defective_visible, defective_full = validate_patch_round_trip(
        clean_visible, clean_full, forward
    )
    labels = [
        {**patch, "search": patch["replace"], "replace": patch["search"]}
        for patch in reversed(forward)
    ]
    return {
        "task": "repair",
        "task_type": list(defect_types),
        "description": [
            {"task_type": task_type, "description": (
                TAXONOMY_RULE_DESCRIPTIONS.get(task_type) or RULE_DESCRIPTIONS[task_type]
            )}
            for task_type in defect_types
        ],
        "resources": generation_data.get("resources", []),
        "label_modified_files": labels,
        "defective_code": defective_visible,
        "defective_full_code": defective_full,
        "llm_raw_response": "",
        "llm_metadata": {
            "model": "deterministic-rule-injector-v1",
            "strategy": "rule_based",
            "rule_count": len(defect_types),
            "insertion_location": location,
        },
        "browser_checks": ([{
            "task_type": task_type,
            "route": (generation_data.get("project_pages") or ["index.html"])[0],
            "actions": [{"action": "click", "selector": "button:not([disabled])"}],
            "assertion": {"type": "visible", "selector": "button:not([disabled])"},
            "capture_delay_ms": 100,
        } for task_type in defect_types] if all(
            task_type in {"trigger_unreachable", "missing_handler", "wrong_target"}
            for task_type in defect_types
        ) else []),
    }
