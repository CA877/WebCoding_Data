#!/usr/bin/env python3
"""Generate new queries from multiple benchmark-style seeds in each domain.

This intentionally performs no quality filtering or similarity screening.  It
stores source IDs so the raw LLM synthesis can be inspected directly.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any

from openai import OpenAI


GENERATION_BENCHMARKS = (
    "WebCompass",
    "DesignBench",
    "Interaction2Code",
    "Vision2Web",
    "ArtifactsBench",
    "Design2Code",
    "Flame-VLM-Code",
    "WebGen-Bench",
    "InteractWeb-Bench",
    "FullFront",
    "FronTalk",
    "ComUIBench",
    "WebUIBench",
    "Web2Code",
)


GENERATION_PROTOCOLS = {
    "WebCompass": {
        "task": "generation",
        "seed_form": "native natural-language generation briefs",
        "query_form": "one complete three-section generation brief",
        "required_input_assets": "none; the natural-language query is the complete input",
        "backend_ceiling": "frontend-first; at most WebCompass-level observable mock behavior",
    },
    "DesignBench": {
        "task": "generation",
        "seed_form": "reference UI screenshots paired with framework targets",
        "query_form": "one screenshot-grounded framework generation instruction",
        "required_input_assets": "one reference screenshot",
        "backend_ceiling": "pure frontend",
    },
    "Interaction2Code": {
        "task": "generation",
        "seed_form": "ordered before/after interaction prototypes plus action metadata",
        "query_form": "one prototype-grounded interactive-page generation instruction",
        "required_input_assets": "ordered before/after prototype images",
        "backend_ceiling": "pure frontend interaction state",
    },
    "Vision2Web": {
        "task": "generation",
        "seed_form": "L1 responsive or L2 multi-page visual prototypes plus a short prompt",
        "query_form": "one prototype-grounded L1 or L2 generation request",
        "required_input_assets": "prototype images",
        "backend_ceiling": "pure frontend with local mock state",
    },
    "ArtifactsBench": {
        "task": "generation",
        "seed_form": "native natural-language artifact requests",
        "query_form": "one direct artifact generation request",
        "required_input_assets": "none; the natural-language query is the complete input",
        "backend_ceiling": "frontend-first; at most WebCompass-level observable mock behavior",
    },
    "Design2Code": {
        "task": "generation",
        "seed_form": "single webpage screenshots",
        "query_form": "one concise screenshot-to-HTML instruction",
        "required_input_assets": "one reference screenshot",
        "backend_ceiling": "pure frontend static HTML and CSS",
    },
    "Flame-VLM-Code": {
        "task": "generation",
        "seed_form": "webpage screenshots paired with React implementations",
        "query_form": "one screenshot-to-React generation instruction",
        "required_input_assets": "one reference screenshot",
        "backend_ceiling": "pure frontend React behavior",
    },
    "WebGen-Bench": {
        "task": "generation",
        "seed_form": "non-technical natural-language website requests",
        "query_form": "one concise non-technical product request",
        "required_input_assets": "none; the natural-language query is the complete input",
        "backend_ceiling": "at most WebCompass-level light backend; no database and no authentication",
    },
    "InteractWeb-Bench": {
        "task": "generation",
        "seed_form": "ambiguous, noisy or conflicting persona-driven website requests",
        "query_form": "one user request retaining realistic imperfections but still implementable",
        "required_input_assets": "none; the natural-language query is the complete input",
        "backend_ceiling": "at most WebCompass-level light backend; no database and no authentication",
    },
    "FullFront": {
        "task": "generation",
        "seed_form": "visual webpage designs used by the webpage-code-generation task",
        "query_form": "one visual-to-code generation instruction",
        "required_input_assets": "one reference screenshot",
        "backend_ceiling": "pure frontend",
    },
    "FronTalk": {
        "task": "generation",
        "seed_form": "multi-turn textual or visual dialogue history with accumulated constraints",
        "query_form": "one single final-state generation query with the full accumulated specification",
        "required_input_assets": "none; all final requirements are merged into the query",
        "backend_ceiling": "frontend-first; at most WebCompass-level observable mock behavior",
    },
    "ComUIBench": {
        "task": "generation",
        "seed_form": "same-site multi-page screenshots with reusable-component annotations",
        "query_form": "one multi-page reusable-UI generation instruction",
        "required_input_assets": "same-site page screenshots and component annotations",
        "backend_ceiling": "pure frontend",
    },
    "WebUIBench": {
        "task": "generation",
        "seed_form": "WebUI-to-Code screenshot examples",
        "query_form": "one WebUI-to-Code generation instruction",
        "required_input_assets": "one webpage screenshot",
        "backend_ceiling": "pure frontend",
    },
    "Web2Code": {
        "task": "generation",
        "seed_form": "webpage screenshots used by the screenshot-to-HTML subset",
        "query_form": "one concise screenshot-to-HTML instruction",
        "required_input_assets": "one webpage screenshot",
        "backend_ceiling": "pure frontend static HTML and CSS",
    },
}


VISUAL_INPUT_BENCHMARKS = frozenset(
    benchmark
    for benchmark, protocol in GENERATION_PROTOCOLS.items()
    if not protocol["required_input_assets"].startswith("none;")
)


# FrontendBench's public paper defines five difficulty levels.  Static level 1
# does not help the user's requested interaction-heavy augmentation, so these
# four generation capabilities are used only as a cross-benchmark reference;
# FrontendBench is not falsely presented as one of the fourteen source pools.
FRONTENDBENCH_INTERACTION_LEVELS = {
    "dynamic_effect": "simple page with dynamic effects",
    "basic_interaction": "simple page with basic interaction",
    "complex_interaction": "simple page with complex interaction",
    "complex_page_complex_interaction": "complex page with complex interaction",
}


INTERACTION_PROFILE_SPECS = {
    "WebCompass": {
        "WC-1 commerce-social-transit": "complex_page_complex_interaction",
        "WC-2 enterprise-systems": "complex_interaction",
        "WC-3 interactive-exploration": "basic_interaction",
        "WC-4 games-simulation": "complex_interaction",
        "WC-5 data-workflows": "complex_page_complex_interaction",
    },
    "Interaction2Code": {
        "I2C-G1 reveal-feedback": "basic_interaction",
        "I2C-G2 form-selection": "complex_interaction",
        "I2C-G3 position-motion": "complex_interaction",
        "I2C-G4 switch-color-media": "basic_interaction",
        "I2C-G5 navigation-new-page": "complex_page_complex_interaction",
    },
    "ArtifactsBench": {
        "AB-1 games": "complex_interaction",
        "AB-2 web-applications": "complex_page_complex_interaction",
        "AB-3 management-data": "complex_interaction",
        "AB-4 visual-simulation": "complex_interaction",
        "AB-5 multimedia-utility-other": "basic_interaction",
    },
}


GENERATION_SCENARIO_CONTEXTS = (
    "community workshop", "coastal field station", "independent studio", "neighborhood exchange",
    "public archive", "transit hub", "botanical laboratory", "small venue program",
    "civic service", "maker collective", "learning cohort", "local newsroom",
    "research observatory", "cultural festival", "repair network", "conservation project",
    "specialty retailer", "accessibility service", "volunteer network", "museum program",
    "shared kitchen", "mobile clinic", "public garden", "equipment library",
    "craft cooperative", "oral-history project", "sports club", "field expedition",
    "language exchange", "energy initiative", "animal shelter", "independent publisher",
)
GENERATION_AUDIENCES = (
    "first-time visitors", "returning members", "small teams", "local residents",
    "students and mentors", "field researchers", "volunteers and coordinators", "creators and clients",
    "commuters", "families", "specialist operators", "community organizers",
    "collectors", "event participants", "service staff", "accessibility-conscious users",
)
GENERATION_INTERACTION_LANES = (
    "direct manipulation with immediate visible feedback",
    "guided input, validation, and recoverable submission",
    "linked views where one selection updates another view",
    "state progression with undo or reset",
    "spatial arrangement with drag, snap, or reorder feedback",
    "discovery, filtering, comparison, and explicit selection",
    "temporal sequencing with play, pause, or scrubbing",
    "cross-page continuity with persistent user-visible state",
)
GENERATION_COMPOSITION_LANES = (
    "editorial hierarchy with asymmetric text and media regions",
    "dense operational layout with clear grouping and scan paths",
    "card-led composition with restrained repetition and strong alignment",
    "long-form page rhythm with alternating section density",
    "prominent hero composition followed by structured supporting content",
    "split-pane information architecture with a persistent contextual region",
    "data-rich visual hierarchy using tables, summaries, and status accents",
    "quiet content-first layout with typography and whitespace as the primary structure",
)
TEXT_DIVERSITY_BENCHMARKS = {
    "WebCompass", "ArtifactsBench", "WebGen-Bench", "InteractWeb-Bench", "FronTalk",
}


VISUAL_TEXT_PROXY_GUIDANCE = {
    "DesignBench": (
        "Turn the framework and UI-density profile into a complete standalone website brief. Name the visible "
        "content hierarchy, layout regions, styling direction, and responsive behavior. The target framework remains "
        "part of the request, but no visual asset is supplied; never require stateful behavior from an HTML/CSS-only profile."
    ),
    "Interaction2Code": (
        "Describe the initial page state, exactly one user trigger, the resulting visible state, and everything that "
        "must remain unchanged. Keep this a from-scratch single-page implementation request, not an edit trajectory."
    ),
    "Vision2Web": (
        "For L1, fully describe one page and its distinct desktop, tablet, and mobile behavior, including reflow, "
        "collapse, visibility, density, navigation, and media treatment. For L2, fully describe the named page set, "
        "page relationships, navigation flow, and shared frontend state. Do not require L3 or real backend behavior."
    ),
    "Design2Code": (
        "Write a self-contained static HTML/CSS website brief that makes layout, text hierarchy, color roles, imagery "
        "regions, spacing rhythm, and long-page structure explicit. This is static reconstruction coverage: do not "
        "request state changes, submission, drag-and-drop, undo, data persistence, or application workflows."
    ),
    "Flame-VLM-Code": (
        "Write a self-contained React page brief with explicit component hierarchy, data-driven repeated regions, "
        "layout, styling, conditional states, and at most one coherent visible interaction. This is generation only."
    ),
    "FullFront": (
        "Describe a complete frontend page spanning FullFront's implementation concerns: composition, hierarchy, "
        "image/text regions, executable interaction when selected by the profile, and polished final-state behavior."
    ),
    "ComUIBench": (
        "Describe a coherent same-site page set with semantic page names. Specify the shared shell, reusable component "
        "families, design tokens, component variants, and cross-page consistency; repeated UI must be implemented once."
    ),
    "WebUIBench": (
        "Convert the selected WebUI-to-Code capability into a complete visible page specification, emphasizing exact "
        "text, element roles, spatial relationships, attributes, visual grouping, and component placement. Do not "
        "turn WebUI-to-Code into a stateful application workflow."
    ),
    "Web2Code": (
        "Write a complete HTML/CSS-oriented page brief covering page structure, layout, text, color system, imagery, "
        "and UI consistency. Vary real webpage archetypes and avoid the benchmark's repetitive image-template wording. "
        "Keep the result static: no submission, state progression, undo, drag-and-drop, or persistent user state."
    ),
}


def diversity_coordinate(source_benchmark: str, domain: str, output_index: int,
                         page_scope: str = "") -> str:
    digest = hashlib.sha256(
        f"{source_benchmark}|{domain}|{output_index}".encode("utf-8")
    ).digest()
    scenario = GENERATION_SCENARIO_CONTEXTS[int.from_bytes(digest[0:2], "big") % len(GENERATION_SCENARIO_CONTEXTS)]
    audience = GENERATION_AUDIENCES[int.from_bytes(digest[2:4], "big") % len(GENERATION_AUDIENCES)]
    lanes = GENERATION_INTERACTION_LANES if page_scope == "multi_page" else tuple(
        lane for lane in GENERATION_INTERACTION_LANES if not lane.startswith("cross-page continuity")
    )
    lane = lanes[int.from_bytes(digest[4:6], "big") % len(lanes)]
    if "-C" in domain:
        return f"context={scenario}; audience={audience}"
    return f"context={scenario}; audience={audience}; interaction={lane}"


def visual_text_proxy_diversity_coordinate(source_benchmark: str, domain: str,
                                           output_index: int) -> str:
    digest = hashlib.sha256(
        f"text-proxy|{source_benchmark}|{domain}|{output_index}".encode("utf-8")
    ).digest()
    scenario = GENERATION_SCENARIO_CONTEXTS[int.from_bytes(digest[0:2], "big") % len(GENERATION_SCENARIO_CONTEXTS)]
    audience = GENERATION_AUDIENCES[int.from_bytes(digest[2:4], "big") % len(GENERATION_AUDIENCES)]
    if "-C" in domain and source_benchmark == "Interaction2Code":
        return f"context={scenario}; audience={audience}"
    lanes = GENERATION_INTERACTION_LANES if source_benchmark == "Interaction2Code" else GENERATION_COMPOSITION_LANES
    lane = lanes[int.from_bytes(digest[4:6], "big") % len(lanes)]
    axis = "interaction" if source_benchmark == "Interaction2Code" else "composition"
    return f"context={scenario}; audience={audience}; {axis}={lane}"


BENCHMARK_GUIDANCE = {
    "WebCompass": (
        "Reproduce the benchmark's product-manager design-document register. The query itself must "
        "contain the three source-native sections '# Web page content', '# web page interaction', "
        "and '# web page visual'. Elaborate concrete layout hierarchy, observable interaction "
        "sequences and feedback, then an explicit visual system with colors, typography, spacing, "
        "and component states. Use detailed Markdown headings and nested bullets like the seeds. "
        "Keep the sections proportionate and aim for 800-950 words; never inflate the document to the hard maximum. "
        "Do not add extra sections or repeat a requirement in more "
        "than one section. "
        "Describe observable behavior rather than prescribing SPA/MPA architecture, storage technology, "
        "CSS timing constants, performance budgets, or implementation libraries unless the selected "
        "references consistently do so. Do not specify pixel measurements, animation durations, named "
        "font families, shadow formulas, upload limits, session timeouts, or backend/authentication "
        "mechanisms. Do not add backend, email, server, or account infrastructure merely to complete a flow."
    ),
    "WebGen-Bench": (
        "Reproduce the benchmark's concise non-expert product-request register in one natural paragraph. "
        "Use this exact four-sentence scaffold: 'Please implement [product and purpose]. The website "
        "should have functionalities for [functional list]. Users should be able to [user action list]. "
        "Use [background color] for the background and [component color] for UI components.' State the "
        "product purpose, broad functionalities, what users can do, and finish with a simple background "
        "and component color direction. Do not name frameworks, libraries, file structures, selectors, "
        "storage mechanisms, APIs, testing procedures, or implementation techniques. Follow the "
        "references' repetitive functional template: 'The website should have functionalities for...' "
        "and 'Users should be able to...'. Do not add UX narrative, journey-quality claims, marketing "
        "justifications, or explanations of why the colors fit the product."
    ),
    "Web-Bench": (
        "Write a dense self-contained final-state implementation contract. Preserve source-native "
        "precision by naming the framework version or web standard, file/component names, routes, DOM "
        "selectors or class names, state transitions, and browser-visible outcomes. Combine all "
        "requirements into the final product from scratch; never mention task numbers, tests, an "
        "existing repository, an earlier version, or an incremental edit."
    ),
    "ArtifactsBench": (
        "Reproduce the benchmark's direct user-to-coder request register. Usually begin with the common "
        "boilerplate 'You are a code expert. Please use your professional knowledge to generate accurate "
        "and professional responses. Make sure the generated code is executable for demonstration.' "
        "Then ask directly for one artifact. Match the selected seeds' variable concision and the same "
        "behavioral abstraction; do not translate a user-visible mechanic into an implementation system "
        "or turn every request into a polished product requirements document. No rendering technique, "
        "algorithm name, numeric physics threshold, file structure, or visual effect may be prescribed "
        "unless that kind of detail appears repeatedly in the selected references. Do not add algorithmic "
        "correctness guarantees, solvability guarantees, or prescriptive art direction to make the task "
        "sound more rigorous."
    ),
    "Vision2Web": (
        "Write the concise textual counterpart of a prototype task whose prototype images are supplied "
        "separately. Start naturally with "
        "'I want to build ...'. In one compact paragraph, name the website, its global navigation, the "
        "main responsibility of each pictured page or viewport, and the user-visible interaction. Assume "
        "prototype images are supplied separately and carry the detailed appearance. Do not prescribe frameworks, "
        "route syntax, localStorage, mock data, external API restrictions, or implementation details. "
        "Use neutral observational language. Do not end with a value proposition, user-benefit summary, "
        "marketing claim, or explanation of how the flow creates engagement."
    ),
    "DesignBench": (
        "Follow the benchmark's image-conditioned Generation task. Ask for a fresh implementation in the "
        "named target framework (Vanilla HTML/CSS, React, Vue, or Angular) that visually reproduces the "
        "supplied screenshot. Keep the request concise. The screenshot, not invented prose, defines exact "
        "content, colors, typography, spacing and layout. Mention responsive behavior and visible interactions "
        "only when supported by seed metadata. Do not add product features, routes, data systems or backend work."
    ),
    "Interaction2Code": (
        "Follow the benchmark's interaction-to-code protocol. Treat the ordered before/after prototype images "
        "as successive UI states and ask for one new frontend implementation that matches the initial state and "
        "reproduces the pictured transition after the indicated user action. State the trigger, state change and "
        "visible result, but do not invent interactions absent from the action metadata. Do not request backend work."
    ),
    "Design2Code": (
        "Use a terse screenshot-to-HTML request. Ask for one self-contained HTML page with CSS that closely "
        "reproduces the supplied screenshot. Let the image carry layout and styling details; do not hallucinate "
        "unseen content, add unrelated behavior, require frameworks, or describe evaluation criteria."
    ),
    "Flame-VLM-Code": (
        "Use a concise screenshot-to-React generation request. Ask for a fresh React page that reproduces the "
        "supplied screenshot's component hierarchy, layout and visible styling, with only the user-visible "
        "interactions supported by the seed. Exclude iterative updates, prior code, repair language and backend work."
    ),
    "InteractWeb-Bench": (
        "Preserve the benchmark's non-expert persona and realistic imperfections: mild rambling, ambiguity, "
        "irrelevant context or one resolvable tension. Emit one imperfect but actionable user request, not a "
        "dialogue. Do not output assistant clarification, verification steps or a response to the user. The final "
        "request must still contain enough evidence to build a coherent website. Keep all functionality frontend-only "
        "or limited to bundled mock data; never add accounts, authentication, databases, payments or server workflows."
    ),
    "FullFront": (
        "Use only FullFront's Webpage Code Generation track. Ask for a new frontend page that translates the "
        "supplied screenshot into executable webpage code while preserving visual hierarchy, element placement, "
        "text and image regions. Do not turn the request into perception QA, design selection, code refinement, "
        "testing or backend implementation."
    ),
    "FronTalk": (
        "Learn the benchmark's long-horizon accumulation of textual and visual requirements, but merge all "
        "accumulated constraints into one final-state generation query. Do not emit turns, change requests, "
        "references to an existing implementation or assistant replies. Preserve concrete final content, layout, "
        "style and interaction decisions, including later decisions that supersede earlier ones."
    ),
    "ComUIBench": (
        "Follow the benchmark's multi-page screenshot-to-code setting. Ask for one coherent multi-page frontend "
        "whose supplied same-site screenshots share reusable components and a consistent design system. Name the "
        "page responsibilities and explicitly require shared headers, navigation, repeated content patterns and "
        "design tokens to be implemented once and reused. Do not add backend services or unseen product features."
    ),
    "WebUIBench": (
        "Use only the WebUI-to-Code generation task. Ask for a fresh webpage implementation from the supplied "
        "screenshot, reproducing visible layout, text, colors and component placement. Do not output a multiple-choice "
        "question, perception question, HTML-understanding question, code completion, bug fix or repair request."
    ),
    "Web2Code": (
        "Use the benchmark's screenshot-to-HTML subset. Ask concisely for one new HTML/CSS page that matches the "
        "supplied webpage screenshot. Do not include screenshot QA, DOM questions, external backend requirements, "
        "or visual details not evidenced by the image."
    ),
}


NATIVE_STYLE_SPECS = {
    "ArtifactsBench": {
        "format": "direct code-expert request",
        "word_ranges": {
            "atomic": (45, 140), "compact": (50, 180), "comprehensive": (100, 300), "": (50, 220),
        },
    },
    "WebCompass": {
        "format": "three-section product-manager design document",
        "target_words": 850,
        "word_ranges": {
            "atomic": (650, 1300), "compact": (650, 1300),
            "comprehensive": (650, 1300), "": (650, 1300),
        },
    },
    "WebGen-Bench": {
        "format": "natural nontechnical one-paragraph product instruction",
        "word_ranges": {
            "atomic": (55, 95), "compact": (60, 105), "comprehensive": (65, 110), "": (60, 105),
        },
    },
    "Web-Bench": {
        "format": "dense final-state technical implementation contract",
        "word_ranges": {
            "atomic": (260, 420), "compact": (300, 480), "comprehensive": (380, 650), "": (320, 550),
        },
    },
    "Vision2Web": {
        "format": "prototype-grounded page-flow narrative",
        "level_word_ranges": {"L1": (15, 45), "L2": (55, 130)},
        "word_ranges": {
            "atomic": (65, 100), "compact": (70, 105), "comprehensive": (75, 115), "": (70, 110),
        },
    },
    "DesignBench": {
        "format": "concise screenshot-grounded framework generation instruction",
        "word_ranges": {"atomic": (35, 75), "compact": (40, 85), "comprehensive": (50, 100), "": (40, 90)},
    },
    "Interaction2Code": {
        "format": "prototype-sequence interaction generation instruction",
        "word_ranges": {"atomic": (55, 105), "compact": (65, 120), "comprehensive": (80, 150), "": (65, 125)},
    },
    "Design2Code": {
        "format": "terse screenshot-to-HTML request",
        "word_ranges": {"atomic": (25, 60), "compact": (30, 70), "comprehensive": (40, 85), "": (30, 70)},
    },
    "Flame-VLM-Code": {
        "format": "concise screenshot-to-React request",
        "word_ranges": {"atomic": (35, 75), "compact": (45, 90), "comprehensive": (55, 110), "": (45, 95)},
    },
    "InteractWeb-Bench": {
        "format": "persona-driven imperfect natural-language request",
        "word_ranges": {"atomic": (90, 155), "compact": (110, 190), "comprehensive": (140, 240), "": (110, 200)},
    },
    "FullFront": {
        "format": "visual webpage-code-generation instruction",
        "word_ranges": {"atomic": (35, 70), "compact": (40, 85), "comprehensive": (50, 100), "": (40, 85)},
    },
    "FronTalk": {
        "format": "single long-form final-state generation brief",
        "word_ranges": {"atomic": (130, 210), "compact": (160, 260), "comprehensive": (190, 330), "": (160, 280)},
    },
    "ComUIBench": {
        "format": "multi-page screenshot-grounded reusable-UI brief",
        "word_ranges": {"atomic": (70, 120), "compact": (85, 145), "comprehensive": (100, 180), "": (85, 155)},
    },
    "WebUIBench": {
        "format": "concise WebUI-to-Code instruction",
        "word_ranges": {"atomic": (25, 55), "compact": (30, 65), "comprehensive": (40, 80), "": (30, 70)},
    },
    "Web2Code": {
        "format": "minimal screenshot-to-HTML instruction",
        "word_ranges": {"atomic": (20, 50), "compact": (25, 60), "comprehensive": (35, 70), "": (25, 60)},
    },
}


def native_style_spec(source_benchmark: str, capability_granularity: str = "",
                      target_level: str = "") -> dict[str, Any]:
    try:
        raw = NATIVE_STYLE_SPECS[source_benchmark]
    except KeyError as exc:
        raise ValueError(f"no native style profile for {source_benchmark}") from exc
    ranges = raw["word_ranges"]
    level_ranges = raw.get("level_word_ranges", {})
    minimum, maximum = level_ranges.get(
        target_level,
        ranges.get(capability_granularity, ranges[""]),
    )
    return {
        "format": raw["format"], "min_words": minimum, "max_words": maximum,
        "target_words": int(raw.get("target_words", round((minimum + maximum) / 2))),
    }


def visual_text_proxy_style_spec(source_benchmark: str, capability_granularity: str = "",
                                 target_level: str = "") -> dict[str, Any]:
    """Length contract for self-contained text PRDs derived from visual benchmark taxonomies."""
    if source_benchmark == "Vision2Web" and target_level == "L1":
        minimum, maximum = 260, 420
    elif source_benchmark == "Vision2Web" and target_level == "L2":
        minimum, maximum = 320, 500
    elif source_benchmark == "ComUIBench":
        minimum, maximum = 350, 550
    elif source_benchmark == "Interaction2Code":
        minimum, maximum = 180, 300
    else:
        minimum, maximum = {
            "atomic": (180, 280),
            "compact": (220, 340),
            "comprehensive": (280, 420),
            "": (220, 360),
        }.get(capability_granularity, (220, 360))
    return {
        "format": "self-contained pure-text website PRD",
        "min_words": minimum,
        "max_words": maximum,
        "target_words": round((minimum + maximum) / 2),
    }


def count_english_words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*\b", text))


def one_shot_word_window(native_style: dict[str, Any]) -> tuple[int, int]:
    """Return a narrow central window that is easier to obey in a single response."""
    target = int(native_style["target_words"])
    lower = max(int(native_style["min_words"]), round(target * 0.88))
    upper = min(int(native_style["max_words"]), round(target * 1.12))
    return lower, upper


def one_shot_completion_budget(native_style: dict[str, Any]) -> int:
    """Leave enough token headroom to close the JSON object without using truncation as a validator."""
    _, upper = one_shot_word_window(native_style)
    return max(500, min(4000, round(upper * 2.2) + 500))


def canonicalize_webcompass_headings(query: str) -> str:
    """Normalize only the three benchmark-native heading lines and preserve the body."""
    canonical = {
        "web page content": "# Web page content",
        "web page interaction": "# web page interaction",
        "web page visual": "# web page visual",
    }
    lines = []
    for line in query.splitlines():
        match = re.fullmatch(r"\s*#\s+(web page (?:content|interaction|visual))\s*", line, re.I)
        lines.append(canonical[match.group(1).casefold()] if match else line)
    return "\n".join(lines)


def validate_native_word_count(source_benchmark: str, capability_granularity: str,
                               query: str, target_level: str = "") -> int:
    spec = native_style_spec(source_benchmark, capability_granularity, target_level)
    count = count_english_words(query)
    if not spec["min_words"] <= count <= spec["max_words"]:
        raise ValueError(
            f"{source_benchmark} {capability_granularity or 'default'} query has {count} words; "
            f"expected {spec['min_words']}-{spec['max_words']}"
        )
    return count


def validate_query_contract(source_benchmark: str, query: str) -> None:
    """Reject structural drift that can be checked without semantic grading."""
    maintenance_patterns = (
        r"\bfix\s+(?:the|this|an?)\s+existing\b",
        r"\brepair\s+(?:the|this|an?)\s+existing\b",
        r"\bmodify\s+(?:the|this|an?)\s+existing\b",
        r"\banswer\s+the\s+(?:question|following)\b",
        r"\bwhich\s+option\b",
    )
    if any(re.search(pattern, query, re.I) for pattern in maintenance_patterns):
        raise ValueError("query drifted outside a from-scratch Generation task")
    if source_benchmark == "WebCompass":
        headings = ("# Web page content", "# web page interaction", "# web page visual")
        if any(query.count(heading) != 1 for heading in headings):
            raise ValueError("WebCompass query must contain each native heading exactly once")
        precision = re.search(
            r"(?:\b\d+(?:\.\d+)?\s*(?:px|ms|fps|seconds?|minutes?)\b|\b\d+(?:\.\d+)?%)",
            query,
            re.I,
        )
        if precision:
            raise ValueError(f"WebCompass query contains forbidden numeric implementation precision: {precision.group(0)}")
        forbidden = first_positive_backend_term(query)
        if forbidden:
            raise ValueError(f"WebCompass query exceeds the allowed implementation/backend abstraction: {forbidden}")
        named_font = re.search(
            r"\b(?:Inter|DM Sans|JetBrains Mono|Public Sans|Source Sans Pro|Roboto|Arial|Helvetica)\b",
            query,
            re.I,
        )
        if named_font:
            raise ValueError(f"WebCompass query prescribes a named font family: {named_font.group(0)}")
    if source_benchmark in {"WebGen-Bench", "InteractWeb-Bench"}:
        forbidden = first_positive_backend_term(query)
        if forbidden:
            raise ValueError(f"{source_benchmark} query exceeds the WebCompass backend ceiling: {forbidden}")
    if source_benchmark == "FronTalk" and re.search(
        r"\b(?:following dialogue requirements|earlier (?:turns|requirements)|later requirements override)\b",
        query,
        re.I,
    ):
        raise ValueError("FronTalk query exposes dialogue history instead of one merged final-state request")
    if source_benchmark == "FronTalk" and re.search(
        r"\b(?:registered users?|authorized administrators?|authentication|logins?|databases?|server workflows?|payment processing)\b",
        query,
        re.I,
    ):
        raise ValueError("FronTalk query exceeds the WebCompass backend ceiling")


REQUIRED_ASSET_REFERENCE_PATTERN = re.compile(
    r"\b(?:screenshots?|prototypes?|images?|pictured|visual references?|provided assets?|supplied assets?)\b",
    re.I,
)


def query_references_required_assets(query: str) -> bool:
    return bool(REQUIRED_ASSET_REFERENCE_PATTERN.search(query))


BACKEND_TERM_PATTERN = re.compile(
    r"\b(?:localStorage|SQLite|database|authentication|backend|API endpoint|server workflow|payment processing|login|log in|sign in)\b",
    re.I,
)
BACKEND_NEGATION_PREFIX = re.compile(
    r"\b(?:without|no|not|avoid(?: any)?|exclude|excluding|"
    r"do not include|does not include|do not need|does not need|"
    r"cannot connect to|can't connect to|not connected to)\b[^.!?;]{0,80}$",
    re.I,
)


def first_positive_backend_term(query: str) -> str:
    """Return a required backend term while allowing explicit frontend-only exclusions."""
    for match in BACKEND_TERM_PATTERN.finditer(query):
        prefix = query[max(0, match.start() - 100):match.start()]
        if BACKEND_NEGATION_PREFIX.search(prefix):
            continue
        return match.group(0)
    return ""


def validate_generated_query(source_benchmark: str, capability_granularity: str,
                             query: str, target_level: str = "") -> int:
    """Return the word count, reporting every deterministic violation in one retry."""
    errors: list[str] = []
    try:
        validate_query_contract(source_benchmark, query)
    except ValueError as exc:
        errors.append(str(exc))
    protocol = GENERATION_PROTOCOLS.get(source_benchmark)
    if (
        protocol
        and not protocol["required_input_assets"].startswith("none;")
        and not query_references_required_assets(query)
    ):
        errors.append(
            f"{source_benchmark} query does not explicitly reference its supplied visual input assets"
        )
    try:
        count = validate_native_word_count(
            source_benchmark, capability_granularity, query, target_level,
        )
    except ValueError as exc:
        count = count_english_words(query)
        errors.append(str(exc))
    if errors:
        raise ValueError("; ".join(errors))
    return count


def retry_correction_guidance(error: str, source_benchmark: str) -> str:
    """Translate deterministic rejection evidence into a concrete LLM revision request."""
    guidance = [
        "Do not copy the rejected query verbatim. Rewrite it and change every rejected detail.",
    ]
    match = re.search(r"has (\d+) words; expected (\d+)-(\d+)", error)
    if match:
        observed, minimum, maximum = (int(value) for value in match.groups())
        if observed > maximum:
            removal = observed - maximum + 150
            guidance.append(
                f"Remove at least {removal} words by deleting repetition and secondary features; "
                f"finish below {maximum} words."
            )
        elif observed < minimum:
            guidance.append(
                f"Add at least {minimum - observed + 30} useful words without inventing a second product system."
            )
    if source_benchmark == "WebCompass":
        guidance.append(
            "Aim near 850 words across only the three required sections. Remove all account, session, "
            "authentication, backend, server and numeric implementation details, even when phrased as exclusions."
        )
    return " ".join(guidance)


def build_retry_prompt(original_prompt: str, rejected_candidate: str,
                       error: str, source_benchmark: str) -> str:
    guidance = retry_correction_guidance(error, source_benchmark)
    if re.search(r"has \d+ words; expected \d+-\d+", error):
        return f"""Revise the rejected benchmark query below. Its deterministic rejection was: {error}
{guidance}
Preserve the same product, benchmark-native voice, page architecture, two cross-page flows when present,
and primary interaction. Remove secondary features and repeated explanations rather than adding anything.
Return one valid JSON object with the same five fields: query, short_name, artifact_archetype,
page_architecture, and cross_page_flows. Return JSON only.
<rejected_candidate>
{rejected_candidate}
</rejected_candidate>"""
    return (
        original_prompt
        + "\n\nThe preceding attempt was rejected by the deterministic contract for this exact reason: "
        + error
        + ". Produce a fresh candidate that corrects that violation while preserving the benchmark-native "
        + "task and all other constraints. "
        + guidance
        + f"\n<rejected_candidate>\n{rejected_candidate}\n</rejected_candidate>"
    )


def build_rejected_attempt(attempt: int, raw_model_content: str,
                           error: Exception) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "raw_model_content": raw_model_content,
        "error": f"{type(error).__name__}: {error}",
    }


PILOT_PROFILE_SPECS = {
    "WebCompass": {
        "WC-1 commerce-social-transit": (
            "comprehensive", "multi_page",
            "a four-page commerce marketplace, social communication, or public-transit journey using client-side mock state only; "
            "no login, authentication, backend, API, server confirmation, payment processing, or admin system",
        ),
        "WC-2 enterprise-systems": ("atomic", "natural", "one advanced enterprise productivity component or workflow on one browser page without additional views"),
        "WC-3 interactive-exploration": ("compact", "natural", "one single-page visual exploration, learning, media, or creative experience driven by one coherent direct-manipulation loop; no accounts, backend, extra pages, or unrelated workflow"),
        "WC-4 games-simulation": ("atomic", "natural", "one stateful game or simulation mechanic on one browser page without additional views"),
        "WC-5 data-workflows": ("comprehensive", "multi_page", "a data workflow spanning input, analysis, detail, and reporting"),
    },
    "WebGen-Bench": {
        "WG-1 commerce-marketplace": ("comprehensive", "multi_page", "a complete catalog-to-explicit-detail-route-to-cart commerce journey; every referenced detail page must appear in the route architecture"),
        "WG-2 internal-enterprise": ("comprehensive", "multi_page", "an enterprise workflow spanning dashboard, records, and settings"),
        "WG-3 analytics-productivity": ("atomic", "natural", "one data-presentation or productivity capability"),
        "WG-4 content-community": ("compact", "natural", "content presentation combined with one within-page community interaction on one page"),
        "WG-5 learning-games-media": ("atomic", "natural", "one learning, media, or browser-game interaction on one page without cross-page state"),
    },
    "Web-Bench": {
        "WB-1 routed-fullstack": (
            "comprehensive", "multi_page",
            "a lightweight final-state Express product with exactly five routes and one lightweight API "
            "over bundled in-memory mock data for one bounded resource; no database, no login, no "
            "authentication, no account or user identity, no roles, no admin console, no payments, no "
            "inventory, and no unrelated backend subsystems",
        ),
        "WB-2 framework-routing": ("comprehensive", "multi_page", "a final framework-based product with real routes and shared state"),
        "WB-3 document-navigation": ("compact", "natural", "hierarchical document navigation plus one active table-of-contents behavior; exclude global search, theme switching, and unrelated URL-state systems"),
        "WB-4 visual-interactive": ("atomic", "natural", "one explicit Canvas, SVG, Three.js, or visual interaction capability"),
        "WB-5 core-dom-layout": ("atomic", "natural", "one native DOM drag-and-drop capability; CSS layout may support it but must not become a second primary challenge"),
    },
    "ArtifactsBench": {
        "AB-1 games": ("atomic", "natural", "one distinctive interactive game mechanic on one browser page without additional views or cross-page state"),
        "AB-2 web-applications": ("comprehensive", "multi_page", "a coherent multi-page web application"),
        "AB-3 management-data": ("compact", "natural", "a focused management or data workflow"),
        "AB-4 visual-simulation": ("atomic", "natural", "one SVG, Canvas, or simulation capability"),
        "AB-5 multimedia-utility-other": ("atomic", "natural", "one multimedia, utility, or diagram interaction"),
    },
    "Vision2Web": {
        "V2W-1 L1 responsive-content": ("compact", "single_page_responsive", "one static page represented by desktop, tablet and mobile prototypes", "L1"),
        "V2W-2 L1 responsive-dashboard": ("comprehensive", "single_page_responsive", "one dense responsive dashboard represented at three viewport sizes", "L1"),
        "V2W-3 L2 content-navigation": ("compact", "multi_page", "a content or knowledge journey across separately pictured pages", "L2"),
        "V2W-4 L2 transaction": ("comprehensive", "multi_page", "a complete transaction or service journey across separately pictured pages", "L2"),
        "V2W-5 L2 saas-public-service": ("atomic", "multi_page", "one focused SaaS or public-service cross-page flow", "L2"),
    },
    "DesignBench": {
        "DB-G1 vanilla-generation": ("atomic", "natural", "one screenshot-grounded Vanilla HTML and CSS page"),
        "DB-G2 react-generation": ("compact", "natural", "one screenshot-grounded React page with component hierarchy"),
        "DB-G3 vue-generation": ("compact", "natural", "one screenshot-grounded Vue page with visible interaction"),
        "DB-G4 angular-generation": ("compact", "natural", "one screenshot-grounded Angular page with visible interaction"),
        "DB-G5 dense-framework-ui": ("comprehensive", "natural", "one visually dense framework-based page without backend work"),
    },
    "Interaction2Code": {
        "I2C-G1 reveal-feedback": ("atomic", "natural", "one source-labeled reveal or visible feedback transition"),
        "I2C-G2 form-selection": ("compact", "natural", "one source-labeled form-control or selection transition"),
        "I2C-G3 position-motion": ("atomic", "natural", "one source-labeled positional transition shown by prototype states"),
        "I2C-G4 switch-color-media": ("compact", "natural", "one source-labeled switch, color, or media transition"),
        "I2C-G5 navigation-new-page": ("comprehensive", "natural", "one multi-step navigation or new-page interaction sequence"),
    },
    "Design2Code": {
        "D2C-G1 editorial": ("atomic", "natural", "one editorial or article screenshot reconstructed as HTML and CSS"),
        "D2C-G2 commerce": ("compact", "natural", "one commerce page screenshot reconstructed as HTML and CSS"),
        "D2C-G3 dashboard": ("comprehensive", "natural", "one dense dashboard screenshot reconstructed as HTML and CSS"),
        "D2C-G4 marketing": ("compact", "natural", "one marketing or portfolio screenshot reconstructed as HTML and CSS"),
        "D2C-G5 long-page": ("comprehensive", "natural", "one visually complex long webpage screenshot reconstructed as HTML and CSS"),
    },
    "Flame-VLM-Code": {
        "FL-G1 dashboard": ("comprehensive", "natural", "one screenshot-grounded React dashboard"),
        "FL-G2 form-workflow": ("compact", "natural", "one screenshot-grounded React form or workflow"),
        "FL-G3 commerce-cards": ("compact", "natural", "one screenshot-grounded React commerce or card interface"),
        "FL-G4 data-visualization": ("atomic", "natural", "one screenshot-grounded React data visualization interface"),
        "FL-G5 interactive-component": ("atomic", "natural", "one screenshot-grounded React component with one visible interaction"),
    },
    "InteractWeb-Bench": {
        "IWB-G1 minimal-persona": ("atomic", "natural", "a terse non-expert persona request with one underspecified visual choice"),
        "IWB-G2 rambling-context": ("compact", "natural", "a rambling request containing irrelevant personal context but a recoverable product goal"),
        "IWB-G3 ambiguous-intent": ("compact", "natural", "a mildly ambiguous request with enough contextual clues for one coherent interpretation"),
        "IWB-G4 conflicting-priorities": ("compact", "natural", "a request with one resolvable tension between visual or interaction priorities"),
        "IWB-G5 noisy-multipage": ("comprehensive", "multi_page", "a noisy but implementable multi-page request using frontend mock data only"),
    },
    "FullFront": {
        "FF-G1 layout-heavy": ("compact", "natural", "one layout-heavy screenshot-to-code page"),
        "FF-G2 text-image-composition": ("atomic", "natural", "one screenshot with important text and image region composition"),
        "FF-G3 long-page": ("comprehensive", "natural", "one long webpage screenshot translated into frontend code"),
        "FF-G4 dashboard": ("comprehensive", "natural", "one dense dashboard screenshot translated into frontend code"),
        "FF-G5 interactive-page": ("compact", "natural", "one screenshot-grounded frontend page with one visible interaction"),
    },
    "FronTalk": {
        "FT-G1 marketing-final-state": ("compact", "natural", "the final accumulated state of a one-page marketing-site dialogue; do not add additional pages"),
        "FT-G2 commerce-final-state": ("comprehensive", "multi_page", "the final accumulated state of a frontend-only commerce-site dialogue"),
        "FT-G3 dashboard-final-state": ("comprehensive", "natural", "the final accumulated state of a one-page dashboard dialogue; do not add additional pages"),
        "FT-G4 editorial-final-state": ("compact", "natural", "the final accumulated state of a one-page editorial or media-site dialogue centered on long-form reading, article navigation, and related content with one lightweight within-page interaction; do not add dashboards, maps, drag-and-drop scheduling, or additional pages"),
        "FT-G5 long-horizon-final-state": ("comprehensive", "multi_page", "a long-horizon dialogue collapsed into one coherent multi-page final specification"),
    },
    "ComUIBench": {
        "CUI-G1 shared-navigation": ("compact", "multi_page", "same-site pages sharing one header, navigation and footer implementation"),
        "CUI-G2 repeated-cards": ("compact", "multi_page", "same-site pages reusing annotated card and list components"),
        "CUI-G3 shared-forms": ("comprehensive", "multi_page", "same-site workflow pages reusing form controls and state presentation"),
        "CUI-G4 design-system": ("comprehensive", "multi_page", "same-site pages governed by reusable tokens and layout primitives"),
        "CUI-G5 complex-site": ("comprehensive", "multi_page", "a complex multi-page site maximizing semantic component reuse"),
    },
    "WebUIBench": {
        "WUI-G1 content-page": ("atomic", "natural", "one WebUI-to-Code content page"),
        "WUI-G2 form-page": ("compact", "natural", "one WebUI-to-Code form interface"),
        "WUI-G3 commerce-page": ("compact", "natural", "one WebUI-to-Code commerce interface"),
        "WUI-G4 dashboard-page": ("comprehensive", "natural", "one dense WebUI-to-Code dashboard"),
        "WUI-G5 long-page": ("comprehensive", "natural", "one complex full-page WebUI-to-Code sample"),
    },
    "Web2Code": {
        "W2C-G1 article": ("atomic", "natural", "one article-like screenshot-to-HTML page"),
        "W2C-G2 product": ("compact", "natural", "one product-page screenshot-to-HTML sample"),
        "W2C-G3 landing": ("compact", "natural", "one landing-page screenshot-to-HTML sample"),
        "W2C-G4 dashboard": ("comprehensive", "natural", "one dashboard screenshot-to-HTML sample"),
        "W2C-G5 complex-page": ("comprehensive", "natural", "one structurally complex screenshot-to-HTML sample"),
    },
}


PILOT_PREFERRED_SEED_IDS = {
    ("WebCompass", "WC-3 interactive-exploration"): [
        "WebCompass:text-generation:953",
        "WebCompass:text-generation:907",
        "WebCompass:text-generation:832",
        "WebCompass:text-generation:868",
    ],
    ("ArtifactsBench", "AB-2 web-applications"): [
        "ArtifactsBench:benchmark:484",
        "ArtifactsBench:benchmark:522",
        "ArtifactsBench:benchmark:533",
        "ArtifactsBench:benchmark:583",
    ],
}


def load_external_profile_specs(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    specs: dict[tuple[str, str], dict[str, str]] = {}
    for benchmark in raw.get("benchmarks", []):
        benchmark_name = str(benchmark.get("benchmark", "")).strip()
        for profile in benchmark.get("profiles", []):
            name = str(profile.get("name", "")).strip()
            if not benchmark_name or not name:
                continue
            specs[(benchmark_name, name)] = {
                "capability_granularity": str(profile.get("capability_granularity", "")).strip(),
                "page_scope": str(profile.get("page_scope", "")).strip(),
                "primary_capability": str(profile.get("primary_capability", "")).strip(),
                "target_level": str(profile.get("target_level", "")).strip(),
                "interaction_level": str(profile.get("interaction_level", "")).strip(),
            }
    return specs


def pilot_profile_spec(source_benchmark: str, domain: str,
                       external_specs: dict[tuple[str, str], dict[str, str]] | None = None) -> dict[str, str]:
    if external_specs and (source_benchmark, domain) in external_specs:
        return external_specs[(source_benchmark, domain)]
    try:
        raw = PILOT_PROFILE_SPECS[source_benchmark][domain]
    except KeyError as exc:
        raise ValueError(f"no pilot profile for {source_benchmark} / {domain}") from exc
    granularity, page_scope, primary = raw[:3]
    target_level = raw[3] if len(raw) > 3 else ""
    return {
        "capability_granularity": granularity,
        "page_scope": page_scope,
        "primary_capability": primary,
        "target_level": target_level,
        "interaction_level": INTERACTION_PROFILE_SPECS.get(source_benchmark, {}).get(domain, ""),
    }


def selected_domains(groups: dict[str, list[dict[str, Any]]], requested: list[str] | None) -> list[str]:
    available = sorted(groups)
    if not requested:
        return available
    missing = sorted(set(requested) - set(groups))
    if missing:
        raise ValueError(f"requested classes are absent from input: {missing}")
    return [domain for domain in available if domain in set(requested)]


def select_pilot_seeds(pool: list[dict[str, Any]], source_benchmark: str, domain: str,
                       count: int, rng: random.Random) -> list[dict[str, Any]]:
    preferred = PILOT_PREFERRED_SEED_IDS.get((source_benchmark, domain))
    if preferred:
        by_id = {str(row.get("instance_id", "")): row for row in pool}
        selected = [by_id[item] for item in preferred if item in by_id]
        if len(selected) >= count:
            return selected[:count]
    return rng.sample(pool, count)


def seed_count_for_benchmark(source_benchmark: str, requested: int, pool_size: int,
                             *, text_proxy_for_visual: bool = False) -> int:
    if source_benchmark in VISUAL_INPUT_BENCHMARKS and not text_proxy_for_visual:
        return 1
    return min(requested, pool_size)


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict) or not str(value.get("query", "")).strip():
        raise ValueError("model response has no non-empty query")
    return value


def validate_multipage_payload(value: dict[str, Any], *, min_pages: int = 3,
                               max_pages: int = 6) -> list[str]:
    pages = value.get("page_architecture")
    if not isinstance(pages, list):
        raise ValueError("multi-page response has no page_architecture array")
    cleaned = [str(item).strip() for item in pages if str(item).strip()]
    if not min_pages <= len(cleaned) <= max_pages:
        raise ValueError(
            f"multi-page response must declare {min_pages}-{max_pages} pages/routes"
        )
    if len({item.casefold() for item in cleaned}) != len(cleaned):
        raise ValueError("multi-page response contains duplicate page declarations")
    flows = value.get("cross_page_flows")
    if not isinstance(flows, list):
        raise ValueError("multi-page response has no cross_page_flows array")
    cleaned_flows = [str(item).strip() for item in flows if str(item).strip()]
    if len(cleaned_flows) != 2:
        raise ValueError("multi-page response must declare exactly two cross-page flows")
    if len({item.casefold() for item in cleaned_flows}) != len(cleaned_flows):
        raise ValueError("multi-page response contains duplicate cross-page flows")
    return cleaned


def normalize_page_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def canonicalize_source_page_architecture(generated_pages: list[str],
                                          required_labels: list[str]) -> list[str]:
    """Replace model-written descriptions with the authoritative visual page labels."""
    labels = [str(label).strip() for label in required_labels if str(label).strip()]
    if len(generated_pages) != len(labels):
        raise ValueError(
            f"asset-bound response declares {len(generated_pages)} pages; expected exactly {len(labels)}"
        )
    architecture_text = normalize_page_label(" ".join(generated_pages))
    missing = [label for label in labels if normalize_page_label(label) not in architecture_text]
    if missing:
        raise ValueError("page_architecture omits supplied page labels: " + ", ".join(missing))
    return labels


def validate_source_page_binding(query: str, pages: list[str],
                                 required_labels: list[str]) -> None:
    """Keep asset-bound multipage queries aligned to their exact pictured page set."""
    labels = [str(label).strip() for label in required_labels if str(label).strip()]
    if not labels:
        return
    if len(pages) != len(labels):
        raise ValueError(
            f"asset-bound response declares {len(pages)} pages; expected exactly {len(labels)}"
        )
    query_text = normalize_page_label(query)
    missing_query = [label for label in labels if normalize_page_label(label) not in query_text]
    if missing_query:
        raise ValueError(
            "asset-bound query omits supplied page labels: " + ", ".join(missing_query)
        )
    normalized_pages = [normalize_page_label(page) for page in pages]
    normalized_labels = [normalize_page_label(label) for label in labels]
    if sorted(normalized_pages) != sorted(normalized_labels):
        raise ValueError(
            "asset-bound page_architecture entries must exactly match the supplied page labels"
        )


def validate_single_page_payload(value: dict[str, Any]) -> list[str]:
    pages = value.get("page_architecture")
    if not isinstance(pages, list):
        raise ValueError("single-page response has no page_architecture array")
    cleaned = [str(item).strip() for item in pages if str(item).strip()]
    if len(cleaned) != 1:
        raise ValueError("single-page response must declare exactly one responsive page")
    return cleaned


def make_job_key(source_benchmark: str, target_level: str, domain: str,
                 output_index: int) -> str:
    return "|".join((source_benchmark.strip(), target_level.strip(), domain.strip(), str(output_index)))


def attempted_job_keys(path: Path) -> set[str]:
    """Return every job already sent once, regardless of its terminal status."""
    if not path.is_file():
        return set()
    attempted: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        attempted.add(str(row.get("job_id") or make_job_key(
            str(row.get("source_benchmark", "")),
            str(row.get("target_level", "")),
            str(row.get("class", "")),
            int(row.get("output_index", 0)),
        )))
    return attempted


def seed_excerpt(instruction: str, limit: int) -> str:
    instruction = instruction.strip()
    if len(instruction) <= limit:
        return instruction
    marker = "\n[seed middle omitted]\n"
    half = max(1, (limit - len(marker)) // 2)
    return instruction[:half] + marker + instruction[-half:]


def multipage_architecture_guidance(source_benchmark: str) -> str:
    if source_benchmark == "WebCompass":
        return """
The content section MUST describe a genuine multi-page website:
- Require 3-6 named pages or routes with distinct user purposes and substantive page-specific content.
- Define a shared site shell, active navigation states, and at least two cross-page user flows with observable feedback.
- State exactly two concise cross-page flows in the query itself,
  using the benchmark-native writing style rather than a separate test or acceptance section.
- Describe any naturally persistent product state only through user-visible behavior and never dictate its storage implementation.
"""
    if source_benchmark == "WebGen-Bench":
        return """
The product must genuinely involve 3-6 connected pages. Mention those pages and the main user journey
in ordinary non-expert prose, but do not enumerate route paths or turn the instruction into a route matrix.
"""
    if source_benchmark == "Web-Bench":
        return """
The final technical contract must define 3-6 real navigable routes, their exact paths and responsibilities,
the shared application shell/state, and browser-visible outcomes for at least two cross-route actions.
"""
    if source_benchmark == "ArtifactsBench":
        return """
Ask for a genuine multi-page artifact with 3-5 named pages and one coherent connected user flow. Keep the
request in ArtifactsBench's direct user voice rather than adding a formal route matrix or grading checklist.
"""
    if source_benchmark == "Vision2Web":
        return """
Describe every distinct page represented by the separate prototype images, the global navigation among them,
and the main click-through flow in natural prose. Do not use route syntax or implementation terminology.
"""
    if source_benchmark == "InteractWeb-Bench":
        return """
Despite the deliberately imperfect user voice, the product must contain 3-5 connected pages with distinct
purposes and two recoverable cross-page journeys. Express them inside one natural request, not as a route table.
Keep all data local or mocked and do not add authentication, databases, payments or server workflows.
"""
    if source_benchmark == "FronTalk":
        return """
Collapse the accumulated dialogue state into one final specification for 3-5 connected pages. Preserve the
resolved page responsibilities, shared visual language and two cross-page flows, without mentioning earlier turns.
Name the complete page set inside the query; do not mention a navigation item, profile, detail view, or download
destination whose page is omitted from that set. Before returning, scan the query for every detail page, profile
page, checkout page, dashboard, workspace, resource page, and other destination. Either include each one in the
3-5 named pages or remove that destination. A component, overlay, tab, or panel must not be called a separate page.
"""
    if source_benchmark == "ComUIBench":
        return """
Describe every separately pictured page from one site. Require the shared shell, annotated repeated blocks and
design tokens to be implemented as reusable components across pages. Include two user-visible cross-page flows.
"""
    raise ValueError(f"no multi-page guidance for {source_benchmark}")


def build_prompt(domain: str, seeds: list[dict[str, Any]], max_seed_chars: int,
                 *, source_benchmark: str = "WebCompass", target_level: str = "",
                 multipage: bool = False, single_page_responsive: bool = False,
                 single_page: bool = False,
                 capability_granularity: str = "", primary_capability: str = "",
                 interaction_level: str = "", diversity_hint: str = "",
                 text_proxy_for_visual: bool = False) -> str:
    if sum((multipage, single_page_responsive, single_page)) > 1:
        raise ValueError("page-scope prompt modes are mutually exclusive")
    if text_proxy_for_visual and source_benchmark not in VISUAL_INPUT_BENCHMARKS:
        raise ValueError("text proxy mode is only valid for visual-input benchmarks")
    visual_mode = source_benchmark in VISUAL_INPUT_BENCHMARKS and not text_proxy_for_visual
    if visual_mode and len(seeds) != 1:
        raise ValueError(f"{source_benchmark} visual query rewriting requires exactly one asset-bound seed")
    source_page_labels = list(dict.fromkeys(
        str(label).strip()
        for seed in seeds
        for label in (seed.get("prototype_page_labels") or [])
        if str(label).strip()
    ))
    blocks = []
    for number, seed in enumerate(seeds, 1):
        display_id = f"asset-bound-seed-{number}" if visual_mode else seed["instance_id"]
        seed_body = seed_excerpt(seed['instruction'], max_seed_chars)
        if text_proxy_for_visual:
            metadata = {
                "capability_profile": domain,
                "source_category": seed.get("source_category", ""),
                "framework": seed.get("framework", ""),
                "action": seed.get("action", ""),
                "description": seed.get("description", ""),
                "tag_types": seed.get("tag_types", []),
                "visual_types": seed.get("visual_types", []),
                "target_level": seed.get("target_level", target_level),
                "page_count": len(seed.get("prototype_page_labels") or []),
            }
            seed_body = json.dumps(metadata, ensure_ascii=False)
        blocks.append(
            f"<seed number=\"{number}\" id=\"{display_id}\">\n"
            f"{seed_body}\n</seed>"
        )
    visual_multipage_guidance = """
The source sample is bound to a supplied multi-page visual asset set:
- Preserve the exact page set, page relationships, and flows stated in the source instruction or depicted by the assets.
- Do not invent page names, routes, features, or flows that the source instruction does not state.
- Repeat every exact page label stated in the source instruction in the query.
- Use the complete supplied page set, including a two-page or seven-page set when that is what the source names.
- Do not rename the pages or make up responsibilities for generically labeled pages such as Page 1 or Page 2.
- State exactly two generic cross-page continuity descriptions grounded in the source instruction in the query.
"""
    if source_page_labels:
        visual_multipage_guidance += (
            "\nThe authoritative supplied page labels are exactly: "
            + "; ".join(source_page_labels)
            + ". Use all of them verbatim and no others.\n"
        )
    architecture = (
        visual_multipage_guidance if (multipage and visual_mode)
        else multipage_architecture_guidance(source_benchmark) if multipage else ("""
The new request MUST describe exactly one responsive page/view:
- Specify how the same page adapts across desktop, tablet, and mobile breakpoints.
- Preserve content hierarchy and recognizable visual identity while allowing layout reflow.
- Do not introduce additional routes, backend services, authentication, or cross-page flows.
- Describe at least two meaningful within-page responsive changes beyond simple uniform scaling.
""" if single_page_responsive else ("""
The new request MUST describe exactly one webpage or browser view:
- Do not add separate pages, routes, page-to-page navigation, or cross-page persistence.
- Within-page panels, overlays, tabs, filters, and interaction states are allowed.
- Describe exactly one page and do not expose component-file planning metadata.
""" if single_page else ""))
    )
    if text_proxy_for_visual and multipage:
        architecture = """
The new request MUST fully describe a genuine multi-page website in text:
- Name 3-5 semantic pages with distinct responsibilities and substantive page-specific content.
- Define the shared shell, active navigation, reusable visual language, and two coherent cross-page flows.
- Describe any shared state only through browser-visible behavior using bundled mock data or local UI state.
- Do not rely on an unseen image or introduce real authentication, databases, payments, or server workflows.
"""
    profile_guidance = BENCHMARK_GUIDANCE.get(
        source_benchmark,
        "Preserve the source queries' request style, implementation scope, and level of specificity.",
    )
    if visual_mode:
        profile_guidance = (
            "Paraphrase only the single source instruction in the benchmark's native query form. Preserve every "
            "explicit framework, output constraint, user action, visible transition, page relationship, and name "
            "that binds it to the supplied assets. If the source instruction is short or generic, the rewrite must "
            "remain equally generic: do not infer navigation, responsive reflow, components, content, colors, "
            "layout, or interaction from assets you cannot see. Refer explicitly to the supplied screenshot or "
            "prototype images and let those assets carry all unstated visual facts."
        )
    elif text_proxy_for_visual:
        profile_guidance = (
            VISUAL_TEXT_PROXY_GUIDANCE[source_benchmark]
            + " The final request must be a self-contained pure-text website brief and must not mention or depend "
            "on screenshots, images as input, prototypes, captions, visual references, supplied assets, or a benchmark. "
            "Do not add a negative disclaimer about those inputs; simply describe the website itself."
        )
    try:
        protocol = GENERATION_PROTOCOLS[source_benchmark]
    except KeyError as exc:
        if source_benchmark != "Web-Bench":
            raise ValueError(f"no generation protocol for {source_benchmark}") from exc
        protocol = {
            "task": "generation",
            "seed_form": "legacy final-state project requirements",
            "query_form": "one final-state generation request",
            "required_input_assets": "none; the natural-language query is the complete input",
            "backend_ceiling": "legacy profile",
        }
    if text_proxy_for_visual:
        protocol = {
            **protocol,
            "seed_form": "official paper taxonomy and representative official seed metadata",
            "query_form": "one independent self-contained pure-text website brief",
            "required_input_assets": "none; the natural-language query is the complete input",
        }
    level_text = f" Target capability level: {target_level}." if target_level else ""
    level_guidance = ""
    if source_benchmark == "Vision2Web" and target_level == "L1" and text_proxy_for_visual:
        level_guidance = (
            "\nVision2Web L1 text-proxy contract: fully describe the same single page at desktop, tablet, "
            "and mobile sizes. State concrete viewport-specific reflow, collapse, visibility, density, navigation, "
            "and media behavior so no prototype image is needed to understand the requirement."
        )
    elif source_benchmark == "Vision2Web" and target_level == "L2" and text_proxy_for_visual:
        level_guidance = (
            "\nVision2Web L2 text-proxy contract: fully describe a 3-5 page frontend, its page graph, navigation, "
            "cross-page workflows, and shared visible state using frontend mock data only."
        )
    elif source_benchmark == "Vision2Web" and target_level == "L1":
        level_guidance = (
            "\nVision2Web L1 contract: the same single static page is supplied as desktop, tablet and mobile "
            "prototype images. Describe one page only and preserve its content hierarchy across the three viewports."
        )
    elif source_benchmark == "Vision2Web" and target_level == "L2":
        level_guidance = (
            "\nVision2Web L2 contract: this is a Level 2 multi-page prototype task. "
            "The exact 4-7 pictured pages are named in the source instruction. "
            "Describe their navigation and cross-page interaction, not responsive variants of one page."
        )
    asset_guidance = ""
    if not protocol["required_input_assets"].startswith("none;") and not text_proxy_for_visual:
        asset_guidance = (
            f"\nInput assets supplied separately: {protocol['required_input_assets']}. "
            "The query must explicitly refer to those assets, must not pretend their visual details are contained "
            "in the query, and must not invent visual facts that are absent from the seed metadata."
        )
    capability_text = ""
    if visual_mode:
        capability_text = (
            "\nThe profile name is an allocation label only. Preserve the exact task, product identity, visible "
            "facts, action, framework, and page relationships in the single source sample. Do not inject the "
            "profile label as a new visual fact when the supplied assets do not establish it."
        )
    elif capability_granularity:
        if capability_granularity == "atomic":
            capability_text += (
                "\nCapability granularity: atomic. Require exactly one dominant implementation "
                "challenge and at most two lightweight supporting behaviors. Do not add an independent "
                "second system such as procedural generation, authentication, admin tooling, audio "
                "synthesis, import/export, or analytics unless that system is the named primary capability."
            )
        elif capability_granularity == "compact":
            capability_text += (
                "\nCapability granularity: compact. Combine 2-4 closely coupled capabilities that form "
                "one coherent workflow; avoid unrelated feature accumulation."
            )
        elif capability_granularity == "comprehensive":
            capability_text += (
                "\nCapability granularity: comprehensive. Describe a complete but implementable product "
                "scope whose features support the same user journey."
            )
        else:
            raise ValueError(f"unsupported capability granularity: {capability_granularity}")
    if primary_capability and not visual_mode:
        capability_text += f"\nPrimary capability target: {primary_capability}."
    interaction_text = ""
    if interaction_level and not visual_mode:
        try:
            interaction_description = FRONTENDBENCH_INTERACTION_LEVELS[interaction_level]
        except KeyError as exc:
            raise ValueError(f"unsupported interaction level: {interaction_level}") from exc
        interaction_text = f"""
Interaction capability reference: {interaction_description}.
- State every important user-visible trigger, the resulting state change, and the visible feedback.
- For complex interaction, include a recoverable boundary, reset, undo, validation, or empty/error state when natural.
- Keep the behavior executable in the browser and within the benchmark's backend ceiling.
- Do not include test steps, assertions, grading language, checklists, or evaluator-only DOM selectors.
"""
    diversity_text = ""
    if diversity_hint:
        diversity_text = f"""
Deterministic diversity coordinate for this new sample: {diversity_hint}.
Adapt this coordinate naturally to the named benchmark domain. Do not copy these literal labels, and do not let the
coordinate override the benchmark's format, capability granularity, page scope, backend ceiling, or source evidence.
"""
    native_style = (
        visual_text_proxy_style_spec(source_benchmark, capability_granularity, target_level)
        if text_proxy_for_visual else
        native_style_spec(source_benchmark, capability_granularity, target_level)
    )
    one_shot_min_words, one_shot_max_words = one_shot_word_window(native_style)
    backend_one_shot_guidance = ""
    if source_benchmark in {
        "WebCompass", "ArtifactsBench", "WebGen-Bench", "InteractWeb-Bench", "FronTalk",
    }:
        backend_one_shot_guidance = """
One-pass frontend boundary:
- Keep every requested behavior browser-visible and implementable from bundled example data or ephemeral UI state.
- The final query must not request or name login, sign-in, authentication, accounts, databases, backend services,
  server workflows, API endpoints, payment processing, or a storage technology.
- Do not add a disclaimer listing excluded backend features; simply omit those features from the final query.
"""
    creation_instruction = (
        "Rewrite the single source instruction into ONE new wording for the same exact visual sample and supplied "
        "assets. Preserve its task semantics and asset binding; this is a query paraphrase, not a new scenario."
        if visual_mode else
        "Create ONE new query by learning their query style and level of detail. You must invent a new product scenario."
    )
    scenario_requirement = (
        "- Do not invent a new product, visible component, interaction, route, content fact, or design property. "
        "Only restate facts present in the source instruction; unseen details remain in the supplied assets."
        if visual_mode else
        "- The result must describe a genuinely new website or browser application, not summarize or combine the seed products."
    )
    domain_requirement = (
        "- Do not force the allocation label or primary capability into the rewritten query; the source sample and assets are authoritative."
        if visual_mode else
        f"- The new scenario must unmistakably fit the named domain `{domain}` and the primary capability target; a merely adjacent product is invalid."
    )
    copying_requirement = (
        "- Preserve source-grounded names, labels, actions, and page relationships when they are needed to bind the query to the same assets; vary only the wording."
        if visual_mode else
        "- Do not copy brand names, distinctive phrases, exact data, or rare entity combinations from a seed."
    )
    source_heading = (
        f"The example below is one asset-bound source instruction from {source_benchmark}.{level_text}"
        if visual_mode else
        f"The examples below are source queries from {source_benchmark}, in the domain: {domain}.{level_text}"
    )
    if text_proxy_for_visual:
        source_heading = (
            f"The notes below are official task metadata from {source_benchmark}, in the capability profile: "
            f"{domain}.{level_text} They are taxonomy evidence only, not a visual input to the new task."
        )
    return f"""You synthesize realistic benchmark-specific web generation requests.

{source_heading}
{creation_instruction}

Generation protocol:
- Task: Generation only; create a new implementation from scratch.
- Seed form: {protocol['seed_form']}.
- Query form: {protocol['query_form']}.
- Backend ceiling: {protocol['backend_ceiling']}.
- Do not turn this into an edit, repair, video-generation, testing, grading or ground-truth task.
{asset_guidance}
{level_guidance}

Source-specific style:
{profile_guidance}
{capability_text}
{interaction_text}
{diversity_text}

Native distribution contract:
- Target about {native_style['target_words']} English words and stop comfortably before the maximum.
- Required range: {native_style['min_words']}-{native_style['max_words']} English words.
- One-pass length window: {one_shot_min_words}-{one_shot_max_words} English words. Draft directly inside this narrower window.
- Native format: {native_style['format']}.
- Match the examples' sentence rhythm, amount of explicit detail, implementation abstraction, and formatting.
- A reader should plausibly believe the new query came from the same collection pipeline as the examples.
{backend_one_shot_guidance}

Requirements:
{scenario_requirement}
{domain_requirement}
- Keep the feature set coherent; do not output a grading rubric or checklist.
- Do not mention any benchmark, seeds, reference examples, or evaluation.
- Do not discuss the query, prompt, input modality, construction process, final deliverable, or what references are absent.
{copying_requirement}
- Do not output code.
- There is no second attempt and no post-generation content validation. Satisfy every constraint in this first response.
- Silently check the completed query before returning it. Never add numeric styling or animation precision, or backend infrastructure, when the benchmark forbids it.
- For WebCompass specifically, the final query must not contain any numeric value followed by px, ms, fps, seconds, minutes, or %, and must not name a font family. Use qualitative language such as brief, subtle, generous, compact, light, or dark instead.
{architecture}

Return only the query text. Do not return JSON, metadata, a preface, or a code fence.

Examples:
{chr(10).join(blocks)}
"""


def one_shot_system_contract(source_benchmark: str, *, multipage: bool,
                             text_proxy_for_visual: bool) -> str:
    rules = [
        "Generate one new web-development user query.",
        "Obey every constraint in the first response because there is no validation or retry.",
        "Return only the user-facing website request, with no preface, commentary, construction metadata, or code fence.",
        "Never call the response a prompt, brief, specification, final deliverable, pure-text task, benchmark proxy, or implementation approach.",
        "The named primary capability is mandatory and dominant; do not replace it or add a second unrelated interaction system.",
        "End with a concrete requirement about visible content, layout, styling, or behavior; never end by describing the output, deliverable, prototype, evaluation, or implementation exercise.",
    ]
    if source_benchmark == "WebCompass":
        rules.append(
            "Use exactly these three top-level headings, each once and in this order: "
            "# Web page content; # web page interaction; # web page visual. "
            "Never turn them into numbered subsections or different capitalization."
        )
    if source_benchmark == "WebGen-Bench":
        rules.append(
            "Return exactly four sentences. Sentence one must start with Please implement. Sentence two must start "
            "with The website should have functionalities for. Sentence three must start with Users should be able to. "
            "Sentence four must start with Use and naturally name one background color and one UI-component color. "
            "Never write the words scaffold or structure as template labels, and add no fifth sentence."
        )
    if multipage:
        rules.append(
            "Every requested page must be named. Each of the two cross-page flows must explicitly begin on one "
            "named page and navigate to a different named page; an overlay or panel within one page is not cross-page."
        )
    if text_proxy_for_visual:
        rules.append(
            "Describe the website directly as a standalone product request. Do not mention absent images, screenshots, "
            "prototypes, captions, supplied assets, later screenshot creation, or the fact that the input is text."
        )
    if source_benchmark == "Vision2Web":
        rules.append(
            "Stay within L1 or L2 frontend scope. Do not create account, login, billing, payment-method, admin, database, "
            "server, or external-API pages even as mock examples."
        )
    if source_benchmark in {"Design2Code", "Web2Code", "WebUIBench"}:
        rules.append(
            "Keep the page static. Do not request realtime data, submission, persistence, authentication, or application workflows."
        )
    return " ".join(rules)


def make_success_record_contract(
    *,
    source_benchmark: str,
    target_level: str,
    domain: str,
    output_index: int,
    query: str,
    page_scope: str,
    capability_granularity: str,
    primary_capability: str,
    interaction_level: str,
    source_instance_ids: list[str],
    source_categories: list[str],
    source_asset_refs: list[str],
    model: str,
    source_page_labels: list[str] | None = None,
    source_annotation_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Return the query fields needed for later merging with the 0805 release."""
    benchmark_slug = re.sub(r"[^a-z0-9]+", "-", source_benchmark.casefold()).strip("-")
    profile_code = re.sub(r"[^a-z0-9]+", "-", domain.split(" ", 1)[0].casefold()).strip("-")
    instance_id = f"gen14-{benchmark_slug}-{profile_code}-{output_index + 1:05d}"
    protocol = GENERATION_PROTOCOLS[source_benchmark]
    source_page_labels = list(source_page_labels or [])
    source_annotation_refs = list(source_annotation_refs or [])
    return {
        "instance_id": instance_id,
        "instruction": query,
        "query": query,
        "task": "text-generation",
        "task_type": [],
        "page_type": "mp" if page_scope == "multi_page" else "sp",
        "language": "en",
        "source_benchmark": source_benchmark,
        "source_profile": domain,
        "target_level": target_level,
        "page_scope": page_scope,
        "capability_granularity": capability_granularity,
        "primary_capability": primary_capability,
        "interaction_level": interaction_level,
        "source_instance_ids": source_instance_ids,
        "source_categories": source_categories,
        "source_asset_refs": source_asset_refs,
        "source_page_labels": source_page_labels,
        "source_annotation_refs": source_annotation_refs,
        "metadata": {
            "release_schema_reference": "webcoding-sft-v2-query-only",
            "source": "fourteen_benchmark_generation_query_expansion_single_call_20260820",
            "source_benchmark": source_benchmark,
            "source_profile": domain,
            "query_expansion_model": model,
            "generation_only": True,
            "text_only_generation": protocol["required_input_assets"].startswith("none;"),
            "required_input_assets": protocol["required_input_assets"],
            "backend_ceiling": protocol["backend_ceiling"],
            "source_instance_ids": source_instance_ids,
            "source_categories": source_categories,
            "source_asset_refs": source_asset_refs,
            "source_page_labels": source_page_labels,
            "source_annotation_refs": source_annotation_refs,
            "frontendbench_interaction_reference": interaction_level,
        },
    }


def generate_one(client: OpenAI, model: str, domain: str, seeds: list[dict[str, Any]],
                 max_seed_chars: int, *, source_benchmark: str = "WebCompass",
                 target_level: str = "", multipage: bool = False,
                 single_page_responsive: bool = False, output_index: int = 0,
                 capability_granularity: str = "", primary_capability: str = "",
                 interaction_level: str = "", stream: bool = False,
                 text_proxy_for_visual: bool = False) -> dict[str, Any]:
    diversity_hint = (
        visual_text_proxy_diversity_coordinate(source_benchmark, domain, output_index)
        if text_proxy_for_visual else
        diversity_coordinate(
            source_benchmark,
            domain,
            output_index,
            "multi_page" if multipage else "single_page",
        )
        if source_benchmark in TEXT_DIVERSITY_BENCHMARKS or text_proxy_for_visual else ""
    )
    strict_single_page = not multipage and not (
        source_benchmark == "Interaction2Code" and domain == "I2C-G5 navigation-new-page"
    )
    prompt = build_prompt(
        domain,
        seeds,
        max_seed_chars,
        source_benchmark=source_benchmark,
        target_level=target_level,
        multipage=multipage,
        single_page_responsive=single_page_responsive,
        single_page=(strict_single_page and not single_page_responsive),
        capability_granularity=capability_granularity,
        primary_capability=primary_capability,
        interaction_level=interaction_level,
        diversity_hint=diversity_hint,
        text_proxy_for_visual=text_proxy_for_visual,
    )
    job_id = make_job_key(source_benchmark, target_level, domain, output_index)
    native_style = (
        visual_text_proxy_style_spec(source_benchmark, capability_granularity, target_level)
        if text_proxy_for_visual else
        native_style_spec(source_benchmark, capability_granularity, target_level)
    )
    one_shot_min_words, one_shot_max_words = one_shot_word_window(native_style)
    completion_budget = one_shot_completion_budget(native_style)
    raw_model_content = ""
    request_started = time.perf_counter()
    time_to_first_token_seconds: float | None = None
    request_seconds: float | None = None
    try:
        system_contract = one_shot_system_contract(
            source_benchmark,
            multipage=multipage,
            text_proxy_for_visual=text_proxy_for_visual,
        )
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_contract
                        + " The query must contain between "
                        + f"{one_shot_min_words} and {one_shot_max_words} English words."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": completion_budget,
            "extra_body": {"enable_thinking": False},
        }
        if stream:
            request_kwargs["stream"] = True
            request_kwargs["stream_options"] = {"include_usage": True}
        response = client.chat.completions.create(**request_kwargs)
        usage = None
        if stream:
            content_parts: list[str] = []
            for chunk in response:
                usage = getattr(chunk, "usage", None) or usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                content = getattr(getattr(choices[0], "delta", None), "content", None)
                if content:
                    if time_to_first_token_seconds is None:
                        time_to_first_token_seconds = time.perf_counter() - request_started
                    content_parts.append(content)
            raw_model_content = "".join(content_parts)
        else:
            raw_model_content = response.choices[0].message.content or ""
            usage = response.usage
        request_seconds = time.perf_counter() - request_started
        query = raw_model_content.strip()
        if not query:
            raise ValueError("the single model response is empty")
        source_page_labels = list(dict.fromkeys(
            str(label).strip()
            for seed in seeds
            for label in (seed.get("prototype_page_labels") or [])
            if str(label).strip()
        ))
        pages = source_page_labels if (multipage and not text_proxy_for_visual) else []
        cross_page_flows: list[str] = []
        page_scope = (
            "multi_page" if multipage else
            "single_page_responsive" if single_page_responsive else
            "single_page"
        )
        source_instance_ids = [str(seed["instance_id"]) for seed in seeds]
        source_categories = sorted({
            str(seed.get("source_category", "")).strip()
            for seed in seeds if str(seed.get("source_category", "")).strip()
        })
        source_asset_refs = list(dict.fromkeys(
            str(reference).strip()
            for seed in seeds
            for reference in (seed.get("source_asset_refs") or [])
            if str(reference).strip()
        ))
        source_annotation_refs = list(dict.fromkeys(
            str(reference).strip()
            for seed in seeds
            for reference in (seed.get("source_annotation_refs") or [])
            if str(reference).strip()
        ))
        contract_asset_refs = [] if text_proxy_for_visual else source_asset_refs
        contract_page_labels = [] if text_proxy_for_visual else source_page_labels
        contract_annotation_refs = [] if text_proxy_for_visual else source_annotation_refs
        contract = make_success_record_contract(
            source_benchmark=source_benchmark,
            target_level=target_level,
            domain=domain,
            output_index=output_index,
            query=query,
            page_scope=page_scope,
            capability_granularity=capability_granularity,
            primary_capability=primary_capability,
            interaction_level=interaction_level,
            source_instance_ids=source_instance_ids,
            source_categories=source_categories,
            source_asset_refs=contract_asset_refs,
            model=model,
            source_page_labels=contract_page_labels,
            source_annotation_refs=contract_annotation_refs,
        )
        if text_proxy_for_visual:
            contract["metadata"].update({
                "construction_route": "benchmark_taxonomy_text_proxy",
                "text_only_generation": True,
                "required_input_assets": "none; the natural-language query is the complete input",
                "visual_input_deferred_to_playwright_stage": True,
            })
            contract["construction_route"] = "benchmark_taxonomy_text_proxy"
        return {
            "status": "ok",
            "job_id": job_id,
            "class": domain,
            "query_word_count": count_english_words(query),
            "native_style_format": native_style["format"],
            "short_name": "",
            "artifact_archetype": "",
            "page_architecture": pages,
            "cross_page_flows": cross_page_flows,
            "diversity_coordinate": diversity_hint,
            **contract,
            "model": model,
            "attempt": 1,
            "llm_call_count": 1,
            "streaming": stream,
            "time_to_first_token_seconds": time_to_first_token_seconds,
            "request_seconds": request_seconds,
            "output_index": output_index,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            } if usage is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        request_seconds = time.perf_counter() - request_started
        failure = f"{type(exc).__name__}: {exc}"
        print(
            f"{source_benchmark} {target_level} {domain} #{output_index}: "
            f"single call failed: {failure}",
            flush=True,
        )
    return {
        "status": "error",
        "job_id": job_id,
        "source_benchmark": source_benchmark,
        "target_level": target_level,
        "class": domain,
        "source_instance_ids": [str(seed["instance_id"]) for seed in seeds],
        "source_asset_refs": list(dict.fromkeys(
            str(reference).strip()
            for seed in seeds
            for reference in (seed.get("source_asset_refs") or [])
            if str(reference).strip()
        )),
        "source_page_labels": list(dict.fromkeys(
            str(label).strip()
            for seed in seeds
            for label in (seed.get("prototype_page_labels") or [])
            if str(label).strip()
        )),
        "source_annotation_refs": list(dict.fromkeys(
            str(reference).strip()
            for seed in seeds
            for reference in (seed.get("source_annotation_refs") or [])
            if str(reference).strip()
        )),
        "model": model,
        "attempt": 1,
        "llm_call_count": 1,
        "streaming": stream,
        "time_to_first_token_seconds": time_to_first_token_seconds,
        "request_seconds": request_seconds,
        "page_scope": (
            "multi_page" if multipage else
            "single_page_responsive" if single_page_responsive else
            "unspecified"
        ),
        "capability_granularity": capability_granularity,
        "primary_capability": primary_capability,
        "interaction_level": interaction_level,
        "diversity_coordinate": diversity_hint,
        "output_index": output_index,
        "error": failure,
        "raw_model_content": raw_model_content,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("datasets/WebCompass_text_generation/data.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--seeds-per-class", type=int, default=4)
    parser.add_argument("--max-seed-chars", type=int, default=2800)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--workers", type=int, default=4)
    page_scope = parser.add_mutually_exclusive_group()
    page_scope.add_argument("--multipage", action="store_true")
    page_scope.add_argument("--single-page-responsive", action="store_true")
    parser.add_argument("--profile-driven-pilot", action="store_true")
    parser.add_argument("--profile-spec-file", type=Path)
    parser.add_argument("--benchmark-profile", default="")
    parser.add_argument("--target-level", default="")
    parser.add_argument("--outputs-per-class", type=int, default=1)
    parser.add_argument("--output-index-offset", type=int, default=0)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--classes", nargs="+")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--text-proxy-for-visual", action="store_true")
    args = parser.parse_args()
    external_profile_specs = load_external_profile_specs(args.profile_spec_file)
    load_env(args.env_file)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "")
    if not api_key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_MODEL are required")
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups: dict[str, list[dict[str, Any]]] = {}
    normalized = []
    for row in rows:
        domain = str((row.get("meta") or {}).get("class") or row.get("source_category") or row.get("class") or "").strip()
        instruction = str(row.get("instruction") or row.get("query") or "").strip()
        instance_id = str(row.get("instance_id") or row.get("registry_id") or row.get("source_id") or "").strip()
        if domain and instruction and instance_id:
            normalized.append({**row, "meta": {**(row.get("meta") or {}), "class": domain},
                               "instruction": instruction, "instance_id": instance_id})
    source_benchmarks = sorted({
        str(row.get("source_benchmark", "")).strip()
        for row in normalized if str(row.get("source_benchmark", "")).strip()
    })
    source_benchmark = args.benchmark_profile.strip()
    if not source_benchmark:
        if len(source_benchmarks) == 1:
            source_benchmark = source_benchmarks[0]
        else:
            parser.error("--benchmark-profile is required when the input does not have one unique source_benchmark")
    for row in normalized:
        groups.setdefault(row["meta"]["class"], []).append(row)

    jobs = []
    for domain in selected_domains(groups, args.classes):
        rng = random.Random(f"{args.seed}:{domain}")
        pool = groups[domain]
        count = seed_count_for_benchmark(
            source_benchmark, args.seeds_per_class, len(pool),
            text_proxy_for_visual=args.text_proxy_for_visual,
        )
        for output_index in range(
            args.output_index_offset,
            args.output_index_offset + args.outputs_per_class,
        ):
            spec = pilot_profile_spec(
                source_benchmark, domain, external_profile_specs,
            ) if args.profile_driven_pilot else {
                "capability_granularity": "", "page_scope": "", "primary_capability": "",
                "target_level": "", "interaction_level": "",
            }
            jobs.append((
                domain,
                select_pilot_seeds(pool, source_benchmark, domain, count, rng),
                output_index,
                spec,
                spec["target_level"] or args.target_level,
            ))
    if args.max_jobs is not None:
        jobs = jobs[:args.max_jobs]

    already_attempted = attempted_job_keys(args.output)
    jobs = [job for job in jobs if make_job_key(
        source_benchmark, job[4], job[0], job[2],
    ) not in already_attempted]

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(generate_one, client, model, domain, seeds, args.max_seed_chars,
                            source_benchmark=source_benchmark,
                            target_level=effective_target_level,
                            multipage=(args.multipage or spec["page_scope"] == "multi_page"),
                            single_page_responsive=(
                                args.single_page_responsive or
                                spec["page_scope"] == "single_page_responsive"
                            ),
                            output_index=output_index,
                            capability_granularity=spec["capability_granularity"],
                            primary_capability=spec["primary_capability"],
                            interaction_level=spec["interaction_level"],
                            stream=args.stream,
                            text_proxy_for_visual=args.text_proxy_for_visual): (domain, output_index)
            for domain, seeds, output_index, spec, effective_target_level in jobs
        }
        with args.output.open("a", encoding="utf-8") as handle:
            for future in as_completed(futures):
                result = future.result()
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                written += 1
                print(f"{result['source_benchmark']} {result['target_level']} "
                      f"{result['class']} #{result['output_index']}: {result['status']}", flush=True)

    skipped = len(already_attempted)
    print(f"wrote {written} new records to {args.output}; skipped {skipped} already-attempted jobs")


if __name__ == "__main__":
    main()
