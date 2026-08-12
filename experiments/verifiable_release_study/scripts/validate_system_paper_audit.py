#!/usr/bin/env python3
"""Replay and structurally validate the retained A.M.Y system-paper audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_system_paper_integrity import (
    DEFAULT_PAPER_WORKTREE,
    DEFAULT_REPOSITORY_ROOT,
    STUDY_ROOT,
    build_audit,
    canonical_json,
)


DEFAULT_RECORD = STUDY_ROOT / "audit/AMY_SYSTEM_PAPER_DEEP_AUDIT_RAW_2026-07-13.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(record_path: Path, repository_root: Path, paper_worktree: Path) -> dict[str, Any]:
    errors: list[str] = []
    retained = json.loads(record_path.read_text(encoding="utf-8"))
    current = build_audit(repository_root, paper_worktree)

    if retained.get("schema_version") != "amy.system-paper-integrity-audit.v1":
        errors.append("unexpected retained schema_version")
    safety = retained.get("safety") or {}
    if any(value is not False for value in safety.values()):
        errors.append("retained audit safety declaration enables an excluded operation")

    integrity = retained.get("release_integrity") or {}
    committed = (integrity.get("committed_head") or {}).get("manifest") or {}
    working = (integrity.get("current_worktree") or {}).get("manifest") or {}
    for label, result in (("committed", committed), ("working", working)):
        entries = int(result.get("entries", 0))
        accounted = (
            int(result.get("matches", 0))
            + len(result.get("missing") or [])
            + len(result.get("mismatches") or [])
        )
        if entries != accounted:
            errors.append(f"{label} manifest accounting does not close")

    benchmark = retained.get("benchmark") or {}
    design = benchmark.get("design_accounting") or {}
    if design.get("run_rows") != sum((design.get("arms") or {}).values()):
        errors.append("benchmark arm accounting does not close")
    schema = benchmark.get("response_and_schema_audit") or {}
    if schema.get("exact_response_contents") != design.get("run_rows"):
        errors.append("response-content accounting differs from run rows")

    inference = benchmark.get("recomputed_inference") or {}
    primary = inference.get("primary") or {}
    if primary.get("complete_pairs") != 60:
        errors.append("unexpected primary complete-pair count")
    secondary = inference.get("secondary") or {}
    unsupported = secondary.get("unsupported_decimal_present") or {}
    for level in ("case_cluster_sensitivity", "domain_cluster_sensitivity"):
        value = ((unsupported.get(level) or {}).get("exact_two_sided_sign_flip_pvalue"))
        if not isinstance(value, (int, float)) or value < 0.05:
            errors.append(f"unsupported-decimal {level} no longer matches retained non-robust conclusion")

    retained_canonical = canonical_json(retained)
    current_canonical = canonical_json(current)
    replay_matches = retained_canonical == current_canonical
    replay_status = current.get("replay_status") or {}

    scanner_path = STUDY_ROOT / "scripts/audit_system_paper_integrity.py"
    return {
        "schema_version": "amy.system-paper-integrity-audit-replay-validation.v1",
        "valid": not errors,
        "errors": errors,
        "classification": "historical_snapshot_with_current_replay",
        "command_contract": "uv run --frozen python scripts/validate_system_paper_audit.py",
        "record_path": record_path.relative_to(STUDY_ROOT).as_posix(),
        "scanner_sha256": sha256(scanner_path),
        "retained_pretty_json_sha256": sha256(record_path),
        "retained_canonical_json_sha256": hashlib.sha256(retained_canonical).hexdigest(),
        "fresh_canonical_json_sha256": hashlib.sha256(current_canonical).hexdigest(),
        "byte_identical_after_canonicalization": replay_matches,
        "current_replay_matches_retained": replay_matches,
        "source_drift_detected": not replay_matches,
        "current_replay_complete": replay_status.get("complete", True),
        "current_replay_missing_required_inputs": replay_status.get(
            "missing_required_inputs", []
        ),
        "summary": {
            "committed_manifest_valid": committed.get("valid"),
            "working_manifest_valid": working.get("valid"),
            "working_manifest_mismatches": len(working.get("mismatches") or []),
            "benchmark_rows": design.get("run_rows"),
            "strict_schema_type_violations": len(schema.get("strict_schema_type_violations") or []),
            "abstract_word_range_violations": schema.get("abstract_word_range_violations"),
            "conclusion_word_range_violations": schema.get("conclusion_word_range_violations"),
            "unsupported_decimal_case_cluster_pvalue": (
                (unsupported.get("case_cluster_sensitivity") or {}).get(
                    "exact_two_sided_sign_flip_pvalue"
                )
            ),
            "unsupported_decimal_domain_cluster_pvalue": (
                (unsupported.get("domain_cluster_sensitivity") or {}).get(
                    "exact_two_sided_sign_flip_pvalue"
                )
            ),
        },
        "limitations": [
            "The retained record is a historical snapshot; a different or unavailable current replay is disclosed rather than retroactively classified as corruption.",
            "A missing local paper worktree makes the current replay incomplete and authorizes no finding; absence is never treated as validation success.",
            "When available, replay is on the same host and paper worktree, not an independent environment.",
            "Canonical identity validates deterministic audit replay, not scientific truth.",
            "Any legitimate paper-worktree edit requires a new retained audit revision rather than overwriting this record.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--paper-worktree", type=Path, default=DEFAULT_PAPER_WORKTREE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(
        args.record.resolve(),
        args.repository_root.resolve(),
        args.paper_worktree.resolve(),
    )
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
