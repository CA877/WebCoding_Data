"""Preflight consistency checks between an Edit, its gap test, and verifiers.

An LLM or reviewer first maps natural-language requirements to stable effect
ids.  These functions only compare those ids and do not attempt semantic
extraction with keywords or regular expressions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


def _texts(value: object, label: str, *, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    rows: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label} contains an empty value")
        rows.append(item.strip())
    if len(rows) < minimum:
        raise ValueError(f"{label} requires at least {minimum} value(s)")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label} must not contain duplicates")
    return tuple(rows)


@dataclass(frozen=True)
class PlanningConsistencyInput:
    required_effects: tuple[str, ...]
    source_gap_effects: tuple[str, ...]
    target_verifier_effects: tuple[str, ...]
    forbidden_effects: tuple[str, ...]
    preservation_effects: tuple[str, ...] = ()
    regression_verifier_effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_effects",
            _texts(self.required_effects, "required_effects", minimum=1),
        )
        for field_name in (
            "source_gap_effects",
            "target_verifier_effects",
            "forbidden_effects",
            "preservation_effects",
            "regression_verifier_effects",
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name),
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanningConsistencyInput":
        return cls(
            required_effects=payload.get("required_effects", ()),
            source_gap_effects=payload.get("source_gap_effects", ()),
            target_verifier_effects=payload.get("target_verifier_effects", ()),
            forbidden_effects=payload.get("forbidden_effects", ()),
            preservation_effects=payload.get("preservation_effects", ()),
            regression_verifier_effects=payload.get(
                "regression_verifier_effects", ()
            ),
        )


@dataclass(frozen=True)
class PlanningConsistencyResult:
    status: Literal["consistent", "contradictory", "incomplete"]
    required_but_forbidden: tuple[str, ...]
    missing_source_gap_effects: tuple[str, ...]
    unverified_required_effects: tuple[str, ...]
    unverified_preservations: tuple[str, ...]


def check_planning_consistency(
    payload: PlanningConsistencyInput,
) -> PlanningConsistencyResult:
    required = set(payload.required_effects)
    contradictory = required & set(payload.forbidden_effects)
    missing_gap = required - set(payload.source_gap_effects)
    missing_target = required - set(payload.target_verifier_effects)
    missing_regression = set(payload.preservation_effects) - set(
        payload.regression_verifier_effects
    )
    if contradictory:
        status: Literal["consistent", "contradictory", "incomplete"] = (
            "contradictory"
        )
    elif missing_gap or missing_target or missing_regression:
        status = "incomplete"
    else:
        status = "consistent"
    return PlanningConsistencyResult(
        status=status,
        required_but_forbidden=tuple(sorted(contradictory)),
        missing_source_gap_effects=tuple(sorted(missing_gap)),
        unverified_required_effects=tuple(sorted(missing_target)),
        unverified_preservations=tuple(sorted(missing_regression)),
    )


__all__ = [
    "PlanningConsistencyInput",
    "PlanningConsistencyResult",
    "check_planning_consistency",
]
