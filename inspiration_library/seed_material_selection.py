"""Choose a small, varied Seed set from grounded browser observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math
import re
from typing import Any

from inspiration_library.doc_api import DocApiClient
from inspiration_library.linear_edit_queries import compact_browser_evidence_for_llm


ScannedSeed = tuple[dict[str, Any], dict[str, Any]]


MATERIAL_PROFILE_SYSTEM = """Read each Seed independently and inventory only frontend material visibly supported by
the supplied browser facts. Material is open-ended: it may be a component group, user flow, data/state relation,
information organization, navigation pattern, responsive composition, visual system, accessibility treatment,
motion/media treatment, or another natural page characteristic. Do not force every kind to appear, compare Seeds,
propose missing features, or optimize for a library quota. Map a material to supplied construct Edit types only when
the existing page clearly shows that type's distinctive component group or observed state. A prerequisite alone is not
enough: a search field is not autocomplete without suggestions, a dark palette is not a theme toggle, a button is not
a click-state feature without a changed state, and desktop navigation is not responsive navigation without mobile
evidence. Business names may differ. Evidence must be a short excerpt copied from that Seed's facts. Return exactly
{"profiles":[...]} and no surrounding text."""


def browser_material_text(observation: dict[str, Any]) -> str:
    """Serialize only compact browser facts for semantic Seed comparison."""

    compact = compact_browser_evidence_for_llm(
        observation,
        include_known_selectors=False,
        max_transition_states=0,
    )
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def compact_seed_material_facts(observation: dict[str, Any]) -> dict[str, Any]:
    """Summarize every observed item by pattern instead of taking DOM prefixes."""

    baseline = observation.get("baseline")
    mobile = observation.get("mobile_baseline")
    baseline = baseline if isinstance(baseline, dict) else {}
    mobile = mobile if isinstance(mobile, dict) else {}

    def summarize_values(values: Sequence[str], *, max_values: int = 16) -> dict[str, Any]:
        unique = sorted({" ".join(value.split()) for value in values if value.strip()})
        serialized = json.dumps(unique, ensure_ascii=False, separators=(",", ":"))
        if len(unique) <= max_values:
            samples = unique
        elif max_values == 1:
            samples = [unique[len(unique) // 2]]
        else:
            indices = {
                round(index * (len(unique) - 1) / (max_values - 1))
                for index in range(max_values)
            }
            samples = [unique[index] for index in sorted(indices)]
        return {
            "unique_count": len(unique),
            "coverage_samples": samples,
            "all_values_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
        }

    def summarize_lines(value: Any) -> dict[str, Any]:
        lines = [line for line in str(value or "").splitlines() if line.strip()]
        return summarize_values(lines, max_values=80)

    def group_rows(
        rows: Any,
        *,
        pattern_keys: Sequence[str],
        value_keys: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            pattern = {
                key: row.get(key)
                for key in pattern_keys
                if row.get(key) not in (None, "", [], {})
            }
            signature = json.dumps(pattern, ensure_ascii=False, sort_keys=True)
            group = groups.setdefault(
                signature,
                {
                    "pattern": pattern,
                    "count": 0,
                    "values": {key: [] for key in value_keys},
                },
            )
            group["count"] += 1
            for key in value_keys:
                value = row.get(key)
                if value in (None, "", [], {}):
                    continue
                rendered = (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if not isinstance(value, str)
                    else value
                )
                group["values"][key].append(rendered)
        result: list[dict[str, Any]] = []
        for signature in sorted(groups):
            group = groups[signature]
            summarized = {
                key: summarize_values(values)
                for key, values in group.pop("values").items()
                if values
            }
            if summarized:
                group["observed_values"] = summarized
            result.append(group)
        return result

    controls = group_rows(
        baseline.get("interactive"),
        pattern_keys=(
            "tag",
            "role",
            "type",
            "checked",
            "disabled",
            "visible",
            "horizontally_reachable",
            "draggable",
            "tabindex",
        ),
        value_keys=("name", "aria_label", "href", "text", "title", "options"),
    )
    return {
        "title": baseline.get("title"),
        "url": baseline.get("url"),
        "visible_text": summarize_lines(baseline.get("visible_text")),
        "accessibility_tree": summarize_lines(baseline.get("aria_snapshot")),
        "interactive_control_patterns": controls,
        "interactive_control_total": len(baseline.get("interactive", [])),
        "structure_patterns": group_rows(
            baseline.get("structures"),
            pattern_keys=("tag", "role", "child_count"),
            value_keys=("id", "aria_label", "text"),
        ),
        "storage": {
            "local_keys": sorted((baseline.get("local_storage") or {}).keys()),
            "session_keys": sorted((baseline.get("session_storage") or {}).keys()),
        },
        "layout_patterns": group_rows(
            baseline.get("landmark_layouts"),
            pattern_keys=(
                "tag",
                "role",
                "display",
                "position",
                "overflow_x",
                "overflow_y",
                "grid_columns",
                "flex_direction",
            ),
        ),
        "aria_state_patterns": group_rows(
            baseline.get("aria_states"),
            pattern_keys=(
                "aria_expanded",
                "aria_selected",
                "aria_pressed",
                "aria_checked",
                "aria_current",
            ),
        ),
        "visual_surface_patterns": group_rows(
            baseline.get("visual_surfaces"),
            pattern_keys=("tag", "role", "width", "height", "visible", "child_count"),
            value_keys=("aria_label", "view_box"),
        ),
        "style_patterns": group_rows(
            baseline.get("style_samples"),
            pattern_keys=(
                "tag",
                "role",
                "font_family",
                "font_size",
                "font_weight",
                "color",
                "background_color",
                "border_radius",
                "box_shadow",
            ),
        ),
        "root_css_variables": dict(
            sorted((baseline.get("root_css_variables") or {}).items())
        ),
        "mobile_difference": {
            "viewport": mobile.get("viewport"),
            "horizontal_overflow": mobile.get("horizontal_overflow"),
            "interactive_control_total": len(mobile.get("interactive", [])),
            "layout_patterns": group_rows(
                mobile.get("landmark_layouts"),
                pattern_keys=("tag", "role", "display", "position", "flex_direction"),
            ),
        },
    }


def _text(value: Any, label: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _normalized_evidence(value: str) -> str:
    return " ".join(value.casefold().split())


def _fact_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        rows: list[str] = []
        for key, item in value.items():
            rows.append(str(key))
            rows.extend(_fact_strings(item))
        return rows
    if isinstance(value, list):
        rows = []
        for item in value:
            rows.extend(_fact_strings(item))
        return rows
    return [str(value)] if value not in (None, "") else []


def _evidence_is_grounded(evidence: str, facts: dict[str, Any]) -> bool:
    normalized = _normalized_evidence(evidence)
    fact_rows = [_normalized_evidence(row) for row in _fact_strings(facts)]
    if any(normalized in row for row in fact_rows):
        return True
    evidence_tokens = re.findall(r"[\w$.-]+", normalized)
    if len(evidence_tokens) < 3:
        return any(normalized in row for row in fact_rows)
    fact_tokens = set(re.findall(r"[\w$.-]+", " ".join(fact_rows)))
    supported = sum(token in fact_tokens for token in evidence_tokens)
    return supported / len(evidence_tokens) >= 0.8


def validate_seed_material_profiles(
    payload: dict[str, Any],
    *,
    expected_seed_ids: Sequence[str],
    construct_task_names: Sequence[str],
    facts_by_seed: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("material profile response requires profiles")
    expected = set(expected_seed_ids)
    allowed_tasks = set(construct_task_names)
    normalized: dict[str, dict[str, Any]] = {}
    for row in profiles:
        if not isinstance(row, dict):
            raise ValueError("each material profile must be an object")
        seed_id = _text(row.get("seed_id"), "profile seed_id")
        if seed_id not in expected or seed_id in normalized:
            raise ValueError(f"unexpected or duplicate material profile: {seed_id}")
        materials = row.get("materials")
        if not isinstance(materials, list) or not 2 <= len(materials) <= 10:
            raise ValueError(f"{seed_id} requires two to ten grounded materials")
        normalized_materials: list[dict[str, Any]] = []
        for material in materials:
            if not isinstance(material, dict):
                raise ValueError(f"{seed_id} material must be an object")
            evidence = _text(material.get("evidence"), "material evidence", minimum=2)
            if not _evidence_is_grounded(evidence, facts_by_seed[seed_id]):
                raise ValueError(
                    f"{seed_id} material evidence was not copied from browser facts: {evidence}"
                )
            tasks = material.get("construct_task_types", [])
            if not isinstance(tasks, list) or len(tasks) > 3:
                raise ValueError("construct_task_types must contain zero to three rows")
            task_names = [_text(task, "construct task type") for task in tasks]
            if len(task_names) != len(set(task_names)):
                raise ValueError("construct_task_types contains duplicates")
            unknown = set(task_names) - allowed_tasks
            if unknown:
                raise ValueError(f"unknown construct task types: {sorted(unknown)}")
            normalized_materials.append(
                {
                    "name": _text(material.get("name"), "material name", minimum=3),
                    "kind": _text(material.get("kind"), "material kind", minimum=3),
                    "evidence": evidence,
                    "construct_task_types": task_names,
                }
            )
        normalized[seed_id] = {
            "seed_id": seed_id,
            "materials": normalized_materials,
        }
    if set(normalized) != expected:
        raise ValueError(f"missing material profiles: {sorted(expected - set(normalized))}")
    return normalized


def extract_seed_material_profiles(
    *,
    scanned: Sequence[ScannedSeed],
    construct_task_names: Sequence[str],
    client: DocApiClient,
    request_id: str,
) -> dict[str, dict[str, Any]]:
    facts_by_seed = {
        str(seed["seed_id"]): compact_seed_material_facts(observation)
        for seed, observation in scanned
    }
    stable = (
        "CURRENT CONSTRUCT EDIT TYPES\n"
        + json.dumps(sorted(construct_task_names), ensure_ascii=False)
        + "\n\nOUTPUT\nReturn profiles in the supplied order. Each profile has seed_id and two to ten "
        "materials. Each material has name, a free-form kind, exact evidence, and zero to three "
        "construct_task_types. The type list is an affinity annotation, not a requested missing feature."
    )
    payload, _ = client.chat_json(
        request_id=request_id,
        system_prompt=MATERIAL_PROFILE_SYSTEM,
        stable_context=stable,
        task="SEED BROWSER FACTS\n"
        + json.dumps(facts_by_seed, ensure_ascii=False, separators=(",", ":")),
        max_tokens=6000,
        stream=True,
        cache_stable_context=True,
    )
    return validate_seed_material_profiles(
        payload,
        expected_seed_ids=list(facts_by_seed),
        construct_task_names=construct_task_names,
        facts_by_seed=facts_by_seed,
    )


def material_profile_embedding_text(profile: dict[str, Any]) -> str:
    return json.dumps(profile.get("materials", []), ensure_ascii=False, separators=(",", ":"))


def browser_material_richness(observation: dict[str, Any]) -> int:
    """Count distinct grounded material, without assigning it to a target class."""

    baseline = observation.get("baseline")
    mobile = observation.get("mobile_baseline")
    snapshots = [row for row in (baseline, mobile) if isinstance(row, dict)]
    controls: set[tuple[str, str, str, str]] = set()
    structures: set[tuple[str, str]] = set()
    visual_surfaces: set[str] = set()
    layout_modes: set[tuple[str, str]] = set()
    aria_states: set[str] = set()
    storage_keys: set[tuple[str, str]] = set()
    style_signatures: set[tuple[str, str, str]] = set()
    viewport_widths: set[int] = set()
    for snapshot in snapshots:
        viewport = snapshot.get("viewport")
        if isinstance(viewport, dict) and isinstance(viewport.get("width"), int):
            viewport_widths.add(viewport["width"])
        for row in snapshot.get("interactive", []):
            if isinstance(row, dict):
                controls.add(
                    (
                        str(row.get("tag") or ""),
                        str(row.get("role") or ""),
                        str(row.get("type") or ""),
                        " ".join(
                            str(row.get("text") or row.get("aria_label") or "").split()
                        ),
                    )
                )
        for row in snapshot.get("structures", []):
            if isinstance(row, dict):
                structures.add(
                    (str(row.get("tag") or ""), str(row.get("role") or ""))
                )
        for row in snapshot.get("visual_surfaces", []):
            if isinstance(row, dict):
                visual_surfaces.add(str(row.get("tag") or ""))
        for row in snapshot.get("landmark_layouts", []):
            if isinstance(row, dict):
                layout_modes.add(
                    (str(row.get("display") or ""), str(row.get("position") or ""))
                )
        for row in snapshot.get("aria_states", []):
            if isinstance(row, dict):
                aria_states.update(
                    key
                    for key, value in row.items()
                    if key.startswith("aria_") and value not in (None, "")
                )
        for storage_kind in ("local_storage", "session_storage"):
            storage = snapshot.get(storage_kind)
            if isinstance(storage, dict):
                storage_keys.update((storage_kind, str(key)) for key in storage)
        for row in snapshot.get("style_samples", []):
            if isinstance(row, dict):
                style_signatures.add(
                    (
                        str(row.get("display") or ""),
                        str(row.get("position") or ""),
                        str(row.get("background_color") or row.get("color") or ""),
                    )
                )
    return (
        min(len(controls), 24)
        + min(len(structures), 12)
        + min(len(visual_surfaces), 6)
        + min(len(layout_modes), 8)
        + min(len(aria_states), 8)
        + min(len(storage_keys), 8)
        + min(len(style_signatures), 8)
        + (2 if len(viewport_widths) > 1 else 0)
    )


def _unit(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [0.0 for _ in values]
    return [value / norm for value in values]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors must have the same non-zero dimension")
    left_unit = _unit(left)
    right_unit = _unit(right)
    return sum(a * b for a, b in zip(left_unit, right_unit))


def build_seed_material_fingerprints(
    scanned: Sequence[ScannedSeed],
    *,
    seed_embeddings: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]:
    """Use one grounded material profile as the Seed's only semantic representation."""

    successful = [row for row in scanned if row[1].get("status") == "ok"]
    if not successful:
        raise ValueError("material fingerprints require successful browser scans")
    fingerprints: dict[str, list[float]] = {}
    for seed, _ in successful:
        seed_id = str(seed["seed_id"])
        if seed_id not in seed_embeddings:
            raise ValueError(f"missing Seed material embedding: {seed_id}")
        fingerprints[seed_id] = _unit(seed_embeddings[seed_id])
    return fingerprints


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(2.0, 1.0 - _cosine(left, right)))


def _initial_medoids(
    seed_ids: Sequence[str], fingerprints: Mapping[str, Sequence[float]], count: int
) -> list[str]:
    dimension = len(fingerprints[seed_ids[0]])
    centroid = _unit(
        [
            sum(float(fingerprints[seed_id][index]) for seed_id in seed_ids)
            for index in range(dimension)
        ]
    )
    first = min(
        seed_ids,
        key=lambda seed_id: (_distance(fingerprints[seed_id], centroid), seed_id),
    )
    medoids = [first]
    while len(medoids) < count:
        choice = max(
            (seed_id for seed_id in seed_ids if seed_id not in medoids),
            key=lambda seed_id: (
                min(
                    _distance(fingerprints[seed_id], fingerprints[medoid])
                    for medoid in medoids
                ),
                seed_id,
            ),
        )
        medoids.append(choice)
    return medoids


def _assign_clusters(
    seed_ids: Sequence[str],
    medoids: Sequence[str],
    fingerprints: Mapping[str, Sequence[float]],
) -> dict[str, list[str]]:
    clusters = {medoid: [] for medoid in medoids}
    for seed_id in seed_ids:
        medoid = min(
            medoids,
            key=lambda candidate: (
                _distance(fingerprints[seed_id], fingerprints[candidate]),
                candidate,
            ),
        )
        clusters[medoid].append(seed_id)
    return clusters


def select_materially_balanced_seeds(
    scanned: Sequence[ScannedSeed],
    *,
    material_records: Mapping[str, dict[str, Any]],
    seed_embeddings: Mapping[str, Sequence[float]],
    count: int,
) -> tuple[list[ScannedSeed], dict[str, Any]]:
    """Group candidates by their own material, then take one real representative per group."""

    rows = sorted(
        (row for row in scanned if row[1].get("status") == "ok"),
        key=lambda row: str(row[0]["seed_id"]),
    )
    if not 1 <= count <= len(rows):
        raise ValueError("count must be inside the successful browser-scan range")
    by_id = {str(seed["seed_id"]): (seed, observation) for seed, observation in rows}
    fingerprints = build_seed_material_fingerprints(
        rows, seed_embeddings=seed_embeddings
    )
    missing_records = set(by_id) - set(material_records)
    if missing_records:
        raise ValueError(f"missing Seed material records: {sorted(missing_records)}")
    seed_ids = sorted(by_id)
    medoids = _initial_medoids(seed_ids, fingerprints, count)
    for _ in range(20):
        clusters = _assign_clusters(seed_ids, medoids, fingerprints)
        updated: list[str] = []
        for medoid in medoids:
            members = clusters[medoid]
            updated.append(
                min(
                    members,
                    key=lambda candidate: (
                        sum(
                            _distance(
                                fingerprints[candidate], fingerprints[other]
                            )
                            for other in members
                        ),
                        candidate,
                    ),
                )
            )
        if updated == medoids:
            break
        medoids = updated
    clusters = _assign_clusters(seed_ids, medoids, fingerprints)
    representatives: list[str] = []
    cluster_rows: list[dict[str, Any]] = []
    for medoid in medoids:
        members = clusters[medoid]
        central = sorted(
            members,
            key=lambda candidate: (
                sum(
                    _distance(fingerprints[candidate], fingerprints[other])
                    for other in members
                ),
                candidate,
            ),
        )
        central_half = central[: min(len(central), max(2, math.ceil(len(central) / 2)))]
        representative = max(
            central_half,
            key=lambda candidate: (
                browser_material_richness(by_id[candidate][1]),
                candidate,
            ),
        )
        representatives.append(representative)
        cluster_rows.append(
            {
                "representative_seed_id": representative,
                "member_seed_ids": sorted(members),
                "representative_browser_material_richness": browser_material_richness(
                    by_id[representative][1]
                ),
                "material_record_sha256": sha256(
                    json.dumps(
                        material_records[representative],
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )
    selected = [by_id[seed_id] for seed_id in representatives]
    pairwise = [
        _distance(fingerprints[left], fingerprints[right])
        for index, left in enumerate(representatives)
        for right in representatives[index + 1 :]
    ]
    report = {
        "schema_version": "webcoding-seed-material-selection-v1",
        "selection_basis": "single_grounded_material_profile",
        "seed_representation_count": 1,
        "generative_llm_calls_for_seed_selection": 0,
        "uses_existing_library_gap": False,
        "candidate_seed_count": len(rows),
        "selected_seed_count": len(selected),
        "mean_selected_pairwise_distance": round(
            sum(pairwise) / len(pairwise), 6
        )
        if pairwise
        else 0.0,
        "clusters": sorted(
            cluster_rows, key=lambda row: row["representative_seed_id"]
        ),
    }
    return selected, report


__all__ = [
    "browser_material_richness",
    "browser_material_text",
    "build_seed_material_fingerprints",
    "compact_seed_material_facts",
    "extract_seed_material_profiles",
    "material_profile_embedding_text",
    "select_materially_balanced_seeds",
    "validate_seed_material_profiles",
]
