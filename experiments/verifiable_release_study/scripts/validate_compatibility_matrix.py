#!/usr/bin/env python3
"""Validate that compatibility is complete, structural, and outcome-blind."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.base_corpus import sha256_file


DEFAULT_MATRIX = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_DRAFT.json"
BASE_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
PREREQUISITES = STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_DRAFT.json"
CATALOG = STUDY_ROOT / "protocol/ATTACK_CATALOG.json"
BASE_RUN_VALIDATION = (
    STUDY_ROOT / "base_pilot_runs/r0_bases_20260713T065228Z/validation.json"
)
FORBIDDEN_ROW_KEYS = {
    "profile_expectations",
    "expected_decision",
    "expected_primary_reason",
    "observed_decision",
    "target_decision",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(matrix_path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    errors: list[str] = []
    matrix = load_json(matrix_path)
    bases = load_json(BASE_REGISTRY)
    prerequisites = load_json(PREREQUISITES)
    catalog = load_json(CATALOG)
    base_run_validation = load_json(BASE_RUN_VALIDATION)

    expected_hashes = {
        "base_registry": sha256_file(BASE_REGISTRY),
        "prerequisite_registry": sha256_file(PREREQUISITES),
        "attack_catalog": sha256_file(CATALOG),
        "base_run_validation": sha256_file(BASE_RUN_VALIDATION),
    }
    if matrix.get("input_sha256") != expected_hashes:
        errors.append("matrix input hashes differ from current draft inputs")
    if matrix.get("classification") != "R0_metadata_only_no_case_generation_or_execution":
        errors.append("matrix is not classified as R0 metadata only")
    for flag in (
        "uses_profile_expectations",
        "uses_observed_decisions",
        "uses_target_decisions",
    ):
        if matrix.get(flag) is not False:
            errors.append(f"matrix outcome-blinding flag is not false: {flag}")
    if base_run_validation.get("valid") is not True:
        errors.append("referenced clean-base validation is not valid")

    prerequisite_by_id = {entry["id"]: entry for entry in prerequisites["prerequisites"]}
    base_by_id = {base["id"]: base for base in bases["bases"]}
    case_by_id = {case["id"]: case for case in catalog["cases"]}
    expected_pairs = [
        (base_id, case_id)
        for base_id in sorted(base_by_id, key=lambda value: value.encode("ascii"))
        for case_id in sorted(case_by_id, key=lambda value: value.encode("ascii"))
    ]
    rows = matrix.get("rows") or []
    observed_pairs = [(row.get("base_id"), row.get("operator_id")) for row in rows]
    if observed_pairs != expected_pairs:
        errors.append("matrix rows are not the complete sorted base × operator Cartesian product")
    if matrix.get("candidate_unit_count") != len(expected_pairs):
        errors.append("candidate unit count differs from Cartesian product")
    unit_ids = [row.get("unit_id") for row in rows]
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("duplicate compatibility unit IDs")

    state_counts: Counter[str] = Counter()
    for row in rows:
        base_id = row.get("base_id")
        operator_id = row.get("operator_id")
        case = case_by_id.get(operator_id)
        base = base_by_id.get(base_id)
        if case is None or base is None:
            continue
        forbidden_present = FORBIDDEN_ROW_KEYS & set(row)
        if forbidden_present:
            errors.append(
                f"{row.get('unit_id')}: contains outcome/expectation fields {sorted(forbidden_present)}"
            )
        expected_metadata = {
            "unit_id": f"{base_id}--{operator_id}",
            "stratum": "S1-CONFORMANCE",
            "base_release_kind": base["release"]["kind"],
            "operator_family": case["family"],
            "operator_kind": case["kind"],
        }
        for field, expected in expected_metadata.items():
            if row.get(field) != expected:
                errors.append(f"{row.get('unit_id')}: metadata mismatch for {field}")
        evaluations = row.get("prerequisites") or []
        if [entry.get("id") for entry in evaluations] != case["prerequisites"]:
            errors.append(f"{row.get('unit_id')}: prerequisite order/set mismatch")
        states: list[str] = []
        for evaluation in evaluations:
            prerequisite = prerequisite_by_id.get(evaluation.get("id"))
            state = evaluation.get("state")
            states.append(state)
            if prerequisite is None:
                errors.append(f"{row.get('unit_id')}: unknown prerequisite")
                continue
            draft_state = prerequisite["draft_state"]
            if draft_state == "BASE_DERIVED":
                if state not in {"TRUE", "FALSE"}:
                    errors.append(f"{row.get('unit_id')}: invalid derived state {state!r}")
            elif state != draft_state:
                errors.append(
                    f"{row.get('unit_id')}: static state {state!r} != {draft_state!r}"
                )
        expected_compatibility = (
            "NOT_COMPATIBLE"
            if "FALSE" in states
            else "PENDING"
            if "PENDING" in states
            else "COMPATIBLE"
        )
        compatibility = row.get("compatibility")
        state_counts[compatibility] += 1
        if compatibility != expected_compatibility:
            errors.append(f"{row.get('unit_id')}: compatibility resolution mismatch")
        expected_false = sorted(
            entry["id"] for entry in evaluations if entry.get("state") == "FALSE"
        )
        expected_pending = sorted(
            entry["id"] for entry in evaluations if entry.get("state") == "PENDING"
        )
        if row.get("blocking_false") != expected_false:
            errors.append(f"{row.get('unit_id')}: false blocker list mismatch")
        if row.get("blocking_pending") != expected_pending:
            errors.append(f"{row.get('unit_id')}: pending blocker list mismatch")

    expected_counts = {
        state: state_counts.get(state, 0)
        for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
    }
    if matrix.get("compatibility_counts") != expected_counts:
        errors.append("compatibility summary counts differ from rows")
    if matrix.get("planned_if_all_pending_resolve_true") != (
        expected_counts["COMPATIBLE"] + expected_counts["PENDING"]
    ):
        errors.append("conditional planned-unit count differs from rows")
    return {
        "valid": not errors,
        "matrix_sha256": sha256_file(matrix_path),
        "candidate_unit_count": len(rows),
        "compatibility_counts": expected_counts,
        "outcome_blinded": not any(FORBIDDEN_ROW_KEYS & set(row) for row in rows),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", nargs="?", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.matrix)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
