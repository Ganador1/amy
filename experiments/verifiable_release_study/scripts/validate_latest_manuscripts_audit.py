#!/usr/bin/env python3
"""Replay and structurally validate the recent-manuscript audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_latest_manuscripts import (
    DEFAULT_PAPER_WORKTREE,
    DEFAULT_REPOSITORY_ROOT,
    STUDY_ROOT,
    build_audit,
    canonical_json,
)


DEFAULT_RECORD = STUDY_ROOT / "audit/LATEST_MANUSCRIPTS_DEEP_AUDIT_RAW_2026-07-13.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(record_path: Path, repository_root: Path, paper_worktree: Path) -> dict[str, Any]:
    errors: list[str] = []
    retained = json.loads(record_path.read_text(encoding="utf-8"))
    current = build_audit(repository_root, paper_worktree)

    if retained.get("schema_version") != "amy.latest-manuscripts-audit.v2":
        errors.append("unexpected retained schema_version")
    safety = retained.get("safety") or {}
    if any(value is not False for value in safety.values()):
        errors.append("retained safety declaration enables an excluded operation")

    revised = retained.get("amy_revised_benchmark") or {}
    revised_provenance = revised.get("provenance_summary") or {}
    if revised.get("exact_source_data_path_count") != 24:
        errors.append("A.M.Y source record selector no longer yields 24 records")
    if revised.get("all_current_replication_prefix_records") != 96:
        errors.append("A.M.Y prefix ambiguity count changed")
    if revised_provenance.get("preview_hash_matches") != 24:
        errors.append("not all 24 A.M.Y retained outputs match their SHA-256")
    revised_references = revised.get("reference_audit") or {}
    if revised_references.get("stodden_year_matches_official_record") is not False:
        errors.append("unexpected Stodden citation-year audit result")
    for field in (
        "authentication_fields",
        "source_revision_fields",
        "dependency_identity_fields",
        "seed_fields",
    ):
        if revised_provenance.get(field) != 0:
            errors.append(f"A.M.Y provenance boundary changed for {field}")

    axiom = retained.get("axiom_meta4_paper") or {}
    if axiom.get("all_three_are_byte_identical") is not True:
        errors.append("AXIOM paper copies are no longer byte-identical")
    if axiom.get("appendix_placeholder_count") != 11:
        errors.append("unexpected AXIOM appendix placeholder count")
    if any((axiom.get("supporting_json_contains_claimed_scores") or {}).values()):
        errors.append("AXIOM support JSON unexpectedly contains paper scores")

    dna = retained.get("amy_latest_dna_paper") or {}
    if dna.get("missing_declared_artifact_count") != 4:
        errors.append("unexpected missing DNA publication-artifact count")
    if dna.get("literal_reasoning_tag_leaks") != 1:
        errors.append("unexpected DNA reasoning-tag leak count")
    if dna.get("duplicated_discussion_anchor_count") != 2:
        errors.append("unexpected DNA duplicated-discussion count")
    dna_literature = dna.get("closest_literature_audit") or {}
    if dna_literature.get("declared_novelty_audit_artifact_present") is not False:
        errors.append("DNA novelty-audit artifact boundary changed")
    dna_pdf = dna.get("pdf_visual_review") or {}
    if dna_pdf.get("review_applies_to_current_pdf_bytes") is not True:
        errors.append("manual DNA PDF review no longer applies to current bytes")
    if dna_pdf.get("content_equivalent_to_markdown") is not False:
        errors.append("unexpected DNA PDF content-equivalence audit result")

    bond = retained.get("atlas_bond_energy_paper") or {}
    bond_provenance = bond.get("provenance_summary") or {}
    if bond_provenance.get("records") != 8 or bond_provenance.get("preview_hash_matches") != 8:
        errors.append("bond-energy provenance accounting changed")
    if bond_provenance.get("environment_present") != 0:
        errors.append("bond-energy records unexpectedly gained environment fields")

    references = retained.get("formal_system_paper_references") or {}
    if references.get("bibliography_entry_count") != 14:
        errors.append("formal-paper bibliography count changed")
    if references.get("undefined_citations") or references.get("uncited_bibliography_entries"):
        errors.append("formal-paper citation-key accounting does not close")
    discrepancies = references.get("metadata_discrepancies") or []
    if len(discrepancies) != 1 or discrepancies[0].get("key") != "wang2026provenance":
        errors.append("unexpected formal-paper metadata discrepancy set")

    retained_canonical = canonical_json(retained)
    current_canonical = canonical_json(current)
    replay_matches = retained_canonical == current_canonical
    replay_status = current.get("replay_status") or {}

    scanner_path = STUDY_ROOT / "scripts/audit_latest_manuscripts.py"
    return {
        "schema_version": "amy.latest-manuscripts-audit-replay-validation.v2",
        "valid": not errors,
        "errors": errors,
        "classification": "historical_snapshot_with_current_replay",
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
            "amy_intended_records": revised.get("exact_source_data_path_count"),
            "amy_prefix_records": revised.get("all_current_replication_prefix_records"),
            "axiom_placeholders": axiom.get("appendix_placeholder_count"),
            "dna_missing_artifacts": dna.get("missing_declared_artifact_count"),
            "dna_pdf_reviewed_sha256": dna_pdf.get("reviewed_pdf_sha256"),
            "bond_records": bond_provenance.get("records"),
            "formal_reference_entries": references.get("bibliography_entry_count"),
        },
        "limitations": [
            "The retained record is a historical snapshot; a different current replay is reported as source drift, not retroactively classified as corruption.",
            "A current replay with missing local-only inputs is incomplete and authorizes no finding; absence is never treated as successful validation.",
            "Replay is on the same host and current dirty repository bytes, not an independent audit.",
            "The external reference metadata comparison is a curated 2026-07-13 snapshot.",
            "Canonical replay establishes deterministic accounting, not scientific truth or authorship.",
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
