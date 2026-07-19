from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = STUDY_ROOT / "scripts/validate_base_aware_mutation_development_check.py"
RECORD = STUDY_ROOT / "development_checks/BASE_AWARE_MUTATION_PLANS_V2_2026-07-15T034921Z.json"


def _module():
    spec = importlib.util.spec_from_file_location("base_aware_receipt_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_base_aware_receipt_is_current_and_nonconfirmatory() -> None:
    result = _module().validate(RECORD)
    assert result["valid"], result["errors"]
    assert result["passed_test_count"] == 4
    assert result["resolved_plan_count"] == 245
    assert result["unavailable_plan_count"] == 1
    assert result["confirmatory_evidence"] is False
    assert result["independent_review_performed"] is False
    assert result["manuscript_claims_authorized"] is False


def test_base_aware_validator_rejects_pre_post_inventory_mismatch(
    tmp_path: Path,
) -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    record["source_inventory_post_sha256"] = "0" * 64
    candidate = tmp_path / "tampered.json"
    candidate.write_text(json.dumps(record), encoding="utf-8")
    result = _module().validate(candidate)
    assert result["valid"] is False
    assert "pre/post source inventory identity differs" in result["errors"]


def test_base_aware_validator_rejects_duplicate_json_names(tmp_path: Path) -> None:
    raw = RECORD.read_text(encoding="utf-8").replace(
        "{\n", '{\n  "schema_version": "forged",\n', 1
    )
    candidate = tmp_path / "duplicate.json"
    candidate.write_text(raw, encoding="utf-8")
    module = _module()
    with pytest.raises(module.DuplicateKeyError):
        module.validate(candidate)
