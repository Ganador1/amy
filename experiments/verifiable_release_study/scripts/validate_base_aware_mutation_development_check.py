#!/usr/bin/env python3
"""Validate the retained base-aware mutation development receipt."""

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
    STUDY_ROOT / "development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-13.json"
)
SCHEMA_PATH = STUDY_ROOT / "schemas/base-aware-mutation-development-check.schema.json"


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate(record_path: Path = DEFAULT_RECORD) -> dict[str, Any]:
    errors: list[str] = []
    record_raw = record_path.read_bytes()
    record = _strict_json(record_raw)
    schema_raw = SCHEMA_PATH.read_bytes()
    schema = _strict_json(schema_raw)
    Draft202012Validator.check_schema(schema)
    errors.extend(
        "schema: " + error.message
        for error in Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(record)
    )
    inventory = record.get("source_inventory") or []
    paths = [item.get("path") for item in inventory if isinstance(item, dict)]
    if paths != sorted(paths, key=lambda value: str(value).encode("utf-8")):
        errors.append("source inventory is not UTF-8-bytewise sorted")
    if len(paths) != len(set(paths)):
        errors.append("source inventory contains duplicate paths")
    for item in inventory:
        if not isinstance(item, dict):
            errors.append("source inventory item is not an object")
            continue
        path = STUDY_ROOT / str(item.get("path"))
        if path.is_symlink() or not path.is_file():
            errors.append(f"source is not a regular non-symlink file: {item.get('path')}")
            continue
        raw = path.read_bytes()
        if item.get("bytes") != len(raw) or item.get("sha256") != _sha(raw):
            errors.append(f"source inventory drift: {item.get('path')}")
    inventory_sha = _sha(rfc8785.dumps(inventory))
    if (
        record.get("source_inventory_pre_sha256") != inventory_sha
        or record.get("source_inventory_post_sha256") != inventory_sha
        or record.get("source_inventory_unchanged_during_execution") is not True
    ):
        errors.append("pre/post source inventory identity differs")
    execution = record.get("execution") or {}
    stdout = execution.get("stdout")
    stderr = execution.get("stderr")
    if not isinstance(stdout, str) or execution.get("stdout_sha256") != _sha(
        stdout.encode("utf-8") if isinstance(stdout, str) else b""
    ):
        errors.append("stdout hash differs")
    if not isinstance(stderr, str) or execution.get("stderr_sha256") != _sha(
        stderr.encode("utf-8") if isinstance(stderr, str) else b""
    ):
        errors.append("stderr hash differs")
    match = re.search(r"(?:^|\s)(\d+) passed(?:[,\s]|$)", stdout or "")
    passed = int(match.group(1)) if match else None
    if execution.get("exit_code") != 0 or passed != 4:
        errors.append("base-aware test execution does not report exactly four passes")
    boundaries = record.get("boundaries") or {}
    if not boundaries or any(value is not False for value in boundaries.values()):
        errors.append("base-aware receipt boundary is not uniformly false")
    if record.get("decision") != "NO-GO":
        errors.append("base-aware receipt does not retain NO-GO")
    try:
        record_display_path = record_path.relative_to(STUDY_ROOT).as_posix()
    except ValueError:
        record_display_path = str(record_path)
    return {
        "schema_version": "amy.base-aware-mutation-development-validation.v1-draft",
        "valid": not errors,
        "errors": errors,
        "record_path": record_display_path,
        "record_sha256": _sha(record_raw),
        "schema_sha256": _sha(schema_raw),
        "validator_sha256": _sha(Path(__file__).read_bytes()),
        "source_inventory_count": len(inventory),
        "passed_test_count": passed,
        "resolved_plan_count": (record.get("declared_coverage") or {}).get(
            "resolved_plan_count"
        ),
        "unavailable_plan_count": (record.get("declared_coverage") or {}).get(
            "unavailable_plan_count"
        ),
        "confirmatory_evidence": False,
        "independent_review_performed": False,
        "manuscript_claims_authorized": False,
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
