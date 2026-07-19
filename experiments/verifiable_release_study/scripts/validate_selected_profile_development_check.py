#!/usr/bin/env python3
"""Validate the retained selected-profile development-check record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD = (
    STUDY_ROOT
    / "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-13.json"
)
DEFAULT_SCHEMA = STUDY_ROOT / "schemas/selected-profile-development-check.schema.json"


class DuplicateKeyError(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=strict_object,
        parse_constant=reject_constant,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate(record_path: Path = DEFAULT_RECORD) -> dict[str, Any]:
    errors: list[str] = []
    record = strict_json(record_path.read_bytes())
    schema = strict_json(DEFAULT_SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    schema_errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(record),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors.extend(f"schema: {error.message}" for error in schema_errors)

    inventory = record.get("source_inventory") or []
    inventory_paths = [entry.get("path") for entry in inventory if isinstance(entry, dict)]
    if inventory_paths != sorted(
        inventory_paths, key=lambda value: str(value).encode("utf-8")
    ):
        errors.append("source inventory is not UTF-8-bytewise sorted")
    if len(inventory_paths) != len(set(inventory_paths)):
        errors.append("source inventory contains duplicate paths")
    for entry in inventory:
        if not isinstance(entry, dict):
            errors.append("source inventory item is not an object")
            continue
        path = STUDY_ROOT / str(entry.get("path"))
        if path.is_symlink() or not path.is_file():
            errors.append(
                f"source inventory path is not a regular non-symlink file: "
                f"{entry.get('path')}"
            )
            continue
        raw = path.read_bytes()
        if entry.get("bytes") != len(raw) or entry.get("sha256") != sha256_bytes(raw):
            errors.append(f"source inventory bytes differ: {entry.get('path')}")
    inventory_sha256 = sha256_bytes(rfc8785.dumps(inventory))
    if (
        record.get("source_inventory_pre_sha256") != inventory_sha256
        or record.get("source_inventory_post_sha256") != inventory_sha256
        or record.get("source_inventory_unchanged_during_execution") is not True
    ):
        errors.append("pre/post source inventory identity differs")

    execution = record.get("execution") or {}
    stdout = str(execution.get("stdout", "")).encode("utf-8")
    stderr = str(execution.get("stderr", "")).encode("utf-8")
    if execution.get("stdout_sha256") != sha256_bytes(stdout):
        errors.append("stdout hash differs")
    if execution.get("stderr_sha256") != sha256_bytes(stderr):
        errors.append("stderr hash differs")
    if execution.get("exit_code") != 0:
        errors.append("development check did not exit zero")
    match = re.search(r"(?:^|\s)(\d+) passed(?:[,\s]|$)", stdout.decode("utf-8"))
    pytest_passed_count = int(match.group(1)) if match else None
    if pytest_passed_count != 6:
        errors.append("development-check stdout does not report exactly six passed tests")
    if stderr:
        errors.append("development check emitted stderr")

    coverage = record.get("declared_coverage") or {}
    expected_coverage = {
        "catalog_case_count": 41,
        "oracle_row_count": 164,
        "development_case_profile_evaluations": 164,
        "semantic_authenticated_pointer_isolation_cases": 11,
        "same_environment_tree_replay_cases": 41,
    }
    if coverage != expected_coverage:
        errors.append("declared development coverage differs")
    boundaries = record.get("boundaries") or {}
    if not boundaries or any(value is not False for value in boundaries.values()):
        errors.append("development-check boundary is not uniformly false")

    runner = STUDY_ROOT / "scripts/run_selected_profile_development_checks.py"
    validator = STUDY_ROOT / "scripts/validate_selected_profile_development_check.py"
    try:
        record_display_path = record_path.relative_to(STUDY_ROOT).as_posix()
    except ValueError:
        record_display_path = str(record_path)
    return {
        "schema_version": "amy.selected-profile-development-check-validation.v2-draft",
        "valid": not errors,
        "errors": errors,
        "record_path": record_display_path,
        "record_sha256": sha256(record_path),
        "schema_sha256": sha256(DEFAULT_SCHEMA),
        "runner_sha256": sha256(runner),
        "validator_sha256": sha256(validator),
        "pytest_passed_count": pytest_passed_count,
        "catalog_case_count": coverage.get("catalog_case_count"),
        "oracle_row_count": coverage.get("oracle_row_count"),
        "development_case_profile_evaluations": coverage.get(
            "development_case_profile_evaluations"
        ),
        "source_inventory_count": len(inventory),
        "source_inventory_unchanged_during_execution": (
            record.get("source_inventory_unchanged_during_execution") is True
        ),
        "confirmatory_evidence": False,
        "production_sigstore_conformance": False,
        "independent_oracle_review": False,
        "limitations": [
            "The record is a same-author development execution under deterministic public test PKI.",
            "Passing against a same-author draft oracle does not independently validate its labels.",
            "No six-base confirmatory case archive or real A.M.Y P3 result is created by this command.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.record.resolve())
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
