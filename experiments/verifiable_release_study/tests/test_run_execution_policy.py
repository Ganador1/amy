from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_run_execution_policy.py"
POLICY_PATH = STUDY_ROOT / "protocol/RUN_EXECUTION_POLICY_DRAFT.json"
SCHEMA_PATH = STUDY_ROOT / "schemas/run-execution-policy.schema.json"


def _module():
    spec = importlib.util.spec_from_file_location("run_execution_policy_validator", VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _counterfactual(tmp_path: Path, monkeypatch, value: dict) -> dict:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    module = _module()
    monkeypatch.setattr(module, "POLICY_PATH", path)
    return module.validate()


def test_current_policy_is_schema_valid_but_no_go() -> None:
    policy = _load(POLICY_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(policy)) == []
    result = _module().validate()
    assert result["valid"] is True
    assert result["decision"] == "NO-GO"
    assert result["freeze_permitted"] is False
    assert result["pending_compatibility_row_count"] == 54
    assert result["dummy_analysis_status"] == "implemented_validated_not_frozen"
    assert result["dummy_analysis_valid"] is True
    assert result["dummy_analysis_planned_row_count"] == 1480
    summary = _load(STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json")
    assert summary["attack_catalog_sha256"] == hashlib.sha256(
        (STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json").read_bytes()
    ).hexdigest()
    assert summary["compatibility_matrix_sha256"] == hashlib.sha256(
        (STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json").read_bytes()
    ).hexdigest()
    assert summary["oracle_sha256"] == hashlib.sha256(
        (STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json").read_bytes()
    ).hexdigest()
    assert summary["manuscript_claims_authorized"] is False
    assert summary["all_required_propositions_evaluable_and_supported"] is False
    assert summary["authorization_blockers"]
    target_invalid = summary["target_invalid_breakdown"]
    assert target_invalid["planned_row_count"] == 1432
    assert target_invalid["subtotals_reconcile"] is True
    assert target_invalid["pooled_primary_result_permitted"] is False
    assert result["external_reproduction_mandatory"] is True
    assert result["read_scope"]["confirmatory_artifacts_read"] is False
    assert result["runner_contract_hashes_match"] is True
    assert result["runner_contract_test_record_valid"] is True
    assert result["runner_contract_passed_test_count"] == 61
    assert result["runner_contract_open_control_count"] == 11
    assert result["runner_confirmatory_execution_permitted"] is False
    assert result["runner_rg006_complete"] is False


def test_outcome_dependent_case_retry_is_rejected(tmp_path: Path, monkeypatch) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["attempt_policy"]["case_level_retry_allowed"] = True
    policy["attempt_policy"]["max_attempts_per_case_within_environment"] = 2
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("case-level retries" in error or "case attempt cap" in error for error in result["errors"])


def test_decision_field_cannot_become_infrastructure_signal(tmp_path: Path, monkeypatch) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    classifier = policy["outcome_blind_infrastructure_classification"]
    classifier["forbidden_fields"].remove("decision")
    classifier["allowed_predecode_signal_fields"].append("decision")
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("does not forbid decision" in error for error in result["errors"])


def test_midrun_runner_loss_cannot_become_retry_eligible(tmp_path: Path, monkeypatch) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    predicate = next(
        item
        for item in policy["eligible_infrastructure_failures"]
        if item["id"] == "INFRA-EXTERNAL-RUNNER-LOSS"
    )
    predicate["required_common_guards"] = [
        guard
        for guard in predicate["required_common_guards"]
        if guard != "SCIENTIFIC_INTENT_EVENT_COUNT_ZERO"
    ]
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("exact typed runtime registry" in error for error in result["errors"])


def test_classifier_process_projection_is_exact_and_not_forbidden() -> None:
    policy = _load(POLICY_PATH)
    classifier = policy["outcome_blind_infrastructure_classification"]
    assert "process" in classifier["classifier_projection_top_level_fields"]
    assert "attempt_record_jcs_sha256" in classifier[
        "classifier_projection_top_level_fields"
    ]
    assert "process" not in classifier["forbidden_fields"]
    assert classifier["allowed_process_metadata_fields"] == [
        "spawned",
        "pid",
        "exit_code",
        "exit_signal",
        "timeout_triggered",
        "output_limit_exceeded",
        "sigterm_sent",
        "sigkill_sent",
        "reaped",
    ]


def test_environment_timeout_covers_worst_case_candidate_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["timeouts_seconds"]["whole_environment_attempt"] = 200000
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("candidate_unit_count" in error for error in result["errors"])


def test_bound_proposition_hash_substitution_is_rejected(tmp_path: Path, monkeypatch) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["bound_design"]["proposition_matrix_sha256"] = "0" * 64
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert result["bound_artifact_hashes_match"] is False


def test_fake_frozen_status_cannot_override_pending_rows_or_dummy_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["status"] = "frozen"
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert result["freeze_permitted"] is False
    assert result["decision"] == "NO-GO"


def test_dummy_breakdown_and_authorization_blockers_are_recomputed(
    tmp_path: Path, monkeypatch
) -> None:
    summary = copy.deepcopy(
        _load(STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json")
    )
    summary["target_invalid_breakdown"]["planned_row_count"] = 1431
    summary["authorization_blockers"] = []
    path = tmp_path / "dummy-summary.json"
    path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    module = _module()
    monkeypatch.setattr(module, "DUMMY_SUMMARY_PATH", path)
    result = module.validate()
    assert result["valid"] is False
    assert result["dummy_analysis_valid"] is False
    assert any("authorization blockers differ" in error for error in result["errors"])
    assert any("target-invalid breakdown" in error for error in result["errors"])


def test_runner_source_hash_substitution_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    binding = next(
        item
        for item in policy["runner_contract"]["source_bindings"]
        if item["role"] == "confirmatory_runner"
    )
    binding["sha256"] = "0" * 64
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert result["runner_contract_hashes_match"] is False


def test_scientific_intent_before_spawn_cannot_be_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["attempt_policy"][
        "scientific_intent_must_be_durably_persisted_before_child_spawn"
    ] = False
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("scientific_intent" in error for error in result["errors"])


def test_process_exit_signal_cannot_enter_classifier_projection(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["outcome_blind_infrastructure_classification"][
        "allowed_predecode_signal_fields"
    ].append("process_exit_signal")
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("predecode signal projection" in error for error in result["errors"])


def test_attempt_two_must_bind_persisted_attempt_one_classification(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["attempt_policy"][
        "attempt_two_requires_persisted_attempt_one_classification_sha256"
    ] = False
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False


def test_no_official_attempt_cannot_drop_planned_rows(
    tmp_path: Path, monkeypatch
) -> None:
    policy = copy.deepcopy(_load(POLICY_PATH))
    policy["attempt_policy"]["no_official_attempt_row_disposition"] = "DROP_ROWS"
    result = _counterfactual(tmp_path, monkeypatch, policy)
    assert result["valid"] is False
    assert any("MISSING_EXECUTION" in error for error in result["errors"])
