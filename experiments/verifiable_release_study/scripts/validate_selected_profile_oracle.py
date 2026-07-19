#!/usr/bin/env python3
"""Validate selected oracle replay and module separation without running cases."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


STUDY_ROOT_BOOTSTRAP = Path(__file__).resolve().parents[1]
if str(STUDY_ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT_BOOTSTRAP))

from amy_verifier.selected_profile_mutations import SUPPORTED_CASE_IDS
from amy_verifier.selected_profile_oracle import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_RESULT_SCHEMA_PATH,
    STUDY_ROOT,
    build_selected_profile_oracle,
)


DEFAULT_ORACLE = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
DEFAULT_SCHEMA = STUDY_ROOT / "schemas/selected-profile-oracle.schema.json"


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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def validate(
    oracle_path: Path = DEFAULT_ORACLE,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    errors: list[str] = []
    retained = _load_json_strict(oracle_path, errors, "selected oracle")
    fresh = build_selected_profile_oracle()
    schema = _load_json_strict(schema_path, errors, "selected-oracle schema")
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(retained),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(f"schema: {error.message}" for error in schema_errors)
    result_schema = _load_json_strict(
        DEFAULT_RESULT_SCHEMA_PATH, errors, "selected-profile result schema"
    )
    oracle_reason_vocabulary = set(
        schema.get("$defs", {})
        .get("oracleRow", {})
        .get("properties", {})
        .get("expected_primary_reason", {})
        .get("enum", [])
    )
    result_reason_vocabulary = set(
        result_schema.get("$defs", {}).get("reasonCode", {}).get("enum", [])
    )
    if oracle_reason_vocabulary != result_reason_vocabulary - {"INTERNAL_ERROR"}:
        errors.append("oracle reason vocabulary differs from the result contract")
    if retained != fresh:
        errors.append("retained oracle differs from deterministic catalog-only replay")

    rows = retained.get("rows") or []
    row_keys = [(row.get("case_id"), row.get("profile_id")) for row in rows]
    if len(rows) != 164 or len(set(row_keys)) != 164:
        errors.append("oracle must contain 164 unique case/profile rows")
    if {case_id for case_id, _ in row_keys} != set(SUPPORTED_CASE_IDS):
        errors.append("oracle case IDs differ from the 41-case generator surface")
    if retained.get("case_count") != 41 or retained.get("row_count") != 164:
        errors.append("oracle count fields differ")

    boundary = retained.get("derivation_boundary") or {}
    required_false = {
        "observed_results_read",
        "confirmatory_cases_read",
        "confirmatory_cases_executed",
        "target_decisions_used_as_profile_expectations",
        "implementation_behavior_used_to_generate_rows",
        "independent_human_review_complete",
    }
    if any(boundary.get(key) is not False for key in required_false):
        errors.append("oracle derivation/review boundary is not fail-closed")
    forbidden_keys = {
        "observed_decision",
        "observed_primary_reason",
        "observed_result",
        "profile_conforms",
        "target_decision",
    }
    present_forbidden = sorted(forbidden_keys & set(_walk_keys(retained)))
    if present_forbidden:
        errors.append(f"oracle contains forbidden outcome fields: {present_forbidden}")

    source = retained.get("source_catalog") or {}
    result_contract = retained.get("result_contract") or {}
    if source.get("sha256") != sha256(DEFAULT_CATALOG_PATH):
        errors.append("oracle source-catalog hash differs")
    if result_contract.get("sha256") != sha256(DEFAULT_RESULT_SCHEMA_PATH):
        errors.append("oracle result-contract hash differs")

    module_paths = {
        "generator": STUDY_ROOT / "amy_verifier/selected_profile_mutations.py",
        "verifier": STUDY_ROOT / "amy_verifier/selected_profile_fixture.py",
        "oracle": STUDY_ROOT / "amy_verifier/selected_profile_oracle.py",
        "evaluator": STUDY_ROOT / "amy_verifier/selected_profile_evaluator.py",
    }
    oracle_imports = _imports(module_paths["oracle"])
    if any(
        name.endswith(
            (
                "selected_profile_mutations",
                "selected_profile_fixture",
                "selected_profile_evaluator",
            )
        )
        for name in oracle_imports
    ):
        errors.append("oracle module imports generator, verifier, or evaluator")
    evaluator_imports = _imports(module_paths["evaluator"])
    if any(name.startswith("amy_verifier") for name in evaluator_imports):
        errors.append("evaluator derives behavior from another A.M.Y module")

    builder_path = STUDY_ROOT / "scripts/build_selected_profile_oracle.py"
    validator_path = STUDY_ROOT / "scripts/validate_selected_profile_oracle.py"
    return {
        "schema_version": "amy.selected-profile-oracle-validation.v1-draft",
        "valid": not errors,
        "errors": errors,
        "oracle_path": _display_path(oracle_path),
        "oracle_sha256": sha256(oracle_path),
        "schema_path": _display_path(schema_path),
        "schema_sha256": sha256(schema_path),
        "catalog_sha256": sha256(DEFAULT_CATALOG_PATH),
        "result_schema_sha256": sha256(DEFAULT_RESULT_SCHEMA_PATH),
        "case_count": len({case_id for case_id, _ in row_keys}),
        "row_count": len(rows),
        "module_sha256": {name: sha256(path) for name, path in module_paths.items()},
        "builder_sha256": sha256(builder_path),
        "validator_sha256": sha256(validator_path),
        "module_separation_static_check": not any(
            "module" in error for error in errors
        ),
        "confirmatory_outcomes_read": False,
        "confirmatory_cases_executed": False,
        "development_fixture_cases_executed_by_this_validator": False,
        "independent_human_review_complete": False,
        "limitations": [
            "The oracle is a deterministic rendering of same-author catalog expectations, not independent validation of those expectations.",
            "This validator performs static/replay checks only and does not execute a mutation or verifier.",
            "Development tests may exercise temporary public-PKI fixtures, but no result from them is confirmatory evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.oracle.resolve(), args.schema.resolve())
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
