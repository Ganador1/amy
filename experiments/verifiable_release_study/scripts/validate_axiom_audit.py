#!/usr/bin/env python3
"""Replay and structurally validate the retained AXIOM integrity audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_axiom_integrity import DEFAULT_REPOSITORY_ROOT, STUDY_ROOT, build_audit, canonical_json


DEFAULT_RECORD = STUDY_ROOT / "audit/AXIOM_DEEP_AUDIT_RAW_2026-07-13.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(record_path: Path, repository_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    retained = json.loads(record_path.read_text(encoding="utf-8"))
    current = build_audit(repository_root)

    if retained.get("schema_version") != "axiom.integrity-audit.v1":
        errors.append("unexpected retained schema_version")
    safety = retained.get("safety") or {}
    if any(value is not False for value in safety.values()):
        errors.append("retained audit safety declaration enables an excluded operation")

    artifact_audit = retained.get("axiom_named_json_artifacts") or {}
    summary = artifact_audit.get("summary") or {}
    artifacts = artifact_audit.get("artifacts") or []
    failures = artifact_audit.get("parse_failures") or []
    if summary.get("axiom_named_json_files") != len(artifacts) + len(failures):
        errors.append("AXIOM JSON inventory accounting does not close")
    if summary.get("parseable_json_files") != len(artifacts):
        errors.append("parseable AXIOM JSON count differs from artifact records")

    scientific = [
        record
        for record in artifacts
        if record.get("classification") not in {"monitoring_configuration", "administrative_report"}
    ]
    if summary.get("scientific_or_claim_artifacts") != len(scientific):
        errors.append("scientific/claim artifact classification accounting does not close")
    for group, summary_key in (
        ("authentication", "scientific_artifacts_with_authentication_fields"),
        ("content_digest", "scientific_artifacts_with_content_digest_fields"),
        ("dependency_identity", "scientific_artifacts_with_dependency_identity_fields"),
        ("model_immutable_identity", "scientific_artifacts_with_model_immutable_identity_fields"),
        ("provenance", "scientific_artifacts_with_provenance_fields"),
        ("raw_exchange", "scientific_artifacts_with_raw_exchange_fields"),
        ("seed", "scientific_artifacts_with_seed_fields"),
        ("source_revision", "scientific_artifacts_with_source_revision_fields"),
    ):
        expected = sum(bool((record.get("field_coverage") or {}).get(group)) for record in scientific)
        if summary.get(summary_key) != expected:
            errors.append(f"field coverage accounting differs for {group}")

    critical = retained.get("critical_claim_checks") or {}
    contradiction = critical.get("failed_upstream_but_final_true") or {}
    if contradiction.get("contradiction_count") != len(contradiction.get("contradictions") or []):
        errors.append("failed-upstream contradiction accounting does not close")
    zero_data = critical.get("zero_data_positive_reports") or {}
    if zero_data.get("count") != len(zero_data.get("reports") or []):
        errors.append("zero-data positive-report accounting does not close")
    literal_demo = critical.get("literal_multidomain_real_data_demo") or {}
    if literal_demo.get("source_literal_subtree_match_count") != len(
        literal_demo.get("source_literal_subtree_matches") or []
    ):
        errors.append("literal subtree match accounting does not close")

    boundary = (retained.get("project_boundary") or {}).get("independent_axiom_surface") or {}
    if boundary.get("console_entry_point_count") != len(
        ((retained.get("project_boundary") or {}).get("package_metadata") or {}).get("console_entry_points") or {}
    ):
        errors.append("console entry-point accounting differs")

    retained_canonical = canonical_json(retained)
    current_canonical = canonical_json(current)
    replay_matches = retained_canonical == current_canonical

    scanner_path = STUDY_ROOT / "scripts/audit_axiom_integrity.py"
    return {
        "schema_version": "axiom.integrity-audit-replay-validation.v1",
        "valid": not errors,
        "errors": errors,
        "classification": "historical_snapshot_with_current_replay",
        "command_contract": "uv run --frozen python scripts/validate_axiom_audit.py",
        "record_path": record_path.relative_to(STUDY_ROOT).as_posix(),
        "scanner_sha256": sha256(scanner_path),
        "retained_pretty_json_sha256": sha256(record_path),
        "retained_canonical_json_sha256": hashlib.sha256(retained_canonical).hexdigest(),
        "fresh_canonical_json_sha256": hashlib.sha256(current_canonical).hexdigest(),
        "byte_identical_after_canonicalization": replay_matches,
        "current_replay_matches_retained": replay_matches,
        "source_drift_detected": not replay_matches,
        "summary": {
            "axiom_named_json_files": summary.get("axiom_named_json_files"),
            "scientific_or_claim_artifacts": summary.get("scientific_or_claim_artifacts"),
            "authenticated_scientific_artifacts": summary.get(
                "scientific_artifacts_with_authentication_fields"
            ),
            "failed_upstream_but_final_true": contradiction.get("contradiction_count"),
            "zero_data_positive_reports": zero_data.get("count"),
            "literal_source_subtree_matches": literal_demo.get("source_literal_subtree_match_count"),
        },
        "limitations": [
            "The retained record is a historical snapshot; a different current replay is reported as source drift, not retroactively classified as corruption.",
            "The replay uses the same host and dirty worktree, not an independent environment.",
            "Canonical byte identity, when present, establishes deterministic replay on that snapshot, not scientific correctness of artifact contents.",
            "The audit does not execute producers or recover historical source, dependency, service, or model states.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.record.resolve(), args.repository_root.resolve())
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
