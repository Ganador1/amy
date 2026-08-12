#!/usr/bin/env python3
"""Validate the draft run/retry policy without reading confirmatory evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = STUDY_ROOT / "protocol/RUN_EXECUTION_POLICY_DRAFT.json"
POLICY_SCHEMA_PATH = STUDY_ROOT / "schemas/run-execution-policy.schema.json"
VALIDATION_SCHEMA_PATH = STUDY_ROOT / "schemas/run-execution-policy-validation.schema.json"
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
BASES_PATH = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
MATRIX_PATH = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
ORACLE_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
PROPOSITIONS_PATH = STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json"
CLAIMS_PATH = STUDY_ROOT / "evidence/CLAIM_EVIDENCE_MATRIX.csv"
DUMMY_LEDGER_PATH = STUDY_ROOT / "dummy_analysis/DUMMY_OBSERVATION_LEDGER.json"
DUMMY_SUMMARY_PATH = STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json"
DUMMY_ANALYZER_PATH = STUDY_ROOT / "scripts/analyze_observation_ledger.py"
DUMMY_INPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/observation-ledger.schema.json"
DUMMY_OUTPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/analysis-summary.schema.json"
RUNNER_TEST_RECORD_PATH = (
    STUDY_ROOT / "development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json"
)
RUNNER_TEST_RECORD_SCHEMA_PATH = STUDY_ROOT / "schemas/rg006-contract-test-record-v3.schema.json"

RUNNER_BINDING_SOURCES = {
    "confirmatory_runner": "amy_verifier/confirmatory_runner.py",
    "dependency_lock": "uv.lock",
    "environment_attempt_schema": "schemas/environment-attempt-record.schema.json",
    "infrastructure_classification_schema": "schemas/infrastructure-classification.schema.json",
    "official_attempt_selection_schema": "schemas/official-attempt-selection.schema.json",
    "process_isolation_schema": "schemas/process-isolation-record.schema.json",
    "project_manifest": "pyproject.toml",
    "rg006_test_record_schema": "schemas/rg006-contract-test-record-v3.schema.json",
    "rg006_test_runner": "scripts/run_rg006_contract_tests.py",
    "run_policy_schema": "schemas/run-execution-policy.schema.json",
    "run_policy_tests": "tests/test_run_execution_policy.py",
    "run_policy_validation_schema": "schemas/run-execution-policy-validation.schema.json",
    "run_policy_validator": "scripts/validate_run_execution_policy.py",
    "runner_contract": "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
    "runner_contract_tests": "tests/test_confirmatory_runner_contract.py",
    "scientific_intent_event_schema": "schemas/scientific-intent-event.schema.json",
}
EXPECTED_RUNNER_OPEN_CONTROLS = [
    "DURABLE_SCIENTIFIC_INTENT_LOG",
    "CAPABILITY_SEPARATED_OUTCOME_VAULT",
    "FULL_PROCESS_TREE_CONTAINMENT",
    "OS_ENFORCED_OFFLINE_BOUNDARY",
    "CRASH_AND_STORAGE_FAULT_INJECTION",
    "BASE_AWARE_CASE_GENERATOR",
    "ALL_PROFILE_CHILD_ADAPTERS",
    "CAMPAIGN_SEAL_TO_LEDGER_LINK",
    "EXTERNAL_SELECTION_AUTHENTICATION",
    "QUALIFIED_INDEPENDENT_HUMAN_REVIEW",
    "R0_FREEZE_AND_REGISTRATION",
]

EXPECTED_CLASSIFIER_TOP_LEVEL_FIELDS = [
    "schema_version",
    "classification",
    "attempt_id",
    "environment_id",
    "attempt_number",
    "attempt_state",
    "attempt_record_jcs_sha256",
    "clock",
    "attempt_two_authorization",
    "process",
    "signals",
    "outcome_guard",
]
EXPECTED_PROCESS_METADATA_FIELDS = [
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
EXPECTED_PREDECODE_SIGNAL_FIELDS = [
    "provider_job_id",
    "provider_job_state",
    "external_cancellation_actor",
    "host_heartbeat_state",
    "image_pull_status",
    "input_acquisition_status",
    "input_lock_completed",
    "preflight_storage_probe",
    "run_started_marker",
    "case_execution_started",
    "run_completed_marker",
    "terminal_scientific_event_count",
    "scientific_intent_event_count",
    "outcomes_exposed_to_selection_process",
    "result_bytes_decoded_before_selection",
    "oracle_join_performed_before_selection",
    "operator_cancellation_requested",
    "input_hash_mismatch",
]
EXPECTED_FORBIDDEN_CLASSIFIER_FIELDS = [
    "raw_artifacts",
    "raw_result_bytes",
    "result_stdout",
    "result_stderr",
    "decision",
    "primary_reason",
    "secondary_reasons",
    "target_decision",
    "expected_decision",
    "expected_primary_reason",
    "oracle_row",
    "profile_totals",
    "manuscript_text",
]

COMMON_RETRY_GUARDS = [
    "ATTEMPT_STATE_PRESTART_ABORTED",
    "RUN_STARTED_FALSE",
    "CASE_EXECUTION_STARTED_FALSE",
    "SCIENTIFIC_INTENT_EVENT_COUNT_ZERO",
    "TERMINAL_SCIENTIFIC_EVENT_COUNT_ZERO",
    "OUTCOME_GUARD_CLEAN",
]
COMMON_RETRY_DISQUALIFIERS = [
    "OUTCOMES_EXPOSED",
    "RESULT_BYTES_DECODED",
    "ORACLE_JOINED",
    "HUMAN_OUTCOME_READ",
    "DECODE_CAPABILITY_RELEASED",
]
IMPLEMENTED_BY = "amy_verifier.confirmatory_runner.classify_infrastructure_before_decode"
EXPECTED_INFRA_PREDICATES = [
    {
        "id": "INFRA-JOB-NOT-STARTED",
        "implementation_predicate_id": "INFRA-JOB-NOT-STARTED",
        "implemented_by": IMPLEMENTED_BY,
        "eligible_for_complete_environment_rerun": True,
        "classification_deadline": "before_outcome_join_and_decision_read",
        "required_common_guards": COMMON_RETRY_GUARDS,
        "predicate_requirements": [
            "PROVIDER_JOB_STATE_NOT_SCHEDULED_OR_RUNNER_UNAVAILABLE"
        ],
        "disqualifiers": COMMON_RETRY_DISQUALIFIERS,
        "required_evidence_fields": [
            "attempt_state",
            "provider_job_id",
            "provider_job_state",
            "run_started_marker",
            "case_execution_started",
            "scientific_intent_event_count",
            "terminal_scientific_event_count",
            "outcomes_exposed_to_selection_process",
            "outcome_guard",
        ],
    },
    {
        "id": "INFRA-EXTERNAL-RUNNER-LOSS",
        "implementation_predicate_id": "INFRA-EXTERNAL-RUNNER-LOSS",
        "implemented_by": IMPLEMENTED_BY,
        "eligible_for_complete_environment_rerun": True,
        "classification_deadline": "before_outcome_join_and_decision_read",
        "required_common_guards": COMMON_RETRY_GUARDS,
        "predicate_requirements": [
            "PROVIDER_JOB_STATE_RUNNER_LOST_OR_PROVIDER_CANCELLED",
            "EXTERNAL_CANCELLATION_ACTOR_PROVIDER",
            "HOST_HEARTBEAT_LOST",
            "OPERATOR_CANCELLATION_FALSE",
        ],
        "disqualifiers": COMMON_RETRY_DISQUALIFIERS,
        "required_evidence_fields": [
            "attempt_state",
            "provider_job_id",
            "provider_job_state",
            "external_cancellation_actor",
            "host_heartbeat_state",
            "operator_cancellation_requested",
            "run_started_marker",
            "case_execution_started",
            "scientific_intent_event_count",
            "terminal_scientific_event_count",
            "outcomes_exposed_to_selection_process",
            "outcome_guard",
        ],
    },
    {
        "id": "INFRA-PRELOCK-ACQUISITION-FAILURE",
        "implementation_predicate_id": "INFRA-PRELOCK-ACQUISITION-FAILURE",
        "implemented_by": IMPLEMENTED_BY,
        "eligible_for_complete_environment_rerun": True,
        "classification_deadline": "before_outcome_join_and_decision_read",
        "required_common_guards": COMMON_RETRY_GUARDS,
        "predicate_requirements": [
            "INPUT_ACQUISITION_FAILED",
            "INPUT_LOCK_INCOMPLETE",
            "INPUT_HASH_MISMATCH_FALSE",
        ],
        "disqualifiers": COMMON_RETRY_DISQUALIFIERS,
        "required_evidence_fields": [
            "attempt_state",
            "input_acquisition_status",
            "input_lock_completed",
            "input_hash_mismatch",
            "run_started_marker",
            "case_execution_started",
            "scientific_intent_event_count",
            "terminal_scientific_event_count",
            "outcomes_exposed_to_selection_process",
            "outcome_guard",
        ],
    },
    {
        "id": "INFRA-PREFLIGHT-STORAGE-FAILURE",
        "implementation_predicate_id": "INFRA-PREFLIGHT-STORAGE-FAILURE",
        "implemented_by": IMPLEMENTED_BY,
        "eligible_for_complete_environment_rerun": True,
        "classification_deadline": "before_outcome_join_and_decision_read",
        "required_common_guards": COMMON_RETRY_GUARDS,
        "predicate_requirements": ["PREFLIGHT_STORAGE_PROBE_FAILED"],
        "disqualifiers": COMMON_RETRY_DISQUALIFIERS,
        "required_evidence_fields": [
            "attempt_state",
            "preflight_storage_probe",
            "run_started_marker",
            "case_execution_started",
            "scientific_intent_event_count",
            "terminal_scientific_event_count",
            "outcomes_exposed_to_selection_process",
            "outcome_guard",
        ],
    },
]

BOUND_PATHS = {
    "attack_catalog_sha256": CATALOG_PATH,
    "selected_compatibility_matrix_sha256": MATRIX_PATH,
    "selected_oracle_sha256": ORACLE_PATH,
    "proposition_matrix_sha256": PROPOSITIONS_PATH,
}
EXPECTED_INFRA_IDS = {item["id"] for item in EXPECTED_INFRA_PREDICATES}
EXPECTED_NON_RETRYABLE_IDS = {
    "CASE_TIMEOUT",
    "VERIFIER_CRASH",
    "RESOURCE_EXHAUSTION",
    "WHOLE_ENVIRONMENT_TIMEOUT",
    "INPUT_HASH_MISMATCH",
    "POLICY_OR_SCHEMA_HASH_MISMATCH",
    "UNEXPECTED_OR_UNFAVORABLE_OUTCOME",
    "ORACLE_OR_ANALYSIS_DISAGREEMENT",
    "DISK_OR_QUOTA_FAILURE",
    "NETWORK_OR_DEPENDENCY_FAILURE",
    "MANUAL_CANCELLATION",
    "HOST_SLEEP",
    "RUNNER_IMPLEMENTATION_DEFECT",
}
EXPECTED_DEVIATION_IDS = {
    "DEV-R0-CONTRACT-CHANGE",
    "DEV-POST-START-CODE-CHANGE",
    "DEV-REGISTERED-INPUT-DRIFT",
    "DEV-ENVIRONMENT-IMAGE-DRIFT",
    "DEV-PROVENANCE-LOG-LOSS",
    "DEV-EXTERNAL-REPRO-INPUT-DRIFT",
    "DEV-RESULT-DISAGREEMENT",
    "DEV-PAPER-ONLY-CORRECTION",
}


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError(f"{path.name} exceeds {max_bytes} bytes")
    return json.loads(raw, object_pairs_hook=_strict_object), raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _schema_errors(schema: Any, instance: Any) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"schema /{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(
            validator.iter_errors(instance),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    ]


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _walk_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _walk_strings(item)]
    return []


def _claim_c011() -> dict[str, str]:
    with CLAIMS_PATH.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["claim_id"] == "C011"]
    if len(rows) != 1:
        raise ValueError("claim ledger must contain exactly one C011 row")
    return rows[0]


def _validate_runner_contract(
    policy: dict[str, Any], policy_raw: bytes
) -> tuple[dict[str, Any], list[str]]:
    local_errors: list[str] = []
    contract = policy.get("runner_contract") or {}
    expected_status = "synthetic_contract_tests_passed_production_controls_open"
    status = contract.get("status")
    reported_status = status if status == expected_status else "missing_or_invalid"
    if status != expected_status:
        local_errors.append("runner-contract status differs")
    if contract.get("implementation_symbol") != "amy_verifier.confirmatory_runner":
        local_errors.append("runner-contract implementation symbol differs")
    if (
        contract.get("classifier_projection_symbol")
        != "amy_verifier.confirmatory_runner.build_classifier_view"
    ):
        local_errors.append("runner-contract classifier projection symbol differs")
    record_contract = contract.get("contract_test_record") or {}
    if (
        record_contract.get("path")
        != "development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json"
        or record_contract.get("must_match_current_source_inventory") is not True
        or record_contract.get("required_decision") != "NO-GO"
    ):
        local_errors.append("runner-contract test-record contract differs")

    bindings = contract.get("source_bindings") or []
    expected_paths = set(RUNNER_BINDING_SOURCES.values())
    expected_roles_by_path = {
        relative: role for role, relative in RUNNER_BINDING_SOURCES.items()
    }
    observed_paths = [
        item.get("path") for item in bindings if isinstance(item, dict)
    ]
    if contract.get("source_binding_count") != len(expected_paths):
        local_errors.append("source-binding count differs from the closed registry")
    if observed_paths != sorted(expected_paths, key=lambda value: value.encode("utf-8")):
        local_errors.append("source bindings are missing, extra, duplicated, or out of order")
    roles: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            local_errors.append("source binding is not an object")
            continue
        role = binding.get("role")
        relative = binding.get("path")
        if not isinstance(role, str) or role in roles:
            local_errors.append("source-binding role is missing or duplicated")
        else:
            roles.add(role)
        if not isinstance(relative, str) or relative not in expected_paths:
            local_errors.append(f"unexpected bound source path: {relative}")
            continue
        if role != expected_roles_by_path[relative]:
            local_errors.append(f"bound source role differs: {relative}")
        path = STUDY_ROOT / relative
        if path.is_symlink() or not path.is_file():
            local_errors.append(f"bound source is not a regular non-symlink file: {relative}")
            continue
        if binding.get("sha256") != _sha(path.read_bytes()):
            local_errors.append(f"bound source hash differs: {relative}")
    runner_hashes_match = not local_errors

    receipt_valid = False
    receipt_sha256: str | None = None
    passed_test_count = 0
    open_control_count = 0
    try:
        if RUNNER_TEST_RECORD_PATH.is_symlink() or not RUNNER_TEST_RECORD_PATH.is_file():
            raise ValueError("test record is not a regular non-symlink file")
        if (
            RUNNER_TEST_RECORD_SCHEMA_PATH.is_symlink()
            or not RUNNER_TEST_RECORD_SCHEMA_PATH.is_file()
        ):
            raise ValueError("test-record schema is not a regular non-symlink file")
        receipt, receipt_raw = _load(RUNNER_TEST_RECORD_PATH, max_bytes=2 * 1024 * 1024)
        receipt_schema, _ = _load(RUNNER_TEST_RECORD_SCHEMA_PATH)
        Draft202012Validator.check_schema(receipt_schema)
        receipt_schema_errors = _schema_errors(receipt_schema, receipt)
        local_errors.extend(
            f"test record {message}" for message in receipt_schema_errors
        )
        receipt_sha256 = _sha(receipt_raw)

        inventory = receipt.get("source_inventory") or []
        expected_inventory_paths = sorted(
            expected_paths | {"protocol/RUN_EXECUTION_POLICY_DRAFT.json"},
            key=lambda value: value.encode("utf-8"),
        )
        inventory_paths = [
            item.get("path") for item in inventory if isinstance(item, dict)
        ]
        if inventory_paths != expected_inventory_paths:
            local_errors.append(
                "test-record source inventory is missing, extra, duplicated, or out of order"
            )
        for item in inventory:
            if not isinstance(item, dict):
                local_errors.append("test-record source inventory item is not an object")
                continue
            relative = item.get("path")
            if relative not in expected_inventory_paths:
                continue
            if relative == "protocol/RUN_EXECUTION_POLICY_DRAFT.json":
                expected_raw = policy_raw
            else:
                source_path = STUDY_ROOT / relative
                if source_path.is_symlink() or not source_path.is_file():
                    local_errors.append(
                        f"test-record source is not a regular non-symlink file: {relative}"
                    )
                    continue
                expected_raw = source_path.read_bytes()
            if item.get("bytes") != len(expected_raw):
                local_errors.append(f"test-record source byte count differs: {relative}")
            if item.get("sha256") != _sha(expected_raw):
                local_errors.append(f"test-record source hash differs: {relative}")
        inventory_sha256 = _sha(rfc8785.dumps(inventory))
        if (
            receipt.get("source_inventory_pre_sha256") != inventory_sha256
            or receipt.get("source_inventory_post_sha256") != inventory_sha256
            or receipt.get("source_inventory_unchanged_during_execution") is not True
        ):
            local_errors.append(
                "test-record source inventory was not identical before and after execution"
            )

        execution = receipt.get("execution") or {}
        stdout = execution.get("stdout")
        stderr = execution.get("stderr")
        if not isinstance(stdout, str) or execution.get("stdout_sha256") != _sha(
            stdout.encode("utf-8") if isinstance(stdout, str) else b""
        ):
            local_errors.append("test-record stdout hash differs")
        if not isinstance(stderr, str) or execution.get("stderr_sha256") != _sha(
            stderr.encode("utf-8") if isinstance(stderr, str) else b""
        ):
            local_errors.append("test-record stderr hash differs")
        raw_passed_count = execution.get("passed_test_count")
        passed_test_count = raw_passed_count if isinstance(raw_passed_count, int) else 0
        required_passed_count = record_contract.get("required_passed_test_count")
        if execution.get("exit_code") != 0 or passed_test_count != required_passed_count:
            local_errors.append("test record does not report the exact required passing suite")
        if receipt.get("decision") != "NO-GO":
            local_errors.append("test record must retain decision NO-GO")
        if receipt.get("rg006_complete") is not False:
            local_errors.append("test record must not claim RG-006 complete")
        if receipt.get("manuscript_claims_authorized") is not False:
            local_errors.append("test record must not authorize manuscript claims")
        coverage = receipt.get("declared_coverage") or {}
        if coverage.get("typed_run_policy_bindings_verified") is not True:
            local_errors.append("test record lacks verified typed run-policy bindings")
        if coverage.get("runner_contract_bound_source_count") != len(expected_paths):
            local_errors.append("test record binding count differs")
        for field in (
            "later_attempt_campaign_seal_tested",
            "attempt_process_consistency_tested",
            "inherited_capture_pipe_deadline_tested",
            "exact_record_hash_recomputation_tested",
            "source_inventory_toctou_rejection_tested",
        ):
            if coverage.get(field) is not True:
                local_errors.append(f"test record lacks declared coverage: {field}")
        expected_coverage = {
            "storage_errno_fault_cell_count": 12,
            "storage_eintr_transient_cell_count": 4,
            "storage_eintr_persistent_cell_count": 3,
            "storage_process_crash_cell_count": 3,
            "same_uid_entry_substitution_tested": True,
            "atomic_noreplace_rename_tested": True,
            "fault_injection_scope": (
                "atomic_jcs_publication_only_not_all_runner_persistence_boundaries"
            ),
            "intent_event_schema_and_process_binding_tested": True,
            "intent_hash_chain_tested": True,
            "intent_ambiguous_rejection_cell_count": 3,
            "intent_advisory_lock_tested": True,
            "intent_popen_failure_retention_tested": True,
            "intent_publication_failure_prevents_spawn_tested": True,
            "intent_pre_spawn_process_crash_cell_count": 1,
            "intent_log_scope": (
                "contract_test_top_level_spawn_only_no_authenticated_checkpoint_"
                "recovery_or_classifier_derivation"
            ),
        }
        for field, expected in expected_coverage.items():
            if coverage.get(field) != expected:
                local_errors.append(f"test record coverage differs: {field}")
        control_statuses = receipt.get("control_statuses") or {}
        derived_open_controls = [
            control
            for control in EXPECTED_RUNNER_OPEN_CONTROLS
            if (control_statuses.get(control) or {}).get("status") != "CLOSED"
        ]
        if set(control_statuses) != set(EXPECTED_RUNNER_OPEN_CONTROLS):
            local_errors.append("test-record control-status registry differs")
        if (
            (control_statuses.get("CRASH_AND_STORAGE_FAULT_INJECTION") or {}).get(
                "status"
            )
            != "PARTIAL"
        ):
            local_errors.append("storage fault control must remain PARTIAL")
        if (
            (control_statuses.get("DURABLE_SCIENTIFIC_INTENT_LOG") or {}).get(
                "status"
            )
            != "PARTIAL"
        ):
            local_errors.append("scientific-intent control must remain PARTIAL")
        open_controls = receipt.get("open_controls") or []
        open_control_count = len(open_controls) if isinstance(open_controls, list) else 0
        if open_controls != derived_open_controls:
            local_errors.append("test-record open controls differ from control statuses")
        if open_controls != EXPECTED_RUNNER_OPEN_CONTROLS:
            local_errors.append("test-record open-control registry differs")
        receipt_valid = not local_errors
    except Exception as exc:
        local_errors.append(
            f"test-record validation failed: {type(exc).__name__}: {exc}"
        )

    boundaries = contract.get("production_boundaries") or {}
    if any(value is not False for value in boundaries.values()):
        local_errors.append("production boundaries cannot be claimed by synthetic tests")
    confirmatory_execution_permitted = (
        contract.get("confirmatory_execution_permitted") is True
    )
    rg006_complete = contract.get("rg006_complete") is True
    return (
        {
            "status": reported_status,
            "hashes_match": runner_hashes_match,
            "test_record_valid": receipt_valid,
            "test_record_sha256": receipt_sha256,
            "passed_test_count": passed_test_count,
            "open_control_count": open_control_count,
            "confirmatory_execution_permitted": confirmatory_execution_permitted,
            "rg006_complete": rg006_complete,
        },
        local_errors,
    )


def validate() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    policy, policy_raw = _load(POLICY_PATH)
    schema, schema_raw = _load(POLICY_SCHEMA_PATH)
    validation_schema, _ = _load(VALIDATION_SCHEMA_PATH)
    catalog, _ = _load(CATALOG_PATH)
    bases, _ = _load(BASES_PATH)
    matrix, _ = _load(MATRIX_PATH)
    oracle, _ = _load(ORACLE_PATH)
    propositions, _ = _load(PROPOSITIONS_PATH)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(validation_schema)
    errors.extend(_schema_errors(schema, policy))
    if any("TBD-BEFORE-REGISTRATION" in text for text in _walk_strings(policy)):
        errors.append("run policy contains a forbidden TBD marker")

    runner, runner_errors = _validate_runner_contract(policy, policy_raw)
    errors.extend(f"runner contract: {message}" for message in runner_errors)

    bound = policy.get("bound_design") or {}
    bound_matches = True
    for key, path in BOUND_PATHS.items():
        observed = _sha(path.read_bytes())
        if bound.get(key) != observed:
            errors.append(f"bound hash mismatch: {key}")
            bound_matches = False

    case_count = len(catalog.get("cases") or [])
    base_count = len(bases.get("bases") or [])
    profile_count = len(catalog.get("profiles") or [])
    proposition_count = len(propositions.get("propositions") or [])
    pending_count = sum(
        row.get("compatibility") == "PENDING" for row in matrix.get("rows") or []
    )
    oracle_rows = oracle.get("rows") or oracle.get("expectations") or []
    if case_count != bound.get("selected_profile_case_count"):
        errors.append("selected case count differs from bound design")
    if base_count != bound.get("base_count"):
        errors.append("base count differs from bound design")
    if profile_count != len(bound.get("profile_ids") or []):
        errors.append("profile count differs from bound design")
    if proposition_count != bound.get("proposition_count"):
        errors.append("proposition count differs from bound design")
    candidate_unit_count = len(matrix.get("rows") or [])
    if candidate_unit_count != bound.get("candidate_unit_count"):
        errors.append("candidate unit count differs from bound design")
    if len(oracle_rows) != case_count * profile_count:
        errors.append("oracle row count is not case_count × profile_count")

    timeouts = policy.get("timeouts_seconds") or {}
    profile_timeouts = timeouts.get("profile_execution") or {}
    inner = timeouts.get("production_sigstore_inner_command")
    if not isinstance(inner, int) or any(
        profile_timeouts.get(profile, 0) <= inner for profile in ("P2", "P3")
    ):
        errors.append("P2/P3 outer timeouts must exceed the Sigstore inner timeout")
    if timeouts.get("case_unit") != 900:
        errors.append("case-unit timeout must be exactly 900 seconds")
    if timeouts.get("whole_environment_attempt") != 259200:
        errors.append("whole-environment timeout must be exactly 259200 seconds")
    if timeouts.get("whole_environment_attempt", 0) < candidate_unit_count * timeouts.get(
        "case_unit", 0
    ):
        errors.append("whole-environment timeout is below candidate_unit_count × case timeout")
    if timeouts.get("elapsed_clock") != "continuous_monotonic_including_suspend":
        errors.append("elapsed clock must include host suspend time")

    attempts = policy.get("attempt_policy") or {}
    if attempts.get("max_attempts_per_environment") != 2:
        errors.append("environment attempt cap must be exactly two")
    if attempts.get("max_attempts_per_case_within_environment") != 1:
        errors.append("case attempt cap must be exactly one")
    if attempts.get("case_level_retry_allowed") is not False:
        errors.append("case-level retries must be forbidden")
    for field in (
        "eligible_retry_requires_zero_scientific_intent_events",
        "eligible_retry_requires_zero_terminal_scientific_events",
        "scientific_intent_must_be_durably_persisted_before_child_spawn",
        "eligible_retry_requires_outcomes_exposed_false",
        "eligible_retry_requires_exactly_one_complete_rerun",
        "attempt_two_requires_persisted_attempt_one_classification_sha256",
        "campaign_selection_covers_all_primary_environments",
        "selection_sealed_before_result_decoding",
    ):
        if attempts.get(field) is not True:
            errors.append(f"attempt-selection fail-closed flag is not true: {field}")
    for field in (
        "invalid_classification_retry_allowed",
        "per_environment_decode_before_campaign_seal_allowed",
    ):
        if attempts.get(field) is not False:
            errors.append(f"attempt-selection fail-closed flag is not false: {field}")
    if (
        attempts.get("no_official_attempt_row_disposition")
        != "ALL_PLANNED_ROWS_MISSING_EXECUTION"
    ):
        errors.append("no-official-attempt rows are not mapped to MISSING_EXECUTION")

    infra = policy.get("eligible_infrastructure_failures") or []
    infra_ids = {item.get("id") for item in infra if isinstance(item, dict)}
    if infra_ids != EXPECTED_INFRA_IDS:
        errors.append("eligible infrastructure predicate registry differs from expected set")
    if infra != EXPECTED_INFRA_PREDICATES:
        errors.append(
            "eligible infrastructure predicates differ from the exact typed runtime registry"
        )
    non_retryable = policy.get("non_retryable_conditions") or []
    non_retryable_ids = {
        item.get("id") for item in non_retryable if isinstance(item, dict)
    }
    if non_retryable_ids != EXPECTED_NON_RETRYABLE_IDS:
        errors.append("non-retryable condition registry differs from expected set")
    deviation_ids = {
        item.get("id")
        for item in policy.get("deviation_rules") or []
        if isinstance(item, dict)
    }
    if deviation_ids != EXPECTED_DEVIATION_IDS:
        errors.append("deviation registry differs from expected set")

    classifier = policy.get("outcome_blind_infrastructure_classification") or {}
    top_level = classifier.get("classifier_projection_top_level_fields") or []
    allowed = classifier.get("allowed_predecode_signal_fields") or []
    allowed_process = classifier.get("allowed_process_metadata_fields") or []
    forbidden = classifier.get("forbidden_fields") or []
    if top_level != EXPECTED_CLASSIFIER_TOP_LEVEL_FIELDS:
        errors.append("infrastructure classifier top-level projection differs")
    if allowed != EXPECTED_PREDECODE_SIGNAL_FIELDS:
        errors.append("infrastructure classifier predecode signal projection differs")
    if allowed_process != EXPECTED_PROCESS_METADATA_FIELDS:
        errors.append("infrastructure classifier process projection differs")
    if forbidden != EXPECTED_FORBIDDEN_CLASSIFIER_FIELDS:
        errors.append("infrastructure classifier forbidden-field registry differs")
    if set(allowed) & set(forbidden):
        errors.append("infrastructure classifier has overlapping allowed/forbidden fields")
    for required in {"decision", "primary_reason", "target_decision", "oracle_row"}:
        if required not in forbidden:
            errors.append(f"infrastructure classifier does not forbid {required}")
    for field in (
        "scientific_intent_marker_must_be_durable_before_child_spawn",
        "exactly_one_typed_predicate_required_for_retry",
        "classification_record_required",
        "classification_record_sha256_required",
        "classifier_receives_process_metadata",
    ):
        if classifier.get(field) is not True:
            errors.append(f"infrastructure classifier guard is not true: {field}")
    for field in (
        "classifier_receives_raw_artifacts",
        "classifier_receives_result_or_oracle_bytes",
        "invalid_classification_retry_allowed",
    ):
        if classifier.get(field) is not False:
            errors.append(f"infrastructure classifier guard is not false: {field}")

    external = policy.get("external_reproduction") or {}
    external_mandatory = external.get("mandatory_before_manuscript_submission") is True
    if not external_mandatory or external.get("claim_C011_allowed_before_completion") is not False:
        errors.append("external reproduction/C011 policy is not fail-closed")
    claim = _claim_c011()
    if claim.get("allowed_now") != "no" or "Mandatory before manuscript submission" not in claim.get("notes", ""):
        errors.append("C011 ledger row does not enforce the mandatory external gate")

    dummy_status = (policy.get("dummy_analysis") or {}).get("status", "not_implemented")
    dummy_valid = False
    dummy_planned_rows = 0
    dummy_contract = policy.get("dummy_analysis") or {}
    if dummy_status in {"implemented_validated_not_frozen", "frozen"}:
        if dummy_contract.get("implementation_path") != "scripts/analyze_observation_ledger.py":
            errors.append("dummy analysis implementation path differs")
        if dummy_contract.get("retained_output_path") != "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json":
            errors.append("dummy analysis retained-output path differs")
        try:
            dummy_summary, _ = _load(DUMMY_SUMMARY_PATH, max_bytes=2 * 1024 * 1024)
            dummy_output_schema, dummy_output_schema_raw = _load(DUMMY_OUTPUT_SCHEMA_PATH)
            dummy_input_schema_raw = DUMMY_INPUT_SCHEMA_PATH.read_bytes()
            dummy_ledger_raw = DUMMY_LEDGER_PATH.read_bytes()
            dummy_errors = _schema_errors(dummy_output_schema, dummy_summary)
            if dummy_errors:
                errors.append("dummy analysis output invalid: " + dummy_errors[0])
            expected_dummy = {
                "classification": "dummy_no_confirmatory_evidence",
                "input_sha256": _sha(dummy_ledger_raw),
                "input_schema_sha256": _sha(dummy_input_schema_raw),
                "output_schema_sha256": _sha(dummy_output_schema_raw),
                "analyzer_sha256": _sha(DUMMY_ANALYZER_PATH.read_bytes()),
                "attack_catalog_sha256": _sha(CATALOG_PATH.read_bytes()),
                "compatibility_matrix_sha256": _sha(MATRIX_PATH.read_bytes()),
                "oracle_sha256": _sha(ORACLE_PATH.read_bytes()),
                "proposition_matrix_sha256": _sha(PROPOSITIONS_PATH.read_bytes()),
                "planned_row_count": 1480,
                "conformance_mismatch_count": 8,
                "terminal_only_denominator_used": False,
                "category_sum_matches_denominator": True,
                "all_required_propositions_evaluable_and_supported": False,
                "manuscript_claims_authorized": False,
            }
            for field, expected in expected_dummy.items():
                if dummy_summary.get(field) != expected:
                    errors.append(f"dummy analysis retained field differs: {field}")
            if dummy_summary.get("category_counts") != {
                "ACCEPT": 759,
                "REJECT": 715,
                "ERROR": 1,
                "MISSING_EXECUTION": 1,
                "GENERATION_FAILURE": 4,
            }:
                errors.append("dummy analysis category counts differ")
            if any(
                item.get("abstract_eligible") is not False
                or item.get("conclusion_eligible") is not False
                for item in dummy_summary.get("propositions") or []
            ):
                errors.append("dummy analysis authorizes abstract/conclusion wording")
            expected_authorization_blockers = [
                "analysis summaries cannot self-authorize manuscript claims",
                "independent exact-byte review and external reproduction require separate authenticated records",
                "one or more required propositions are unsupported, incomplete, or not evaluable",
                "input is a synthetic dummy ledger",
            ]
            if dummy_summary.get("authorization_blockers") != expected_authorization_blockers:
                errors.append("dummy analysis authorization blockers differ")
            target_invalid = dummy_summary.get("target_invalid_breakdown") or {}
            breakdown_rows = target_invalid.get("by_profile_and_family") or []
            breakdown_planned = sum(
                item.get("planned_row_count", -1)
                for item in breakdown_rows
                if isinstance(item, dict)
            )
            aggregate_counts = target_invalid.get("category_counts") or {}
            recomputed_counts = {
                category: sum(
                    (item.get("category_counts") or {}).get(category, -1)
                    for item in breakdown_rows
                    if isinstance(item, dict)
                )
                for category in (
                    "ACCEPT",
                    "REJECT",
                    "ERROR",
                    "MISSING_EXECUTION",
                    "GENERATION_FAILURE",
                )
            }
            if (
                target_invalid.get("planned_row_count") != 1432
                or breakdown_planned != 1432
                or sum(aggregate_counts.values()) != 1432
                or aggregate_counts != recomputed_counts
                or target_invalid.get("subtotals_reconcile") is not True
                or target_invalid.get("pooled_primary_result_permitted") is not False
            ):
                errors.append("dummy analysis target-invalid breakdown does not reconcile")
            dummy_scope = dummy_summary.get("read_scope") or {}
            if dummy_scope.get("dummy_input_only") is not True or any(
                dummy_scope.get(field) is not False
                for field in (
                    "confirmatory_artifacts_read",
                    "model_outputs_read",
                    "network_used",
                    "independent_review_performed",
                )
            ):
                errors.append("dummy analysis exceeds its no-confirmatory read scope")
            dummy_planned_rows = int(dummy_summary.get("planned_row_count") or 0)
            dummy_valid = not any(error.startswith("dummy analysis") for error in errors)
        except Exception as exc:
            errors.append(f"dummy analysis validation failed: {type(exc).__name__}: {exc}")
    status = policy.get("status")
    freeze_permitted = (
        not errors
        and status == "frozen"
        and pending_count == 0
        and dummy_status == "frozen"
        and dummy_valid
        and runner["hashes_match"]
        and runner["test_record_valid"]
        and runner["confirmatory_execution_permitted"]
        and runner["rg006_complete"]
    )
    if pending_count:
        warnings.append(f"{pending_count} compatibility rows remain pending")
    if dummy_status != "frozen":
        warnings.append(f"dummy analysis is {dummy_status}")
    if status != "frozen":
        warnings.append(f"run policy status is {status}")
    if not runner["confirmatory_execution_permitted"]:
        warnings.append("runner contract forbids confirmatory execution")
    if not runner["rg006_complete"]:
        warnings.append(
            f"RG-006 remains incomplete with {runner['open_control_count']} open controls"
        )

    result = {
        "schema_version": "amy.run-execution-policy-validation.v1-draft",
        "valid": not errors,
        "policy_sha256": _sha(policy_raw),
        "policy_schema_sha256": _sha(schema_raw),
        "validator_sha256": _sha(Path(__file__).read_bytes()),
        "bound_artifact_hashes_match": bound_matches,
        "runner_contract_status": runner["status"],
        "runner_contract_hashes_match": runner["hashes_match"],
        "runner_contract_test_record_valid": runner["test_record_valid"],
        "runner_contract_test_record_sha256": runner["test_record_sha256"],
        "runner_contract_passed_test_count": runner["passed_test_count"],
        "runner_contract_open_control_count": runner["open_control_count"],
        "runner_confirmatory_execution_permitted": runner[
            "confirmatory_execution_permitted"
        ],
        "runner_rg006_complete": runner["rg006_complete"],
        "case_count": case_count,
        "base_count": base_count,
        "profile_count": profile_count,
        "proposition_count": proposition_count,
        "pending_compatibility_row_count": pending_count,
        "dummy_analysis_status": dummy_status,
        "dummy_analysis_valid": dummy_valid,
        "dummy_analysis_planned_row_count": dummy_planned_rows,
        "external_reproduction_mandatory": external_mandatory,
        "freeze_permitted": freeze_permitted,
        "decision": "GO" if freeze_permitted else "NO-GO",
        "read_scope": {
            "confirmatory_artifacts_read": False,
            "verifier_results_read": False,
            "oracle_join_performed": False,
            "independent_review_performed": False,
        },
        "errors": errors,
        "warnings": warnings,
    }
    output_errors = _schema_errors(validation_schema, result)
    if output_errors:
        raise ValueError("invalid validation result: " + "; ".join(output_errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate()
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    ) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
