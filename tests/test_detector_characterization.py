"""Contract and fail-safe policy tests for automated detector evidence."""

from copy import deepcopy

import pytest

from core.detector_characterization import (
    SCHEMA_VERSION,
    evaluate_characterization,
    summarize_characterizations,
    unmeasured_characterization,
    validate_characterization,
)


def _measured_record(*, assurance_level: str = "third_party") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "measured",
        "detector": {
            "name": "example_safety_gate",
            "version": "1.2.3",
            "digest": {"sha256": "a" * 64},
        },
        "purpose": "safety",
        "task": {
            "positive_class": "unsafe output",
            "negative_class": "allowed output",
            "decision_threshold": "0.5",
            "scope": "held-out English prompts from benchmark v1",
        },
        "evaluation_set": {
            "digest": {"sha256": "b" * 64},
            "sample_size": 200,
            "positives": 100,
            "negatives": 100,
        },
        "confusion_matrix": {"tp": 92, "fp": 10, "tn": 90, "fn": 8},
        "estimates": {
            "sensitivity": {
                "value": "0.92",
                "ci95_lower": "0.85",
                "ci95_upper": "0.96",
            },
            "specificity": {
                "value": "0.90",
                "ci95_lower": "0.82",
                "ci95_upper": "0.94",
            },
        },
        "asserted_assurance_level": assurance_level,
        "evidence_ref": {
            "predicate_type": "https://example.org/DetectorCharacterization/v2",
            "digest": {"sha256": "c" * 64},
        },
        "limitations": ["The estimate is not portable beyond the declared scope."],
    }


def _verified_assurance(record: dict) -> dict:
    return {
        "status": "verified",
        "signature_verified": True,
        "authorized_issuer": True,
        "verifier": {"id": "https://example.org/independent-verifier/v1"},
        "evidence_ref": deepcopy(record["evidence_ref"]),
        "verification_result_digest": {"sha256": "d" * 64},
    }


def test_unmeasured_record_never_implies_perfect_performance(tmp_path):
    source = tmp_path / "detector.py"
    source.write_text("def detect(value): return bool(value)\n", encoding="utf-8")
    record = unmeasured_characterization(
        name="detector",
        version="source-digest",
        source_path=source,
        source_id="detector.py",
        purpose="scientific_publication",
        reason="No held-out characterization has been performed.",
    )

    assert validate_characterization(record) == {
        "valid": True,
        "status": "unmeasured",
        "errors": [],
    }
    assert record["detector"]["digest"]["sha256"]
    assert "estimates" not in record
    assessment = evaluate_characterization(record, use_case="scientific_publication")
    assert assessment["decision"] == "manual_review_required"
    assert assessment["external_release_eligible"] is False
    assert assessment["manual_review_required"] is True


def test_missing_or_unmeasured_safety_characterization_fails_closed(tmp_path):
    missing = evaluate_characterization(None, use_case="safety")
    assert missing["status"] == "invalid"
    assert missing["decision"] == "block"

    source = tmp_path / "safety.py"
    source.write_text("pass\n", encoding="utf-8")
    unmeasured = unmeasured_characterization(
        name="safety_gate",
        version="source-digest",
        source_path=source,
        purpose="safety",
        reason="Benchmark unavailable.",
    )
    assessment = evaluate_characterization(unmeasured, use_case="safety")
    assert assessment["decision"] == "block"
    assert assessment["eligible"] is False
    assert "false passing safety verdict" in assessment["risk_direction"]


def test_declared_third_party_assurance_alone_never_authorizes_release():
    record = _measured_record()
    assessment = evaluate_characterization(
        record,
        use_case="safety",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
    )
    assert assessment["decision"] == "block"
    assert assessment["assurance_verified"] is False
    assert assessment["eligible"] is False
    assert assessment["reason"] == "asserted assurance has no separate verification result"


def test_measured_detector_requires_thresholds_and_verified_assurance():
    record = _measured_record()
    accepted = evaluate_characterization(
        record,
        use_case="safety",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
        assurance_verification=_verified_assurance(record),
    )
    assert accepted["decision"] == "allow"
    assert accepted["eligible"] is True
    assert accepted["assurance_verified"] is True

    rejected = evaluate_characterization(
        record,
        use_case="safety",
        minimum_sensitivity_lower="0.90",
        minimum_specificity_lower="0.80",
        assurance_verification=_verified_assurance(record),
    )
    assert rejected["decision"] == "block"
    assert rejected["eligible"] is False


def test_mismatched_or_unauthorized_assurance_evidence_fails_closed():
    record = _measured_record()
    verification = _verified_assurance(record)
    verification["evidence_ref"]["digest"]["sha256"] = "e" * 64
    mismatched = evaluate_characterization(
        record,
        use_case="safety",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
        assurance_verification=verification,
    )
    assert mismatched["decision"] == "block"
    assert "not bound" in mismatched["reason"]

    verification = _verified_assurance(record)
    verification["authorized_issuer"] = False
    unauthorized = evaluate_characterization(
        record,
        use_case="safety",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
        assurance_verification=verification,
    )
    assert unauthorized["decision"] == "block"
    assert "not authorized" in unauthorized["reason"]


def test_self_attested_measurement_does_not_authorize_external_release():
    record = _measured_record(assurance_level="self_attested")
    assessment = evaluate_characterization(
        record,
        use_case="scientific_publication",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
        assurance_verification=_verified_assurance(record),
    )
    assert assessment["decision"] == "manual_review_required"
    assert assessment["external_release_eligible"] is False


def test_measurement_without_explicit_acceptance_threshold_is_not_auto_release():
    record = _measured_record()
    assessment = evaluate_characterization(
        record,
        use_case="scientific_publication",
        assurance_verification=_verified_assurance(record),
    )
    assert assessment["decision"] == "manual_review_required"
    assert assessment["external_release_eligible"] is False


def test_json_floats_are_rejected_for_policy_comparisons():
    record = _measured_record()
    record["estimates"]["sensitivity"]["value"] = 0.92
    validation = validate_characterization(record)
    assert validation["valid"] is False
    assert (
        "estimates.sensitivity values must be decimal strings between 0 and 1"
        in validation["errors"]
    )

    with pytest.raises(ValueError, match="decimal string"):
        evaluate_characterization(
            _measured_record(),
            use_case="safety",
            minimum_sensitivity_lower=0.80,
            minimum_specificity_lower="0.80",
        )


def test_v1_or_absent_measured_fields_are_rejected_not_defaulted():
    legacy = _measured_record()
    legacy["schema_version"] = "amy.detector-characterization.v1"
    validation = validate_characterization(legacy)
    assert validation["valid"] is False
    assert f"schema_version must be {SCHEMA_VERSION}" in validation["errors"]

    absent = _measured_record()
    del absent["asserted_assurance_level"]
    del absent["evidence_ref"]
    assessment = evaluate_characterization(absent, use_case="scientific_publication")
    assert assessment["status"] == "invalid"
    assert assessment["decision"] == "block"


def test_invalid_metrics_and_digest_sets_are_rejected():
    mismatched = _measured_record()
    mismatched["estimates"]["sensitivity"]["value"] = "0.99"
    validation = validate_characterization(mismatched)
    assert validation["valid"] is False
    assert "estimates.sensitivity.value does not match confusion matrix" in validation["errors"]

    bad_digest = deepcopy(_measured_record())
    bad_digest["detector"]["digest"]["sha256"] = "SHA256:not-a-digest"
    validation = validate_characterization(bad_digest)
    assert validation["valid"] is False
    assert "detector.digest.sha256 must be a lowercase SHA-256 digest" in validation["errors"]


def test_capability_and_safety_report_asymmetric_under_detection_risk():
    capability = evaluate_characterization(
        _measured_record(),
        use_case="capability_claim",
    )
    assert capability["decision"] == "qualify"
    assert "conservatively understate capability" in capability["risk_direction"]

    safety = evaluate_characterization(
        _measured_record(),
        use_case="safety",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
    )
    assert "false passing safety verdict" in safety["risk_direction"]


def test_summary_binds_verification_by_evidence_digest():
    record = _measured_record()
    evidence_sha256 = record["evidence_ref"]["digest"]["sha256"]
    summary = summarize_characterizations(
        [record],
        use_case="scientific_publication",
        minimum_sensitivity_lower="0.80",
        minimum_specificity_lower="0.80",
        verification_by_evidence_digest={
            evidence_sha256: _verified_assurance(record),
        },
    )
    assert summary["decision"] == "allow"
    assert summary["external_release_eligible"] is True
    assert summary["manual_review_required"] is False


def test_summary_requires_every_detector_to_satisfy_policy(tmp_path):
    source = tmp_path / "unknown.py"
    source.write_text("pass\n", encoding="utf-8")
    unmeasured = unmeasured_characterization(
        name="unknown_gate",
        version="source-digest",
        source_path=source,
        purpose="scientific_publication",
        reason="Not measured.",
    )
    summary = summarize_characterizations(
        [_measured_record(), unmeasured],
        use_case="scientific_publication",
    )
    assert summary["counts"] == {"measured": 1, "unmeasured": 1, "invalid": 0}
    assert summary["decision"] == "manual_review_required"
    assert summary["external_release_eligible"] is False
    assert summary["manual_review_required"] is True


def test_empty_inventory_is_not_implicit_success():
    summary = summarize_characterizations([], use_case="scientific_publication")
    assert summary["decision"] == "manual_review_required"
    assert summary["external_release_eligible"] is False
