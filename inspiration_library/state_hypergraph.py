"""Typed state-hypergraph planning for source-conditioned WebCoding Edit queries.

The module is intentionally provider-free. Semantic seed profiling and donor-card
authoring happen before this stage; graph search, version lineage, query assembly,
and structural quality checks are deterministic and inexpensive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import json
from pathlib import Path
from typing import Any, Iterable


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return tuple(dict.fromkeys(value))


@dataclass(frozen=True)
class StateSpec:
    id: str
    kind: str
    value_shape: str
    scope: str
    persistence: str
    observables: tuple[str, ...]

    @classmethod
    def from_dict(cls, state_id: str, data: dict[str, Any]) -> "StateSpec":
        if not isinstance(data, dict):
            raise ValueError(f"state spec {state_id} must be an object")
        fields = ("kind", "value_shape", "scope", "persistence")
        missing = [
            name for name in fields if not isinstance(data.get(name), str) or not data[name]
        ]
        if missing:
            raise ValueError(
                f"state spec {state_id} missing fields: {', '.join(missing)}"
            )
        return cls(
            id=state_id,
            kind=data["kind"],
            value_shape=data["value_shape"],
            scope=data["scope"],
            persistence=data["persistence"],
            observables=_strings(data.get("observables", []), "observables"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value_shape": self.value_shape,
            "scope": self.scope,
            "persistence": self.persistence,
            "observables": list(self.observables),
        }


def _state_specs(value: Any, field_name: str) -> dict[str, StateSpec]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return {
        state_id: StateSpec.from_dict(state_id, spec)
        for state_id, spec in value.items()
        if isinstance(state_id, str) and state_id
    }


@dataclass(frozen=True)
class SeedProfile:
    id: str
    project_path: str
    domain: str
    available_states: tuple[str, ...]
    current_features: tuple[str, ...]
    preserve: tuple[str, ...]
    bindings: dict[str, str]
    grounding_facts: tuple[str, ...] = ()
    preferred_targets: tuple[str, ...] = ()
    state_specs: dict[str, StateSpec] = field(default_factory=dict)
    profile_evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedProfile":
        required = ("id", "project_path", "domain")
        missing = [key for key in required if not isinstance(data.get(key), str) or not data[key]]
        if missing:
            raise ValueError(f"seed profile missing fields: {', '.join(missing)}")
        bindings = data.get("bindings", {})
        if not isinstance(bindings, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in bindings.items()
        ):
            raise ValueError("bindings must map strings to strings")
        return cls(
            id=data["id"],
            project_path=data["project_path"],
            domain=data["domain"],
            available_states=_strings(data.get("available_states", []), "available_states"),
            current_features=_strings(data.get("current_features", []), "current_features"),
            preserve=_strings(data.get("preserve", []), "preserve"),
            bindings=dict(bindings),
            grounding_facts=_strings(data.get("grounding_facts", []), "grounding_facts"),
            preferred_targets=_strings(data.get("preferred_targets", []), "preferred_targets"),
            state_specs=_state_specs(data.get("state_specs", {}), "state_specs"),
            profile_evidence=dict(data.get("profile_evidence", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_path": self.project_path,
            "domain": self.domain,
            "available_states": list(self.available_states),
            "current_features": list(self.current_features),
            "preserve": list(self.preserve),
            "bindings": dict(self.bindings),
            "grounding_facts": list(self.grounding_facts),
            "preferred_targets": list(self.preferred_targets),
            "state_specs": {
                state_id: spec.to_dict()
                for state_id, spec in sorted(self.state_specs.items())
            },
            "profile_evidence": dict(self.profile_evidence),
        }


@dataclass(frozen=True)
class CapabilityEdge:
    id: str
    title: str
    compatible_domains: tuple[str, ...]
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    mutates: tuple[str, ...]
    invalidates: tuple[str, ...]
    estimated_cost: float
    target_value: float
    difficulty: str
    goal: str
    dependency_clause: str
    behavior_clauses: tuple[str, ...]
    acceptance: tuple[str, ...]
    donor_evidence: dict[str, Any]
    state_specs: dict[str, StateSpec] = field(default_factory=dict)
    ui_regions: tuple[str, ...] = ()
    write_files: tuple[str, ...] = ()
    browser_checks: tuple[dict[str, Any], ...] = ()
    visible_preserve: tuple[str, ...] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityEdge":
        for field_name in ("id", "title", "goal"):
            if not isinstance(data.get(field_name), str) or not data[field_name].strip():
                raise ValueError(f"capability {field_name} must be a non-empty string")
        evidence = data.get("donor_evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"capability {data['id']} requires donor_evidence")
        return cls(
            id=data["id"],
            title=data["title"],
            compatible_domains=_strings(
                data.get("compatible_domains", []), "compatible_domains"
            ),
            requires=_strings(data.get("requires", []), "requires"),
            produces=_strings(data.get("produces", []), "produces"),
            mutates=_strings(data.get("mutates", []), "mutates"),
            invalidates=_strings(data.get("invalidates", []), "invalidates"),
            estimated_cost=float(data.get("estimated_cost", 1.0)),
            target_value=float(data.get("target_value", 1.0)),
            difficulty=str(data.get("difficulty", "medium")),
            goal=data["goal"].strip(),
            dependency_clause=str(data.get("dependency_clause", "")).strip(),
            behavior_clauses=_strings(
                data.get("behavior_clauses", []), "behavior_clauses"
            ),
            acceptance=_strings(data.get("acceptance", []), "acceptance"),
            donor_evidence=dict(evidence),
            state_specs=_state_specs(data.get("state_specs", {}), "state_specs"),
            ui_regions=_strings(data.get("ui_regions", []), "ui_regions"),
            write_files=_strings(data.get("write_files", []), "write_files"),
            browser_checks=tuple(
                dict(item) for item in data.get("browser_checks", [])
                if isinstance(item, dict)
            ),
            visible_preserve=(
                _strings(data["visible_preserve"], "visible_preserve")
                if "visible_preserve" in data
                else None
            ),
        )

    def compatible_with(self, domain: str) -> bool:
        return not self.compatible_domains or domain in self.compatible_domains or "*" in self.compatible_domains

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "compatible_domains": list(self.compatible_domains),
            "requires": list(self.requires),
            "produces": list(self.produces),
            "mutates": list(self.mutates),
            "invalidates": list(self.invalidates),
            "state_specs": {
                state_id: spec.to_dict()
                for state_id, spec in sorted(self.state_specs.items())
            },
            "estimated_cost": self.estimated_cost,
            "target_value": self.target_value,
            "difficulty": self.difficulty,
            "goal": self.goal,
            "dependency_clause": self.dependency_clause,
            "behavior_clauses": list(self.behavior_clauses),
            "acceptance": list(self.acceptance),
            "ui_regions": list(self.ui_regions),
            "write_files": list(self.write_files),
            "browser_checks": [dict(check) for check in self.browser_checks],
            "visible_preserve": (
                list(self.visible_preserve) if self.visible_preserve is not None else None
            ),
            "donor_evidence": dict(self.donor_evidence),
        }


def build_state_registry(
    seed: SeedProfile, capabilities: Iterable[CapabilityEdge]
) -> dict[str, StateSpec]:
    registry = dict(seed.state_specs)
    for edge in capabilities:
        for state_id, spec in edge.state_specs.items():
            existing = registry.get(state_id)
            if existing is not None and existing != spec:
                raise ValueError(
                    f"conflicting type declarations for state {state_id}: "
                    f"{existing.to_dict()} != {spec.to_dict()}"
                )
            registry[state_id] = spec
    return registry


def typed_state_coverage(
    seed: SeedProfile, capabilities: Iterable[CapabilityEdge]
) -> dict[str, Any]:
    edges = tuple(capabilities)
    registry = build_state_registry(seed, edges)
    referenced = set(seed.available_states)
    for edge in edges:
        referenced.update(edge.requires)
        referenced.update(edge.produces)
        referenced.update(edge.mutates)
        referenced.update(edge.invalidates)
    missing = sorted(referenced - set(registry))
    return {
        "referenced_state_count": len(referenced),
        "typed_state_count": len(referenced) - len(missing),
        "coverage": 1.0 if not referenced else round((len(referenced) - len(missing)) / len(referenced), 6),
        "missing_state_specs": missing,
        "registry": {
            state_id: registry[state_id].to_dict() for state_id in sorted(registry)
        },
    }


def _verification_has_ok_case(path: Path, case_id: str) -> bool:
    try:
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        else:
            payload = json.loads(path.read_text())
            rows = payload if isinstance(payload, list) else [payload]
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    return any(
        isinstance(row, dict)
        and row.get("case_id") == case_id
        and row.get("status") == "ok"
        for row in rows
    )


def audit_provenance_references(
    capabilities: Iterable[CapabilityEdge], project_root: Path
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for edge in capabilities:
        evidence = edge.donor_evidence
        source_value = evidence.get("source_project")
        verification_value = evidence.get("verification")
        case_id = evidence.get("case_id")
        source_path = (
            (project_root / source_value).resolve()
            if isinstance(source_value, str) and source_value
            else None
        )
        verification_path = (
            (project_root / verification_value).resolve()
            if isinstance(verification_value, str) and verification_value
            else None
        )
        source_exists = bool(source_path and source_path.exists())
        verification_exists = bool(verification_path and verification_path.is_file())
        verified_case = bool(
            verification_exists
            and isinstance(case_id, str)
            and case_id
            and _verification_has_ok_case(verification_path, case_id)
        )
        rows.append(
            {
                "capability_id": edge.id,
                "case_id": case_id,
                "source_project": str(source_path) if source_path else None,
                "verification": str(verification_path) if verification_path else None,
                "source_exists": source_exists,
                "verification_exists": verification_exists,
                "verified_case_status_ok": verified_case,
                "pass": source_exists and verification_exists and verified_case,
            }
        )
    return {"pass": all(row["pass"] for row in rows), "capabilities": rows}


@dataclass(frozen=True)
class HypergraphPlan:
    target_capability_id: str
    capability_ids: tuple[str, ...]
    dependencies: dict[str, tuple[str, ...]]
    total_cost: float
    ranking_score: float
    topology: str
    final_states: tuple[str, ...]
    state_provenance: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_capability_id": self.target_capability_id,
            "capability_ids": list(self.capability_ids),
            "dependencies": {key: list(value) for key, value in self.dependencies.items()},
            "total_cost": self.total_cost,
            "ranking_score": self.ranking_score,
            "topology": self.topology,
            "final_states": list(self.final_states),
            "state_provenance": {
                capability_id: dict(values)
                for capability_id, values in self.state_provenance.items()
            },
        }


class HypergraphPlanner:
    """Bounded uniform-cost search over typed capability hyperedges."""

    def __init__(self, capabilities: Iterable[CapabilityEdge], *, max_edges: int = 4):
        self.capabilities = tuple(capabilities)
        self.by_id = {edge.id: edge for edge in self.capabilities}
        if len(self.by_id) != len(self.capabilities):
            raise ValueError("capability ids must be unique")
        if max_edges < 1:
            raise ValueError("max_edges must be positive")
        self.max_edges = max_edges

    def plan_for_target(
        self, seed: SeedProfile, target_capability_id: str
    ) -> HypergraphPlan | None:
        target = self.by_id.get(target_capability_id)
        if target is None or not target.compatible_with(seed.domain):
            return None

        initial_states = frozenset(seed.available_states)
        # cost, edge_count, stable sequence key, available states, chosen sequence
        queue: list[tuple[float, int, tuple[str, ...], frozenset[str], tuple[str, ...]]] = [
            (0.0, 0, (), initial_states, ())
        ]
        best: dict[tuple[frozenset[str], tuple[str, ...]], float] = {}

        while queue:
            cost, _, _, states, chosen = heapq.heappop(queue)
            state_key = (states, chosen)
            if cost > best.get(state_key, float("inf")):
                continue
            if target_capability_id in chosen:
                return self._materialize_plan(seed, target, chosen, states, cost)
            if len(chosen) >= self.max_edges:
                continue

            for edge in sorted(self.capabilities, key=lambda item: item.id):
                if edge.id in chosen or not edge.compatible_with(seed.domain):
                    continue
                if not set(edge.requires).issubset(states):
                    continue
                next_states = frozenset(
                    (set(states) - set(edge.invalidates))
                    | set(edge.produces)
                    | set(edge.mutates)
                )
                next_chosen = (*chosen, edge.id)
                next_cost = round(cost + edge.estimated_cost, 6)
                next_key = (next_states, next_chosen)
                if next_cost >= best.get(next_key, float("inf")):
                    continue
                best[next_key] = next_cost
                heapq.heappush(
                    queue,
                    (next_cost, len(next_chosen), next_chosen, next_states, next_chosen),
                )
        return None

    def rank_plans(self, seed: SeedProfile) -> list[HypergraphPlan]:
        plans: list[HypergraphPlan] = []
        preferred = set(seed.preferred_targets)
        for edge in self.capabilities:
            if not edge.compatible_with(seed.domain):
                continue
            plan = self.plan_for_target(seed, edge.id)
            if plan is None:
                continue
            preference_bonus = 1.0 if edge.id in preferred else 0.0
            plans.append(
                HypergraphPlan(
                    target_capability_id=plan.target_capability_id,
                    capability_ids=plan.capability_ids,
                    dependencies=plan.dependencies,
                    total_cost=plan.total_cost,
                    ranking_score=round(plan.ranking_score + preference_bonus, 6),
                    topology=plan.topology,
                    final_states=plan.final_states,
                    state_provenance=plan.state_provenance,
                )
            )
        return sorted(
            plans,
            key=lambda plan: (
                -plan.ranking_score,
                plan.total_cost,
                plan.target_capability_id,
            ),
        )

    def _materialize_plan(
        self,
        seed: SeedProfile,
        target: CapabilityEdge,
        chosen: tuple[str, ...],
        states: frozenset[str],
        cost: float,
    ) -> HypergraphPlan:
        producers: dict[str, str] = {}
        raw_dependencies: dict[str, tuple[str, ...]] = {}
        state_provenance: dict[str, dict[str, str]] = {}
        for capability_id in chosen:
            edge = self.by_id[capability_id]
            state_provenance[capability_id] = {
                state: producers.get(state, "seed") for state in edge.requires
            }
            parents = {
                producers[state]
                for state in edge.requires
                if state in producers
            }
            raw_dependencies[capability_id] = tuple(sorted(parents))
            for state in edge.invalidates:
                producers.pop(state, None)
            for state in (*edge.produces, *edge.mutates):
                producers[state] = capability_id

        raw_ancestors: dict[str, set[str]] = {}

        def collect_raw(capability_id: str) -> set[str]:
            if capability_id in raw_ancestors:
                return set(raw_ancestors[capability_id])
            result: set[str] = set()
            for parent in raw_dependencies[capability_id]:
                result.add(parent)
                result.update(collect_raw(parent))
            raw_ancestors[capability_id] = result
            return set(result)

        dependencies: dict[str, tuple[str, ...]] = {}
        for capability_id, parents in raw_dependencies.items():
            immediate = tuple(
                parent
                for parent in parents
                if not any(
                    parent in collect_raw(other_parent)
                    for other_parent in parents
                    if other_parent != parent
                )
            )
            dependencies[capability_id] = tuple(sorted(immediate))

        topology = _classify_topology(chosen, dependencies)
        topology_bonus = {
            "node": 0.0,
            "chain": 0.5,
            "fork": 0.8,
            "join": 0.8,
            "fork_join": 1.2,
        }[topology]
        ranking_score = round(target.target_value + topology_bonus - cost, 6)
        return HypergraphPlan(
            target_capability_id=target.id,
            capability_ids=chosen,
            dependencies=dependencies,
            total_cost=round(cost, 6),
            ranking_score=ranking_score,
            topology=topology,
            final_states=tuple(sorted(states)),
            state_provenance=state_provenance,
        )


def _classify_topology(
    capability_ids: tuple[str, ...], dependencies: dict[str, tuple[str, ...]]
) -> str:
    if len(capability_ids) <= 1:
        return "node"
    out_degree = {capability_id: 0 for capability_id in capability_ids}
    has_join = False
    for parents in dependencies.values():
        has_join = has_join or len(parents) > 1
        for parent in parents:
            out_degree[parent] += 1
    has_fork = any(value > 1 for value in out_degree.values())
    if has_fork and has_join:
        return "fork_join"
    if has_fork:
        return "fork"
    if has_join:
        return "join"
    return "chain"


def analyze_order_pairs(
    seed: SeedProfile,
    plan: HypergraphPlan,
    capabilities: dict[str, CapabilityEdge],
) -> tuple[dict[str, Any], ...]:
    """Classify A→B / B→A using typed state reads, writes, and invalidations.

    This is a cheap structural diagnostic. Pairs that may write or invalidate the
    same state are explicitly deferred to a browser order audit instead of being
    declared commutative from metadata alone.
    """

    seed_states = set(seed.available_states)
    ancestors: dict[str, set[str]] = {}

    def collect_ancestors(capability_id: str) -> set[str]:
        if capability_id in ancestors:
            return set(ancestors[capability_id])
        result: set[str] = set()
        for parent in plan.dependencies[capability_id]:
            result.add(parent)
            result.update(collect_ancestors(parent))
        ancestors[capability_id] = result
        return set(result)

    rows: list[dict[str, Any]] = []
    ids = plan.capability_ids
    for first_index, first_id in enumerate(ids):
        first = capabilities[first_id]
        for second_id in ids[first_index + 1 :]:
            second = capabilities[second_id]
            first_outputs = set((*first.produces, *first.mutates))
            second_outputs = set((*second.produces, *second.mutates))
            forward_states = (set(second.requires) & first_outputs) - seed_states
            reverse_states = (set(first.requires) & second_outputs) - seed_states
            forward_ancestors = collect_ancestors(second_id)
            reverse_ancestors = collect_ancestors(first_id)
            conflicting_states = (
                (first_outputs & set(second.invalidates))
                | (second_outputs & set(first.invalidates))
                | (set(first.mutates) & set(second.mutates))
            )
            shared_ui_regions = set(first.ui_regions) & set(second.ui_regions)
            shared_write_files = set(first.write_files) & set(second.write_files)
            if forward_states and reverse_states:
                classification = "cyclic_dependency"
                forward_order = "blocked_missing_states"
                reverse_order = "blocked_missing_states"
                browser_audit = False
            elif forward_states:
                classification = "hard_forward_dependency"
                forward_order = "structurally_valid"
                reverse_order = "blocked_missing_states"
                browser_audit = False
            elif reverse_states:
                classification = "hard_reverse_dependency"
                forward_order = "blocked_missing_states"
                reverse_order = "structurally_valid"
                browser_audit = False
            elif conflicting_states or shared_ui_regions:
                classification = "potential_order_conflict"
                forward_order = "structurally_valid_needs_browser_audit"
                reverse_order = "structurally_valid_needs_browser_audit"
                browser_audit = True
            elif first_id in forward_ancestors:
                classification = "transitive_forward_dependency"
                forward_order = "structurally_valid"
                reverse_order = "blocked_missing_prerequisite_path"
                browser_audit = False
            elif second_id in reverse_ancestors:
                classification = "transitive_reverse_dependency"
                forward_order = "blocked_missing_prerequisite_path"
                reverse_order = "structurally_valid"
                browser_audit = False
            else:
                classification = "independent_or_shared_seed_input"
                forward_order = "structurally_valid"
                reverse_order = "structurally_valid"
                browser_audit = bool(shared_write_files)
            rows.append(
                {
                    "first_capability_id": first_id,
                    "second_capability_id": second_id,
                    "forward_order": forward_order,
                    "reverse_order": reverse_order,
                    "classification": classification,
                    "forward_dependency_states": sorted(forward_states),
                    "reverse_dependency_states": sorted(reverse_states),
                    "conflicting_states": sorted(conflicting_states),
                    "shared_ui_regions": sorted(shared_ui_regions),
                    "shared_write_files": sorted(shared_write_files),
                    "dependency_via": sorted(
                        forward_ancestors - {first_id}
                        if first_id in forward_ancestors
                        else reverse_ancestors - {second_id}
                        if second_id in reverse_ancestors
                        else set()
                    ),
                    "requires_browser_order_audit": browser_audit,
                }
            )
    return tuple(rows)


@dataclass(frozen=True)
class VersionNode:
    id: str
    capabilities: tuple[str, ...]
    available_states: tuple[str, ...]
    merge_required: bool = False
    merge_parents: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capabilities": list(self.capabilities),
            "available_states": list(self.available_states),
            "merge_required": self.merge_required,
            "merge_parents": list(self.merge_parents),
        }


@dataclass(frozen=True)
class VersionTransition:
    source_version_id: str
    target_version_id: str
    capability_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_version_id": self.source_version_id,
            "target_version_id": self.target_version_id,
            "capability_id": self.capability_id,
        }


@dataclass(frozen=True)
class VersionMerge:
    source_version_ids: tuple[str, ...]
    target_version_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_version_ids": list(self.source_version_ids),
            "target_version_id": self.target_version_id,
        }


@dataclass(frozen=True)
class VersionDag:
    nodes: tuple[VersionNode, ...]
    transitions: tuple[VersionTransition, ...]
    merges: tuple[VersionMerge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "transitions": [transition.to_dict() for transition in self.transitions],
            "merges": [merge.to_dict() for merge in self.merges],
        }


def _version_id(capabilities: Iterable[str]) -> str:
    items = tuple(sorted(capabilities))
    return "v_seed" if not items else "v__" + "__".join(items)


def build_version_dag(
    seed: SeedProfile,
    plan: HypergraphPlan,
    capabilities: dict[str, CapabilityEdge],
) -> VersionDag:
    ancestors: dict[str, set[str]] = {}

    def collect(capability_id: str) -> set[str]:
        if capability_id in ancestors:
            return set(ancestors[capability_id])
        result: set[str] = set()
        for parent in plan.dependencies[capability_id]:
            result.add(parent)
            result.update(collect(parent))
        ancestors[capability_id] = result
        return set(result)

    node_specs: dict[tuple[str, ...], dict[str, Any]] = {
        (): {"merge_required": False, "merge_parents": ()}
    }
    transitions: list[VersionTransition] = []
    merges: list[VersionMerge] = []
    for capability_id in plan.capability_ids:
        source_caps = tuple(sorted(collect(capability_id)))
        target_caps = tuple(sorted((*source_caps, capability_id)))
        direct_parents = plan.dependencies[capability_id]
        merge_heads = tuple(
            parent
            for parent in direct_parents
            if not any(
                parent in collect(other_parent)
                for other_parent in direct_parents
                if other_parent != parent
            )
        )
        merge_required = len(merge_heads) > 1
        merge_parents = tuple(
            sorted(
                _version_id(tuple(sorted((*collect(parent), parent))))
                for parent in merge_heads
            )
        )
        node_specs.setdefault(
            source_caps,
            {"merge_required": merge_required, "merge_parents": merge_parents},
        )
        if merge_required:
            node_specs[source_caps] = {
                "merge_required": True,
                "merge_parents": merge_parents,
            }
            merges.append(
                VersionMerge(
                    source_version_ids=merge_parents,
                    target_version_id=_version_id(source_caps),
                )
            )
        node_specs.setdefault(
            target_caps, {"merge_required": False, "merge_parents": ()}
        )
        transitions.append(
            VersionTransition(
                source_version_id=_version_id(source_caps),
                target_version_id=_version_id(target_caps),
                capability_id=capability_id,
            )
        )

    nodes: list[VersionNode] = []
    for caps, spec in sorted(node_specs.items(), key=lambda item: (len(item[0]), item[0])):
        states = set(seed.available_states)
        for capability_id in caps:
            edge = capabilities[capability_id]
            states.difference_update(edge.invalidates)
            states.update(edge.produces)
            states.update(edge.mutates)
        nodes.append(
            VersionNode(
                id=_version_id(caps),
                capabilities=caps,
                available_states=tuple(sorted(states)),
                merge_required=bool(spec["merge_required"]),
                merge_parents=tuple(spec["merge_parents"]),
            )
        )
    return VersionDag(
        nodes=tuple(nodes),
        transitions=tuple(transitions),
        merges=tuple(merges),
    )


@dataclass(frozen=True)
class QueryQuality:
    score: int
    dimensions: dict[str, int]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "score_scope": "structural_completeness_only",
            "dimensions": dict(self.dimensions),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class EditQuery:
    record_id: str
    seed_id: str
    capability_id: str
    source_version_id: str
    target_version_id: str
    instruction: str
    consumes_states: tuple[str, ...]
    produces_states: tuple[str, ...]
    predecessor_capabilities: tuple[str, ...]
    acceptance: tuple[str, ...]
    preservation: tuple[str, ...]
    donor_evidence: dict[str, Any]
    quality: QueryQuality
    input_state_sources: dict[str, str] = field(default_factory=dict)
    status: str = "ok"
    generation_mode: str = "deterministic"
    source_evidence_status: str = "planned_version_not_materialized"
    target_code_status: str = "not_generated"
    training_admission: str = "not_eligible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "seed_id": self.seed_id,
            "capability_id": self.capability_id,
            "source_version_id": self.source_version_id,
            "target_version_id": self.target_version_id,
            "instruction": self.instruction,
            "consumes_states": list(self.consumes_states),
            "produces_states": list(self.produces_states),
            "predecessor_capabilities": list(self.predecessor_capabilities),
            "acceptance": list(self.acceptance),
            "preservation": list(self.preservation),
            "donor_evidence": dict(self.donor_evidence),
            "quality": self.quality.to_dict(),
            "input_state_sources": dict(self.input_state_sources),
            "status": self.status,
            "generation_mode": self.generation_mode,
            "source_evidence_status": self.source_evidence_status,
            "target_code_status": self.target_code_status,
            "training_admission": self.training_admission,
        }


def compose_edit_queries(
    seed: SeedProfile,
    plan: HypergraphPlan,
    capabilities: dict[str, CapabilityEdge],
) -> tuple[EditQuery, ...]:
    dag = build_version_dag(seed, plan, capabilities)
    transition_by_capability = {
        transition.capability_id: transition for transition in dag.transitions
    }
    queries: list[EditQuery] = []
    for capability_id in plan.capability_ids:
        edge = capabilities[capability_id]
        paragraphs = [edge.goal.rstrip(". ") + "."]
        if edge.dependency_clause:
            paragraphs.append(edge.dependency_clause.rstrip(". ") + ".")
        paragraphs.extend(clause.rstrip(". ") + "." for clause in edge.behavior_clauses)
        visible_preserve = (
            seed.preserve if edge.visible_preserve is None else edge.visible_preserve
        )
        if visible_preserve:
            preservation = ", ".join(visible_preserve)
            paragraphs.append(f"Preserve {preservation}.")
        instruction = " ".join(paragraphs)
        quality = _score_query(seed, edge, instruction, plan.dependencies[capability_id])
        transition = transition_by_capability[capability_id]
        queries.append(
            EditQuery(
                record_id=f"{seed.id}__{capability_id}",
                seed_id=seed.id,
                capability_id=capability_id,
                source_version_id=transition.source_version_id,
                target_version_id=transition.target_version_id,
                instruction=instruction,
                consumes_states=edge.requires,
                produces_states=tuple(dict.fromkeys((*edge.produces, *edge.mutates))),
                predecessor_capabilities=plan.dependencies[capability_id],
                acceptance=edge.acceptance,
                preservation=seed.preserve,
                donor_evidence=edge.donor_evidence,
                quality=quality,
                input_state_sources=plan.state_provenance.get(capability_id, {}),
                source_evidence_status=(
                    "verified_seed" if transition.source_version_id == "v_seed"
                    else "planned_version_not_materialized"
                ),
            )
        )
    return tuple(queries)


def _score_query(
    seed: SeedProfile,
    edge: CapabilityEdge,
    instruction: str,
    predecessors: tuple[str, ...],
) -> QueryQuality:
    warnings: list[str] = []
    implementation_markers = ("data-", "#", "localStorage", "sessionStorage", "querySelector")
    leaks = [marker for marker in implementation_markers if marker in instruction]
    if leaks:
        warnings.append("implementation details leaked into the natural instruction")

    dimensions = {
        "source_grounding": 20 if edge.requires and edge.dependency_clause else 10,
        "state_dependency": 20 if edge.requires and edge.dependency_clause else 5,
        "behavioral_specificity": min(20, len(edge.behavior_clauses) * 10),
        "browser_verifiability": min(20, len(edge.acceptance) * 10),
        "scope_preservation": 15 if seed.preserve else 0,
        "natural_language": 5 if not leaks else 0,
    }
    if predecessors and not edge.dependency_clause:
        warnings.append("a graph dependency exists but the query does not describe it")
    score = sum(dimensions.values())
    return QueryQuality(score=score, dimensions=dimensions, warnings=tuple(warnings))


def load_seed_profile(path: Path) -> SeedProfile:
    return SeedProfile.from_dict(json.loads(path.read_text()))


def load_capability_library(path: Path) -> tuple[CapabilityEdge, ...]:
    data = json.loads(path.read_text())
    rows = data.get("capabilities") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("capability library must contain a capabilities list")
    return tuple(CapabilityEdge.from_dict(row) for row in rows)
