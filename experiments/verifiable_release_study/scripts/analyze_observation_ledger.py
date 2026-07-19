#!/usr/bin/env python3
"""Analyze a frozen finite-corpus ledger with no terminal-only denominator."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
INPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/observation-ledger.schema.json"
OUTPUT_SCHEMA_PATH = STUDY_ROOT / "schemas/analysis-summary.schema.json"
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
MATRIX_PATH = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
ORACLE_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
PROPOSITIONS_PATH = STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json"
CATEGORIES = ("ACCEPT", "REJECT", "ERROR", "MISSING_EXECUTION", "GENERATION_FAILURE")


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path, *, max_bytes: int = 16 * 1024 * 1024) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError(f"{path.name} exceeds {max_bytes} bytes")
    return json.loads(raw, object_pairs_hook=_strict_object), raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _category(row: dict[str, Any]) -> str:
    if row["generation_status"] == "GENERATION_FAILURE":
        return "GENERATION_FAILURE"
    if row["execution_status"] == "MISSING_EXECUTION":
        return "MISSING_EXECUTION"
    return str(row["decision"])


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    observed = Counter(_category(row) for row in rows)
    return {category: observed.get(category, 0) for category in CATEGORIES}


def _conformance_mismatches(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        row["row_id"]
        for row in rows
        if _category(row) not in {"ACCEPT", "REJECT"}
        or row["decision"] != row["expected_decision"]
        or row["primary_reason"] != row["expected_primary_reason"]
    )


def _authoritative_design() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    catalog, _ = _load(CATALOG_PATH)
    matrix, _ = _load(MATRIX_PATH)
    oracle, _ = _load(ORACLE_PATH)
    cases = {case["id"]: case for case in catalog["cases"]}
    units = {
        row["unit_id"]: row
        for row in matrix["rows"]
        if row["compatibility"] == "COMPATIBLE"
    }
    expectations = {
        (row["case_id"], row["profile_id"]): row for row in oracle["rows"]
    }
    if len(cases) != len(catalog["cases"]):
        raise ValueError("duplicate attack-catalog case id")
    if len(units) != sum(
        row["compatibility"] == "COMPATIBLE" for row in matrix["rows"]
    ):
        raise ValueError("duplicate compatible unit id")
    if len(expectations) != len(oracle["rows"]):
        raise ValueError("duplicate oracle case/profile row")
    return cases, units, expectations


def _validate_rows_against_frozen_design(
    rows: list[dict[str, Any]],
    environments: list[str],
    profiles: list[str],
) -> None:
    cases, units, expectations = _authoritative_design()
    observed_keys: list[tuple[str, str, str]] = []
    for row in rows:
        unit = units.get(row["unit_id"])
        if unit is None:
            raise ValueError(f"row references non-compatible unit: {row['unit_id']}")
        case = cases.get(unit["operator_id"])
        expectation = expectations.get((unit["operator_id"], row["profile_id"]))
        if case is None or expectation is None:
            raise ValueError(f"frozen design lookup failed for row: {row['row_id']}")
        expected_row_id = (
            f"{row['unit_id']}--{row['environment_id']}--{row['profile_id']}"
        )
        authoritative = {
            "row_id": expected_row_id,
            "base_id": unit["base_id"],
            "operator_id": unit["operator_id"],
            "operator_family": case["family"],
            "operator_kind": case["kind"],
            "stratum": unit["stratum"],
            "expected_decision": expectation["expected_decision"],
            "expected_primary_reason": expectation["expected_primary_reason"],
            "target_decision": case["target_decision"],
        }
        for field, expected in authoritative.items():
            if row[field] != expected:
                raise ValueError(
                    f"row differs from frozen design: {row['row_id']}:{field}"
                )
        observed_keys.append(
            (row["unit_id"], row["environment_id"], row["profile_id"])
        )

    expected_keys = {
        (unit, environment, profile)
        for unit in units
        for environment in environments
        for profile in profiles
    }
    if len(observed_keys) != len(set(observed_keys)):
        raise ValueError("duplicate unit/environment/profile observation cell")
    if set(observed_keys) != expected_keys or len(observed_keys) != len(expected_keys):
        raise ValueError(
            "ledger is not the exact compatible unit × environment × profile product"
        )

    # P0-P3 are paired views over one generated case archive. A generated
    # unit/environment may not silently substitute different case bytes by profile.
    paired: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        paired[(row["unit_id"], row["environment_id"])].append(row)
    for key, members in paired.items():
        generation_states = {row["generation_status"] for row in members}
        if len(generation_states) != 1:
            raise ValueError(
                "profile-paired rows disagree on case generation: " + "/".join(key)
            )
        generated = [
            row for row in members if row["generation_status"] == "GENERATED"
        ]
        hashes = {row["case_archive_sha256"] for row in generated}
        if len(hashes) > 1:
            raise ValueError(
                "profile-paired rows use different case archives: " + "/".join(key)
            )


def _selected_rows(proposition: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposition_id = proposition["id"]
    if proposition_id == "PR-001":
        return [row for row in rows if row["stratum"] == "S1-CONFORMANCE"]
    if proposition_id == "PR-007":
        return [row for row in rows if row["operator_id"] == "CLEAN-001"]
    if proposition_id == "PR-008":
        return [row for row in rows if row["operator_kind"] == "target_invalid"]
    if proposition_id == "PR-009":
        return rows
    if proposition_id == "PR-010":
        return [row for row in rows if row["stratum"] == "S2-PRODUCTION-SIGSTORE"]
    if proposition_id == "PR-011":
        return [row for row in rows if row["external_reproduction"]]
    if proposition_id == "PR-012":
        return []
    operator_ids = set(proposition.get("operator_ids") or [])
    profiles = set(proposition.get("profiles") or [])
    strata = set(proposition.get("strata") or [])
    return [
        row
        for row in rows
        if (not operator_ids or row["operator_id"] in operator_ids)
        and (not profiles or row["profile_id"] in profiles)
        and (not strata or row["stratum"] in strata)
    ]


def _determinism_mismatches(
    rows: list[dict[str, Any]], environments: list[str]
) -> list[str]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["unit_id"], row["profile_id"])].append(row)
    mismatches: set[str] = set()
    for members in grouped.values():
        by_environment = {row["environment_id"]: row for row in members}
        if set(by_environment) != set(environments):
            mismatches.update(row["row_id"] for row in members)
            continue
        ordered = [by_environment[environment] for environment in environments]
        first = ordered[0]
        if any(_category(row) not in {"ACCEPT", "REJECT"} for row in ordered):
            mismatches.update(row["row_id"] for row in ordered)
            continue
        if any(
            row["case_archive_sha256"] != first["case_archive_sha256"]
            or row["trust_policy_sha256"] != first["trust_policy_sha256"]
            or row["decision"] != first["decision"]
            or row["primary_reason"] != first["primary_reason"]
            for row in ordered[1:]
        ):
            mismatches.update(row["row_id"] for row in ordered)
    return sorted(mismatches)


def _target_invalid_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_rows = [row for row in rows if row["operator_kind"] == "target_invalid"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in target_rows:
        grouped[(row["profile_id"], row["operator_family"])].append(row)
    table: list[dict[str, Any]] = []
    for (profile_id, family), members in sorted(
        grouped.items(), key=lambda item: (item[0][0].encode(), item[0][1].encode())
    ):
        table.append(
            {
                "profile_id": profile_id,
                "operator_family": family,
                "planned_row_count": len(members),
                "category_counts": _counts(members),
                "accepted_unit_ids": sorted(
                    {row["unit_id"] for row in members if _category(row) == "ACCEPT"},
                    key=lambda value: value.encode("ascii"),
                ),
            }
        )
    return {
        "planned_row_count": len(target_rows),
        "category_counts": _counts(target_rows),
        "by_profile_and_family": table,
        "subtotals_reconcile": (
            sum(item["planned_row_count"] for item in table) == len(target_rows)
            and all(
                sum(item["category_counts"].values()) == item["planned_row_count"]
                for item in table
            )
        ),
        "pooled_primary_result_permitted": False,
    }


def analyze(input_path: Path) -> dict[str, Any]:
    ledger, ledger_raw = _load(input_path)
    input_schema, input_schema_raw = _load(INPUT_SCHEMA_PATH)
    output_schema, output_schema_raw = _load(OUTPUT_SCHEMA_PATH)
    propositions, proposition_raw = _load(PROPOSITIONS_PATH)
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(output_schema)
    input_errors = list(Draft202012Validator(input_schema).iter_errors(ledger))
    if input_errors:
        raise ValueError(f"observation ledger schema failure: {input_errors[0].message}")

    design = ledger["design"]
    expected_hashes = {
        "attack_catalog_sha256": _sha(CATALOG_PATH.read_bytes()),
        "compatibility_matrix_sha256": _sha(MATRIX_PATH.read_bytes()),
        "oracle_sha256": _sha(ORACLE_PATH.read_bytes()),
        "proposition_matrix_sha256": _sha(proposition_raw),
    }
    for field, expected in expected_hashes.items():
        if design[field] != expected:
            raise ValueError(f"design hash mismatch: {field}")

    rows = ledger["rows"]
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("duplicate observation row_id")
    expected_order = sorted(
        rows,
        key=lambda row: tuple(
            str(row[field]).encode("ascii")
            for field in ("base_id", "operator_id", "environment_id", "profile_id")
        ),
    )
    if rows != expected_order:
        raise ValueError("observation rows are not in frozen order")

    _validate_rows_against_frozen_design(
        rows, design["required_environment_ids"], design["profile_ids"]
    )

    category_counts = _counts(rows)
    mismatches = _conformance_mismatches(rows)
    proposition_results: list[dict[str, Any]] = []
    for proposition in propositions["propositions"]:
        selected = _selected_rows(proposition, rows)
        proposition_id = proposition["id"]
        not_evaluable_reasons: list[str] = []
        if proposition_id in {"PR-003", "PR-006"}:
            status = "NOT_EVALUABLE"
            proposition_mismatches = []
            not_evaluable_reasons = [
                "required authenticated manifest/provenance observables are not present in observation-ledger.v1"
            ]
        elif proposition_id == "PR-008":
            status = "DESCRIPTIVE_COMPLETE"
            proposition_mismatches: list[str] = []
        elif not selected:
            status = "NOT_EVALUABLE"
            proposition_mismatches = []
            not_evaluable_reasons = [
                "the required stratum or evidence class is absent from this ledger"
            ]
        elif proposition_id == "PR-009":
            proposition_mismatches = _determinism_mismatches(
                selected, design["required_environment_ids"]
            )
            status = "SUPPORTED" if not proposition_mismatches else "FALSIFIED_OR_INCOMPLETE"
        else:
            proposition_mismatches = _conformance_mismatches(selected)
            status = "SUPPORTED" if not proposition_mismatches else "FALSIFIED_OR_INCOMPLETE"
        positive = status == "SUPPORTED"
        proposition_results.append(
            {
                "id": proposition_id,
                "status": status,
                "planned_row_count": len(selected),
                "category_counts": _counts(selected),
                "mismatch_count": len(proposition_mismatches),
                "mismatch_row_ids": proposition_mismatches,
                "not_evaluable_reasons": not_evaluable_reasons,
                "would_support_positive_wording": positive,
                "abstract_eligible": False,
                "conclusion_eligible": False,
                "required_negative_wording": status in {"FALSIFIED_OR_INCOMPLETE", "NOT_EVALUABLE"},
            }
        )

    classification = ledger["classification"]
    dummy = classification == "dummy_no_confirmatory_evidence"
    required_statuses = {
        item["id"]: item["status"] for item in proposition_results
    }
    required_complete = all(
        required_statuses.get(proposition_id) == expected
        for proposition_id, expected in {
            **{f"PR-{index:03d}": "SUPPORTED" for index in range(1, 8)},
            "PR-008": "DESCRIPTIVE_COMPLETE",
            "PR-009": "SUPPORTED",
            "PR-010": "SUPPORTED",
            "PR-011": "SUPPORTED",
        }.items()
    )
    authorization_blockers = [
        "analysis summaries cannot self-authorize manuscript claims",
        "independent exact-byte review and external reproduction require separate authenticated records",
    ]
    if not required_complete:
        authorization_blockers.append(
            "one or more required propositions are unsupported, incomplete, or not evaluable"
        )
    if dummy:
        authorization_blockers.append("input is a synthetic dummy ledger")

    result = {
        "schema_version": "amy.analysis-summary.v1-draft",
        "classification": classification,
        "input_sha256": _sha(ledger_raw),
        "input_schema_sha256": _sha(input_schema_raw),
        "output_schema_sha256": _sha(output_schema_raw),
        "analyzer_sha256": _sha(Path(__file__).read_bytes()),
        "attack_catalog_sha256": expected_hashes["attack_catalog_sha256"],
        "compatibility_matrix_sha256": expected_hashes["compatibility_matrix_sha256"],
        "oracle_sha256": expected_hashes["oracle_sha256"],
        "proposition_matrix_sha256": _sha(proposition_raw),
        "planned_row_count": len(rows),
        "category_counts": category_counts,
        "category_sum_matches_denominator": sum(category_counts.values()) == len(rows),
        "terminal_only_denominator_used": False,
        "conformance_mismatch_count": len(mismatches),
        "conformance_mismatch_row_ids": mismatches,
        "target_invalid_breakdown": _target_invalid_breakdown(rows),
        "propositions": proposition_results,
        "all_required_propositions_evaluable_and_supported": required_complete,
        "authorization_blockers": authorization_blockers,
        "manuscript_claims_authorized": False,
        "read_scope": {
            "dummy_input_only": dummy,
            "confirmatory_artifacts_read": not dummy,
            "model_outputs_read": False,
            "network_used": False,
            "independent_review_performed": False,
        },
    }
    output_errors = list(Draft202012Validator(output_schema).iter_errors(result))
    if output_errors:
        raise ValueError(f"analysis output schema failure: {output_errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rfc8785.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
