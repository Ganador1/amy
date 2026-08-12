from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_release_lineage_contract.py"
CONTRACT_PATH = STUDY_ROOT / "protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json"
CONTRACT_SCHEMA_PATH = STUDY_ROOT / "schemas/release-lineage-contract.schema.json"
RESULT_PATH = STUDY_ROOT / "protocol/RELEASE_LINEAGE_VALIDATION.json"
RESULT_SCHEMA_PATH = STUDY_ROOT / "schemas/release-lineage-validation.schema.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location("release_lineage_validator", VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_counterfactual(tmp_path: Path, monkeypatch, contract: dict) -> dict:
    module = _load_validator()
    path = tmp_path / "counterfactual-lineage.json"
    path.write_text(json.dumps(contract, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(module, "CONTRACT_PATH", path)
    return module.validate()


def _dummy_parent(stage: str, digit: str) -> dict:
    return {
        "stage": stage,
        "release_record_sha256": digit * 64,
        "payload_manifest_sha256": digit * 64,
        "transport_archive_sha256": digit * 64,
        "version_doi": f"https://doi.org/10.0000/{stage.lower()}-{digit}",
    }


def _dummy_r2_identity(version: str, digit: str) -> dict:
    return {
        "stage": "R2",
        "stage_version": version,
        "repository_uri": "https://example.invalid/repository",
        "git_object_format": "sha1",
        "source_commit_oid": digit * 40,
        "source_tree_oid": digit * 40,
        "source_snapshot_sha256": digit * 64,
        "dependency_lock_sha256": digit * 64,
        "execution_image_digest": "sha256:" + digit * 64,
        "payload_manifest_sha256": digit * 64,
        "attestation_policy_sha256": digit * 64,
        "trusted_root_sha256": digit * 64,
        "attestation_bundle_sha256": digit * 64,
        "verifier_binary_sha256": digit * 64,
        "result_schema_sha256": digit * 64,
        "transport_archive_sha256": digit * 64,
        "version_doi": f"https://doi.org/10.0000/{version}",
        "publication_timestamp": "2026-07-13T00:00:00Z",
    }


def test_retained_release_lineage_validation_replays_exactly() -> None:
    module = _load_validator()
    fresh = module.validate()
    retained = _load(RESULT_PATH)
    assert fresh == retained
    assert fresh["valid"] is True
    assert fresh["release_freeze_permitted"] is False
    assert fresh["decision"] == "NO-GO"
    assert fresh["stage_status"] == {
        "R0": "draft_not_frozen",
        "R1": "not_created",
        "R2": "not_created",
    }
    assert fresh["software_component_status"] == {
        "A.M.Y": "unresolved_before_R0",
        "Atlas": "unresolved_before_R0",
        "AXIOM": "unresolved_before_R0",
    }
    assert "Unresolved study toolchain identity" in "\n".join(fresh["warnings"])
    assert fresh["read_scope"]["confirmatory_artifacts_read"] is False
    assert fresh["read_scope"]["verifier_results_read"] is False
    assert fresh["read_scope"]["independent_review_performed"] is False

    schema = _load(RESULT_SCHEMA_PATH)
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(retained)
    ) == []
    assert fresh["contract_sha256"] == hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    assert fresh["validator_sha256"] == hashlib.sha256(VALIDATOR_PATH.read_bytes()).hexdigest()


def test_release_identity_tuple_binds_policy_root_bundle_schema_and_archive() -> None:
    contract = _load(CONTRACT_PATH)
    fields = contract["required_release_identity_fields"]
    for required in (
        "source_commit_oid",
        "source_snapshot_sha256",
        "dependency_lock_sha256",
        "execution_image_digest",
        "payload_manifest_sha256",
        "attestation_policy_sha256",
        "trusted_root_sha256",
        "attestation_bundle_sha256",
        "verifier_binary_sha256",
        "result_schema_sha256",
        "transport_archive_sha256",
        "version_doi",
    ):
        assert required in fields
    assert contract["identity_rules"]["software_version_is_execution_identity"] is False
    assert contract["identity_rules"]["latest_is_execution_identity"] is False
    assert contract["identity_rules"]["signature_proves_scientific_truth"] is False


def test_release_identity_schema_requires_exactly_the_frozen_18_fields() -> None:
    contract = _load(CONTRACT_PATH)
    schema = _load(CONTRACT_SCHEMA_PATH)
    required = schema["$defs"]["releaseIdentity"]["required"]
    assert required == contract["required_release_identity_fields"]
    assert len(required) == 18
    assert "concept_doi" not in required
    assert "concept_doi" in schema["$defs"]["releaseIdentity"]["properties"]
    identity_validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/releaseIdentity",
            "$defs": schema["$defs"],
        },
        format_checker=FormatChecker(),
    )
    assert list(identity_validator.iter_errors(_dummy_r2_identity("paper-v1", "a"))) == []


def test_r0_external_registration_pointers_resolve_to_represented_fields() -> None:
    contract = _load(CONTRACT_PATH)
    r0 = contract["stages"][0]
    assert r0["registration_identifier"] is None
    assert r0["external_record_sha256"] is None
    assert "/stages/0/registration_identifier" in r0["unresolved_fields"]
    assert "/stages/0/external_record_sha256" in r0["unresolved_fields"]


def test_nonexistent_unresolved_pointer_is_rejected(tmp_path: Path, monkeypatch) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    contract["stages"][0]["unresolved_fields"].append("/stages/0/not-a-field")
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any("unresolved pointer does not resolve" in error for error in result["errors"])


def test_unresolved_pointer_cannot_target_a_resolved_value(tmp_path: Path, monkeypatch) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    contract["stages"][0]["unresolved_fields"].append("/record_status")
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any("unresolved pointer targets a resolved value" in error for error in result["errors"])


def test_study_toolchain_component_is_required_and_cannot_be_falsely_frozen(
    tmp_path: Path, monkeypatch
) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    contract["study_toolchain_component"]["resolution_status"] = "frozen"
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any(
        "amy-verifiable-release-study: frozen component identity contains null values"
        in error
        for error in result["errors"]
    )


def test_false_frozen_state_without_identity_is_rejected(tmp_path: Path, monkeypatch) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    contract["record_status"] = "frozen"
    contract["current_decision"] = {
        "decision": "GO",
        "freeze_permitted_now": True,
        "blocking_reasons": [],
    }
    contract["stages"][0]["status"] = "frozen_unpublished"
    contract["stages"][0]["freeze_permitted"] = True
    contract["stages"][0]["unresolved_fields"] = []
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert result["release_freeze_permitted"] is False
    assert any("frozen/published state is incomplete" in error for error in result["errors"])


def test_created_R1_without_exact_R0_parent_is_rejected(tmp_path: Path, monkeypatch) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    r1 = contract["stages"][1]
    r1.update(
        {
            "status": "draft_not_frozen",
            "version_label": "evidence-v1.0.0-draft",
            "contains_or_derives_from_confirmatory_outputs": True,
            "parents": [],
            "unresolved_fields": ["/stages/1/parents", "/stages/1/identity"],
        }
    )
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any("R1: exact parent-stage links" in error for error in result["errors"])


def test_git_object_format_mismatch_is_not_relabelled_as_sha256(
    tmp_path: Path, monkeypatch
) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    component = contract["software_components"][0]
    component.update(
        {
            "distribution_identity": "amy",
            "declared_version": "2.0.0-alpha.1",
            "git_object_format": "sha1",
            "source_commit_oid": "a" * 64,
            "source_tree_oid": "b" * 64,
            "source_snapshot_sha256": "c" * 64,
            "dependency_lock_sha256": "d" * 64,
            "execution_image_digest": "sha256:" + "e" * 64,
            "resolution_status": "frozen",
        }
    )
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any("A.M.Y: source_commit_oid length" in error for error in result["errors"])
    assert any("A.M.Y: source_tree_oid length" in error for error in result["errors"])


def test_git_object_format_oid_relation_is_enforced_by_json_schema() -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    component = contract["software_components"][0]
    component["git_object_format"] = "sha1"
    component["source_commit_oid"] = "a" * 64
    component["source_tree_oid"] = "b" * 64
    schema = _load(CONTRACT_SCHEMA_PATH)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(contract)
    )
    assert any(list(error.absolute_path)[-1:] == ["source_commit_oid"] for error in errors)
    assert any(list(error.absolute_path)[-1:] == ["source_tree_oid"] for error in errors)
    identity = _dummy_r2_identity("paper-v1", "a")
    identity["git_object_format"] = "sha256"
    identity_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/$defs/releaseIdentity",
        "$defs": schema["$defs"],
    }
    identity_errors = list(
        Draft202012Validator(
            identity_schema, format_checker=FormatChecker()
        ).iter_errors(identity)
    )
    assert any(
        list(error.absolute_path)[-1:] == ["source_commit_oid"]
        for error in identity_errors
    )
    assert any(
        list(error.absolute_path)[-1:] == ["source_tree_oid"]
        for error in identity_errors
    )


def test_R2_correction_must_supersede_exact_prior_immutable_record(
    tmp_path: Path, monkeypatch
) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    parents = [_dummy_parent("R0", "a"), _dummy_parent("R1", "b")]
    contract["r2_release_records"] = [
        {
            "record_kind": "initial_publication",
            "release_record_sha256": "c" * 64,
            "supersedes_release_record_sha256": None,
            "correction_reason": None,
            "parents": parents,
            "identity": _dummy_r2_identity("paper-v1", "c"),
        },
        {
            "record_kind": "correction",
            "release_record_sha256": "d" * 64,
            "supersedes_release_record_sha256": "e" * 64,
            "correction_reason": "Corrected identified release metadata.",
            "parents": parents,
            "identity": _dummy_r2_identity("paper-v2-correction-1", "d"),
        },
    ]
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any(
        "correction must supersede the exact prior R2 record" in error
        for error in result["errors"]
    )


def test_R2_correction_must_preserve_exact_R0_R1_parents(
    tmp_path: Path, monkeypatch
) -> None:
    contract = copy.deepcopy(_load(CONTRACT_PATH))
    first_parents = [_dummy_parent("R0", "a"), _dummy_parent("R1", "b")]
    changed_parents = [_dummy_parent("R0", "a"), _dummy_parent("R1", "f")]
    contract["r2_release_records"] = [
        {
            "record_kind": "initial_publication",
            "release_record_sha256": "c" * 64,
            "supersedes_release_record_sha256": None,
            "correction_reason": None,
            "parents": first_parents,
            "identity": _dummy_r2_identity("paper-v1", "c"),
        },
        {
            "record_kind": "correction",
            "release_record_sha256": "d" * 64,
            "supersedes_release_record_sha256": "c" * 64,
            "correction_reason": "Corrected identified release metadata.",
            "parents": changed_parents,
            "identity": _dummy_r2_identity("paper-v2-correction-1", "d"),
        },
    ]
    result = _validate_counterfactual(tmp_path, monkeypatch, contract)
    assert result["valid"] is False
    assert any(
        "correction must preserve exact R0/R1 parents" in error
        for error in result["errors"]
    )
