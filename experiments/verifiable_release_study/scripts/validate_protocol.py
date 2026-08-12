#!/usr/bin/env python3
"""Deterministically validate the study-design contracts.

Draft mode permits explicit TBD markers. Registration-ready mode rejects every
remaining TBD marker and every draft/not-frozen status.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"P0", "P1", "P2", "P3"}
DECISIONS = {"ACCEPT", "REJECT", "ERROR"}
GATE_STATUSES = {"open", "partial", "complete"}
FULL_GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
CONFIRMATORY_RQS = {"RQ1", "RQ2", "RQ3", "RQ4", "RQ5"}
EXPLORATORY_RQS = {"E-RQ6"}
DESIGN_REQUIREMENTS = {"D1", "D2", "D3", "D4", "D5", "D6"}
SELECTED_MIGRATED_OPERATOR_IDS = {
    "BUILD-DIRTY-001",
    "BUILD-METADATA-MISSING-001",
    "BUILDER-PREDICATE-MISMATCH-001",
    "EXECUTION-IMAGE-MISMATCH-001",
    "MATERIAL-LOCK-MISMATCH-001",
    "PREDICATE-WRONG-TYPE-001",
    "SNAPSHOT-DIGEST-MISMATCH-001",
    "SNAPSHOT-ROLE-MISMATCH-001",
    "SOURCE-TREE-MISMATCH-001",
    "SOURCE-WRONG-REVISION-001",
    "WORKFLOW-PARAMETER-MISMATCH-001",
}
HISTORICAL_V1_SHA256 = {
    "schemas/github-production-verification-result.schema.json": (
        "64eef1a87da45dff355047963ebe762dfced1a2ba7e60be9a87dfcc28a1e2c18"
    ),
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json": (
        "68ea605c25a8e73ebe955a1bfd3977a309f13b40b9a112aee6b2e9bc5cd38c26"
    ),
    "production_pilot_runs/github_cli_2.96.0_upstream_smoke/result.json": (
        "444615e874774a01679e55098885a5e790d78a70a8f5fa0cc39caab28e545baa"
    ),
    "scripts/verify_github_attestation.py": (
        "9fbfa1ff99f8e5308cae741acfa6a5c683b0c36adaa68bfe930dee61ee49993b"
    ),
    "amy_verifier/github_attestation.py": (
        "6731d83c0ea94d0ce2029ce529a175c3eb9cd1d17e9698b090f47a72044fe6ac"
    ),
}


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object name: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def strict_json_loads(text: str) -> Any:
    """Parse protocol JSON with no duplicate-name or NaN/Infinity ambiguity."""

    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonstandard_constant,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(relative: str) -> tuple[Path, Any]:
    path = STUDY_ROOT / relative
    return path, strict_json_loads(path.read_text(encoding="utf-8"))


def walk_strings(value: Any, location: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        found.append((location, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(walk_strings(item, f"{location}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(walk_strings(item, f"{location}.{key}"))
    return found


def validate(registration_ready: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    catalog_path, catalog = load_json("protocol/ATTACK_CATALOG.json")
    selected_catalog_path, selected_catalog = load_json(
        "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
    )
    selected_catalog_validation_path, selected_catalog_validation = load_json(
        "protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json"
    )
    selected_oracle_path, selected_oracle = load_json(
        "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
    )
    selected_oracle_validation_path, selected_oracle_validation = load_json(
        "protocol/SELECTED_PROFILE_ORACLE_VALIDATION.json"
    )
    selected_development_record_path, selected_development_record = load_json(
        "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_V2_2026-07-15T034921Z.json"
    )
    selected_development_validation_path, selected_development_validation = load_json(
        "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_V2_2026-07-15T034921Z.json"
    )
    base_aware_record_path, base_aware_record = load_json(
        "development_checks/BASE_AWARE_MUTATION_PLANS_V2_2026-07-15T034921Z.json"
    )
    base_aware_validation_path, base_aware_validation = load_json(
        "development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_V2_2026-07-15T034921Z.json"
    )
    robustness_catalog_path, robustness_catalog = load_json(
        "protocol/ROBUSTNESS_CATALOG_DRAFT.json"
    )
    reasons_path, reasons = load_json("protocol/REASON_CODES.json")
    production_reasons_path, production_reasons = load_json(
        "protocol/PRODUCTION_REASON_CODES_DRAFT.json"
    )
    trust_path, trust = load_json("protocol/TRUST_POLICY_DRAFT.json")
    historical_production_policy_path, historical_production_policy = load_json(
        "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json"
    )
    production_policy_path, production_policy = load_json(
        "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json"
    )
    attestation_decision_path, attestation_decision = load_json(
        "protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json"
    )
    upstream_attestation_audit_path, upstream_attestation_audit = load_json(
        "audit/UPSTREAM_ATTESTATION_SEMANTICS_2026-07-13.json"
    )
    registration_gates_path, registration_gates = load_json(
        "protocol/REGISTRATION_GATES.json"
    )
    model_review_protocol_path, model_review_protocol = load_json(
        "protocol/MODEL_REVIEW_PROTOCOL.json"
    )
    model_review_protocol_schema_path, model_review_protocol_schema = load_json(
        "schemas/model-review-protocol.schema.json"
    )
    model_review_response_schema_path, model_review_response_schema = load_json(
        "schemas/model-review-response.schema.json"
    )
    model_review_runner_path = STUDY_ROOT / "scripts/run_model_review_batch.py"
    model_review_validator_path = STUDY_ROOT / "scripts/validate_model_review_batch.py"
    model_review_test_path = STUDY_ROOT / "tests/test_model_review_protocol.py"
    pre_r0_closure_ledger_path, pre_r0_closure_ledger = load_json(
        "protocol/PRE_R0_CLOSURE_LEDGER.json"
    )
    pre_r0_closure_validation_path, pre_r0_closure_validation = load_json(
        "protocol/PRE_R0_CLOSURE_LEDGER_VALIDATION.json"
    )
    pre_r0_closure_schema_path, pre_r0_closure_schema = load_json(
        "schemas/pre-r0-closure-ledger.schema.json"
    )
    pre_r0_closure_validation_schema_path, pre_r0_closure_validation_schema = load_json(
        "schemas/pre-r0-closure-ledger-validation.schema.json"
    )
    pre_r0_closure_validator_path = (
        STUDY_ROOT / "scripts/validate_pre_r0_closure_ledger.py"
    )
    lineage_contract_path, lineage_contract = load_json(
        "protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json"
    )
    lineage_validation_path, lineage_validation = load_json(
        "protocol/RELEASE_LINEAGE_VALIDATION.json"
    )
    proposition_path, proposition_matrix = load_json(
        "protocol/PROPOSITION_MATRIX_DRAFT.json"
    )
    run_policy_path, run_policy = load_json(
        "protocol/RUN_EXECUTION_POLICY_DRAFT.json"
    )
    run_policy_validation_path, run_policy_validation = load_json(
        "protocol/RUN_EXECUTION_POLICY_VALIDATION.json"
    )
    rg006_test_record_path, rg006_test_record = load_json(
        "development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json"
    )
    base_registry_path, base_registry = load_json("corpus/BASE_REGISTRY_DRAFT.json")
    prerequisite_path, prerequisite_registry = load_json(
        "protocol/PREREQUISITE_REGISTRY_DRAFT.json"
    )
    selected_prerequisite_path, selected_prerequisite_registry = load_json(
        "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json"
    )
    compatibility_path, compatibility_matrix = load_json(
        "corpus/COMPATIBILITY_MATRIX_DRAFT.json"
    )
    selected_compatibility_path, selected_compatibility_matrix = load_json(
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
    )
    selected_compatibility_validation_path, selected_compatibility_validation = load_json(
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json"
    )
    selected_base_validation_path, selected_base_validation = load_json(
        "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/validation.json"
    )
    selected_base_summary_path, selected_base_summary = load_json(
        "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/summary.json"
    )
    selected_effective_policy_path, selected_effective_policy = load_json(
        "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/effective_fixture_policy.jcs.json"
    )
    selected_base_comparison_path, selected_base_comparison = load_json(
        "selected_profile_base_runs/SELECTED_RUN_COMPARISON_2026-07-13.json"
    )
    selected_base_current_replay_path, selected_base_current_replay = load_json(
        "selected_profile_base_runs/R0_SELECTED_BASES_CURRENT_REPLAY_2026-07-13.json"
    )
    result_schema_path, result_schema = load_json("schemas/verifier-result.schema.json")
    manifest_schema_path, manifest_schema = load_json("schemas/manifest.schema.json")
    production_manifest_schema_path, production_manifest_schema = load_json(
        "schemas/manifest-production-v0.2.schema.json"
    )
    production_policy_schema_path, production_policy_schema = load_json(
        "schemas/github-attestation-policy-v2.schema.json"
    )
    historical_production_result_schema_path, historical_production_result_schema = (
        load_json("schemas/github-production-verification-result.schema.json")
    )
    production_result_schema_path, production_result_schema = load_json(
        "schemas/github-production-verification-result-v2.schema.json"
    )
    selected_fixture_result_schema_path, selected_fixture_result_schema = load_json(
        "schemas/selected-profile-fixture-result.schema.json"
    )
    selected_oracle_schema_path, selected_oracle_schema = load_json(
        "schemas/selected-profile-oracle.schema.json"
    )
    selected_development_schema_path, selected_development_schema = load_json(
        "schemas/selected-profile-development-check.schema.json"
    )
    base_aware_schema_path, base_aware_schema = load_json(
        "schemas/base-aware-mutation-development-check.schema.json"
    )
    lineage_contract_schema_path, lineage_contract_schema = load_json(
        "schemas/release-lineage-contract.schema.json"
    )
    lineage_validation_schema_path, lineage_validation_schema = load_json(
        "schemas/release-lineage-validation.schema.json"
    )
    run_policy_schema_path, run_policy_schema = load_json(
        "schemas/run-execution-policy.schema.json"
    )
    run_policy_validation_schema_path, run_policy_validation_schema = load_json(
        "schemas/run-execution-policy-validation.schema.json"
    )
    process_isolation_schema_path, process_isolation_schema = load_json(
        "schemas/process-isolation-record.schema.json"
    )
    environment_attempt_schema_path, environment_attempt_schema = load_json(
        "schemas/environment-attempt-record.schema.json"
    )
    infrastructure_classification_schema_path, infrastructure_classification_schema = (
        load_json("schemas/infrastructure-classification.schema.json")
    )
    official_attempt_selection_schema_path, official_attempt_selection_schema = load_json(
        "schemas/official-attempt-selection.schema.json"
    )
    rg006_test_record_schema_path, rg006_test_record_schema = load_json(
        "schemas/rg006-contract-test-record-v3.schema.json"
    )
    review_record_schema_path, review_record_schema = load_json(
        "schemas/r0-human-review-record.schema.json"
    )
    review_record_template_path, review_record_template = load_json(
        "protocol/R0_HUMAN_REVIEW_RECORD_TEMPLATE.json"
    )
    review_packet_verification_schema_path, review_packet_verification_schema = load_json(
        "schemas/r0-review-packet-verification.schema.json"
    )
    reviewer_identity_policy_path, reviewer_identity_policy = load_json(
        "protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json"
    )
    reviewer_identity_validation_path, reviewer_identity_validation = load_json(
        "protocol/R0_REVIEWER_IDENTITY_POLICY_VALIDATION.json"
    )
    reviewer_identity_schema_path, reviewer_identity_schema = load_json(
        "schemas/r0-reviewer-identity-policy.schema.json"
    )
    reviewer_identity_validation_schema_path, reviewer_identity_validation_schema = (
        load_json("schemas/r0-reviewer-identity-policy-validation.schema.json")
    )

    for label, schema in (
        ("result", result_schema),
        ("pilot manifest", manifest_schema),
        ("production manifest", production_manifest_schema),
        ("production attestation policy", production_policy_schema),
        ("historical production verification result v1", historical_production_result_schema),
        ("production verification result", production_result_schema),
        ("selected-profile fixture result", selected_fixture_result_schema),
        ("selected-profile oracle", selected_oracle_schema),
        ("selected-profile development check", selected_development_schema),
        ("base-aware mutation development check", base_aware_schema),
        ("release-lineage contract", lineage_contract_schema),
        ("release-lineage validation", lineage_validation_schema),
        ("run-execution policy", run_policy_schema),
        ("run-execution policy validation", run_policy_validation_schema),
        ("process-isolation record", process_isolation_schema),
        ("environment-attempt record", environment_attempt_schema),
        ("infrastructure classification", infrastructure_classification_schema),
        ("official-attempt selection", official_attempt_selection_schema),
        ("RG-006 contract-test record", rg006_test_record_schema),
        ("R0 human-review record", review_record_schema),
        ("R0 review-packet verification", review_packet_verification_schema),
        ("R0 reviewer-identity policy", reviewer_identity_schema),
        (
            "R0 reviewer-identity policy validation",
            reviewer_identity_validation_schema,
        ),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f"Invalid {label} JSON Schema: {type(exc).__name__}: {exc}")

    for label, instance, schema in (
        ("production attestation policy", production_policy, production_policy_schema),
        ("release-lineage contract", lineage_contract, lineage_contract_schema),
        ("release-lineage validation", lineage_validation, lineage_validation_schema),
        ("run-execution policy", run_policy, run_policy_schema),
        (
            "run-execution policy validation",
            run_policy_validation,
            run_policy_validation_schema,
        ),
        (
            "RG-006 contract-test record",
            rg006_test_record,
            rg006_test_record_schema,
        ),
        ("R0 human-review template", review_record_template, review_record_schema),
        (
            "R0 reviewer-identity policy",
            reviewer_identity_policy,
            reviewer_identity_schema,
        ),
        (
            "R0 reviewer-identity policy validation",
            reviewer_identity_validation,
            reviewer_identity_validation_schema,
        ),
    ):
        instance_errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance)
        )
        if instance_errors:
            errors.append(
                f"Invalid {label} instance: {instance_errors[0].message}"
            )

    for relative, expected_digest in HISTORICAL_V1_SHA256.items():
        if sha256(STUDY_ROOT / relative) != expected_digest:
            errors.append(f"Historical v1 artifact changed bytes: {relative}")
    if historical_production_policy.get("policy_version") != "0.1.0-draft":
        errors.append("Historical v1 policy no longer declares its original version")

    policy_schema_identity = production_policy.get("policy_schema") or {}
    if production_policy.get("schema_version") != "amy.github-attestation-policy.v2-draft":
        errors.append("Current production policy is not the v2 contract")
    if policy_schema_identity.get("schema_path") != str(
        production_policy_schema_path.relative_to(STUDY_ROOT)
    ):
        errors.append("Production policy points to an unexpected policy schema")
    if policy_schema_identity.get("schema_sha256") != sha256(
        production_policy_schema_path
    ):
        errors.append("Production policy-schema hash differs from current bytes")

    lineage_validator_path = STUDY_ROOT / "scripts/validate_release_lineage_contract.py"
    expected_lineage_hashes = {
        "contract_sha256": sha256(lineage_contract_path),
        "contract_schema_sha256": sha256(lineage_contract_schema_path),
        "validation_schema_sha256": sha256(lineage_validation_schema_path),
        "source_ledger_sha256": sha256(STUDY_ROOT / "evidence/SOURCE_LEDGER.md"),
        "validator_sha256": sha256(lineage_validator_path),
    }
    for field, expected_digest in expected_lineage_hashes.items():
        if lineage_validation.get(field) != expected_digest:
            errors.append(f"Release-lineage validation {field} differs from current bytes")
    if lineage_validation.get("valid") is not True:
        errors.append("Release-lineage retained validation is not internally valid")
    if lineage_validation.get("record_status") != lineage_contract.get("record_status"):
        errors.append("Release-lineage validation/contract status mismatch")
    if lineage_validation.get("decision") != (
        lineage_contract.get("current_decision") or {}
    ).get("decision"):
        errors.append("Release-lineage validation/contract decision mismatch")
    lineage_read_scope = lineage_validation.get("read_scope") or {}
    if any(
        lineage_read_scope.get(field) is not False
        for field in (
            "confirmatory_artifacts_read",
            "verifier_results_read",
            "network_used",
            "independent_review_performed",
        )
    ):
        errors.append("Release-lineage validation exceeds its declared static read scope")

    run_policy_validator_path = STUDY_ROOT / "scripts/validate_run_execution_policy.py"
    expected_run_policy_hashes = {
        "policy_sha256": sha256(run_policy_path),
        "policy_schema_sha256": sha256(run_policy_schema_path),
        "validator_sha256": sha256(run_policy_validator_path),
    }
    for field, expected_digest in expected_run_policy_hashes.items():
        if run_policy_validation.get(field) != expected_digest:
            errors.append(f"Run-policy validation {field} differs from current bytes")
    if run_policy_validation.get("valid") is not True:
        errors.append("Run-policy retained validation is not internally valid")
    if run_policy_validation.get("bound_artifact_hashes_match") is not True:
        errors.append("Run-policy retained validation reports bound-artifact drift")
    if run_policy_validation.get("external_reproduction_mandatory") is not True:
        errors.append("Run policy does not make external reproduction mandatory")
    if run_policy_validation.get("freeze_permitted") is not False:
        errors.append("Draft run policy must not permit freeze")
    if run_policy_validation.get("decision") != "NO-GO":
        errors.append("Draft run-policy validation must report NO-GO")
    if run_policy_validation.get("dummy_analysis_status") != (
        run_policy.get("dummy_analysis") or {}
    ).get("status"):
        errors.append("Run-policy dummy-analysis status differs from retained validation")
    if run_policy_validation.get("dummy_analysis_valid") is not True:
        errors.append("Run-policy retained dummy analysis is not valid")
    if run_policy_validation.get("dummy_analysis_planned_row_count") != 1480:
        errors.append("Run-policy retained dummy-analysis denominator differs")
    if run_policy_validation.get("runner_contract_hashes_match") is not True:
        errors.append("Run-policy runner-contract source hashes do not match")
    if run_policy_validation.get("runner_contract_test_record_valid") is not True:
        errors.append("Run-policy RG-006 synthetic test record is not valid")
    if run_policy_validation.get("runner_contract_test_record_sha256") != sha256(
        rg006_test_record_path
    ):
        errors.append("Run-policy RG-006 test-record SHA-256 differs")
    if run_policy_validation.get("runner_contract_passed_test_count") != 61:
        errors.append("Run-policy RG-006 passing-test count differs")
    if run_policy_validation.get("runner_contract_open_control_count") != 11:
        errors.append("Run-policy RG-006 open-control count differs")
    if run_policy_validation.get("runner_confirmatory_execution_permitted") is not False:
        errors.append("Draft runner must forbid confirmatory execution")
    if run_policy_validation.get("runner_rg006_complete") is not False:
        errors.append("Draft runner must not claim RG-006 completion")
    if rg006_test_record.get("decision") != "NO-GO":
        errors.append("RG-006 synthetic test record must report NO-GO")
    if rg006_test_record.get("rg006_complete") is not False:
        errors.append("RG-006 synthetic test record must remain incomplete")
    if rg006_test_record.get("manuscript_claims_authorized") is not False:
        errors.append("RG-006 synthetic test record must not authorize manuscript claims")
    rg006_boundaries = rg006_test_record.get("boundaries") or {}
    if any(value is not False for value in rg006_boundaries.values()):
        errors.append("RG-006 synthetic test record exceeds its engineering boundary")
    run_policy_read_scope = run_policy_validation.get("read_scope") or {}
    if any(
        run_policy_read_scope.get(field) is not False
        for field in (
            "confirmatory_artifacts_read",
            "verifier_results_read",
            "oracle_join_performed",
            "independent_review_performed",
        )
    ):
        errors.append("Run-policy validation exceeds its declared design-only read scope")

    reviewer_identity_validator_path = (
        STUDY_ROOT / "scripts/validate_r0_reviewer_identity_policy.py"
    )
    expected_reviewer_identity_hashes = {
        "policy_sha256": sha256(reviewer_identity_policy_path),
        "policy_schema_sha256": sha256(reviewer_identity_schema_path),
        "validation_schema_sha256": sha256(
            reviewer_identity_validation_schema_path
        ),
        "source_ledger_sha256": sha256(STUDY_ROOT / "evidence/SOURCE_LEDGER.md"),
        "validator_sha256": sha256(reviewer_identity_validator_path),
    }
    for field, expected_digest in expected_reviewer_identity_hashes.items():
        if reviewer_identity_validation.get(field) != expected_digest:
            errors.append(
                f"Reviewer-identity validation {field} differs from current bytes"
            )
    if reviewer_identity_validation.get("valid") is not True:
        errors.append("Reviewer-identity retained validation is not internally valid")
    if reviewer_identity_validation.get("policy_status") != (
        reviewer_identity_policy.get("status")
    ):
        errors.append("Reviewer-identity policy/validation status differs")
    if reviewer_identity_validation.get("decision") != "NO-GO":
        errors.append("Unfrozen reviewer-identity policy must report NO-GO")
    for field in (
        "selected_version_not_known_vulnerable",
        "freeze_permitted",
        "authentication_execution_permitted",
        "rg004_complete",
    ):
        if reviewer_identity_validation.get(field) is not False:
            errors.append(f"Reviewer-identity draft boundary is not false: {field}")
    reviewer_identity_read_scope = reviewer_identity_validation.get("read_scope") or {}
    if any(value is not False for value in reviewer_identity_read_scope.values()):
        errors.append("Reviewer-identity validation exceeds its static read scope")

    versions = {
        "catalog": catalog.get("catalog_version"),
        "reasons": reasons.get("registry_version"),
        "trust": trust.get("policy_version"),
        "result_schema": ((result_schema.get("properties") or {}).get("schema_version") or {}).get("const"),
    }
    if len(set(versions.values())) != 1:
        errors.append(f"Contract versions differ: {versions}")

    catalog_profiles = {entry.get("id") for entry in catalog.get("profiles", [])}
    if catalog_profiles != PROFILES:
        errors.append(f"Catalog profiles {sorted(catalog_profiles)} != {sorted(PROFILES)}")
    selected_catalog_profiles = {
        entry.get("id") for entry in selected_catalog.get("profiles", [])
    }
    if selected_catalog_profiles != PROFILES:
        errors.append(
            "Selected catalog profiles "
            f"{sorted(selected_catalog_profiles)} != {sorted(PROFILES)}"
        )

    schema_profiles = set(
        (((result_schema.get("properties") or {}).get("profile_id") or {}).get("enum")) or []
    )
    if schema_profiles != PROFILES:
        errors.append(f"Result-schema profiles {sorted(schema_profiles)} != {sorted(PROFILES)}")

    expected_check_states = {"PASS", "FAIL", "NOT_RUN", "NOT_REQUIRED"}
    schema_check_states = set(
        ((((result_schema.get("$defs") or {}).get("checkState") or {}).get("enum")) or [])
    )
    if schema_check_states != expected_check_states:
        errors.append(
            f"Result-schema check states {sorted(schema_check_states)} != "
            f"{sorted(expected_check_states)}"
        )

    commit_pattern = (
        (((result_schema.get("properties") or {}).get("implementation") or {})
         .get("properties") or {})
        .get("git_commit", {})
        .get("pattern")
    )
    if commit_pattern != r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$":
        errors.append("Result-schema git_commit must accept exactly 40 or 64 hex characters")

    limits = trust.get("limits") or {}
    integer_limits = {
        key: value
        for key, value in limits.items()
        if key != "status"
    }
    for key, value in integer_limits.items():
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"Trust-policy limit {key} must be a positive integer")
    if (
        isinstance(limits.get("single_payload_max_bytes"), int)
        and isinstance(limits.get("payload_total_max_bytes"), int)
        and limits["single_payload_max_bytes"] > limits["payload_total_max_bytes"]
    ):
        errors.append("single_payload_max_bytes exceeds payload_total_max_bytes")

    production_tool = production_policy.get("tool") or {}
    tool_version = production_tool.get("version")
    if not isinstance(tool_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", tool_version):
        errors.append("Production policy must pin a semantic gh version")
    release_url = production_tool.get("release_url")
    if isinstance(tool_version, str) and (
        not isinstance(release_url, str) or not release_url.endswith(f"/v{tool_version}")
    ):
        errors.append("Production-policy gh release URL does not match the pinned version")
    for field in ("archive_sha256_by_platform", "binary_sha256_by_platform"):
        platform_hashes = production_tool.get(field)
        if not isinstance(platform_hashes, dict) or not platform_hashes:
            errors.append(f"Production-policy {field} must be a non-empty object")
            continue
        for platform, digest in platform_hashes.items():
            if not isinstance(platform, str) or not SHA256_HEX.fullmatch(str(digest)):
                errors.append(f"Production-policy {field}/{platform} is not a SHA-256 digest")

    production_subject = production_policy.get("subject") or {}
    if production_subject.get("allow_additional_subjects") is not False:
        errors.append("A.M.Y production policy must reject additional attestation subjects")
    if production_subject.get("digest_algorithm") != "sha256":
        errors.append("A.M.Y production subject algorithm must be sha256")

    workflow_dependencies = production_policy.get("workflow_dependencies") or {}
    if not workflow_dependencies:
        errors.append("Production policy has no pinned workflow dependencies")
    for dependency, pin in workflow_dependencies.items():
        if not isinstance(pin, dict) or not FULL_GIT_SHA1.fullmatch(str(pin.get("commit", ""))):
            errors.append(f"Workflow dependency {dependency} is not pinned to a full SHA-1 OID")

    audited_upstream = upstream_attestation_audit.get("upstream") or {}
    pinned_attest_commit = (
        (workflow_dependencies.get("actions_attest") or {}).get("commit")
    )
    if audited_upstream.get("commit") != pinned_attest_commit:
        errors.append("Upstream attestation audit does not match the pinned action commit")
    observed_default = upstream_attestation_audit.get("observed_default_provenance") or {}
    if observed_default.get("predicate_type") != (
        (production_policy.get("statement") or {}).get("p3_predicate_type")
    ):
        errors.append("Audited default predicate type differs from production policy")
    if (upstream_attestation_audit.get("current_local_p3_contract") or {}).get(
        "compatible_with_pinned_default_predicate"
    ) is not False:
        errors.append("Upstream audit must retain the observed default/P3 incompatibility")

    expected_attestation_profiles = {
        "standard_provenance_plus_authenticated_manifest_metadata",
        "dual_standard_and_custom_attestations",
        "custom_slsa_build_type",
        "reduce_p3_to_default_fields_only",
    }
    candidate_profiles = attestation_decision.get("candidate_profiles") or []
    candidate_profile_ids = {
        candidate.get("id")
        for candidate in candidate_profiles
        if isinstance(candidate, dict)
    }
    if candidate_profile_ids != expected_attestation_profiles:
        errors.append("Attestation decision does not enumerate the four reviewed profiles")
    if attestation_decision.get("recommended_profile") not in candidate_profile_ids:
        errors.append("Attestation decision recommends an unknown profile")
    selected_attestation_profile = attestation_decision.get("selected_profile")
    if selected_attestation_profile is not None and (
        selected_attestation_profile not in candidate_profile_ids
    ):
        errors.append("Attestation decision selects an unknown profile")
    if attestation_decision.get("upstream_audit") != str(
        upstream_attestation_audit_path.relative_to(STUDY_ROOT)
    ):
        errors.append("Attestation decision points to an unexpected upstream audit")
    if attestation_decision.get("blocking_registration_gate") != "RG-009":
        errors.append("Attestation decision is not bound to registration gate RG-009")
    if attestation_decision.get("status") == "selected_for_implementation_not_frozen" and (
        selected_attestation_profile != attestation_decision.get("recommended_profile")
    ):
        errors.append("Selected attestation profile differs from the reviewed recommendation")

    production_provenance = production_policy.get("provenance") or {}
    production_identity = production_policy.get("identity") or {}
    if production_provenance.get("source_repository_uri") != production_identity.get(
        "repository_uri"
    ):
        errors.append("Production policy uses inconsistent source repository URIs")
    if "materials" in production_provenance:
        errors.append("Selected production profile must not require custom SLSA materials")
    manifest_assertions = production_provenance.get("manifest_assertions") or {}
    if set(manifest_assertions) != {"source", "dependency_lock", "execution_image"}:
        errors.append("Production manifest-assertion policy is incomplete")
    production_statement = production_policy.get("statement") or {}
    if production_statement.get("attestation_mode") != (
        "actions_attest_default_slsa_provenance"
    ):
        errors.append("Selected production profile is not pinned to default SLSA provenance")
    if production_statement.get("workflow_assertion_location") != "/build_metadata":
        errors.append("Selected production workflow assertions are not bound to build_metadata")

    production_manifest_policy = production_policy.get("manifest") or {}
    if production_manifest_policy.get("schema_path") != str(
        production_manifest_schema_path.relative_to(STUDY_ROOT)
    ):
        errors.append("Production policy points to an unexpected manifest schema")
    if production_manifest_policy.get("schema_sha256") != sha256(
        production_manifest_schema_path
    ):
        errors.append("Production manifest schema hash differs from policy")
    production_schema_version = (
        ((production_manifest_schema.get("properties") or {}).get("schema_version") or {})
        .get("const")
    )
    if production_manifest_policy.get("schema_version") != production_schema_version:
        errors.append("Production manifest policy/schema versions differ")
    production_required = set(production_manifest_schema.get("required") or [])
    if "build_metadata" not in production_required:
        errors.append("Production manifest schema does not require authenticated build metadata")

    production_payload = (
        (production_manifest_schema.get("properties") or {}).get("payloads") or {}
    )
    production_payload_ref = (
        ((production_payload.get("items") or {}).get("$ref"))
    )
    if production_payload_ref != "#/$defs/payload":
        errors.append("Production manifest payload schema uses an unexpected reference")
        production_payload_properties = {}
    else:
        production_payload_properties = (
            ((production_manifest_schema.get("$defs") or {}).get("payload") or {})
            .get("properties") or {}
        )
    production_limits = production_policy.get("limits") or {}
    if production_payload.get("maxItems") != production_limits.get(
        "payload_file_max_count"
    ):
        errors.append("Production manifest maxItems differs from production policy")
    if (production_payload_properties.get("bytes") or {}).get("maximum") != (
        production_limits.get("single_payload_max_bytes")
    ):
        errors.append("Production payload byte maximum differs from production policy")
    production_role_values = set(
        (production_payload_properties.get("role") or {}).get("enum") or []
    )
    production_release_kinds = set(
        (((((production_manifest_schema.get("properties") or {}).get("release") or {})
           .get("properties") or {})
          .get("kind") or {})
         .get("enum") or [])
    )
    production_role_policy = production_manifest_policy.get(
        "required_roles_by_release_kind"
    ) or {}
    if set(production_role_policy) != production_release_kinds:
        errors.append("Production required-role kinds differ from its manifest schema")
    for kind, required_roles in production_role_policy.items():
        unknown_roles = set(required_roles) - production_role_values
        if unknown_roles:
            errors.append(f"production {kind}: unknown roles {sorted(unknown_roles)}")

    production_result_policy = production_policy.get("result") or {}
    if production_result_policy.get("schema_path") != str(
        production_result_schema_path.relative_to(STUDY_ROOT)
    ):
        errors.append("Production policy points to an unexpected result schema")
    if production_result_policy.get("schema_sha256") != sha256(
        production_result_schema_path
    ):
        errors.append("Production result schema hash differs from policy")
    production_result_version = (
        ((production_result_schema.get("$defs") or {}).get("schemaVersion") or {}).get(
            "const"
        )
    )
    if production_result_policy.get("schema_version") != production_result_version:
        errors.append("Production result policy/schema versions differ")
    p1_result_checks = (
        ((production_result_schema.get("$defs") or {}).get("p1Checks") or {}).get(
            "properties"
        )
        or {}
    )
    if set(p1_result_checks) != {
        "closed_world_inventory",
        "manifest_canonicality",
        "manifest_json_syntax",
        "manifest_schema",
        "path_safety",
        "payload_digests",
    }:
        errors.append("Production result schema does not expose the complete P1 check set")
    required_contract_identity = {
        "policy_sha256",
        "policy_schema_sha256",
        "result_schema_sha256",
    }
    for variant in ("accept", "reject", "error"):
        required = set(
            ((production_result_schema.get("$defs") or {}).get(variant) or {}).get(
                "required"
            )
            or []
        )
        if not required_contract_identity.issubset(required):
            errors.append(
                f"Production v2 {variant} result does not require complete contract identity"
            )

    production_v2_adapter_path = STUDY_ROOT / "amy_verifier/github_attestation_v2.py"
    production_v2_core_path = STUDY_ROOT / "amy_verifier/github_attestation_v2_core.py"
    production_v2_cli_path = STUDY_ROOT / "scripts/verify_github_attestation_v2.py"
    v2_adapter_source = production_v2_adapter_path.read_text(encoding="utf-8")
    v2_cli_source = production_v2_cli_path.read_text(encoding="utf-8")
    for required_text in (
        "expected_policy_sha256",
        "policy_schema_sha256",
        "result_schema_sha256",
        "result_schema_raw",
        "_validate_result_schema",
        "require_frozen=True",
    ):
        if required_text not in v2_adapter_source:
            errors.append(f"Production v2 adapter omits control: {required_text}")
    for required_text in (
        "--expected-policy-sha256",
        "--policy-schema",
        "--result-schema",
        "output_contract_ready",
    ):
        if required_text not in v2_cli_source:
            errors.append(f"Production v2 CLI omits control: {required_text}")

    manifest_payload = (
        ((manifest_schema.get("properties") or {}).get("payloads") or {})
    )
    manifest_item_properties = (
        ((manifest_payload.get("items") or {}).get("properties") or {})
    )
    if manifest_payload.get("maxItems") != limits.get("payload_file_max_count"):
        errors.append("Manifest maxItems differs from trust-policy payload_file_max_count")
    if (
        (manifest_item_properties.get("bytes") or {}).get("maximum")
        != limits.get("single_payload_max_bytes")
    ):
        errors.append("Manifest payload byte maximum differs from trust policy")
    if (
        (manifest_item_properties.get("path") or {}).get("maxLength")
        != limits.get("path_max_utf8_bytes")
    ):
        warnings.append(
            "Manifest path maxLength counts code points; custom policy separately enforces UTF-8 bytes"
        )

    manifest_policy = trust.get("manifest") or {}
    declared_manifest_path = manifest_policy.get("schema_path")
    if declared_manifest_path != "schemas/manifest.schema.json":
        errors.append("Trust policy points to an unexpected manifest schema path")
    if manifest_policy.get("schema_version") != (
        ((manifest_schema.get("properties") or {}).get("schema_version") or {}).get("const")
    ):
        errors.append("Trust-policy and manifest-schema versions differ")
    role_values = set(
        ((manifest_item_properties.get("role") or {}).get("enum")) or []
    )
    release_kinds = set(
        (((((manifest_schema.get("properties") or {}).get("release") or {})
           .get("properties") or {})
          .get("kind") or {})
         .get("enum") or [])
    )
    role_policy = manifest_policy.get("required_roles_by_release_kind") or {}
    if set(role_policy) != release_kinds:
        errors.append("Trust-policy required-role kinds differ from manifest release kinds")
    for kind, required_roles in role_policy.items():
        unknown_roles = set(required_roles) - role_values
        if unknown_roles:
            errors.append(f"{kind}: unknown required roles {sorted(unknown_roles)}")

    reason_entries = reasons.get("codes", [])
    reason_codes = [entry.get("code") for entry in reason_entries]
    if len(reason_codes) != len(set(reason_codes)):
        errors.append("Duplicate reason codes")
    reason_decisions = {entry.get("code"): entry.get("decision") for entry in reason_entries}
    if set(reason_decisions.values()) - DECISIONS:
        errors.append("Reason registry contains an unknown decision")

    production_reason_base = production_reasons.get("extends") or {}
    if production_reason_base.get("path") != str(reasons_path.relative_to(STUDY_ROOT)):
        errors.append("Production reason extension points to an unexpected base registry")
    if production_reason_base.get("sha256") != sha256(reasons_path):
        errors.append("Production reason extension base hash differs from the retained registry")
    additional_reason_entries = production_reasons.get("additional_codes") or []
    additional_reason_codes = [
        entry.get("code") for entry in additional_reason_entries if isinstance(entry, dict)
    ]
    if len(additional_reason_codes) != len(set(additional_reason_codes)):
        errors.append("Production reason extension contains duplicate codes")
    if set(additional_reason_codes) & set(reason_codes):
        errors.append("Production reason extension redundantly redefines base codes")
    if {
        entry.get("decision")
        for entry in additional_reason_entries
        if isinstance(entry, dict)
    } - DECISIONS:
        errors.append("Production reason extension contains an unknown decision")
    production_adapter_path = STUDY_ROOT / "amy_verifier/github_attestation.py"
    adapter_tree = ast.parse(production_adapter_path.read_text(encoding="utf-8"))
    adapter_literal_reasons = {
        node.args[0].value
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GitHubGateRejected"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    production_reason_vocabulary = set(reason_codes) | set(additional_reason_codes)
    unknown_adapter_reasons = adapter_literal_reasons - production_reason_vocabulary
    if unknown_adapter_reasons:
        errors.append(
            "Production adapter emits unregistered reasons: "
            f"{sorted(unknown_adapter_reasons)}"
        )
    registered_rejections = {
        entry.get("code")
        for entry in [*reason_entries, *additional_reason_entries]
        if isinstance(entry, dict) and entry.get("decision") == "REJECT"
    }
    production_result_reason_codes = set(
        ((((production_result_schema.get("$defs") or {}).get("reasonCode") or {}).get("enum"))
         or [])
    )
    if production_result_reason_codes != registered_rejections:
        errors.append("Production result-schema reasons differ from versioned registries")
    selected_fixture_reason_codes = set(
        (
            ((selected_fixture_result_schema.get("$defs") or {}).get("reasonCode") or {}).get(
                "enum"
            )
            or []
        )
    )
    if selected_fixture_reason_codes != production_reason_vocabulary:
        errors.append(
            "Selected-fixture result-schema reasons differ from versioned registries"
        )
    selected_fixture_reject_codes = set(
        (
            (
                (selected_fixture_result_schema.get("$defs") or {}).get(
                    "rejectReasonCode"
                )
                or {}
            ).get("enum")
            or []
        )
    )
    if selected_fixture_reject_codes != registered_rejections:
        errors.append(
            "Selected-fixture REJECT reasons differ from versioned registries"
        )

    if robustness_catalog.get("stratum") != "S0-ENGINEERING-ROBUSTNESS":
        errors.append("Robustness catalog is not isolated in the engineering stratum")
    for flag, expected in (
        ("confirmatory", False),
        ("executed_before_registration", True),
        ("excluded_from_primary_denominators", True),
    ):
        if robustness_catalog.get(flag) is not expected:
            errors.append(f"Robustness catalog has an invalid {flag} boundary")
    robustness_cases = robustness_catalog.get("cases") or []
    robustness_ids = [
        case.get("id") for case in robustness_cases if isinstance(case, dict)
    ]
    if len(robustness_ids) != len(set(robustness_ids)):
        errors.append("Duplicate robustness case IDs")
    robustness_coverage_counts = {
        state: sum(
            1
            for case in robustness_cases
            if isinstance(case, dict) and case.get("coverage_state") == state
        )
        for state in ("IMPLEMENTED", "SPECIFIED_NOT_IMPLEMENTED")
    }
    for case in robustness_cases:
        if not isinstance(case, dict):
            errors.append("Robustness cases must be objects")
            continue
        case_id = str(case.get("id", "<missing-id>"))
        if not re.fullmatch(r"RB-(?:TOCTOU|FAULT)-[A-Z0-9-]+-\d{3}", case_id):
            errors.append(f"{case_id}: invalid robustness case ID")
        if case.get("family") not in {"toctou", "fault_injection"}:
            errors.append(f"{case_id}: unknown robustness family")
        decision = case.get("expected_decision")
        reason = case.get("expected_reason")
        if decision not in {"REJECT", "ERROR"}:
            errors.append(f"{case_id}: robustness decision must be REJECT or ERROR")
        if reason_decisions.get(reason) != decision:
            errors.append(f"{case_id}: robustness reason/decision mismatch")
        profiles = set(case.get("profiles") or [])
        if not profiles or profiles - PROFILES:
            errors.append(f"{case_id}: invalid robustness profile set")
        coverage = case.get("coverage_state")
        if coverage not in {"IMPLEMENTED", "SPECIFIED_NOT_IMPLEMENTED"}:
            errors.append(f"{case_id}: invalid robustness coverage state")
        evidence = case.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{case_id}: robustness evidence must be a list")
            evidence = []
        if coverage == "IMPLEMENTED" and not evidence:
            errors.append(f"{case_id}: implemented robustness case has no test evidence")
        if coverage == "SPECIFIED_NOT_IMPLEMENTED" and evidence:
            errors.append(f"{case_id}: unimplemented robustness case claims evidence")
        for node_id in evidence:
            relative_test = str(node_id).split("::", 1)[0]
            if not (STUDY_ROOT / relative_test).is_file():
                errors.append(f"{case_id}: robustness test path does not exist")

    schema_reason_codes = set(
        ((((result_schema.get("$defs") or {}).get("reasonCode") or {}).get("enum")) or [])
    )
    if schema_reason_codes != set(reason_codes):
        errors.append("Result-schema reason enum differs from reason registry")

    precedence = reasons.get("primary_reason_precedence", {})
    common_precedence = set(precedence.get("common_preflight", []))
    for profile in sorted(PROFILES):
        if profile not in precedence:
            errors.append(f"Missing reason precedence for {profile}")

    cases = catalog.get("cases", [])
    case_ids = [case.get("id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        errors.append("Duplicate case IDs")
    if not cases:
        errors.append("Attack catalog has no cases")

    used_reasons: dict[str, set[str]] = {profile: set() for profile in PROFILES}
    target_invalid = 0
    clean = 0
    for case in cases:
        case_id = case.get("id", "<missing-id>")
        kind = case.get("kind")
        target = case.get("target_decision")
        prerequisites = case.get("prerequisites")
        expectations = case.get("profile_expectations") or {}

        if not re.fullmatch(r"[A-Z0-9-]+", str(case_id)):
            errors.append(f"{case_id}: invalid case ID syntax")
        if not isinstance(prerequisites, list) or not prerequisites:
            errors.append(f"{case_id}: prerequisites must be a non-empty list")
        if set(expectations) != PROFILES:
            errors.append(f"{case_id}: profile expectation set is incomplete")
        if target not in {"ACCEPT", "REJECT"}:
            errors.append(f"{case_id}: target decision must be ACCEPT or REJECT")
        if kind == "clean":
            clean += 1
            if target != "ACCEPT":
                errors.append(f"{case_id}: clean case target must be ACCEPT")
        elif kind == "target_invalid":
            target_invalid += 1
            if target != "REJECT":
                errors.append(f"{case_id}: target-invalid case target must be REJECT")
        else:
            errors.append(f"{case_id}: unsupported kind {kind!r}")

        for profile, expectation in expectations.items():
            decision = expectation.get("decision")
            reason = expectation.get("primary_reason")
            if decision not in DECISIONS:
                errors.append(f"{case_id}/{profile}: unknown decision {decision!r}")
            if decision == "ERROR":
                errors.append(f"{case_id}/{profile}: expected ERROR is forbidden in primary catalog")
            if reason not in reason_decisions:
                errors.append(f"{case_id}/{profile}: unknown reason {reason!r}")
            elif reason_decisions[reason] != decision:
                errors.append(
                    f"{case_id}/{profile}: reason {reason} maps to "
                    f"{reason_decisions[reason]}, not {decision}"
                )
            else:
                used_reasons[profile].add(reason)
            if reason not in common_precedence | set(precedence.get(profile, [])):
                errors.append(f"{case_id}/{profile}: reason {reason} absent from precedence")

    if clean == 0 or target_invalid == 0:
        errors.append("Catalog requires at least one clean and one target-invalid case")

    selected_cases = selected_catalog.get("cases") or []
    selected_case_ids = [
        case.get("id") for case in selected_cases if isinstance(case, dict)
    ]
    if len(selected_case_ids) != len(selected_cases) or len(selected_case_ids) != len(
        set(selected_case_ids)
    ):
        errors.append("Selected-profile catalog has duplicate or malformed case IDs")
    if selected_catalog.get("catalog_version") != "0.4.0-draft":
        errors.append("Selected-profile catalog version differs from 0.4.0-draft")
    if len(selected_case_ids) != 41:
        errors.append("Selected-profile catalog must contain exactly 41 cases")
    if not set(case_ids).issubset(selected_case_ids):
        errors.append("Selected-profile catalog drops historical v0.3 case IDs")
    if len(set(selected_case_ids) - set(case_ids)) != 7:
        errors.append("Selected-profile catalog must add exactly seven case IDs")
    selected_profile_record = selected_catalog.get("profile_selection") or {}
    if selected_profile_record.get("id") != (
        "standard_provenance_plus_authenticated_manifest_metadata"
    ):
        errors.append("Selected catalog identifies an unexpected production profile")
    if selected_profile_record.get("custom_slsa_materials") is not False:
        errors.append("Selected catalog retains custom SLSA materials")
    production_reason_decisions = {
        **reason_decisions,
        **{
            entry.get("code"): entry.get("decision")
            for entry in additional_reason_entries
            if isinstance(entry, dict)
        },
    }
    selected_by_id = {
        case["id"]: case for case in selected_cases if isinstance(case, dict)
    }
    for case_id, case in selected_by_id.items():
        prerequisites = case.get("prerequisites")
        expectations = case.get("profile_expectations") or {}
        if not isinstance(prerequisites, list) or not prerequisites:
            errors.append(f"{case_id}: selected prerequisites must be a non-empty list")
        if set(expectations) != PROFILES:
            errors.append(f"{case_id}: selected profile expectation set is incomplete")
        target = case.get("target_decision")
        if target not in {"ACCEPT", "REJECT"}:
            errors.append(f"{case_id}: selected target decision is invalid")
        for profile, expectation in expectations.items():
            decision = expectation.get("decision")
            reason = expectation.get("primary_reason")
            if decision not in {"ACCEPT", "REJECT"}:
                errors.append(f"{case_id}/{profile}: selected expected decision is invalid")
            if production_reason_decisions.get(reason) != decision:
                errors.append(
                    f"{case_id}/{profile}: selected reason {reason!r} does not map to "
                    f"{decision!r}"
                )
    for case_id in SELECTED_MIGRATED_OPERATOR_IDS:
        mutation = (selected_by_id.get(case_id) or {}).get("mutation_contract") or {}
        if set(mutation) != {
            "authenticated_object",
            "isolation",
            "json_pointer",
            "payload_bytes_changed",
            "reattest_after_mutation",
        }:
            errors.append(f"{case_id}: selected mutation contract is incomplete")
        if mutation.get("payload_bytes_changed") is not False:
            errors.append(f"{case_id}: selected semantic mutation changes payload bytes")
        if mutation.get("reattest_after_mutation") is not True:
            errors.append(f"{case_id}: selected semantic mutation is not re-attested")
    if selected_catalog_validation.get("valid") is not True:
        errors.append("Selected-profile catalog validation is not valid")
    if selected_catalog_validation.get("catalog_pretty_sha256") != sha256(
        selected_catalog_path
    ):
        errors.append("Selected-profile catalog validation hash differs")
    if selected_catalog_validation.get("prerequisite_pretty_sha256") != sha256(
        selected_prerequisite_path
    ):
        errors.append("Selected-profile prerequisite validation hash differs")
    selected_catalog_builder_path = (
        STUDY_ROOT / "scripts/build_selected_profile_catalog.py"
    )
    selected_catalog_validator_path = (
        STUDY_ROOT / "scripts/validate_selected_profile_catalog.py"
    )
    if selected_catalog_validation.get("builder_sha256") != sha256(
        selected_catalog_builder_path
    ):
        errors.append("Selected-profile catalog validation builder hash differs")
    if selected_catalog_validation.get("validator_sha256") != sha256(
        selected_catalog_validator_path
    ):
        errors.append("Selected-profile catalog validation validator hash differs")
    selected_catalog_summary = selected_catalog_validation.get("summary") or {}
    if selected_catalog_summary.get("confirmatory_outcomes_read") is not False:
        errors.append("Selected-profile catalog validation read confirmatory outcomes")
    if selected_catalog_summary.get("confirmatory_cases_executed") is not False:
        errors.append("Selected-profile catalog validation executed confirmatory cases")
    if selected_catalog_summary.get("implemented_generator_case_count") != 41:
        errors.append("Selected-profile mutation generator does not cover all 41 cases")

    selected_oracle_schema_errors = sorted(
        Draft202012Validator(selected_oracle_schema).iter_errors(selected_oracle),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(
        f"Selected-profile oracle schema: {error.message}"
        for error in selected_oracle_schema_errors
    )
    selected_oracle_rows = selected_oracle.get("rows") or []
    selected_oracle_by_key = {
        (row.get("case_id"), row.get("profile_id")): row
        for row in selected_oracle_rows
        if isinstance(row, dict)
    }
    expected_oracle_pairs = {
        (case_id, profile): (
            expectation.get("decision"),
            expectation.get("primary_reason"),
        )
        for case_id, case in selected_by_id.items()
        for profile, expectation in (case.get("profile_expectations") or {}).items()
    }
    observed_oracle_pairs = {
        key: (
            row.get("expected_decision"),
            row.get("expected_primary_reason"),
        )
        for key, row in selected_oracle_by_key.items()
    }
    if len(selected_oracle_rows) != 164 or len(selected_oracle_by_key) != 164:
        errors.append("Selected-profile oracle must contain 164 unique rows")
    if observed_oracle_pairs != expected_oracle_pairs:
        errors.append("Selected-profile oracle rows differ from catalog expectations")
    selected_oracle_source = selected_oracle.get("source_catalog") or {}
    if selected_oracle_source.get("sha256") != sha256(selected_catalog_path):
        errors.append("Selected-profile oracle catalog hash differs")
    selected_oracle_result_contract = selected_oracle.get("result_contract") or {}
    if selected_oracle_result_contract.get("sha256") != sha256(
        selected_fixture_result_schema_path
    ):
        errors.append("Selected-profile oracle result-schema hash differs")
    selected_oracle_boundary = selected_oracle.get("derivation_boundary") or {}
    for field in (
        "observed_results_read",
        "confirmatory_cases_read",
        "confirmatory_cases_executed",
        "target_decisions_used_as_profile_expectations",
        "implementation_behavior_used_to_generate_rows",
        "independent_human_review_complete",
    ):
        if selected_oracle_boundary.get(field) is not False:
            errors.append(f"Selected-profile oracle boundary differs: {field}")
    if selected_oracle_validation.get("valid") is not True:
        errors.append("Selected-profile oracle validation is not valid")
    if selected_oracle_validation.get("oracle_sha256") != sha256(selected_oracle_path):
        errors.append("Selected-profile oracle validation hash differs")
    if selected_oracle_validation.get("schema_sha256") != sha256(
        selected_oracle_schema_path
    ):
        errors.append("Selected-profile oracle-schema validation hash differs")
    selected_oracle_builder_path = STUDY_ROOT / "scripts/build_selected_profile_oracle.py"
    selected_oracle_validator_path = (
        STUDY_ROOT / "scripts/validate_selected_profile_oracle.py"
    )
    if selected_oracle_validation.get("builder_sha256") != sha256(
        selected_oracle_builder_path
    ):
        errors.append("Selected-profile oracle validation builder hash differs")
    if selected_oracle_validation.get("validator_sha256") != sha256(
        selected_oracle_validator_path
    ):
        errors.append("Selected-profile oracle validation validator hash differs")
    if selected_oracle_validation.get("confirmatory_outcomes_read") is not False:
        errors.append("Selected-profile oracle validation read confirmatory outcomes")
    if selected_oracle_validation.get("confirmatory_cases_executed") is not False:
        errors.append("Selected-profile oracle validation executed confirmatory cases")
    if selected_oracle_validation.get("independent_human_review_complete") is not False:
        errors.append("Selected-profile oracle incorrectly claims independent review")

    selected_development_schema_errors = sorted(
        Draft202012Validator(selected_development_schema).iter_errors(
            selected_development_record
        ),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(
        f"Selected-profile development record schema: {error.message}"
        for error in selected_development_schema_errors
    )
    if selected_development_validation.get("valid") is not True:
        errors.append("Selected-profile retained development check is not valid")
    if selected_development_validation.get("record_sha256") != sha256(
        selected_development_record_path
    ):
        errors.append("Selected-profile development-record validation hash differs")
    if selected_development_validation.get("schema_sha256") != sha256(
        selected_development_schema_path
    ):
        errors.append("Selected-profile development-schema validation hash differs")
    expected_development_counts = {
        "pytest_passed_count": 6,
        "catalog_case_count": 41,
        "oracle_row_count": 164,
        "development_case_profile_evaluations": 164,
    }
    for field, expected in expected_development_counts.items():
        if selected_development_validation.get(field) != expected:
            errors.append(f"Selected-profile development-check count differs: {field}")
    for field in (
        "confirmatory_evidence",
        "production_sigstore_conformance",
        "independent_oracle_review",
    ):
        if selected_development_validation.get(field) is not False:
            errors.append(f"Selected-profile development-check boundary differs: {field}")
    if (
        selected_development_validation.get(
            "source_inventory_unchanged_during_execution"
        )
        is not True
    ):
        errors.append("Selected-profile development pre/post source inventory differs")

    base_aware_schema_errors = sorted(
        Draft202012Validator(
            base_aware_schema, format_checker=FormatChecker()
        ).iter_errors(base_aware_record),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(
        f"Base-aware mutation development record schema: {error.message}"
        for error in base_aware_schema_errors
    )
    base_aware_validator_path = (
        STUDY_ROOT / "scripts/validate_base_aware_mutation_development_check.py"
    )
    if base_aware_validation.get("valid") is not True:
        errors.append("Base-aware mutation development validation is not valid")
    if base_aware_validation.get("record_sha256") != sha256(base_aware_record_path):
        errors.append("Base-aware mutation development record hash differs")
    if base_aware_validation.get("schema_sha256") != sha256(base_aware_schema_path):
        errors.append("Base-aware mutation development schema hash differs")
    if base_aware_validation.get("validator_sha256") != sha256(
        base_aware_validator_path
    ):
        errors.append("Base-aware mutation development validator hash differs")
    expected_base_aware_counts = {
        "passed_test_count": 4,
        "resolved_plan_count": 245,
        "unavailable_plan_count": 1,
    }
    for field, expected in expected_base_aware_counts.items():
        if base_aware_validation.get(field) != expected:
            errors.append(f"Base-aware mutation validation count differs: {field}")
    for field in (
        "confirmatory_evidence",
        "independent_review_performed",
        "manuscript_claims_authorized",
    ):
        if base_aware_validation.get(field) is not False:
            errors.append(f"Base-aware mutation validation boundary differs: {field}")
    base_aware_inventory = base_aware_record.get("source_inventory") or []
    inventory_paths = [
        item.get("path") for item in base_aware_inventory if isinstance(item, dict)
    ]
    if len(inventory_paths) != len(base_aware_inventory) or inventory_paths != sorted(
        inventory_paths, key=lambda value: str(value).encode("utf-8")
    ):
        errors.append("Base-aware mutation source inventory is malformed or unsorted")
    for item in base_aware_inventory:
        if not isinstance(item, dict):
            continue
        relative = item.get("path")
        path = STUDY_ROOT / str(relative)
        if not path.is_file() or path.is_symlink():
            errors.append(f"Base-aware mutation source is not a regular file: {relative}")
            continue
        raw = path.read_bytes()
        if item.get("bytes") != len(raw) or item.get("sha256") != hashlib.sha256(
            raw
        ).hexdigest():
            errors.append(f"Base-aware mutation source inventory differs: {relative}")
    base_aware_inventory_sha256 = hashlib.sha256(
        rfc8785.dumps(base_aware_inventory)
    ).hexdigest()
    if (
        base_aware_record.get("source_inventory_pre_sha256")
        != base_aware_inventory_sha256
        or base_aware_record.get("source_inventory_post_sha256")
        != base_aware_inventory_sha256
        or base_aware_record.get("source_inventory_unchanged_during_execution")
        is not True
    ):
        errors.append("Base-aware mutation pre/post source inventory binding differs")
    base_aware_execution = base_aware_record.get("execution") or {}
    for field in ("stdout", "stderr"):
        value = base_aware_execution.get(field)
        if not isinstance(value, str) or base_aware_execution.get(
            f"{field}_sha256"
        ) != hashlib.sha256(value.encode("utf-8")).hexdigest():
            errors.append(f"Base-aware mutation execution {field} hash differs")
    base_aware_coverage = base_aware_record.get("declared_coverage") or {}
    if base_aware_coverage != {
        "base_count": 6,
        "operator_count": 41,
        "base_operator_plan_count": 246,
        "resolved_plan_count": 245,
        "unavailable_plan_count": 1,
        "disposable_target_dependent_execution_count": 65,
        "policy_fixture_collision_tested": True,
        "forged_plan_rejection_tested": True,
    }:
        errors.append("Base-aware mutation declared coverage differs")
    if base_aware_record.get("unavailable_plans") != [
        {
            "base_id": "B04-SOFTWARE",
            "operator_id": "INVENTORY-OMIT-ROLE-001",
            "reason_code": "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
        }
    ]:
        errors.append("Base-aware mutation unavailable-plan identity differs")
    if any(
        value is not False
        for value in (base_aware_record.get("boundaries") or {}).values()
    ):
        errors.append("Base-aware mutation development record crosses a boundary")
    if base_aware_record.get("decision") != "NO-GO":
        errors.append("Base-aware mutation development record must remain NO-GO")
    if base_aware_record.get("manuscript_claims_authorized") is not False:
        errors.append("Base-aware mutation development record authorizes manuscript claims")

    proposition_scope = proposition_matrix.get("scope") or {}
    if set(proposition_scope.get("confirmatory_rqs") or []) != CONFIRMATORY_RQS:
        errors.append("Proposition matrix does not declare exactly RQ1-RQ5 as confirmatory")
    if set(proposition_scope.get("exploratory_rqs") or []) != EXPLORATORY_RQS:
        errors.append("Proposition matrix does not declare exactly E-RQ6 as exploratory")
    if set(proposition_scope.get("design_requirements") or []) != DESIGN_REQUIREMENTS:
        errors.append("Proposition matrix design-requirement set differs from D1-D6")
    if proposition_scope.get("no_population_inference") is not True:
        errors.append("Proposition matrix must prohibit population inference")
    if proposition_scope.get("profile_rows_are_paired") is not True:
        errors.append("Proposition matrix must declare profile rows as paired")

    missingness_contract = proposition_matrix.get("missingness_contract") or {}
    required_missingness = {
        "generation_failure",
        "missing_execution",
        "error_decision",
        "not_applicable",
    }
    if set(missingness_contract) != required_missingness:
        errors.append("Proposition matrix missingness contract is incomplete")
    denominator_contract = proposition_matrix.get("denominator_contract") or {}
    if denominator_contract.get("terminal_only_denominator_allowed") is not False:
        errors.append("Proposition matrix must forbid terminal-only denominators")
    if denominator_contract.get("category_partition") != [
        "ACCEPT",
        "REJECT",
        "ERROR",
        "MISSING_EXECUTION",
        "GENERATION_FAILURE",
    ]:
        errors.append("Proposition matrix category partition differs")
    if denominator_contract.get("category_counts_must_sum_to_planned_denominator") is not True:
        errors.append("Proposition matrix does not require category accounting")
    reporting_contract = proposition_matrix.get("reporting_decision_contract") or {}
    for field in (
        "positive_abstract_rule",
        "positive_conclusion_rule",
        "negative_or_incomplete_rule",
        "descriptive_rule",
    ):
        if not isinstance(reporting_contract.get(field), str) or not reporting_contract[field]:
            errors.append(f"Proposition reporting contract is missing {field}")
    if reporting_contract.get("hand_entered_result_numbers_allowed") is not False:
        errors.append("Proposition reporting contract must forbid hand-entered numbers")
    if reporting_contract.get("machine_generated_from_released_case_rows_required") is not True:
        errors.append("Proposition reporting contract must require machine-generated numbers")

    proposition_entries = proposition_matrix.get("propositions") or []
    if not isinstance(proposition_entries, list) or not proposition_entries:
        errors.append("Proposition matrix has no propositions")
        proposition_entries = []
    proposition_ids = [
        proposition.get("id")
        for proposition in proposition_entries
        if isinstance(proposition, dict)
    ]
    if len(proposition_ids) != len(set(proposition_ids)):
        errors.append("Duplicate proposition IDs")
    required_proposition_fields = {
        "id",
        "title",
        "claim_class",
        "rq_ids",
        "design_requirements",
        "strata",
        "applicable_units",
        "profiles",
        "observed_fields",
        "denominator_rule",
        "support_rule",
        "falsification_rule",
        "permitted_positive_wording",
        "required_negative_wording",
        "forbidden_extrapolations",
        "abstract_eligibility",
        "conclusion_eligibility",
    }
    covered_rqs: set[str] = set()
    covered_design_requirements: set[str] = set()
    for proposition in proposition_entries:
        if not isinstance(proposition, dict):
            errors.append("Proposition entries must be objects")
            continue
        proposition_id = str(proposition.get("id", "<missing-id>"))
        if not re.fullmatch(r"PR-\d{3}", proposition_id):
            errors.append(f"{proposition_id}: invalid proposition ID")
        missing_fields = required_proposition_fields - set(proposition)
        if missing_fields:
            errors.append(f"{proposition_id}: missing fields {sorted(missing_fields)}")
        rq_ids = set(proposition.get("rq_ids") or [])
        unknown_rqs = rq_ids - CONFIRMATORY_RQS - EXPLORATORY_RQS
        if unknown_rqs or not rq_ids:
            errors.append(f"{proposition_id}: invalid RQ set {sorted(rq_ids)}")
        covered_rqs.update(rq_ids)
        design_ids = set(proposition.get("design_requirements") or [])
        unknown_design = design_ids - DESIGN_REQUIREMENTS
        if unknown_design:
            errors.append(
                f"{proposition_id}: unknown design requirements {sorted(unknown_design)}"
            )
        if not rq_ids & EXPLORATORY_RQS:
            covered_design_requirements.update(design_ids)
        profiles = set(proposition.get("profiles") or [])
        if profiles - PROFILES:
            errors.append(f"{proposition_id}: unknown profiles {sorted(profiles - PROFILES)}")
        operators = set(proposition.get("operator_ids") or [])
        if operators - set(selected_case_ids):
            errors.append(
                f"{proposition_id}: unknown selected-profile operators "
                f"{sorted(operators - set(selected_case_ids))}"
            )
        if proposition_id == "PR-006" and operators != SELECTED_MIGRATED_OPERATOR_IDS:
            errors.append(
                "PR-006 operator set differs from the eleven selected semantic cases"
            )
        for list_field in ("strata", "observed_fields", "forbidden_extrapolations"):
            if not isinstance(proposition.get(list_field), list) or not proposition[list_field]:
                errors.append(f"{proposition_id}: {list_field} must be a non-empty list")
        for text_field in (
            "title",
            "claim_class",
            "applicable_units",
            "denominator_rule",
            "support_rule",
            "falsification_rule",
            "permitted_positive_wording",
            "required_negative_wording",
            "abstract_eligibility",
        ):
            value = proposition.get(text_field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{proposition_id}: {text_field} must be non-empty text")

    if not CONFIRMATORY_RQS.issubset(covered_rqs):
        errors.append(
            f"Proposition matrix does not cover RQs {sorted(CONFIRMATORY_RQS - covered_rqs)}"
        )
    if not EXPLORATORY_RQS.issubset(covered_rqs):
        errors.append("Proposition matrix does not cover E-RQ6")
    if covered_design_requirements != DESIGN_REQUIREMENTS:
        errors.append(
            "Proposition matrix does not cover design requirements: "
            f"{sorted(DESIGN_REQUIREMENTS - covered_design_requirements)}"
        )

    if base_registry.get("classification") != "R0_inputs_only_no_confirmatory_cases":
        errors.append("Base registry must be classified as R0 inputs only")
    generation_contract = base_registry.get("generation") or {}
    if generation_contract.get("derived_confirmatory_cases_generated_before_registration") is not False:
        errors.append("Base registry does not explicitly prohibit preregistration case generation")
    stratum_ids = {
        stratum.get("id")
        for stratum in base_registry.get("strata", [])
        if isinstance(stratum, dict)
    }
    if stratum_ids != {"S1-CONFORMANCE", "S2-PRODUCTION-SIGSTORE", "S3-INDEPENDENT-REPRODUCTION"}:
        errors.append("Base registry stratum set is incomplete")

    base_entries = base_registry.get("bases") or []
    if not isinstance(base_entries, list) or len(base_entries) < 3:
        errors.append("Base registry requires at least three structurally distinct bases")
        base_entries = []
    base_ids = [base.get("id") for base in base_entries if isinstance(base, dict)]
    if len(base_ids) != len(set(base_ids)):
        errors.append("Duplicate base-registry IDs")
    base_seeds = [base.get("seed") for base in base_entries if isinstance(base, dict)]
    if len(base_seeds) != len(set(base_seeds)):
        errors.append("Duplicate base-registry seeds")
    base_kinds: set[str] = set()
    unfrozen_base_hashes: list[str] = []
    allowed_recipe_types = {"empty", "utf8", "jcs_json", "sha256_counter", "minimal_pdf"}
    for base in base_entries:
        if not isinstance(base, dict):
            errors.append("Base-registry entries must be objects")
            continue
        base_id = str(base.get("id", "<missing-id>"))
        if not re.fullmatch(r"B\d{2}-[A-Z0-9-]+", base_id):
            errors.append(f"{base_id}: invalid base ID")
        if base.get("stratum") != "S1-CONFORMANCE":
            errors.append(f"{base_id}: generated draft base must be in S1-CONFORMANCE")
        if base.get("license_spdx") != "CC0-1.0" or base.get("third_party_bytes") is not False:
            errors.append(f"{base_id}: base license/third-party policy differs from draft contract")
        release = base.get("release") or {}
        release_kind = release.get("kind")
        if release_kind not in release_kinds:
            errors.append(f"{base_id}: unknown release kind {release_kind!r}")
        else:
            base_kinds.add(release_kind)
        payload_specs = base.get("payloads") or []
        paths = [entry.get("path") for entry in payload_specs if isinstance(entry, dict)]
        if len(paths) != len(payload_specs) or any(not isinstance(path, str) for path in paths):
            errors.append(f"{base_id}: invalid payload blueprint paths")
            paths = []
        elif paths != sorted(paths, key=lambda path: path.encode("utf-8")):
            errors.append(f"{base_id}: payload blueprints are not UTF-8 byte sorted")
        if len(paths) != len(set(paths)):
            errors.append(f"{base_id}: duplicate payload blueprint paths")
        roles = {
            entry.get("role")
            for entry in payload_specs
            if isinstance(entry, dict)
        }
        missing_roles = set(role_policy.get(release_kind, [])) - roles
        if missing_roles:
            errors.append(f"{base_id}: missing required roles {sorted(missing_roles)}")
        for entry in payload_specs:
            if not isinstance(entry, dict):
                continue
            recipe_type = (entry.get("recipe") or {}).get("type")
            if recipe_type not in allowed_recipe_types:
                errors.append(f"{base_id}/{entry.get('path')}: unknown recipe {recipe_type!r}")
        for target_name, target_path in (base.get("mutation_targets") or {}).items():
            if target_path not in paths:
                errors.append(f"{base_id}: mutation target {target_name} is not a payload path")
        for hash_field in (
            "expected_base_archive_sha256",
            "expected_manifest_sha256",
            "expected_tree_sha256",
        ):
            value = base.get(hash_field)
            if value is None:
                unfrozen_base_hashes.append(f"{base_id}.{hash_field}")
            elif not SHA256_HEX.fullmatch(str(value)):
                errors.append(f"{base_id}: {hash_field} is not SHA-256")
    if base_kinds != release_kinds:
        errors.append(
            "Base registry does not cover each manifest release kind exactly as a set: "
            f"missing={sorted(release_kinds - base_kinds)}"
        )

    prerequisite_entries = prerequisite_registry.get("prerequisites") or []
    prerequisite_ids = [
        entry.get("id") for entry in prerequisite_entries if isinstance(entry, dict)
    ]
    if len(prerequisite_ids) != len(set(prerequisite_ids)):
        errors.append("Duplicate prerequisite-registry IDs")
    catalog_prerequisites = {
        prerequisite
        for case in cases
        for prerequisite in (case.get("prerequisites") or [])
    }
    if set(prerequisite_ids) != catalog_prerequisites:
        errors.append(
            "Prerequisite registry differs from attack catalog: "
            f"missing={sorted(catalog_prerequisites - set(prerequisite_ids))}, "
            f"extra={sorted(set(prerequisite_ids) - catalog_prerequisites)}"
        )
    allowed_prerequisite_states = {"TRUE", "FALSE", "PENDING", "BASE_DERIVED"}
    if set(prerequisite_registry.get("allowed_states") or []) != allowed_prerequisite_states:
        errors.append("Prerequisite registry state vocabulary is incomplete")
    for entry in prerequisite_entries:
        if not isinstance(entry, dict):
            errors.append("Prerequisite registry entries must be objects")
            continue
        if entry.get("draft_state") not in allowed_prerequisite_states:
            errors.append(f"{entry.get('id')}: unknown prerequisite state")

    selected_prerequisite_entries = (
        selected_prerequisite_registry.get("prerequisites") or []
    )
    selected_prerequisite_ids = [
        entry.get("id")
        for entry in selected_prerequisite_entries
        if isinstance(entry, dict)
    ]
    if len(selected_prerequisite_ids) != len(selected_prerequisite_entries) or len(
        selected_prerequisite_ids
    ) != len(set(selected_prerequisite_ids)):
        errors.append("Selected prerequisite registry has duplicate or malformed IDs")
    selected_catalog_prerequisites = {
        prerequisite
        for case in selected_cases
        for prerequisite in (case.get("prerequisites") or [])
    }
    if set(selected_prerequisite_ids) != selected_catalog_prerequisites:
        errors.append(
            "Selected prerequisite registry differs from selected catalog: "
            f"missing={sorted(selected_catalog_prerequisites - set(selected_prerequisite_ids))}, "
            f"extra={sorted(set(selected_prerequisite_ids) - selected_catalog_prerequisites)}"
        )
    if len(selected_prerequisite_ids) != 30:
        errors.append("Selected prerequisite registry must contain exactly 30 entries")
    for entry in selected_prerequisite_entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("draft_state") not in allowed_prerequisite_states:
            errors.append(f"{entry.get('id')}: invalid selected prerequisite state")
    selected_pending_prerequisite_ids = {
        entry.get("id")
        for entry in selected_prerequisite_entries
        if isinstance(entry, dict) and entry.get("draft_state") == "PENDING"
    }
    if selected_pending_prerequisite_ids != {
        "dirty_build_field_or_invariant_frozen",
        "manifest_size_limit_frozen",
        "required_material_policy_frozen",
        "selected_manifest_metadata_policy_frozen",
        "source_revision_policy_frozen",
    }:
        errors.append("Selected pending-prerequisite set differs from the reviewed draft")

    planned_environment_entries = base_registry.get("planned_environments") or []
    planned_environments = {
        entry.get("id"): entry
        for entry in planned_environment_entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    if len(planned_environments) != len(planned_environment_entries):
        errors.append("Base registry has invalid or duplicate planned environment IDs")

    probe_contract = prerequisite_registry.get("environment_probe_contract") or {}
    if (
        selected_prerequisite_registry.get("environment_probe_contract") or {}
    ) != probe_contract:
        errors.append("Selected prerequisite environment-probe contract differs historically")
    probe_script_relative = probe_contract.get("script_path")
    probe_script_path: Path | None = None
    study_root_resolved = STUDY_ROOT.resolve()
    if not isinstance(probe_script_relative, str):
        errors.append("Environment-probe contract has no script path")
    else:
        relative = Path(probe_script_relative)
        candidate = (STUDY_ROOT / relative).resolve()
        try:
            candidate.relative_to(study_root_resolved)
        except ValueError:
            errors.append("Environment-probe script path escapes the study root")
        else:
            if relative.is_absolute() or ".." in relative.parts:
                errors.append("Environment-probe script path is not a safe relative path")
            elif not candidate.is_file():
                errors.append("Environment-probe script does not exist")
            else:
                probe_script_path = candidate
                if probe_contract.get("script_sha256") != sha256(candidate):
                    errors.append("Environment-probe script SHA-256 differs from its contract")

    probe_record_entries = probe_contract.get("records") or []
    probe_environment_ids = [
        record.get("environment_id")
        for record in probe_record_entries
        if isinstance(record, dict)
    ]
    if len(probe_environment_ids) != len(set(probe_environment_ids)):
        errors.append("Environment-probe contract has duplicate environment IDs")
    if set(probe_environment_ids) != set(planned_environments):
        errors.append(
            "Environment-probe records do not cover exactly the planned environments"
        )

    environment_probe_paths: list[Path] = []
    environment_probe_records: dict[str, dict[str, Any]] = {}
    contracted_probe_relative_paths: list[str] = []
    for record_contract in probe_record_entries:
        if not isinstance(record_contract, dict):
            errors.append("Environment-probe record contracts must be objects")
            continue
        environment_id = record_contract.get("environment_id")
        relative_value = record_contract.get("path")
        if not isinstance(relative_value, str):
            errors.append(f"{environment_id}: environment-probe path is missing")
            continue
        relative = Path(relative_value)
        candidate = (STUDY_ROOT / relative).resolve()
        try:
            candidate.relative_to(study_root_resolved)
        except ValueError:
            errors.append(f"{environment_id}: environment-probe path escapes study root")
            continue
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"{environment_id}: environment-probe path is unsafe")
            continue
        if not candidate.is_file():
            errors.append(f"{environment_id}: environment-probe record does not exist")
            continue
        environment_probe_paths.append(candidate)
        contracted_probe_relative_paths.append(relative_value)
        if not SHA256_HEX.fullmatch(str(record_contract.get("sha256", ""))):
            errors.append(f"{environment_id}: environment-probe SHA-256 is malformed")
        elif record_contract["sha256"] != sha256(candidate):
            errors.append(f"{environment_id}: environment-probe SHA-256 mismatch")
        try:
            probe = strict_json_loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(
                f"{environment_id}: environment-probe record cannot be parsed: "
                f"{type(exc).__name__}"
            )
            continue
        if probe.get("schema_version") != "amy.filesystem-capability-probe.v1":
            errors.append(f"{environment_id}: unexpected environment-probe schema")
        if probe.get("classification") != "R0_environment_compatibility_evidence":
            errors.append(f"{environment_id}: unexpected environment-probe classification")
        if probe.get("environment_id") != environment_id:
            errors.append(f"{environment_id}: environment-probe identity mismatch")
        if probe.get("network_required_by_probe") is not False:
            errors.append(f"{environment_id}: environment probe must not require network")
        if probe.get("all_required_supported") is not True:
            errors.append(f"{environment_id}: not every required capability passed")

        planned = planned_environments.get(environment_id) or {}
        if probe.get("expected_image") != planned.get("image"):
            errors.append(f"{environment_id}: probed image differs from base registry")
        if planned.get("platform") == "linux/amd64":
            runtime = probe.get("runtime") or {}
            if runtime.get("system") != "Linux" or runtime.get("machine") not in {
                "x86_64",
                "amd64",
            }:
                errors.append(f"{environment_id}: runtime does not match linux/amd64")

        capabilities = probe.get("capabilities") or {}
        details = probe.get("probe_details") or {}
        for capability in planned.get("required_capabilities") or []:
            if capability in {"regular_files", "symlink", "hardlink", "fifo"}:
                supported = (details.get(capability) or {}).get("supported")
            else:
                supported = capabilities.get(capability)
            if supported is not True:
                errors.append(
                    f"{environment_id}: required capability did not pass: {capability}"
                )
        environment_probe_records[str(environment_id)] = probe

    filesystem_prerequisites = {
        "filesystem_supports_fifo",
        "filesystem_supports_hardlink",
        "filesystem_supports_symlink",
    }
    contracted_path_set = set(contracted_probe_relative_paths)
    prerequisite_by_id = {
        entry.get("id"): entry
        for entry in prerequisite_entries
        if isinstance(entry, dict)
    }
    for prerequisite_id in filesystem_prerequisites:
        entry = prerequisite_by_id.get(prerequisite_id) or {}
        if entry.get("source") != "required_environment_probes":
            errors.append(f"{prerequisite_id}: source is not required environment probes")
        if entry.get("draft_state") != "TRUE":
            errors.append(f"{prerequisite_id}: state is not TRUE after passing probes")
        if set(entry.get("evidence_paths") or []) != contracted_path_set:
            errors.append(f"{prerequisite_id}: evidence paths differ from probe contract")
        for environment_id, probe in environment_probe_records.items():
            if (probe.get("capabilities") or {}).get(prerequisite_id) is not True:
                errors.append(
                    f"{prerequisite_id}: capability is not true in {environment_id}"
                )
    forbidden_compatibility_inputs = {
        "profile_expectations",
        "observed_decision",
        "target_decision",
    }
    if set(
        (prerequisite_registry.get("compatibility_rule") or {}).get("forbidden_inputs")
        or []
    ) != forbidden_compatibility_inputs:
        errors.append("Prerequisite registry does not forbid all outcome-derived inputs")

    base_run_validation_path = (
        STUDY_ROOT / "base_pilot_runs/r0_bases_20260713T065228Z/validation.json"
    )
    expected_compatibility_hashes = {
        "base_registry": sha256(base_registry_path),
        "prerequisite_registry": sha256(prerequisite_path),
        "attack_catalog": sha256(catalog_path),
        "base_run_validation": sha256(base_run_validation_path),
    }
    if compatibility_matrix.get("input_sha256") != expected_compatibility_hashes:
        errors.append("Compatibility matrix input hashes differ from current contracts")
    if compatibility_matrix.get("classification") != (
        "R0_metadata_only_no_case_generation_or_execution"
    ):
        errors.append("Compatibility matrix is not classified as R0 metadata only")
    for flag in (
        "uses_profile_expectations",
        "uses_observed_decisions",
        "uses_target_decisions",
    ):
        if compatibility_matrix.get(flag) is not False:
            errors.append(f"Compatibility matrix outcome-blinding flag is not false: {flag}")
    compatibility_rows = compatibility_matrix.get("rows") or []
    expected_pairs = [
        (base_id, case_id)
        for base_id in sorted(base_ids, key=lambda value: str(value).encode("ascii"))
        for case_id in sorted(case_ids, key=lambda value: str(value).encode("ascii"))
    ]
    observed_pairs = [
        (row.get("base_id"), row.get("operator_id"))
        for row in compatibility_rows
        if isinstance(row, dict)
    ]
    if observed_pairs != expected_pairs:
        errors.append("Compatibility matrix is not the complete sorted base × operator product")
    forbidden_row_keys = forbidden_compatibility_inputs | {
        "expected_decision",
        "expected_primary_reason",
    }
    if any(forbidden_row_keys & set(row) for row in compatibility_rows if isinstance(row, dict)):
        errors.append("Compatibility matrix contains outcome or expectation fields")
    compatibility_state_counts = {
        state: sum(
            1
            for row in compatibility_rows
            if isinstance(row, dict) and row.get("compatibility") == state
        )
        for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
    }
    if compatibility_matrix.get("candidate_unit_count") != len(expected_pairs):
        errors.append("Compatibility matrix candidate count differs from Cartesian product")
    if compatibility_matrix.get("compatibility_counts") != compatibility_state_counts:
        errors.append("Compatibility matrix summary counts differ from rows")
    pending_compatibility_count = compatibility_state_counts["PENDING"]

    if set(
        (
            (selected_prerequisite_registry.get("compatibility_rule") or {}).get(
                "forbidden_inputs"
            )
            or []
        )
    ) != forbidden_compatibility_inputs:
        errors.append(
            "Selected prerequisite registry does not forbid all outcome-derived inputs"
        )
    expected_selected_compatibility_hashes = {
        "base_registry": sha256(base_registry_path),
        "prerequisite_registry": sha256(selected_prerequisite_path),
        "attack_catalog": sha256(selected_catalog_path),
        "selected_base_run_summary": sha256(selected_base_summary_path),
        "selected_base_run_validation": sha256(selected_base_validation_path),
        "selected_effective_fixture_policy": sha256(selected_effective_policy_path),
        "selected_profile_mutation_generator": sha256(
            STUDY_ROOT / "amy_verifier/selected_profile_mutations.py"
        ),
    }
    if selected_compatibility_matrix.get("input_sha256") != (
        expected_selected_compatibility_hashes
    ):
        errors.append("Selected compatibility input hashes differ from current contracts")
    if selected_compatibility_matrix.get("classification") != (
        "R0_metadata_only_no_case_generation_or_execution"
    ):
        errors.append("Selected compatibility is not classified as R0 metadata only")
    selected_matrix_flags = {
        "uses_profile_expectations": False,
        "uses_target_decisions": False,
        "uses_confirmatory_mutation_outcomes": False,
        "uses_observed_clean_base_validation": True,
        "uses_base_aware_mutation_plan_resolution": True,
        "mutation_plan_resolution_uses_outcomes": False,
    }
    for flag, expected in selected_matrix_flags.items():
        if selected_compatibility_matrix.get(flag) is not expected:
            errors.append(f"Selected compatibility evidence-use flag differs: {flag}")
    selected_compatibility_rows = selected_compatibility_matrix.get("rows") or []
    expected_selected_pairs = [
        (base_id, case_id)
        for base_id in sorted(base_ids, key=lambda value: str(value).encode("ascii"))
        for case_id in sorted(
            selected_case_ids, key=lambda value: str(value).encode("ascii")
        )
    ]
    observed_selected_pairs = [
        (row.get("base_id"), row.get("operator_id"))
        for row in selected_compatibility_rows
        if isinstance(row, dict)
    ]
    if observed_selected_pairs != expected_selected_pairs:
        errors.append(
            "Selected compatibility is not the complete sorted base × operator product"
        )
    selected_forbidden_row_keys = forbidden_row_keys | {
        "observed_result",
    }
    if any(
        selected_forbidden_row_keys & set(row)
        for row in selected_compatibility_rows
        if isinstance(row, dict)
    ):
        errors.append("Selected compatibility contains outcome or expectation fields")
    selected_compatibility_state_counts = {
        state: sum(
            1
            for row in selected_compatibility_rows
            if isinstance(row, dict) and row.get("compatibility") == state
        )
        for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
    }
    if selected_compatibility_matrix.get("candidate_unit_count") != len(
        expected_selected_pairs
    ):
        errors.append("Selected compatibility candidate count differs from product")
    if selected_compatibility_matrix.get("compatibility_counts") != (
        selected_compatibility_state_counts
    ):
        errors.append("Selected compatibility summary counts differ from rows")
    selected_plan_state_counts = {
        state: sum(
            1
            for row in selected_compatibility_rows
            if isinstance(row, dict)
            and isinstance(row.get("mutation_plan"), dict)
            and row["mutation_plan"].get("status") == state
        )
        for state in ("RESOLVED", "UNAVAILABLE")
    }
    if selected_plan_state_counts != {"RESOLVED": 245, "UNAVAILABLE": 1}:
        errors.append("Selected mutation-plan counts differ from current resolution")
    if selected_compatibility_matrix.get("mutation_plan_counts") != (
        selected_plan_state_counts
    ):
        errors.append("Selected mutation-plan summary counts differ from rows")
    if selected_compatibility_validation.get("mutation_plan_counts") != (
        selected_plan_state_counts
    ):
        errors.append("Selected mutation-plan validation counts differ from rows")
    if selected_compatibility_state_counts != {
        "COMPATIBLE": 185,
        "PENDING": 54,
        "NOT_COMPATIBLE": 7,
    }:
        errors.append("Selected compatibility state counts differ from reviewed draft")
    unavailable_plan_rows = [
        row
        for row in selected_compatibility_rows
        if isinstance(row, dict)
        and (row.get("mutation_plan") or {}).get("status") == "UNAVAILABLE"
    ]
    if len(unavailable_plan_rows) != 1:
        errors.append("Selected compatibility must contain exactly one unavailable plan")
    else:
        unavailable_row = unavailable_plan_rows[0]
        if (
            unavailable_row.get("unit_id")
            != "B04-SOFTWARE--INVENTORY-OMIT-ROLE-001"
            or unavailable_row.get("compatibility") != "NOT_COMPATIBLE"
            or unavailable_row.get("blocking_false")
            != ["required_role_has_exactly_one_payload"]
            or unavailable_row.get("generator_blocking_reason")
            != "TARGET_REQUIRED_ROLE_NOT_UNIQUE"
            or unavailable_row.get("mutation_plan")
            != {
                "status": "UNAVAILABLE",
                "reason_code": "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
                "plan": None,
                "plan_sha256": None,
            }
        ):
            errors.append("Selected compatibility unavailable-plan row differs")
    selected_pending_compatibility_count = selected_compatibility_state_counts[
        "PENDING"
    ]
    if run_policy_validation.get("pending_compatibility_row_count") != (
        selected_pending_compatibility_count
    ):
        errors.append("Run-policy pending-row count differs from selected compatibility")
    if selected_compatibility_validation.get("valid") is not True:
        errors.append("Selected compatibility validation is not valid")
    if selected_compatibility_validation.get("matrix_sha256") != sha256(
        selected_compatibility_path
    ):
        errors.append("Selected compatibility validation hash differs")
    for true_field in (
        "outcome_blinded",
        "counterfactual_outcome_fields_invariant",
        "deterministic_replay_identical",
        "selected_base_run_separate_validator_valid",
    ):
        if selected_compatibility_validation.get(true_field) is not True:
            errors.append(f"Selected compatibility validation flag is not true: {true_field}")
    for false_field in ("confirmatory_cases_generated", "confirmatory_outcomes_read"):
        if selected_compatibility_validation.get(false_field) is not False:
            errors.append(
                f"Selected compatibility validation boundary is not false: {false_field}"
            )

    review_catalog_keys = set(review_record_template.get("catalog_case_decisions") or {})
    expected_review_catalog_keys = set(selected_case_ids)
    if review_catalog_keys != expected_review_catalog_keys:
        errors.append("R0 human-review template catalog coverage differs from 41 cases")
    review_oracle_keys = set(review_record_template.get("oracle_row_decisions") or {})
    expected_review_oracle_keys = {
        f"{row.get('case_id')}::{row.get('profile_id')}"
        for row in selected_oracle_rows
        if isinstance(row, dict)
    }
    if review_oracle_keys != expected_review_oracle_keys:
        errors.append("R0 human-review template oracle coverage differs from 164 rows")
    review_proposition_keys = set(
        review_record_template.get("proposition_decisions") or {}
    )
    expected_review_proposition_keys = {
        proposition.get("id")
        for proposition in proposition_entries
        if isinstance(proposition, dict)
    }
    if review_proposition_keys != expected_review_proposition_keys:
        errors.append("R0 human-review template proposition coverage differs")
    review_compatibility = review_record_template.get(
        "compatibility_policy_decisions"
    ) or {}
    review_matrix_keys = set(review_compatibility.get("matrix_row_decisions") or {})
    expected_review_matrix_keys = {
        row.get("unit_id")
        for row in selected_compatibility_rows
        if isinstance(row, dict)
    }
    if review_matrix_keys != expected_review_matrix_keys:
        errors.append("R0 human-review template compatibility coverage differs")
    expected_review_policy_keys = {
        "clean_base_evidence_boundary",
        "finite_designed_denominator",
        "outcome_blindness",
        "pending_rows_excluded_until_resolved",
        "post_execution_reclassification_forbidden",
        "s1_s2_stratum_assignment",
        "structural_prerequisites_only",
    }
    if set(review_compatibility.get("policy_decisions") or {}) != (
        expected_review_policy_keys
    ):
        errors.append("R0 human-review template policy coverage differs")
    if (
        review_record_template.get("record_status") != "template_unreviewed"
        or review_record_template.get("independent_human_review_occurred") is not False
        or review_record_template.get("reviewer") is not None
        or review_record_template.get("overall_decision") != "NOT_REVIEWED"
    ):
        errors.append("R0 human-review template overstates review status")
    if selected_base_validation.get("valid") is not True:
        errors.append("Selected clean-base validation is not valid")
    if selected_base_validation.get("base_count") != 6:
        errors.append("Selected clean-base validation count differs from six")
    selected_clean_results = [
        result
        for record in selected_base_validation.get("validated_bases", [])
        if isinstance(record, dict)
        for result in (record.get("clean_profile_results") or {}).values()
    ]
    if len(selected_clean_results) != 24 or any(
        result != {"decision": "ACCEPT", "primary_reason": "OK"}
        for result in selected_clean_results
    ):
        errors.append("Selected clean-base validation is not exactly 24 ACCEPT/OK rows")
    if selected_base_validation.get("confirmatory_cases_generated") is not False:
        errors.append("Selected clean-base run generated confirmatory cases")
    if selected_base_validation.get("confirmatory_outcomes_read") is not False:
        errors.append("Selected clean-base run read confirmatory outcomes")
    if selected_base_validation.get("production_sigstore_conformance") is not False:
        errors.append("Selected clean-base fixture is mislabeled as production Sigstore")
    if selected_base_comparison.get("valid") is not True:
        errors.append("Selected clean-base retained-run comparison is not valid")
    if selected_base_comparison.get(
        "base_archive_and_result_inventories_identical"
    ) is not True:
        errors.append("Selected clean-base retained-run outputs differ")
    if (selected_base_comparison.get("source_archive_sha256") or {}).get(
        "identical"
    ) is not False:
        errors.append("Selected terminology rerun did not retain distinct source archives")
    if selected_base_current_replay.get("valid") is not True:
        errors.append("Selected clean-base current replay is not valid")
    if selected_base_current_replay.get("retained_source_archive_self_valid") is not True:
        errors.append("Selected retained source archive is not internally valid")
    if selected_base_current_replay.get("retained_source_matches_current_study") is not False:
        errors.append("Selected current replay does not disclose post-run source drift")
    expected_selected_source_drift = {
        "amy_verifier/github_attestation.py",
        "amy_verifier/selected_profile_fixture.py",
        "scripts/validate_selected_profile_base_run.py",
    }
    if set(selected_base_current_replay.get("retained_source_drift_paths") or []) != (
        expected_selected_source_drift
    ):
        errors.append("Selected current replay source-drift path set differs")
    if selected_base_current_replay.get("confirmatory_cases_generated") is not False:
        errors.append("Selected current replay generated confirmatory cases")
    if selected_base_current_replay.get("confirmatory_outcomes_read") is not False:
        errors.append("Selected current replay read confirmatory outcomes")
    selected_fixture_boundary = (
        (selected_effective_policy.get("fixture_overlay") or {}).get(
            "cryptographic_boundary"
        )
        or {}
    )
    if selected_fixture_boundary.get("production_sigstore_conformance") is not False:
        errors.append("Selected effective fixture policy is mislabeled as production Sigstore")
    if any(
        "TBD-BEFORE-REGISTRATION" in value
        for _, value in walk_strings(selected_effective_policy)
    ):
        errors.append("Selected effective controlled fixture retains production TBD values")
    selected_implementation_state = attestation_decision.get("implementation_state") or {}
    expected_production_contract_paths = {
        "historical_v1_result_schema": "schemas/github-production-verification-result.schema.json",
        "historical_v1_policy_template": "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json",
        "historical_v1_cli": "scripts/verify_github_attestation.py",
        "historical_v1_cryptographic_core": "amy_verifier/github_attestation.py",
        "production_policy_schema": "schemas/github-attestation-policy-v2.schema.json",
        "production_result_schema": "schemas/github-production-verification-result-v2.schema.json",
        "production_policy_template": "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json",
        "production_cryptographic_core": "amy_verifier/github_attestation_v2_core.py",
        "production_adapter": "amy_verifier/github_attestation_v2.py",
        "production_cli": "scripts/verify_github_attestation_v2.py",
    }
    for field, expected in expected_production_contract_paths.items():
        if selected_implementation_state.get(field) != expected:
            errors.append(f"Attestation decision production path differs: {field}")
    for field in (
        "production_output_schema_complete",
        "production_policy_schema_closed",
        "production_policy_external_sha_required",
        "production_api_evidence_contract_identity_complete",
        "production_api_accept_schema_validation_complete",
        "historical_v1_bytes_preserved",
    ):
        if selected_implementation_state.get(field) is not True:
            errors.append(f"Attestation decision v2 contract flag is not true: {field}")
    expected_selected_state = {
        "selected_fixture_semantic_cases_implemented": True,
        "selected_fixture_snapshot_is_valid_deterministic_ustar": True,
        "selected_clean_base_migration_complete": True,
        "selected_clean_base_count": 6,
        "selected_clean_profile_result_count": 24,
        "selected_catalog_migration_complete": True,
        "selected_catalog_case_count": 41,
        "selected_compatibility_matrix_complete": True,
        "selected_compatibility_candidate_unit_count": 246,
        "full_41_case_generator_migration_complete": True,
        "pilot_profile_migration_complete": False,
    }
    for field, expected in expected_selected_state.items():
        if selected_implementation_state.get(field) != expected:
            errors.append(f"Attestation decision selected migration state differs: {field}")

    claim_matrix_path = STUDY_ROOT / "evidence/CLAIM_EVIDENCE_MATRIX.csv"
    claim_validator_path = STUDY_ROOT / "scripts/validate_claim_evidence_matrix.py"
    claim_test_path = STUDY_ROOT / "tests/test_claim_evidence_matrix.py"
    claim_spec = importlib.util.spec_from_file_location(
        "validate_claim_evidence_matrix_for_protocol", claim_validator_path
    )
    if claim_spec is None or claim_spec.loader is None:
        errors.append("Claim-evidence validator cannot be imported")
        claim_validation: dict[str, Any] = {"valid": False}
    else:
        claim_module = importlib.util.module_from_spec(claim_spec)
        claim_spec.loader.exec_module(claim_module)
        claim_validation = claim_module.validate_claim_evidence_matrix(
            claim_matrix_path, study_root=STUDY_ROOT
        )
        if claim_validation.get("valid") is not True:
            errors.append("Claim-evidence matrix validation is not valid")
        if claim_validation.get("claim_count") != 47:
            errors.append("Claim-evidence matrix count differs from 47")
        if claim_validation.get("allowed_claim_count") != 40:
            errors.append("Claim-evidence allowed count differs from 40")
        if claim_validation.get("resolved_reference_count") != 70:
            errors.append("Claim-evidence reference count differs from 70")
        claim_boundaries = claim_validation.get("boundaries") or {}
        if claim_boundaries.get("scientific_claims_authorized_by_validator") is not False:
            errors.append("Claim-evidence validator exceeds its authorization boundary")

    with claim_matrix_path.open(
        encoding="utf-8", newline=""
    ) as handle:
        claim_rows = list(csv.DictReader(handle))
    claim_ids = [row.get("claim_id") for row in claim_rows]
    if len(claim_ids) != len(set(claim_ids)):
        errors.append("Duplicate claim IDs")
    if any(row.get("allowed_now") not in {"yes", "no"} for row in claim_rows):
        errors.append("Claim ledger allowed_now must be yes/no")

    source_text = (STUDY_ROOT / "evidence/SOURCE_LEDGER.md").read_text(encoding="utf-8")
    source_ids = re.findall(r"^\| (S\d+) \|", source_text, flags=re.MULTILINE)
    if len(source_ids) != len(set(source_ids)):
        errors.append("Duplicate source-ledger IDs")

    declared_gate_statuses = set(registration_gates.get("allowed_statuses") or [])
    if declared_gate_statuses != GATE_STATUSES:
        errors.append(
            f"Registration-gate statuses {sorted(declared_gate_statuses)} != "
            f"{sorted(GATE_STATUSES)}"
        )
    gate_entries = registration_gates.get("gates") or []
    if not isinstance(gate_entries, list) or not gate_entries:
        errors.append("Registration-gate registry has no gates")
        gate_entries = []
    gate_ids = [gate.get("id") for gate in gate_entries if isinstance(gate, dict)]
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("Duplicate registration-gate IDs")

    open_blocking_gate_ids: list[str] = []
    for gate in gate_entries:
        if not isinstance(gate, dict):
            errors.append("Registration-gate entries must be objects")
            continue
        gate_id = str(gate.get("id", "<missing-id>"))
        gate_status = gate.get("status")
        blocks_registration = gate.get("blocks_registration")
        evidence_paths = gate.get("evidence")
        if not re.fullmatch(r"RG-\d{3}", gate_id):
            errors.append(f"{gate_id}: invalid registration-gate ID")
        if gate_status not in GATE_STATUSES:
            errors.append(f"{gate_id}: invalid status {gate_status!r}")
        if not isinstance(blocks_registration, bool):
            errors.append(f"{gate_id}: blocks_registration must be boolean")
        if not isinstance(gate.get("requirement"), str) or not gate["requirement"].strip():
            errors.append(f"{gate_id}: requirement must be non-empty text")
        if not isinstance(evidence_paths, list):
            errors.append(f"{gate_id}: evidence must be a list")
            evidence_paths = []
        if gate_status == "complete" and not evidence_paths:
            errors.append(f"{gate_id}: a complete gate must cite retained evidence")
        for evidence_path in evidence_paths:
            if not isinstance(evidence_path, str) or not evidence_path.strip():
                errors.append(f"{gate_id}: evidence paths must be non-empty strings")
                continue
            relative_path = Path(evidence_path)
            candidate = (STUDY_ROOT / relative_path).resolve()
            try:
                candidate.relative_to(study_root_resolved)
            except ValueError:
                errors.append(f"{gate_id}: evidence path escapes the study root: {evidence_path}")
                continue
            if relative_path.is_absolute() or ".." in relative_path.parts:
                errors.append(f"{gate_id}: evidence path is not a safe relative path: {evidence_path}")
            elif not candidate.exists():
                errors.append(f"{gate_id}: evidence path does not exist: {evidence_path}")
        if blocks_registration is True and gate_status != "complete":
            open_blocking_gate_ids.append(gate_id)

    computed_gate_status = "no_go" if open_blocking_gate_ids else "ready"
    if registration_gates.get("status") != computed_gate_status:
        errors.append(
            "Registration-gate top-level status disagrees with blocking gate states: "
            f"expected {computed_gate_status!r}"
        )

    Draft202012Validator.check_schema(model_review_protocol_schema)
    Draft202012Validator.check_schema(model_review_response_schema)
    errors.extend(
        f"Model-review protocol schema: {error.message}"
        for error in Draft202012Validator(model_review_protocol_schema).iter_errors(
            model_review_protocol
        )
    )
    model_review_specification = importlib.util.spec_from_file_location(
        "bound_model_review_runner", model_review_runner_path
    )
    if model_review_specification is None or model_review_specification.loader is None:
        errors.append("Model-review runner cannot be loaded")
        model_review_preparation = {}
    else:
        model_review_module = importlib.util.module_from_spec(model_review_specification)
        model_review_specification.loader.exec_module(model_review_module)
        try:
            model_review_preparation = model_review_module.validate_only()
        except Exception as exc:
            errors.append(
                f"Model-review protocol preparation failed: {type(exc).__name__}: {exc}"
            )
            model_review_preparation = {}
    if model_review_preparation.get("valid") is not True:
        errors.append("Model-review protocol preparation is not valid")
    if model_review_preparation.get("slot_count") != 10:
        errors.append("Model-review protocol does not prepare exactly ten slots")
    if model_review_preparation.get("union_source_count") != 49:
        errors.append("Model-review protocol source-union count differs")
    if model_review_preparation.get("network_used") is not False:
        errors.append("Model-review static preparation unexpectedly used network")
    Draft202012Validator.check_schema(pre_r0_closure_schema)
    Draft202012Validator.check_schema(pre_r0_closure_validation_schema)
    errors.extend(
        f"Pre-R0 closure ledger schema: {error.message}"
        for error in Draft202012Validator(pre_r0_closure_schema).iter_errors(
            pre_r0_closure_ledger
        )
    )
    errors.extend(
        f"Pre-R0 closure validation schema: {error.message}"
        for error in Draft202012Validator(
            pre_r0_closure_validation_schema
        ).iter_errors(pre_r0_closure_validation)
    )
    closure_ids = [
        item.get("gate_id")
        for item in (pre_r0_closure_ledger.get("controls") or [])
        if isinstance(item, dict)
    ]
    if closure_ids != open_blocking_gate_ids:
        errors.append("Pre-R0 closure-ledger blocker IDs differ from registration gates")
    closure_summary = pre_r0_closure_ledger.get("summary") or {}
    if closure_summary.get("registration_blocker_count") != len(open_blocking_gate_ids):
        errors.append("Pre-R0 closure-ledger blocker count differs")
    if pre_r0_closure_validation.get("valid") is not True:
        errors.append("Pre-R0 closure-ledger retained validation is not valid")
    if pre_r0_closure_validation.get("decision") != "NO-GO":
        errors.append("Pre-R0 closure-ledger validation must remain NO-GO")
    if pre_r0_closure_validation.get("registration_blocker_ids") != open_blocking_gate_ids:
        errors.append("Pre-R0 closure validation blocker IDs differ")
    closure_hash_bindings = {
        "ledger_sha256": sha256(pre_r0_closure_ledger_path),
        "schema_sha256": sha256(pre_r0_closure_schema_path),
        "validator_sha256": sha256(pre_r0_closure_validator_path),
    }
    for field, expected in closure_hash_bindings.items():
        if pre_r0_closure_validation.get(field) != expected:
            errors.append(f"Pre-R0 closure validation hash differs: {field}")

    readiness_paths = [
        STUDY_ROOT / "README.md",
        STUDY_ROOT / "protocol/PROTOCOL_DRAFT.md",
        STUDY_ROOT / "protocol/THREAT_MODEL.md",
        STUDY_ROOT / "protocol/VERSIONING_AND_SIGNING_POLICY.md",
        STUDY_ROOT / "protocol/PATH_POLICY_DRAFT.md",
        STUDY_ROOT / "protocol/ATTACK_CATALOG.json",
        selected_catalog_path,
        selected_oracle_path,
        robustness_catalog_path,
        STUDY_ROOT / "protocol/REASON_CODES.json",
        production_reasons_path,
        STUDY_ROOT / "protocol/TRUST_POLICY_DRAFT.json",
        production_policy_path,
        production_policy_schema_path,
        production_result_schema_path,
        STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
        attestation_decision_path,
        upstream_attestation_audit_path,
        registration_gates_path,
        model_review_protocol_path,
        pre_r0_closure_ledger_path,
        pre_r0_closure_validation_path,
        lineage_contract_path,
        proposition_path,
        run_policy_path,
        run_policy_validation_path,
        STUDY_ROOT / "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
        rg006_test_record_path,
        review_record_template_path,
        reviewer_identity_policy_path,
        reviewer_identity_validation_path,
        STUDY_ROOT / "reviews/R0_REVIEW_PACKET_DRAFT.md",
        STUDY_ROOT / "dummy_analysis/DUMMY_OBSERVATION_LEDGER.json",
        STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json",
        base_registry_path,
        prerequisite_path,
        selected_prerequisite_path,
        compatibility_path,
        selected_compatibility_path,
        STUDY_ROOT / "protocol/PRODUCTION_SIGSTORE_GATE_DRAFT.md",
        STUDY_ROOT / "schemas/verifier-result.schema.json",
        STUDY_ROOT / "schemas/manifest.schema.json",
        production_manifest_schema_path,
        run_policy_schema_path,
        run_policy_validation_schema_path,
        process_isolation_schema_path,
        environment_attempt_schema_path,
        infrastructure_classification_schema_path,
        official_attempt_selection_schema_path,
        rg006_test_record_schema_path,
        pre_r0_closure_schema_path,
        pre_r0_closure_validation_schema_path,
        review_record_schema_path,
        review_packet_verification_schema_path,
        reviewer_identity_schema_path,
        reviewer_identity_validation_schema_path,
        model_review_protocol_schema_path,
        model_review_response_schema_path,
        STUDY_ROOT / "schemas/observation-ledger.schema.json",
        STUDY_ROOT / "schemas/analysis-summary.schema.json",
        selected_fixture_result_schema_path,
        selected_oracle_schema_path,
        STUDY_ROOT / "preregistration/OSF_PREREGISTRATION_DRAFT.md",
    ]
    tbd_locations: list[str] = []
    tbd_grammar_paths = {production_policy_schema_path}
    for path in readiness_paths:
        if path in tbd_grammar_paths:
            # This schema defines the permitted template marker as grammar. Its
            # literal constants are not unresolved release values.
            continue
        if path.suffix == ".json":
            obj = strict_json_loads(path.read_text(encoding="utf-8"))
            for location, value in walk_strings(obj):
                if "TBD-BEFORE-REGISTRATION" in value:
                    tbd_locations.append(f"{path.relative_to(STUDY_ROOT)}:{location}")
        else:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "TBD-BEFORE-REGISTRATION" in line:
                    tbd_locations.append(f"{path.relative_to(STUDY_ROOT)}:{line_number}")

    draft_statuses = [
        f"selected_catalog:{selected_catalog.get('status')}",
        f"selected_oracle:{selected_oracle.get('status')}",
        f"robustness:{robustness_catalog.get('status')}",
        f"reasons:{reasons.get('status')}",
        f"trust:{trust.get('status')}",
        f"production_policy:{production_policy.get('status')}",
        f"release_lineage:{lineage_contract.get('record_status')}",
        f"run_policy:{run_policy.get('status')}",
        f"attestation_profile:{attestation_decision.get('status')}",
        f"propositions:{proposition_matrix.get('status')}",
        f"bases:{base_registry.get('status')}",
        f"selected_prerequisites:{selected_prerequisite_registry.get('status')}",
        f"selected_compatibility:{selected_compatibility_matrix.get('status')}",
        f"reviewer_identity:{reviewer_identity_policy.get('status')}",
    ]
    if registration_ready:
        if tbd_locations:
            errors.append(f"Registration-ready mode found {len(tbd_locations)} TBD markers")
        if any("draft" in value or "not_frozen" in value for value in draft_statuses):
            errors.append(f"Registration-ready mode found draft status: {draft_statuses}")
        if production_policy.get("status") != "release_specific_frozen":
            errors.append(
                "Registration-ready mode requires a release-specific frozen production policy"
            )
        if (
            lineage_contract.get("record_status") != "frozen"
            or lineage_validation.get("release_freeze_permitted") is not True
            or (lineage_contract.get("current_decision") or {}).get("decision") != "GO"
        ):
            errors.append(
                "Registration-ready mode requires a frozen, internally valid release lineage"
            )
        if attestation_decision.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires a frozen independently reviewed "
                "attestation profile"
            )
        if selected_attestation_profile is None:
            errors.append("Registration-ready mode requires a selected attestation profile")
        if robustness_catalog.get("status") != "frozen_engineering_complete":
            errors.append(
                "Registration-ready mode requires a completed frozen robustness catalog"
            )
        if robustness_coverage_counts["SPECIFIED_NOT_IMPLEMENTED"]:
            errors.append(
                "Registration-ready mode found unimplemented robustness cases"
            )
        if proposition_matrix.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires an independently reviewed frozen proposition matrix"
            )
        if base_registry.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires an independently reviewed frozen base registry"
            )
        if unfrozen_base_hashes:
            errors.append(
                f"Registration-ready mode found {len(unfrozen_base_hashes)} unfrozen base hashes"
            )
        if selected_catalog.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires a frozen selected-profile catalog"
            )
        if selected_oracle.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires a frozen independently reviewed oracle"
            )
        if selected_prerequisite_registry.get("status") != "frozen_independently_reviewed":
            errors.append(
                "Registration-ready mode requires a frozen selected prerequisite registry"
            )
        if selected_compatibility_matrix.get("status") != "frozen_no_pending_rows":
            errors.append(
                "Registration-ready mode requires a frozen selected compatibility matrix"
            )
        if selected_pending_compatibility_count:
            errors.append(
                "Registration-ready mode found "
                f"{selected_pending_compatibility_count} selected pending compatibility rows"
            )
        if (
            run_policy_validation.get("freeze_permitted") is not True
            or run_policy_validation.get("decision") != "GO"
            or run_policy_validation.get("runner_confirmatory_execution_permitted")
            is not True
            or run_policy_validation.get("runner_rg006_complete") is not True
            or run_policy_validation.get("runner_contract_open_control_count") != 0
        ):
            errors.append(
                "Registration-ready mode requires a frozen RG-006 runner with "
                "zero open controls and explicit confirmatory authorization"
            )
        if (
            reviewer_identity_policy.get("status")
            != "frozen_authorized_for_authentication_only"
            or reviewer_identity_validation.get("decision")
            != "GO-FOR-AUTHENTICATION-ONLY"
        ):
            errors.append(
                "Registration-ready mode requires a preauthorized frozen reviewer-identity policy"
            )
        if open_blocking_gate_ids:
            errors.append(
                "Registration-ready mode found incomplete blocking gates: "
                f"{open_blocking_gate_ids}"
            )
    elif tbd_locations:
        warnings.append(f"Draft contains {len(tbd_locations)} explicit TBD markers")
    if open_blocking_gate_ids:
        warnings.append(
            f"Registration remains NO-GO with {len(open_blocking_gate_ids)} "
            "incomplete blocking gates"
        )
    if unfrozen_base_hashes:
        warnings.append(
            f"Base registry contains {len(unfrozen_base_hashes)} null hashes pending R0 freeze"
        )
    if selected_pending_compatibility_count:
        warnings.append(
            "Selected compatibility matrix contains "
            f"{selected_pending_compatibility_count} PENDING rows"
        )

    normative_text = "\n".join(
        (STUDY_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "protocol/PROTOCOL_DRAFT.md",
            "protocol/VERSIONING_AND_SIGNING_POLICY.md",
        )
    )
    if "provenance.intoto.jsonl" in normative_text:
        errors.append("Normative release-object text still references detached provenance input")

    tracked_contracts = [
        STUDY_ROOT / "README.md",
        STUDY_ROOT / "protocol/PROTOCOL_DRAFT.md",
        STUDY_ROOT / "protocol/THREAT_MODEL.md",
        STUDY_ROOT / "protocol/VERSIONING_AND_SIGNING_POLICY.md",
        STUDY_ROOT / "protocol/CLAIM_BOUNDARIES.md",
        STUDY_ROOT / "protocol/LIMITATIONS_AND_BOUNDARIES.md",
        STUDY_ROOT / "protocol/PRODUCTION_SIGSTORE_GATE_DRAFT.md",
        STUDY_ROOT / "protocol/PATH_POLICY_DRAFT.md",
        catalog_path,
        selected_catalog_path,
        selected_catalog_validation_path,
        selected_oracle_path,
        selected_oracle_validation_path,
        selected_development_record_path,
        selected_development_validation_path,
        base_aware_record_path,
        base_aware_validation_path,
        robustness_catalog_path,
        reasons_path,
        production_reasons_path,
        trust_path,
        historical_production_policy_path,
        production_policy_path,
        STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
        attestation_decision_path,
        upstream_attestation_audit_path,
        STUDY_ROOT / "audit/UPSTREAM_ATTESTATION_SEMANTICS_2026-07-13.md",
        STUDY_ROOT / "audit/RELEASE_IDENTITY_VERSION_SHA_SIGNATURE_AUDIT_2026-07-13.md",
        registration_gates_path,
        model_review_protocol_path,
        pre_r0_closure_ledger_path,
        pre_r0_closure_validation_path,
        lineage_contract_path,
        lineage_validation_path,
        proposition_path,
        run_policy_path,
        run_policy_validation_path,
        STUDY_ROOT / "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
        rg006_test_record_path,
        review_record_template_path,
        reviewer_identity_policy_path,
        reviewer_identity_validation_path,
        STUDY_ROOT / "reviews/R0_REVIEW_PACKET_DRAFT.md",
        STUDY_ROOT / "dummy_analysis/DUMMY_OBSERVATION_LEDGER.json",
        STUDY_ROOT / "dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json",
        base_registry_path,
        prerequisite_path,
        selected_prerequisite_path,
        compatibility_path,
        selected_compatibility_path,
        selected_compatibility_validation_path,
        selected_base_summary_path,
        selected_base_validation_path,
        selected_effective_policy_path,
        selected_base_comparison_path,
        selected_base_current_replay_path,
        manifest_schema_path,
        production_manifest_schema_path,
        production_policy_schema_path,
        historical_production_result_schema_path,
        production_result_schema_path,
        selected_fixture_result_schema_path,
        selected_oracle_schema_path,
        selected_development_schema_path,
        base_aware_schema_path,
        lineage_contract_schema_path,
        lineage_validation_schema_path,
        run_policy_schema_path,
        run_policy_validation_schema_path,
        process_isolation_schema_path,
        environment_attempt_schema_path,
        infrastructure_classification_schema_path,
        official_attempt_selection_schema_path,
        rg006_test_record_schema_path,
        model_review_protocol_schema_path,
        model_review_response_schema_path,
        pre_r0_closure_schema_path,
        pre_r0_closure_validation_schema_path,
        review_record_schema_path,
        review_packet_verification_schema_path,
        reviewer_identity_schema_path,
        reviewer_identity_validation_schema_path,
        STUDY_ROOT / "schemas/observation-ledger.schema.json",
        STUDY_ROOT / "schemas/analysis-summary.schema.json",
        result_schema_path,
        STUDY_ROOT / "amy_verifier/confirmatory_runner.py",
        STUDY_ROOT / "amy_verifier/github_attestation.py",
        production_v2_adapter_path,
        production_v2_core_path,
        STUDY_ROOT / "amy_verifier/selected_profile_fixture.py",
        STUDY_ROOT / "amy_verifier/selected_profile_mutations.py",
        STUDY_ROOT / "amy_verifier/selected_profile_oracle.py",
        STUDY_ROOT / "amy_verifier/selected_profile_evaluator.py",
        STUDY_ROOT / "scripts/verify_github_attestation.py",
        model_review_runner_path,
        model_review_validator_path,
        pre_r0_closure_validator_path,
        production_v2_cli_path,
        STUDY_ROOT / "scripts/build_selected_profile_catalog.py",
        STUDY_ROOT / "scripts/validate_selected_profile_catalog.py",
        STUDY_ROOT / "scripts/build_selected_profile_oracle.py",
        STUDY_ROOT / "scripts/validate_selected_profile_oracle.py",
        STUDY_ROOT / "scripts/run_selected_profile_development_checks.py",
        STUDY_ROOT / "scripts/validate_selected_profile_development_check.py",
        STUDY_ROOT / "scripts/run_base_aware_mutation_development_check.py",
        base_aware_validator_path,
        model_review_test_path,
        lineage_validator_path,
        run_policy_validator_path,
        STUDY_ROOT / "scripts/run_rg006_contract_tests.py",
        STUDY_ROOT / "scripts/build_r0_review_packet.py",
        reviewer_identity_validator_path,
        STUDY_ROOT / "scripts/verify_r0_review_packet.py",
        STUDY_ROOT / "scripts/build_dummy_analysis_fixture.py",
        STUDY_ROOT / "scripts/analyze_observation_ledger.py",
        STUDY_ROOT / "scripts/build_selected_profile_bases.py",
        STUDY_ROOT / "scripts/validate_selected_profile_base_run.py",
        STUDY_ROOT / "scripts/compare_selected_profile_base_runs.py",
        STUDY_ROOT / "scripts/build_selected_profile_compatibility_matrix.py",
        STUDY_ROOT / "scripts/validate_selected_profile_compatibility_matrix.py",
        STUDY_ROOT / "tests/test_selected_profile_full_generator_oracle.py",
        STUDY_ROOT / "tests/test_selected_profile_development_record.py",
        STUDY_ROOT / "tests/test_selected_profile_base_aware_mutations.py",
        STUDY_ROOT / "tests/test_base_aware_mutation_development_record.py",
        STUDY_ROOT / "tests/test_release_lineage_contract.py",
        STUDY_ROOT / "tests/test_run_execution_policy.py",
        STUDY_ROOT / "tests/test_confirmatory_runner_contract.py",
        STUDY_ROOT / "tests/test_dummy_analysis.py",
        STUDY_ROOT / "tests/test_r0_human_review_contract.py",
        STUDY_ROOT / "tests/test_github_attestation_v2.py",
        STUDY_ROOT / "preregistration/OSF_PREREGISTRATION_DRAFT.md",
        STUDY_ROOT / "evidence/CLAIM_EVIDENCE_MATRIX.csv",
        claim_validator_path,
        claim_test_path,
        STUDY_ROOT / "scripts/validate_robustness_run.py",
        STUDY_ROOT / "robustness_runs/engineering_20260713T072737Z/RESULT.json",
        STUDY_ROOT / "pyproject.toml",
        STUDY_ROOT / "uv.lock",
    ]
    if probe_script_path is not None:
        tracked_contracts.append(probe_script_path)
    tracked_contracts.extend(environment_probe_paths)
    return {
        "valid": not errors,
        "mode": "registration_ready" if registration_ready else "draft",
        "contract_version": next(iter(set(versions.values()))) if len(set(versions.values())) == 1 else None,
        "case_count": len(cases),
        "selected_profile_case_count": len(selected_cases),
        "selected_profile_added_case_count": len(
            set(selected_case_ids) - set(case_ids)
        ),
        "selected_profile_oracle_row_count": len(selected_oracle_rows),
        "selected_profile_oracle_validation_valid": selected_oracle_validation.get(
            "valid"
        ),
        "selected_profile_development_check_valid": selected_development_validation.get(
            "valid"
        ),
        "selected_profile_development_case_profile_evaluations": (
            selected_development_validation.get("development_case_profile_evaluations")
        ),
        "base_aware_mutation_development_valid": base_aware_validation.get("valid"),
        "base_aware_mutation_resolved_plan_count": base_aware_validation.get(
            "resolved_plan_count"
        ),
        "base_aware_mutation_unavailable_plan_count": base_aware_validation.get(
            "unavailable_plan_count"
        ),
        "clean_case_count": clean,
        "target_invalid_case_count": target_invalid,
        "family_count": len({case.get("family") for case in cases}),
        "claim_count": len(claim_rows),
        "robustness_case_count": len(robustness_cases),
        "robustness_coverage_counts": robustness_coverage_counts,
        "proposition_count": len(proposition_entries),
        "covered_rqs": sorted(covered_rqs),
        "covered_design_requirements": sorted(covered_design_requirements),
        "base_blueprint_count": len(base_entries),
        "base_release_kinds": sorted(base_kinds),
        "unfrozen_base_hash_count": len(unfrozen_base_hashes),
        "prerequisite_count": len(prerequisite_entries),
        "selected_prerequisite_count": len(selected_prerequisite_entries),
        "selected_pending_prerequisite_count": len(
            selected_pending_prerequisite_ids
        ),
        "environment_probe_count": len(environment_probe_records),
        "environment_probe_ids": sorted(environment_probe_records),
        "attestation_profile_status": attestation_decision.get("status"),
        "selected_attestation_profile": selected_attestation_profile,
        "production_policy_contract_version": production_policy.get(
            "schema_version"
        ),
        "production_policy_status": production_policy.get("status"),
        "production_policy_sha256": sha256(production_policy_path),
        "production_policy_schema_sha256": sha256(production_policy_schema_path),
        "production_result_schema_sha256": sha256(production_result_schema_path),
        "historical_v1_artifacts_preserved": all(
            sha256(STUDY_ROOT / relative) == expected
            for relative, expected in HISTORICAL_V1_SHA256.items()
        ),
        "compatibility_candidate_unit_count": len(compatibility_rows),
        "compatibility_counts": compatibility_state_counts,
        "selected_compatibility_candidate_unit_count": len(
            selected_compatibility_rows
        ),
        "selected_compatibility_counts": selected_compatibility_state_counts,
        "selected_compatibility_outcome_blinded": (
            selected_compatibility_validation.get("outcome_blinded")
        ),
        "selected_clean_base_validation_valid": selected_base_validation.get(
            "valid"
        ),
        "selected_clean_base_current_replay_valid": selected_base_current_replay.get(
            "valid"
        ),
        "selected_clean_base_current_source_drift_count": len(
            selected_base_current_replay.get("retained_source_drift_paths") or []
        ),
        "release_lineage_validation_valid": lineage_validation.get("valid"),
        "release_lineage_record_status": lineage_contract.get("record_status"),
        "release_lineage_decision": (
            lineage_contract.get("current_decision") or {}
        ).get("decision"),
        "release_lineage_freeze_permitted": lineage_validation.get(
            "release_freeze_permitted"
        ),
        "release_lineage_unresolved_field_count": lineage_validation.get(
            "unresolved_field_count"
        ),
        "run_execution_policy_validation_valid": run_policy_validation.get("valid"),
        "run_execution_policy_status": run_policy.get("status"),
        "run_execution_policy_sha256": sha256(run_policy_path),
        "run_execution_policy_freeze_permitted": run_policy_validation.get(
            "freeze_permitted"
        ),
        "run_execution_policy_decision": run_policy_validation.get("decision"),
        "dummy_analysis_status": run_policy_validation.get("dummy_analysis_status"),
        "dummy_analysis_valid": run_policy_validation.get("dummy_analysis_valid"),
        "dummy_analysis_planned_row_count": run_policy_validation.get(
            "dummy_analysis_planned_row_count"
        ),
        "external_reproduction_mandatory": run_policy_validation.get(
            "external_reproduction_mandatory"
        ),
        "r0_human_review_template_valid": not list(
            Draft202012Validator(
                review_record_schema, format_checker=FormatChecker()
            ).iter_errors(review_record_template)
        ),
        "r0_human_review_record_status": review_record_template.get(
            "record_status"
        ),
        "r0_human_review_occurred": review_record_template.get(
            "independent_human_review_occurred"
        ),
        "r0_reviewer_identity_policy_status": reviewer_identity_policy.get(
            "status"
        ),
        "r0_reviewer_identity_policy_validation_valid": (
            reviewer_identity_validation.get("valid")
        ),
        "r0_reviewer_identity_authentication_permitted": (
            reviewer_identity_validation.get("authentication_execution_permitted")
        ),
        "source_count": len(source_ids),
        "claim_evidence_validation_valid": claim_validation.get("valid"),
        "claim_evidence_resolved_reference_count": claim_validation.get(
            "resolved_reference_count"
        ),
        "registration_gate_count": len(gate_entries),
        "registration_gate_status": computed_gate_status,
        "open_blocking_gate_count": len(open_blocking_gate_ids),
        "open_blocking_gate_ids": open_blocking_gate_ids,
        "pre_r0_closure_ledger_valid": pre_r0_closure_validation.get("valid"),
        "pre_r0_closure_open_requirement_count": pre_r0_closure_validation.get(
            "open_requirement_count"
        ),
        "model_review_protocol_valid": model_review_preparation.get("valid"),
        "model_review_slot_count": model_review_preparation.get("slot_count"),
        "model_review_union_source_count": model_review_preparation.get(
            "union_source_count"
        ),
        "model_review_raw_batch_in_public_subject": False,
        "tbd_count": len(tbd_locations),
        "tbd_locations": tbd_locations,
        "used_reasons_by_profile": {
            profile: sorted(values) for profile, values in sorted(used_reasons.items())
        },
        "contract_sha256": {
            str(path.relative_to(STUDY_ROOT)): sha256(path) for path in tracked_contracts
        },
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registration-ready", action="store_true")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(registration_ready=args.registration_ready)
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
