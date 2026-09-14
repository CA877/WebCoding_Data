"""Typed records for planning mixed WebCoding Edit sequences.

The existing instruction-only planner models every Edit as state ``requires``
and ``produces``.  This module keeps real state dependencies while also
representing layout, visual, DOM-region, route, storage, and accessibility
changes without inventing fake state variables.

It deliberately contains no semantic heuristics.  An LLM or human supplies
the product interpretation; these functions only reject structurally false
claims such as reading a material before an earlier Edit creates it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


SourceKind = Literal["accepted_edit", "observed_pattern", "human_or_paper_idea"]
MaterialKind = Literal[
    "business_object",
    "state",
    "dom_region",
    "route",
    "storage",
    "visual_rule",
    "accessibility_rule",
]
RelationKind = Literal["consumes", "extends", "preserves", "conflicts"]
ReconciliationStatus = Literal[
    "exact",
    "rebound",
    "missing",
    "preservation_failed",
]


SOURCE_KINDS = frozenset(
    {"accepted_edit", "observed_pattern", "human_or_paper_idea"}
)
MATERIAL_KINDS = frozenset(
    {
        "business_object",
        "state",
        "dom_region",
        "route",
        "storage",
        "visual_rule",
        "accessibility_rule",
    }
)
RELATION_KINDS = frozenset({"consumes", "extends", "preserves", "conflicts"})


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _text_tuple(value: object, *, label: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    normalized = tuple(
        _required_text(item, label=f"{label} item")
        for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(f"{label} requires at least {minimum} value(s)")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class PageMaterial:
    """One typed piece of page state, structure, or presentation."""

    key: str
    kind: MaterialKind
    observable: tuple[str, ...]
    scope: str = "page"

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _required_text(self.key, label="material.key"))
        if self.kind not in MATERIAL_KINDS:
            raise ValueError(f"unsupported material kind: {self.kind}")
        object.__setattr__(
            self,
            "observable",
            _text_tuple(self.observable, label="material.observable", minimum=1),
        )
        object.__setattr__(self, "scope", _required_text(self.scope, label="material.scope"))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PageMaterial":
        if not isinstance(payload, Mapping):
            raise ValueError("material must be an object")
        return cls(
            key=payload.get("key"),
            kind=payload.get("kind"),
            observable=payload.get("observable", ()),
            scope=payload.get("scope", "page"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "observable": list(self.observable),
            "scope": self.scope,
        }


@dataclass(frozen=True)
class PageChangeRecord:
    """A planned or observed page change with provenance and evidence."""

    edit_id: str
    source_kind: SourceKind
    source_ref: str
    edit_types: tuple[str, ...]
    reads: tuple[str, ...] = ()
    creates: tuple[PageMaterial, ...] = ()
    mutates: tuple[PageMaterial, ...] = ()
    preserves: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    implementation_reference: Mapping[str, Any] | None = field(
        default=None,
        compare=True,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "edit_id", _required_text(self.edit_id, label="edit_id"))
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported source kind: {self.source_kind}")
        object.__setattr__(
            self,
            "source_ref",
            _required_text(self.source_ref, label="source_ref"),
        )
        object.__setattr__(
            self,
            "edit_types",
            _text_tuple(self.edit_types, label="edit_types", minimum=1),
        )
        object.__setattr__(self, "reads", _text_tuple(self.reads, label="reads"))
        object.__setattr__(
            self,
            "preserves",
            _text_tuple(self.preserves, label="preserves", minimum=1),
        )
        object.__setattr__(
            self,
            "verification",
            _text_tuple(self.verification, label="verification", minimum=1),
        )
        object.__setattr__(self, "creates", tuple(self.creates))
        object.__setattr__(self, "mutates", tuple(self.mutates))
        if self.implementation_reference is not None:
            if not isinstance(self.implementation_reference, Mapping):
                raise ValueError("implementation_reference must be an object")
            object.__setattr__(
                self,
                "implementation_reference",
                dict(self.implementation_reference),
            )
        self.validate()

    def validate(self) -> None:
        if not self.creates and not self.mutates:
            raise ValueError(f"{self.edit_id} must create or mutate a page material")
        for material in (*self.creates, *self.mutates):
            if not isinstance(material, PageMaterial):
                raise ValueError(f"{self.edit_id} contains an invalid page material")
        changed_keys = [item.key for item in (*self.creates, *self.mutates)]
        if len(set(changed_keys)) != len(changed_keys):
            raise ValueError(f"{self.edit_id} changes the same material more than once")
        if set(self.reads) & {item.key for item in self.creates}:
            raise ValueError(f"{self.edit_id} cannot read a material it creates")
        if self.implementation_reference is not None:
            visible = self.implementation_reference.get("training_instruction_visible", False)
            if visible is not False:
                raise ValueError("implementation reference must stay hidden from training query")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PageChangeRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("page change record must be an object")
        creates = payload.get("creates", ())
        mutates = payload.get("mutates", ())
        if not isinstance(creates, (list, tuple)) or not isinstance(mutates, (list, tuple)):
            raise ValueError("creates and mutates must be lists")
        return cls(
            edit_id=payload.get("edit_id"),
            source_kind=payload.get("source_kind"),
            source_ref=payload.get("source_ref"),
            edit_types=payload.get("edit_types", ()),
            reads=payload.get("reads", ()),
            creates=tuple(PageMaterial.from_dict(item) for item in creates),
            mutates=tuple(PageMaterial.from_dict(item) for item in mutates),
            preserves=payload.get("preserves", ()),
            verification=payload.get("verification", ()),
            implementation_reference=payload.get("implementation_reference"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "edit_id": self.edit_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "edit_types": list(self.edit_types),
            "reads": list(self.reads),
            "creates": [item.to_dict() for item in self.creates],
            "mutates": [item.to_dict() for item in self.mutates],
            "preserves": list(self.preserves),
            "verification": list(self.verification),
        }
        if self.implementation_reference is not None:
            payload["implementation_reference"] = dict(self.implementation_reference)
        return payload

    @property
    def created_keys(self) -> frozenset[str]:
        return frozenset(item.key for item in self.creates)

    @property
    def mutated_keys(self) -> frozenset[str]:
        return frozenset(item.key for item in self.mutates)

    @property
    def changed_keys(self) -> frozenset[str]:
        return self.created_keys | self.mutated_keys


@dataclass(frozen=True)
class PlannedEdit:
    edit_id: str
    index: int
    instruction: str
    change: PageChangeRecord
    independent_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "edit_id", _required_text(self.edit_id, label="edit_id"))
        if not isinstance(self.index, int) or self.index < 1:
            raise ValueError("edit index must be a positive integer")
        object.__setattr__(
            self,
            "instruction",
            _required_text(self.instruction, label="instruction"),
        )
        if not isinstance(self.change, PageChangeRecord):
            raise ValueError("change must be a PageChangeRecord")
        if self.change.edit_id != self.edit_id:
            raise ValueError("planned edit id must match change edit id")
        object.__setattr__(
            self,
            "independent_from",
            _text_tuple(self.independent_from, label="independent_from"),
        )
        if self.edit_id in self.independent_from:
            raise ValueError("an Edit cannot be independent from itself")


@dataclass(frozen=True)
class PlanRelation:
    source_edit_id: str
    target_edit_id: str
    kind: RelationKind
    materials: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_edit_id",
            _required_text(self.source_edit_id, label="source_edit_id"),
        )
        object.__setattr__(
            self,
            "target_edit_id",
            _required_text(self.target_edit_id, label="target_edit_id"),
        )
        if self.source_edit_id == self.target_edit_id:
            raise ValueError("relation source and target must differ")
        if self.kind not in RELATION_KINDS:
            raise ValueError(f"unsupported relation kind: {self.kind}")
        object.__setattr__(
            self,
            "materials",
            _text_tuple(self.materials, label="relation.materials", minimum=1),
        )


@dataclass(frozen=True)
class SequenceValidation:
    hard_dependency_count: int
    independent_edit_ids: tuple[str, ...]
    edit_type_counts: dict[str, int]


@dataclass(frozen=True)
class PlannedSequence:
    edits: tuple[PlannedEdit, ...]
    relations: tuple[PlanRelation, ...]
    initial_materials: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "edits", tuple(self.edits))
        object.__setattr__(self, "relations", tuple(self.relations))
        object.__setattr__(
            self,
            "initial_materials",
            _text_tuple(self.initial_materials, label="initial_materials"),
        )

    def validate(self) -> SequenceValidation:
        if not 1 <= len(self.edits) <= 5:
            raise ValueError("planned sequence requires 1 to 5 Edits")
        edit_ids = [edit.edit_id for edit in self.edits]
        if len(set(edit_ids)) != len(edit_ids):
            raise ValueError("planned edit ids must be unique")
        if [edit.index for edit in self.edits] != list(range(1, len(self.edits) + 1)):
            raise ValueError("planned edit indexes must be consecutive and ordered")

        by_id = {edit.edit_id: edit for edit in self.edits}
        available = set(self.initial_materials)
        for edit in self.edits:
            edit.change.validate()
            for key in edit.change.reads:
                if key not in available:
                    raise ValueError(f"{edit.edit_id} reads unavailable material {key}")
            for material in edit.change.mutates:
                if material.key not in available:
                    raise ValueError(
                        f"{edit.edit_id} mutates unavailable material {material.key}"
                    )
            for key in edit.change.preserves:
                if key not in available:
                    raise ValueError(f"{edit.edit_id} preserves unavailable material {key}")
            for material in edit.change.creates:
                if material.key in available:
                    raise ValueError(
                        f"{edit.edit_id} creates existing material {material.key}; use mutates"
                    )
            available.update(edit.change.created_keys)

        hard_dependency_count = 0
        seen_relations: set[tuple[str, str, str, tuple[str, ...]]] = set()
        for relation in self.relations:
            signature = (
                relation.source_edit_id,
                relation.target_edit_id,
                relation.kind,
                relation.materials,
            )
            if signature in seen_relations:
                raise ValueError("duplicate plan relation")
            seen_relations.add(signature)
            if relation.source_edit_id not in by_id or relation.target_edit_id not in by_id:
                raise ValueError("plan relation references an unknown Edit")
            source = by_id[relation.source_edit_id]
            target = by_id[relation.target_edit_id]
            if source.index >= target.index:
                raise ValueError("plan relation must point from an earlier to a later Edit")

            if relation.kind == "consumes":
                hard_dependency_count += 1
                for material in relation.materials:
                    if material not in source.change.changed_keys:
                        raise ValueError(
                            f"{source.edit_id} does not produce consumed material {material}"
                        )
                    if material not in target.change.reads:
                        raise ValueError(
                            f"{target.edit_id} does not read consumed material {material}"
                        )
            elif relation.kind == "extends":
                hard_dependency_count += 1
                for material in relation.materials:
                    if material not in source.change.created_keys:
                        raise ValueError(
                            f"{source.edit_id} does not create extended material {material}"
                        )
                    if material not in target.change.mutated_keys:
                        raise ValueError(
                            f"{target.edit_id} does not mutate extended material {material}"
                        )
            elif relation.kind == "preserves":
                for material in relation.materials:
                    if material not in source.change.changed_keys:
                        raise ValueError(
                            f"{source.edit_id} does not change preserved material {material}"
                        )
                    if material not in target.change.preserves:
                        raise ValueError(
                            f"{target.edit_id} does not preserve material {material}"
                        )
            else:  # conflicts
                for material in relation.materials:
                    if material not in source.change.changed_keys:
                        raise ValueError(
                            f"{source.edit_id} does not change conflicting material {material}"
                        )
                    if material not in target.change.changed_keys:
                        raise ValueError(
                            f"{target.edit_id} does not change conflicting material {material}"
                        )

        independent_ids: list[str] = []
        for edit in self.edits:
            if not edit.independent_from:
                continue
            for source_id in edit.independent_from:
                if source_id not in by_id:
                    raise ValueError(f"{edit.edit_id} references unknown independent Edit")
                source = by_id[source_id]
                if source.index >= edit.index:
                    raise ValueError("independent_from must reference an earlier Edit")
                if source.change.changed_keys & (
                    set(edit.change.reads) | edit.change.mutated_keys
                ):
                    raise ValueError(
                        f"{edit.edit_id} is not independent from {source.edit_id}"
                    )
            independent_ids.append(edit.edit_id)

        if hard_dependency_count < 1:
            raise ValueError("planned sequence requires at least one hard dependency")
        if not independent_ids:
            raise ValueError("planned sequence requires at least one independent later Edit")

        edit_type_counts = Counter(
            edit_type
            for edit in self.edits
            for edit_type in edit.change.edit_types
        )
        return SequenceValidation(
            hard_dependency_count=hard_dependency_count,
            independent_edit_ids=tuple(independent_ids),
            edit_type_counts=dict(sorted(edit_type_counts.items())),
        )


@dataclass(frozen=True)
class ReconciliationResult:
    status: ReconciliationStatus
    missing_materials: tuple[str, ...] = ()
    rebound_materials: dict[str, str] = field(default_factory=dict)
    violated_preservations: tuple[str, ...] = ()


def compare_planned_to_actual(
    planned: PageChangeRecord,
    actual: PageChangeRecord,
    *,
    material_aliases: Mapping[str, str] | None = None,
    violated_preservations: Sequence[str] = (),
) -> ReconciliationResult:
    """Compare a planned page change with browser-backed actual evidence.

    ``material_aliases`` lets a later Edit consume the actual material name
    when the implementation chose a semantically equivalent internal name.
    The caller must establish semantic equivalence; this function only checks
    that the rebound material exists with the same material kind.
    """

    planned.validate()
    actual.validate()
    aliases = dict(material_aliases or {})
    actual_by_key = {
        material.key: material
        for material in (*actual.creates, *actual.mutates)
    }
    missing: list[str] = []
    rebound: dict[str, str] = {}
    for material in (*planned.creates, *planned.mutates):
        actual_key = aliases.get(material.key, material.key)
        actual_material = actual_by_key.get(actual_key)
        if actual_material is None or actual_material.kind != material.kind:
            missing.append(material.key)
            continue
        if actual_key != material.key:
            rebound[material.key] = actual_key

    preservation_failures = list(violated_preservations)
    for preserved in planned.preserves:
        if preserved not in actual.preserves and preserved not in preservation_failures:
            preservation_failures.append(preserved)

    if preservation_failures:
        return ReconciliationResult(
            status="preservation_failed",
            missing_materials=tuple(missing),
            rebound_materials=rebound,
            violated_preservations=tuple(preservation_failures),
        )
    if missing:
        return ReconciliationResult(
            status="missing",
            missing_materials=tuple(missing),
            rebound_materials=rebound,
        )
    if rebound:
        return ReconciliationResult(status="rebound", rebound_materials=rebound)
    return ReconciliationResult(status="exact")


__all__ = [
    "PageChangeRecord",
    "PageMaterial",
    "PlanRelation",
    "PlannedEdit",
    "PlannedSequence",
    "ReconciliationResult",
    "SequenceValidation",
    "compare_planned_to_actual",
]

