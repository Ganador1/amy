from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from amy_verifier.base_corpus import (
    load_draft_inputs,
    minimal_pdf,
    sha256_counter_stream,
    validate_registry,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
TRUST_PATH = STUDY_ROOT / "protocol/TRUST_POLICY_DRAFT.json"
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_r0_base_run.py"
VALID_RUN = STUDY_ROOT / "base_pilot_runs/r0_bases_20260713T065228Z"
FAILED_RUN = STUDY_ROOT / "base_pilot_runs/r0_bases_20260713T064933Z"


def _load_run_validator():
    spec = importlib.util.spec_from_file_location("r0_base_run_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_six_structurally_distinct_base_blueprints_are_internally_valid() -> None:
    registry, policy = load_draft_inputs(REGISTRY_PATH, TRUST_PATH)
    assert validate_registry(registry, policy) == []
    assert len(registry["bases"]) == 6
    assert len({base["release"]["kind"] for base in registry["bases"]}) == 6
    assert all(base["third_party_bytes"] is False for base in registry["bases"])
    assert all(
        base[field] is None
        for base in registry["bases"]
        for field in (
            "expected_base_archive_sha256",
            "expected_manifest_sha256",
            "expected_tree_sha256",
        )
    )


def test_binary_recipe_is_deterministic_across_hash_chunk_boundary() -> None:
    first = sha256_counter_stream("boundary-fixture", 2 * 1024 * 1024 + 1)
    second = sha256_counter_stream("boundary-fixture", 2 * 1024 * 1024 + 1)
    assert first == second
    assert len(first) == 2 * 1024 * 1024 + 1
    assert first != sha256_counter_stream("different-seed", len(first))


def test_minimal_pdf_recipe_has_stable_pdf_structure() -> None:
    first = minimal_pdf("Fixture", "No scientific claim.")
    second = minimal_pdf("Fixture", "No scientific claim.")
    assert first == second
    assert first.startswith(b"%PDF-1.4\n")
    assert first.endswith(b"%%EOF\n")
    assert b"xref\n" in first and b"startxref\n" in first


def test_retained_r0_base_pilot_passes_independent_validator() -> None:
    result = _load_run_validator().validate(VALID_RUN)
    assert result["valid"], result["errors"]
    assert result["base_count"] == 6
    assert result["confirmatory_cases_generated"] is False
    assert not (VALID_RUN / "cases").exists()


def test_first_failed_attempt_is_retained_and_not_reclassified() -> None:
    failure = json.loads((FAILED_RUN / "VALIDATION_FAILED.json").read_text())
    assert failure["valid"] is False
    assert failure["result_records_affected"] == 24
    assert "failed_attempt" in failure["attempt_disposition"]
