"""Machine-readable capability evidence for automated decision gates.

A source digest identifies detector bytes; it does not establish how well the
detector works.  This module keeps those concepts separate and makes missing
measurements explicit instead of interpreting absence as perfect performance.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "amy.detector-characterization.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSURANCE_LEVELS = {"self_attested", "third_party", "reproduced"}
_USE_CASES = {"safety", "scientific_publication", "capability_claim"}


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 of the exact detector source bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unmeasured_characterization(
    *,
    name: str,
    version: str,
    source_path: Path | str,
    source_id: str | None = None,
    purpose: str,
    reason: str,
) -> dict[str, Any]:
    """Describe an identified detector whose capability has not been measured."""
    path = Path(source_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unmeasured",
        "detector": {
            "name": name,
            "version": version,
            "sha256": sha256_file(path),
            "source": source_id or path.as_posix(),
        },
        "purpose": purpose,
        "reason": reason,
    }


def validate_characterization(record: object) -> dict[str, Any]:
    """Validate a characterization record without trusting declared metrics."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return {"valid": False, "status": "invalid", "errors": ["record must be an object"]}

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    status = record.get("status")
    if status not in {"measured", "unmeasured"}:
        errors.append("status must be measured or unmeasured")

    detector = record.get("detector")
    if not isinstance(detector, dict):
        errors.append("detector must be an object")
    else:
        for field in ("name", "version"):
            if not _nonempty_string(detector.get(field)):
                errors.append(f"detector.{field} must be a non-empty string")
        digest = detector.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append("detector.sha256 must be a lowercase SHA-256 digest")

    purpose = record.get("purpose")
    if purpose not in _USE_CASES:
        errors.append(f"purpose must be one of {sorted(_USE_CASES)}")

    if status == "unmeasured":
        if not _nonempty_string(record.get("reason")):
            errors.append("unmeasured records require a reason")
    elif status == "measured":
        _validate_measured_fields(record, errors)

    return {
        "valid": not errors,
        "status": status if not errors else "invalid",
        "errors": errors,
    }


def evaluate_characterization(
    record: object,
    *,
    use_case: str,
    minimum_sensitivity_lower: float | None = None,
    minimum_specificity_lower: float | None = None,
) -> dict[str, Any]:
    """Apply fail-safe policy to one detector characterization.

    Safety decisions require valid measurements whose lower confidence bounds
    meet policy. Scientific publication additionally requires independent or
    reproduced assurance before automated external release. Capability claims
    remain qualified because estimates are scoped to the declared task/set.
    """
    if use_case not in _USE_CASES:
        raise ValueError(f"unsupported use_case: {use_case}")
    for label, value in (
        ("minimum_sensitivity_lower", minimum_sensitivity_lower),
        ("minimum_specificity_lower", minimum_specificity_lower),
    ):
        if value is not None and not _probability(value):
            raise ValueError(f"{label} must be between 0 and 1")

    validation = validate_characterization(record)
    status = validation["status"]
    detector = record.get("detector") if isinstance(record, dict) else None
    base = {
        "status": status,
        "use_case": use_case,
        "detector": dict(detector) if isinstance(detector, dict) else None,
        "purpose": record.get("purpose") if isinstance(record, dict) else None,
        "eligible": False,
        "external_release_eligible": False,
        "manual_review_required": True,
        "errors": validation["errors"],
    }
    if status == "invalid":
        return {**base, "decision": "block", "reason": "invalid characterization"}
    if status == "unmeasured":
        decision = "block" if use_case == "safety" else (
            "manual_review_required" if use_case == "scientific_publication" else "qualify"
        )
        return {
            **base,
            "decision": decision,
            "reason": "detector capability is unmeasured; identity is not capability",
        }

    measured = record  # validated as a dict above
    if use_case in {"safety", "scientific_publication"} and (
        minimum_sensitivity_lower is None or minimum_specificity_lower is None
    ):
        return {
            **base,
            "decision": "block" if use_case == "safety" else "manual_review_required",
            "reason": "no explicit lower-confidence-bound acceptance policy was supplied",
        }
    sensitivity_lower = measured["estimates"]["sensitivity"]["ci95_lower"]
    specificity_lower = measured["estimates"]["specificity"]["ci95_lower"]
    thresholds_met = (
        sensitivity_lower >= (minimum_sensitivity_lower or 0.0)
        and specificity_lower >= (minimum_specificity_lower or 0.0)
    )
    if not thresholds_met:
        return {
            **base,
            "decision": "block",
            "reason": "lower confidence bound is below policy threshold",
        }

    assurance = measured["assurance_level"]
    independently_assured = assurance in {"third_party", "reproduced"}
    if use_case == "safety":
        return {
            **base,
            "decision": "allow" if independently_assured else "block",
            "eligible": independently_assured,
            "external_release_eligible": independently_assured,
            "manual_review_required": not independently_assured,
            "reason": (
                "measured lower bounds and independent-assurance policy satisfied"
                if independently_assured
                else "self-attested measurements do not satisfy safety assurance"
            ),
        }
    if use_case == "scientific_publication":
        return {
            **base,
            "decision": "allow" if independently_assured else "manual_review_required",
            "eligible": independently_assured,
            "external_release_eligible": independently_assured,
            "manual_review_required": not independently_assured,
            "reason": (
                "measured characterization has independent or reproduced assurance"
                if independently_assured
                else "self-attested measurements require external review"
            ),
        }
    return {
        **base,
        "decision": "qualify",
        "eligible": True,
        "reason": "capability estimate is valid only for the declared scope and evaluation set",
    }


def summarize_characterizations(
    records: list[object],
    *,
    use_case: str = "scientific_publication",
    minimum_sensitivity_lower: float | None = None,
    minimum_specificity_lower: float | None = None,
) -> dict[str, Any]:
    """Summarize all gates; an empty inventory never becomes implicit success."""
    assessments = [
        evaluate_characterization(
            record,
            use_case=use_case,
            minimum_sensitivity_lower=minimum_sensitivity_lower,
            minimum_specificity_lower=minimum_specificity_lower,
        )
        for record in records
    ]
    if not assessments:
        return {
            "use_case": use_case,
            "decision": "block" if use_case == "safety" else "manual_review_required",
            "external_release_eligible": False,
            "manual_review_required": True,
            "counts": {"measured": 0, "unmeasured": 0, "invalid": 0},
            "assessments": [],
            "reason": "no detector characterization records supplied",
        }

    counts = {
        status: sum(item["status"] == status for item in assessments)
        for status in ("measured", "unmeasured", "invalid")
    }
    external_eligible = all(item["external_release_eligible"] for item in assessments)
    manual_review = any(item["manual_review_required"] for item in assessments)
    decisions = {item["decision"] for item in assessments}
    if "block" in decisions:
        decision = "block"
    elif "manual_review_required" in decisions:
        decision = "manual_review_required"
    elif decisions == {"allow"}:
        decision = "allow"
    else:
        decision = "qualify"
    return {
        "use_case": use_case,
        "decision": decision,
        "external_release_eligible": external_eligible,
        "manual_review_required": manual_review,
        "counts": counts,
        "assessments": assessments,
        "reason": "all detector records must independently satisfy the selected policy",
    }


def _validate_measured_fields(record: dict[str, Any], errors: list[str]) -> None:
    task = record.get("task")
    if not isinstance(task, dict):
        errors.append("task must be an object")
    else:
        for field in ("positive_class", "negative_class", "scope"):
            if not _nonempty_string(task.get(field)):
                errors.append(f"task.{field} must be a non-empty string")
        if not _probability(task.get("decision_threshold")):
            errors.append("task.decision_threshold must be between 0 and 1")

    evaluation_set = record.get("evaluation_set")
    counts: dict[str, int] | None = None
    if not isinstance(evaluation_set, dict):
        errors.append("evaluation_set must be an object")
    else:
        digest = evaluation_set.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append("evaluation_set.sha256 must be a lowercase SHA-256 digest")
        values = {field: evaluation_set.get(field) for field in ("sample_size", "positives", "negatives")}
        if not all(_nonnegative_int(value) for value in values.values()):
            errors.append("evaluation-set counts must be non-negative integers")
        else:
            counts = values
            if values["sample_size"] <= 0:
                errors.append("evaluation_set.sample_size must be positive")
            if values["positives"] <= 0 or values["negatives"] <= 0:
                errors.append("evaluation set must contain positive and negative examples")
            if values["positives"] + values["negatives"] != values["sample_size"]:
                errors.append("evaluation-set class counts must equal sample_size")

    matrix = record.get("confusion_matrix")
    matrix_values: dict[str, int] | None = None
    if not isinstance(matrix, dict):
        errors.append("confusion_matrix must be an object")
    else:
        values = {field: matrix.get(field) for field in ("tp", "fp", "tn", "fn")}
        if not all(_nonnegative_int(value) for value in values.values()):
            errors.append("confusion-matrix values must be non-negative integers")
        else:
            matrix_values = values
            if counts and (
                values["tp"] + values["fn"] != counts["positives"]
                or values["tn"] + values["fp"] != counts["negatives"]
            ):
                errors.append("confusion matrix does not match evaluation-set class counts")

    estimates = record.get("estimates")
    if not isinstance(estimates, dict):
        errors.append("estimates must be an object")
    else:
        for metric in ("sensitivity", "specificity"):
            estimate = estimates.get(metric)
            if not isinstance(estimate, dict):
                errors.append(f"estimates.{metric} must be an object")
                continue
            values = [estimate.get(field) for field in ("value", "ci95_lower", "ci95_upper")]
            if not all(_probability(value) for value in values):
                errors.append(f"estimates.{metric} values must be finite probabilities")
                continue
            value, lower, upper = values
            if not lower <= value <= upper:
                errors.append(f"estimates.{metric} confidence interval must contain value")

        if (
            matrix_values
            and matrix_values["tp"] + matrix_values["fn"] > 0
            and matrix_values["tn"] + matrix_values["fp"] > 0
        ):
            expected = {
                "sensitivity": matrix_values["tp"] / (matrix_values["tp"] + matrix_values["fn"]),
                "specificity": matrix_values["tn"] / (matrix_values["tn"] + matrix_values["fp"]),
            }
            for metric, expected_value in expected.items():
                estimate = estimates.get(metric)
                if isinstance(estimate, dict) and _probability(estimate.get("value")):
                    if not math.isclose(estimate["value"], expected_value, abs_tol=1e-12):
                        errors.append(f"estimates.{metric}.value does not match confusion matrix")

    if record.get("assurance_level") not in _ASSURANCE_LEVELS:
        errors.append(f"assurance_level must be one of {sorted(_ASSURANCE_LEVELS)}")
    evidence_ref = record.get("evidence_ref")
    if not isinstance(evidence_ref, dict):
        errors.append("evidence_ref must be an object")
    else:
        if not _nonempty_string(evidence_ref.get("predicate_type")):
            errors.append("evidence_ref.predicate_type must be a non-empty string")
        digest = evidence_ref.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            errors.append("evidence_ref.sha256 must be a lowercase SHA-256 digest")
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(
        _nonempty_string(item) for item in limitations
    ):
        errors.append("limitations must be a non-empty list of strings")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _probability(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )
