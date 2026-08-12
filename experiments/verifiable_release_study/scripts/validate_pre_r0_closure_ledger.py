#!/usr/bin/env python3
"""Validate the bound pre-R0 closure ledger without reading run outcomes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = STUDY_ROOT / "protocol/PRE_R0_CLOSURE_LEDGER.json"
SCHEMA_PATH = STUDY_ROOT / "schemas/pre-r0-closure-ledger.schema.json"
VALIDATION_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/pre-r0-closure-ledger-validation.schema.json"
)
BOUND_PATHS = {
    "registration_gates_sha256": "protocol/REGISTRATION_GATES.json",
    "run_execution_policy_sha256": "protocol/RUN_EXECUTION_POLICY_DRAFT.json",
    "run_execution_policy_validation_sha256": "protocol/RUN_EXECUTION_POLICY_VALIDATION.json",
    "selected_compatibility_matrix_sha256": "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json",
    "r0_reviewer_identity_policy_validation_sha256": "protocol/R0_REVIEWER_IDENTITY_POLICY_VALIDATION.json",
    "release_lineage_validation_sha256": "protocol/RELEASE_LINEAGE_VALIDATION.json",
}
EXPECTED_BLOCKERS = [
    "RG-001", "RG-002", "RG-004", "RG-005", "RG-006",
    "RG-009", "RG-010", "RG-011", "RG-013", "RG-014",
]


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> tuple[Any, bytes]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required input is not a regular non-symlink file: {path}")
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=_strict_object), raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _protocol_state() -> dict[str, Any]:
    path = STUDY_ROOT / "scripts/validate_protocol.py"
    specification = importlib.util.spec_from_file_location(
        "pre_r0_bound_protocol_validator", path
    )
    if specification is None or specification.loader is None:
        raise ValueError("cannot load the bound protocol validator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.validate(registration_ready=False)


def validate() -> dict[str, Any]:
    errors: list[str] = []
    ledger, ledger_raw = _load(LEDGER_PATH)
    schema, schema_raw = _load(SCHEMA_PATH)
    validation_schema, _ = _load(VALIDATION_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(validation_schema)
    errors.extend(
        f"ledger schema: {error.message}"
        for error in Draft202012Validator(schema).iter_errors(ledger)
    )

    bindings_match = True
    bindings = ledger.get("bindings") if isinstance(ledger, dict) else {}
    for field, relative in BOUND_PATHS.items():
        path = STUDY_ROOT / relative
        actual = _sha(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
        if not isinstance(bindings, dict) or bindings.get(field) != actual:
            bindings_match = False
            errors.append(f"bound SHA-256 differs: {field}")

    gates, _ = _load(STUDY_ROOT / "protocol/REGISTRATION_GATES.json")
    gate_by_id = {item["id"]: item for item in gates["gates"]}
    actual_blockers = [
        item["id"]
        for item in gates["gates"]
        if item["blocks_registration"] and item["status"] != "complete"
    ]
    if actual_blockers != EXPECTED_BLOCKERS:
        errors.append("registration blocker set or order differs")

    controls = ledger.get("controls") if isinstance(ledger, dict) else []
    controls = controls if isinstance(controls, list) else []
    control_ids = [item.get("gate_id") for item in controls if isinstance(item, dict)]
    if control_ids != EXPECTED_BLOCKERS:
        errors.append("closure-ledger control set or order differs")
    for item in controls:
        if not isinstance(item, dict):
            continue
        gate = gate_by_id.get(item.get("gate_id"))
        if gate is None or item.get("gate_status") != gate.get("status"):
            errors.append(f"gate status differs: {item.get('gate_id')}")

    evidence_paths: list[str] = []
    requirement_ids: list[str] = []
    for item in controls:
        if not isinstance(item, dict):
            continue
        evidence_paths.extend(item.get("current_evidence_paths") or [])
        requirement_ids.extend(
            requirement.get("id")
            for requirement in (item.get("unmet_requirements") or [])
            if isinstance(requirement, dict)
        )
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("unmet requirement IDs are not globally unique")

    paths_exist = True
    for relative in evidence_paths:
        path = STUDY_ROOT / relative
        try:
            path.relative_to(STUDY_ROOT)
        except ValueError:
            paths_exist = False
            errors.append(f"evidence path escapes study root: {relative}")
            continue
        if not path.is_file() or path.is_symlink():
            paths_exist = False
            errors.append(f"current evidence path missing or unsafe: {relative}")

    summary = ledger.get("summary") if isinstance(ledger, dict) else {}
    run_validation, _ = _load(
        STUDY_ROOT / "protocol/RUN_EXECUTION_POLICY_VALIDATION.json"
    )
    protocol_state = _protocol_state()
    expected_summary = {
        "registration_blocker_count": len(EXPECTED_BLOCKERS),
        "partial_blocker_count": sum(
            gate_by_id[item]["status"] == "partial" for item in EXPECTED_BLOCKERS
        ),
        "open_blocker_count": sum(
            gate_by_id[item]["status"] == "open" for item in EXPECTED_BLOCKERS
        ),
        "pending_compatibility_row_count": run_validation[
            "pending_compatibility_row_count"
        ],
        "unresolved_tbd_count": protocol_state["tbd_count"],
        "runner_open_control_count": run_validation[
            "runner_contract_open_control_count"
        ],
        "confirmatory_execution_permitted": False,
        "freeze_permitted": False,
    }
    if summary != expected_summary:
        errors.append("closure-ledger summary differs from bound current state")

    result = {
        "schema_version": "amy.pre-r0-closure-ledger-validation.v1",
        "classification": "same_worktree_structural_validation_not_independent_review",
        "ledger_sha256": _sha(ledger_raw),
        "schema_sha256": _sha(schema_raw),
        "validator_sha256": _sha(Path(__file__).read_bytes()),
        "valid": not errors,
        "errors": sorted(errors),
        "control_count": len(controls),
        "open_requirement_count": len(requirement_ids),
        "current_evidence_path_count": len(evidence_paths),
        "all_bindings_match": bindings_match,
        "all_current_evidence_paths_exist": paths_exist,
        "registration_blocker_ids": actual_blockers,
        "decision": "NO-GO",
        "boundaries": {
            "confirmatory_evidence_read": False,
            "scientific_claims_authorized": False,
            "independent_review_performed": False,
            "network_used": False,
        },
    }
    output_errors = list(Draft202012Validator(validation_schema).iter_errors(result))
    if output_errors:
        raise ValueError(f"validation-output schema failure: {output_errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate()
    raw = rfc8785.dumps(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
    else:
        print(raw.decode("utf-8"))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
