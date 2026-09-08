"""Build reviewed Seed pools and generate linear multi-round Edit queries."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit

from instruction_augmentation.doc_api import DocApiClient
from instruction_augmentation.production import parse_json_object
from instruction_augmentation.transfer_evidence import RankedEffect


DISALLOWED_ORIGINAL_ISSUES = {
    "blank_or_shell",
    "broken_resource",
    "build_or_entry_missing",
    "console_error",
    "interaction_broken",
    "layout_overflow",
    "missing_required_feature",
}
MIN_EDIT_COUNT = 4
MAX_EDIT_COUNT = 12
DEFAULT_EDIT_COUNT = 10
# Public default retained for existing imports.
EDIT_COUNT = DEFAULT_EDIT_COUNT
TARGET_MIN_INSTRUCTION_WORDS = 80
TARGET_MAX_INSTRUCTION_WORDS = 120
MIN_INSTRUCTION_WORDS = 75
MAX_INSTRUCTION_WORDS = 125
MIN_INSTRUCTION_SENTENCES = 4
MAX_INSTRUCTION_SENTENCES = 8
_PUBLIC_WEB_API_IDENTIFIERS = frozenset({"localStorage", "sessionStorage"})
_OPENING_VERB_ALTERNATIVES = (
    "Introduce",
    "Create",
    "Provide",
    "Build",
    "Design",
    "Implement",
    "Develop",
    "Extend",
)

GENERATION_SYSTEM = """You produce incremental Edit instructions for an existing local frontend project.
The main output is the instructions, not code. Return the requested 4 to 12 Edits in one linear page-version
history: q1 edits s0 into s1, q2 edits s1 into s2, and qN edits s(N-1) into sN. Never create sibling or branch
sources. Some later Edits must consume state introduced by earlier Edits, but not every Edit should do so. Follow
the exact dependency and origin-count limits in the task.
A real dependency means a later user-visible result reads a named state produced by an earlier Edit. Sharing a
screen, style, file, or component is not a dependency. Each instruction must fit the host product, be possible
with existing local data, avoid backends and remote services, and describe an observable user-facing change.
Keep every regression constraint in the preserve metadata. Do not use generic phrases such as preserve existing,
keep current, remain unchanged, continue to work, or without affecting in the natural instruction. Across the whole
sequence, at most one instruction may name one concrete coexistence condition, and only when omitting it would make
the requested product behavior ambiguous. Retrieved cards may describe functionality, interaction rules, responsive layout,
visual organization, or accessibility. Retrieved cards must not crowd out natural host product gaps. Do not mention selectors, source code,
donors, datasets, benchmarks, state graphs, or internal
state names inside the natural-language instruction. Every Edit must add a visible change in that same step; this may
be a user capability or a concrete visual, responsive, or accessibility improvement. An internal refactor, hidden
event store, or state-management change is not sufficient. Do not duplicate a control or behavior already present in
the browser evidence. Treat every recorded action transition
as an existing behavior, and treat a matching visible control as likely implemented unless the proposed Edit adds a
materially different user result. The source_gap explanation must name the missing result, not merely restate the request.
An action that changes active_element or scroll_position already implements focus or jump-to-content behavior even
when no new text appears; do not propose the same user goal through a differently placed control.
Only claim that an existing control lacks behavior when browser evidence actually exercised that control and observed
no relevant result. A control that appears in a desktop or mobile snapshot but was not exercised is unknown, not a
confirmed gap; choose another module instead of proposing the same visible control.
Do not call a validation rule, state, message, or behavior "existing" unless it appears in the supplied source facts.
Do not claim that ordinary browser code can detect hardware facts such as exact RAM, GPU VRAM, disk capacity, installed
drivers, or connection speed. Use an explicit local simulation or user-provided inputs when such a feature is natural.
A field or label observed only once at page, topic, or section level must not be treated as a per-item attribute;
only propose filtering, grouping, comparison, or aggregation by that field when browser evidence shows the field on
the relevant records. A new control, placement, or visual treatment is not a new capability when the source already
completes the same user goal with the same meaningful state transition; choose a materially different result instead.
A singleton page, article, or product does not support a multi-item list, catalog, history, or cross-item navigation
feature unless source facts or a named earlier Edit provide the additional records. Every control, setting, field, and
state named as already available must be traceable to source facts or a declared earlier producer.
A new structured state
must have a visible surface such as history, saved items, staged changes, a summary, or a restorable view. Treat a
control as decorative unless the source evidence includes the local objects needed for its result: do not invent
unseen pagination pages, records, routes, inventory, accounts, or server responses. Use a retrieved card when its
object-action-state pattern maps to Host base objects, a named earlier output, or UI/state created inside the same
frozen feature module; donor names, route names, frameworks, and business domains do not need to match. If a natural later feature needs a missing local
prerequisite, add that prerequisite as an earlier host-grounded Edit with its own visible user value, then depend on
it. Write every instruction as one complete feature module rather than one isolated button or cosmetic sentence. The
instruction must stand alone for an implementation model: identify its location and host objects, describe the full
user path and resulting visible states, and include only the feedback and edge behavior that belongs to that product
goal. Keep naturally inseparable parts together;
for example, search, result count, no-results feedback, and reset belong in one search module instead of four Edits.
Search, category or date filters, sorting, result count, no-results feedback, and reset that all transform the same
result surface are one discovery module, not a chain of separate Edit instructions. Build dependencies from richer
downstream uses of that combined result state, such as a saved view or summary, rather than manufacturing a chain
between its individual controls.
Completeness is task-specific, not a checklist. Do not automatically append empty, error, loading, persistence,
responsive, keyboard, accessibility, or preservation clauses. Add one only when it changes how this particular
feature must work. Never repeat the same quality-assurance ending across the sequence. Do not pad instructions with
generic quality claims, and do not move user-visible requirements only into acceptance metadata. Use varied direct
opening verbs. Do not mention q numbers, an "earlier Edit", or an "earlier feature" in an
instruction; refer to the product capability or visible state itself. For every Edit, state why the source cannot already complete the goal, why the goal fits the product, why a user
benefits, and what evidence supports every required state. When depends_on contains qK, copy the corresponding
produces[].state string from qK character for character into requires[].state and set requires[].source to qK; never
paraphrase that state name. Do not reinterpret an existing status label when its product meaning is ambiguous.
Every independent Edit must include at least one requires entry sourced from seed browser evidence. A dependent Edit
must visibly read or transform data/state produced by its declared predecessors; merely opening, documenting, or
adding a shortcut to an earlier control is not a dependency. Make that consumption visible in the instruction without
using q numbers.
Before writing the JSON, silently plan the requested number of module-sized changes and merge any items that are
normally one feature. Reject a candidate whose real implementation is only one isolated click handler, toggle, label,
or cosmetic property and whose remaining sentences would be generic quality clauses; merge it with a coherent larger
workflow or choose a richer candidate instead. For a functional module, identify the host-specific business objects
and their relevant fields or relationships, the user's multi-step path, the meaningful state transitions, and the
visible surfaces that must stay synchronized. For a visual, style, information-organization, or responsive module,
identify the exact page regions, hierarchy, typography, spacing, color, motion, and breakpoint behavior that actually
change; do not invent storage or empty states merely to make it sound complete. Across the sequence, use the host
evidence to vary product workflows, information presentation, visual treatment, responsive structure, navigation,
and direct manipulation instead of producing many versions of a control plus localStorage. Use concrete host labels,
data fields, roles, categories, and visual characteristics wherever the evidence supports them. Word count is
guidance, not a correctness boundary: choose a complete useful module and describe it precisely without padding.
Do not copy example domains, wording, or labels from the prompt.
Do not use a skip link, back-to-top button, theme toggle or color-theme switcher, guided tour or onboarding overlay,
reading-progress bar, character counter, or shortcut overlay
as a standalone Edit merely to fill the sequence. Such utilities are acceptable only as an inseparable part of a
broader host-specific navigation, reading, form, or personalization workflow with multiple synchronized results.
Output one JSON object and no commentary."""

WEBCOMPASS_EDIT_TYPES = (
    'Data Table', 'Rich Text Editor', 'Drag & Drop Interface', 'Tree View',
    'Real-time Dashboard', 'Infinite Scroll', 'Async Form Validation',
    'File Upload with Progress', 'Parallax Scrolling', 'Page Transitions',
    'Particle Effects', 'Skeleton Loading', 'Shopping Cart', 'User Authentication',
    'Multi-step Wizard', 'Notification Center',
)
WEBCOMPASS_EDIT_POLICY = (
    '\nEvery Edit must be a complete, coherent user task whose core capability is semantically close to '
    'one of these WebCompass Edit families: ' + '; '.join(WEBCOMPASS_EDIT_TYPES) + '. '
    'Domain-specific adaptations are encouraged; matching a label or mentioning a component is insufficient. '
    'Match the core behavior and task granularity, not exact benchmark wording. Do not split one complete '
    'workflow into isolated buttons, handlers, saves, exports, or cosmetic properties to fill a chain. '
    'Choose the complete capability before its helper actions: saving and restoring are usually parts of '
    'one owning task, not two tasks. Explain the chosen family through actual behavior in the goal. '
    'Core-behavior guide (adapt to Host, not a mandatory checklist): Data Table coordinates tabular record '
    'operations; Rich Text Editor supports formatting, selection and editing; Drag & Drop moves objects '
    'between meaningful positions or containers; Tree View navigates expandable hierarchies; Real-time '
    'Dashboard updates related metrics/charts over time; Infinite Scroll progressively loads more items; '
    'Async Form Validation handles pending, valid and invalid field states without stale-response races; '
    'File Upload with Progress manages files, progress and cancellation/recovery; Parallax Scrolling '
    'coordinates layered movement; Page Transitions coordinates outgoing/incoming page states; Particle '
    'Effects animates an interactive particle system; Skeleton Loading presents layout-matched placeholders '
    'and a controlled content transition; Shopping Cart manages line items, quantities and totals; User '
    'Authentication covers sign-in/out and session-dependent UI; Multi-step Wizard handles steps, validation '
    'and completion; Notification Center manages an event inbox, unread/read state and notification actions. '
    'A visual task can be complete without a multi-step form: specify its region, trigger, transition, and '
    'result. A data-table task should describe coordinated record operations; a wizard should describe '
    'steps, validation, navigation, and completion. Never force backend availability or unrelated features '
    'onto the Host. Broad inspiration may supply details, but each final task needs a meaningful family fit. '
    'If no complete fitting task exists, reject it rather than relabeling an unrelated utility.\n'
    'CAPABILITY DEPTH: Family resemblance, full-task completeness, and observable acceptance are separate '
    'judgments. Aim for the coordinated interaction depth of substantive official tasks, not merely the '
    'simplest example that can carry a family name. Specify which operations share state, what changes '
    'after an action or time event, and how the user observes and revises the result. A collection of '
    'unrelated controls, extra words, or generic quality clauses cannot substitute for those relationships. '
    'The following are reference patterns, not a requirement to include every listed feature in every task. '
    'Choose a coherent Host-appropriate combination with comparable depth, and explain any simpler choice.\n'
    'Tree View: beyond expand/collapse and jumping to a leaf, define meaningful hierarchy-state interaction. '
    'Reference patterns include parent selection propagating to descendants with partial-selection feedback, '
    'and search revealing matching descendants through their ancestor path while preserving useful expansion '
    'or selection state when cleared. Specify the relationship between node actions and the selected/result '
    'surface. A bare expandable directory with focus highlighting alone is a shallow navigation variant, '
    'not sufficient depth for this generation target. Do not add irrelevant checkbox operations just to qualify.\n'
    'Rich Text Editor: define real selection/block editing with an explicit toolbar repertoire, including '
    'appropriate inline formatting and structured content such as headings, lists, quotes, or links/media. '
    'Explain how toolbar/dialog actions retain the intended selection and how the edited document synchronizes '
    'with preview and saved/reopened or submitted structured content. Heading/emphasis plus a preview alone '
    'is a shallow variant. A plain textarea with decorative buttons or unsaved visual formatting fails the '
    'core capability. Choose formats that serve the product rather than reproducing all toolbar options.\n'
    'Real-time Dashboard: name the changing quantities, the event or time-driven data source, and the '
    'consistent update rule for metrics and related charts with refresh status/time. Local user events or '
    'explicitly simulated data are valid; existing historical facts must not be fabricated as changing. '
    'A static statistics panel plus an appended activity log is not sufficient: the measures and their '
    'visualization themselves must update coherently. Unrelated random counters and charts also fail.\n'
    'For every family, describe necessary intermediate and recovery states in its own user workflow, '
    'rather than imposing identical failure/empty/persistence requirements on all visual and functional '
    'tasks. New local UI and state may be introduced inside the task; never misrepresent them as existing '
    'Host facts or invent external services. Several partial inspiration cards may jointly support one '
    'complete task. Establish this depth in the goal before freezing the plan.\n'
)
GENERATION_SYSTEM += WEBCOMPASS_EDIT_POLICY

AUDIT_SYSTEM = """You independently audit candidate Edit instructions for one existing frontend.
Judge what the supplied source and browser evidence actually support. Check source grounding, novelty versus current
behavior, product naturalness, instruction specificity, local-only feasibility, preservation of prior behavior, and
whether every claimed dependency really consumes an earlier produced state. Do not reward terminology or complex
names. Reject an Edit that is generic, already present, requires an unstated backend, invents unavailable business
objects, or claims a dependency based only on shared UI. Inspect undeclared actual state consumption and whether
instructions add behavior outside the supplied module_plan. Naming a control solely to hide or preserve it does
not establish a dependency. Length and lexical-overlap review_notes are hints, never verdicts; a concise complete
feature can pass and a padded micro-feature must fail. Source versions must remain one linear s0->s1->...->sN history.
This audit evaluates candidate instructions only; it must not claim target code exists. Output one JSON object.""" + WEBCOMPASS_EDIT_POLICY


def _validate_edit_count(edit_count: int) -> int:
    if not MIN_EDIT_COUNT <= edit_count <= MAX_EDIT_COUNT:
        raise ValueError(
            f"edit_count must be from {MIN_EDIT_COUNT} to {MAX_EDIT_COUNT}"
        )
    return edit_count


def _dependency_limits(edit_count: int) -> tuple[int, int]:
    _validate_edit_count(edit_count)
    return 1, min(3, (edit_count + 1) // 2)


def _minimum_later_independent_edits(edit_count: int) -> int:
    _validate_edit_count(edit_count)
    return 1 if edit_count < 6 else 2


def _max_donor_edits(edit_count: int) -> int:
    _validate_edit_count(edit_count)
    return (edit_count * 3) // 5


def _minimum_retrieved_edits(edit_count: int) -> int:
    _validate_edit_count(edit_count)
    return 1 if edit_count < 6 else 2


def normalize_repeated_instruction_openings(
    payload: dict[str, Any], *, maximum_per_verb: int = 2
) -> dict[str, Any]:
    """Vary repeated opening verbs without changing the requested behavior."""

    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    rows = normalized.get("edits")
    if not isinstance(rows, list):
        return normalized
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("instruction"), str):
            continue
        instruction = row["instruction"]
        opening = re.match(r"([A-Za-z]+)(\b.*)", instruction, re.DOTALL)
        if opening is None:
            continue
        verb = opening.group(1).lower()
        if counts.get(verb, 0) < maximum_per_verb:
            counts[verb] = counts.get(verb, 0) + 1
            continue
        replacement = next(
            (
                candidate
                for candidate in _OPENING_VERB_ALTERNATIVES
                if counts.get(candidate.lower(), 0) < maximum_per_verb
            ),
            None,
        )
        if replacement is None:
            continue
        row["instruction"] = replacement + opening.group(2)
        original_opening = opening.group(1)
        for collection_name in ("dependency_evidence", "new_values"):
            collection = row.get(collection_name)
            if not isinstance(collection, list):
                continue
            for evidence in collection:
                if not isinstance(evidence, dict):
                    continue
                phrase = evidence.get("instruction_evidence")
                if isinstance(phrase, str) and re.match(
                    rf"^{re.escape(original_opening)}\b", phrase
                ):
                    evidence["instruction_evidence"] = re.sub(
                        rf"^{re.escape(original_opening)}\b",
                        replacement,
                        phrase,
                        count=1,
                    )
        counts[replacement.lower()] = counts.get(replacement.lower(), 0) + 1
    return normalized


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _safe_relative_path(value: str) -> str:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError(f"unsafe project path: {value}")
    return candidate.as_posix()


def files_from_generate_record(record: dict[str, Any]) -> dict[str, str]:
    rows = record.get("response")
    if not isinstance(rows, list) or not rows:
        raise ValueError("generate record requires response files")
    files: dict[str, str] = {}
    for row in rows:
        path = _safe_relative_path(str(row.get("path", "")))
        code = row.get("code")
        if not isinstance(code, str):
            raise ValueError(f"generate file requires code: {path}")
        if path in files:
            raise ValueError(f"duplicate project path: {path}")
        files[path] = code
    if "index.html" not in files:
        raise ValueError("Seed requires index.html")
    return files


def apply_exact_patches(
    files: dict[str, str], patches: Iterable[dict[str, Any]]
) -> dict[str, str]:
    result = dict(files)
    for patch in patches:
        path = _safe_relative_path(str(patch.get("path", "")))
        if path not in result:
            raise ValueError(f"patch path is missing: {path}")
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(search, str) or not search:
            raise ValueError(f"patch search is empty: {path}")
        if not isinstance(replace, str):
            raise ValueError(f"patch replace is invalid: {path}")
        count = result[path].count(search)
        if count != 1:
            raise ValueError(f"patch search must occur exactly once in {path}; found {count}")
        result[path] = result[path].replace(search, replace, 1)
    return result


def files_from_repaired_record(record: dict[str, Any]) -> dict[str, str]:
    input_rows = record.get("input_files")
    if not isinstance(input_rows, list) or not input_rows:
        raise ValueError("repair record requires input_files")
    files: dict[str, str] = {}
    for row in input_rows:
        path = _safe_relative_path(str(row.get("path", "")))
        code = row.get("code")
        if not isinstance(code, str):
            raise ValueError(f"repair input requires code: {path}")
        files[path] = code
    files = apply_exact_patches(files, record.get("response", []))
    if "index.html" not in files:
        raise ValueError("Seed requires index.html")
    return files


def _original_is_eligible(review: dict[str, Any]) -> bool:
    issues = {str(value) for value in review.get("issues", [])}
    return bool(
        review.get("hard_gate_pass") is True
        and review.get("grade") in {"A", "B"}
        and not issues.intersection(DISALLOWED_ORIGINAL_ISSUES)
    )


def _supplement_is_eligible(audit: dict[str, Any]) -> bool:
    return bool(
        audit.get("status") == "ok"
        and isinstance(audit.get("output_duplicate_groups"), list)
        and not audit["output_duplicate_groups"]
    )


def build_seed_pool(
    *,
    original_records: Iterable[dict[str, Any]],
    original_reviews: Iterable[dict[str, Any]],
    supplement_records: Iterable[dict[str, Any]],
    supplement_audits: Iterable[dict[str, Any]],
    original_count: int,
    supplement_count: int,
    selection_seed: int,
) -> list[dict[str, Any]]:
    if original_count < 1 or supplement_count < 1:
        raise ValueError("both source datasets require a positive candidate count")
    original_by_id = {str(row["instance_id"]): row for row in original_records}
    review_by_id = {str(row["instance_id"]): row for row in original_reviews}
    eligible_original_ids = sorted(
        instance_id
        for instance_id, review in review_by_id.items()
        if _original_is_eligible(review) and instance_id in original_by_id
    )
    if len(eligible_original_ids) < original_count:
        raise ValueError(
            f"only {len(eligible_original_ids)} reviewed 0805 Seeds for {original_count} requested"
        )
    selected_original_ids = random.Random(selection_seed).sample(
        eligible_original_ids, original_count
    )

    supplement_by_id = {str(row["instance_id"]): row for row in supplement_records}
    audit_by_id = {str(row["instance_id"]): row for row in supplement_audits}
    eligible_supplement_ids = sorted(
        instance_id
        for instance_id, audit in audit_by_id.items()
        if _supplement_is_eligible(audit) and instance_id in supplement_by_id
    )
    if len(eligible_supplement_ids) < supplement_count:
        raise ValueError(
            f"only {len(eligible_supplement_ids)} reviewed supplement Seeds for "
            f"{supplement_count} requested"
        )
    selected_supplement_ids = random.Random(selection_seed + 1).sample(
        eligible_supplement_ids, supplement_count
    )

    pool: list[dict[str, Any]] = []
    for instance_id in selected_original_ids:
        record = original_by_id[instance_id]
        review = review_by_id[instance_id]
        pool.append(
            {
                "seed_id": f"0805__{instance_id}",
                "dataset": "0805",
                "source_instance_id": instance_id,
                "original_instruction": str(record.get("instruction", "")),
                "page_type": str(record.get("page_type", "")),
                "files": files_from_generate_record(record),
                "prior_quality_evidence": {
                    "kind": "generate_manual_review_20260813",
                    "hard_gate_pass": True,
                    "grade": review["grade"],
                    "total_score": review.get("total_score"),
                    "issues": review.get("issues", []),
                },
                "source_metadata": record.get("metadata", {}),
            }
        )
    for instance_id in selected_supplement_ids:
        record = supplement_by_id[instance_id]
        audit = audit_by_id[instance_id]
        pool.append(
            {
                "seed_id": f"0805supplement__{instance_id}",
                "dataset": "0805supplement",
                "source_instance_id": instance_id,
                "original_instruction": str(record.get("instruction", "")),
                "page_type": str(record.get("page_type", "")),
                "files": files_from_repaired_record(record),
                "prior_quality_evidence": {
                    "kind": "repair_clean_browser_rerender_20260823",
                    "status": audit["status"],
                    "route_kind": audit.get("route_kind"),
                    "output_duplicate_groups": audit["output_duplicate_groups"],
                    "patch_count": audit.get("patch_count"),
                },
                "source_metadata": record.get("metadata", {}),
            }
        )
    pool.sort(key=lambda row: row["seed_id"])
    if len({row["seed_id"] for row in pool}) != len(pool):
        raise ValueError("candidate Seed ids are not unique")
    return pool


def choose_sample(
    pool: Iterable[dict[str, Any]], *, sample_count: int, selection_seed: int
) -> list[dict[str, Any]]:
    candidates = sorted(pool, key=lambda row: str(row["seed_id"]))
    if sample_count < 1 or sample_count > len(candidates):
        raise ValueError("sample_count is outside the candidate pool")
    sampled = random.Random(selection_seed).sample(candidates, sample_count)
    return [{**row, "sample_index": index} for index, row in enumerate(sampled, 1)]


def materialize_seed(seed: dict[str, Any], directory: Path) -> None:
    files = seed.get("files")
    if not isinstance(files, dict) or "index.html" not in files:
        raise ValueError("candidate Seed has no index.html")
    directory.mkdir(parents=True, exist_ok=True)
    for relative, content in sorted(files.items()):
        path = directory / _safe_relative_path(str(relative))
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = str(content)
        if path.exists():
            if path.read_text(encoding="utf-8") != rendered:
                raise ValueError(f"immutable Seed file differs: {path}")
            continue
        path.write_text(rendered, encoding="utf-8")


def source_context(files: dict[str, str]) -> str:
    return "\n\n".join(
        f"<<<FILE:{name}>>>\n{content}\n<<<END_FILE>>>"
        for name, content in sorted(files.items())
    )


def compact_browser_evidence(observation: dict[str, Any]) -> dict[str, Any]:
    baseline = observation.get("baseline", {})
    def compact_state(state_id: str, snapshot: dict[str, Any], action: Any = None) -> dict[str, Any]:
        dom_html = str(snapshot.get("html", ""))
        aria_snapshot = str(snapshot.get("aria_snapshot", ""))
        visible_text = str(snapshot.get("visible_text", ""))
        interactive = snapshot.get("interactive")
        if not isinstance(interactive, list):
            interactive = []
        return {
            "state_id": state_id,
            "state_sha256": snapshot.get("state_sha256"),
            "url": snapshot.get("url"),
            "title": snapshot.get("title"),
            "action": action,
            "dom_html": _bounded_text(dom_html, 12000),
            "dom_html_length": snapshot.get("html_length", len(dom_html)),
            "dom_html_truncated_for_prompt": len(dom_html) > 12000
            or bool(snapshot.get("html_truncated")),
            "aria_snapshot": _bounded_text(aria_snapshot, 7000),
            "aria_snapshot_truncated_for_prompt": len(aria_snapshot) > 7000,
            "visible_text": _bounded_text(visible_text, 5000),
            "visible_text_truncated_for_prompt": len(visible_text) > 5000,
            "interactive": interactive,
            "interactive_total": len(interactive),
            "visual_surfaces": (
                snapshot.get("visual_surfaces", [])
                if isinstance(snapshot.get("visual_surfaces"), list)
                else []
            ),
            "style_samples": (
                snapshot.get("style_samples", [])
                if isinstance(snapshot.get("style_samples"), list)
                else []
            ),
            "local_storage": snapshot.get("local_storage"),
            "session_storage": snapshot.get("session_storage"),
            "viewport": snapshot.get("viewport"),
            "landmark_layouts": (
                snapshot.get("landmark_layouts", [])
                if isinstance(snapshot.get("landmark_layouts"), list)
                else []
            ),
            "aria_states": (
                snapshot.get("aria_states", [])
                if isinstance(snapshot.get("aria_states"), list)
                else []
            ),
            "focusable_order": (
                snapshot.get("focusable_order", [])
                if isinstance(snapshot.get("focusable_order"), list)
                else []
            ),
            "root_css_variables": snapshot.get("root_css_variables", {}),
        }

    baseline_state = compact_state("baseline", baseline)
    states: list[dict[str, Any]] = []
    seen = {str(baseline.get("state_sha256") or "baseline")}
    mobile_baseline = observation.get("mobile_baseline")
    mobile_state = None
    if isinstance(mobile_baseline, dict):
        mobile_signature = str(
            mobile_baseline.get("state_sha256") or "mobile_baseline"
        )
        if mobile_signature not in seen:
            seen.add(mobile_signature)
            mobile_state = compact_state("mobile_baseline", mobile_baseline)
    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict):
            continue
        path_id = str(path.get("id", "path"))
        for index, step in enumerate(path.get("steps", []), 1):
            if not isinstance(step, dict) or not isinstance(step.get("state"), dict):
                continue
            snapshot = step["state"]
            signature = str(snapshot.get("state_sha256") or f"{path_id}-{index}")
            if signature in seen:
                continue
            seen.add(signature)
            states.append(
                compact_state(
                    f"{path_id}__step_{index}", snapshot, action=step.get("action")
                )
            )
            if step.get("dialogs"):
                states[-1]["dialogs"] = step["dialogs"]
    return {
        "status": observation.get("status"),
        "baseline": baseline_state,
        "mobile_baseline": mobile_state,
        "states": states,
        "structures": (
            baseline.get("structures", [])
            if isinstance(baseline.get("structures"), list)
            else []
        ),
        "horizontal_overflow": baseline.get("horizontal_overflow"),
        "remote_requests": observation.get("remote_requests", []),
        "console_errors": observation.get("console_errors", []),
        "page_errors": observation.get("page_errors", []),
        "dialog_events": observation.get("dialog_events", []),
        "visual_routing": observation.get("visual_routing", {}),
    }


_CONTROL_FIELDS = (
    "selector",
    "tag",
    "role",
    "type",
    "text",
    "aria_label",
    "name",
    "href",
    "data_action",
    "data_command",
    "value",
    "checked",
    "disabled",
    "visible",
    "horizontally_reachable",
    "draggable",
    "tabindex",
    "title",
)


def _bounded_text(value: Any, limit: int) -> str:
    rendered = str(value or "").strip()
    if len(rendered) <= limit:
        return rendered
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    marker = f"\n[middle omitted; sha256={digest}]\n"
    remaining = max(2, limit - len(marker))
    prefix_length = remaining // 2
    suffix_length = remaining - prefix_length
    return rendered[:prefix_length] + marker + rendered[-suffix_length:]


def _browser_url_without_local_port(value: Any) -> str:
    rendered = str(value or "")
    parsed = urlsplit(rendered)
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        return parsed.path + (f"?{parsed.query}" if parsed.query else "") + (
            f"#{parsed.fragment}" if parsed.fragment else ""
        )
    return rendered


def _compact_control(row: Any, *, include_selector: bool) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return {
        key: (
            row.get(key)
            if key == "selector"
            else _bounded_text(row.get(key), 240)
            if isinstance(row.get(key), str)
            else row.get(key)
        )
        for key in _CONTROL_FIELDS
        if (include_selector or key != "selector")
        and row.get(key) not in (None, "", [], {})
    }


def _compact_active_element(value: Any, *, include_selector: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    tag = str(value.get("tag") or "")
    return {
        key: (
            _bounded_text(item, 240)
            if isinstance(item, str) and key != "selector"
            else item
        )
        for key, item in value.items()
        if key != "rect"
        and (include_selector or key != "selector")
        and item not in (None, "", [], {})
        and not (key == "text" and tag in {"body", "html"})
    }


def _compact_scroll_position(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: int(value[key])
        for key in ("x", "y")
        if isinstance(value.get(key), (int, float))
    }


def _compact_browser_action(
    value: Any, *, before: dict[str, Any], include_selectors: bool
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if include_selectors:
        return dict(value)
    compact = {
        str(key): item
        for key, item in value.items()
        if key not in {"selector", "target_selector"}
        and item not in (None, "", [], {})
    }
    controls = [
        row for row in before.get("interactive", []) if isinstance(row, dict)
    ]
    by_selector = {
        str(row.get("selector")): row for row in controls if row.get("selector")
    }
    source = by_selector.get(str(value.get("selector") or ""))
    if source is not None:
        compact["control"] = _compact_control(source, include_selector=False)
    target = by_selector.get(str(value.get("target_selector") or ""))
    if target is not None:
        compact["target_control"] = _compact_control(
            target, include_selector=False
        )
    return compact


def _compact_fact_rows(value: Any, *, limit: int | None = None) -> list[Any]:
    """Compact every browser row and remove exact duplicates.

    ``limit`` remains accepted for older callers, but is deliberately ignored:
    model-facing evidence must not depend on DOM order or a front-N prefix.
    """

    rows = value if isinstance(value, list) else []
    compacted: list[Any] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            compact = _bounded_text(row, 240)
            signature = json.dumps(compact, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                compacted.append(compact)
            continue
        compact = {
            str(key): _bounded_text(item, 240)
            if isinstance(item, str) and key != "selector"
            else item
            for key, item in row.items()
            if item not in (None, "", [], {})
        }
        signature = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        if signature not in seen:
            seen.add(signature)
            compacted.append(compact)
    return compacted


def _summarize_all_strings(
    values: Iterable[Any], *, sample_count: int = 12, value_limit: int = 240
) -> dict[str, Any]:
    full_unique = sorted({str(value) for value in values if value not in (None, "")})
    compact_unique = [_bounded_text(value, value_limit) for value in full_unique]
    if len(full_unique) <= sample_count:
        return {"values": compact_unique}
    serialized = json.dumps(full_unique, ensure_ascii=False, separators=(",", ":"))
    if sample_count == 1:
        samples = [compact_unique[len(compact_unique) // 2]]
    else:
        indices = sorted(
            {
                round(index * (len(compact_unique) - 1) / (sample_count - 1))
                for index in range(sample_count)
            }
        )
        samples = [compact_unique[index] for index in indices]
    return {
        "unique_count": len(full_unique),
        "coverage_samples": samples,
        "all_values_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _summarize_fact_collection(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        pattern = {
            str(key): _bounded_text(value, 240) if isinstance(value, str) else value
            for key, value in row.items()
            if key != "selector" and value not in (None, "", [], {})
        }
        signature = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
        group = groups.setdefault(
            signature, {"pattern": pattern, "count": 0, "selectors": []}
        )
        group["count"] += 1
        if row.get("selector") not in (None, ""):
            group["selectors"].append(str(row["selector"]))
    summarized: list[dict[str, Any]] = []
    for signature in sorted(groups):
        group = groups[signature]
        summarized.append(
            {
                "pattern": group["pattern"],
                "count": group["count"],
                **(
                    {"selectors": _summarize_all_strings(group["selectors"])}
                    if group["selectors"]
                    else {}
                ),
            }
        )
    return summarized


def _flatten_compact_facts(value: Any, *, prefix: str = "") -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, item in sorted(value.items(), key=lambda row: str(row[0])):
            child = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_compact_facts(item, prefix=child))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_flatten_compact_facts(item, prefix=prefix))
    elif value not in (None, ""):
        rows.append(f"{prefix}={_bounded_text(value, 180)}")
    return rows


def _nested_fact_coverage(value: Any, *, sample_count: int = 16) -> dict[str, Any]:
    unique = sorted(set(_flatten_compact_facts(value)))
    return {
        "fact_count": len(unique),
        "facts": _summarize_all_strings(unique, sample_count=sample_count),
    }


def _fact_rows_delta(before: Any, after: Any) -> dict[str, Any]:
    """Compare every inspector row and group equivalent field changes."""

    before_rows = [row for row in before if isinstance(row, dict)] if isinstance(before, list) else []
    after_rows = [row for row in after if isinstance(row, dict)] if isinstance(after, list) else []

    def identity(row: dict[str, Any]) -> str:
        selector = row.get("selector")
        if selector not in (None, ""):
            return f"selector:{selector}"
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    before_map = {identity(row): row for row in before_rows}
    after_map = {identity(row): row for row in after_rows}
    added = _summarize_fact_collection(
        after_map[key] for key in sorted(after_map.keys() - before_map.keys())
    )
    removed = _summarize_fact_collection(
        before_map[key] for key in sorted(before_map.keys() - after_map.keys())
    )
    grouped: dict[str, dict[str, Any]] = {}
    for key in sorted(before_map.keys() & after_map.keys()):
        before_row = before_map[key]
        after_row = after_map[key]
        changes = {
            str(field): {
                "before": _bounded_text(before_row.get(field), 240),
                "after": _bounded_text(after_row.get(field), 240),
            }
            for field in sorted(set(before_row) | set(after_row))
            if field != "selector" and before_row.get(field) != after_row.get(field)
        }
        if not changes:
            continue
        signature = json.dumps(changes, ensure_ascii=False, sort_keys=True)
        group = grouped.setdefault(
            signature,
            {"changes": changes, "item_count": 0, "identities": []},
        )
        group["item_count"] += 1
        group["identities"].append(key)
    changed_groups: list[dict[str, Any]] = []
    for signature in sorted(grouped):
        group = grouped[signature]
        changed_groups.append(
            {
                "changes": group["changes"],
                "item_count": group["item_count"],
                "identities": _summarize_all_strings(group["identities"]),
            }
        )
    return {
        key: value
        for key, value in (
            ("added", added),
            ("removed", removed),
            ("changed_groups", changed_groups),
        )
        if value
    }


def _control_identity(row: dict[str, Any]) -> str:
    selector = row.get("selector")
    if isinstance(selector, str) and selector:
        return selector
    return json.dumps(
        {
            key: row.get(key)
            for key in (
                "tag", "role", "type", "text", "aria_label", "name", "href",
                "data_action", "data_command",
            )
            if row.get(key) not in (None, "")
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _summarize_control_collection(
    rows: Iterable[dict[str, Any]], *, include_selector: bool
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    value_fields = (
        "selector",
        "text",
        "aria_label",
        "name",
        "href",
        "data_action",
        "data_command",
        "value",
        "title",
        "options",
    )
    for row in rows:
        pattern = {
            key: row.get(key)
            for key in (
                "tag",
                "role",
                "type",
                "checked",
                "disabled",
                "visible",
                "horizontally_reachable",
                "draggable",
                "tabindex",
            )
            if row.get(key) not in (None, "", [], {})
        }
        signature = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
        group = groups.setdefault(
            signature,
            {
                "pattern": pattern,
                "count": 0,
                "values": {
                    field: []
                    for field in value_fields
                    if include_selector or field != "selector"
                },
            },
        )
        group["count"] += 1
        for field, values in group["values"].items():
            value = row.get(field)
            if value in (None, "", [], {}):
                continue
            values.append(
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
    summarized: list[dict[str, Any]] = []
    for signature in sorted(groups):
        group = groups[signature]
        values = {
            field: _summarize_all_strings(items)
            for field, items in group["values"].items()
            if items
        }
        summarized.append(
            {
                "pattern": group["pattern"],
                "count": group["count"],
                **({"observed_values": values} if values else {}),
            }
        )
    return summarized


def _summarize_structure_collection(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        pattern = {
            key: row.get(key)
            for key in ("tag", "role", "child_count")
            if row.get(key) not in (None, "", [], {})
        }
        signature = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
        group = groups.setdefault(
            signature,
            {
                "pattern": pattern,
                "count": 0,
                "values": {"id": [], "aria_label": [], "text": []},
            },
        )
        group["count"] += 1
        for field, values in group["values"].items():
            if row.get(field) not in (None, "", [], {}):
                values.append(row[field])
    summarized: list[dict[str, Any]] = []
    for signature in sorted(groups):
        group = groups[signature]
        values = {
            field: _summarize_all_strings(items)
            for field, items in group["values"].items()
            if items
        }
        summarized.append(
            {
                "pattern": group["pattern"],
                "count": group["count"],
                **({"observed_values": values} if values else {}),
            }
        )
    return summarized


def _compact_record_groups(value: Any) -> list[dict[str, Any]]:
    """Keep record scope and spread samples without treating section labels as item fields."""

    groups = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        records = [
            {
                "text": _bounded_text(row.get("text"), 500),
                "data": row.get("data", {}),
                "marker_fields": [
                    {
                        key: item.get(key)
                        for key in ("text", "data")
                        if item.get(key) not in (None, "", [], {})
                    }
                    for item in row.get("marker_fields", [])
                    if isinstance(item, dict)
                ],
            }
            for row in group.get("records", [])
            if isinstance(row, dict)
        ]
        signatures = [
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in records
        ]
        if len(records) <= 8:
            sampled_records: Any = records
        else:
            indices = sorted(
                {
                    round(index * (len(records) - 1) / 7)
                    for index in range(8)
                }
            )
            sampled_records = {
                "sampled_count": len(indices),
                "coverage_samples": [records[index] for index in indices],
                "all_records_sha256": hashlib.sha256(
                    json.dumps(signatures, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
        compacted.append(
            {
                key: group.get(key)
                for key in (
                    "item_tag",
                    "item_role",
                    "item_class_signature",
                    "item_count",
                )
                if group.get(key) not in (None, "", [], {})
            }
            | {"records": sampled_records}
        )
    return compacted


def _ordered_text_delta(before: Any, after: Any, *, limit: int) -> dict[str, str]:
    def rows(value: Any) -> list[str]:
        result: list[str] = []
        for line in str(value or "").splitlines():
            normalized = " ".join(line.split())
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    before_rows = rows(before)
    after_rows = rows(after)
    before_set = set(before_rows)
    after_set = set(after_rows)
    added = _bounded_text("\n".join(row for row in after_rows if row not in before_set), limit)
    removed = _bounded_text("\n".join(row for row in before_rows if row not in after_set), limit)
    return {
        key: value
        for key, value in (("added", added), ("removed", removed))
        if value
    }


def _mapping_delta(before: Any, after: Any) -> dict[str, Any]:
    before_map = before if isinstance(before, dict) else {}
    after_map = after if isinstance(after, dict) else {}
    changed: dict[str, Any] = {}
    for key in sorted(set(before_map) | set(after_map)):
        if before_map.get(key) == after_map.get(key):
            continue
        changed[str(key)] = {
            "before": _bounded_text(before_map.get(key), 500),
            "after": _bounded_text(after_map.get(key), 500),
        }
    return changed


def _controls_delta(
    before: Any, after: Any, *, include_selector: bool
) -> dict[str, list[Any]]:
    before_rows = [row for row in before if isinstance(row, dict)] if isinstance(before, list) else []
    after_rows = [row for row in after if isinstance(row, dict)] if isinstance(after, list) else []
    before_map = {_control_identity(row): row for row in before_rows}
    after_map = {_control_identity(row): row for row in after_rows}
    added = _summarize_control_collection(
        (after_map[key] for key in sorted(after_map.keys() - before_map.keys())),
        include_selector=include_selector,
    )
    removed = _summarize_control_collection(
        (before_map[key] for key in sorted(before_map.keys() - after_map.keys())),
        include_selector=include_selector,
    )
    changed_by_pattern: dict[str, dict[str, Any]] = {}
    for key in sorted(before_map.keys() & after_map.keys()):
        before_control = _compact_control(
            before_map[key], include_selector=include_selector
        )
        after_control = _compact_control(after_map[key], include_selector=include_selector)
        if before_control != after_control:
            before_pattern = {
                field: value for field, value in before_control.items() if field != "selector"
            }
            after_pattern = {
                field: value for field, value in after_control.items() if field != "selector"
            }
            signature = json.dumps(
                {"before": before_pattern, "after": after_pattern},
                ensure_ascii=False,
                sort_keys=True,
            )
            group = changed_by_pattern.setdefault(
                signature,
                {
                    "before": before_pattern,
                    "after": after_pattern,
                    "count": 0,
                    "identities": [],
                },
            )
            group["count"] += 1
            group["identities"].append(key)
    changed = [
        {
            "before": changed_by_pattern[signature]["before"],
            "after": changed_by_pattern[signature]["after"],
            "count": changed_by_pattern[signature]["count"],
            "identities": _summarize_all_strings(
                changed_by_pattern[signature]["identities"]
            ),
        }
        for signature in sorted(changed_by_pattern)
    ]
    return {
        key: value
        for key, value in (("added", added), ("removed", removed), ("changed", changed))
        if value
    }


def _compact_baseline_snapshot(
    snapshot: Any, *, include_selectors: bool
) -> dict[str, Any]:
    state = snapshot if isinstance(snapshot, dict) else {}
    interactive = state.get("interactive")
    if not isinstance(interactive, list):
        interactive = []
    structures = state.get("structures")
    if not isinstance(structures, list):
        structures = []
    return {
        "state_sha256": state.get("state_sha256"),
        "url": _browser_url_without_local_port(state.get("url")),
        "title": state.get("title"),
        "visible_text": _bounded_text(state.get("visible_text"), 1800),
        "accessibility_tree": _bounded_text(state.get("aria_snapshot"), 2000),
        "interactive_controls": _summarize_control_collection(
            (row for row in interactive if isinstance(row, dict)),
            include_selector=include_selectors,
        ),
        "interactive_control_total": len(interactive),
        "structures": _summarize_structure_collection(
            row for row in structures if isinstance(row, dict)
        ),
        "local_storage": state.get("local_storage", {}),
        "session_storage": state.get("session_storage", {}),
        "viewport": state.get("viewport"),
        "horizontal_overflow": state.get("horizontal_overflow"),
        "landmark_layouts": _summarize_fact_collection(
            row
            for row in state.get("landmark_layouts", [])
            if isinstance(row, dict)
        ),
        "aria_states": _summarize_fact_collection(
            row for row in state.get("aria_states", []) if isinstance(row, dict)
        ),
        "active_element": _compact_active_element(
            state.get("active_element"), include_selector=include_selectors
        ),
        "scroll_position": _compact_scroll_position(state.get("scroll_position")),
        "record_groups": _compact_record_groups(state.get("record_groups")),
        "visual_surfaces": _summarize_fact_collection(
            row for row in state.get("visual_surfaces", []) if isinstance(row, dict)
        ),
        "style_samples": _summarize_fact_collection(
            row for row in state.get("style_samples", []) if isinstance(row, dict)
        ),
        "root_css_variables": dict(
            (
                str(key),
                _bounded_text(value, 240) if isinstance(value, str) else value,
            )
            for key, value in sorted(
                (state.get("root_css_variables") or {}).items()
            )
        )
        if isinstance(state.get("root_css_variables"), dict)
        else {},
    }


def _compact_state_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    state_id: str,
    action: Any,
    dialogs: Any,
    include_selectors: bool,
) -> dict[str, Any]:
    control_delta = _controls_delta(
        before.get("interactive"),
        after.get("interactive"),
        include_selector=include_selectors,
    )
    if len(json.dumps(control_delta, ensure_ascii=False)) > 3500:
        control_delta = _nested_fact_coverage(control_delta, sample_count=20)
    delta = {
        "state_id": state_id,
        "state_sha256": after.get("state_sha256"),
        "action": _compact_browser_action(
            action, before=before, include_selectors=include_selectors
        ),
        "url_before": _browser_url_without_local_port(before.get("url")),
        "url_after": _browser_url_without_local_port(after.get("url")),
        "visible_text_delta": _ordered_text_delta(
            before.get("visible_text"), after.get("visible_text"), limit=600
        ),
        "accessibility_delta": _ordered_text_delta(
            before.get("aria_snapshot"), after.get("aria_snapshot"), limit=600
        ),
        "control_delta": control_delta,
        "local_storage_delta": _mapping_delta(
            before.get("local_storage"), after.get("local_storage")
        ),
        "session_storage_delta": _mapping_delta(
            before.get("session_storage"), after.get("session_storage")
        ),
        "active_element_before": _compact_active_element(
            before.get("active_element"), include_selector=include_selectors
        ),
        "active_element_after": _compact_active_element(
            after.get("active_element"), include_selector=include_selectors
        ),
        "scroll_position_before": _compact_scroll_position(
            before.get("scroll_position")
        ),
        "scroll_position_after": _compact_scroll_position(
            after.get("scroll_position")
        ),
        "dialogs": dialogs if isinstance(dialogs, list) else [],
    }
    if delta["active_element_before"] == delta["active_element_after"]:
        delta.pop("active_element_before")
        delta.pop("active_element_after")
    if delta["scroll_position_before"] == delta["scroll_position_after"]:
        delta.pop("scroll_position_before")
        delta.pop("scroll_position_after")
    for field in ("aria_states", "visual_surfaces", "style_samples"):
        before_value = before.get(field, [])
        after_value = after.get(field, [])
        if before_value != after_value:
            field_delta = _fact_rows_delta(before_value, after_value)
            if field_delta:
                if len(json.dumps(field_delta, ensure_ascii=False)) > 2400:
                    field_delta = _nested_fact_coverage(
                        field_delta, sample_count=16
                    )
                delta[f"{field}_delta"] = field_delta
    return {
        key: value
        for key, value in delta.items()
        if value not in (None, "", [], {}) and not (
            key == "url_before" and value == delta.get("url_after")
        )
    }


def _semantic_transition_delta(delta: dict[str, Any]) -> dict[str, Any] | None:
    """Drop animation-only noise while retaining every observed semantic change."""

    metadata = {"state_id", "state_sha256", "action", "url_before", "url_after"}
    changed_fields = set(delta) - metadata
    if changed_fields == {"style_samples_delta"} or not changed_fields:
        return None
    if "style_samples_delta" in changed_fields and len(changed_fields) > 1:
        delta = dict(delta)
        delta.pop("style_samples_delta", None)
    return delta


def compact_browser_evidence_for_llm(
    observation: dict[str, Any],
    *,
    include_known_selectors: bool = False,
    max_transition_states: int | None = None,
) -> dict[str, Any]:
    """Keep one baseline plus mechanical state deltas for low-cost semantic work.

    Complete DOM/AX snapshots remain on disk.  This model-facing view preserves
    observed actions, new/removed text, control changes, storage changes, URLs,
    dialogs, responsive facts, and visual routing without repeating the whole
    page after every action.
    """

    baseline = observation.get("baseline")
    if not isinstance(baseline, dict):
        baseline = {}
    payload: dict[str, Any] = {
        "status": observation.get("status"),
        "baseline": _compact_baseline_snapshot(
            baseline, include_selectors=include_known_selectors
        ),
        "transitions": [],
        "remote_requests": observation.get("remote_requests", []),
        "console_errors": observation.get("console_errors", []),
        "page_errors": observation.get("page_errors", []),
        "dialog_events": observation.get("dialog_events", []),
        "visual_routing": observation.get("visual_routing", {}),
        "state_delta_catalog": [],
    }
    mobile = observation.get("mobile_baseline")
    if isinstance(mobile, dict):
        payload["mobile_difference"] = {
            "viewport": mobile.get("viewport"),
            "horizontal_overflow": mobile.get("horizontal_overflow"),
            "visible_text_delta": _ordered_text_delta(
                baseline.get("visible_text"), mobile.get("visible_text"), limit=1000
            ),
            "accessibility_delta": _ordered_text_delta(
                baseline.get("aria_snapshot"), mobile.get("aria_snapshot"), limit=1000
            ),
            "control_delta": _controls_delta(
                baseline.get("interactive"),
                mobile.get("interactive"),
                include_selector=include_known_selectors,
            ),
            "landmark_layout_delta": _fact_rows_delta(
                baseline.get("landmark_layouts"), mobile.get("landmark_layouts")
            ),
            "visual_surface_delta": _fact_rows_delta(
                baseline.get("visual_surfaces"), mobile.get("visual_surfaces")
            ),
            "style_delta": _fact_rows_delta(
                baseline.get("style_samples"), mobile.get("style_samples")
            ),
        }
    if max_transition_states is not None and max_transition_states < 0:
        raise ValueError("max_transition_states must be non-negative or None")

    def at_transition_limit() -> bool:
        return (
            max_transition_states is not None
            and emitted >= max_transition_states
        )

    emitted = 0
    delta_ids: dict[str, str] = {}

    def catalog_delta(delta: dict[str, Any]) -> str:
        signature_payload = {
            key: value
            for key, value in delta.items()
            if key not in {"state_id", "state_sha256"}
        }
        signature = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
        existing = delta_ids.get(signature)
        if existing is not None:
            return existing
        delta_id = f"d{len(delta_ids) + 1}"
        delta_ids[signature] = delta_id
        payload["state_delta_catalog"].append({"delta_id": delta_id, **delta})
        return delta_id

    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict) or at_transition_limit():
            continue
        prior = path.get("before") if isinstance(path.get("before"), dict) else baseline
        path_row: dict[str, Any] = {
            "id": path.get("id"),
            "purpose": path.get("purpose"),
            "status": path.get("status"),
            "state_delta_refs": [],
        }
        steps = path.get("steps") if isinstance(path.get("steps"), list) else []
        for index, step in enumerate(steps, 1):
            if at_transition_limit():
                break
            if not isinstance(step, dict) or not isinstance(step.get("state"), dict):
                continue
            state = step["state"]
            delta = _semantic_transition_delta(
                _compact_state_delta(
                    prior,
                    state,
                    state_id=f"{path.get('id', 'path')}__step_{index}",
                    action=step.get("action"),
                    dialogs=step.get("dialogs"),
                    include_selectors=include_known_selectors,
                )
            )
            if delta is not None:
                path_row["state_delta_refs"].append(catalog_delta(delta))
                emitted += 1
            prior = state
        after = path.get("after") if isinstance(path.get("after"), dict) else None
        if (
            after is not None
            and not at_transition_limit()
            and after.get("state_sha256") != prior.get("state_sha256")
        ):
            delta = _semantic_transition_delta(
                _compact_state_delta(
                    prior,
                    after,
                    state_id=f"{path.get('id', 'path')}__after",
                    action={"action": "path_result"},
                    dialogs=[],
                    include_selectors=include_known_selectors,
                )
            )
            if delta is not None:
                path_row["state_delta_refs"].append(catalog_delta(delta))
                emitted += 1
        payload["transitions"].append(path_row)
    payload["transition_state_total"] = emitted
    payload["unique_state_delta_count"] = len(payload["state_delta_catalog"])
    if include_known_selectors:
        selectors: set[str] = set()
        snapshots: list[dict[str, Any]] = [baseline]
        if isinstance(mobile, dict):
            snapshots.append(mobile)
        for path in observation.get("exploration_paths", []):
            if not isinstance(path, dict):
                continue
            for step in path.get("steps", []):
                if isinstance(step, dict) and isinstance(step.get("state"), dict):
                    snapshots.append(step["state"])
            if isinstance(path.get("after"), dict):
                snapshots.append(path["after"])
        for snapshot in snapshots:
            for row in snapshot.get("interactive", []):
                if isinstance(row, dict) and isinstance(row.get("selector"), str):
                    selectors.add(row["selector"])
        payload["known_selectors"] = sorted(selectors)
    return payload


def _nonempty_string(value: Any, *, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _instruction_word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", value))


def _instruction_sentence_count(value: str) -> int:
    return len(
        [
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", value.strip())
            if sentence.strip()
        ]
    )


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if value is None and allow_empty:
        value = []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{label} must be a list")
    rows = [_nonempty_string(item, label=label) for item in value]
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label} contains duplicates")
    return rows


def _card_requirements(card: dict[str, Any]) -> list[str]:
    value = card.get("requires")
    if not isinstance(value, list):
        value = card.get("prerequisites")
    if not isinstance(value, list):
        value = []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_card_assessments(
    payload: dict[str, Any], hidden_cards: tuple[dict[str, Any], ...]
) -> tuple[list[dict[str, Any]], set[str]]:
    raw = payload.get("card_assessments", [])
    if not hidden_cards:
        if raw not in (None, []):
            raise ValueError("card_assessments require supplied retrieved cards")
        return [], set()
    if not isinstance(raw, list) or len(raw) != len(hidden_cards):
        raise ValueError("card_assessments must contain exactly one row per retrieved card")
    cards_by_id = {
        _nonempty_string(card.get("capability_id"), label="capability_id"): card
        for card in hidden_cards
    }
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    compatible_ids: set[str] = set()

    def canonical_card_id(value: Any) -> str:
        candidate = _nonempty_string(
            value, label="card_assessments.capability_id"
        )
        if candidate in cards_by_id:
            return candidate
        suffix = candidate.rsplit("__", 1)[-1]
        suffix_matches = [
            card_id
            for card_id in cards_by_id
            if card_id.rsplit("__", 1)[-1] == suffix
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        return candidate

    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("every card assessment must be an object")
        capability_id = canonical_card_id(row.get("capability_id"))
        if capability_id not in cards_by_id or capability_id in seen:
            raise ValueError("card_assessments contain an unknown or duplicate capability_id")
        seen.add(capability_id)
        compatible = row.get("compatible")
        if not isinstance(compatible, bool):
            raise ValueError(f"{capability_id} compatible must be a boolean")
        raw_mappings = row.get("prerequisite_mapping", [])
        if not isinstance(raw_mappings, list):
            raise ValueError(f"{capability_id} prerequisite_mapping must be a list")
        mappings: list[dict[str, str]] = []
        for mapping in raw_mappings:
            if not isinstance(mapping, dict):
                raise ValueError(f"{capability_id} prerequisite mapping must be an object")
            mappings.append(
                {
                    "requirement": _nonempty_string(
                        mapping.get("requirement"),
                        label=f"{capability_id}.prerequisite_mapping.requirement",
                    ),
                    "host_evidence": _nonempty_string(
                        mapping.get("host_evidence"),
                        label=f"{capability_id}.prerequisite_mapping.host_evidence",
                        minimum=20,
                    ),
                    "evidence_scope": _nonempty_string(
                        mapping.get("evidence_scope"),
                        label=f"{capability_id}.prerequisite_mapping.evidence_scope",
                    ),
                }
            )
        if compatible:
            expected = set(_card_requirements(cards_by_id[capability_id]))
            mapped = {item["requirement"] for item in mappings}
            if expected and mapped != expected:
                raise ValueError(
                    f"{capability_id} compatible assessment must map every prerequisite exactly"
                )
            if not mappings:
                raise ValueError(
                    f"{capability_id} compatible assessment requires host evidence"
                )
            compatible_ids.add(capability_id)
        normalized.append(
            {
                "capability_id": capability_id,
                "compatible": compatible,
                "prerequisite_mapping": mappings,
                "reason": _nonempty_string(
                    row.get("reason"),
                    label=f"{capability_id}.reason",
                    minimum=20,
                ),
            }
        )
    if seen != set(cards_by_id):
        raise ValueError("card_assessments do not cover every retrieved card")
    return normalized, compatible_ids


def _evidence_quote_is_present(quote: str, corpus: str) -> bool:
    normalized_quote = _normalized_for_leakage(quote)
    normalized_corpus = _normalized_for_leakage(
        corpus.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    )
    return len(normalized_quote) >= 4 and normalized_quote in normalized_corpus


def _dependency_signal_tokens(value: str) -> set[str]:
    stop = {
        "a", "an", "and", "by", "current", "data", "for", "from", "in", "of",
        "on", "state", "the", "to", "user", "value", "visible", "with",
    }
    return {
        _light_stem(token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in stop
    }


def _light_stem(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 2:
        return token[:-1]
    return token


_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
}


def _numeric_values(value: str) -> set[str]:
    values = set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?", value.lower()))
    for word, number in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", value, re.I):
            values.add(number)
    return values


def _quote_supports_claim_numbers(claim: str, quote: str) -> bool:
    claim_numbers = _numeric_values(claim)
    quote_numbers = _numeric_values(quote)
    missing = claim_numbers - quote_numbers
    if not missing:
        return True
    marker_match = re.search(
        r"terminal marker values\s+([^.;]+)", quote, re.I
    )
    if marker_match:
        marker_count = len(
            [value for value in marker_match.group(1).split(",") if value.strip()]
        )
        missing.discard(str(marker_count))
    return not missing


def _claim_signal_tokens(value: str) -> set[str]:
    stop = {
        "a", "an", "and", "are", "card", "current", "each", "exist", "field",
        "for", "from", "gallery", "has", "have", "in", "is", "item", "object",
        "of", "on", "page", "record", "the", "to", "use", "uses", "with",
    }
    return {
        _light_stem(token)
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if (len(token) >= 3 or token == "id") and token not in stop
    }


def validate_edit_sequence(
    payload: dict[str, Any],
    *,
    seed_id: str,
    donor_ids: set[str],
    planner_cards: Iterable[dict[str, Any]] | None = None,
    edit_count: int | None = DEFAULT_EDIT_COUNT,
    host_evidence_corpus: str | None = None,
    module_plan: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    adaptive_count = edit_count is None
    rows = payload.get("edits")
    if not isinstance(rows, list):
        raise ValueError("edit sequence requires an edits list")
    if edit_count is None:
        edit_count = _validate_edit_count(len(rows))
    else:
        edit_count = _validate_edit_count(edit_count)
    minimum_dependencies, maximum_dependencies = _dependency_limits(edit_count)
    maximum_donor_edits = _max_donor_edits(edit_count)
    minimum_later_independent = _minimum_later_independent_edits(edit_count)
    seed_summary = _nonempty_string(payload.get("seed_summary"), label="seed_summary", minimum=20)
    current = _string_list(payload.get("existing_capabilities"), label="existing_capabilities")
    if len(rows) != edit_count:
        raise ValueError(f"edit sequence requires exactly {edit_count} edits")
    edit_count_reason = str(payload.get("edit_count_reason") or "").strip()
    if adaptive_count and len(edit_count_reason) < 20:
        raise ValueError("adaptive edit sequence requires an edit_count_reason")
    if not edit_count_reason:
        edit_count_reason = "The requested fixed sequence length was used."
    normalized: list[dict[str, Any]] = []
    frozen_plan = tuple(module_plan or ())
    review_notes: list[str] = []
    if frozen_plan and len(frozen_plan) != edit_count:
        raise ValueError("frozen module plan length differs from Edit sequence")
    produced_by_edit: dict[str, set[str]] = {}
    dependent_count = 0
    later_independent_count = 0
    donor_edit_count = 0
    forbidden_instruction_terms = re.compile(
        r"\b(?:DOM|AX tree|dataset|benchmark|state graph|JSON)\b"
        r"|\b(?:CSS|DOM) selector\b"
        r"|\bdonor (?:capability|source|card|page|seed)\b",
        re.I,
    )
    forbidden_sequence_references = re.compile(
        r"\b(?:q\d+|earlier (?:edit|feature)|previous (?:edit|feature))\b",
        re.I,
    )
    instruction_openings: list[str] = []
    hidden_cards = tuple(planner_cards or ())
    card_assessments, compatible_card_ids = _normalize_card_assessments(
        payload, hidden_cards
    )
    cited_donor_ids: set[str] = set()

    def canonical_donor_id(value: str | None) -> str | None:
        if value is None or value in donor_ids:
            return value
        suffix = value.rsplit("__", 1)[-1]
        matches = [
            donor_id
            for donor_id in donor_ids
            if donor_id.rsplit("__", 1)[-1] == suffix
        ]
        return matches[0] if len(matches) == 1 else value

    def reject_hidden_evidence_leakage(instruction: str, edit_id: str) -> None:
        rendered = _normalized_for_leakage(instruction)
        if "```" in instruction or "`" in instruction:
            raise ValueError(f"{edit_id} instruction exposes code formatting")
        for card in hidden_cards:
            identity_terms = {
                str(card.get("capability_id", "")).strip(),
                str(card.get("source_seed_id", "")).strip(),
                str(card.get("source_project", "")).strip(),
            }
            source_slices = card.get("source_slices")
            if not isinstance(source_slices, list):
                source_slices = card.get("donor_snippets", [])
            for snippet in source_slices:
                if not isinstance(snippet, dict):
                    continue
                identity_terms.update(
                    {
                        str(
                            snippet.get("slice_id")
                            or snippet.get("snippet_id")
                            or ""
                        ).strip(),
                        str(snippet.get("path", "")).strip(),
                    }
                )
                code = str(snippet.get("content") or snippet.get("code") or "")
                code_norm = _normalized_for_leakage(code)
                if len(code_norm) >= 30:
                    for start in range(0, max(1, len(code_norm) - 29), 15):
                        fragment = code_norm[start : start + 30]
                        if len(fragment) == 30 and fragment in rendered:
                            raise ValueError(
                                f"{edit_id} instruction copies hidden donor code"
                            )
                code_identifiers = set(
                    re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]{7,}\b", code)
                )
                for identifier in code_identifiers:
                    if identifier in _PUBLIC_WEB_API_IDENTIFIERS:
                        continue
                    if ("_" in identifier or re.search(r"[a-z][A-Z]", identifier)) and re.search(
                        rf"\b{re.escape(identifier)}\b", instruction
                    ):
                        raise ValueError(
                            f"{edit_id} instruction exposes a hidden donor identifier"
                        )
            for term in identity_terms:
                if term and len(term) >= 4 and term.lower() in instruction.lower():
                    raise ValueError(f"{edit_id} instruction exposes donor identity")
    for offset, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError("every Edit must be an object")
        edit_id = _nonempty_string(row.get("edit_id"), label="edit_id")
        if edit_id != f"q{offset}" or row.get("edit_index") != offset:
            raise ValueError(f"Edit ids and indexes must be q1..q{edit_count}")
        source_version = _nonempty_string(row.get("source_version"), label="source_version")
        target_version = _nonempty_string(row.get("target_version"), label="target_version")
        if source_version != f"s{offset - 1}":
            raise ValueError(f"{edit_id} must use the prior accepted linear source s{offset - 1}")
        if target_version != f"s{offset}":
            raise ValueError(f"{edit_id} must produce s{offset}")
        instruction = _nonempty_string(row.get("instruction"), label="instruction", minimum=80)
        instruction_words = _instruction_word_count(instruction)
        if not MIN_INSTRUCTION_WORDS <= instruction_words <= MAX_INSTRUCTION_WORDS:
            review_notes.append(f"{edit_id}: length outside suggested range ({instruction_words} words)")
        instruction_sentences = _instruction_sentence_count(instruction)
        if not MIN_INSTRUCTION_SENTENCES <= instruction_sentences <= MAX_INSTRUCTION_SENTENCES:
            review_notes.append(f"{edit_id}: sentence count outside suggested range ({instruction_sentences})")
        if forbidden_instruction_terms.search(instruction):
            raise ValueError(f"{edit_id} instruction exposes production internals")
        if forbidden_sequence_references.search(instruction):
            raise ValueError(f"{edit_id} instruction exposes sequence-internal references")
        if re.search(
            r"\b(?:theme|dark mode|light mode)\b.*\b(?:switch|switcher|toggle)\b"
            r"|\b(?:switch|switcher|toggle)\b.*\b(?:theme|dark mode|light mode)\b",
            instruction,
            re.I | re.S,
        ):
            raise ValueError(f"{edit_id} uses a generic theme-switch filler module")
        if re.search(
            r"\b(?:guided tour|onboarding tour|walkthrough overlay)\b",
            instruction,
            re.I,
        ):
            raise ValueError(f"{edit_id} uses a generic guided-tour filler module")
        if re.search(r"\bshortcut overlay\b", instruction, re.I):
            raise ValueError(f"{edit_id} uses a generic shortcut-overlay filler module")
        opening = re.search(r"[A-Za-z]+", instruction)
        if opening is None:
            raise ValueError(f"{edit_id} instruction requires an English opening verb")
        instruction_openings.append(opening.group(0).lower())
        reject_hidden_evidence_leakage(instruction, edit_id)
        raw_donor_id = row.get("donor_capability_id")
        raw_donor_ids = row.get('donor_capability_ids', raw_donor_id)
        if raw_donor_ids is None:
            raw_donor_ids = []
        elif isinstance(raw_donor_ids, str):
            raw_donor_ids = [raw_donor_ids] if raw_donor_ids.strip() else []
        if not isinstance(raw_donor_ids, list) or any(not isinstance(x, str) or not x.strip() for x in raw_donor_ids):
            raise ValueError(f'{edit_id} donor references must be strings')
        cited_ids = list(dict.fromkeys(canonical_donor_id(x.strip()) for x in raw_donor_ids))
        donor_id = cited_ids[0] if cited_ids else None
        if isinstance(raw_donor_id, str) and raw_donor_id.strip() and canonical_donor_id(raw_donor_id.strip()) not in cited_ids:
            raise ValueError(f'{edit_id} primary donor differs from donor references')
        origin = {
            "verified_donor": "verified_donor_adaptation",
            "donor_adaptation": "verified_donor_adaptation",
            "donor": "verified_donor_adaptation",
            "retrieved_card_adaptation": "verified_donor_adaptation",
            "host_gap": "host_grounded_gap",
            "host_gounded_gap": "host_grounded_gap",
        }.get(row.get("origin"), row.get("origin"))
        if donor_id in donor_ids:
            origin = "verified_donor_adaptation"
        if origin not in {"verified_donor_adaptation", "host_grounded_gap"}:
            raise ValueError(f"{edit_id} has an invalid origin")
        if origin == "verified_donor_adaptation":
            if not cited_ids or any(value not in donor_ids for value in cited_ids):
                raise ValueError(f"{edit_id} cites an unknown donor capability")
            if hidden_cards and any(value not in compatible_card_ids for value in cited_ids):
                raise ValueError(
                    f"{edit_id} cites a retrieved card assessed as incompatible"
                )
            donor_edit_count += 1
            cited_donor_ids.update(cited_ids)
        elif donor_id is not None:
            raise ValueError(f"{edit_id} host gap must not cite a donor")
        raw_dependencies = row.get("depends_on")
        if isinstance(raw_dependencies, str):
            dependency_ids = re.findall(r"\bq\d+\b", raw_dependencies)
            raw_dependencies = dependency_ids or [raw_dependencies]
        dependencies = _string_list(
            raw_dependencies, label=f"{edit_id}.depends_on", allow_empty=True
        )
        allowed_previous = {f"q{index}" for index in range(1, offset)}
        if not set(dependencies).issubset(allowed_previous):
            raise ValueError(f"{edit_id} depends on a non-prior Edit")
        if offset == 1 and dependencies:
            raise ValueError("q1 cannot depend on another Edit")
        if dependencies:
            dependent_count += 1
        elif offset > 1:
            later_independent_count += 1
        if frozen_plan:
            planned = frozen_plan[offset - 1]
            if str(planned.get("edit_id")) != edit_id:
                raise ValueError(f"{edit_id} does not align with the frozen module plan")
            planned_dependencies = [str(value) for value in planned.get("depends_on", [])]
            if dependencies != planned_dependencies:
                raise ValueError(
                    f"{edit_id}.depends_on differs from the frozen module plan"
                )
            planned_goal = str(planned.get("goal") or "")
            for behavior, pattern in {
                "search": r"\bsearch\w*\b",
                "filter": r"\bfilter\w*\b",
                "sort": r"\bsort\w*\b",
            }.items():
                if planned_goal and re.search(pattern, instruction, re.I) and not re.search(
                    pattern, planned_goal, re.I
                ):
                    raise ValueError(
                        f"{edit_id} adds {behavior} behavior outside the frozen module goal"
                    )
        requirements = row.get("requires")
        if not isinstance(requirements, list) or not requirements:
            raise ValueError(f"{edit_id}.requires must be non-empty")
        normalized_requirements: list[dict[str, str]] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ValueError(f"{edit_id} requirement must be an object")
            state = _nonempty_string(requirement.get("state"), label=f"{edit_id}.requires.state")
            source = _nonempty_string(requirement.get("source"), label=f"{edit_id}.requires.source")
            prior_match = re.search(r"\bq\d+\b", source)
            if prior_match:
                source = prior_match.group(0)
            elif source in {"host", "s0", "current_source"} or not re.fullmatch(
                r"q\d+", source
            ):
                source = "seed"
            if source != "seed" and source not in allowed_previous:
                raise ValueError(f"{edit_id} requirement source is not prior")
            normalized_requirement = {
                "state": state,
                "source": source,
                "evidence": _nonempty_string(
                    requirement.get("evidence"),
                    label=f"{edit_id}.requires.evidence",
                    minimum=20,
                ),
            }
            raw_quote = requirement.get("evidence_quote")
            if source == "seed" and host_evidence_corpus is not None:
                quote = _nonempty_string(
                    raw_quote,
                    label=f"{edit_id}.requires.evidence_quote",
                    minimum=4,
                )
                if not _evidence_quote_is_present(quote, host_evidence_corpus):
                    raise ValueError(
                        f"{edit_id} seed requirement evidence_quote is absent from Host evidence"
                    )
                normalized_requirement["evidence_quote"] = quote
            elif isinstance(raw_quote, str) and raw_quote.strip():
                normalized_requirement["evidence_quote"] = raw_quote.strip()
            if source in produced_by_edit:
                valid_states = produced_by_edit[source]
                if state not in valid_states:
                    state_norm = _normalized_for_leakage(state)
                    suffixes = (
                        f" from {source}",
                        f" produced by {source}",
                        f" output by {source}",
                    )
                    canonical_matches = [
                        candidate
                        for candidate in valid_states
                        if any(
                            state_norm
                            == _normalized_for_leakage(candidate) + suffix
                            for suffix in suffixes
                        )
                    ]
                    if len(canonical_matches) != 1:
                        raise ValueError(
                            f"{edit_id} required state {state!r} does not exactly match an output of {source}"
                        )
                    normalized_requirement["provider_state"] = state
                    state = canonical_matches[0]
                    normalized_requirement["state"] = state
                    normalized_requirement[
                        "state_match_status"
                    ] = "canonicalized_explicit_source_suffix"
                else:
                    normalized_requirement["state_match_status"] = "exact"
            normalized_requirements.append(normalized_requirement)
        requirement_keys = {
            (item["state"], item["source"]) for item in normalized_requirements
        }
        if len(requirement_keys) != len(normalized_requirements):
            raise ValueError(f"{edit_id} contains duplicate required states")
        for dependency in dependencies:
            declared = [
                item for item in normalized_requirements if item["source"] == dependency
            ]
            if not declared:
                raise ValueError(
                    f"{edit_id} does not declare a required state from dependency {dependency}"
                )
        productions = row.get("produces")
        if not isinstance(productions, list) or not productions:
            raise ValueError(f"{edit_id}.produces must be non-empty")
        normalized_productions: list[dict[str, str]] = []
        for production in productions:
            if not isinstance(production, dict):
                raise ValueError(f"{edit_id} production must be an object")
            normalized_productions.append(
                {
                    key: _nonempty_string(
                        production.get(key), label=f"{edit_id}.produces.{key}"
                    )
                    for key in (
                        "state",
                        "value_shape",
                        "scope",
                        "persistence",
                        "observable",
                    )
                }
            )
        production_names = {item["state"] for item in normalized_productions}
        if len(production_names) != len(normalized_productions):
            raise ValueError(f"{edit_id} produces duplicate states")
        produced_by_edit[edit_id] = production_names
        if frozen_plan:
            planned_state = str(frozen_plan[offset - 1].get("produces_state") or "").strip()
            if planned_state not in production_names:
                raise ValueError(
                    f"{edit_id} must copy the frozen produces_state exactly"
                )
        raw_dependency_evidence = row.get("dependency_evidence", [])
        if not isinstance(raw_dependency_evidence, list):
            raise ValueError(f"{edit_id}.dependency_evidence must be a list")
        normalized_dependency_evidence: list[dict[str, str]] = []
        for evidence_row in raw_dependency_evidence:
            if not isinstance(evidence_row, dict):
                raise ValueError(f"{edit_id} dependency evidence must be an object")
            producer = _nonempty_string(
                evidence_row.get("producer_edit"),
                label=f"{edit_id}.dependency_evidence.producer_edit",
            )
            state = _nonempty_string(
                evidence_row.get("consumed_state"),
                label=f"{edit_id}.dependency_evidence.consumed_state",
            )
            phrase = _nonempty_string(
                evidence_row.get("instruction_evidence"),
                label=f"{edit_id}.dependency_evidence.instruction_evidence",
                minimum=4,
            )
            reverse_failure = _nonempty_string(
                evidence_row.get("reverse_failure"),
                label=f"{edit_id}.dependency_evidence.reverse_failure",
                minimum=20,
            )
            if producer not in dependencies:
                raise ValueError(
                    f"{edit_id} dependency_evidence cites an undeclared producer"
                )
            if state not in produced_by_edit.get(producer, set()):
                raise ValueError(
                    f"{edit_id} dependency_evidence state is not produced by {producer}"
                )
            if _normalized_for_leakage(phrase) not in _normalized_for_leakage(instruction):
                raise ValueError(
                    f"{edit_id} dependency instruction evidence is not an exact instruction phrase"
                )
            signal_overlap = _dependency_signal_tokens(state) & _dependency_signal_tokens(phrase)
            producer_instruction = next(
                (
                    prior["instruction"]
                    for prior in normalized
                    if prior["edit_id"] == producer
                ),
                "",
            )
            producer_overlap = _dependency_signal_tokens(
                producer_instruction
            ) & _dependency_signal_tokens(phrase)
            if len(signal_overlap) < 2 and len(producer_overlap) < 2:
                raise ValueError(
                    f"{edit_id} dependency instruction evidence does not identify the consumed state"
                )
            readable_state = _normalized_for_leakage(
                re.sub(r"[_\s-]+", " ", state)
            )
            readable_reverse = _normalized_for_leakage(
                re.sub(r"[_\s-]+", " ", reverse_failure)
            )
            if readable_state not in readable_reverse:
                raise ValueError(
                    f"{edit_id} reverse_failure must name the consumed state"
                )
            normalized_dependency_evidence.append(
                {
                    "producer_edit": producer,
                    "consumed_state": state,
                    "instruction_evidence": phrase,
                    "reverse_failure": reverse_failure,
                }
            )
        expected_dependency_pairs = {
            (requirement["source"], requirement["state"])
            for requirement in normalized_requirements
            if requirement["source"] in dependencies
        }
        actual_dependency_pairs = {
            (item["producer_edit"], item["consumed_state"])
            for item in normalized_dependency_evidence
        }
        if (
            host_evidence_corpus is not None
            and actual_dependency_pairs != expected_dependency_pairs
        ):
            raise ValueError(
                f"{edit_id} dependency_evidence must cover every and only declared prior state"
            )
        if len(actual_dependency_pairs) != len(normalized_dependency_evidence):
            raise ValueError(f"{edit_id} contains duplicate dependency evidence")

        raw_source_claims = row.get("source_claims", [])
        if not isinstance(raw_source_claims, list):
            raise ValueError(f"{edit_id}.source_claims must be a list")
        normalized_source_claims: list[dict[str, str]] = []
        for claim_row in raw_source_claims:
            if not isinstance(claim_row, dict):
                raise ValueError(f"{edit_id} source claim must be an object")
            claim = _nonempty_string(
                claim_row.get("claim"), label=f"{edit_id}.source_claims.claim", minimum=8
            )
            quote = _nonempty_string(
                claim_row.get("evidence_quote"),
                label=f"{edit_id}.source_claims.evidence_quote",
                minimum=4,
            )
            if host_evidence_corpus is not None and not _evidence_quote_is_present(
                quote, host_evidence_corpus
            ):
                raise ValueError(
                    f"{edit_id} source_claim evidence_quote is absent from Host evidence"
                )
            if host_evidence_corpus is not None:
                if not _quote_supports_claim_numbers(claim, quote):
                    raise ValueError(
                        f"{edit_id} source_claim numbers are not present in its evidence_quote"
                    )
                if not (_claim_signal_tokens(claim) & _claim_signal_tokens(quote)):
                    review_notes.append(
                        f"{edit_id}: source claim has low lexical overlap with its quote; "
                        f"check semantic support: {claim}"
                    )
            normalized_source_claims.append(
                {"claim": claim, "evidence_quote": quote}
            )
        if host_evidence_corpus is not None and not normalized_source_claims:
            raise ValueError(f"{edit_id} requires at least one grounded source_claim")
        if host_evidence_corpus is not None:
            claimed_text = " ".join(
                value
                for claim_row in normalized_source_claims
                for value in (claim_row["claim"], claim_row["evidence_quote"])
            ).lower()
            for descriptor in re.findall(
                r"\bexisting\s+(shadow|color|style|layout|typography|spacing|animation|motion)\b",
                instruction,
                re.I,
            ):
                if descriptor.lower() not in claimed_text:
                    raise ValueError(
                        f"{edit_id} calls {descriptor.lower()} existing without a source claim"
                    )

        raw_new_values = row.get("new_values", [])
        if not isinstance(raw_new_values, list):
            raise ValueError(f"{edit_id}.new_values must be a list")
        normalized_new_values: list[dict[str, str]] = []
        for value_row in raw_new_values:
            if not isinstance(value_row, dict):
                raise ValueError(f"{edit_id} new value must be an object")
            raw_value = value_row.get("value")
            if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
                raw_value = str(raw_value)
            value = _nonempty_string(
                raw_value, label=f"{edit_id}.new_values.value"
            )
            phrase = _nonempty_string(
                value_row.get("instruction_evidence"),
                label=f"{edit_id}.new_values.instruction_evidence",
                minimum=3,
            )
            rationale = _nonempty_string(
                value_row.get("rationale"),
                label=f"{edit_id}.new_values.rationale",
                minimum=15,
            )
            if _normalized_for_leakage(phrase) not in _normalized_for_leakage(instruction):
                raise ValueError(
                    f"{edit_id} new value evidence is not an exact instruction phrase"
                )
            value_numbers = _numeric_values(value)
            if not value_numbers or not value_numbers.issubset(_numeric_values(phrase)):
                raise ValueError(
                    f"{edit_id} new value must name a number from its instruction evidence"
                )
            if re.search(
                r"\b(?:browser-derived|existing|fixed collection|host|maximum|minimum|observed|source)\b",
                rationale,
                re.I,
            ):
                raise ValueError(
                    f"{edit_id} new_values must not relabel a Host-derived number"
                )
            normalized_new_values.append(
                {
                    "value": value,
                    "instruction_evidence": phrase,
                    "rationale": rationale,
                }
            )
        if host_evidence_corpus is not None:
            source_numbers = {
                number
                for claim_row in normalized_source_claims
                for number in _numeric_values(claim_row["claim"])
            }
            introduced_numbers = {
                number
                for value_row in normalized_new_values
                for number in _numeric_values(value_row["value"])
            }
            uncovered_numbers = _numeric_values(instruction) - source_numbers - introduced_numbers
            # English "one" is routinely distributive ("one view but not the other") rather
            # than a configurable product limit. Explicit digit 1 remains uncommon in these
            # instructions; larger counts and all other number words stay fully audited.
            uncovered_numbers.discard("1")
            if uncovered_numbers:
                raise ValueError(
                    f"{edit_id} instruction has ungrounded numeric values: {sorted(uncovered_numbers)}"
                )
            duplicated_numeric_origins = source_numbers & introduced_numbers
            if duplicated_numeric_origins:
                raise ValueError(
                    f"{edit_id} Host-derived numbers must not be relabeled as new values: "
                    f"{sorted(duplicated_numeric_origins)}"
                )
            if re.search(
                r"\b(?:all|the)\s+(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
                r"(?:\s+\w+){0,2}\s+(?:categories|options|statuses|tags|types)\b",
                instruction,
                re.I,
            ):
                raise ValueError(
                    f"{edit_id} must derive category options dynamically instead of asserting a fixed category count"
                )
        dependency_reason = row.get("dependency_reason")
        if not dependencies and not str(dependency_reason or "").strip():
            dependency_reason = "Independent of states introduced by earlier edits."
        normalized.append(
            {
                "edit_index": offset,
                "edit_id": edit_id,
                "source_version": source_version,
                "target_version": target_version,
                "instruction": instruction,
                "origin": origin,
                "donor_capability_id": donor_id,
                "donor_capability_ids": cited_ids,
                "source_gap": _nonempty_string(
                    row.get("source_gap"), label=f"{edit_id}.source_gap", minimum=20
                ),
                "user_value": _nonempty_string(
                    row.get("user_value"), label=f"{edit_id}.user_value", minimum=20
                ),
                "product_fit": _nonempty_string(
                    row.get("product_fit"), label=f"{edit_id}.product_fit", minimum=20
                ),
                "requires": normalized_requirements,
                "produces": normalized_productions,
                "depends_on": dependencies,
                "dependency_evidence": normalized_dependency_evidence,
                "source_claims": normalized_source_claims,
                "new_values": normalized_new_values,
                "dependency_reason": _nonempty_string(
                    dependency_reason, label=f"{edit_id}.dependency_reason", minimum=20
                ),
                "preserve": _string_list(row.get("preserve"), label=f"{edit_id}.preserve"),
                "acceptance": _string_list(
                    row.get("acceptance"), label=f"{edit_id}.acceptance"
                ),
            }
        )
    if host_evidence_corpus is not None:
        host_norm = _normalized_for_leakage(host_evidence_corpus)
        host_signal_tokens = _dependency_signal_tokens(host_evidence_corpus)
        dependency_ancestors: dict[str, set[str]] = {}
        for edit in normalized:
            ancestors = set(edit["depends_on"])
            for dependency in edit["depends_on"]:
                ancestors.update(dependency_ancestors.get(dependency, set()))
            dependency_ancestors[edit["edit_id"]] = ancestors
        for consumer_index, consumer in enumerate(normalized):
            consumer_tokens = _dependency_signal_tokens(consumer["instruction"])
            for producer in normalized[:consumer_index]:
                if producer["edit_id"] in dependency_ancestors[consumer["edit_id"]]:
                    continue
                implicit_signals: list[str] = []
                for production in producer["produces"]:
                    state = production["state"]
                    state_tokens = _dependency_signal_tokens(state)
                    state_specific_tokens = state_tokens - host_signal_tokens
                    if (
                        len(state_tokens) >= 2
                        and len(state_tokens & consumer_tokens) >= 2
                        and bool(state_specific_tokens & consumer_tokens)
                        and _normalized_for_leakage(state) not in host_norm
                    ):
                        implicit_signals.append(state)
                for label in re.findall(r'["\u201c]([^"\u201d]{3,80})["\u201d]', producer["instruction"]):
                    label_tokens = _dependency_signal_tokens(label)
                    if (
                        len(label_tokens) >= 2
                        and label_tokens.issubset(consumer_tokens)
                        and _normalized_for_leakage(label) not in host_norm
                    ):
                        implicit_signals.append(label)
                if implicit_signals:
                    review_notes.append(
                        f"{consumer['edit_id']} shares terms with {producer['edit_id']}; check actual state consumption: "
                        + ", ".join(sorted(set(implicit_signals)))
                    )

        fragmented_discovery_edits = []
        for edit in normalized:
            first_sentence = re.split(r"(?<=[.!?])\s+", edit["instruction"], maxsplit=1)[0]
            if re.search(
                r"\b(?:add|build|create|develop|implement|introduce|provide)\b"
                r".{0,100}\b(?:filter|search|sort)\b",
                first_sentence,
                re.I,
            ):
                fragmented_discovery_edits.append(edit["edit_id"])
        if len(fragmented_discovery_edits) > 1:
            raise ValueError(
                "search, filtering, and sorting for one result surface must be one module, not "
                + ", ".join(fragmented_discovery_edits)
            )

    raw_dependency_plan = payload.get("dependency_plan", [])
    if not isinstance(raw_dependency_plan, list):
        raise ValueError("dependency_plan must be a list of dependent Edit ids")
    dependency_plan = _string_list(
        raw_dependency_plan, label="dependency_plan", allow_empty=True
    )
    actual_dependent_ids = [
        edit["edit_id"] for edit in normalized if edit["depends_on"]
    ]
    if host_evidence_corpus is not None and dependency_plan != actual_dependent_ids:
        raise ValueError(
            "dependency_plan must exactly list every dependent Edit in sequence order"
        )
    if frozen_plan:
        planned_dependent_ids = [
            str(row["edit_id"]) for row in frozen_plan if row.get("depends_on")
        ]
        if dependency_plan != planned_dependent_ids:
            raise ValueError("dependency_plan differs from the frozen module plan")

    if later_independent_count < minimum_later_independent:
        raise ValueError(
            f"sequence requires at least {minimum_later_independent} later independent Edits"
        )
    if not minimum_dependencies <= dependent_count <= maximum_dependencies:
        raise ValueError(
            "sequence requires "
            f"{minimum_dependencies} to {maximum_dependencies} state-dependent later Edits"
        )
    if donor_edit_count > maximum_donor_edits:
        raise ValueError(
            f"at most {maximum_donor_edits} Edits may adapt verified donors"
        )
    minimum_compatible_adaptations = min(
        _minimum_retrieved_edits(edit_count), len(compatible_card_ids)
    )
    if hidden_cards and len(cited_donor_ids) < minimum_compatible_adaptations:
        raise ValueError(
            "sequence must adapt at least "
            f"{minimum_compatible_adaptations} distinct compatible retrieved cards"
        )
    opening_limit = max(3, (edit_count * 2 + 4) // 5)
    most_common_opening = max(instruction_openings.count(value) for value in set(instruction_openings))
    if most_common_opening > opening_limit:
        raise ValueError(
            f"sequence may use the same instruction opening at most {opening_limit} times"
        )
    order_diagnostics: list[dict[str, Any]] = []
    for edit in normalized:
        for dependency in edit["depends_on"]:
            consumed = [
                item["state"]
                for item in edit["requires"]
                if item["source"] == dependency
            ]
            order_diagnostics.append(
                {
                    "producer_edit": dependency,
                    "consumer_edit": edit["edit_id"],
                    "forward_order": f"{dependency}->{edit['edit_id']}",
                    "forward_status": "valid_by_declared_state_flow",
                    "reverse_order": f"{edit['edit_id']}->{dependency}",
                    "reverse_status": "invalid_before_producer",
                    "consumed_states": consumed,
                    "evidence_scope": "instruction_plan_only",
                }
            )
    return {
        "schema_version": "webcoding-linear-edit-query-sequence-v5",
        "seed_id": seed_id,
        "seed_summary": seed_summary,
        "edit_count_reason": edit_count_reason,
        "dependency_plan": dependency_plan,
        "frozen_module_plan_sha256": (
            hashlib.sha256(
                json.dumps(frozen_plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if frozen_plan
            else None
        ),
        "existing_capabilities": current,
        "card_assessments": card_assessments,
        "compatible_card_count": len(compatible_card_ids),
        "edit_count": edit_count,
        "dependent_edit_count": dependent_count,
        "independent_later_edit_count": later_independent_count,
        "donor_edit_count": donor_edit_count,
        "order_diagnostics": order_diagnostics,
        "review_notes": review_notes,
        "edits": normalized,
    }


def _normalized_for_leakage(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _compact_hidden_source_slice(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    content = str(row.get("content") or row.get("code") or "")
    if len(content) > 900:
        content = content[:560] + "\n[...slice shortened...]\n" + content[-280:]
    return {
        key: value
        for key, value in {
            "slice_id": row.get("slice_id") or row.get("snippet_id"),
            "path": row.get("path"),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
            "language": row.get("language"),
            "evidence_summary": _bounded_text(row.get("evidence_summary"), 280),
            "sha256": row.get("sha256"),
            "content": content,
            "source_kind": row.get("source_kind"),
            "intended_use": row.get("intended_use"),
            "dependency_closure": row.get("dependency_closure"),
            "standalone_verified": row.get("standalone_verified"),
        }.items()
        if value not in (None, "", [], {})
    }


def generation_stable_prefix(
    capability_bank: dict[str, Any],
    *,
    ranked_effects: Iterable[RankedEffect] | None = None,
    retrieved_cards: Iterable[dict[str, Any]] | None = None,
    edit_count: int | None = DEFAULT_EDIT_COUNT,
) -> str:
    if edit_count is None:
        count_policy = (
            f"Create {MIN_EDIT_COUNT} to {MAX_EDIT_COUNT} linear source-conditioned Edit instructions. "
            "Choose the smallest count that retains every strong, distinct module; do not fill a target count "
            "with utilities, duplicate goals, or claims unsupported by the Host. Do not prefer eight; use "
            "the Host and retrieved inspiration to determine the number of distinct useful workflows. "
            "Include at least one and no "
            "more than three state-dependent later Edits, keep at least one later Edit independent (two when "
            "the final count is six or more), and use no more than three fifths retrieved-card adaptations. "
        )
    else:
        edit_count = _validate_edit_count(edit_count)
        minimum_dependencies, maximum_dependencies = _dependency_limits(edit_count)
        minimum_later_independent = _minimum_later_independent_edits(edit_count)
        maximum_donor_edits = _max_donor_edits(edit_count)
        count_policy = (
            f"Create exactly {edit_count} linear source-conditioned Edit instructions. Include "
            f"{minimum_dependencies} to {maximum_dependencies} state-dependent later Edits, at least "
            f"{minimum_later_independent} later independent Edits, and at most {maximum_donor_edits} "
            "retrieved-card adaptations. "
        )
    effect_rows = tuple(ranked_effects or ())
    retrieved_rows = tuple(retrieved_cards or ())
    if retrieved_rows:
        compact_cards = []
        for row in retrieved_rows:
            if "source_slices" in row:
                source_slices = [
                    compact
                    for compact in (
                        _compact_hidden_source_slice(slice_row)
                        for slice_row in row["source_slices"][:1]
                    )
                    if compact
                ]
                compact_cards.append(
                    {
                        "capability_id": row["capability_id"],
                        "change_type": row["change_type"],
                        "summary": row["summary"],
                        "requires": row["requires"],
                        "user_actions": row["user_actions"],
                        "produces": row["produces"],
                        "visible_result": row["visible_result"],
                        "future_uses": row["future_uses"],
                        "source_slices": source_slices,
                    }
                )
            else:
                # Immutable historical retrieval artifacts remain readable.
                donor_snippets = [
                    compact
                    for compact in (
                        _compact_hidden_source_slice(slice_row)
                        for slice_row in row["donor_snippets"][:1]
                    )
                    if compact
                ]
                compact_cards.append(
                    {
                        "capability_id": row["capability_id"],
                        "name": row["name"],
                        "family": row["family"],
                        "summary": row["summary"],
                        "prerequisites": row["prerequisites"],
                        "user_actions": row["user_actions"],
                        "state_reads": row["state_reads"],
                        "state_writes": row["state_writes"],
                        "visible_result": row["visible_result"],
                        "donor_snippets": donor_snippets,
                    }
                )
        heading = "TOP-K PAGE-CHANGE CARDS WITH HIDDEN SOURCE SLICES"
    elif effect_rows:
        compact_cards = [row.to_planner_dict() for row in effect_rows]
        heading = "HOST-CONDITIONED PAGE-EFFECT CANDIDATES"
    else:
        compact_cards = [
            {
                "id": row["id"],
                "summary": row["summary"],
                "prerequisites": row["prerequisites"],
                "outputs": row["outputs"],
                "verification": row["verification"],
            }
            for row in capability_bank["capabilities"]
        ]
        heading = "VERIFIED DONOR CAPABILITIES"
    return (
        "PRODUCTION POLICY\n"
        + count_policy
        + "First assess every retrieved card against the Host and frozen module goals. A card is compatible when "
        "its object-action-state pattern can be mapped to Host base objects, a frozen planned output, or UI/state "
        "that the same frozen module will create. Donor business names, route names, frameworks, and domains may "
        "differ; these are not incompatibilities. Reject only when an irreducible base object, local data field, "
        "page region, or dependency cannot be mapped without changing the frozen goal. A page-, topic-, or "
        "section-level singleton still does not satisfy a per-record base-data prerequisite. After this assessment, "
        "adapt min(2, compatible-card count) distinct compatible cards; "
        "if no card is compatible, use only host-grounded gaps. Do not force cards into fixed q positions. "
        "Every retrieved-card adaptation must cite its supplied capability_id. A semantic dependency "
        "must consume a state produced by an earlier Edit. "
        "Retrieved source slices are hidden planning evidence. Adapt their object/action/state structure to "
        "the host, but never copy code or expose donor identity, paths, selectors, or identifiers in an instruction.\n\n"
        + heading
        + "\n"
        + json.dumps(compact_cards, ensure_ascii=False)
    )


def generation_task(
    seed: dict[str, Any],
    observation: dict[str, Any],
    *,
    include_source: bool,
    edit_count: int | None = DEFAULT_EDIT_COUNT,
    minimum_donor_edits: int = 0,
    module_plan: Iterable[dict[str, Any]] | None = None,
) -> str:
    if edit_count is None:
        maximum_donor_edits = _max_donor_edits(MAX_EDIT_COUNT)
        count_request = (
            f"Return the strongest {MIN_EDIT_COUNT} to {MAX_EDIT_COUNT} edits as q1 through qN, mapping "
            "s0->s1 through s(N-1)->sN. Also return edit_count_reason explaining why adding another module "
            "would become unsupported, duplicative, or unnaturally small. Do not prefer any fixed count."
        )
        dependency_request = (
            "Use at least one and no more than three dependent later Edits, and retain at least one later "
            "independent Edit (two when N is six or more)."
        )
    else:
        edit_count = _validate_edit_count(edit_count)
        maximum_donor_edits = _max_donor_edits(edit_count)
        minimum_dependencies, maximum_dependencies = _dependency_limits(edit_count)
        minimum_later_independent = _minimum_later_independent_edits(edit_count)
        count_request = (
            f"Return exactly {edit_count} edits, q1 through q{edit_count}, mapping s0->s1 through "
            f"s{edit_count - 1}->s{edit_count}. Also return edit_count_reason."
        )
        dependency_request = (
            f"Use {minimum_dependencies} to {maximum_dependencies} dependent later Edits and keep at least "
            f"{minimum_later_independent} later Edits independent."
        )
    if not 0 <= minimum_donor_edits <= maximum_donor_edits:
        raise ValueError("minimum_donor_edits is outside the supported range")
    sections = [
        "HOST PROVENANCE\n"
        + json.dumps(
            {
                "seed_id": seed["seed_id"],
                "dataset": seed["dataset"],
                "original_instruction": _bounded_text(
                    seed.get("original_instruction", ""), 6000
                ),
                "page_type": seed.get("page_type"),
            },
            ensure_ascii=False,
        ),
        "CURRENT BROWSER EVIDENCE\n"
        + json.dumps(
            compact_browser_evidence_for_llm(
                observation,
                include_known_selectors=False,
            ),
            ensure_ascii=False,
        ),
        "BROWSER-DERIVED HOST FACTS\n"
        + browser_derived_host_fact_text(observation),
    ]
    if include_source:
        sections.append("COMPLETE HOST SOURCE FACTS\n" + source_context(seed["files"]))
    frozen_plan = tuple(module_plan or ())
    if frozen_plan:
        sections.append(
            "FROZEN EDIT MODULE PLAN\n"
            + json.dumps(frozen_plan, ensure_ascii=False)
        )
    frozen_plan_instruction = (
        "FROZEN EDIT MODULE PLAN is authoritative. Expand q1 through qN in that order; copy each row's "
        "depends_on and produces_state exactly, keep independent rows independent, and do not add cross-Edit "
        "integration behavior absent from the frozen goal. Do not add a new search, filter, sort, save, export, "
        "comparison, or selection action merely to make a frozen summary or layout module richer. Independent "
        "rows must not consume states from other rows. Merely hiding controls in print or preserving them does "
        "not imply state consumption. "
        "A retrieved card may be adapted only when it fits "
        "one frozen goal without changing that goal or its dependency structure. "
        "Expand within-goal interaction details (selection semantics, structured editing, synchronized "
        "views, and necessary intermediate states); these are not unrelated new capability goals. "
        "Do not use plan freezing to justify a shallow family imitation. If the goal cannot meet the "
        "capability-depth standard without changing its purpose or dependencies, flag the plan for "
        "replanning instead of silently weakening the standard. "
        if frozen_plan
        else ""
    )
    sections.append(
        count_request
        + " Return seed_summary, existing_capabilities, card_assessments, dependency_plan, and edits. "
        "dependency_plan is the sequence-ordered list of exactly those edit_ids whose depends_on is non-empty. "
        "Each edit needs "
        "edit_index, edit_id, source_version, target_version, instruction, origin, donor_capability_id, "
        "source_gap, user_value, product_fit, source_claims[{claim,evidence_quote}], "
        "new_values[{value,instruction_evidence,rationale}], "
        "requires[{state,source,evidence,evidence_quote}], "
        "produces[{state,value_shape,scope,persistence,observable}], depends_on, "
        "dependency_evidence[{producer_edit,consumed_state,instruction_evidence,reverse_failure}], dependency_reason, "
        "preserve, and acceptance. Before writing edits, return exactly one card_assessments row for every "
        + frozen_plan_instruction
        + "supplied card: {capability_id, compatible, prerequisite_mapping[{requirement,host_evidence,evidence_scope}],reason}. "
        "For a compatible card, copy every listed card requirement exactly into one prerequisite_mapping row "
        "and map it to a same-shaped Host base object, frozen planned output, or a control/state introduced inside "
        "that same frozen module. Different donor names, routes, frameworks, or business domains are expected and "
        "must not by themselves make a card incompatible. Preserve base-object scope and cardinality; for an incompatible card, use "
        "an empty mapping or only the partial mappings and explain the missing prerequisite. "
        "For example, a retrieved card that selects repeated entities into comparison state is compatible with a "
        "frozen comparison module that creates its own dropdown or checkbox selection over another repeated entity "
        "type; map that requirement to same-module construction rather than rejecting it as absent from s0. "
        f"Adapt min(2, compatible-card count) distinct compatible cards and no more than {maximum_donor_edits} total "
        "retrieved cards, citing the exact supplied capability_id for each such Edit. If compatible-card count "
        "is zero, use no retrieved card; "
        "the remaining Edits must be host_grounded_gap. First choose module boundaries: one Edit owns all controls, "
        "state transitions, synchronized surfaces, and task-specific feedback needed to complete one user goal; do "
        "not reserve those pieces as separate micro-Edits. Search, multiple filters, sort, count, no-results feedback, "
        "and reset acting on the same record surface must be one discovery Edit; never split them into successive "
        "search/filter/sort Edits merely to create dependencies. Before keeping a candidate, apply a semantic-substance "
        "test: name the concrete host business objects, the user path, the changing states, and how multiple visible "
        "parts respond. If the actual change is still only one button, toggle, message, or style property, merge it "
        "into a coherent larger workflow or replace it; never stretch it with generic requirements. Before proposing "
        "per-record filtering, grouping, comparison, or aggregation, confirm the browser evidence shows that field on "
        "the records rather than only once on the page or section. Reject a supposedly new feature when the source "
        "already reaches the same user goal and state transition through another control, even if the candidate changes "
        "its placement, label, or styling. For a visual, "
        "style, information-organization, or responsive Edit, specify the affected regions and concrete hierarchy, "
        "typography, spacing, color, motion, and breakpoint changes instead of inventing business state. Each "
        "instruction must be a standalone, coherent feature "
        f"module of {TARGET_MIN_INSTRUCTION_WORDS}-{TARGET_MAX_INSTRUCTION_WORDS} English words and "
        f"{MIN_INSTRUCTION_SENTENCES}-{MAX_INSTRUCTION_SENTENCES} complete sentences, targeting 95-110 words only "
        "after the module has passed that substance test. Include empty/error/loading states, reset behavior, "
        "persistence, responsive rules, keyboard behavior, accessibility, or preservation only when each item is "
        "necessary for that specific feature. Put regression requirements in preserve metadata, not in the natural "
        "instruction. Across the entire sequence, at most one instruction may state one specifically named coexistence "
        "condition; never use generic preserve/keep/remain/without-affecting phrases to reach the word target. Do not "
        "repeat a fixed closing checklist across instructions. Across "
        "the sequence, vary functional workflows, information organization, visual or style changes, responsive "
        "layout, navigation, and direct interaction when the host evidence supports them. "
        "Before finalizing each item, trace every named Host control, setting, record field, validation rule, and "
        "state to either current browser/source facts or an explicit depends_on producer; delete or rewrite anything "
        "without such provenance. For every Host fact used to justify an Edit, add one source_claims row with a short "
        "verbatim evidence_quote found in HOST PROVENANCE, CURRENT BROWSER EVIDENCE, BROWSER-DERIVED HOST FACTS, "
        "or COMPLETE HOST SOURCE FACTS. For record counts and numeric ranges, prefer the explicit browser-derived "
        "item_count and min/max facts instead of quoting one example object from source. "
        "The quote must directly prove the claim, including the same literal number whenever the claim contains a "
        "count, year, limit, or breakpoint; the only exception is a complete terminal-marker values list whose "
        "enumerated length exactly equals the claimed count. One example record does not prove a collection count. For a repeated "
        "record count, quote item_class_signature together with item_count; for a year range or category-like values, "
        "quote the browser-derived record-year or terminal-marker facts. "
        "Every requires row sourced from seed must also contain such an exact evidence_quote; do not use summaries, "
        "inferences, or future planned behavior as the quote. Account for every number in the natural instruction: "
        "source_claims may quote only the original Seed/Host material supplied in those sections; never quote another "
        "planned Edit or describe a planned feature as a Host fact. Prior Edit evidence belongs only in requires and "
        "dependency_evidence. "
        "Host-derived numbers must occur in a source_claim and its quote, while a newly chosen interaction limit, "
        "timeout, or breakpoint needs a new_values row whose instruction_evidence is a verbatim phrase and whose "
        "rationale explains the product choice. Values copied from the frozen module plan are not Host facts: for "
        "example, 'select two views' requires a new_values row for 2 unless Host evidence independently fixes that "
        "limit. Avoid incidental number words such as 'one column per view' when the same relationship can be stated "
        "without another numeric value. Derive category/filter options from distinct record values; never "
        "confuse the number of records with the number of unique categories. new_values is only for numeric values; "
        "when category values come from the observed records, do not invent zero-count categories or a rule for them. "
        "do not place labels, messages, key names, or option lists there. Never invent an arbitrary example result "
        "count such as '8 of 12'; specify a dynamic 'X of total' display instead. Before returning JSON, inventory "
        "every digit and number word in every instruction and ensure it is covered by a directly quoted source_claim "
        "or a numeric new_values row. A number read or computed from Host/browser facts belongs only in source_claims; "
        "never repeat or relabel it in new_values. Do not manufacture a collection workflow from a "
        "singleton host object. Vary the "
        "opening verbs across the sequence, with no opening verb used more than twice, and never refer to q numbers "
        "or an earlier Edit inside an instruction. Before returning JSON, verify that every depends_on qK has a separate "
        "requires row whose source is qK and whose state copies one produces.state from qK character for character; also "
        "verify the required number of dependent and later-independent Edits. Choose dependency positions from the "
        "actual content. " + dependency_request + " Every dependent Edit must visibly consume a state "
        "produced by an earlier Edit, and its requires rows must perform the exact state-name copy described above. "
        "Its natural instruction must explicitly name the prior user-facing capability it consumes and the combined "
        "behavior the user sees; putting the relationship only in depends_on, requires, or dependency_reason is invalid. "
        "For every prior-state requires row, return one dependency_evidence row: consumed_state must copy the producer's "
        "state exactly; instruction_evidence must be a verbatim phrase from the natural instruction that names that "
        "state and its visible use; reverse_failure must name the state (spaces or underscores are equivalent) and explain the user-visible result "
        "that becomes impossible in B->A order. If the instruction could be implemented unchanged after removing the "
        "cited prior capability, it is not a real dependency. Merely hiding or preserving another control, e.g. in print "
        "styles, does not consume its state. Conversely, if an instruction reads state from any capability "
        "introduced elsewhere in this planned sequence, it must declare that producer in depends_on and in "
        "dependency_evidence; never label a hidden dependency as independent. Before "
        "finalizing an independent later Edit, compare its wording with every earlier produces.state and every new "
        "quoted UI label; declare a dependency only if the requested result needs its produced state. "
        "Keep one to three truly state-consuming later modules according to the frozen plan. Count an "
        "Edit once even if it consumes two producer states. "
        "Write dependency_plan before drafting instructions and treat it as immutable: for example, if it is "
        "['q3','q6'], only q3 and q6 may have non-empty depends_on, and both must have it. If another Edit later needs "
        "a planned state, either replace one planned dependent ID or remove that cross-Edit behavior. "
        "For every other module, remove clauses about cooperating with earlier planned search, filters, sort, panels, "
        "or saved views; linear source versions already preserve them without creating a semantic dependency. "
        "Do not create a late responsive, print, keyboard, or style module that merely enumerates controls introduced "
        "by earlier Edits; put each new control's necessary presentation and input behavior in its own feature module. "
        "Prefer concise, complete instructions; word and sentence counts are guidance, not correctness criteria. "
        "Do not pad instructions or borrow another module's behavior to meet a word count. "
        "Do not assign retrieved cards to fixed q positions: place only compatible adaptations where they form a "
        "natural product sequence, and fill every other position from observed host gaps. "
        "FINAL HARD CHECK: return the requested number of module-sized Edits; merge all discovery controls for one result "
        "surface; dependency_plan and the actual non-empty depends_on rows must be exactly the same Edit "
        "IDs in sequence order; every other "
        "Edit must avoid mentioning planned controls or states; do not state a numeric category/type count in an "
        "instruction; every Host-derived number belongs in a directly quoted source_claim and never in new_values. "
        "Keep every non-instruction explanatory string to one specific sentence, use one or two requires/produces "
        "rows when sufficient, and avoid repeating the same browser evidence across fields."
    )
    return "\n\n".join(sections)


def browser_derived_host_facts(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarize count/range facts directly computed from saved browser states."""

    groups: dict[str, dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            raw_groups = value.get("record_groups")
            if isinstance(raw_groups, list):
                for group in raw_groups:
                    if not isinstance(group, dict) or not group.get("item_count"):
                        continue
                    records = [
                        row for row in group.get("records", []) if isinstance(row, dict)
                    ]
                    record_text = "\n".join(str(row.get("text") or "") for row in records)
                    years = sorted(
                        {
                            int(token)
                            for token in re.findall(r"\b(?:18|19|20)\d{2}\b", record_text)
                        }
                    )
                    marker_values = sorted(
                        {
                            str(marker.get("text") or "").strip()
                            for row in records
                            for marker in row.get("marker_fields", [])
                            if isinstance(marker, dict) and str(marker.get("text") or "").strip()
                        }
                    )
                    labeled_years = sorted(
                        {
                            int(token)
                            for token in re.findall(
                                r"\b(?:circa|year|dated?)\s*[:\-]?\s*((?:18|19|20)\d{2})\b",
                                record_text,
                                re.I,
                            )
                        }
                    )
                    terminal_markers = sorted(
                        {
                            line.rsplit("•", 1)[1].strip()
                            for row in records
                            for line in str(row.get("text") or "").splitlines()
                            if "•" in line and line.rsplit("•", 1)[1].strip()
                        }
                    )
                    fact = {
                        "item_tag": group.get("item_tag"),
                        "item_role": group.get("item_role"),
                        "item_class_signature": group.get("item_class_signature"),
                        "item_count": int(group["item_count"]),
                        **(
                            {
                                "observed_four_digit_values": years,
                                "four_digit_min": min(years),
                                "four_digit_max": max(years),
                            }
                            if years
                            else {}
                        ),
                        **(
                            {
                                "observed_record_year_values": labeled_years,
                                "observed_record_year_min": min(labeled_years),
                                "observed_record_year_max": max(labeled_years),
                            }
                            if labeled_years
                            else {}
                        ),
                        **({"marker_values": marker_values} if marker_values else {}),
                        **(
                            {
                                "observed_terminal_marker_count": len(terminal_markers),
                                "observed_terminal_marker_values": terminal_markers,
                            }
                            if terminal_markers
                            else {}
                        ),
                    }
                    signature = json.dumps(fact, ensure_ascii=False, sort_keys=True)
                    groups[signature] = fact
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(observation)
    return list(groups.values())


def browser_derived_host_fact_text(observation: dict[str, Any]) -> str:
    """Render derived facts as short literal lines that the planner can quote exactly."""

    lines: list[str] = []
    for index, fact in enumerate(browser_derived_host_facts(observation), 1):
        lines.append(
            f"record group {index}: item class {fact.get('item_class_signature') or '(none)'}; "
            f"item tag {fact.get('item_tag') or '(none)'}; item count {fact['item_count']}."
        )
        years = fact.get("observed_record_year_values")
        if isinstance(years, list) and years:
            lines.append(
                f"record group {index}: observed record years "
                + ", ".join(str(value) for value in years)
                + f"; observed record year range {min(years)} to {max(years)}."
            )
        markers = fact.get("observed_terminal_marker_values")
        if isinstance(markers, list) and markers:
            lines.append(
                f"record group {index}: terminal marker count {len(markers)}; terminal marker values "
                + ", ".join(str(value) for value in markers)
                + "."
            )
    return "\n".join(lines) if lines else "No repeated record group was observed."


def planner_host_evidence_corpus(
    seed: dict[str, Any], observation: dict[str, Any]
) -> str:
    """Return the exact Host material from which planner evidence quotes may come."""

    return (
        str(seed.get("original_instruction", ""))
        + "\n"
        + json.dumps(
            compact_browser_evidence_for_llm(
                observation, include_known_selectors=False
            ),
            ensure_ascii=False,
        )
        + "\n"
        + browser_derived_host_fact_text(observation)
        + "\n"
        + source_context(seed["files"])
    )


def generate_edit_sequence(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    capability_bank: dict[str, Any],
    client: DocApiClient,
    request_id: str,
    ranked_effects: Iterable[RankedEffect] | None = None,
    retrieved_cards: Iterable[dict[str, Any]] | None = None,
    edit_count: int | None = DEFAULT_EDIT_COUNT,
    module_plan: Iterable[dict[str, Any]] | None = None,
    revision_candidate: dict[str, Any] | None = None,
    revision_feedback: str | None = None,
) -> dict[str, Any]:
    if edit_count is not None:
        edit_count = _validate_edit_count(edit_count)
    effect_rows = tuple(ranked_effects or ())
    retrieved_rows = tuple(retrieved_cards or ())
    donor_ids = (
        {str(row["capability_id"]) for row in retrieved_rows}
        if retrieved_rows
        else {str(row["id"]) for row in capability_bank["capabilities"]}
    )
    donor_ids.update(row.effect_family_id for row in effect_rows)
    stable = generation_stable_prefix(
        capability_bank,
        ranked_effects=effect_rows,
        retrieved_cards=retrieved_rows,
        edit_count=edit_count,
    )
    plan_rows = tuple(module_plan or ())
    task = generation_task(
        seed,
        observation,
        include_source=True,
        edit_count=edit_count,
        minimum_donor_edits=0,
        module_plan=plan_rows,
    )
    if revision_candidate is not None:
        if not revision_feedback:
            raise ValueError('candidate revision requires diagnosed feedback')
        task += (
            '\n\nPREVIOUS CANDIDATE TO REVISE\n' + json.dumps(revision_candidate, ensure_ascii=False)
            + '\n\nDIAGNOSED FEEDBACK\n' + revision_feedback
            + '\nReturn the complete corrected JSON, keeping the frozen modules, order and real dependencies. '
            'Correct the diagnosed problems and any directly related inconsistencies; do not replace the '
            'chain with unrelated tasks. Every evidence_quote must be a contiguous verbatim Host substring, '
            'not assembled from separate fields or another state. Review all clauses of each source claim. '
            'Keep only behavior within the frozen module goal.'
        )
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=GENERATION_SYSTEM,
        stable_context=stable,
        task=task,
        max_tokens=max(9000, (edit_count or MAX_EDIT_COUNT) * 1200),
        stream=True,
        cache_stable_context=False,
    )
    return validate_edit_sequence(
        normalize_repeated_instruction_openings(payload),
        seed_id=str(seed["seed_id"]),
        donor_ids=donor_ids,
        planner_cards=retrieved_rows,
        edit_count=edit_count,
        host_evidence_corpus=planner_host_evidence_corpus(seed, observation),
        module_plan=plan_rows,
    )


def validate_quality_audit(
    payload: dict[str, Any],
    *,
    seed_id: str,
    edit_count: int = DEFAULT_EDIT_COUNT,
) -> dict[str, Any]:
    edit_count = _validate_edit_count(edit_count)
    rows = payload.get("edits")
    if not isinstance(rows, list) or len(rows) != edit_count:
        raise ValueError(f"quality audit requires {edit_count} Edit rows")
    dimensions = (
        "source_grounding",
        "novelty",
        "product_naturalness",
        "specificity",
        "local_feasibility",
        "preservation",
        "dependency_correctness",
    )
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if row.get("edit_id") != f"q{index}":
            raise ValueError(f"quality audit ids must be q1..q{edit_count}")
        scores = row.get("scores")
        if not isinstance(scores, dict):
            raise ValueError("quality audit scores are missing")
        normalized_scores: dict[str, int] = {}
        for dimension in dimensions:
            value = scores.get(dimension)
            if not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f"invalid quality score: {dimension}")
            normalized_scores[dimension] = value
        decision = row.get("decision")
        if decision not in {"accept", "reject"}:
            raise ValueError("quality decision must be accept or reject")
        if decision == "accept" and min(normalized_scores.values()) < 4:
            raise ValueError("accepted Edit has a quality score below 4")
        issues = _string_list(
            row.get("issues"), label="quality issues", allow_empty=True
        )
        if decision == "accept" and issues:
            raise ValueError("accepted Edit still has quality issues")
        evidence = row.get("evidence")
        if isinstance(evidence, dict):
            # Some providers represent the three requested judgments as named fields.
            # Preserve them in the existing list schema without relaxing the verdict.
            fields = ("family_fit", "interaction_depth", "observable_acceptance")
            if set(evidence) != set(fields) or any(
                not isinstance(evidence[key], str) or not evidence[key].strip()
                for key in fields
            ):
                raise ValueError("quality evidence object must contain the three depth judgments")
            evidence = [f"{key}: {evidence[key]}" for key in fields]
        normalized.append(
            {
                "edit_id": row["edit_id"],
                "scores": normalized_scores,
                "decision": decision,
                "issues": issues,
                "evidence": _string_list(evidence, label="quality evidence"),
            }
        )
    sequence_decision = payload.get("sequence_decision")
    if sequence_decision not in {"accept", "reject"}:
        raise ValueError("sequence_decision must be accept or reject")
    if sequence_decision == "accept" and any(
        row["decision"] != "accept" for row in normalized
    ):
        raise ValueError("accepted sequence contains a rejected Edit")
    sequence_issues = payload.get("sequence_issues")
    if isinstance(sequence_issues, list):
        normalized_issues = []
        for issue in sequence_issues:
            if isinstance(issue, dict):
                if set(issue) != {"edit_id", "issue"} or issue["edit_id"] not in {
                    row["edit_id"] for row in normalized
                }:
                    raise ValueError("sequence issue object must reference a known Edit")
                issue = f"{issue['edit_id']}: {_nonempty_string(issue['issue'], label='sequence issue')}"
            normalized_issues.append(issue)
        sequence_issues = normalized_issues
    sequence_issues = _string_list(sequence_issues, label="sequence issues", allow_empty=True)
    if sequence_decision == "accept" and sequence_issues:
        raise ValueError("accepted sequence still has quality issues")
    return {
        "schema_version": "webcoding-linear-edit-query-audit-v1",
        "seed_id": seed_id,
        "sequence_decision": sequence_decision,
        "sequence_issues": sequence_issues,
        "edits": normalized,
    }


def audit_edit_sequence(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    sequence: dict[str, Any],
    client: DocApiClient,
    request_id: str,
) -> dict[str, Any]:
    edit_count = _validate_edit_count(int(sequence.get("edit_count", DEFAULT_EDIT_COUNT)))
    stable = (
        "AUDIT RUBRIC\n"
        "Score each dimension from 1 to 5. Accept only if every dimension is at least 4 and no hard "
        "problem is present. An accepted Edit must have an empty issues list, and an accepted sequence "
        "must have an empty sequence_issues list. A target implementation has not been generated, so do not "
        "assess implementation quality."
    )
    task = (
        "HOST SOURCE\n"
        + source_context(seed["files"])
        + "\n\nBROWSER EVIDENCE\n"
        + json.dumps(compact_browser_evidence_for_llm(observation), ensure_ascii=False)
        + "\n\nCANDIDATE SEQUENCE\n"
        + json.dumps(sequence, ensure_ascii=False)
        + f"\n\nReturn sequence_decision, sequence_issues, and {edit_count} edits. Each audit Edit needs "
        "edit_id, scores with source_grounding, novelty, product_naturalness, specificity, local_feasibility, "
        "preservation, dependency_correctness, plus decision, issues, and evidence."
        " In evidence, explain each task's completeness and how its core behavior resembles one of "
        "the official WebCompass families. Judge behavior, not exact category labels. Reject any task "
        "that is incomplete or outside these families, even if it matches the earlier frozen plan."
        " Keep evidence, issues and sequence_issues as lists of strings, not objects. "
        "For each Edit, give separate evidence "
        "statements for family fit, interaction depth, and "
        "observable acceptance. Explicitly identify the shared-state operations and the action/time -> "
        "changed result that would be tested. Evaluate the actual instruction, not capabilities implied "
        "only by its title, rationale, acceptance metadata, or prior approval. If family fit holds but "
        "interaction depth is shallow, reject with a concrete missing relationship, score specificity "
        "at most 3, and distinguish that from a wrong-family rejection. Apply the same standard to a "
        "frozen plan; name needs_replanning in issues when its goal is too narrow. Do not reject for "
        "omitting an optional feature if a different coherent combination supplies comparable depth."
    )
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=AUDIT_SYSTEM,
        stable_context=stable,
        task=task,
        max_tokens=9000,
        stream=True,
    )
    return validate_quality_audit(
        payload,
        seed_id=str(seed["seed_id"]),
        edit_count=edit_count,
    )


def load_json_response(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return parse_json_object(text)
    except ValueError as strict_error:
        rendered = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", rendered, re.DOTALL)
        if fenced:
            rendered = fenced.group(1)
        repaired: list[str] = []
        in_string = False
        escaped = False
        for index, character in enumerate(rendered):
            if character == '"' and not escaped:
                if not in_string:
                    in_string = True
                    repaired.append(character)
                else:
                    cursor = index + 1
                    while cursor < len(rendered) and rendered[cursor].isspace():
                        cursor += 1
                    following = rendered[cursor] if cursor < len(rendered) else ""
                    if following in {",", "}", "]", ":", ""}:
                        in_string = False
                        repaired.append(character)
                    else:
                        repaired.append('\\"')
                escaped = False
                continue
            repaired.append(character)
            if character == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        try:
            payload = json.loads("".join(repaired))
        except json.JSONDecodeError as repair_error:
            raise strict_error from repair_error
        if not isinstance(payload, dict):
            raise strict_error
        return payload


__all__ = [
    "AUDIT_SYSTEM",
    "DEFAULT_EDIT_COUNT",
    "EDIT_COUNT",
    "GENERATION_SYSTEM",
    "MAX_EDIT_COUNT",
    "MIN_EDIT_COUNT",
    "append_jsonl",
    "apply_exact_patches",
    "audit_edit_sequence",
    "build_seed_pool",
    "browser_derived_host_facts",
    "browser_derived_host_fact_text",
    "choose_sample",
    "compact_browser_evidence",
    "files_from_generate_record",
    "files_from_repaired_record",
    "generate_edit_sequence",
    "generation_task",
    "generation_stable_prefix",
    "load_json_response",
    "materialize_seed",
    "planner_host_evidence_corpus",
    "read_jsonl",
    "source_context",
    "validate_edit_sequence",
    "validate_quality_audit",
]
