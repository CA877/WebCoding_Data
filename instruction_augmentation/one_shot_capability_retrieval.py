"""Retrieve page-change cards once per Seed and attach exact donor source slices."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

from instruction_augmentation.dynamic_capability_retrieval import rank_capabilities
from instruction_augmentation.doc_api import DocApiClient
from instruction_augmentation.linear_edit_queries import (
    browser_derived_host_fact_text,
    compact_browser_evidence_for_llm,
    WEBCOMPASS_EDIT_POLICY,
)


_ELLIPSIS_RE = re.compile(r"(?:\.\.\.|…)")
_LANGUAGE_BY_SUFFIX = {
    ".astro": "astro",
    ".css": "css",
    ".html": "html",
    ".htm": "html",
    ".js": "javascript",
    ".jsx": "javascript",
    ".less": "less",
    ".mjs": "javascript",
    ".sass": "sass",
    ".scss": "scss",
    ".svelte": "svelte",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
}
_SOURCE_SUFFIXES = frozenset(_LANGUAGE_BY_SUFFIX) | {
    ".cjs",
    ".json",
    ".mdx",
}
_RETRIEVAL_QUERY_MAX_CHARS = 24_000
_LLM_RETRIEVAL_QUERY_MAX_CHARS = 8_000


def _module_state_tokens(value: str) -> set[str]:
    ignored = {"data", "id", "ids", "mode", "result", "results", "state", "value"}
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        if len(token) >= 3 and token not in ignored:
            tokens.add(token)
    return tokens


def _module_goal_covers_state(produces_state: str, goal: str) -> bool:
    state_tokens = _module_state_tokens(produces_state)
    goal_tokens = _module_state_tokens(goal)
    if not state_tokens:
        return False
    concepts = {
        "comparison": {"compar", "comparison", "pin", "side"},
        "density": {"compact", "density", "layout", "spacious"},
        "discovery": {"discover", "filter", "query", "search", "sort"},
        "distribution": {"chart", "count", "distribut", "distribution", "summary"},
        "filter": {"filter", "narrow", "query"},
        "focus": {"detail", "focus", "open"},
        "focused": {"detail", "focus", "open"},
        "highlight": {"differ", "highlight"},
        "print": {"export", "print", "printer"},
        "query": {"discover", "filter", "query", "search", "sort"},
        "range": {"between", "range", "span"},
        "saved": {"bookmark", "save", "store"},
        "selected": {"choose", "mark", "pin", "select"},
        "selection": {"choose", "mark", "pin", "select"},
        "timeline": {"chronological", "timeline"},
    }
    for token in state_tokens:
        alternatives = concepts.get(token)
        if (
            alternatives is not None
            and token not in goal_tokens
            and not (alternatives & goal_tokens)
        ):
            return False
    generic = {"artifact", "card", "collection", "item", "record"}
    specific_tokens = state_tokens - generic
    return bool(
        (specific_tokens & goal_tokens)
        or any(concepts.get(token, set()) & goal_tokens for token in specific_tokens)
    )


RETRIEVAL_QUERY_SYSTEM = """You write one semantic retrieval query and a compact Edit module plan for an existing frontend host.
Use only the supplied original request and saved browser observations. Summarize the product domain, observed
business objects, meaningful states and interactions, information organization, visual treatment, responsive
behavior, and deeper states exposed by exploration. Then describe structurally compatible kinds of complete
page changes that would be natural next additions. Cover functional, visual, layout, navigation, information,
and direct-manipulation directions only where they fit the host; do not choose a particular library card or
invent remote data, accounts, routes, or backends. A possible change must be a complete user goal rather than
an isolated button, event handler, CSS property, or generic quality improvement. Do not mention donors, source
code, selectors, datasets, benchmarks, or internal pipeline details. Merge search, filters, sorting, counts,
empty results, ranges, and reset for the same record surface into one discovery module. After creating that
module, do not plan another range filter, result summary, count, empty state, or reset for the same surface;
replace it with a different complete user goal, or report that the requested count is unsupported. Follow the supplied
module count, without preferring eight. Use one to three real dependencies: a dependent module must consume a named state produced
by an earlier module, and its visible goal must become impossible if the producer is removed. Every other module
must be expressible from the observed Host alone and must not mention planned controls or states. Do not use a
theme switch, guided tour, reading progress, back-to-top button, or shortcut overlay as a filler module. Return
one JSON object only. Ground every module in one short verbatim quote from the supplied Host evidence. Each
dependent module may depend on exactly one prior module; copy that producer's produces_state character for
character into consumes_state and name the same state in reverse_failure. Every module, including independent
ones, must declare its own non-empty produces_state. The producer owns the consumed state; the dependent module
must produce a different new state. Name the meaningful concepts from produces_state explicitly in that row's
goal; do not claim a selection, filter, saved value, or mode that the goal never asks the user to create. Only
propose a user goal that the observed source does not already support. Comparison, timeline, print, and export
modules are not dependent on discovery merely because they can use currently visible records; they can operate
on the base records. Select complete family-level capabilities first, then connect real state consumption;
never select save/restore/export utilities just to manufacture dependencies. A local-only Host may create an inquiry draft or on-page confirmation, but
must not claim to send or submit a request to an external organization without observed backend support. Prefer
one strong dependent module for a short chain; add others only for distinct complete user goals. Small confirmation,
validation, empty, loading, and error feedback belong inside their parent module; full Async Form Validation,
Skeleton Loading, or Notification Center capabilities may be distinct tasks when their core behavior is specified. A
saved discovery configuration is a saved view or saved discovery configuration, not an inquiry draft."""


def _unique_texts(*values: Any) -> list[str]:
    rows: list[str] = []
    for value in values:
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = [item for item in value if isinstance(item, str)]
        else:
            candidates = []
        for candidate in candidates:
            rendered = candidate.strip()
            if rendered and rendered not in rows:
                rows.append(rendered)
    return rows


def compact_planner_card(
    card: dict[str, Any], *, source_slices: list[dict[str, Any]]
) -> dict[str, Any]:
    """Keep only the fields consumed by embedding recall and Q1-Q5 planning.

    Older pools split dependency information across prerequisites/state_reads and
    state_writes.  They are adapted here so immutable historical pools remain
    usable while every new retrieval artifact has one small schema.
    """

    capability_id = str(card.get("capability_id", "")).strip()
    if not capability_id:
        raise ValueError("capability_id is required")
    summary = str(card.get("summary", "")).strip()
    visible_result = str(card.get("visible_result", "")).strip()
    if not summary or not visible_result:
        raise ValueError(f"planner card lacks a summary or visible result: {capability_id}")
    return {
        "capability_id": capability_id,
        "change_type": str(
            card.get("change_type") or card.get("family") or "unspecified"
        ).strip(),
        "summary": summary,
        "requires": _unique_texts(
            card.get("requires"),
            card.get("prerequisites"),
            card.get("state_reads"),
        ),
        "user_actions": _unique_texts(
            card.get("user_actions"), card.get("user_action")
        ),
        "produces": _unique_texts(card.get("produces"), card.get("state_writes")),
        "visible_result": visible_result,
        "future_uses": _unique_texts(card.get("future_uses")),
        "source_slices": source_slices,
    }


def _compact_text(value: Any, *, limit: int) -> str:
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    rendered = rendered.strip()
    if len(rendered) <= limit:
        return rendered
    digest = sha256(rendered.encode("utf-8")).hexdigest()[:16]
    marker = f"\n[middle omitted; sha256={digest}]\n"
    remaining = max(2, limit - len(marker))
    prefix_length = remaining // 2
    suffix_length = remaining - prefix_length
    return rendered[:prefix_length] + marker + rendered[-suffix_length:]


def _coverage_indices(size: int, count: int) -> list[int]:
    if size <= 0 or count <= 0:
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


def _bounded_json_value(
    value: Any, *, string_limit: int = 220, list_limit: int = 8, dict_limit: int = 16
) -> Any:
    """Process every fact, deduplicate lists, then keep spread coverage samples.

    This intentionally never uses DOM-order front-N slicing.  When a list is
    too repetitive for an embedding query, the query retains its total,
    unique count, evenly spread samples, and a digest of all normalized rows.
    """

    if isinstance(value, str):
        return _compact_text(value, limit=string_limit)
    if isinstance(value, list):
        normalized = [
            _bounded_json_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in value
        ]
        unique: list[Any] = []
        signatures: list[str] = []
        seen: set[str] = set()
        for item in normalized:
            signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            signatures.append(signature)
            unique.append(item)
        if len(unique) <= list_limit:
            return unique
        serialized = json.dumps(signatures, ensure_ascii=False, separators=(",", ":"))
        return {
            "total_count": len(value),
            "unique_count": len(unique),
            "coverage_samples": [
                unique[index] for index in _coverage_indices(len(unique), list_limit)
            ],
            "all_values_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
        }
    if isinstance(value, dict):
        return {
            str(key): _bounded_json_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    return value


def _embedding_browser_evidence(observation: dict[str, Any]) -> dict[str, Any]:
    """Create a small retrieval view; complete browser evidence stays on disk."""

    facts = compact_browser_evidence_for_llm(
        observation,
        include_known_selectors=False,
    )
    baseline = facts.get("baseline") if isinstance(facts.get("baseline"), dict) else {}
    compact: dict[str, Any] = {
        "status": facts.get("status"),
        "baseline": {
            "title": _compact_text(baseline.get("title", ""), limit=240),
            "url": _compact_text(baseline.get("url", ""), limit=400),
            "visible_text": _compact_text(
                baseline.get("visible_text", ""), limit=1200
            ),
            "accessibility_tree": _compact_text(
                baseline.get("accessibility_tree", ""), limit=1200
            ),
            "interactive_controls": _bounded_json_value(
                baseline.get("interactive_controls", []),
                string_limit=180,
                list_limit=16,
                dict_limit=12,
            ),
            "interactive_control_total": baseline.get(
                "interactive_control_total"
            ),
            "structures": _bounded_json_value(
                baseline.get("structures", []),
                string_limit=180,
                list_limit=10,
                dict_limit=8,
            ),
            "local_storage": _bounded_json_value(
                baseline.get("local_storage", {}), string_limit=240, dict_limit=12
            ),
            "session_storage": _bounded_json_value(
                baseline.get("session_storage", {}),
                string_limit=240,
                dict_limit=12,
            ),
            "viewport": baseline.get("viewport"),
            "horizontal_overflow": baseline.get("horizontal_overflow"),
            "landmark_layouts": _bounded_json_value(
                baseline.get("landmark_layouts", []), list_limit=6, dict_limit=12
            ),
            "aria_states": _bounded_json_value(
                baseline.get("aria_states", []), list_limit=8, dict_limit=10
            ),
            "visual_surfaces": _bounded_json_value(
                baseline.get("visual_surfaces", []), list_limit=6, dict_limit=10
            ),
            "style_samples": _bounded_json_value(
                baseline.get("style_samples", []), list_limit=5, dict_limit=12
            ),
            "root_css_variables": _bounded_json_value(
                baseline.get("root_css_variables", {}), dict_limit=12
            ),
        },
        "remote_requests": _bounded_json_value(
            facts.get("remote_requests", []), list_limit=5
        ),
        "console_errors": _bounded_json_value(
            facts.get("console_errors", []), list_limit=5
        ),
        "page_errors": _bounded_json_value(
            facts.get("page_errors", []), list_limit=5
        ),
        "dialog_events": _bounded_json_value(
            facts.get("dialog_events", []), list_limit=5
        ),
        "visual_routing": _bounded_json_value(
            facts.get("visual_routing", {}), dict_limit=12
        ),
    }
    mobile = facts.get("mobile_difference")
    if isinstance(mobile, dict):
        compact["mobile_difference"] = _bounded_json_value(
            mobile, string_limit=320, list_limit=5, dict_limit=12
        )
    delta_catalog = {
        str(row.get("delta_id")): row
        for row in facts.get("state_delta_catalog", [])
        if isinstance(row, dict) and row.get("delta_id")
    }
    transition_rows: list[dict[str, Any]] = []
    for path in facts.get("transitions", []):
        if not isinstance(path, dict):
            continue
        refs = path.get("state_delta_refs")
        if not isinstance(refs, list) or not refs:
            continue
        deltas = [delta_catalog[str(ref)] for ref in refs if str(ref) in delta_catalog]
        if not deltas:
            continue
        transition_rows.append(
            {
                "id": _compact_text(path.get("id", ""), limit=160),
                "purpose": _compact_text(path.get("purpose", ""), limit=260),
                "status": path.get("status"),
                "state_deltas": _bounded_json_value(
                    deltas, string_limit=240, list_limit=4, dict_limit=16
                ),
            }
        )
    compact["transitions"] = _bounded_json_value(
        transition_rows, string_limit=240, list_limit=12, dict_limit=16
    )
    compact["transition_path_total"] = len(transition_rows)
    return compact


def _flatten_query_facts(value: Any, *, prefix: str = "") -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, item in sorted(value.items(), key=lambda row: str(row[0])):
            child = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_query_facts(item, prefix=child))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_flatten_query_facts(item, prefix=prefix))
    elif value not in (None, ""):
        rows.append(f"{prefix}={_compact_text(value, limit=180)}")
    return rows


def _all_fact_coverage(value: Any, *, sample_count: int) -> dict[str, Any]:
    unique = sorted(set(_flatten_query_facts(value)))
    serialized = json.dumps(unique, ensure_ascii=False, separators=(",", ":"))
    return {
        "unique_fact_count": len(unique),
        "coverage_samples": [
            unique[index]
            for index in _coverage_indices(len(unique), sample_count)
        ],
        "all_facts_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _serialize_retrieval_query(payload: dict[str, Any]) -> str:
    return (
        "HOST PAGE FACTS\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\nRETRIEVAL GOAL\nFind page changes whose required business roles can be mapped to this "
        "host. Include functional behavior, interaction, information organization, responsive layout, "
        "visual style, and accessibility changes. Prefer changes that can use local data and can support "
        "natural later edits."
    )


def build_seed_retrieval_query(
    *, seed: dict[str, Any], observation: dict[str, Any]
) -> str:
    """Build a low-cost embedding query from the instruction and browser facts only."""

    original_instruction = str(seed.get("original_instruction", ""))
    design_marker = "Web design document:"
    if design_marker in original_instruction:
        original_instruction = original_instruction.split(design_marker, 1)[1]
    query_payload = {
        "seed_id": seed.get("seed_id"),
        "original_instruction": _compact_text(original_instruction, limit=2500),
        "page_type": seed.get("page_type"),
        "browser_evidence": _embedding_browser_evidence(observation),
        "browser_derived_host_facts": browser_derived_host_fact_text(observation),
    }
    rendered = _serialize_retrieval_query(query_payload)
    if len(rendered) > _RETRIEVAL_QUERY_MAX_CHARS:
        full_browser_evidence = query_payload["browser_evidence"]
        for sample_count in (80, 48, 24):
            query_payload["browser_evidence"] = {
                "status": full_browser_evidence.get("status"),
                "all_observed_fact_coverage": _all_fact_coverage(
                    full_browser_evidence, sample_count=sample_count
                ),
            }
            rendered = _serialize_retrieval_query(query_payload)
            if len(rendered) <= _RETRIEVAL_QUERY_MAX_CHARS:
                break
    if len(rendered) > _RETRIEVAL_QUERY_MAX_CHARS:
        raise ValueError("retrieval query exceeds its hard character budget")
    return rendered


def validate_generated_retrieval_query(payload: dict[str, Any]) -> str:
    query = payload.get("retrieval_query")
    if not isinstance(query, str) or len(query.strip()) < 200:
        raise ValueError("retrieval_query must be a substantive string")
    query = query.strip()
    if len(query) > _LLM_RETRIEVAL_QUERY_MAX_CHARS:
        raise ValueError("retrieval_query exceeds its hard character budget")
    forbidden = re.compile(
        r"\b(?:donor|dataset|benchmark|source code|CSS selector|DOM selector|AX tree)\b",
        re.I,
    )
    if forbidden.search(query):
        raise ValueError("retrieval_query leaks internal planning terminology")
    return query


def validate_generated_retrieval_plan(
    payload: dict[str, Any], *, host_evidence_corpus: str | None = None
) -> dict[str, Any]:
    query = validate_generated_retrieval_query(payload)
    rows = payload.get("module_plan")
    if not isinstance(rows, list) or not 4 <= len(rows) <= 12:
        raise ValueError("module_plan must contain 4 to 12 modules")
    normalized: list[dict[str, Any]] = []
    dependent_ids: list[str] = []
    produced_states: dict[str, str] = {}
    prior_independent_signals: list[tuple[str, str]] = []
    normalized_host_evidence = (
        re.sub(
            r"\s+",
            " ",
            host_evidence_corpus.replace("\\n", " ")
            .replace("\\r", " ")
            .replace("\\t", " "),
        )
        .strip()
        .lower()
        if host_evidence_corpus is not None
        else None
    )
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError("every module_plan row must be an object")
        edit_id = str(row.get("edit_id") or "").strip()
        if edit_id != f"q{index}":
            raise ValueError("module_plan edit_ids must be q1 through qN in order")
        title = str(row.get("title") or "").strip()
        host_region = str(row.get("host_region") or "").strip()
        goal = str(row.get("goal") or "").strip()
        produces_state = str(row.get("produces_state") or "").strip()
        host_evidence_quote = str(row.get("host_evidence_quote") or "").strip()
        source_gap = str(row.get("source_gap") or "").strip()
        if min(len(title), len(host_region), len(produces_state)) < 3 or len(goal) < 20:
            raise ValueError(f"{edit_id} module plan lacks a specific region, goal, or output state")
        if len(source_gap) < 20:
            raise ValueError(f"{edit_id} module plan lacks a specific source gap")
        if re.search(
            r"\b(?:already|currently)\s+(?:has|supports|provides|implements)\b",
            source_gap,
            re.I,
        ):
            raise ValueError(f"{edit_id} proposes behavior described as already present")
        if len(host_evidence_quote) < 4:
            raise ValueError(f"{edit_id} module plan requires a Host evidence quote")
        if not _module_goal_covers_state(produces_state, goal):
            raise ValueError(
                f"{edit_id}.goal does not describe its own produces_state"
            )
        if normalized_host_evidence is not None and re.sub(
            r"\s+", " ", host_evidence_quote
        ).strip().lower() not in normalized_host_evidence:
            raise ValueError(f"{edit_id} module plan Host evidence quote is absent")
        raw_dependencies = row.get("depends_on", [])
        if isinstance(raw_dependencies, str):
            raw_dependencies = re.findall(r"\bq\d+\b", raw_dependencies)
        if not isinstance(raw_dependencies, list):
            raise ValueError(f"{edit_id}.depends_on must be a list")
        dependencies = [str(value).strip() for value in raw_dependencies if str(value).strip()]
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(f"{edit_id}.depends_on contains duplicates")
        if len(dependencies) > 1:
            raise ValueError(f"{edit_id} module plan may consume exactly one prior module")
        allowed = {f"q{prior}" for prior in range(1, index)}
        if not set(dependencies).issubset(allowed):
            raise ValueError(f"{edit_id} module plan depends on a non-prior module")
        consumes_state = str(row.get("consumes_state") or "").strip()
        reverse_failure = str(row.get("reverse_failure") or "").strip()
        if dependencies:
            dependent_ids.append(edit_id)
            if len(consumes_state) < 3 or len(reverse_failure) < 20:
                raise ValueError(
                    f"{edit_id} dependent module must name consumed state and reverse-order failure"
                )
            expected_state = produced_states[dependencies[0]]
            if consumes_state != expected_state:
                raise ValueError(
                    f"{edit_id}.consumes_state must exactly copy {dependencies[0]}.produces_state"
                )
            if produces_state == consumes_state:
                raise ValueError(
                    f"{edit_id} dependent module must produce a new state"
                )
            readable_state = re.sub(r"[_\s-]+", " ", consumes_state).lower()
            readable_reverse = re.sub(r"[_\s-]+", " ", reverse_failure).lower()
            if readable_state not in readable_reverse:
                raise ValueError(
                    f"{edit_id}.reverse_failure must name the consumed state"
                )
        elif consumes_state or reverse_failure:
            raise ValueError(f"{edit_id} independent module must not claim prior-state consumption")
        else:
            normalized_goal = re.sub(r"[_\s-]+", " ", goal).lower()
            for prior_edit, signal in prior_independent_signals:
                normalized_signal = re.sub(r"[_\s-]+", " ", signal).lower()
                if len(normalized_signal) >= 4 and normalized_signal in normalized_goal:
                    raise ValueError(
                        f"{edit_id} independent module mentions planned output from {prior_edit}"
                    )
        if re.search(
            r"\b(?:theme switch|guided tour|reading progress|back[- ]to[- ]top|shortcut overlay)\b",
            title + " " + goal,
            re.I,
        ):
            raise ValueError(f"{edit_id} is a generic filler module")
        if dependencies and re.search(
            r"\b(?:comparison|timeline|print|export)\b", title + " " + goal, re.I
        ) and re.search(r"\b(?:discovery|filter|visible).*(?:criteria|ids?|items?|records?|results?|set)\b", consumes_state, re.I):
            raise ValueError(
                f"{edit_id} uses a discovery result only as a weak dependency"
            )
        if re.search(r"\b(?:send|submit)\w*\b", goal, re.I) and re.search(
            r"\b(?:inquiry|request|message)\b", goal, re.I
        ) and not re.search(r"\b(?:client-side|draft|local|on-page)\b", goal, re.I):
            raise ValueError(f"{edit_id} assumes an unobserved external submission")
        if re.search(r"\b(?:confirmation|feedback|message|toast)\b", title, re.I) and not re.search(
            r"\b(?:create|edit|manage|recover|restore|retry)\b", goal, re.I
        ):
            raise ValueError(f"{edit_id} is feedback split out as a micro-Edit")
        if dependencies and re.search(r"\bdiscovery\b", consumes_state, re.I) and re.search(
            r"\binquiry draft\b", goal, re.I
        ):
            raise ValueError(
                f"{edit_id} gives a saved discovery state an unrelated product meaning"
            )
        normalized.append(
            {
                "edit_id": edit_id,
                "title": title,
                "host_region": host_region,
                "goal": goal,
                "produces_state": produces_state,
                "host_evidence_quote": host_evidence_quote,
                "source_gap": source_gap,
                "depends_on": dependencies,
                "consumes_state": consumes_state,
                "reverse_failure": reverse_failure,
            }
        )
        produced_states[edit_id] = produces_state
        prior_independent_signals.append((edit_id, produces_state))
    if len({row["title"].lower() for row in normalized}) != len(normalized):
        raise ValueError("module_plan contains duplicate module titles")
    if len({row["produces_state"] for row in normalized}) != len(normalized):
        raise ValueError("module_plan contains duplicate output states")
    primary_discovery_regions = {
        re.sub(r"\W+", " ", row["host_region"].lower()).strip()
        for row in normalized
        if len(re.findall(r"\b(?:search|filter|sort)\w*\b", row["goal"], re.I)) >= 2
        and not re.search(r"\b(?:export|restore|save)\w*\b", row["goal"], re.I)
    }
    for row in normalized:
        region = re.sub(r"\W+", " ", row["host_region"].lower()).strip()
        if region not in primary_discovery_regions:
            continue
        goal = row["goal"]
        if re.search(r"\b(?:export|restore|save)\w*\b", goal, re.I):
            continue
        if len(re.findall(r"\b(?:search|filter|sort)\w*\b", goal, re.I)) >= 2:
            continue
        if re.search(r"\b(?:narrow|filter|search|sort)\w*\b", goal, re.I) or re.search(
            r"\b(?:empty|reset|result summary)\b|\bmatch(?:es|ing)?\b.{0,40}\bquery\b",
            goal,
            re.I,
        ):
            raise ValueError(
                f"{row['edit_id']} duplicates a subgoal owned by the discovery module"
            )
    discovery_edit_ids = {
        row["edit_id"]
        for row in normalized
        if len(re.findall(r"\b(?:search|filter|sort)\w*\b", row["goal"], re.I)) >= 2
        and not re.search(r"\b(?:export|restore|save)\w*\b", row["goal"], re.I)
    }
    for row in normalized:
        if row["depends_on"] or not discovery_edit_ids:
            continue
        if re.search(
            r"\b(?:currently visible|filtered (?:items|records|results)|matching (?:items|records|results)|discovery results?)\b",
            row["goal"],
            re.I,
        ):
            raise ValueError(
                f"{row['edit_id']} is independent but implicitly consumes discovery output"
            )
    if not 1 <= len(dependent_ids) <= 3:
        raise ValueError("module_plan must contain one to three dependent modules")
    dependency_plan = payload.get("dependency_plan")
    if dependency_plan != dependent_ids:
        raise ValueError("dependency_plan must exactly list dependent module ids in order")
    return {
        "retrieval_query": query,
        "dependency_plan": dependent_ids,
        "module_plan": normalized,
    }


def generate_seed_retrieval_plan(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    client: DocApiClient,
    request_id: str,
    retrieved_cards: Iterable[dict[str, Any]] = (),
    edit_count: int | None = None,
    retrieval_query: str | None = None,
) -> dict[str, Any]:
    """Use the existing retrieval-query call to freeze module boundaries and dependencies."""

    evidence_context = build_seed_retrieval_query(seed=seed, observation=observation)
    if edit_count is not None and not 4 <= edit_count <= 12:
        raise ValueError("edit_count must be 4 to 12")
    cards = [compact_planner_card(row, source_slices=[]) for row in retrieved_cards]
    planning_context = evidence_context + "\nRetrieved inspiration (not Host facts):\n" + json.dumps(cards, ensure_ascii=False)
    count_instruction = (
        f"Plan exactly {edit_count} complete modules. " if edit_count is not None else
        "Choose 4 to 12 complete modules based on the Host and retrieved inspiration; do not prefer eight. "
    )
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=RETRIEVAL_QUERY_SYSTEM + WEBCOMPASS_EDIT_POLICY,
        stable_context=planning_context,
        task=(
            "Return retrieval_query, dependency_plan, and module_plan. Each module_plan row must contain "
            "edit_id, title, host_region, goal, produces_state, host_evidence_quote, source_gap, depends_on, "
            "consumes_state, and reverse_failure. host_evidence_quote must be a short verbatim substring "
            "of the supplied original request or browser evidence. Use q1 through qN in linear order. "
            + count_instruction +
            "Choose module goals AFTER considering the retrieved cards. Transfer useful object-action-state "
            "patterns across domains; a module may create the UI needed to use that inspiration. "
            "Do not treat card content as proof of existing Host behavior. "
            "Every row needs its own non-empty produces_state and a specific source_gap explaining which user "
            "goal is absent. First merge controls acting on one result surface, then choose one to three later modules "
            "whose user-visible result truly consumes exactly one earlier produces_state; copy that state "
            "character for character into consumes_state. Write reverse_failure as a full explanatory sentence "
            "naming that state and the concrete downstream action or result that becomes impossible without it; "
            "a bare state name is not an explanation. Leave consumes_state and "
            "reverse_failure empty for every independent module. The dependent module must produce a new state, "
            "not the state it consumes. For example, in an unrelated clinic booking product, a complete "
            "multi-step appointment wizard can produce local_appointment_records; a later full notification "
            "center can consume local_appointment_records to create an appointment_notification_inbox with "
            "unread state, grouped event entries, dismiss/read actions and relevant navigation. The wizard "
            "already owns its own confirmation; the inbox must be a distinct complete capability. "
            "One strong dependency suffices for a four-module chain. dependency_plan must exactly equal "
            "the Edit IDs with non-empty depends_on. "
            "Do not make comparison, timeline, print, or export depend on discovery merely because it can use "
            "visible records. Conversely, an independent later module must not say 'currently visible', 'filtered', "
            "'matching', or 'discovery results'; scope it to the base Host records. Do not claim that a form sends "
            "or submits to an external organization; use a local "
            "draft or on-page confirmation unless backend support appears in Host evidence. "
            "Before returning, review each goal for a real fit to one official family: express the core "
            "behavior in goal, not merely a family label. Merge saving and restoring a configuration into "
            "its owning task. A comparison/export panel alone is not an official-family task. Replace "
            "such weak modules with a complete fitting capability, not a renamed micro-feature. "
            "Before freezing, evaluate family fit and interaction depth separately. Each goal must name "
            "the coherent operations, their shared state and visible interaction outcome, including the "
            "source/update relationship for time-driven capabilities. Do not leave the essential "
            "relationships to be guessed during expansion. Revise a shallow goal now, before fixing "
            "its dependencies; do not substitute labels, extra clauses, or arbitrary new business data. "
            "Write retrieval_query in English for the English capability pool."
        ),
        max_tokens=4000,
        stream=True,
        cache_stable_context=False,
    )
    if retrieval_query is not None:
        payload["retrieval_query"] = retrieval_query
    result = validate_generated_retrieval_plan(
        payload, host_evidence_corpus=evidence_context
    )
    if edit_count is not None and len(result["module_plan"]) != edit_count:
        raise ValueError("module_plan does not match requested edit_count")
    return result


def generate_seed_retrieval_query(
    *,
    seed: dict[str, Any],
    observation: dict[str, Any],
    client: DocApiClient,
    request_id: str,
) -> str:
    """Ask one LLM to turn bounded host evidence into the embedding query."""

    evidence_context = build_seed_retrieval_query(seed=seed, observation=observation)
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=("Write a semantic retrieval query from the Host original request and observed browser facts. "
                       "Describe the domain, objects, existing abilities, and useful functional or visual directions. "
                       "Do not freeze module goals or dependencies before seeing retrieved inspiration. "
                       "Do not invent existing fields, backend services, or observed behavior. Return JSON only."
                       + WEBCOMPASS_EDIT_POLICY),
        stable_context=evidence_context,
        task=(
            "Return {\"retrieval_query\": \"...\"}. Write the query in English because the "
            "current capability pool is English. Make it specific enough to retrieve several "
            "different complete feature modules for this host, without naming any unseen card."
        ),
        max_tokens=1800,
        stream=True,
        cache_stable_context=False,
    )
    return validate_generated_retrieval_query(payload)


def _safe_evidence_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source evidence path is missing")
    path = PurePosixPath(value.strip())
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe source evidence path: {value}")
    return path


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _evidence_anchors(evidence: str) -> list[str]:
    candidates = [evidence]
    candidates.extend(part.strip() for part in _ELLIPSIS_RE.split(evidence))
    candidates.extend(
        match.strip()
        for match in re.findall(
            r"(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*\s*\([^\n]{0,180}?\)",
            evidence,
        )
    )
    candidates.extend(
        match.strip()
        for match in re.findall(r"[`'\"]([^`'\"]{4,160})[`'\"]", evidence)
    )
    unique: list[str] = []
    for candidate in sorted(candidates, key=len, reverse=True):
        if len(_normalized(candidate)) < 10 or candidate in unique:
            continue
        unique.append(candidate)
    return unique


def _line_span_for_exact(source: str, matched: str) -> tuple[int, int] | None:
    offset = source.find(matched)
    if offset < 0:
        return None
    start = source.count("\n", 0, offset) + 1
    end = start + matched.count("\n")
    return start, end


def _locate_evidence(lines: list[str], evidence: str) -> tuple[int, int, str, float] | None:
    source = "\n".join(lines)
    exact = _line_span_for_exact(source, evidence)
    if exact is not None:
        return (*exact, "exact", 1.0)
    evidence_norm = _normalized(evidence)
    anchors = _evidence_anchors(evidence)
    best: tuple[int, int, str, float] | None = None
    max_width = min(12, max(1, len(lines)))
    for anchor in anchors:
        anchor_norm = _normalized(anchor)
        method = "normalized_evidence" if anchor == evidence else "evidence_anchor"
        confidence = min(1.0, len(anchor_norm) / max(1, len(evidence_norm)))
        for start in range(len(lines)):
            for width in range(1, min(max_width, len(lines) - start) + 1):
                chunk_norm = _normalized("\n".join(lines[start : start + width]))
                if anchor_norm not in chunk_norm:
                    continue
                candidate = (start + 1, start + width, method, confidence)
                if best is None or candidate[3] > best[3]:
                    best = candidate
                break
    return best


def compile_donor_snippets(
    card: dict[str, Any], *, context_lines: int = 4, max_snippets: int = 2
) -> list[dict[str, Any]]:
    """Resolve old evidence locators to exact framework-independent source slices."""

    if context_lines < 0 or max_snippets < 1:
        raise ValueError("invalid donor snippet limits")
    source_project = Path(str(card.get("source_project", ""))).expanduser()
    if not source_project.is_dir():
        return []
    project_root = source_project.resolve()
    rows = card.get("source_evidence")
    if not isinstance(rows, list):
        return []
    snippets: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for evidence_index, evidence_row in enumerate(rows, 1):
        if len(snippets) >= max_snippets or not isinstance(evidence_row, dict):
            break
        try:
            relative = _safe_evidence_path(evidence_row.get("path"))
        except ValueError:
            continue
        evidence = evidence_row.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        source_path = (project_root / relative.as_posix()).resolve()
        try:
            source_path.relative_to(project_root)
        except ValueError:
            continue
        if not source_path.is_file() or source_path.stat().st_size > 4_000_000:
            continue
        source = source_path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        located = _locate_evidence(lines, evidence)
        if located is None:
            continue
        anchor_start, anchor_end, method, confidence = located
        start_line = max(1, anchor_start - context_lines)
        end_line = min(len(lines), anchor_end + context_lines)
        key = (relative.as_posix(), start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        content = "\n".join(lines[start_line - 1 : end_line])
        snippet_hash = sha256(content.encode("utf-8")).hexdigest()
        snippets.append(
            {
                "slice_id": f"{card['capability_id']}__slice_{evidence_index}",
                "path": relative.as_posix(),
                "start_line": start_line,
                "end_line": end_line,
                "language": _LANGUAGE_BY_SUFFIX.get(source_path.suffix.lower(), "text"),
                "locator_method": method,
                "locator_confidence": round(confidence, 6),
                "sha256": snippet_hash,
                "content": content,
            }
        )
    return snippets


def _source_files(project_root: Path) -> list[Path]:
    return [
        path
        for path in sorted(project_root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in _SOURCE_SUFFIXES
        and not any(part in {".git", "node_modules", "dist", "build"} for part in path.parts)
        and path.stat().st_size <= 4_000_000
    ]


def _source_anchor_variants(card: dict[str, Any]) -> list[tuple[str, str, float]]:
    variants: list[tuple[str, str, float]] = []

    def add(value: str, method: str, confidence: float) -> None:
        rendered = value.strip()
        if rendered and rendered not in {row[0] for row in variants}:
            variants.append((rendered, method, confidence))

    for anchor in _unique_texts(card.get("source_anchors")):
        add(anchor, "exact_browser_anchor", 1.0)
        for identifier in re.findall(r"#([A-Za-z_][A-Za-z0-9_-]*)", anchor):
            add(identifier, "runtime_selector_id", 0.95)
        if anchor.startswith("#/"):
            route = anchor[1:].split("?", 1)[0]
            add(route, "runtime_route_path", 0.95)

    local_id = str(card.get("capability_id", "")).rsplit("__", 1)[-1]
    generic_tokens = {
        "design",
        "filter",
        "layout",
        "navigation",
        "responsive",
        "state",
        "system",
        "toggle",
        "view",
    }
    for token in local_id.split("_"):
        if len(token) >= 5 and token not in generic_tokens:
            add(token, "capability_token", 0.7)

    if str(card.get("change_type", "")) == "layout" or str(
        card.get("family", "")
    ) == "responsive":
        add("@media", "layout_source_pattern", 0.8)
        add("minmax(", "layout_source_pattern", 0.75)
    return variants


def _compile_anchor_slices(
    card: dict[str, Any], *, context_lines: int, max_snippets: int
) -> list[dict[str, Any]]:
    project = Path(str(card.get("source_project", ""))).expanduser()
    if not project.is_dir():
        return []
    project_root = project.resolve()
    anchors = _source_anchor_variants(card)
    slices: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for anchor_index, (anchor, locator_method, locator_confidence) in enumerate(anchors, 1):
        if len(slices) >= max_snippets:
            break
        for source_path in _source_files(project_root):
            source = source_path.read_text(encoding="utf-8", errors="replace")
            offset = source.find(anchor)
            if offset < 0:
                offset = source.casefold().find(anchor.casefold())
                if offset < 0:
                    continue
                effective_method = f"casefold_{locator_method}"
                effective_confidence = locator_confidence * 0.95
            else:
                effective_method = locator_method
                effective_confidence = locator_confidence
            lines = source.splitlines()
            anchor_start = source.count("\n", 0, offset) + 1
            anchor_end = anchor_start + anchor.count("\n")
            start_line = max(1, anchor_start - context_lines)
            end_line = min(len(lines), anchor_end + context_lines)
            relative = source_path.relative_to(project_root).as_posix()
            key = (relative, start_line, end_line)
            if key in seen:
                continue
            seen.add(key)
            content = "\n".join(lines[start_line - 1 : end_line])
            slices.append(
                {
                    "slice_id": f"{card['capability_id']}__slice_anchor_{anchor_index}",
                    "path": relative,
                    "start_line": start_line,
                    "end_line": end_line,
                    "language": _LANGUAGE_BY_SUFFIX.get(
                        source_path.suffix.lower(), "text"
                    ),
                    "locator_method": effective_method,
                    "locator_confidence": effective_confidence,
                    "sha256": sha256(content.encode("utf-8")).hexdigest(),
                    "content": content,
                }
            )
            break
    return slices


def compile_source_slices(
    card: dict[str, Any], *, context_lines: int = 4, max_slices: int = 2
) -> list[dict[str, Any]]:
    """Attach real source text from any supported frontend source-file format."""

    existing = card.get("source_slices")
    if isinstance(existing, list) and existing:
        return [dict(row) for row in existing if isinstance(row, dict)][:max_slices]
    located = compile_donor_snippets(
        card, context_lines=context_lines, max_snippets=max_slices
    )
    if located:
        return located
    return _compile_anchor_slices(
        card, context_lines=context_lines, max_snippets=max_slices
    )


def retrieve_top_k_with_source_slices(
    *,
    query_vector: list[float],
    embedded_pool: Iterable[dict[str, Any]],
    host_seed_id: str,
    top_k: int,
    max_per_family: int = 2,
) -> list[dict[str, Any]]:
    """Return a change-type-bounded embedding Top-K with exact source slices."""

    if max_per_family < 1:
        raise ValueError("max_per_family must be positive")
    pool = list(embedded_pool)
    ranked = rank_capabilities(
        query_vector=query_vector,
        embedded_pool=pool,
        host_seed_id=host_seed_id,
        used_capability_ids=set(),
        top_k=max(1, len(pool)),
    )
    preferred: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for row in ranked:
        snippets = compile_source_slices(row)
        if not snippets:
            continue
        compiled = {
            **compact_planner_card(row, source_slices=snippets),
            "similarity": row["similarity"],
        }
        family = compiled["change_type"]
        if family_counts.get(family, 0) < max_per_family:
            preferred.append(compiled)
            family_counts[family] = family_counts.get(family, 0) + 1
        else:
            overflow.append(compiled)
    selected = preferred[:top_k]
    if len(selected) < top_k:
        selected.extend(overflow[: top_k - len(selected)])
    selected.sort(key=lambda item: (-item["similarity"], item["capability_id"]))
    if len(selected) != top_k:
        raise ValueError(
            f"requested Top-{top_k}, but only {len(selected)} cards have compilable source slices"
        )
    return selected


def retrieve_top_k_cards(
    *,
    query_vector: list[float],
    embedded_pool: Iterable[dict[str, Any]],
    host_seed_id: str,
    top_k: int,
    max_per_family: int = 2,
) -> list[dict[str, Any]]:
    """Return embedding Top-K cards; exact source slices are optional evidence."""

    if max_per_family < 1:
        raise ValueError("max_per_family must be positive")
    pool = list(embedded_pool)
    ranked = rank_capabilities(
        query_vector=query_vector,
        embedded_pool=pool,
        host_seed_id=host_seed_id,
        used_capability_ids=set(),
        top_k=max(1, len(pool)),
    )
    preferred: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for row in ranked:
        compiled = {
            **compact_planner_card(
                row,
                source_slices=compile_source_slices(row),
            ),
            "similarity": row["similarity"],
        }
        family = compiled["change_type"]
        if family_counts.get(family, 0) < max_per_family:
            preferred.append(compiled)
            family_counts[family] = family_counts.get(family, 0) + 1
        else:
            overflow.append(compiled)
    selected = preferred[:top_k]
    if len(selected) < top_k:
        selected.extend(overflow[: top_k - len(selected)])
    selected.sort(key=lambda item: (-item["similarity"], item["capability_id"]))
    if len(selected) != top_k:
        raise ValueError(f"requested Top-{top_k}, but only {len(selected)} cards are available")
    return selected


def retrieve_top_k_with_snippets(**kwargs: Any) -> list[dict[str, Any]]:
    """Backward-compatible spelling for historical callers."""

    return retrieve_top_k_with_source_slices(**kwargs)


def planner_card_context(card: dict[str, Any]) -> dict[str, Any]:
    """Remove lineage and vectors while keeping the hidden evidence needed by the planner."""

    return compact_planner_card(
        card,
        source_slices=compile_source_slices(card),
    )


__all__ = [
    "RETRIEVAL_QUERY_SYSTEM",
    "build_seed_retrieval_query",
    "compile_donor_snippets",
    "compile_source_slices",
    "compact_planner_card",
    "generate_seed_retrieval_query",
    "generate_seed_retrieval_plan",
    "planner_card_context",
    "retrieve_top_k_cards",
    "retrieve_top_k_with_source_slices",
    "retrieve_top_k_with_snippets",
    "validate_generated_retrieval_query",
    "validate_generated_retrieval_plan",
]
