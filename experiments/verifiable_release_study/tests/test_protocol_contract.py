from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = STUDY_ROOT / "scripts" / "validate_protocol.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("study_validate_protocol", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_draft_contract_is_internally_valid() -> None:
    result = _load_validator().validate(registration_ready=False)
    assert result["valid"], result["errors"]
    assert result["case_count"] > 0
    assert result["target_invalid_case_count"] > 0
    assert result["registration_gate_count"] == 14
    assert result["registration_gate_status"] == "no_go"
    assert result["open_blocking_gate_count"] == 10
    assert result["external_reproduction_mandatory"] is True
    assert result["dummy_analysis_status"] == "implemented_validated_not_frozen"
    assert result["r0_human_review_template_valid"] is True
    assert result["r0_human_review_record_status"] == "template_unreviewed"
    assert result["r0_human_review_occurred"] is False
    assert result["r0_reviewer_identity_policy_status"] == (
        "template_not_authorized_not_frozen"
    )
    assert result["r0_reviewer_identity_policy_validation_valid"] is True
    assert result["r0_reviewer_identity_authentication_permitted"] is False


def test_registration_gate_fails_while_tbd_markers_exist() -> None:
    result = _load_validator().validate(registration_ready=True)
    assert not result["valid"]
    assert result["tbd_count"] > 0
    assert any("TBD" in error for error in result["errors"])
    assert any("incomplete blocking gates" in error for error in result["errors"])


def test_core_and_v2_json_schemas_are_valid_draft_2020_12() -> None:
    for relative in (
        "schemas/manifest.schema.json",
        "schemas/manifest-production-v0.2.schema.json",
        "schemas/verifier-result.schema.json",
        "schemas/github-production-verification-result.schema.json",
        "schemas/github-attestation-policy-v2.schema.json",
        "schemas/github-production-verification-result-v2.schema.json",
        "schemas/run-execution-policy.schema.json",
        "schemas/run-execution-policy-validation.schema.json",
        "schemas/r0-human-review-record.schema.json",
        "schemas/r0-review-packet-verification.schema.json",
        "schemas/r0-reviewer-identity-policy.schema.json",
        "schemas/r0-reviewer-identity-policy-validation.schema.json",
    ):
        schema = json.loads((STUDY_ROOT / relative).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_protocol_json_parser_rejects_duplicate_names_and_nonstandard_numbers() -> None:
    validator = _load_validator()
    with pytest.raises(ValueError, match="duplicate JSON object name"):
        validator.strict_json_loads('{"decision":"GO","decision":"NO-GO"}')
    with pytest.raises(ValueError, match="non-standard JSON numeric constant"):
        validator.strict_json_loads('{"value":NaN}')


def test_catalog_has_complete_profile_expectations() -> None:
    catalog = json.loads(
        (STUDY_ROOT / "protocol/ATTACK_CATALOG.json").read_text(encoding="utf-8")
    )
    assert {profile["id"] for profile in catalog["profiles"]} == {"P0", "P1", "P2", "P3"}
    for case in catalog["cases"]:
        assert set(case["profile_expectations"]) == {"P0", "P1", "P2", "P3"}
        assert case["target_decision"] in {"ACCEPT", "REJECT"}


def test_proposition_matrix_forbids_terminal_only_denominators_and_silent_omission() -> None:
    matrix = json.loads(
        (STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json").read_text(
            encoding="utf-8"
        )
    )
    denominator = matrix["denominator_contract"]
    assert denominator["terminal_only_denominator_allowed"] is False
    assert denominator["category_partition"] == [
        "ACCEPT",
        "REJECT",
        "ERROR",
        "MISSING_EXECUTION",
        "GENERATION_FAILURE",
    ]
    assert denominator["category_counts_must_sum_to_planned_denominator"] is True
    reporting = matrix["reporting_decision_contract"]
    assert reporting["hand_entered_result_numbers_allowed"] is False
    assert "cannot be silently omitted" in reporting["negative_or_incomplete_rule"]
    assert all(item["conclusion_eligibility"] for item in matrix["propositions"])


def test_reason_mismatch_falsifies_affected_propositions() -> None:
    matrix = json.loads(
        (STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json").read_text(
            encoding="utf-8"
        )
    )
    by_id = {item["id"]: item for item in matrix["propositions"]}
    for proposition_id in ("PR-002", "PR-007", "PR-010"):
        assert "reason" in by_id[proposition_id]["falsification_rule"].lower()
    assert "bars the complete" in by_id["PR-009"]["falsification_rule"]
