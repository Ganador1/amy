#!/usr/bin/env python3
"""Replay and validate the outcome-blind selected-profile S1 migration."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from build_selected_profile_catalog import (
    HISTORICAL_CATALOG,
    HISTORICAL_CATALOG_SHA256,
    STUDY_ROOT,
    build_catalog,
    build_prerequisite_registry,
    canonical_json,
    sha256,
)


DEFAULT_CATALOG = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
DEFAULT_PREREQUISITES = (
    STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json"
)
MIGRATED_CASE_IDS = {
    "BUILD-DIRTY-001",
    "BUILD-METADATA-MISSING-001",
    "BUILDER-PREDICATE-MISMATCH-001",
    "EXECUTION-IMAGE-MISMATCH-001",
    "MATERIAL-LOCK-MISMATCH-001",
    "PREDICATE-WRONG-TYPE-001",
    "SNAPSHOT-DIGEST-MISMATCH-001",
    "SNAPSHOT-ROLE-MISMATCH-001",
    "SOURCE-TREE-MISMATCH-001",
    "SOURCE-WRONG-REVISION-001",
    "WORKFLOW-PARAMETER-MISMATCH-001",
}
ADDED_CASE_IDS = MIGRATED_CASE_IDS - {
    "BUILD-DIRTY-001",
    "MATERIAL-LOCK-MISMATCH-001",
    "PREDICATE-WRONG-TYPE-001",
    "SOURCE-WRONG-REVISION-001",
}


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object name: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _load_json_strict(path: Path, errors: list[str], label: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{label} is not strict unambiguous JSON: {exc}")
        return {}


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(STUDY_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _function_string_literals(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def validate(catalog_path: Path, prerequisite_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    retained_catalog = _load_json_strict(catalog_path, errors, "selected catalog")
    retained_prerequisites = _load_json_strict(
        prerequisite_path, errors, "selected prerequisite registry"
    )
    fresh_catalog = build_catalog()
    fresh_prerequisites = build_prerequisite_registry()

    if retained_catalog.get("catalog_version") != "0.4.0-draft":
        errors.append("unexpected selected-profile catalog version")
    if retained_prerequisites.get("schema_version") != "0.2.0-draft":
        errors.append("unexpected selected-profile prerequisite version")
    if retained_catalog.get("status") != (
        "selected_profile_migration_not_frozen_not_executed"
    ):
        errors.append("selected-profile catalog does not disclose its unexecuted status")

    derived = retained_catalog.get("derived_from") or {}
    if derived.get("path") != HISTORICAL_CATALOG:
        errors.append("selected catalog points to an unexpected historical catalog")
    if derived.get("sha256") != HISTORICAL_CATALOG_SHA256:
        errors.append("selected catalog historical hash differs")
    if sha256(STUDY_ROOT / HISTORICAL_CATALOG) != HISTORICAL_CATALOG_SHA256:
        errors.append("historical catalog bytes changed")

    historical = _load_json_strict(
        STUDY_ROOT / HISTORICAL_CATALOG, errors, "historical catalog"
    )
    historical_ids = {case["id"] for case in historical.get("cases") or []}
    selected_cases = retained_catalog.get("cases") or []
    selected_ids = {case.get("id") for case in selected_cases if isinstance(case, dict)}
    if len(selected_ids) != len(selected_cases):
        errors.append("selected catalog contains duplicate or malformed case IDs")
    if not historical_ids.issubset(selected_ids):
        errors.append("selected catalog drops one or more historical case IDs")
    if selected_ids - historical_ids != ADDED_CASE_IDS:
        errors.append("selected catalog additions differ from the reviewed seven IDs")
    if len(selected_cases) != 41:
        errors.append("selected catalog must contain exactly 41 cases")

    profiles = {profile.get("id") for profile in retained_catalog.get("profiles") or []}
    if profiles != {"P0", "P1", "P2", "P3"}:
        errors.append("selected catalog profile set differs")
    by_id = {
        case["id"]: case
        for case in selected_cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    for case_id, case in by_id.items():
        expectations = case.get("profile_expectations") or {}
        if set(expectations) != profiles:
            errors.append(f"{case_id}: incomplete profile expectations")
        if case.get("kind") == "target_invalid" and case.get("target_decision") != "REJECT":
            errors.append(f"{case_id}: target-invalid case is not target REJECT")

    prerequisite_ids = {
        entry.get("id")
        for entry in retained_prerequisites.get("prerequisites") or []
        if isinstance(entry, dict)
    }
    unknown_prerequisites = {
        prerequisite
        for case in selected_cases
        for prerequisite in case.get("prerequisites") or []
        if prerequisite not in prerequisite_ids
    }
    if unknown_prerequisites:
        errors.append(f"unknown selected prerequisites: {sorted(unknown_prerequisites)}")

    for case_id in MIGRATED_CASE_IDS:
        case = by_id.get(case_id) or {}
        mutation = case.get("mutation_contract") or {}
        if set(mutation) != {
            "authenticated_object",
            "isolation",
            "json_pointer",
            "payload_bytes_changed",
            "reattest_after_mutation",
        }:
            errors.append(f"{case_id}: mutation contract is incomplete")
        if mutation.get("reattest_after_mutation") is not True:
            errors.append(f"{case_id}: changed authenticated bytes are not re-attested")
        if mutation.get("payload_bytes_changed") is not False:
            errors.append(f"{case_id}: semantic-isolation case changes payload bytes")
        expectations = case.get("profile_expectations") or {}
        if (expectations.get("P2") or {}).get("decision") != "ACCEPT":
            errors.append(f"{case_id}: P2 ablation is not ACCEPT")
        if (expectations.get("P3") or {}).get("decision") != "REJECT":
            errors.append(f"{case_id}: P3 target is not REJECT")

    forbidden_selected_text = json.dumps(
        [by_id.get(case_id, {}) for case_id in sorted(MIGRATED_CASE_IDS)],
        sort_keys=True,
    )
    for forbidden in (
        "amy:source-snapshot",
        "amy:dependency-lock",
        "externalParameters/source/dirty",
    ):
        if forbidden in forbidden_selected_text:
            errors.append(f"selected catalog retains pre-selection field: {forbidden}")
    if (retained_catalog.get("profile_selection") or {}).get(
        "custom_slsa_materials"
    ) is not False:
        errors.append("selected catalog does not reject custom SLSA materials")

    metadata_missing = by_id.get("BUILD-METADATA-MISSING-001") or {}
    missing_expectations = metadata_missing.get("profile_expectations") or {}
    if missing_expectations.get("P1") != {
        "decision": "REJECT",
        "primary_reason": "SCHEMA_INVALID",
    }:
        errors.append("missing metadata does not expose its P1 schema boundary")
    if missing_expectations.get("P3") != {
        "decision": "REJECT",
        "primary_reason": "PROVENANCE_INVALID",
    }:
        errors.append("missing metadata does not expose its P3 provenance boundary")

    fixture_path = STUDY_ROOT / "amy_verifier/selected_profile_fixture.py"
    generator_path = STUDY_ROOT / "amy_verifier/selected_profile_mutations.py"
    implemented_case_literals = _function_string_literals(
        generator_path, "apply_selected_profile_mutation"
    )
    missing_implementations = selected_ids - implemented_case_literals
    if missing_implementations:
        errors.append(
            f"selected fixture lacks mutation branches: {sorted(missing_implementations)}"
        )
    unexpected_implementations = {
        value for value in implemented_case_literals if value.endswith("-001")
    } - selected_ids
    if unexpected_implementations:
        errors.append(
            f"selected generator has unknown case branches: {sorted(unexpected_implementations)}"
        )

    fixture_contract = retained_catalog.get("fixture_policy") or {}
    fixture_contract_path = STUDY_ROOT / str(fixture_contract.get("path"))
    if not fixture_contract_path.is_file():
        errors.append("selected fixture-policy overlay is missing")
    elif fixture_contract.get("sha256") != sha256(fixture_contract_path):
        errors.append("selected fixture-policy overlay hash differs")
    if fixture_contract.get("production_sigstore_conformance") is not False:
        errors.append("selected fixture is mislabeled as production Sigstore")

    retained_catalog_canonical = canonical_json(retained_catalog)
    fresh_catalog_canonical = canonical_json(fresh_catalog)
    retained_prerequisite_canonical = canonical_json(retained_prerequisites)
    fresh_prerequisite_canonical = canonical_json(fresh_prerequisites)
    if retained_catalog_canonical != fresh_catalog_canonical:
        errors.append("fresh selected catalog differs after canonicalization")
    if retained_prerequisite_canonical != fresh_prerequisite_canonical:
        errors.append("fresh selected prerequisite registry differs after canonicalization")

    pending_prerequisites = sorted(
        entry["id"]
        for entry in retained_prerequisites.get("prerequisites") or []
        if entry.get("draft_state") == "PENDING"
    )
    builder_path = STUDY_ROOT / "scripts/build_selected_profile_catalog.py"
    validator_path = STUDY_ROOT / "scripts/validate_selected_profile_catalog.py"
    return {
        "schema_version": "amy.selected-profile-catalog-validation.v1-draft",
        "valid": not errors,
        "errors": errors,
        "classification": "pre_registration_outcome_blind_contract_replay",
        "catalog_path": _display_path(catalog_path),
        "prerequisite_path": _display_path(prerequisite_path),
        "catalog_pretty_sha256": sha256(catalog_path),
        "catalog_canonical_sha256": hashlib.sha256(
            retained_catalog_canonical
        ).hexdigest(),
        "fresh_catalog_canonical_sha256": hashlib.sha256(
            fresh_catalog_canonical
        ).hexdigest(),
        "prerequisite_pretty_sha256": sha256(prerequisite_path),
        "prerequisite_canonical_sha256": hashlib.sha256(
            retained_prerequisite_canonical
        ).hexdigest(),
        "fresh_prerequisite_canonical_sha256": hashlib.sha256(
            fresh_prerequisite_canonical
        ).hexdigest(),
        "builder_sha256": sha256(builder_path),
        "validator_sha256": sha256(validator_path),
        "fixture_implementation_sha256": sha256(fixture_path),
        "mutation_generator_sha256": sha256(generator_path),
        "summary": {
            "historical_case_count": len(historical_ids),
            "selected_case_count": len(selected_ids),
            "preserved_case_id_count": len(historical_ids & selected_ids),
            "added_case_count": len(ADDED_CASE_IDS),
            "migrated_semantic_case_count": len(MIGRATED_CASE_IDS),
            "implemented_generator_case_count": len(
                selected_ids & implemented_case_literals
            ),
            "prerequisite_count": len(prerequisite_ids),
            "pending_prerequisite_count": len(pending_prerequisites),
            "pending_prerequisite_ids": pending_prerequisites,
            "confirmatory_outcomes_read": False,
            "confirmatory_cases_executed": False,
        },
        "limitations": [
            "The fixture uses deterministic public test PKI, not production Sigstore.",
            "Development tests exercise all 41 operators on temporary generic fixtures; they do not materialize the registered six-base confirmatory corpus.",
            "The selected compatibility matrix and draft oracle are separately replayed; independent oracle review, release-specific production policy, and a real A.M.Y P3 run remain open.",
            "No target expectation was derived from observed confirmatory behavior.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--prerequisites", type=Path, default=DEFAULT_PREREQUISITES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.catalog.resolve(), args.prerequisites.resolve())
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
