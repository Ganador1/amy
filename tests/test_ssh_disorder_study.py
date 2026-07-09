from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.run.run_ssh_disorder_study import (
    _paper_sections,
    build_manifest,
    evaluate_hypotheses,
    parse_atlas_report,
    sha256_file,
    validate_preregistration_hash,
    verify_manifest,
    write_condition_tables,
)


PREREG_HASH = "a" * 64


def _atlas_report(preregistration_hash: str = PREREG_HASH) -> str:
    return "\n".join(
        [
            "SSH disorder diagnostic benchmark:",
            "  seed_derivation=sha256",
            "  paired_orientations=true",
            "  primary_estimand=error_gap_minus_error_joint",
            "  namespace=primary",
            "  protocol_sha256=" + "b" * 64,
            f"  preregistration_sha256={preregistration_hash}",
            "  Condition summaries:",
            "    summary; namespace=primary; disorder_type=off_diagonal; "
            "n=20; delta=0.1; strength=0.2; "
            "effective_realizations_per_orientation=8; "
            "reference_label=random_ssh_log_geometric_mean; total=16; "
            "gap_accuracy=0.625; joint_accuracy=0.875; "
            "gap_positive_rate=not_defined; joint_positive_rate=not_defined; "
            "error_gap_minus_error_joint=0.25; "
            "gap_wrong_joint_right=4; gap_right_joint_wrong=0; "
            "mcnemar_pvalue=0.125",
            "    summary; namespace=primary; disorder_type=diagonal; "
            "n=20; delta=0.1; strength=0.2; "
            "effective_realizations_per_orientation=8; "
            "reference_label=not_defined; total=16; "
            "gap_accuracy=not_defined; joint_accuracy=not_defined; "
            "gap_positive_rate=0.5; joint_positive_rate=0.25; "
            "error_gap_minus_error_joint=not_defined; "
            "gap_wrong_joint_right=not_defined; "
            "gap_right_joint_wrong=not_defined; mcnemar_pvalue=not_defined",
            "  pooled; namespace=primary; disorder_type=off_diagonal; "
            "reference_label=random_ssh_log_geometric_mean; total=100; "
            "gap_accuracy=0.70; gap_accuracy_ci95=0.60,0.78; "
            "joint_accuracy=0.82; joint_accuracy_ci95=0.73,0.88; "
            "error_gap_minus_error_joint=0.12; "
            "error_difference_ci95=0.04,0.20; "
            "gap_wrong_joint_right=20; gap_right_joint_wrong=8; "
            "mcnemar_pvalue=0.035; "
            "reference_label_flips_from_clean_parent=3",
        ]
    )


def test_sha256_file_hashes_exact_bytes(tmp_path):
    target = tmp_path / "value.txt"
    target.write_bytes(b"amy\n")

    assert sha256_file(target) == hashlib.sha256(b"amy\n").hexdigest()


def test_parse_atlas_report_preserves_condition_and_pooled_fields():
    parsed = parse_atlas_report(_atlas_report())

    assert parsed["namespace"] == "primary"
    assert parsed["protocol_sha256"] == "b" * 64
    assert parsed["preregistration_sha256"] == PREREG_HASH
    assert len(parsed["summaries"]) == 2
    assert parsed["summaries"][0]["n"] == 20
    assert parsed["summaries"][0]["gap_accuracy"] == pytest.approx(0.625)
    assert parsed["summaries"][1]["gap_accuracy"] is None
    assert parsed["summaries"][1]["reference_label"] == "not_defined"
    assert parsed["pooled"]["error_difference_ci95"] == [0.04, 0.20]
    assert parsed["pooled"]["gap_wrong_joint_right"] == 20


def test_validate_preregistration_hash_rejects_mismatch():
    parsed = parse_atlas_report(_atlas_report("c" * 64))

    with pytest.raises(ValueError, match="preregistration hash mismatch"):
        validate_preregistration_hash(parsed, PREREG_HASH)


def test_write_condition_tables_combines_labeled_runs(tmp_path):
    primary = parse_atlas_report(_atlas_report())
    replication = parse_atlas_report(
        _atlas_report().replace("namespace=primary", "namespace=replication")
    )

    paths = write_condition_tables(
        tmp_path,
        {"primary": primary, "replication": replication},
    )

    rows = json.loads(paths["json"].read_text(encoding="utf-8"))
    with paths["csv"].open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["run"] for row in rows} == {"primary", "replication"}
    assert len(csv_rows) == 4
    assert {row["run"] for row in csv_rows} == {"primary", "replication"}


def test_evaluate_hypotheses_reports_support_and_failed_replication():
    primary = parse_atlas_report(_atlas_report())["pooled"]
    replication = dict(primary)
    replication.update(
        {
            "error_gap_minus_error_joint": -0.02,
            "mcnemar_pvalue": 0.7,
        }
    )

    decision = evaluate_hypotheses(primary, replication, alpha=0.05)

    assert decision["H1_primary_supported"] is True
    assert decision["H1_replication_supported"] is False
    assert decision["H2_replication_supported"] is False
    assert "failed" in decision["plain_language"].lower()


def test_manifest_uses_relative_paths_and_detects_tampering(tmp_path):
    first = tmp_path / "a.txt"
    second_dir = tmp_path / "nested"
    second_dir.mkdir()
    second = second_dir / "b.json"
    first.write_text("alpha", encoding="utf-8")
    second.write_text('{"beta": 2}\n', encoding="utf-8")

    manifest = build_manifest(tmp_path, [first, second])

    text = manifest.read_text(encoding="utf-8")
    assert "  a.txt" in text
    assert "  nested/b.json" in text
    assert str(tmp_path) not in text
    assert verify_manifest(tmp_path, manifest)["ok"] is True

    second.write_text('{"beta": 3}\n', encoding="utf-8")
    verification = verify_manifest(tmp_path, manifest)
    assert verification["ok"] is False
    assert verification["failed"] == ["nested/b.json"]


def test_study_sections_make_nonclaims_and_falsification_explicit():
    parsed = parse_atlas_report(_atlas_report())
    decision = evaluate_hypotheses(parsed["pooled"], parsed["pooled"], alpha=0.05)

    sections = _paper_sections(
        preregistration_sha256=PREREG_HASH,
        runs={"primary": parsed, "replication": parsed},
        decision=decision,
        experiment_ids=["primary_experiment", "replication_experiment"],
        literature_result={"papers": []},
    )
    by_heading = {section["heading"]: section["content"] for section in sections}

    assert "does not claim" in by_heading["Discussion"].lower()
    assert "Testable Predictions" in by_heading
    assert "H1." in by_heading["Testable Predictions"]
    assert "Testable via:" in by_heading["Testable Predictions"]
