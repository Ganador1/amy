#!/usr/bin/env python3
"""Validate release-lineage semantics without reading verifier outcomes or releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = STUDY_ROOT / "protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json"
CONTRACT_SCHEMA_PATH = STUDY_ROOT / "schemas/release-lineage-contract.schema.json"
VALIDATION_SCHEMA_PATH = STUDY_ROOT / "schemas/release-lineage-validation.schema.json"
SOURCE_LEDGER_PATH = STUDY_ROOT / "evidence/SOURCE_LEDGER.md"
COMMAND_CONTRACT = (
    "uv run --frozen --extra pilot python "
    "scripts/validate_release_lineage_contract.py --compact"
)
REQUIRED_SOURCE_IDS = {
    "S01",
    "S02",
    "S03",
    "S04",
    "S07",
    "S08",
    "S10",
    "S11",
    "S13",
    "S16",
    "S19",
    "S20",
    "S22",
    "S25",
    "S30",
    "S31",
    "S32",
    "S33",
    "S35",
    "S36",
}
REQUIRED_IDENTITY_FIELDS = (
    "stage",
    "stage_version",
    "repository_uri",
    "git_object_format",
    "source_commit_oid",
    "source_tree_oid",
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
    "publication_timestamp",
)
STAGE_ORDER = ("R0", "R1", "R2")
COMPONENT_NAMES = ("A.M.Y", "Atlas", "AXIOM")
STUDY_TOOLCHAIN_NAME = "amy-verifiable-release-study"


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, *, max_bytes: int = 1024 * 1024) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError(f"{path.name} exceeds {max_bytes} bytes")
    return json.loads(raw, object_pairs_hook=_strict_object), raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _walk_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _walk_strings(item)]
    return []


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [key for item in value for key in _walk_keys(item)]
    if isinstance(value, dict):
        return list(value) + [key for item in value.values() for key in _walk_keys(item)]
    return []


def _format_schema_error(error: Any) -> str:
    location = "/" + "/".join(str(part) for part in error.absolute_path)
    return f"schema {location}: {error.message}"


def _oid_length_ok(object_format: str, oid: str) -> bool:
    return len(oid) == (40 if object_format == "sha1" else 64)


def _resolve_json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must start with /")
    current = document
    for encoded_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded_token):
            raise ValueError("invalid JSON Pointer escape")
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit():
                raise KeyError(token)
            index = int(token)
            if index >= len(current):
                raise IndexError(index)
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        else:
            raise KeyError(token)
    return current


def _validate_component_identity(component: dict[str, Any], errors: list[str]) -> str:
    name = component.get("name")
    status = component.get("resolution_status")
    identity_keys = (
        "distribution_identity",
        "declared_version",
        "git_object_format",
        "source_commit_oid",
        "source_tree_oid",
        "source_snapshot_sha256",
        "dependency_lock_sha256",
        "execution_image_digest",
    )
    if status == "frozen" and any(component.get(key) is None for key in identity_keys):
        errors.append(f"{name}: frozen component identity contains null values")
    if status == "unresolved_before_R0" and all(
        component.get(key) is not None for key in identity_keys
    ):
        errors.append(f"{name}: complete component identity is mislabeled unresolved")
    object_format = component.get("git_object_format")
    for key in ("source_commit_oid", "source_tree_oid"):
        oid = component.get(key)
        if object_format in {"sha1", "sha256"} and isinstance(oid, str):
            if not _oid_length_ok(object_format, oid):
                errors.append(f"{name}: {key} length differs from git_object_format")
    return status


def validate() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    contract, contract_raw = _load_json(CONTRACT_PATH)
    contract_schema, contract_schema_raw = _load_json(CONTRACT_SCHEMA_PATH)
    validation_schema, validation_schema_raw = _load_json(VALIDATION_SCHEMA_PATH)
    source_ledger_raw = SOURCE_LEDGER_PATH.read_bytes()

    Draft202012Validator.check_schema(contract_schema)
    Draft202012Validator.check_schema(validation_schema)
    contract_validator = Draft202012Validator(
        contract_schema,
        format_checker=FormatChecker(),
    )
    errors.extend(
        _format_schema_error(error)
        for error in sorted(
            contract_validator.iter_errors(contract),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    )

    source_ledger_text = source_ledger_raw.decode("utf-8")
    available_source_ids = set(re.findall(r"^\| (S[0-9]{2}) \|", source_ledger_text, re.MULTILINE))
    declared_source_ids = set(contract.get("normative_source_ids") or [])
    if not REQUIRED_SOURCE_IDS.issubset(declared_source_ids):
        errors.append(
            "normative source set omits required IDs: "
            + ", ".join(sorted(REQUIRED_SOURCE_IDS - declared_source_ids))
        )
    unresolved_source_ids = sorted(declared_source_ids - available_source_ids)
    if unresolved_source_ids:
        errors.append("source ledger does not define: " + ", ".join(unresolved_source_ids))

    if any("TBD-BEFORE-REGISTRATION" in text for text in _walk_strings(contract)):
        errors.append("lineage contract must use explicit null/unresolved state, not TBD strings")
    forbidden_keys = sorted(
        key for key in _walk_keys(contract) if key in {"self_sha256", "record_sha256"}
    )
    if forbidden_keys:
        errors.append("lineage contract contains a forbidden self-hash field")

    identity_fields = tuple(contract.get("required_release_identity_fields") or [])
    if identity_fields != REQUIRED_IDENTITY_FIELDS:
        errors.append("required release-identity tuple differs from the frozen field order")
    schema_identity_fields = tuple(
        (((contract_schema.get("$defs") or {}).get("releaseIdentity") or {}).get("required") or [])
    )
    if schema_identity_fields != REQUIRED_IDENTITY_FIELDS:
        errors.append(
            "releaseIdentity schema required fields differ from the frozen 18-field tuple"
        )

    components = contract.get("software_components") or []
    component_names = tuple(item.get("name") for item in components if isinstance(item, dict))
    if component_names != COMPONENT_NAMES:
        errors.append(f"software components must be ordered exactly as {COMPONENT_NAMES}")
    component_status = {
        name: "unresolved_before_R0" for name in COMPONENT_NAMES
    }
    for component in components:
        if not isinstance(component, dict) or component.get("name") not in component_status:
            continue
        name = component["name"]
        component_status[name] = _validate_component_identity(component, errors)

    study_toolchain = contract.get("study_toolchain_component")
    study_toolchain_status = "unresolved_before_R0"
    if not isinstance(study_toolchain, dict):
        errors.append("study toolchain component is missing")
    elif study_toolchain.get("name") != STUDY_TOOLCHAIN_NAME:
        errors.append(f"study toolchain component must be named {STUDY_TOOLCHAIN_NAME}")
    else:
        study_toolchain_status = _validate_component_identity(study_toolchain, errors)

    stage_entries = contract.get("stages") or []
    stage_names = tuple(item.get("stage") for item in stage_entries if isinstance(item, dict))
    if stage_names != STAGE_ORDER:
        errors.append(f"stages must be ordered exactly as {STAGE_ORDER}")
    stages = {
        item.get("stage"): item
        for item in stage_entries
        if isinstance(item, dict) and item.get("stage") in STAGE_ORDER
    }
    stage_status = {
        stage: (stages.get(stage) or {}).get("status", "not_created")
        for stage in STAGE_ORDER
    }
    stage_rules = contract.get("stage_rules") or {}
    parent_link_requirements = {
        stage: list(((stage_rules.get(stage) or {}).get("required_parent_stages") or []))
        for stage in STAGE_ORDER
    }
    stage_indexes = {
        item.get("stage"): index
        for index, item in enumerate(stage_entries)
        if isinstance(item, dict) and item.get("stage") in STAGE_ORDER
    }

    for stage in STAGE_ORDER:
        state = stages.get(stage)
        if not isinstance(state, dict):
            continue
        status = state.get("status")
        parents = state.get("parents") or []
        identity = state.get("identity")
        unresolved = state.get("unresolved_fields") or []
        stage_index = stage_indexes.get(stage)
        if status in {"frozen_unpublished", "published"}:
            if (
                identity is None
                or unresolved
                or state.get("freeze_permitted") is not True
                or not isinstance(state.get("registration_identifier"), str)
                or not isinstance(state.get("external_record_sha256"), str)
            ):
                errors.append(f"{stage}: frozen/published state is incomplete")
        else:
            if state.get("freeze_permitted") is not False:
                errors.append(f"{stage}: non-frozen state cannot permit freeze")
        if status == "not_created":
            if (
                identity is not None
                or parents
                or state.get("version_label") is not None
                or state.get("registration_identifier") is not None
                or state.get("external_record_sha256") is not None
            ):
                errors.append(f"{stage}: not-created state contains release identity or parents")
            if state.get("contains_or_derives_from_confirmatory_outputs") is not False:
                errors.append(f"{stage}: not-created state cannot contain confirmatory outputs")
        elif stage in {"R1", "R2"}:
            observed_parents = [item.get("stage") for item in parents if isinstance(item, dict)]
            if observed_parents != parent_link_requirements[stage]:
                errors.append(f"{stage}: exact parent-stage links are incomplete or reordered")
            if state.get("contains_or_derives_from_confirmatory_outputs") is not True:
                errors.append(f"{stage}: created post-R0 stage must disclose confirmatory derivation")
        if stage == "R0":
            if parents:
                errors.append("R0 must not have a parent release")
            if state.get("contains_or_derives_from_confirmatory_outputs") is not False:
                errors.append("R0 must not contain or derive from confirmatory outputs")
        if status == "draft_not_frozen" and stage_index is not None:
            for field in ("registration_identifier", "external_record_sha256"):
                pointer = f"/stages/{stage_index}/{field}"
                if state.get(field) is None and pointer not in unresolved:
                    errors.append(f"{stage}: unresolved {field} lacks its explicit pointer")
        if isinstance(identity, dict):
            if identity.get("stage") != stage:
                errors.append(f"{stage}: release identity names a different stage")
            if identity.get("stage_version") != state.get("version_label"):
                errors.append(f"{stage}: release identity/version-label mismatch")
            object_format = identity.get("git_object_format")
            for key in ("source_commit_oid", "source_tree_oid"):
                oid = identity.get(key)
                if object_format in {"sha1", "sha256"} and isinstance(oid, str):
                    if not _oid_length_ok(object_format, oid):
                        errors.append(f"{stage}: {key} length differs from git_object_format")
            if identity.get("concept_doi") == identity.get("version_doi"):
                errors.append(f"{stage}: concept DOI cannot substitute for version DOI")

    unresolved_pointers = [
        pointer
        for item in stage_entries
        if isinstance(item, dict)
        for pointer in (item.get("unresolved_fields") or [])
    ]
    for pointer in unresolved_pointers:
        if not isinstance(pointer, str):
            errors.append("unresolved pointer is not a string")
            continue
        try:
            pointed_value = _resolve_json_pointer(contract, pointer)
        except (IndexError, KeyError, ValueError):
            errors.append(f"unresolved pointer does not resolve in the contract: {pointer}")
            continue
        explicitly_unresolved = (
            pointed_value is None
            or pointed_value == []
            or (
                isinstance(pointed_value, dict)
                and pointed_value.get("resolution_status") == "unresolved_before_R0"
            )
        )
        if not explicitly_unresolved:
            errors.append(f"unresolved pointer targets a resolved value: {pointer}")
    if len(unresolved_pointers) != len(set(unresolved_pointers)):
        errors.append("unresolved pointers must be globally unique")

    r2_records = contract.get("r2_release_records") or []
    seen_r2_record_hashes: set[str] = set()
    seen_r2_version_dois: set[str] = set()
    previous_record_sha256: str | None = None
    previous_parents: list[dict[str, Any]] | None = None
    for index, record in enumerate(r2_records):
        if not isinstance(record, dict):
            continue
        kind = record.get("record_kind")
        record_sha256 = record.get("release_record_sha256")
        supersedes = record.get("supersedes_release_record_sha256")
        parents = record.get("parents") or []
        identity = record.get("identity") or {}
        observed_parent_stages = [
            parent.get("stage") for parent in parents if isinstance(parent, dict)
        ]
        if observed_parent_stages != parent_link_requirements["R2"]:
            errors.append(f"R2 record {index}: exact R0/R1 parents are incomplete or reordered")
        if identity.get("stage") != "R2":
            errors.append(f"R2 record {index}: identity must name stage R2")
        if index == 0:
            if kind != "initial_publication" or supersedes is not None:
                errors.append("R2 record 0 must be an initial publication without supersedes")
        elif kind != "correction" or supersedes != previous_record_sha256:
            errors.append(
                f"R2 record {index}: correction must supersede the exact prior R2 record"
            )
        if index > 0 and parents != previous_parents:
            errors.append(f"R2 record {index}: correction must preserve exact R0/R1 parents")
        if record_sha256 in seen_r2_record_hashes:
            errors.append(f"R2 record {index}: release_record_sha256 is duplicated")
        if isinstance(record_sha256, str):
            seen_r2_record_hashes.add(record_sha256)
            previous_record_sha256 = record_sha256
        version_doi = identity.get("version_doi")
        if version_doi in seen_r2_version_dois:
            errors.append(f"R2 record {index}: version DOI is duplicated")
        if isinstance(version_doi, str):
            seen_r2_version_dois.add(version_doi)
        previous_parents = parents

    r2_state = stages.get("R2") or {}
    if r2_state.get("status") == "not_created":
        if r2_records:
            errors.append("R2 is not-created but immutable R2 release records exist")
    else:
        if not r2_records:
            errors.append("created R2 stage lacks an immutable R2 release record")
        else:
            latest_r2 = r2_records[-1]
            if latest_r2.get("identity") != r2_state.get("identity"):
                errors.append("R2 stage identity must equal the latest immutable R2 record")
            if latest_r2.get("parents") != r2_state.get("parents"):
                errors.append("R2 stage parents must equal the latest immutable R2 record")

    unresolved_field_count = sum(
        len(item.get("unresolved_fields") or [])
        for item in stage_entries
        if isinstance(item, dict)
    )
    record_status = contract.get("record_status")
    decision_record = contract.get("current_decision") or {}
    decision = decision_record.get("decision")
    release_freeze_permitted = bool(
        not errors
        and record_status == "frozen"
        and decision == "GO"
        and decision_record.get("freeze_permitted_now") is True
        and not decision_record.get("blocking_reasons")
        and all(status == "frozen" for status in component_status.values())
        and study_toolchain_status == "frozen"
        and stage_status.get("R0") in {"frozen_unpublished", "published"}
        and unresolved_field_count == 0
    )
    if record_status == "frozen" and not release_freeze_permitted:
        errors.append("record claims frozen status without satisfying all release-freeze conditions")
    if decision_record.get("freeze_permitted_now") is not release_freeze_permitted:
        errors.append("current decision disagrees with computed release-freeze permission")

    rules = contract.get("identity_rules") or {}
    required_field_set = set(REQUIRED_IDENTITY_FIELDS)
    cryptographic_boundary_checks = {
        "software_label_not_execution_identity": rules.get(
            "software_version_is_execution_identity"
        )
        is False,
        "latest_forbidden_as_identity": rules.get("latest_is_execution_identity") is False,
        "git_oid_distinct_from_artifact_sha256": rules.get("git_oid_is_artifact_sha256")
        is False,
        "exact_byte_sha256_required": rules.get("artifact_hash_algorithm") == "sha256"
        and rules.get("artifact_digest_scope") == "exact_bytes",
        "policy_digest_required": "attestation_policy_sha256" in required_field_set,
        "trusted_root_digest_required": "trusted_root_sha256" in required_field_set,
        "attestation_bundle_digest_required": "attestation_bundle_sha256"
        in required_field_set,
        "result_schema_digest_required": "result_schema_sha256" in required_field_set,
        "transport_archive_digest_required": "transport_archive_sha256"
        in required_field_set,
        "self_hash_forbidden": rules.get("self_hash_field_allowed") is False
        and not forbidden_keys,
        "new_bytes_new_version": rules.get("new_bytes_require_new_version") is True
        and rules.get("new_bytes_require_new_manifest") is True
        and rules.get("new_bytes_require_new_attestation") is True,
        "signature_truth_claim_forbidden": rules.get("signature_proves_scientific_truth")
        is False,
        "stateless_rollback_claim_forbidden": rules.get("rollback_protection_is_stateless")
        is False,
    }
    failed_boundary_checks = sorted(
        key for key, passed in cryptographic_boundary_checks.items() if not passed
    )
    if failed_boundary_checks:
        errors.append("cryptographic boundary checks failed: " + ", ".join(failed_boundary_checks))

    if record_status == "draft_not_frozen":
        warnings.append("Lineage contract is internally checkable but remains draft and NO-GO")
    unresolved_components = sorted(
        name for name, status in component_status.items() if status != "frozen"
    )
    if unresolved_components:
        warnings.append("Unresolved software identities: " + ", ".join(unresolved_components))
    if study_toolchain_status != "frozen":
        warnings.append(
            f"Unresolved study toolchain identity: {STUDY_TOOLCHAIN_NAME}"
        )
    missing_stages = sorted(stage for stage, status in stage_status.items() if status == "not_created")
    if missing_stages:
        warnings.append("Release stages not created: " + ", ".join(missing_stages))
    if unresolved_field_count:
        warnings.append(f"Lineage state contains {unresolved_field_count} explicit unresolved pointers")

    result = {
        "schema_version": "amy.release-lineage-validation.v1-draft",
        "classification": "same_author_static_contract_validation_no_release_execution",
        "validity_scope": (
            "internal_contract_consistency_not_release_readiness_or_independent_review"
        ),
        "valid": not errors,
        "release_freeze_permitted": release_freeze_permitted,
        "record_status": record_status,
        "lineage_id": contract.get("lineage_id"),
        "decision": decision,
        "contract_sha256": _sha256(contract_raw),
        "contract_schema_sha256": _sha256(contract_schema_raw),
        "validation_schema_sha256": _sha256(validation_schema_raw),
        "source_ledger_sha256": _sha256(source_ledger_raw),
        "validator_sha256": _sha256(Path(__file__).read_bytes()),
        "command_contract": COMMAND_CONTRACT,
        "normative_source_count": len(declared_source_ids),
        "normative_sources_resolved": not unresolved_source_ids,
        "required_identity_field_count": len(REQUIRED_IDENTITY_FIELDS),
        "software_component_status": component_status,
        "stage_status": stage_status,
        "unresolved_field_count": unresolved_field_count,
        "parent_link_requirements": parent_link_requirements,
        "cryptographic_boundary_checks": cryptographic_boundary_checks,
        "read_scope": {
            "contract": "protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json",
            "contract_schema": "schemas/release-lineage-contract.schema.json",
            "validation_schema": "schemas/release-lineage-validation.schema.json",
            "source_ledger": "evidence/SOURCE_LEDGER.md",
            "confirmatory_artifacts_read": False,
            "verifier_results_read": False,
            "network_used": False,
            "independent_review_performed": False,
        },
        "errors": errors,
        "warnings": warnings,
    }
    output_errors = list(
        Draft202012Validator(
            validation_schema,
            format_checker=FormatChecker(),
        ).iter_errors(result)
    )
    if output_errors:
        raise RuntimeError("validation output violates its schema: " + output_errors[0].message)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate()
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
