from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest
import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = STUDY_ROOT / "scripts/run_model_review_batch.py"
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_model_review_batch.py"
PROTOCOL_PATH = STUDY_ROOT / "protocol/MODEL_REVIEW_PROTOCOL.json"
PROTOCOL_SCHEMA_PATH = STUDY_ROOT / "schemas/model-review-protocol.schema.json"
RESPONSE_SCHEMA_PATH = STUDY_ROOT / "schemas/model-review-response.schema.json"


def _module():
    specification = importlib.util.spec_from_file_location(
        "model_review_runner_test", RUNNER_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _validator_module():
    specification = importlib.util.spec_from_file_location(
        "model_review_validator_test", VALIDATOR_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


@pytest.fixture
def failed_batch(tmp_path: Path, monkeypatch) -> Path:
    """Build a complete ten-slot transport-failure fixture from current bytes."""
    module = _module()

    def unavailable(*args, **kwargs):
        raise URLError("injected unavailable endpoint")

    monkeypatch.setattr(module.urllib.request, "urlopen", unavailable)
    result = module.run("http://127.0.0.1:11434", tmp_path)
    return Path(result["batch_directory"])


def test_protocol_and_response_schemas_are_closed() -> None:
    for path in (PROTOCOL_SCHEMA_PATH, RESPONSE_SCHEMA_PATH):
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


def test_frozen_protocol_has_ten_unique_roles_and_no_vote_semantics() -> None:
    protocol = _load(PROTOCOL_PATH)
    schema = _load(PROTOCOL_SCHEMA_PATH)
    assert list(Draft202012Validator(schema).iter_errors(protocol)) == []
    slots = protocol["review_slots"]
    assert [slot["slot_id"] for slot in slots] == [f"MR-{i:02d}" for i in range(1, 11)]
    assert len({slot["model_label"] for slot in slots}) == 10
    assert len({slot["role"] for slot in slots}) == 10
    assert protocol["finding_admission"]["model_vote_allowed"] is False
    assert protocol["finding_admission"]["majority_rule_allowed"] is False
    assert protocol["boundaries"]["manuscript_claims_authorized"] is False


def test_validate_only_prepares_every_request_without_network(monkeypatch) -> None:
    module = _module()

    def forbidden_network(*args, **kwargs):
        raise AssertionError("validate-only must not use network")

    monkeypatch.setattr(module.urllib.request, "urlopen", forbidden_network)
    result = module.validate_only()
    assert result["valid"] is True
    assert result["slot_count"] == 10
    assert result["union_source_count"] == 49
    assert [item["slot_id"] for item in result["prepared_requests"]] == [
        f"MR-{i:02d}" for i in range(1, 11)
    ]
    assert all(item["request_bytes"] > 100_000 for item in result["prepared_requests"])
    assert result["network_used"] is False
    assert result["manuscript_claims_authorized"] is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:11434?secret=value",
    ],
)
def test_nonlocal_or_ambiguous_endpoint_is_rejected(endpoint: str) -> None:
    module = _module()
    with pytest.raises(ValueError):
        module.validate_endpoint(endpoint)


def test_transport_failure_is_retained_without_retry_or_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    protocol, protocol_raw, response_schema, response_schema_raw = module.load_contracts()

    def unavailable(*args, **kwargs):
        raise URLError("injected unavailable endpoint")

    monkeypatch.setattr(module.urllib.request, "urlopen", unavailable)
    record = module.run_slot(
        endpoint="http://127.0.0.1:11434",
        batch_dir=tmp_path,
        protocol=protocol,
        protocol_sha256=module.sha256(protocol_raw),
        response_schema=response_schema,
        response_schema_sha256=module.sha256(response_schema_raw),
        slot=protocol["review_slots"][0],
    )
    assert record["http_status"] is None
    assert "URLError" in record["error"]
    assert record["response"]["bytes"] == 0
    assert record["boundaries"]["attempt_number"] == 1
    assert record["boundaries"]["retry_performed"] is False
    assert record["boundaries"]["replacement_model_used"] is False
    assert record["boundaries"]["manuscript_claims_authorized"] is False
    retained = list((tmp_path / "records").glob("*.jcs.json"))
    assert len(retained) == 1
    assert rfc8785.dumps(record) == retained[0].read_bytes()


def test_unknown_response_field_is_rejected() -> None:
    schema = _load(RESPONSE_SCHEMA_PATH)
    value = {
        "verdict": "MAJOR_REVISION",
        "critical_findings": [],
        "hidden_assumptions": [],
        "missing_tests": [],
        "reproducibility_risks": [],
        "overclaims": [],
        "strongest_falsification_test": "Run one concrete adversarial falsification test.",
        "uncertainties": [],
        "recommended_next_actions": [],
        "model_confidence_score": 0.99,
    }
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert any("Additional properties" in error.message for error in errors)


def test_generated_restricted_network_attempt_set_is_mechanically_valid(
    failed_batch: Path,
) -> None:
    result = _validator_module().validate(failed_batch)
    assert result["valid"] is True
    assert result["batch_status"] == "COMPLETE_ATTEMPT_SET_WITH_FAILURES"
    assert result["attempt_count"] == 10
    assert result["http_success_count"] == 0
    assert result["error_count"] == 10
    assert result["closed_response_count"] == 0
    assert result["decision"] == "NO-GO"
    assert result["boundaries"]["model_findings_verified"] is False


def test_generated_request_tampering_is_detected(
    tmp_path: Path, failed_batch: Path
) -> None:
    copy = tmp_path / "batch"
    shutil.copytree(failed_batch, copy)
    request = next((copy / "requests").glob("*.jcs.json"))
    request.write_bytes(request.read_bytes() + b" ")
    result = _validator_module().validate(copy)
    assert result["valid"] is False
    assert result["request_hashes_match"] is False


def test_duplicate_summary_key_is_rejected(
    tmp_path: Path, failed_batch: Path
) -> None:
    copy = tmp_path / "batch"
    shutil.copytree(failed_batch, copy)
    summary = copy / "summary.jcs.json"
    raw = summary.read_bytes().replace(
        b'{"attempt_count":', b'{"attempt_count":10,"attempt_count":', 1
    )
    summary.write_bytes(raw)
    result = _validator_module().validate(copy)
    assert result["valid"] is False
    assert any("DuplicateKeyError" in error for error in result["errors"])
