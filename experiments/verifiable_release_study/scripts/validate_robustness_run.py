#!/usr/bin/env python3
"""Validate the retained cross-platform S0 robustness engineering record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD = (
    STUDY_ROOT / "robustness_runs/engineering_20260713T072737Z/RESULT.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = DEFAULT_RECORD) -> dict[str, Any]:
    errors: list[str] = []
    record = load_json(path)
    catalog = load_json(STUDY_ROOT / "protocol/ROBUSTNESS_CATALOG_DRAFT.json")
    bases = load_json(STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json")

    if record.get("classification") != (
        "exploratory_pre_registration_engineering_not_confirmatory_evidence"
    ):
        errors.append("retained run has an invalid evidence classification")
    if record.get("confirmatory") is not False:
        errors.append("retained robustness run must be non-confirmatory")

    cases = catalog.get("cases") or []
    implemented = [
        case for case in cases if case.get("coverage_state") == "IMPLEMENTED"
    ]
    if len(implemented) != len(cases):
        errors.append("current robustness catalog contains unimplemented cases")
    if record.get("scheduled_case_count") != len(cases):
        errors.append("recorded scheduled-case count differs from catalog")
    if record.get("direct_test_count") != len(implemented):
        errors.append("recorded direct-test count differs from implemented catalog")

    expected_sources = record.get("source_sha256") or {}
    for relative, expected in expected_sources.items():
        candidate = STUDY_ROOT / relative
        if not candidate.is_file():
            errors.append(f"retained source path does not exist: {relative}")
        elif sha256(candidate) != expected:
            errors.append(f"retained source hash mismatch: {relative}")

    planned_linux = next(
        environment
        for environment in bases["planned_environments"]
        if environment["id"] == "ENV-LINUX-PINNED"
    )
    runs = record.get("runs") or []
    run_ids = {run.get("environment_id") for run in runs if isinstance(run, dict)}
    if run_ids != {"ENV-AUTHOR", "ENV-LINUX-PINNED"}:
        errors.append("retained run does not cover exactly both planned environments")
    for run in runs:
        if not isinstance(run, dict):
            errors.append("run entries must be objects")
            continue
        environment_id = run.get("environment_id")
        if run.get("exit_code") != 0:
            errors.append(f"{environment_id}: nonzero test exit")
        output = run.get("stdout")
        if not isinstance(output, str) or re.search(r"12 passed in [0-9.]+s", output) is None:
            errors.append(f"{environment_id}: unexpected pytest summary")
        if run.get("direct_test_count") != 12:
            errors.append(f"{environment_id}: direct-test count is not 12")
        if environment_id == "ENV-LINUX-PINNED":
            if run.get("image") != planned_linux.get("image"):
                errors.append("Linux test image differs from the base registry")
            if run.get("network_isolation_enforced") is not True:
                errors.append("Linux test run did not enforce network isolation")
            if run.get("repository_mount") != "read_only":
                errors.append("Linux test run did not mount the study read-only")

    comparison = record.get("cross_environment_comparison") or {}
    if comparison.get("same_exit_code") is not True:
        errors.append("cross-environment exit codes differ")
    if comparison.get("same_passed_test_count") is not True:
        errors.append("cross-environment passed-test counts differ")
    if comparison.get("byte_identical_stdout") is not False:
        errors.append("timing-bearing pytest stdout must not be labeled byte-identical")

    return {
        "valid": not errors,
        "record_sha256": sha256(path),
        "scheduled_case_count": len(cases),
        "implemented_case_count": len(implemented),
        "environment_count": len(runs),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", nargs="?", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.record)
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
