#!/usr/bin/env python3
"""Build a full synthetic observation ledger without reading confirmatory evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
MATRIX_PATH = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
ORACLE_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
PROPOSITIONS_PATH = STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json"
POLICY_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json"
SCHEMA_PATH = STUDY_ROOT / "schemas/observation-ledger.schema.json"
ENVIRONMENTS = ("ENV-AUTHOR", "ENV-LINUX-PINNED")
PROFILES = ("P0", "P1", "P2", "P3")


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> Any:
    return json.loads(path.read_bytes(), object_pairs_hook=_strict_object)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dummy_sha(namespace: str, value: str) -> str:
    return hashlib.sha256(f"A.M.Y-DUMMY\0{namespace}\0{value}".encode()).hexdigest()


def build() -> dict[str, Any]:
    catalog = _load(CATALOG_PATH)
    matrix = _load(MATRIX_PATH)
    oracle = _load(ORACLE_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)

    case_by_id = {case["id"]: case for case in catalog["cases"]}
    expectation = {
        (row["case_id"], row["profile_id"]): row for row in oracle["rows"]
    }
    compatible = sorted(
        (row for row in matrix["rows"] if row["compatibility"] == "COMPATIBLE"),
        key=lambda row: (row["base_id"].encode("ascii"), row["operator_id"].encode("ascii")),
    )
    if len(compatible) != 185:
        raise ValueError("dummy fixture expects the current 185 compatible-unit draft")

    special_units = [row["unit_id"] for row in compatible[:6]]
    rows: list[dict[str, Any]] = []
    policy_sha = _sha(POLICY_PATH)
    for matrix_row in compatible:
        operator_id = matrix_row["operator_id"]
        case = case_by_id[operator_id]
        unit_id = matrix_row["unit_id"]
        archive_sha = _dummy_sha("case", unit_id)
        for environment_id in ENVIRONMENTS:
            for profile_id in PROFILES:
                expected = expectation[(operator_id, profile_id)]
                row: dict[str, Any] = {
                    "row_id": f"{unit_id}--{environment_id}--{profile_id}",
                    "unit_id": unit_id,
                    "base_id": matrix_row["base_id"],
                    "operator_id": operator_id,
                    "operator_family": case["family"],
                    "operator_kind": case["kind"],
                    "stratum": matrix_row["stratum"],
                    "profile_id": profile_id,
                    "environment_id": environment_id,
                    "expected_decision": expected["expected_decision"],
                    "expected_primary_reason": expected["expected_primary_reason"],
                    "target_decision": case["target_decision"],
                    "generation_status": "GENERATED",
                    "execution_status": "TERMINAL",
                    "decision": expected["expected_decision"],
                    "primary_reason": expected["expected_primary_reason"],
                    "case_archive_sha256": archive_sha,
                    "trust_policy_sha256": policy_sha,
                    "external_reproduction": False,
                    "production_control_kind": (
                        "clean" if operator_id == "CLEAN-001"
                        else "negative" if matrix_row["stratum"] == "S2-PRODUCTION-SIGSTORE"
                        else "none"
                    ),
                }
                if unit_id == special_units[0] and environment_id == "ENV-AUTHOR":
                    row.update(
                        generation_status="GENERATION_FAILURE",
                        execution_status="MISSING_EXECUTION",
                        decision=None,
                        primary_reason=None,
                        case_archive_sha256=None,
                        trust_policy_sha256=None,
                    )
                elif (
                    unit_id == special_units[1]
                    and environment_id == "ENV-AUTHOR"
                    and profile_id == "P0"
                ):
                    row.update(
                        execution_status="MISSING_EXECUTION",
                        decision=None,
                        primary_reason=None,
                    )
                elif (
                    unit_id == special_units[2]
                    and environment_id == "ENV-AUTHOR"
                    and profile_id == "P1"
                ):
                    row.update(decision="ERROR", primary_reason="INTERNAL_ERROR")
                elif (
                    unit_id == special_units[3]
                    and environment_id == "ENV-AUTHOR"
                    and profile_id == "P2"
                ):
                    row["primary_reason"] = (
                        "JSON_INVALID" if row["expected_primary_reason"] != "JSON_INVALID" else "OK"
                    )
                elif (
                    unit_id == special_units[4]
                    and environment_id == "ENV-LINUX-PINNED"
                    and profile_id == "P3"
                ):
                    row["decision"] = "REJECT" if row["expected_decision"] == "ACCEPT" else "ACCEPT"
                    row["primary_reason"] = "SIGNATURE_INVALID" if row["decision"] == "REJECT" else "OK"
                elif (
                    unit_id == special_units[5]
                    and environment_id == "ENV-LINUX-PINNED"
                ):
                    row["case_archive_sha256"] = _dummy_sha("drift", unit_id)
                rows.append(row)

    rows.sort(
        key=lambda row: tuple(
            str(row[field]).encode("ascii")
            for field in ("base_id", "operator_id", "environment_id", "profile_id")
        )
    )
    result = {
        "schema_version": "amy.observation-ledger.v1-draft",
        "classification": "dummy_no_confirmatory_evidence",
        "design": {
            "attack_catalog_sha256": _sha(CATALOG_PATH),
            "compatibility_matrix_sha256": _sha(MATRIX_PATH),
            "oracle_sha256": _sha(ORACLE_PATH),
            "proposition_matrix_sha256": _sha(PROPOSITIONS_PATH),
            "profile_ids": list(PROFILES),
            "required_environment_ids": list(ENVIRONMENTS),
            "planned_compatibility_state": "COMPATIBLE",
            "row_order": "base_id_operator_id_environment_id_profile_id_ascii",
            "source_is_outcome_blind": True,
        },
        "rows": rows,
    }
    schema_errors = list(Draft202012Validator(schema).iter_errors(result))
    if schema_errors:
        raise ValueError(f"dummy ledger schema failure: {schema_errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rfc8785.dumps(build()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
