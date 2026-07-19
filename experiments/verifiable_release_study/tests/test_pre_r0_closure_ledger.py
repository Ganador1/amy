from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = STUDY_ROOT / "protocol/PRE_R0_CLOSURE_LEDGER.json"
VALIDATION_PATH = STUDY_ROOT / "protocol/PRE_R0_CLOSURE_LEDGER_VALIDATION.json"
SCHEMA_PATH = STUDY_ROOT / "schemas/pre-r0-closure-ledger.schema.json"
VALIDATION_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/pre-r0-closure-ledger-validation.schema.json"
)
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_pre_r0_closure_ledger.py"
EXPECTED_BLOCKERS = [
    "RG-001", "RG-002", "RG-004", "RG-005", "RG-006",
    "RG-009", "RG-010", "RG-011", "RG-013", "RG-014",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _module():
    specification = importlib.util.spec_from_file_location(
        "pre_r0_closure_validator_test", VALIDATOR_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_closure_ledger_and_validation_schemas_are_closed() -> None:
    for path in (SCHEMA_PATH, VALIDATION_SCHEMA_PATH):
        schema = _load(path)
        Draft202012Validator.check_schema(schema)

        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("type") == "object":
                    assert value.get("additionalProperties") is False
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(schema)


def test_retained_closure_validation_replays_exactly() -> None:
    module = _module()
    replay = module.validate()
    assert replay["valid"] is True
    assert replay["decision"] == "NO-GO"
    assert replay["registration_blocker_ids"] == EXPECTED_BLOCKERS
    assert replay["open_requirement_count"] == 17
    assert rfc8785.dumps(replay) == VALIDATION_PATH.read_bytes()


def test_every_control_prohibits_overclaiming_and_has_open_evidence() -> None:
    ledger = _load(LEDGER_PATH)
    assert [item["gate_id"] for item in ledger["controls"]] == EXPECTED_BLOCKERS
    assert ledger["summary"] == {
        "registration_blocker_count": 10,
        "partial_blocker_count": 7,
        "open_blocker_count": 3,
        "pending_compatibility_row_count": 54,
        "unresolved_tbd_count": 47,
        "runner_open_control_count": 11,
        "confirmatory_execution_permitted": False,
        "freeze_permitted": False,
    }
    for control in ledger["controls"]:
        assert control["prohibited_inferences"]
        assert control["unmet_requirements"]
        assert control["blocks_registration"] is True
        assert control["blocks_confirmatory_execution"] is True
        assert all(
            requirement["status"] == "OPEN"
            for requirement in control["unmet_requirements"]
        )
    assert ledger["boundaries"]["scientific_claims_authorized"] is False
    assert ledger["boundaries"]["ledger_self_certifies_completion"] is False


def test_bound_source_substitution_is_rejected(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    ledger = copy.deepcopy(_load(LEDGER_PATH))
    ledger["bindings"]["registration_gates_sha256"] = "0" * 64
    path = tmp_path / "ledger.json"
    path.write_bytes(rfc8785.dumps(ledger))
    monkeypatch.setattr(module, "LEDGER_PATH", path)
    result = module.validate()
    assert result["valid"] is False
    assert result["all_bindings_match"] is False
    assert any("registration_gates_sha256" in error for error in result["errors"])


def test_duplicate_json_key_is_rejected(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    raw = LEDGER_PATH.read_bytes().replace(
        b'{\n  "schema_version":',
        b'{\n  "status":"NO-GO",\n  "schema_version":',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_bytes(raw)
    monkeypatch.setattr(module, "LEDGER_PATH", path)
    with pytest.raises(module.DuplicateKeyError):
        module.validate()
