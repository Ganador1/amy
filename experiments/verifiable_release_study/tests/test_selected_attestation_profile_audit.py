from __future__ import annotations

import importlib.util
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = STUDY_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_profile_audit_is_valid_and_current_drift_is_disclosed(
    monkeypatch,
) -> None:
    scanner = _load_script("audit_selected_attestation_profile")
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_selected_attestation_profile_audit")
    result = validator.validate(
        STUDY_ROOT / "audit/SELECTED_ATTESTATION_PROFILE_AUDIT_RAW_V2_2026-07-15T034921Z.json"
    )
    assert result["valid"], result["errors"]
    assert result["byte_identical_after_canonicalization"] is False
    assert result["current_replay_matches_retained"] is False
    assert result["source_drift_detected"] is True
    assert "protocol/REGISTRATION_GATES.json" in result[
        "retained_input_drift_paths"
    ]


def test_selected_profile_audit_separates_byte_binding_from_git_tree_equivalence() -> None:
    scanner = _load_script("audit_selected_attestation_profile")
    audit = scanner.build_audit()

    assert audit["selection"]["profile_selected_but_not_frozen"] is True
    assert audit["implementation"]["all_listed_controls_present"] is True
    assert audit["implementation"]["unregistered_adapter_rejection_codes"] == []
    snapshot = audit["source_snapshot_semantics"]
    assert snapshot["snapshot_payload_bytes_hashed_by_p1"] is True
    assert snapshot["archive_interior_inspected"] is False
    assert snapshot["declared_git_tree_recomputed_from_snapshot"] is False
    assert snapshot["git_tree_equivalence_claimed_by_selected_profile"] is False
    assert snapshot["claim_boundary_matches_implementation"] is True
    retained = audit["tests_and_retained_runs"]
    assert retained["integrated_test_mocks_cryptographic_verifier"] is True
    assert retained["real_selected_repository_p3_record_count"] == 0
    migration = audit["selected_s1_migration"]
    assert migration["fixture_snapshot"]["valid_deterministic_ustar"] is True
    assert migration["fixture_snapshot"]["git_tree_equivalence_claimed"] is False
    assert migration["clean_bases"]["base_count"] == 6
    assert migration["clean_bases"]["clean_profile_result_count"] == 24
    assert migration["catalog"]["selected_case_count"] == 41
    assert migration["catalog"]["implemented_generator_case_count"] == 41
    assert migration["oracle"]["row_count"] == 164
    assert migration["oracle"]["independent_human_review_complete"] is False
    assert migration["development_execution"]["validation_valid"] is True
    assert migration["development_execution"]["case_profile_evaluations"] == 164
    assert migration["development_execution"]["confirmatory_evidence"] is False
    assert migration["compatibility"]["candidate_unit_count"] == 246
    assert migration["compatibility"]["outcome_blinded"] is True
    assert migration["full_41_case_generator_migration_complete"] is True
    assert audit["registration"]["freeze_permitted_now"] is False
