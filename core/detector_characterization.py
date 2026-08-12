"""Machine-readable capability evidence for automated decision gates.

A source digest identifies detector bytes; it does not establish how well the
detector works. Missing measurements make no claim, and issuer-declared
assurance is never treated as independently verified evidence.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "amy.detector-characterization.v2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_PROBABILITY_RE = re.compile(r"^(?:0(?:\.\d+)?|1(?:\.0+)?)$")
_METRIC_TOLERANCE = Decimal("1e-12")
_ASSURANCE_LEVELS = {
    "self_attested",
    "third_party",
    "reproduced",
    "enclave_attested",
}
_USE_CASES = {"safety", "scientific_publication", "capability_claim"}
_POSITIVE_CLASS_ROLES = {"capability_evidence", "failure_evidence", "other"}
_PASS_CONDITIONS = {
    "presence_of_detected_positives",
    "absence_of_detected_positives",
    "other",
}


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
            "digest": {"sha256": sha256_file(path)},
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
        _validate_digest_set(detector.get("digest"), "detector.digest", errors)

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
    minimum_sensitivity_lower: str | None = None,
    minimum_specificity_lower: str | None = None,
    assurance_verification: object = None,
    claim_semantics: object = None,
) -> dict[str, Any]:
    """Apply fail-safe policy to one detector characterization.

    Policy thresholds use decimal strings to avoid JSON floating-point
    ambiguity. ``asserted_assurance_level`` remains producer testimony; a
    separate, digest-bound verification result must authenticate and authorize
    the referenced evidence before it can satisfy safety or release policy.
    """
    if use_case not in _USE_CASES:
        raise ValueError(f"unsupported use_case: {use_case}")
    parsed_thresholds: dict[str, Decimal | None] = {}
    for label, value in (
        ("minimum_sensitivity_lower", minimum_sensitivity_lower),
        ("minimum_specificity_lower", minimum_specificity_lower),
    ):
        parsed = _parse_decimal_probability(value) if value is not None else None
        if value is not None and parsed is None:
            raise ValueError(f"{label} must be a decimal string between 0 and 1")
        parsed_thresholds[label] = parsed

    validation = validate_characterization(record)
    status = validation["status"]
    detector = record.get("detector") if isinstance(record, dict) else None
    semantics = _assess_claim_semantics(record, claim_semantics)
    base = {
        "status": status,
        "use_case": use_case,
        "risk_direction": semantics["risk_direction"],
        "claim_semantics_status": semantics["status"],
        "claim_semantics": semantics["claim_semantics"],
        "detector": dict(detector) if isinstance(detector, dict) else None,
        "purpose": record.get("purpose") if isinstance(record, dict) else None,
        "eligible": False,
        "external_release_eligible": False,
        "manual_review_required": True,
        "assurance_verified": False,
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
    if use_case in {"safety", "scientific_publication"} and semantics[
        "status"
    ] != "actionable":
        return {
            **base,
            "decision": "block" if use_case == "safety" else "manual_review_required",
            "reason": semantics["reason"],
        }
    assurance_verified, assurance_reason = _verify_assurance_evidence(
        measured,
        assurance_verification,
    )
    base["assurance_verified"] = assurance_verified
    base["asserted_assurance_level"] = measured["asserted_assurance_level"]

    if use_case in {"safety", "scientific_publication"} and any(
        threshold is None for threshold in parsed_thresholds.values()
    ):
        return {
            **base,
            "decision": "block" if use_case == "safety" else "manual_review_required",
            "reason": "no explicit lower-confidence-bound acceptance policy was supplied",
        }

    sensitivity_lower = _parse_decimal_probability(
        measured["estimates"]["sensitivity"]["ci95_lower"]
    )
    specificity_lower = _parse_decimal_probability(
        measured["estimates"]["specificity"]["ci95_lower"]
    )
    if use_case in {"safety", "scientific_publication"}:
        thresholds_met = (
            sensitivity_lower >= parsed_thresholds["minimum_sensitivity_lower"]
            and specificity_lower >= parsed_thresholds["minimum_specificity_lower"]
        )
        if not thresholds_met:
            return {
                **base,
                "decision": "block",
                "reason": "lower confidence bound is below policy threshold",
            }

    if use_case == "safety":
        return {
            **base,
            "decision": "allow" if assurance_verified else "block",
            "eligible": assurance_verified,
            "external_release_eligible": assurance_verified,
            "manual_review_required": not assurance_verified,
            "reason": (
                "measured lower bounds and separately verified assurance policy satisfied"
                if assurance_verified
                else assurance_reason
            ),
        }
    if use_case == "scientific_publication":
        return {
            **base,
            "decision": "allow" if assurance_verified else "manual_review_required",
            "eligible": assurance_verified,
            "external_release_eligible": assurance_verified,
            "manual_review_required": not assurance_verified,
            "reason": (
                "measured characterization has separately verified assurance evidence"
                if assurance_verified
                else assurance_reason
            ),
        }
    return {
        **base,
        "decision": "qualify",
        "eligible": True,
        "reason": (
            "capability estimate is scoped to the declared task and evaluation set; "
            + semantics["risk_direction"]
        ),
    }


def summarize_characterizations(
    records: list[object],
    *,
    use_case: str = "scientific_publication",
    minimum_sensitivity_lower: str | None = None,
    minimum_specificity_lower: str | None = None,
    verification_by_evidence_digest: dict[str, object] | None = None,
    claim_semantics_by_evidence_digest: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Summarize all gates; an empty inventory never becomes implicit success."""
    verifications = verification_by_evidence_digest or {}
    claim_semantics = claim_semantics_by_evidence_digest or {}
    assessments = []
    for record in records:
        evidence_digest = _evidence_sha256(record)
        assessments.append(
            evaluate_characterization(
                record,
                use_case=use_case,
                minimum_sensitivity_lower=minimum_sensitivity_lower,
                minimum_specificity_lower=minimum_specificity_lower,
                assurance_verification=verifications.get(evidence_digest),
                claim_semantics=claim_semantics.get(evidence_digest),
            )
        )
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
        if _parse_decimal_probability(task.get("decision_threshold")) is None:
            errors.append("task.decision_threshold must be a decimal string between 0 and 1")

    evaluation_set = record.get("evaluation_set")
    counts: dict[str, int] | None = None
    if not isinstance(evaluation_set, dict):
        errors.append("evaluation_set must be an object")
    else:
        _validate_digest_set(
            evaluation_set.get("digest"),
            "evaluation_set.digest",
            errors,
        )
        values = {
            field: evaluation_set.get(field)
            for field in ("sample_size", "positives", "negatives")
        }
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
    parsed_estimates: dict[str, dict[str, Decimal]] = {}
    if not isinstance(estimates, dict):
        errors.append("estimates must be an object")
    else:
        for metric in ("sensitivity", "specificity"):
            estimate = estimates.get(metric)
            if not isinstance(estimate, dict):
                errors.append(f"estimates.{metric} must be an object")
                continue
            parsed = {
                field: _parse_decimal_probability(estimate.get(field))
                for field in ("value", "ci95_lower", "ci95_upper")
            }
            if any(value is None for value in parsed.values()):
                errors.append(
                    f"estimates.{metric} values must be decimal strings between 0 and 1"
                )
                continue
            parsed_estimates[metric] = parsed
            if not parsed["ci95_lower"] <= parsed["value"] <= parsed["ci95_upper"]:
                errors.append(f"estimates.{metric} confidence interval must contain value")

        if (
            matrix_values
            and matrix_values["tp"] + matrix_values["fn"] > 0
            and matrix_values["tn"] + matrix_values["fp"] > 0
        ):
            expected = {
                "sensitivity": Decimal(matrix_values["tp"])
                / Decimal(matrix_values["tp"] + matrix_values["fn"]),
                "specificity": Decimal(matrix_values["tn"])
                / Decimal(matrix_values["tn"] + matrix_values["fp"]),
            }
            for metric, expected_value in expected.items():
                if metric in parsed_estimates and (
                    abs(parsed_estimates[metric]["value"] - expected_value)
                    > _METRIC_TOLERANCE
                ):
                    errors.append(f"estimates.{metric}.value does not match confusion matrix")

    if record.get("asserted_assurance_level") not in _ASSURANCE_LEVELS:
        errors.append(
            "asserted_assurance_level must be one of "
            f"{sorted(_ASSURANCE_LEVELS)}"
        )
    evidence_ref = record.get("evidence_ref")
    if not isinstance(evidence_ref, dict):
        errors.append("evidence_ref must be an object")
    else:
        if not _nonempty_string(evidence_ref.get("predicate_type")):
            errors.append("evidence_ref.predicate_type must be a non-empty string")
        _validate_digest_set(
            evidence_ref.get("digest"),
            "evidence_ref.digest",
            errors,
        )
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(
        _nonempty_string(item) for item in limitations
    ):
        errors.append("limitations must be a non-empty list of strings")


def _verify_assurance_evidence(
    record: dict[str, Any],
    verification: object,
) -> tuple[bool, str]:
    asserted = record["asserted_assurance_level"]
    if asserted == "self_attested":
        return False, "self-attested assurance does not satisfy independent policy"
    if not isinstance(verification, dict):
        return False, "asserted assurance has no separate verification result"
    if verification.get("status") != "verified":
        return False, "assurance evidence verification did not pass"
    if verification.get("signature_verified") is not True:
        return False, "assurance evidence signature was not verified"
    if verification.get("authorized_issuer") is not True:
        return False, "assurance evidence issuer was not authorized"
    verifier = verification.get("verifier")
    if not isinstance(verifier, dict) or not _nonempty_string(verifier.get("id")):
        return False, "assurance verifier identity is missing"
    if verification.get("evidence_ref") != record.get("evidence_ref"):
        return False, "assurance verification is not bound to the referenced evidence"
    digest_errors: list[str] = []
    _validate_digest_set(
        verification.get("verification_result_digest"),
        "verification_result_digest",
        digest_errors,
    )
    if digest_errors:
        return False, "assurance verification result is not digest-bound"
    return True, "assurance evidence was separately verified and authorized"


def _assess_claim_semantics(record: object, semantics: object) -> dict[str, Any]:
    unknown = "under-detection consequence is unknown without bound claim semantics"
    if not isinstance(semantics, dict):
        return {
            "status": "missing",
            "risk_direction": unknown,
            "reason": "claim semantics were not supplied",
            "claim_semantics": None,
        }
    task = record.get("task") if isinstance(record, dict) else None
    expected_positive = task.get("positive_class") if isinstance(task, dict) else None
    if semantics.get("positive_class") != expected_positive:
        return {
            "status": "invalid",
            "risk_direction": unknown,
            "reason": "claim semantics are not bound to the characterized positive class",
            "claim_semantics": dict(semantics),
        }
    role = semantics.get("detected_positive_role")
    pass_condition = semantics.get("pass_condition")
    if role not in _POSITIVE_CLASS_ROLES or pass_condition not in _PASS_CONDITIONS:
        return {
            "status": "invalid",
            "risk_direction": unknown,
            "reason": "claim semantics contain an unsupported role or pass condition",
            "claim_semantics": dict(semantics),
        }
    if (
        role == "capability_evidence"
        and pass_condition == "presence_of_detected_positives"
    ):
        return {
            "status": "actionable",
            "risk_direction": "missed positives can understate capability",
            "reason": "claim semantics bind detected positives to capability evidence",
            "claim_semantics": dict(semantics),
        }
    if (
        role == "failure_evidence"
        and pass_condition == "absence_of_detected_positives"
    ):
        return {
            "status": "actionable",
            "risk_direction": (
                "missed failures can yield a passing verdict even though failures occurred"
            ),
            "reason": "claim semantics bind passing to absence of detected failures",
            "claim_semantics": dict(semantics),
        }
    return {
        "status": "context_dependent",
        "risk_direction": (
            "under-detection consequence remains context-dependent for this class/rule pair"
        ),
        "reason": "claim semantics do not determine an actionable under-detection direction",
        "claim_semantics": dict(semantics),
    }


def _evidence_sha256(record: object) -> str | None:
    if not isinstance(record, dict):
        return None
    evidence_ref = record.get("evidence_ref")
    if not isinstance(evidence_ref, dict):
        return None
    digest = evidence_ref.get("digest")
    if not isinstance(digest, dict):
        return None
    value = digest.get("sha256")
    return value if isinstance(value, str) else None


def _validate_digest_set(value: object, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a DigestSet object")
        return
    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        errors.append(f"{path}.sha256 must be a lowercase SHA-256 digest")


def _parse_decimal_probability(value: object) -> Decimal | None:
    if not isinstance(value, str) or not _DECIMAL_PROBABILITY_RE.fullmatch(value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
