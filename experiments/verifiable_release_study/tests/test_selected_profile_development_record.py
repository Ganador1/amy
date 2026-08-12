from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = STUDY_ROOT / "scripts/validate_selected_profile_development_check.py"
RECORD = (
    STUDY_ROOT
    / "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_V2_2026-07-15T034921Z.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("selected_development_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_selected_development_execution_is_hash_bound_and_nonconfirmatory() -> None:
    result = _load_validator().validate(RECORD)
    assert result["valid"], result["errors"]
    assert result["pytest_passed_count"] == 6
    assert result["catalog_case_count"] == 41
    assert result["oracle_row_count"] == 164
    assert result["development_case_profile_evaluations"] == 164
    assert result["confirmatory_evidence"] is False
    assert result["production_sigstore_conformance"] is False
    assert result["independent_oracle_review"] is False
    assert result["source_inventory_unchanged_during_execution"] is True


def test_selected_development_validator_rejects_pre_post_inventory_mismatch(
    tmp_path: Path,
) -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    record["source_inventory_post_sha256"] = "0" * 64
    candidate = tmp_path / "tampered.json"
    candidate.write_text(json.dumps(record), encoding="utf-8")
    result = _load_validator().validate(candidate)
    assert result["valid"] is False
    assert "pre/post source inventory identity differs" in result["errors"]


def test_selected_development_validator_rejects_duplicate_json_names(
    tmp_path: Path,
) -> None:
    raw = RECORD.read_text(encoding="utf-8").replace(
        "{\n", '{\n  "schema_version": "forged",\n', 1
    )
    candidate = tmp_path / "duplicate.json"
    candidate.write_text(raw, encoding="utf-8")
    module = _load_validator()
    with pytest.raises(module.DuplicateKeyError):
        module.validate(candidate)
