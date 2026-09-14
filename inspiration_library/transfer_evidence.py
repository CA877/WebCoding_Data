"""Host-conditioned evidence for reusing observed webpage changes.

Semantic interpretation remains an LLM responsibility.  This module stores
the LLM's explicit host-role mapping and then performs deterministic gates and
ranking.  It deliberately separates an abstract browser-visible effect from
the donor code variants that may later help a code model implement the effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
from math import inf
import os
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping


TransferOutcome = Literal[
    "accepted",
    "missing_prerequisite",
    "source_already_has_behavior",
    "regression_conflict",
    "environment_mismatch",
    "task_verifier_conflict",
    "target_failed",
    "cost_regression",
]

OUTCOMES = frozenset(
    {
        "accepted",
        "missing_prerequisite",
        "source_already_has_behavior",
        "regression_conflict",
        "environment_mismatch",
        "task_verifier_conflict",
        "target_failed",
        "cost_regression",
    }
)
CURRENT_HOST_BLOCKERS = frozenset(
    {
        "missing_prerequisite",
        "source_already_has_behavior",
        "task_verifier_conflict",
    }
)
VARIANT_BLOCKERS = frozenset(
    {"environment_mismatch", "task_verifier_conflict", "regression_conflict"}
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _texts(value: object, label: str, *, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    rows = tuple(_text(item, f"{label} item") for item in value)
    if len(rows) < minimum:
        raise ValueError(f"{label} requires at least {minimum} value(s)")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label} must not contain duplicates")
    return rows


@dataclass(frozen=True)
class ImplementationVariant:
    """One hidden implementation carrier for an abstract page effect."""

    variant_id: str
    effect_family_id: str
    framework: str
    architecture_tags: tuple[str, ...]
    code_slice_ref: str
    test_slice_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "variant_id",
            "effect_family_id",
            "framework",
            "code_slice_ref",
            "test_slice_ref",
            "evidence_ref",
        ):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "architecture_tags",
            _texts(self.architecture_tags, "architecture_tags"),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ImplementationVariant":
        return cls(
            variant_id=payload.get("variant_id"),
            effect_family_id=payload.get("effect_family_id"),
            framework=payload.get("framework"),
            architecture_tags=payload.get("architecture_tags", ()),
            code_slice_ref=payload.get("code_slice_ref"),
            test_slice_ref=payload.get("test_slice_ref"),
            evidence_ref=payload.get("evidence_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "effect_family_id": self.effect_family_id,
            "framework": self.framework,
            "architecture_tags": list(self.architecture_tags),
            "code_slice_ref": self.code_slice_ref,
            "test_slice_ref": self.test_slice_ref,
            "evidence_ref": self.evidence_ref,
            "training_instruction_visible": False,
        }


@dataclass(frozen=True)
class EffectFamily:
    """A browser-visible effect independent of framework and donor code."""

    effect_family_id: str
    summary: str
    required_roles: tuple[str, ...]
    produced_material_kinds: tuple[str, ...]
    observable_results: tuple[str, ...]
    implementation_variants: tuple[ImplementationVariant, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effect_family_id",
            _text(self.effect_family_id, "effect_family_id"),
        )
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(
            self,
            "required_roles",
            _texts(self.required_roles, "required_roles", minimum=1),
        )
        object.__setattr__(
            self,
            "produced_material_kinds",
            _texts(
                self.produced_material_kinds,
                "produced_material_kinds",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "observable_results",
            _texts(self.observable_results, "observable_results", minimum=1),
        )
        variants = tuple(
            row
            if isinstance(row, ImplementationVariant)
            else ImplementationVariant.from_dict(row)
            for row in self.implementation_variants
        )
        if len({row.variant_id for row in variants}) != len(variants):
            raise ValueError("implementation variant ids must be unique")
        if any(row.effect_family_id != self.effect_family_id for row in variants):
            raise ValueError("implementation variant belongs to another effect family")
        object.__setattr__(self, "implementation_variants", variants)

    def to_planner_dict(self) -> dict[str, Any]:
        """Return the effect-only view; donor code is intentionally absent."""

        return {
            "effect_family_id": self.effect_family_id,
            "summary": self.summary,
            "required_roles": list(self.required_roles),
            "produced_material_kinds": list(self.produced_material_kinds),
            "observable_results": list(self.observable_results),
        }


@dataclass(frozen=True)
class HostFitAssessment:
    """Semantic host mapping produced by an LLM or a human reviewer."""

    effect_family_id: str
    host_profile_id: str
    natural_gap: bool
    semantic_fit: float
    mapped_roles: tuple[str, ...]
    future_uses: tuple[str, ...]
    framework: str
    architecture_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effect_family_id",
            _text(self.effect_family_id, "effect_family_id"),
        )
        object.__setattr__(
            self, "host_profile_id", _text(self.host_profile_id, "host_profile_id")
        )
        if not isinstance(self.natural_gap, bool):
            raise ValueError("natural_gap must be boolean")
        if isinstance(self.semantic_fit, bool) or not isinstance(
            self.semantic_fit, (int, float)
        ):
            raise ValueError("semantic_fit must be a number")
        if not 0.0 <= float(self.semantic_fit) <= 1.0:
            raise ValueError("semantic_fit must be between 0 and 1")
        object.__setattr__(self, "semantic_fit", float(self.semantic_fit))
        object.__setattr__(
            self, "mapped_roles", _texts(self.mapped_roles, "mapped_roles")
        )
        object.__setattr__(
            self, "future_uses", _texts(self.future_uses, "future_uses")
        )
        object.__setattr__(self, "framework", _text(self.framework, "framework"))
        object.__setattr__(
            self,
            "architecture_tags",
            _texts(self.architecture_tags, "architecture_tags"),
        )


@dataclass(frozen=True)
class TransferEvidence:
    """An observed transfer result.  Absence of a row remains unknown."""

    evidence_id: str
    effect_family_id: str
    host_profile_id: str
    host_roles: tuple[str, ...]
    outcome: TransferOutcome
    browser_evidence_refs: tuple[str, ...]
    implementation_variant_id: str | None = None
    framework: str | None = None
    token_cost: int | None = None
    wall_time_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "effect_family_id", "host_profile_id"):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "host_roles", _texts(self.host_roles, "host_roles", minimum=1)
        )
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unsupported transfer outcome: {self.outcome}")
        object.__setattr__(
            self,
            "browser_evidence_refs",
            _texts(
                self.browser_evidence_refs,
                "browser_evidence_refs",
                minimum=1,
            ),
        )
        if self.implementation_variant_id is not None:
            object.__setattr__(
                self,
                "implementation_variant_id",
                _text(self.implementation_variant_id, "implementation_variant_id"),
            )
        if self.framework is not None:
            object.__setattr__(self, "framework", _text(self.framework, "framework"))
        if self.token_cost is not None and (
            isinstance(self.token_cost, bool) or self.token_cost < 0
        ):
            raise ValueError("token_cost must be non-negative")
        if self.wall_time_seconds is not None and (
            isinstance(self.wall_time_seconds, bool) or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds must be non-negative")

    @property
    def sign(self) -> Literal["positive", "negative"]:
        return "positive" if self.outcome == "accepted" else "negative"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TransferEvidence":
        return cls(
            evidence_id=payload.get("evidence_id"),
            effect_family_id=payload.get("effect_family_id"),
            host_profile_id=payload.get("host_profile_id"),
            host_roles=tuple(payload.get("host_roles", ())),
            outcome=payload.get("outcome"),
            browser_evidence_refs=tuple(payload.get("browser_evidence_refs", ())),
            implementation_variant_id=payload.get("implementation_variant_id"),
            framework=payload.get("framework"),
            token_cost=payload.get("token_cost"),
            wall_time_seconds=payload.get("wall_time_seconds"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "webcoding-transfer-evidence-v1",
            "evidence_id": self.evidence_id,
            "effect_family_id": self.effect_family_id,
            "host_profile_id": self.host_profile_id,
            "host_roles": list(self.host_roles),
            "outcome": self.outcome,
            "sign": self.sign,
            "browser_evidence_refs": list(self.browser_evidence_refs),
            "implementation_variant_id": self.implementation_variant_id,
            "framework": self.framework,
            "token_cost": self.token_cost,
            "wall_time_seconds": self.wall_time_seconds,
        }


def load_transfer_evidence(path: Path) -> tuple[TransferEvidence, ...]:
    if not path.exists():
        return ()
    rows: list[TransferEvidence] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"transfer evidence line {line_number} is not an object")
            row = TransferEvidence.from_dict(payload)
            if row.evidence_id in seen:
                raise ValueError(f"duplicate transfer evidence id: {row.evidence_id}")
            seen.add(row.evidence_id)
            rows.append(row)
    return tuple(rows)


def append_transfer_evidence(path: Path, evidence: TransferEvidence) -> bool:
    """Append one new attempt; an existing evidence id is left untouched."""

    if not isinstance(evidence, TransferEvidence):
        raise ValueError("evidence must be a TransferEvidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            existing_ids = {
                str(json.loads(line)["evidence_id"])
                for line in handle
                if line.strip()
            }
            if evidence.evidence_id in existing_ids:
                return False
            handle.seek(0, os.SEEK_END)
            handle.write(
                json.dumps(
                    evidence.to_dict(), ensure_ascii=False, separators=(",", ":")
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return True


@dataclass(frozen=True)
class RankedEffect:
    effect_family_id: str
    summary: str
    semantic_fit: float
    future_uses: tuple[str, ...]
    matched_successes: int
    matched_failures: int
    evidence_status: Literal["positive", "mixed", "negative", "unknown"]
    average_accepted_token_cost: float | None
    required_roles: tuple[str, ...]
    observable_results: tuple[str, ...]

    def to_planner_dict(self) -> dict[str, Any]:
        return {
            "effect_family_id": self.effect_family_id,
            "summary": self.summary,
            "semantic_fit": self.semantic_fit,
            "future_uses": list(self.future_uses),
            "matched_successes": self.matched_successes,
            "matched_failures": self.matched_failures,
            "evidence_status": self.evidence_status,
            "required_roles": list(self.required_roles),
            "observable_results": list(self.observable_results),
        }


def _role_match(required_roles: tuple[str, ...], evidence: TransferEvidence) -> bool:
    return set(required_roles).issubset(evidence.host_roles)


def rank_effect_families(
    families: Iterable[EffectFamily],
    assessments: Iterable[HostFitAssessment],
    evidence: Iterable[TransferEvidence],
    *,
    top_k: int,
) -> tuple[RankedEffect, ...]:
    """Rank abstract effects without exposing donor implementation carriers.

    Ordering is lexicographic and inspectable: product fit, future use, matched
    successes, matched failures, accepted cost, then stable id.  Unknown pairs
    are never converted into negative examples.
    """

    if top_k < 1:
        raise ValueError("top_k must be positive")
    family_rows = tuple(families)
    by_family = {row.effect_family_id: row for row in family_rows}
    if len(by_family) != len(family_rows):
        raise ValueError("effect family ids must be unique")
    assessment_rows = tuple(assessments)
    assessment_by_family = {row.effect_family_id: row for row in assessment_rows}
    if len(assessment_by_family) != len(assessment_rows):
        raise ValueError("one host fit assessment is allowed per effect family")
    evidence_rows = tuple(evidence)

    ranked: list[RankedEffect] = []
    for family in family_rows:
        assessment = assessment_by_family.get(family.effect_family_id)
        if assessment is None or not assessment.natural_gap:
            continue
        missing_roles = set(family.required_roles) - set(assessment.mapped_roles)
        if missing_roles:
            raise ValueError(
                f"{family.effect_family_id} has unmapped required roles: "
                + ", ".join(sorted(missing_roles))
            )
        family_evidence = tuple(
            row
            for row in evidence_rows
            if row.effect_family_id == family.effect_family_id
        )
        if any(
            row.host_profile_id == assessment.host_profile_id
            and row.outcome in CURRENT_HOST_BLOCKERS
            for row in family_evidence
        ):
            continue
        matched = tuple(
            row for row in family_evidence if _role_match(family.required_roles, row)
        )
        successes = sum(row.outcome == "accepted" for row in matched)
        failures = sum(row.outcome != "accepted" for row in matched)
        accepted_costs = [
            row.token_cost
            for row in matched
            if row.outcome == "accepted" and row.token_cost is not None
        ]
        if successes and failures:
            evidence_status: Literal["positive", "mixed", "negative", "unknown"] = (
                "mixed"
            )
        elif successes:
            evidence_status = "positive"
        elif failures:
            evidence_status = "negative"
        else:
            evidence_status = "unknown"
        ranked.append(
            RankedEffect(
                effect_family_id=family.effect_family_id,
                summary=family.summary,
                semantic_fit=assessment.semantic_fit,
                future_uses=assessment.future_uses,
                matched_successes=successes,
                matched_failures=failures,
                evidence_status=evidence_status,
                average_accepted_token_cost=(
                    sum(accepted_costs) / len(accepted_costs)
                    if accepted_costs
                    else None
                ),
                required_roles=family.required_roles,
                observable_results=family.observable_results,
            )
        )
    ranked.sort(
        key=lambda row: (
            -row.semantic_fit,
            -len(row.future_uses),
            -row.matched_successes,
            row.matched_failures,
            row.average_accepted_token_cost
            if row.average_accepted_token_cost is not None
            else inf,
            row.effect_family_id,
        )
    )
    return tuple(ranked[:top_k])


def select_implementation_variants(
    family: EffectFamily,
    assessment: HostFitAssessment,
    evidence: Iterable[TransferEvidence],
    *,
    top_k: int,
) -> tuple[ImplementationVariant, ...]:
    """Select donor code only after the abstract effect has been chosen."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if family.effect_family_id != assessment.effect_family_id:
        raise ValueError("effect family and host fit assessment do not match")
    allowed_tags = set(assessment.architecture_tags)
    evidence_rows = tuple(evidence)
    scored: list[tuple[tuple[Any, ...], ImplementationVariant]] = []
    for variant in family.implementation_variants:
        if variant.framework not in {assessment.framework, "any"}:
            continue
        if variant.architecture_tags and not set(variant.architecture_tags).issubset(
            allowed_tags
        ):
            continue
        variant_evidence = tuple(
            row
            for row in evidence_rows
            if row.effect_family_id == family.effect_family_id
            and row.implementation_variant_id == variant.variant_id
        )
        compatible = tuple(
            row
            for row in variant_evidence
            if row.framework in {None, assessment.framework}
            and _role_match(family.required_roles, row)
        )
        successes = sum(row.outcome == "accepted" for row in compatible)
        failures = sum(row.outcome != "accepted" for row in compatible)
        hard_failures = sum(row.outcome in VARIANT_BLOCKERS for row in compatible)
        if hard_failures and not successes:
            continue
        costs = [
            row.token_cost
            for row in compatible
            if row.outcome == "accepted" and row.token_cost is not None
        ]
        scored.append(
            (
                (
                    -successes,
                    failures,
                    sum(costs) / len(costs) if costs else inf,
                    variant.variant_id,
                ),
                variant,
            )
        )
    scored.sort(key=lambda row: row[0])
    return tuple(row[1] for row in scored[:top_k])


__all__ = [
    "EffectFamily",
    "HostFitAssessment",
    "ImplementationVariant",
    "RankedEffect",
    "TransferEvidence",
    "append_transfer_evidence",
    "load_transfer_evidence",
    "rank_effect_families",
    "select_implementation_variants",
]
