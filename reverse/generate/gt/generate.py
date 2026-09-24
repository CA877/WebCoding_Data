#!/usr/bin/env python3
"""One-call bare-model project generation for the 14-source Generate queries.

This producer only turns text queries into project files. Build, browser, screenshot,
and evaluator gates deliberately remain separate downstream stages.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import subprocess
import tempfile
import threading
import time
from typing import Any, NamedTuple

import httpx


def load_env(path: Path) -> None:
    """Load a small shell-style API env file without depending on another repo."""
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid env assignment at {path}:{line_number}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"invalid env key at {path}:{line_number}")
        values = shlex.split(raw_value, comments=True, posix=True)
        os.environ[key] = values[0] if values else ""


FILE_RE = re.compile(
    r"^<<<FILE:(?P<path>[^>\r\n]+)>>>\r?\n"
    r"(?P<content>.*?)^<<<END_FILE>>>(?:\r?\n|$)",
    re.MULTILINE | re.DOTALL,
)
HTML_HREF_RE = re.compile(r"\bhref\s*=\s*(['\"])(?P<href>.*?)\1", re.IGNORECASE | re.DOTALL)
HASH_ROUTE_HREF_RE = re.compile(
    r"\bhref\s*=\s*(['\"])#(?P<route>/?[A-Za-z][A-Za-z0-9_-]*(?:/[A-Za-z0-9_.$/{}/-]+)*|/)\1",
    re.IGNORECASE,
)
DATA_ROUTE_RE = re.compile(
    r"\bdata-route\s*=\s*(['\"])(?P<route>[A-Za-z][A-Za-z0-9_./:{}$-]*|/)\1",
    re.IGNORECASE,
)
ROUTE_PATH_RE = re.compile(
    r"\b(?:path|route)\s*:\s*(['\"])(?P<route>[#/][A-Za-z0-9_./:{}$*-]*|/)\1",
    re.IGNORECASE,
)
ROUTE_PATH_ATTR_RE = re.compile(
    r"\bpath\s*=\s*(['\"])(?P<route>/[A-Za-z0-9_./:{}$*-]*|/)\1",
    re.IGNORECASE,
)
SWITCH_ROUTE_RE = re.compile(
    r"\bcase\s+(['\"])(?P<route>#[A-Za-z0-9_./:{}$-]+)\1\s*:",
    re.IGNORECASE,
)
NAVIGATE_ROUTE_RE = re.compile(
    r"\b(?:[A-Za-z_$][\w$]*\.)?(?:navigate|navigateTo)\s*\(\s*"
    r"(['\"])(?P<route>#[A-Za-z0-9_./:{}$-]+|/[A-Za-z0-9_./:{}$-]*|[A-Za-z][A-Za-z0-9_-]*)\1",
    re.IGNORECASE,
)
HASH_ASSIGN_ROUTE_RE = re.compile(
    r"\b(?:window\.)?location\.hash\s*=\s*(?P<quote>['\"`])"
    r"(?P<route>#[A-Za-z0-9_./:{}$-]+|[A-Za-z][A-Za-z0-9_./:{}$-]*)"
    r"(?P=quote)",
    re.IGNORECASE,
)
HASH_ROUTE_LITERAL_RE = re.compile(
    r"(?P<quote>['\"`])(?P<route>#/[A-Za-z0-9_./:{}$-]*)(?P=quote)",
    re.IGNORECASE,
)
CUSTOM_ROUTER_MAP_RE = re.compile(
    r"\bnew\s+(?:Router|[A-Za-z_$][\w$]*Router)\s*\(.*?,\s*\{(?P<body>.*?)\}\s*\)",
    re.IGNORECASE | re.DOTALL,
)
ROUTER_MAP_KEY_RE = re.compile(
    r"(?P<quote>['\"])(?P<route>[A-Za-z][A-Za-z0-9_./:{}$-]*|/)(?P=quote)\s*:",
    re.IGNORECASE,
)
VIEW_SECTION_TAG_RE = re.compile(
    r"<(?:section|div|main)\b(?P<attrs>[^>]*\bview-section\b[^>]*)>",
    re.IGNORECASE,
)
ELEMENT_ID_RE = re.compile(
    r"\bid\s*=\s*(['\"])(?P<route>[A-Za-z][A-Za-z0-9_-]*)\1",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a principal frontend engineer producing one training-data ground-truth project.
Privately plan the complete implementation and verify all file references before answering.
Return only complete literal project files using the requested file-boundary protocol.
Never return a tutorial, explanation, patch, pseudocode, TODO, or omitted section."""

CACHEABLE_GROUND_TRUTH_CONTEXT_VERSION = "physical-multi-html-v3"
CACHEABLE_GROUND_TRUTH_CONTEXT = """Stable WebCoding ground-truth production policy.

Produce a complete frontend project, not an explanation or design sketch. Every prominent control must have an honest browser-observable behavior and useful initial data. Keep the implementation within a frontend-only boundary: bundled fixtures, URL state, sessionStorage and localStorage are allowed; backend servers, databases, real authentication, payment processing, cloud deployment and external APIs are outside scope. Loading, empty, validation, error, success, reset and recovery states should be implemented when relevant.

The emitted files are the training answer. They must work from a fresh directory using only the emitted project. All runtime code, styles, icons, illustrations, fonts, fixtures and data must be local. Do not use CDNs, remote fonts, remote images, placeholder-image services, iframes, analytics, runtime fetches, base64 blobs, binary files, lockfiles, source maps or generated build output. Local SVG, CSS illustration and code-generated graphics are preferred. Every referenced local file must be included and every relative link must resolve.

Physical multi-page projects use independent HTML documents. A multi-page request must emit at least two complete .html or .htm files, and each named page should have its own directly reachable document. A hash route, tab, wizard step, hidden section, currentView variable or collection of page components inside one index.html is still a single physical page. Every document must support direct navigation and refresh, contain substantive page-specific content, link to the other relevant documents, and share styles or JavaScript modules where appropriate. If a request asks for seamless or no-reload navigation, the project may progressively enhance local links in JavaScript, but the destination HTML documents must still physically exist and remain usable when opened directly.

Framework projects must remain real projects in their required framework. React and Vue projects should use Vite-compatible package scripts and source modules; Angular projects should include the required Angular configuration. When a framework project is physically multi-page, include multiple HTML entry documents and shared or per-entry bootstrapping code rather than collapsing the pages into one router-only document. Do not replace a required framework with unrelated static markup.

Use semantic structure, accessible names, visible keyboard focus, useful touch targets, coherent responsive behavior and stable rendering. Visual quality should come from deliberate information hierarchy, typography, spacing, color roles, meaningful illustration or data display, and task-appropriate interaction feedback. Avoid empty shells, generic admin templates, repeated placeholder cards, fake controls and decorative effects with no product meaning. Implement the requested product rather than printing these instructions in the interface.

Before responding, privately check the complete file list, entry points, imports, navigation targets, runtime assets and main user flow. Output only literal file blocks in the required boundary format. Do not emit Markdown fences, commentary, tests, evaluation instructions, benchmark names, TODO, FIXME, pseudocode or omitted sections.

Apply this fixed implementation checklist to every project.

Completeness and file delivery:
- Return every source file needed to run the project from a fresh directory. Never rely on a file that is merely named, implied, globally installed, or present in an unstated template.
- Each file boundary contains the full literal content of exactly one safe relative path. Paths are never absolute and never traverse to a parent directory.
- Static projects contain complete HTML, CSS and JavaScript rather than fragments. Framework projects contain a compatible package manifest, entry document, source entry, root component, styles and required configuration.
- Every import, script source, stylesheet link, form destination and navigation link resolves to an emitted file or an intentional same-document anchor.
- Exclude lockfiles, build directories, minified bundles, source maps, test fixtures, evaluator files, screenshots, binary data and base64 payloads.
- Keep code direct and readable. Avoid generated boilerplate, redundant comments and duplicated markup that does not contribute behavior.

Offline and resource behavior:
- Treat the runtime as disconnected from the public internet. The browser never requests a CDN, remote image, remote font, analytics endpoint, external iframe, placeholder service or third-party API.
- Use system font stacks, local inline SVG, CSS shapes, patterns and code-generated Canvas graphics when visual assets are useful. Every local asset path exists.
- Do not hide a remote dependency behind CSS url(), JavaScript fetch(), dynamic import(), HTML preload or a package script.
- Bundled records are deterministic, meaningful and rich enough to demonstrate the requested interface immediately after load.
- Browser persistence may use localStorage or sessionStorage for cross-document continuity. Storage keys remain stable across every participating physical document.

Physical multi-page behavior:
- A declared multi-page site contains two or more independent HTML or HTM documents and one substantive document for every explicitly named page.
- A fragment, tab panel, accordion, hidden section, wizard step, JavaScript view variable or client-side route inside one index document remains one physical page.
- Every physical page loads directly over a local HTTP server, survives refresh, shows page-specific primary content and exposes working links to the other relevant documents.
- Shared CSS and JavaScript provide consistency and cross-page behavior but never replace the required HTML documents.
- If seamless navigation or no full-page reload is requested, retain real destination documents and progressively enhance their links. Direct navigation without enhancement still reaches a useful page.
- Preserve requested cross-page state with URL parameters or browser storage and visibly use that state on the destination page.
- Do not create nominal HTML files that redirect to one document, render identical shells, or contain only placeholder content.

Interaction integrity:
- Prominent buttons, links, filters, tabs, toggles, form controls, drag targets, media controls and table actions perform the behavior promised by their labels.
- Every action has observable feedback: visible state, validation, selection, recalculation, navigation, confirmation, undo or recovery.
- Initialize the product into a useful state. Never leave the core feature behind an undismissable overlay, empty canvas, hidden root or uninitialized handler.
- Implement reset, cancel, undo and recovery as real transitions. Preserve unrelated state when requested and communicate the result visibly.
- Forms have labels, constraints and understandable validation. Never accept invalid data silently or show success before conditions are met.
- Filters, sorting and comparisons update visible content. Quantity, progress, price, count and summary displays derive from current browser state.
- Drag, Canvas, SVG, timeline and media-like interactions have a usable initial render and deterministic controls, with keyboard alternatives where accessibility is requested.
- Avoid fake loading delays and decorative controls whose only effect is an unrelated animation.

Visual and layout integrity:
- Choose a deliberate visual direction for the requested domain, with clear type hierarchy, spacing rhythm, color roles, surfaces and affordances.
- Keep visual language consistent across physical documents while giving every page a distinct composition and primary purpose.
- Favor meaningful illustrations, diagrams, timelines, editorial compositions, data displays, spatial canvases or SVG motifs when they support the product.
- Do not force every product into a generic sidebar dashboard, workbench shell or repeated metric-card template.
- A simple interface is acceptable when appropriate but looks intentional and complete. Avoid huge empty regions caused by missing content, collapsed containers or failed initialization.
- Use responsive rules for common desktop and narrow viewports. Prevent accidental horizontal overflow, clipped navigation, unreadable contrast and overlapping fixed elements.
- Provide visible hover, focus, active, selected, disabled, error and success treatments where applicable. Critical status never relies on color alone.
- Animation, gradients, glass effects and decorative texture reinforce product meaning rather than substituting for functionality.

Accessibility and semantics:
- Use landmarks, headings, labels, buttons and links according to their semantic roles. Clickable non-controls require a strong reason and complete keyboard behavior.
- Meaningful controls have accessible names, focus indicators remain visible, modal focus is managed, and keyboard order follows the visual task flow.
- Status and validation feedback remain understandable without color. Use descriptive text and suitable live-region semantics for important dynamic feedback.
- Tables use headers and captions when useful. Informative graphics have text alternatives and decorative graphics stay outside the accessibility tree.

Framework and runtime consistency:
- Honor an explicitly requested frontend framework. Do not answer a React, Vue or Angular request with unrelated static HTML, and do not introduce a framework when portable HTML is the intended runtime.
- A Vite-style project uses compatible module entry points and package scripts. Imported dependencies appear in the package manifest, and the selected versions are mutually compatible.
- Keep browser-only logic in the browser. Do not add a server merely to hold mock records, submit a local form, preserve UI state or simulate a response.
- Avoid framework initialization races. The root element exists before mounting, module paths resolve, required styles load, and initial data is available before the primary view renders.
- Never reference a Prisma schema, environment secret, database migration, server route or unavailable generated client in a frontend-only answer.
- For static documents, scripts use defer, modules or safe initialization order so controls are attached after their elements exist.
- Keep the clean source as authored source. Do not emit compiled JavaScript beside TypeScript source unless the runtime explicitly requires the compiled file and the project documents that design.

State and page continuity:
- Define one understandable browser-state model for records shared across pages. Read, update and serialize the same schema everywhere instead of creating independent hard-coded counts.
- A page opened directly without prior session state still displays bundled initial data and remains usable. Missing optional state falls back safely rather than producing a blank view or exception.
- Links carrying a selected record use a stable identifier in the URL or shared storage. Destination pages resolve that identifier, display the selected record and provide a recovery path when it is unknown.
- Undo operates on a real previous state, reset returns to a documented initial state, and cancel prevents unintended mutation. Confirmation appears only after the action succeeds locally.
- Sorting and filtering preserve the underlying data, empty states explain how to recover, and navigating back does not silently corrupt the current selection.
- If multiple pages update the same state, subsequent pages recompute their summaries from storage during load so the visible result remains coherent after navigation and refresh.

Visual variety without template collapse:
- Choose compositions from the actual product: an editorial story can use chapters and immersive media; a cultural archive can use collection walls and timelines; a creative tool can use a canvas and inspectors; a service flow can use guided steps and summaries.
- Dashboards are appropriate only when the user primarily needs monitoring or management. Even then, the layout should express the domain instead of repeating generic charts and metric cards.
- Brand expression may use locally drawn marks, typographic rhythm, domain-specific iconography, layered surfaces, maps, diagrams, specimens, artifacts or abstract SVG scenes.
- Distinct pages should not merely swap a heading above the same grid. Their layout, information density and interaction surface should match their role in the journey.
- Use enough representative content to judge the design, while avoiding repetitive filler paragraphs and placeholder labels such as Item 1, Card 2 or Lorem ipsum.
- A visually ambitious request still needs readable text, stable controls and restrained motion. Respect reduced-motion preferences when animated presentation is central.

Failure prevention:
- Do not leave syntax fragments, truncated arrays, unmatched tags, incomplete CSS rules or references to functions that were never defined.
- Do not render the application only after a button whose handler is unavailable. The initial page must show its core content without hidden manual initialization.
- Do not prevent navigation with empty href values, inaccessible click handlers or links to missing documents.
- Do not create zero-height Canvas or SVG roots, invisible text on matching backgrounds, full-screen overlays above the application, or fixed panels that cover the primary controls.
- Do not call network APIs at startup, even with graceful fallback. The offline bundled path is the only runtime path.
- Do not claim a feature in explanatory copy when the actual control or state transition is absent.

Private acceptance review before output:
- Confirm that the implementation answers the supplied request instead of substituting a nearby generic product.
- Confirm that every named multi-page destination exists as a physical document with distinct content, direct-load behavior and working local navigation.
- Confirm that prominent controls are wired, the main flow starts, and requested success, error, empty, reset, undo and recovery states are reachable.
- Confirm that no public-network URL or missing local resource exists anywhere in HTML, CSS, JavaScript, configuration or data.
- Confirm that imports and scripts are internally consistent and no backend, database, authentication service, payment flow or deployment requirement was introduced.
- Confirm meaningful initial content, stable layout, visible focus, readable contrast and an intentional visual direction.
- Output only complete file blocks using exactly <<<FILE:path/to/file>>>, the literal content, and <<<END_FILE>>>. Repeat for every file without Markdown or surrounding commentary."""


class GenerationContract(NamedTuple):
    benchmark: str
    framework: str
    runtime: str
    page_mode: str
    framework_basis: str
    benchmark_focus: str


BENCHMARK_FOCUS = {
    "WebCompass": (
        "Prioritize browser-observable functionality, polished visual quality, realistic state "
        "transitions, interaction feedback, and coherent navigation."
    ),
    "DesignBench": (
        "Use the benchmark-specified framework and preserve a clean component structure while "
        "delivering the complete responsive visual implementation."
    ),
    "Interaction2Code": (
        "Prioritize the requested interaction transition: trigger, visible before/after state, "
        "feedback, reversibility, and keyboard-accessible behavior."
    ),
    "Vision2Web": (
        "For L1, implement one responsive page whose composition adapts across viewports. For L2, "
        "implement the complete connected frontend page graph and preserve visible cross-page state."
    ),
    "ArtifactsBench": (
        "Implement the central artifact honestly, including its core game, SVG, Canvas, simulation, "
        "visualization, editing, or utility mechanics rather than a decorative mockup."
    ),
    "Design2Code": (
        "Prioritize full-page layout fidelity: hierarchy, typography, color roles, spacing, image "
        "regions, long-page structure, and responsive behavior."
    ),
    "Flame-VLM-Code": (
        "Produce React code with reusable component hierarchy, data-driven repeated regions, event "
        "handling, conditional states, and complete styling."
    ),
    "WebGen-Bench": (
        "Implement the full locally demonstrable website, including content presentation, user "
        "interaction, browser-side data management, and observable completion states."
    ),
    # The text-query builder uses these short names for the same benchmark
    # families. Keep them as first-class contracts so its JSONL can be consumed
    # without a lossy pre-processing rename.
    "WebGen": (
        "Implement the full locally demonstrable website, including content presentation, user "
        "interaction, browser-side data management, and observable completion states."
    ),
    "Cookie-Bench": (
        "Prioritize the requested browser interaction, clear state transitions, useful initial "
        "data, accessible controls, and a complete responsive frontend."
    ),
    "MiniAppBench": (
        "Implement the requested interactive artifact faithfully, including touch-friendly controls, "
        "deterministic local state, visible feedback, and complete responsive behavior."
    ),
    "InteractWeb-Bench": (
        "Treat the query as the clarified final intent and implement all consistent requirements, "
        "including multi-page continuity when requested."
    ),
    "FullFront": (
        "Implement the requested layout, text-image composition, authored interactions, and the "
        "complete visible page rather than isolated components."
    ),
    "FronTalk": (
        "Treat the query as the consolidated final version of a conversational build and preserve "
        "all accumulated final-state functionality in one coherent project."
    ),
    "ComUIBench": (
        "Use reusable Vue components across the complex multi-page site. Shared navigation, cards, "
        "forms, overlays, tokens, and state variants must be implemented once and reused."
    ),
    "WebUIBench": (
        "Prioritize correct semantic HTML, element attributes, visual structure, complete page "
        "composition, and functional controls described by the query."
    ),
    "Web2Code": (
        "Prioritize complete webpage structure and visual fidelity across layout, text, color, "
        "spacing, component grouping, and responsive behavior."
    ),
}

DESIGNBENCH_PROFILE_FRAMEWORK = {
    "DB-G1 vanilla-generation": "vanilla",
    "DB-G2 react-generation": "react",
    "DB-G3 vue-generation": "vue",
    "DB-G4 angular-generation": "angular",
    "DB-C01 vanilla-content": "vanilla",
    "DB-C02 vanilla-dense": "vanilla",
    "DB-C03 react-content": "react",
    "DB-C04 react-dense": "react",
    "DB-C05 vue-content": "vue",
    "DB-C06 vue-dense": "vue",
    "DB-C07 angular-content": "angular",
    "DB-C08 angular-dense": "angular",
}

RUNTIME_FOR_FRAMEWORK = {
    "vanilla": "static",
    "react": "vite_react",
    "vue": "vite_vue",
    "angular": "angular",
    "query_explicit": "adaptive",
}


def _categories(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for candidate in (row.get("source_categories"), (row.get("metadata") or {}).get("source_categories")):
        if isinstance(candidate, list):
            values.extend(str(item) for item in candidate)
    return values


def _designbench_framework(row: dict[str, Any]) -> tuple[str, str]:
    profile = str(row.get("source_profile") or "")
    if profile in DESIGNBENCH_PROFILE_FRAMEWORK:
        return DESIGNBENCH_PROFILE_FRAMEWORK[profile], "benchmark_profile"
    category_map = {
        "generation=vanilla": "vanilla",
        "generation=react": "react",
        "generation=vue": "vue",
        "generation=angular": "angular",
    }
    found = {category_map[item] for item in _categories(row) if item in category_map}
    if len(found) > 1:
        if profile == "DB-G5 dense-framework-ui":
            return "query_explicit", "query_required_by_profile"
        raise ValueError(f"conflicting DesignBench framework metadata: {sorted(found)}")
    if found:
        return found.pop(), "benchmark_metadata"
    # DB-G5 is a mixed profile. Its rows normally retain generation=<framework>.
    if profile == "DB-G5 dense-framework-ui":
        return "vanilla", "portable_default"
    return "vanilla", "portable_default"


def _page_mode(row: dict[str, Any]) -> str:
    values = {
        str(row.get("page_type") or "").lower(),
        str(row.get("page_scope") or "").lower(),
        str((row.get("metadata") or {}).get("page_scope") or "").lower(),
        str(row.get("product_category") or "").lower(),
    }
    if values & {"mp", "multi_page", "multi-page", "multi-page product website"}:
        return "multi_page"
    if values & {"single_page_responsive", "responsive", "multi_viewport"}:
        return "single_page_responsive"
    return "single_page"


def resolve_contract(row: dict[str, Any]) -> GenerationContract:
    benchmark = str(
        row.get("source_benchmark")
        or row.get("benchmark")
        or (row.get("metadata") or {}).get("source_benchmark")
        or ""
    )
    if benchmark not in BENCHMARK_FOCUS:
        raise ValueError(f"unsupported or missing source_benchmark: {benchmark!r}")
    if benchmark == "DesignBench":
        framework, basis = _designbench_framework(row)
    elif benchmark == "Flame-VLM-Code":
        framework, basis = "react", "benchmark_required"
    elif benchmark == "ComUIBench":
        framework, basis = "vue", "benchmark_pipeline"
    else:
        # These benchmarks evaluate rendered frontend behavior or HTML rather than
        # prescribing a framework. Vanilla is the portable default; an explicit
        # stack in the user query remains authoritative in the prompt.
        framework, basis = "vanilla", "portable_default"
    return GenerationContract(
        benchmark=benchmark,
        framework=framework,
        runtime=RUNTIME_FOR_FRAMEWORK[framework],
        page_mode=_page_mode(row),
        framework_basis=basis,
        benchmark_focus=BENCHMARK_FOCUS[benchmark],
    )


def query_text(row: dict[str, Any]) -> str:
    value = row.get("query") or row.get("instruction")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("record has no non-empty query/instruction")
    return value.strip()


def source_id(row: dict[str, Any]) -> str:
    value = (
        row.get("instance_id")
        or row.get("id")
        or row.get("job_id")
        or row.get("allocation_id")
    )
    if value is None or not str(value).strip():
        raise ValueError("record has no instance_id/id/job_id")
    return str(value).strip()


def project_dir_name(row: dict[str, Any]) -> str:
    original = source_id(row)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._-") or "case"
    # Query-expansion reruns can reuse both instance_id and job_id while producing
    # a different query. The query digest prevents two paid generations from ever
    # targeting the same directory, while exact duplicate source rows still dedupe.
    digest = hashlib.sha256((original + "\0" + query_text(row)).encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:100]}-{digest}"


def _framework_instruction(contract: GenerationContract) -> str:
    if contract.framework == "query_explicit":
        required = (
            "This mixed DesignBench profile states its required framework directly in the user request. "
            "You must use exactly that named Vanilla/React/Vue/Angular framework and provide its complete "
            "runnable project; do not substitute another framework."
        )
    elif contract.framework == "react":
        required = (
            "You must use React with a Vite-compatible package.json, index.html, and complete "
            "src/ JSX or TSX modules. Do not replace React with static HTML."
        )
    elif contract.framework == "vue":
        required = (
            "You must use Vue 3 with a Vite-compatible package.json, index.html, and complete "
            "src/ .vue modules using reusable components. Do not replace Vue with static HTML."
        )
    elif contract.framework == "angular":
        required = (
            "You must use Angular with package.json, angular.json, tsconfig files, and complete "
            "src/ application modules/components/templates/styles. Do not replace Angular with another framework."
        )
    else:
        required = (
            "Use portable semantic HTML, handcrafted CSS, and browser JavaScript by default. "
            "If the user request explicitly names a frontend framework, that explicit request overrides "
            "this portable default and you must provide the complete runnable framework project."
        )
    return required


def _page_instruction(row: dict[str, Any], contract: GenerationContract) -> str:
    architecture = row.get("page_architecture")
    architecture_text = json.dumps(architecture, ensure_ascii=False) if architecture else "not separately enumerated"
    if contract.page_mode == "multi_page":
        if contract.runtime == "static":
            shape = (
                "HARD PHYSICAL MULTI-PAGE OUTPUT CONTRACT. Implement every requested page as a separate complete HTML "
                "document with working links between documents. Emit at least two independent .html/.htm files; a single "
                "index.html with hash routes, tabs, hidden sections, wizard steps, currentView state, or multiple page "
                "components does not satisfy this contract. Every named page must be directly reachable and refreshable. "
                "If the request requires client-side routing or no full-page reloads, progressively enhance navigation "
                "while still emitting the real destination HTML documents. Do not emit links to files that do not exist. "
                "Share CSS and JavaScript modules where appropriate, and preserve required state across documents with "
                "URL parameters, sessionStorage, or localStorage. Before finishing, verify the emitted file list contains "
                "a complete HTML document for each declared page."
            )
        else:
            shape = (
                "HARD PHYSICAL MULTI-PAGE OUTPUT CONTRACT. Create at least two independent HTML entry documents and a "
                "separate HTML document for every requested page, while retaining the required framework and shared "
                "reusable source modules. Every document must be directly reachable and refreshable in the documented "
                "local runtime. A router-only index.html does not satisfy this physical multi-page requirement."
            )
        return f"{shape}\nDeclared page architecture: {architecture_text}"
    if contract.page_mode == "single_page_responsive":
        return (
            "Create one responsive page and implement materially different but coherent desktop, tablet, and mobile "
            f"compositions. Declared page architecture: {architecture_text}"
        )
    return f"Create one complete page/view. Declared page architecture: {architecture_text}"


def build_user_prompt(row: dict[str, Any], contract: GenerationContract) -> str:
    profile = str(row.get("source_profile") or row.get("product_category") or "unspecified")
    return f"""Implement the following final-state frontend request as a complete runnable project.

<user_request>
{query_text(row)}
</user_request>

Benchmark-derived implementation contract:
- Source benchmark: {contract.benchmark}
- Source profile: {profile}
- Benchmark focus: {contract.benchmark_focus}
- Framework policy: {_framework_instruction(contract)}
- Page policy: {_page_instruction(row, contract)}

Shared ground-truth requirements:
- Implement every user-visible core requirement honestly. Every prominent control must work and produce observable feedback.
- Keep the scope at or below the WebCompass backend boundary. Do not implement a backend server, database service, real authentication, payment processing, cloud deployment, or external API. Represent these semantics with bundled deterministic data, in-browser state, URL state, sessionStorage, or localStorage.
- HARD OFFLINE ASSET CONTRACT: every emitted runtime dependency must be local. Before finishing, scan every file and remove all http:// and https:// asset URLs, CDN imports, remote placeholder-image services, remote fonts, iframes, analytics, and runtime fetches. Create needed illustrations with local SVG/CSS or bundled project files.
- The project must work from a fresh directory using the included files and documented commands. If a package manager is required, include package.json with compatible scripts and versions.
- Put all runtime assets, icons, fonts, fixtures, and data in the project or generate them in code. Do not use a CDN, remote URL, iframe, analytics, remote font, or runtime network request.
- Include meaningful initial data so the completed interface is visually rich and immediately demonstrable.
- Implement loading, empty, validation, error, success, reset, and recovery states when the request makes them relevant.
- Use semantic structure, accessible labels, visible keyboard focus, coherent responsive layout, and stable rendering.
- Do not add tests, evaluation instructions, benchmark names, TODOs, fake buttons, pseudocode, omitted sections, binary files, base64 blobs, lockfiles, or generated build output.
- Add README.md only for framework projects that require install/build/run commands. Do not display these implementation instructions in the webpage.

Output protocol (mandatory):
<<<FILE:path/to/file>>>
complete literal file content
<<<END_FILE>>>

Repeat the block for every required file. Output file blocks only, without Markdown fences or commentary.
Never put a boundary marker inside file content.
"""


def build_cached_messages(row: dict[str, Any], contract: GenerationContract) -> list[dict[str, Any]]:
    """Use a message-level cache boundary required by Qwen 3.5+ models."""
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT + "\n\n" + CACHEABLE_GROUND_TRUTH_CONTEXT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
        },
        {"role": "user", "content": build_user_prompt(row, contract)},
    ]


def parse_file_blocks(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for match in FILE_RE.finditer(text.strip() + "\n"):
        name = match.group("path").strip().replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"unsafe output path: {name}")
        if name in files:
            raise ValueError(f"duplicate output path: {name}")
        files[name] = match.group("content")
    if not files:
        raise ValueError("model response contains no complete file blocks")
    return files


def _missing_local_html_targets(files: dict[str, str]) -> list[str]:
    names = set(files)
    missing: set[str] = set()
    for source_name, content in files.items():
        if not source_name.endswith((".html", ".htm")):
            continue
        source_parent = PurePosixPath(source_name).parent.as_posix()
        for match in HTML_HREF_RE.finditer(content):
            href = match.group("href").strip()
            lowered = href.lower()
            if (
                not href
                or href.startswith(("#", "//"))
                or lowered.startswith(("http://", "https://", "mailto:", "tel:", "javascript:", "data:"))
            ):
                continue
            path = href.split("#", 1)[0].split("?", 1)[0]
            if not path or "${" in path or not path.lower().endswith((".html", ".htm")):
                continue
            target = posixpath.normpath(posixpath.join(source_parent, path))
            if target.startswith("../") or target not in names:
                missing.add(target)
    return sorted(missing)


def _canonical_route_root(value: str) -> str | None:
    route = value.strip()
    if route.startswith("#"):
        route = route[1:]
    route = route.split("?", 1)[0].strip()
    if route in {"", "/", "home", "index"}:
        return "/"
    route = route.strip("/")
    if not route or route == "*":
        return None
    return "/" + route.split("/", 1)[0]


def _has_multiple_hash_routes(files: dict[str, str]) -> bool:
    combined = "\n".join(files.values())
    has_client_router = bool(
        re.search(
            r"\bhashchange\b|\blocation\.hash\b|\bhistory\.pushState\b|\bpopstate\b|"
            r"\bBrowserRouter\b|\bHashRouter\b|\bcreateBrowserRouter\b|\bcreateHashRouter\b",
            combined,
            re.IGNORECASE,
        )
    )
    route_roots: set[str] = set()
    for pattern in (
        HASH_ROUTE_HREF_RE,
        HASH_ROUTE_LITERAL_RE,
        DATA_ROUTE_RE,
        ROUTE_PATH_RE,
        ROUTE_PATH_ATTR_RE,
        SWITCH_ROUTE_RE,
        NAVIGATE_ROUTE_RE,
        HASH_ASSIGN_ROUTE_RE,
    ):
        for match in pattern.finditer(combined):
            canonical = _canonical_route_root(match.group("route"))
            if canonical is not None:
                route_roots.add(canonical)
    for router_match in CUSTOM_ROUTER_MAP_RE.finditer(combined):
        for key_match in ROUTER_MAP_KEY_RE.finditer(router_match.group("body")):
            canonical = _canonical_route_root(key_match.group("route"))
            if canonical is not None:
                route_roots.add(canonical)
    has_view_id_hash_router = bool(
        re.search(r"\blocation\.hash\s*=\s*[A-Za-z_$][\w$]*", combined, re.IGNORECASE)
        and re.search(r"\bfunction\s+navigate\s*\(", combined, re.IGNORECASE)
    )
    if has_view_id_hash_router:
        for tag_match in VIEW_SECTION_TAG_RE.finditer(combined):
            id_match = ELEMENT_ID_RE.search(tag_match.group("attrs"))
            if id_match:
                canonical = _canonical_route_root(id_match.group("route"))
                if canonical is not None:
                    route_roots.add(canonical)
    return has_client_router and len(route_roots) >= 2


def validate_project_files(files: dict[str, str], contract: GenerationContract) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    names = set(files)
    suffixes = {PurePosixPath(name).suffix.lower() for name in names}
    if contract.page_mode == "multi_page":
        html_count = sum(name.lower().endswith((".html", ".htm")) for name in names)
        if html_count < 2:
            errors.append(
                "physical multi-page project requires at least two independent HTML documents"
            )
    if contract.runtime == "static":
        if "index.html" not in names:
            errors.append("static project is missing index.html")
        for target in _missing_local_html_targets(files):
            errors.append(f"missing local HTML target: {target}")
    elif contract.runtime == "vite_react":
        if "package.json" not in names:
            warnings.append("React project is missing package.json")
        if not ({".jsx", ".tsx"} & suffixes):
            warnings.append("React project has no JSX/TSX source")
    elif contract.runtime == "vite_vue":
        if "package.json" not in names:
            warnings.append("Vue project is missing package.json")
        if ".vue" not in suffixes:
            warnings.append("Vue project has no .vue source")
    elif contract.runtime == "angular":
        for required in ("package.json", "angular.json"):
            if required not in names:
                warnings.append(f"Angular project is missing {required}")
        if ".ts" not in suffixes:
            warnings.append("Angular project has no TypeScript source")
    elif contract.runtime == "adaptive":
        if "index.html" not in names and "package.json" not in names:
            warnings.append("adaptive framework project has neither index.html nor package.json")
    combined = "\n".join(files.values())
    network_text = combined.replace("http://www.w3.org/2000/svg", "")
    network_text = re.sub(
        r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?",
        "",
        network_text,
        flags=re.IGNORECASE,
    )
    if re.search(r"https?://|//cdn\.|@import\s+url", network_text, re.I):
        warnings.append("project contains a remote URL or CSS import")
    if re.search(r"\b(?:TODO|FIXME|implement later|placeholder implementation)\b", combined, re.I):
        warnings.append("project contains TODO or placeholder language")
    for name, content in files.items():
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in {".js", ".mjs", ".cjs"}:
            continue
        input_type = "commonjs" if suffix == ".cjs" else "module"
        try:
            checked = subprocess.run(
                ["node", f"--input-type={input_type}", "--check"],
                input=content,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            warnings.append("JavaScript syntax validation unavailable")
            break
        if checked.returncode != 0:
            warnings.append(f"invalid JavaScript syntax: {name}")
    if sum(len(value) for value in files.values()) < 1500:
        warnings.append("project output is suspiciously short")
    return errors, warnings


def _serialize_usage(usage: Any) -> Any:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return usage


def _raw_failure_path(root: Path, project_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    return root / f"{project_id}.{stamp}.txt"


def _write_project_atomic(output_dir: Path, project_id: str, files: dict[str, str], metadata: dict[str, Any]) -> None:
    projects = output_dir / "projects"
    staging = output_dir / ".staging"
    projects.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    target = projects / project_id
    if target.exists():
        raise FileExistsError(f"project directory already exists without a completed marker: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=f"{project_id}.", dir=staging))
    for name, content in files.items():
        path = temporary / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (temporary / ".generation.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.rename(temporary, target)


def _error_status(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "ratelimit" in name or "rate_limit" in name:
        return "rate_limit"
    if "connection" in name:
        return "connection_error"
    return "error"


def _generate_raw(
    client: Any,
    model: str,
    row: dict[str, Any],
    contract: GenerationContract,
    max_tokens: int,
    enable_thinking: bool,
    stream: bool,
    wire_api: str,
    actor_authorization: str,
) -> tuple[str, Any]:
    extra_headers = (
        {"x-openai-actor-authorization": actor_authorization}
        if actor_authorization
        else None
    )
    if wire_api == "responses":
        request = {
            "model": model,
            "instructions": SYSTEM_PROMPT + "\n\n" + CACHEABLE_GROUND_TRUTH_CONTEXT,
            "input": build_user_prompt(row, contract),
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if extra_headers:
            request["extra_headers"] = extra_headers
        if stream:
            parts: list[str] = []
            with client.responses.stream(**request) as response_stream:
                for event in response_stream:
                    if event.type == "response.output_text.delta":
                        parts.append(event.delta)
                try:
                    response = response_stream.get_final_response()
                except RuntimeError as exc:
                    # Nju-Link can close a successful SSE stream after the final
                    # text delta without forwarding response.completed. Preserve
                    # only a syntactically complete file-block response; the
                    # normal project validator still rejects truncated output.
                    text = "".join(parts).strip()
                    if (
                        "response.completed" not in str(exc)
                        or not text
                        or not text.endswith("<<<END_FILE>>>")
                    ):
                        raise
                    return text, None
            return "".join(parts), response.usage
        response = client.responses.create(**request)
        return response.output_text or "", response.usage

    request = {
        "model": model,
        "messages": build_cached_messages(row, contract),
        "temperature": 0.25,
        "max_tokens": max_tokens,
        "extra_body": {"enable_thinking": enable_thinking},
        "stream": stream,
    }
    if extra_headers:
        request["extra_headers"] = extra_headers
    if stream:
        request["stream_options"] = {"include_usage": True}
        response = client.chat.completions.create(**request)
        parts = []
        usage = None
        for chunk in response:
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                parts.append(content)
        return "".join(parts), usage
    response = client.chat.completions.create(**request)
    return response.choices[0].message.content or "", response.usage


def generate_one(
    client: Any,
    model: str,
    row: dict[str, Any],
    output_dir: Path,
    max_tokens: int,
    enable_thinking: bool,
    stream: bool,
    wire_api: str,
    actor_authorization: str,
) -> dict[str, Any]:
    original_id = source_id(row)
    project_id = project_dir_name(row)
    completed = output_dir / "projects" / project_id / ".generation.json"
    if completed.is_file():
        return {"instance_id": original_id, "project_id": project_id, "status": "skipped"}
    started = time.monotonic()
    contract = resolve_contract(row)
    try:
        raw, usage = _generate_raw(
            client, model, row, contract, max_tokens, enable_thinking,
            stream, wire_api, actor_authorization,
        )
        try:
            files = parse_file_blocks(raw)
        except Exception:
            _raw_failure_path(output_dir / "raw_failures", project_id).write_text(raw, encoding="utf-8")
            raise
        errors, warnings = validate_project_files(files, contract)
        if errors:
            _raw_failure_path(output_dir / "raw_failures", project_id).write_text(raw, encoding="utf-8")
            raise ValueError("; ".join(errors))
        metadata = {
            "status": "ok",
            "instance_id": original_id,
            "project_id": project_id,
            "query": query_text(row),
            "source_benchmark": contract.benchmark,
            "source_profile": row.get("source_profile") or row.get("product_category"),
            "contract": contract._asdict(),
            "model": model,
            "thinking": enable_thinking,
            "stream": stream,
            "wire_api": wire_api,
            "store": False if wire_api == "responses" else None,
            "llm_calls": 1,
            "prompt_cache_context_version": CACHEABLE_GROUND_TRUTH_CONTEXT_VERSION,
            "warnings": warnings,
            "files": {name: len(content.encode("utf-8")) for name, content in files.items()},
            "usage": _serialize_usage(usage),
        }
        _write_project_atomic(output_dir, project_id, files, metadata)
        return {
            "instance_id": original_id,
            "project_id": project_id,
            "status": "ok",
            "source_benchmark": contract.benchmark,
            "framework": contract.framework,
            "page_mode": contract.page_mode,
            "files": len(files),
            "warnings": warnings,
            "usage": _serialize_usage(usage),
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "instance_id": original_id,
            "project_id": project_id,
            "status": _error_status(exc),
            "source_benchmark": contract.benchmark,
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def generate_with_claim(
    client: Any, model: str, row: dict[str, Any], output_dir: Path,
    max_tokens: int, enable_thinking: bool, stream: bool, wire_api: str,
    actor_authorization: str, provider_label: str, max_attempts: int,
    retry_backoff_seconds: float, claim_stale_seconds: float,
) -> dict[str, Any]:
    project_id = project_dir_name(row)
    completed = output_dir / "projects" / project_id / ".generation.json"
    if completed.is_file():
        return {"instance_id": source_id(row), "project_id": project_id, "status": "skipped"}
    claim_dir = output_dir / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)
    claim = claim_dir / f"{project_id}.lock"
    if claim.exists() and time.time() - claim.stat().st_mtime > claim_stale_seconds:
        claim.unlink(missing_ok=True)
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return {"instance_id": source_id(row), "project_id": project_id, "status": "claimed"}
    os.write(fd, json.dumps({"pid": os.getpid(), "provider": provider_label, "time": time.time()}).encode())
    os.close(fd)
    failures: list[dict[str, Any]] = []
    try:
        for attempt in range(1, max_attempts + 1):
            result = generate_one(
                client, model, row, output_dir, max_tokens, enable_thinking,
                stream, wire_api, actor_authorization,
            )
            if result["status"] in {"ok", "skipped"}:
                result.update(provider_label=provider_label, attempts=attempt, attempt_errors=failures)
                marker = output_dir / "projects" / project_id / ".generation.json"
                if marker.is_file() and result["status"] == "ok":
                    metadata = json.loads(marker.read_text(encoding="utf-8"))
                    metadata.update(provider_label=provider_label, llm_calls=attempt, attempt_errors=failures)
                    marker.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return result
            failures.append({k: result.get(k) for k in ("status", "error_type", "error", "duration_seconds")})
            if attempt < max_attempts:
                time.sleep(min(retry_backoff_seconds * attempt, 30.0))
        result.update(provider_label=provider_label, attempts=max_attempts, attempt_errors=failures)
        return result
    finally:
        claim.unlink(missing_ok=True)


def _input_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in inputs:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    if not files:
        raise ValueError("no input JSONL files found")
    return files


def discover_useless_hashes(
    inputs: list[Path], explicit_overrides: list[Path]
) -> tuple[set[str], list[Path]]:
    candidates = {path.resolve() for path in explicit_overrides}
    for input_path in inputs:
        raw_dir = input_path if input_path.is_dir() else input_path.parent
        if raw_dir.name == "raw":
            metadata_dir = raw_dir.parent / "metadata"
            if metadata_dir.is_dir():
                candidates.update(
                    path.resolve() for path in metadata_dir.glob("*usability_override*.jsonl")
                )
    hashes: set[str] = set()
    files = sorted(candidates)
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("usability") != "useless":
                    continue
                digest = row.get("query_sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise ValueError(f"invalid useless override hash at {path}:{line_number}")
                hashes.add(digest)
    return hashes, files


def load_rows(
    inputs: list[Path], *, excluded_query_hashes: set[str] | None = None
) -> tuple[list[dict[str, Any]], int, int, int]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    excluded_query_hashes = excluded_query_hashes or set()
    unusable = 0
    duplicates = 0
    excluded = 0
    for path in _input_files(inputs):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("status") not in {None, "ok"}:
                    unusable += 1
                    continue
                identifier = source_id(row)
                query = query_text(row)
                query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
                if query_hash in excluded_query_hashes:
                    excluded += 1
                    continue
                key = (identifier, query_hash)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                rows.append(row)
    return rows, unusable, duplicates, excluded


def plan_summary(
    rows: list[dict[str, Any]], unusable: int = 0, duplicate_source_rows: int = 0,
    excluded_useless: int = 0,
) -> dict[str, Any]:
    contracts = [resolve_contract(row) for row in rows]
    return {
        "usable": len(rows),
        "unusable_source_rows": unusable,
        "duplicate_source_rows": duplicate_source_rows,
        "excluded_useless": excluded_useless,
        "by_benchmark": dict(sorted(Counter(item.benchmark for item in contracts).items())),
        "by_framework": dict(sorted(Counter(item.framework for item in contracts).items())),
        "by_runtime": dict(sorted(Counter(item.runtime for item in contracts).items())),
        "by_page_mode": dict(sorted(Counter(item.page_mode for item in contracts).items())),
    }


def append_result(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def batch_exit_code(status_counts: Counter[str]) -> int:
    failed = sum(count for status, count in status_counts.items() if status not in {"ok", "skipped", "claimed"})
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True,
                        help="JSONL file or directory of JSONL files; repeatable")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--usability-override", action="append", type=Path, default=[],
                        help="Additional usability override JSONL; adjacent raw/../metadata files are auto-discovered")
    parser.add_argument("--include-useless", action="store_true",
                        help="Explicitly ignore useless-query overrides (not recommended)")
    parser.add_argument("--model")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=30000)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--provider-label", default="primary")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--claim-stale-seconds", type=float, default=3600.0)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument(
        "--wire-api", choices=("chat-completions", "responses"),
        default=os.environ.get("OPENAI_WIRE_API", "chat-completions"),
    )
    parser.add_argument(
        "--actor-authorization",
        default=os.environ.get("OPENAI_ACTOR_AUTHORIZATION", ""),
    )
    parser.add_argument("--job-id", action="append", dest="job_ids")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if (args.workers < 1 or args.max_tokens < 1 or args.timeout <= 0
            or args.max_attempts < 1 or args.claim_stale_seconds <= 0
            or args.retry_backoff_seconds < 0):
        parser.error("worker, token, timeout, attempt, backoff, and claim settings are invalid")
    if args.env_file:
        load_env(args.env_file)
    excluded_hashes, override_files = discover_useless_hashes(args.input, args.usability_override)
    if args.include_useless:
        excluded_hashes = set()
    rows, unusable, duplicates, excluded = load_rows(
        args.input, excluded_query_hashes=excluded_hashes
    )
    if args.job_ids:
        wanted = set(args.job_ids)
        rows = [row for row in rows if source_id(row) in wanted or str(row.get("job_id")) in wanted]
        found = {source_id(row) for row in rows} | {str(row.get("job_id")) for row in rows}
        missing = wanted - found
        if missing:
            parser.error(f"requested IDs not found: {sorted(missing)}")
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[:args.limit]
    summary = plan_summary(rows, unusable, duplicates, excluded)
    summary["usability_override_files"] = [str(path) for path in override_files]
    print(json.dumps({"plan": summary}, ensure_ascii=False, sort_keys=True), flush=True)
    if args.plan_only:
        return
    key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if base_url.rstrip("/") == "https://api.nju-link.com":
        base_url = base_url.rstrip("/") + "/v1"
    model = args.model or os.environ.get("OPENAI_MODEL", "")
    if not key or not base_url or not model:
        parser.error("OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL/--model are required")
    from openai import OpenAI
    http_client = httpx.Client(trust_env=False, verify=False, timeout=args.timeout)
    client = OpenAI(
        api_key=key,
        base_url=base_url,
        timeout=args.timeout,
        max_retries=0,
        http_client=http_client,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.output_dir / "results.jsonl"
    lock = threading.Lock()
    status_counts: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                generate_with_claim, client, model, row, args.output_dir,
                args.max_tokens, args.enable_thinking, not args.no_stream,
                args.wire_api, args.actor_authorization, args.provider_label,
                args.max_attempts, args.retry_backoff_seconds, args.claim_stale_seconds,
            )
            for row in rows
        ]
        for completed, future in enumerate(as_completed(futures), 1):
            result = future.result()
            status_counts[result["status"]] += 1
            if result["status"] != "skipped":
                append_result(result_path, result, lock)
            print(json.dumps({"progress": f"{completed}/{len(futures)}", **result}, ensure_ascii=False), flush=True)
    print(json.dumps({"batch_status_counts": dict(sorted(status_counts.items()))}, ensure_ascii=False), flush=True)
    http_client.close()
    raise SystemExit(batch_exit_code(status_counts))


if __name__ == "__main__":
    main()
