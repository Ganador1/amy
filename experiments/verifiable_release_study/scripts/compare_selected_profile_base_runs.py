#!/usr/bin/env python3
"""Compare two retained selected-profile R0 runs without executing a verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIRST = (
    STUDY_ROOT
    / "selected_profile_base_runs/r0_selected_bases_20260713T095915Z"
)
DEFAULT_SECOND = (
    STUDY_ROOT
    / "selected_profile_base_runs/r0_selected_bases_20260713T101851Z"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for top_level in ("archives", "bases"):
        directory = root / top_level
        for path in sorted(
            (candidate for candidate in directory.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix().encode("utf-8"),
        ):
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    return records


def compare(first: Path = DEFAULT_FIRST, second: Path = DEFAULT_SECOND) -> dict[str, Any]:
    first_summary = load_json(first / "summary.json")
    second_summary = load_json(second / "summary.json")
    first_validation = load_json(first / "validation.json")
    second_validation = load_json(second / "validation.json")
    first_inventory = inventory(first)
    second_inventory = inventory(second)
    first_records = {
        record["base_id"]: record for record in first_summary["base_records"]
    }
    second_records = {
        record["base_id"]: record for record in second_summary["base_records"]
    }
    compared_fields = [
        "archive_bytes",
        "archive_sha256",
        "attestation_sha256",
        "blueprint_payload_count",
        "clean_profile_results",
        "injected_fixture_payload_count",
        "manifest_sha256",
        "release_kind",
        "total_payload_count",
        "tree_sha256",
    ]
    base_comparisons = []
    for base_id in sorted(set(first_records) | set(second_records)):
        first_record = first_records.get(base_id) or {}
        second_record = second_records.get(base_id) or {}
        mismatched_fields = [
            field
            for field in compared_fields
            if first_record.get(field) != second_record.get(field)
        ]
        base_comparisons.append(
            {
                "base_id": base_id,
                "compared_fields": compared_fields,
                "mismatched_fields": mismatched_fields,
                "identical": not mismatched_fields,
            }
        )
    errors: list[str] = []
    if first_validation.get("valid") is not True:
        errors.append("first retained run validation is not valid")
    if second_validation.get("valid") is not True:
        errors.append("second retained run validation is not valid")
    if first_inventory != second_inventory:
        errors.append("base/archive/result file inventories differ")
    if not all(record["identical"] for record in base_comparisons):
        errors.append("one or more summary base records differ")
    for label, summary in (("first", first_summary), ("second", second_summary)):
        if summary.get("confirmatory_cases_generated") is not False:
            errors.append(f"{label} run generated confirmatory cases")
        if summary.get("confirmatory_outcomes_read") is not False:
            errors.append(f"{label} run read confirmatory outcomes")
        if summary.get("production_sigstore_conformance") is not False:
            errors.append(f"{label} run is mislabeled as production Sigstore")
    return {
        "schema_version": "amy.selected-profile-base-run-comparison.v1-draft",
        "valid": not errors,
        "classification": "same_environment_R0_release_output_comparison",
        "first_run": first.relative_to(STUDY_ROOT).as_posix(),
        "second_run": second.relative_to(STUDY_ROOT).as_posix(),
        "first_summary_sha256": sha256(first / "summary.json"),
        "second_summary_sha256": sha256(second / "summary.json"),
        "first_validation_sha256": sha256(first / "validation.json"),
        "second_validation_sha256": sha256(second / "validation.json"),
        "base_count": len(base_comparisons),
        "compared_file_count": len(first_inventory),
        "base_comparisons": base_comparisons,
        "base_archive_and_result_inventories_identical": (
            first_inventory == second_inventory
        ),
        "source_archive_sha256": {
            "first": first_summary.get("source_archive_sha256"),
            "second": second_summary.get("source_archive_sha256"),
            "identical": first_summary.get("source_archive_sha256")
            == second_summary.get("source_archive_sha256"),
        },
        "reason_for_second_run": (
            "The validator terminology was narrowed from independent to separate "
            "same-worktree replay; the first run was retained rather than overwritten."
        ),
        "confirmatory_cases_generated": False,
        "confirmatory_outcomes_read": False,
        "production_sigstore_conformance": False,
        "errors": errors,
        "limitations": [
            "This is a same-environment byte comparison, not independent reproduction.",
            "Identical controlled-fixture outputs do not establish production Sigstore conformance."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, default=DEFAULT_FIRST)
    parser.add_argument("--second", type=Path, default=DEFAULT_SECOND)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = compare(args.first.resolve(), args.second.resolve())
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
