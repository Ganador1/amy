#!/usr/bin/env python3
"""Replay and validate the selected-attestation-profile audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_selected_attestation_profile import STUDY_ROOT, build_audit, canonical_json, sha256


DEFAULT_RECORD = (
    STUDY_ROOT / "audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_2026-07-13.json"
)


def validate(record_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    input_drift_paths: list[str] = []
    retained = json.loads(record_path.read_text(encoding="utf-8"))
    current = build_audit()

    if retained.get("schema_version") != "amy.selected-attestation-profile-audit.v1":
        errors.append("unexpected retained schema_version")
    safety = retained.get("safety") or {}
    if any(value is not False for value in safety.values()):
        errors.append("retained safety declaration enables an excluded operation")

    scope = retained.get("scope") or {}
    inputs = scope.get("inputs") or {}
    for relative, metadata in inputs.items():
        path = STUDY_ROOT / relative
        if not path.is_file():
            input_drift_paths.append(relative)
            continue
        if metadata.get("sha256") != sha256(path):
            input_drift_paths.append(relative)
            continue
        if metadata.get("bytes") != path.stat().st_size:
            input_drift_paths.append(relative)

    selection = retained.get("selection") or {}
    if selection.get("profile_selected_but_not_frozen") is not True:
        errors.append("profile is not recorded as selected-but-unfrozen")
    implementation = retained.get("implementation") or {}
    if implementation.get("all_listed_controls_present") is not True:
        errors.append("one or more listed implementation controls is absent")
    if implementation.get("unregistered_adapter_rejection_codes") != []:
        errors.append("adapter uses unregistered production rejection codes")
    policy_contract = retained.get("policy_and_schema") or {}
    if policy_contract.get("current_policy_contract_version") != (
        "amy.github-attestation-policy.v2-draft"
    ):
        errors.append("current selected-profile audit does not use the v2 policy contract")
    if policy_contract.get("policy_schema_valid_draft_2020_12") is not True:
        errors.append("v2 policy template does not validate against its policy schema")
    if policy_contract.get("policy_schema_hash_matches") is not True:
        errors.append("v2 policy-schema digest is not bound")
    if policy_contract.get("policy_schema_typed_object_openings") != []:
        errors.append("v2 policy schema has an unclosed typed object")
    if policy_contract.get("historical_v1_bytes_preserved") is not True:
        errors.append("historical v1 attestation artifacts changed bytes")
    expected_p1_checks = {
        "closed_world_inventory",
        "manifest_canonicality",
        "manifest_json_syntax",
        "manifest_schema",
        "path_safety",
        "payload_digests",
    }
    if set(implementation.get("integrated_p1_check_keys") or []) != expected_p1_checks:
        errors.append("integrated P3 does not expose the complete P1 check set")

    snapshot = retained.get("source_snapshot_semantics") or {}
    if snapshot.get("snapshot_payload_bytes_hashed_by_p1") is not True:
        errors.append("source snapshot is not shown as byte-hashed by P1")
    if snapshot.get("archive_interior_inspected") is not False:
        errors.append("retained audit unexpectedly claims archive-semantic inspection")
    if snapshot.get("declared_git_tree_recomputed_from_snapshot") is not False:
        errors.append("retained audit unexpectedly claims snapshot/Git-tree equivalence")
    if snapshot.get("git_tree_equivalence_claimed_by_selected_profile") is not False:
        errors.append("selected profile exceeds its opaque source-snapshot boundary")
    if snapshot.get("claim_boundary_matches_implementation") is not True:
        errors.append("source-snapshot claim boundary differs from implementation")

    migration = retained.get("selected_s1_migration") or {}
    fixture_snapshot = migration.get("fixture_snapshot") or {}
    if fixture_snapshot.get("valid_deterministic_ustar") is not True:
        errors.append("selected S1 source snapshot is not a validated deterministic USTAR")
    if fixture_snapshot.get("git_tree_equivalence_claimed") is not False:
        errors.append("selected S1 fixture exceeds the opaque snapshot boundary")
    clean_bases = migration.get("clean_bases") or {}
    if clean_bases.get("validation_valid") is not True:
        errors.append("selected-profile clean-base validation is not valid")
    if clean_bases.get("base_count") != 6:
        errors.append("selected-profile clean-base count differs from six")
    if clean_bases.get("clean_profile_result_count") != 24:
        errors.append("selected-profile clean-result count differs from 24")
    if clean_bases.get("confirmatory_cases_generated") is not False:
        errors.append("selected-profile clean-base run generated confirmatory cases")
    if clean_bases.get("confirmatory_outcomes_read") is not False:
        errors.append("selected-profile clean-base run read confirmatory outcomes")
    if clean_bases.get("production_sigstore_conformance") is not False:
        errors.append("controlled selected fixture is mislabeled as production Sigstore")
    if clean_bases.get("retained_run_comparison_valid") is not True:
        errors.append("selected-profile retained-run comparison is not valid")
    if clean_bases.get("retained_base_archive_result_files_identical") is not True:
        errors.append("selected-profile retained clean-run outputs differ")
    if clean_bases.get("retained_source_archives_identical") is not False:
        errors.append("selected-profile terminology rerun did not preserve source distinction")
    if clean_bases.get("current_replay_valid") is not True:
        errors.append("selected-profile current clean-base replay is not valid")
    if clean_bases.get("retained_source_archive_self_valid") is not True:
        errors.append("selected-profile retained source archive is not internally valid")
    if clean_bases.get("retained_source_matches_current_study") is not False:
        errors.append("selected-profile current replay does not disclose source drift")
    if set(clean_bases.get("retained_source_drift_paths") or []) != {
        "amy_verifier/github_attestation.py",
        "amy_verifier/selected_profile_fixture.py",
        "scripts/validate_selected_profile_base_run.py",
    }:
        errors.append("selected-profile current source-drift path set differs")
    selected_catalog = migration.get("catalog") or {}
    if selected_catalog.get("validation_valid") is not True:
        errors.append("selected-profile catalog validation is not valid")
    expected_catalog_counts = {
        "historical_case_count": 34,
        "selected_case_count": 41,
        "preserved_case_id_count": 34,
        "added_case_count": 7,
        "migrated_semantic_case_count": 11,
        "implemented_generator_case_count": 41,
    }
    for field, expected in expected_catalog_counts.items():
        if selected_catalog.get(field) != expected:
            errors.append(f"selected-profile catalog count differs: {field}")
    if selected_catalog.get("confirmatory_cases_executed") is not False:
        errors.append("selected-profile catalog migration executed confirmatory cases")
    if selected_catalog.get("confirmatory_outcomes_read") is not False:
        errors.append("selected-profile catalog migration read confirmatory outcomes")
    oracle = migration.get("oracle") or {}
    if oracle.get("validation_valid") is not True:
        errors.append("selected-profile oracle validation is not valid")
    if oracle.get("case_count") != 41 or oracle.get("row_count") != 164:
        errors.append("selected-profile oracle counts differ from 41/164")
    if oracle.get("module_separation_static_check") is not True:
        errors.append("selected generator/verifier/oracle/evaluator are not separated")
    if oracle.get("confirmatory_cases_executed") is not False:
        errors.append("selected-profile oracle validation executed confirmatory cases")
    if oracle.get("confirmatory_outcomes_read") is not False:
        errors.append("selected-profile oracle validation read confirmatory outcomes")
    if oracle.get("independent_human_review_complete") is not False:
        errors.append("selected-profile draft oracle incorrectly claims independent review")
    development = migration.get("development_execution") or {}
    if development.get("validation_valid") is not True:
        errors.append("selected-profile development execution record is not valid")
    if development.get("pytest_passed_count") != 6:
        errors.append("selected-profile development pytest count differs from six")
    if development.get("case_count") != 41 or development.get("oracle_row_count") != 164:
        errors.append("selected-profile development execution coverage differs")
    if development.get("case_profile_evaluations") != 164:
        errors.append("selected-profile development case/profile count differs")
    if development.get("source_inventory_unchanged_during_execution") is not True:
        errors.append("selected-profile development source inventory changed during execution")
    for field in (
        "confirmatory_evidence",
        "production_sigstore_conformance",
        "independent_oracle_review",
    ):
        if development.get(field) is not False:
            errors.append(f"selected-profile development boundary differs: {field}")
    base_aware = migration.get("base_aware_mutation_plans") or {}
    if base_aware.get("validation_valid") is not True:
        errors.append("base-aware mutation development receipt is not valid")
    if base_aware.get("passed_test_count") != 4:
        errors.append("base-aware mutation development test count differs from four")
    if (
        base_aware.get("resolved_plan_count") != 245
        or base_aware.get("unavailable_plan_count") != 1
    ):
        errors.append("base-aware mutation plan counts differ from 245/1")
    if base_aware.get("disposable_target_dependent_execution_count") != 65:
        errors.append("base-aware disposable target-dependent execution count differs")
    for field in (
        "policy_fixture_collision_tested",
        "forged_plan_rejection_tested",
        "source_inventory_unchanged_during_execution",
    ):
        if base_aware.get(field) is not True:
            errors.append(f"base-aware mutation control differs: {field}")
    if base_aware.get("unavailable_plans") != [
        {
            "base_id": "B04-SOFTWARE",
            "operator_id": "INVENTORY-OMIT-ROLE-001",
            "reason_code": "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
        }
    ]:
        errors.append("base-aware unavailable-plan identity differs")
    if any(value is not False for value in (base_aware.get("boundaries") or {}).values()):
        errors.append("base-aware mutation receipt crosses a prohibited boundary")
    if base_aware.get("decision") != "NO-GO":
        errors.append("base-aware mutation receipt must remain NO-GO")
    if base_aware.get("manuscript_claims_authorized") is not False:
        errors.append("base-aware mutation receipt authorizes manuscript claims")
    compatibility = migration.get("compatibility") or {}
    if compatibility.get("validation_valid") is not True:
        errors.append("selected-profile compatibility validation is not valid")
    if compatibility.get("candidate_unit_count") != 246:
        errors.append("selected-profile compatibility count differs from 246")
    if compatibility.get("compatibility_counts") != {
        "COMPATIBLE": 185,
        "PENDING": 54,
        "NOT_COMPATIBLE": 7,
    }:
        errors.append("selected-profile compatibility state counts differ")
    if compatibility.get("mutation_plan_counts") != {
        "RESOLVED": 245,
        "UNAVAILABLE": 1,
    }:
        errors.append("selected-profile compatibility mutation-plan counts differ")
    if compatibility.get("outcome_blinded") is not True:
        errors.append("selected-profile compatibility is not outcome-blinded")
    if compatibility.get("counterfactual_outcome_fields_invariant") is not True:
        errors.append("selected compatibility changes under counterfactual outcomes")
    if compatibility.get("confirmatory_cases_generated") is not False:
        errors.append("selected compatibility generation created confirmatory cases")
    if compatibility.get("confirmatory_outcomes_read") is not False:
        errors.append("selected compatibility generation read confirmatory outcomes")
    if migration.get("full_41_case_generator_migration_complete") is not True:
        errors.append("audit does not record full temporary-fixture generator migration")
    if migration.get("pilot_profile_migration_complete") is not False:
        errors.append("audit incorrectly claims a complete frozen six-base case runner")

    tests = retained.get("tests_and_retained_runs") or {}
    if tests.get("integrated_test_mocks_cryptographic_verifier") is not True:
        errors.append("integrated synthetic test boundary is not disclosed")
    for field in (
        "v2_external_policy_digest_rejection_test_present",
        "v2_template_refusal_test_present",
        "v2_mutable_policy_bypass_test_present",
        "v2_evidence_snapshot_test_present",
        "v2_result_schema_substitution_test_present",
        "v2_library_result_validation_test_present",
        "v2_duplicate_policy_schema_test_present",
        "v2_cross_field_consistency_test_present",
        "historical_v1_invariant_test_present",
    ):
        if tests.get(field) is not True:
            errors.append(f"selected-profile audit omits v2 regression evidence: {field}")
    if tests.get("real_selected_repository_p3_record_count") != 0:
        errors.append("retained audit unexpectedly claims a real selected-repository P3 run")

    registration = retained.get("registration") or {}
    blocker_ids = {
        blocker.get("id")
        for blocker in registration.get("open_blockers") or []
        if isinstance(blocker, dict)
    }
    required_blockers = {
        "independent_review_incomplete",
        "real_amy_p3_absent",
        "release_policy_tbd_values",
        "release_workflow_absent",
        "s1_registered_runner_migration_incomplete",
    }
    if not required_blockers.issubset(blocker_ids):
        errors.append("retained audit omits one or more known freeze blockers")
    if registration.get("freeze_permitted_now") is not False:
        errors.append("retained audit incorrectly permits profile freeze")

    retained_canonical = canonical_json(retained)
    current_canonical = canonical_json(current)
    replay_matches = retained_canonical == current_canonical

    scanner_path = STUDY_ROOT / "scripts/audit_selected_attestation_profile.py"
    return {
        "schema_version": "amy.selected-attestation-profile-audit-validation.v1",
        "valid": not errors,
        "errors": errors,
        "classification": "historical_snapshot_with_current_replay",
        "record_path": record_path.relative_to(STUDY_ROOT).as_posix(),
        "command_contract": (
            "uv run --frozen python scripts/validate_selected_attestation_profile_audit.py"
        ),
        "scanner_sha256": sha256(scanner_path),
        "retained_pretty_json_sha256": sha256(record_path),
        "retained_canonical_json_sha256": hashlib.sha256(retained_canonical).hexdigest(),
        "fresh_canonical_json_sha256": hashlib.sha256(current_canonical).hexdigest(),
        "byte_identical_after_canonicalization": replay_matches,
        "current_replay_matches_retained": replay_matches,
        "source_drift_detected": not replay_matches,
        "retained_input_drift_paths": sorted(set(input_drift_paths)),
        "summary": {
            "listed_control_count": len(
                ((retained.get("implementation") or {}).get("controls") or {})
            ),
            "open_blocker_count": registration.get("open_blocker_count"),
            "policy_tbd_count": (
                (retained.get("policy_and_schema") or {}).get("unresolved_tbd_count")
            ),
            "current_policy_contract_version": policy_contract.get(
                "current_policy_contract_version"
            ),
            "current_policy_sha256": policy_contract.get("current_policy_sha256"),
            "policy_schema_sha256": policy_contract.get(
                "policy_schema_sha256_observed"
            ),
            "result_schema_sha256": policy_contract.get(
                "result_schema_sha256_observed"
            ),
            "historical_v1_bytes_preserved": policy_contract.get(
                "historical_v1_bytes_preserved"
            ),
            "real_selected_repository_p3_record_count": tests.get(
                "real_selected_repository_p3_record_count"
            ),
            "snapshot_git_tree_equivalence": snapshot.get(
                "declared_git_tree_recomputed_from_snapshot"
            ),
            "selected_fixture_valid_ustar": fixture_snapshot.get(
                "valid_deterministic_ustar"
            ),
            "selected_clean_base_count": clean_bases.get("base_count"),
            "selected_catalog_case_count": selected_catalog.get(
                "selected_case_count"
            ),
            "selected_generator_case_count": selected_catalog.get(
                "implemented_generator_case_count"
            ),
            "selected_oracle_row_count": oracle.get("row_count"),
            "selected_development_case_profile_evaluations": development.get(
                "case_profile_evaluations"
            ),
            "base_aware_resolved_plan_count": base_aware.get("resolved_plan_count"),
            "base_aware_unavailable_plan_count": base_aware.get(
                "unavailable_plan_count"
            ),
            "selected_compatibility_candidate_unit_count": compatibility.get(
                "candidate_unit_count"
            ),
        },
        "limitations": [
            "The retained record is a historical snapshot; current-input or canonical replay differences are disclosed as drift and do not rewrite the dated bytes.",
            "The replay uses the same host and present study bytes.",
            "AST and contract inspection do not execute GitHub CLI, Sigstore, or the release workflow.",
            "Unit-test presence is not itself evidence that a real A.M.Y P3 attestation exists.",
            "The selected S1 migration evidence uses controlled public test PKI and no adversarial confirmatory execution.",
            "The audit intentionally records unresolved semantic and registration gaps rather than treating code presence as production readiness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.record.resolve())
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
