from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
MATRIX = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
BUILDER = STUDY_ROOT / "scripts/build_selected_profile_compatibility_matrix.py"
VALIDATOR = STUDY_ROOT / "scripts/validate_selected_profile_compatibility_matrix.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_matrix_is_complete_replayable_and_outcome_blinded() -> None:
    result = _load(VALIDATOR, "selected_compatibility_validator").validate(MATRIX)
    assert result["valid"], result["errors"]
    assert result["candidate_unit_count"] == 246
    assert result["compatibility_counts"] == {
        "COMPATIBLE": 185,
        "PENDING": 54,
        "NOT_COMPATIBLE": 7,
    }
    assert result["mutation_plan_counts"] == {
        "RESOLVED": 245,
        "UNAVAILABLE": 1,
    }
    assert result["outcome_blinded"] is True
    assert result["counterfactual_outcome_fields_invariant"] is True
    assert result["deterministic_replay_identical"] is True
    assert result["selected_base_run_separate_validator_valid"] is True


def test_retained_selected_matrix_equals_fresh_builder_output() -> None:
    builder = _load(BUILDER, "selected_compatibility_builder")
    fresh = builder.build_matrix()
    retained = json.loads(MATRIX.read_text())
    assert fresh == retained


def test_selected_matrix_declares_clean_base_evidence_without_mutation_outcomes() -> None:
    matrix = json.loads(MATRIX.read_text())
    assert matrix["uses_observed_clean_base_validation"] is True
    assert matrix["uses_confirmatory_mutation_outcomes"] is False
    assert matrix["uses_profile_expectations"] is False
    assert matrix["uses_target_decisions"] is False
    assert matrix["uses_base_aware_mutation_plan_resolution"] is True
    assert matrix["mutation_plan_resolution_uses_outcomes"] is False
    forbidden = {
        "profile_expectations",
        "expected_decision",
        "expected_primary_reason",
        "observed_decision",
        "observed_result",
        "target_decision",
    }
    assert all(forbidden.isdisjoint(row) for row in matrix["rows"])


def test_pending_and_structurally_inapplicable_operators_are_not_called_failures() -> None:
    matrix = json.loads(MATRIX.read_text())
    pending = {
        row["operator_id"]
        for row in matrix["rows"]
        if row["compatibility"] == "PENDING"
    }
    assert pending == {
        "BUILD-DIRTY-001",
        "BUILD-METADATA-MISSING-001",
        "EXECUTION-IMAGE-MISMATCH-001",
        "MATERIAL-LOCK-MISMATCH-001",
        "RESOURCE-MANIFEST-LIMIT-001",
        "SNAPSHOT-DIGEST-MISMATCH-001",
        "SNAPSHOT-ROLE-MISMATCH-001",
        "SOURCE-TREE-MISMATCH-001",
        "SOURCE-WRONG-REVISION-001",
    }
    incompatible = [
        row for row in matrix["rows"] if row["compatibility"] == "NOT_COMPATIBLE"
    ]
    assert len(incompatible) == 7
    transparency = [
        row
        for row in incompatible
        if row["operator_id"] == "TRANSPARENCY-MISSING-001"
    ]
    assert len(transparency) == 6
    assert all(
        row["blocking_false"] == ["public_keyless_profile_frozen"]
        for row in transparency
    )
    unavailable = [
        row
        for row in incompatible
        if row["generator_blocking_reason"] is not None
    ]
    assert len(unavailable) == 1
    assert unavailable[0]["unit_id"] == "B04-SOFTWARE--INVENTORY-OMIT-ROLE-001"
    assert unavailable[0]["blocking_false"] == [
        "required_role_has_exactly_one_payload"
    ]
    assert unavailable[0]["mutation_plan"] == {
        "status": "UNAVAILABLE",
        "reason_code": "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
        "plan_sha256": None,
        "plan": None,
    }


def test_selected_migration_preserves_historical_matrix_and_catalog_bytes() -> None:
    expected = {
        "corpus/COMPATIBILITY_MATRIX_DRAFT.json": (
            "19c219f1a2bdc65d033ed7717c9924c3f503016463539eb22d250df3e576a921"
        ),
        "protocol/ATTACK_CATALOG.json": (
            "409213b0660263467947dc611933352cea145a03d536224181d94a3107c8c46d"
        ),
        "protocol/PREREQUISITE_REGISTRY_DRAFT.json": (
            "7bb7d65d24f38f648d4bcd198cdd66f2dfe32b810a3818a4c85fa8b7a5abe903"
        ),
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((STUDY_ROOT / relative).read_bytes()).hexdigest() == digest
