"""Deterministic evidence for an earlier Edit influencing a later Edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


ActionStatus = Literal["ok", "error"]
ReverseMode = Literal["precondition_probe", "materialized_branch"]
ReverseStatus = Literal[
    "missing_prerequisite",
    "unexpectedly_possible",
    "invalid_probe",
]
CertificateStatus = Literal[
    "certified",
    "missing_source_absence_evidence",
    "missing_produced_material",
    "reverse_order_not_rejected",
    "invalid_reverse_probe",
    "insufficient_interventions",
    "intervention_action_failed",
    "producer_not_observed",
    "consumer_not_observed",
    "producer_does_not_vary",
    "consumer_does_not_respond",
    "nondeterministic_response",
    "restore_failed",
    "regression_failed",
]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ReverseOrderProbe:
    """Evidence from attempting B before A.

    ``precondition_probe`` is the cheap production default.  A selected audit
    subset can use ``materialized_branch`` to implement the reverse branch.
    """

    attempted_order: tuple[str, str]
    mode: ReverseMode
    status: ReverseStatus
    missing_material: str
    evidence_ref: str

    def __post_init__(self) -> None:
        order = tuple(self.attempted_order)
        if len(order) != 2 or order[0] == order[1]:
            raise ValueError("attempted_order must contain two different Edit ids")
        object.__setattr__(
            self,
            "attempted_order",
            tuple(_text(row, "attempted_order item") for row in order),
        )
        if self.mode not in {"precondition_probe", "materialized_branch"}:
            raise ValueError(f"unsupported reverse probe mode: {self.mode}")
        if self.status not in {
            "missing_prerequisite",
            "unexpectedly_possible",
            "invalid_probe",
        }:
            raise ValueError(f"unsupported reverse probe status: {self.status}")
        object.__setattr__(
            self,
            "missing_material",
            _text(self.missing_material, "missing_material"),
        )
        object.__setattr__(
            self, "evidence_ref", _text(self.evidence_ref, "evidence_ref")
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReverseOrderProbe":
        return cls(
            attempted_order=tuple(payload.get("attempted_order", ())),
            mode=payload.get("mode"),
            status=payload.get("status"),
            missing_material=payload.get("missing_material"),
            evidence_ref=payload.get("evidence_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted_order": list(self.attempted_order),
            "mode": self.mode,
            "status": self.status,
            "missing_material": self.missing_material,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class InterventionObservation:
    """One browser observation after changing the producer state."""

    case_id: str
    producer_fingerprint: str
    consumer_fingerprint: str
    action_status: ActionStatus
    producer_observed: bool
    consumer_observed: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "case_id",
            "producer_fingerprint",
            "consumer_fingerprint",
            "evidence_ref",
        ):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name)
            )
        if self.action_status not in {"ok", "error"}:
            raise ValueError(f"unsupported action status: {self.action_status}")
        if not isinstance(self.producer_observed, bool) or not isinstance(
            self.consumer_observed, bool
        ):
            raise ValueError("observation flags must be boolean")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "InterventionObservation":
        return cls(
            case_id=payload.get("case_id"),
            producer_fingerprint=payload.get("producer_fingerprint"),
            consumer_fingerprint=payload.get("consumer_fingerprint"),
            action_status=payload.get("action_status"),
            producer_observed=payload.get("producer_observed"),
            consumer_observed=payload.get("consumer_observed"),
            evidence_ref=payload.get("evidence_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "producer_fingerprint": self.producer_fingerprint,
            "consumer_fingerprint": self.consumer_fingerprint,
            "action_status": self.action_status,
            "producer_observed": self.producer_observed,
            "consumer_observed": self.consumer_observed,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class DependencyInterventionSpec:
    producer_edit_id: str
    consumer_edit_id: str
    material_key: str
    source_absence_confirmed: bool
    material_after_producer_confirmed: bool
    reverse_order_probe: ReverseOrderProbe | Mapping[str, Any]
    observations: tuple[InterventionObservation | Mapping[str, Any], ...]
    baseline_case_id: str
    restore_case_id: str
    regression_passed: bool

    def __post_init__(self) -> None:
        for field_name in (
            "producer_edit_id",
            "consumer_edit_id",
            "material_key",
            "baseline_case_id",
            "restore_case_id",
        ):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name)
            )
        if self.producer_edit_id == self.consumer_edit_id:
            raise ValueError("producer and consumer Edit ids must differ")
        for field_name in (
            "source_absence_confirmed",
            "material_after_producer_confirmed",
            "regression_passed",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be boolean")
        reverse = self.reverse_order_probe
        if not isinstance(reverse, ReverseOrderProbe):
            if not isinstance(reverse, Mapping):
                raise ValueError("reverse_order_probe must be an object")
            reverse = ReverseOrderProbe.from_dict(reverse)
        object.__setattr__(self, "reverse_order_probe", reverse)
        observations = tuple(
            row
            if isinstance(row, InterventionObservation)
            else InterventionObservation.from_dict(row)
            for row in self.observations
        )
        if len({row.case_id for row in observations}) != len(observations):
            raise ValueError("intervention case ids must be unique")
        object.__setattr__(self, "observations", observations)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DependencyInterventionSpec":
        return cls(
            producer_edit_id=payload.get("producer_edit_id"),
            consumer_edit_id=payload.get("consumer_edit_id"),
            material_key=payload.get("material_key"),
            source_absence_confirmed=payload.get("source_absence_confirmed"),
            material_after_producer_confirmed=payload.get(
                "material_after_producer_confirmed"
            ),
            reverse_order_probe=payload.get("reverse_order_probe", {}),
            observations=tuple(payload.get("observations", ())),
            baseline_case_id=payload.get("baseline_case_id"),
            restore_case_id=payload.get("restore_case_id"),
            regression_passed=payload.get("regression_passed"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_edit_id": self.producer_edit_id,
            "consumer_edit_id": self.consumer_edit_id,
            "material_key": self.material_key,
            "source_absence_confirmed": self.source_absence_confirmed,
            "material_after_producer_confirmed": self.material_after_producer_confirmed,
            "reverse_order_probe": self.reverse_order_probe.to_dict(),
            "observations": [row.to_dict() for row in self.observations],
            "baseline_case_id": self.baseline_case_id,
            "restore_case_id": self.restore_case_id,
            "regression_passed": self.regression_passed,
        }


@dataclass(frozen=True)
class DependencyCertificate:
    status: CertificateStatus
    producer_edit_id: str
    consumer_edit_id: str
    material_key: str
    distinct_producer_values: int
    distinct_consumer_values: int
    reverse_order_status: str
    evidence_grade: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "producer_edit_id": self.producer_edit_id,
            "consumer_edit_id": self.consumer_edit_id,
            "material_key": self.material_key,
            "distinct_producer_values": self.distinct_producer_values,
            "distinct_consumer_values": self.distinct_consumer_values,
            "reverse_order_status": self.reverse_order_status,
            "evidence_grade": self.evidence_grade,
        }


def certify_dependency(spec: DependencyInterventionSpec) -> DependencyCertificate:
    """Certify A→B by changing A's value and observing B's response."""

    if not isinstance(spec, DependencyInterventionSpec):
        raise ValueError("spec must be a DependencyInterventionSpec")
    observations = spec.observations
    producer_values = {row.producer_fingerprint for row in observations}
    consumer_values = {row.consumer_fingerprint for row in observations}
    reverse_status = (
        "rejected_missing_prerequisite"
        if spec.reverse_order_probe.status == "missing_prerequisite"
        else spec.reverse_order_probe.status
    )
    evidence_grade = (
        "intervention_plus_reverse_branch"
        if spec.reverse_order_probe.mode == "materialized_branch"
        else "intervention_plus_precondition_probe"
    )

    def result(status: CertificateStatus) -> DependencyCertificate:
        return DependencyCertificate(
            status=status,
            producer_edit_id=spec.producer_edit_id,
            consumer_edit_id=spec.consumer_edit_id,
            material_key=spec.material_key,
            distinct_producer_values=len(producer_values),
            distinct_consumer_values=len(consumer_values),
            reverse_order_status=reverse_status,
            evidence_grade=evidence_grade,
        )

    if not spec.source_absence_confirmed:
        return result("missing_source_absence_evidence")
    if not spec.material_after_producer_confirmed:
        return result("missing_produced_material")
    expected_reverse = (spec.consumer_edit_id, spec.producer_edit_id)
    if spec.reverse_order_probe.attempted_order != expected_reverse:
        return result("invalid_reverse_probe")
    if spec.reverse_order_probe.missing_material != spec.material_key:
        return result("invalid_reverse_probe")
    if spec.reverse_order_probe.status == "invalid_probe":
        return result("invalid_reverse_probe")
    if spec.reverse_order_probe.status != "missing_prerequisite":
        return result("reverse_order_not_rejected")
    if len(observations) < 3:
        return result("insufficient_interventions")
    if any(row.action_status != "ok" for row in observations):
        return result("intervention_action_failed")
    if any(not row.producer_observed for row in observations):
        return result("producer_not_observed")
    if any(not row.consumer_observed for row in observations):
        return result("consumer_not_observed")
    if len(producer_values) < 2:
        return result("producer_does_not_vary")

    outputs_by_producer: dict[str, set[str]] = {}
    for row in observations:
        outputs_by_producer.setdefault(row.producer_fingerprint, set()).add(
            row.consumer_fingerprint
        )
    if any(len(outputs) > 1 for outputs in outputs_by_producer.values()):
        return result("nondeterministic_response")
    if len(consumer_values) < 2:
        return result("consumer_does_not_respond")

    by_id = {row.case_id: row for row in observations}
    baseline = by_id.get(spec.baseline_case_id)
    restored = by_id.get(spec.restore_case_id)
    if baseline is None or restored is None:
        return result("restore_failed")
    if (
        baseline.producer_fingerprint != restored.producer_fingerprint
        or baseline.consumer_fingerprint != restored.consumer_fingerprint
    ):
        return result("restore_failed")
    if not spec.regression_passed:
        return result("regression_failed")
    return result("certified")


__all__ = [
    "DependencyCertificate",
    "DependencyInterventionSpec",
    "InterventionObservation",
    "ReverseOrderProbe",
    "certify_dependency",
]
