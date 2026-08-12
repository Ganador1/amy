#!/usr/bin/env python3
"""Replay and structurally validate the retained A.M.Y integrity audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_amy_integrity import DEFAULT_REPOSITORY_ROOT, STUDY_ROOT, build_audit, canonical_json


DEFAULT_RECORD = STUDY_ROOT / "audit/AMY_DEEP_AUDIT_RAW_2026-07-13.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(record_path: Path, repository_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    retained = json.loads(record_path.read_text(encoding="utf-8"))
    current = build_audit(repository_root)

    if retained.get("schema_version") != "amy.integrity-audit.v1":
        errors.append("unexpected retained schema_version")
    safety = retained.get("safety") or {}
    if any(value is not False for key, value in safety.items() if key != "mutates_audited_artifacts"):
        errors.append("retained safety declaration contains an enabled hazardous operation")
    if safety.get("mutates_audited_artifacts") is not False:
        errors.append("retained audit does not declare read-only behavior")

    directory = retained.get("directory_provenance") or {}
    directory_summary = directory.get("summary") or {}
    if directory_summary.get("provenance_records") != (
        directory_summary.get("stored_output_sha256_matches_current_bytes", 0)
        + directory_summary.get("stored_output_sha256_mismatches", 0)
        + len(directory.get("malformed_stored_output_digests") or [])
        + len(directory.get("parse_failures") or [])
    ):
        errors.append("directory provenance digest accounting does not close")
    if directory_summary.get("authenticated_records") != len(
        directory.get("authenticated_record_paths") or []
    ):
        errors.append("authenticated directory-provenance accounting differs")

    flat = retained.get("flat_experiments") or {}
    flat_summary = flat.get("summary") or {}
    if flat_summary.get("records") != (
        flat_summary.get("identifier_recomputation_matches", 0)
        + flat_summary.get("identifier_failures", 0)
        + len(flat.get("parse_failures") or [])
    ):
        errors.append("flat experiment identifier accounting does not close")

    publication = (retained.get("publication_manifests") or {}).get("summary") or {}
    if publication.get("referenced_files") != (
        publication.get("referenced_files_present", 0)
        + publication.get("referenced_files_missing", 0)
    ):
        errors.append("publication manifest reference accounting does not close")

    checksum = (retained.get("checksum_release_manifests") or {}).get("summary") or {}
    if checksum.get("entries") != (
        checksum.get("current_digest_matches", 0)
        + checksum.get("current_digest_failures", 0)
    ):
        errors.append("checksum manifest accounting does not close")

    retained_canonical = canonical_json(retained)
    current_canonical = canonical_json(current)
    replay_matches = retained_canonical == current_canonical

    scanner_path = STUDY_ROOT / "scripts/audit_amy_integrity.py"
    return {
        "schema_version": "amy.integrity-audit-replay-validation.v1",
        "valid": not errors,
        "errors": errors,
        "classification": "historical_snapshot_with_current_replay",
        "command_contract": "uv run --frozen python scripts/validate_amy_audit.py",
        "record_path": record_path.relative_to(STUDY_ROOT).as_posix(),
        "scanner_sha256": sha256(scanner_path),
        "retained_pretty_json_sha256": sha256(record_path),
        "retained_canonical_json_sha256": hashlib.sha256(retained_canonical).hexdigest(),
        "fresh_canonical_json_sha256": hashlib.sha256(current_canonical).hexdigest(),
        "byte_identical_after_canonicalization": replay_matches,
        "current_replay_matches_retained": replay_matches,
        "source_drift_detected": not replay_matches,
        "summary": {
            "directory_provenance_records": directory_summary.get("provenance_records"),
            "directory_output_digest_matches": directory_summary.get(
                "stored_output_sha256_matches_current_bytes"
            ),
            "directory_authenticated_records": directory_summary.get("authenticated_records"),
            "flat_experiment_records": flat_summary.get("records"),
            "publication_manifests": publication.get("manifest_files"),
            "checksum_entries": checksum.get("entries"),
        },
        "limitations": [
            "The retained record is a historical snapshot; a different current replay is reported as source drift, not retroactively classified as corruption.",
            "The replay uses the same host and dirty working tree, not an independent environment.",
            "Canonical byte identity, when present, establishes deterministic replay on that snapshot, not correctness of every interpretation.",
            "The audit recomputes present bytes; it does not recover historical bytes or authenticate mutable local declarations.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.record.resolve(), args.repository_root.resolve())
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
            indent=None if args.compact else 2,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
