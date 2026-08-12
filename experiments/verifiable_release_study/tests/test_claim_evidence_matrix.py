from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest


STUDY_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = STUDY_ROOT / "evidence/CLAIM_EVIDENCE_MATRIX.csv"
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_claim_evidence_matrix.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("claim_matrix_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _read_rows(path: Path = MATRIX_PATH) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return reader.fieldnames, list(reader)


def _write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _mutated_matrix(
    tmp_path: Path, mutator, *, source: Path = MATRIX_PATH
) -> Path:
    fields, rows = _read_rows(source)
    mutator(fields, rows)
    output = tmp_path / "matrix.csv"
    _write_rows(output, fields, rows)
    return output


def _refs(row: dict[str, str]) -> list[dict[str, str]]:
    return json.loads(row["current_evidence"])


def _set_refs(row: dict[str, str], refs: list[dict[str, str]]) -> None:
    row["current_evidence"] = json.dumps(
        refs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _copy_evidence_tree(tmp_path: Path) -> Path:
    root = tmp_path / "study"
    root.mkdir()
    _, rows = _read_rows()
    for row in rows:
        for reference in _refs(row):
            relative = Path(reference["path"])
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(STUDY_ROOT / relative, destination)
    return root


def test_retained_claim_evidence_matrix_is_valid() -> None:
    result = VALIDATOR.validate_claim_evidence_matrix()
    assert result["valid"] is True, result["errors"]
    assert result["claim_count"] == 47
    assert result["allowed_claim_count"] == 40
    assert result["resolved_reference_count"] >= 40
    assert result["boundaries"]["scientific_claims_authorized_by_validator"] is False


def test_duplicate_claim_id_is_rejected(tmp_path: Path) -> None:
    matrix = _mutated_matrix(
        tmp_path, lambda _fields, rows: rows[1].__setitem__("claim_id", "C001")
    )
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("claim IDs" in error or "duplicate claim" in error for error in result["errors"])


def test_extra_csv_column_is_rejected(tmp_path: Path) -> None:
    def mutate(fields, rows):
        fields.append("unexpected")
        for row in rows:
            row["unexpected"] = "x"

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert "CSV header" in result["errors"][0]


def test_allowed_claim_without_references_is_rejected(tmp_path: Path) -> None:
    matrix = _mutated_matrix(
        tmp_path, lambda _fields, rows: rows[0].__setitem__("current_evidence", "[]")
    )
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("allowed claim has no evidence" in error for error in result["errors"])


def test_non_authorized_claim_with_reference_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        _set_refs(rows[5], _refs(rows[0]))

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("non-authorized claim" in error for error in result["errors"])


def test_noncanonical_reference_json_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        rows[0]["current_evidence"] = json.dumps(_refs(rows[0]), indent=2)

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("canonical JSON" in error for error in result["errors"])


def test_unknown_reference_field_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        refs = _refs(rows[0])
        refs[0]["comment"] = "not part of the closed reference contract"
        _set_refs(rows[0], refs)

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("exact keys" in error for error in result["errors"])


def test_duplicate_key_in_reference_json_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        rows[0]["current_evidence"] = rows[0]["current_evidence"].replace(
            '"sha256":', '"sha256":"' + "0" * 64 + '","sha256":', 1
        )

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("DuplicateKeyError" in error for error in result["errors"])


@pytest.mark.parametrize("bad_path", ["../outside.json", "/tmp/outside.json", "audit\\file.json"])
def test_unsafe_evidence_path_is_rejected(tmp_path: Path, bad_path: str) -> None:
    def mutate(_fields, rows):
        refs = _refs(rows[0])
        refs[0]["path"] = bad_path
        _set_refs(rows[0], refs)

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("path" in error for error in result["errors"])


def test_symlinked_evidence_file_is_rejected(tmp_path: Path) -> None:
    root = _copy_evidence_tree(tmp_path)
    link = root / "linked-evidence.md"
    link.symlink_to(root / "audit/BASELINE_AUDIT_2026-07-13.md")

    fields, rows = _read_rows()
    refs = _refs(rows[0])
    refs[0]["path"] = "linked-evidence.md"
    _set_refs(rows[0], refs)
    matrix = root / "matrix.csv"
    _write_rows(matrix, fields, rows)

    result = VALIDATOR.validate_claim_evidence_matrix(matrix, study_root=root)
    assert result["valid"] is False
    assert any("symlinks are forbidden" in error for error in result["errors"])


def test_sha256_mismatch_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        refs = _refs(rows[0])
        refs[0]["sha256"] = "0" * 64
        _set_refs(rows[0], refs)

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("SHA-256 mismatch" in error for error in result["errors"])


def test_missing_json_pointer_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        row = next(row for row in rows if row["claim_id"] == "C043")
        refs = _refs(row)
        refs[0]["locator"] = "json_pointer:/does/not/exist"
        _set_refs(row, refs)

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("KeyError" in error for error in result["errors"])


def test_nonunique_line_anchor_is_rejected(tmp_path: Path) -> None:
    root = _copy_evidence_tree(tmp_path)
    baseline = root / "audit/BASELINE_AUDIT_2026-07-13.md"
    anchor = "| F01 | Historical A.M.Y output hashes are internally consistent | 1,653/1,653 `output.txt` SHA-256 values matched `tool.output_hash`; no missing outputs | Strong evidence of current byte consistency, but not signer authenticity |"
    baseline.write_text(baseline.read_text(encoding="utf-8") + anchor + "\n", encoding="utf-8")

    fields, rows = _read_rows()
    digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
    for row in rows:
        refs = _refs(row)
        changed = False
        for ref in refs:
            if ref["path"] == "audit/BASELINE_AUDIT_2026-07-13.md":
                ref["sha256"] = digest
                changed = True
        if changed:
            _set_refs(row, refs)
    matrix = root / "matrix.csv"
    _write_rows(matrix, fields, rows)

    result = VALIDATOR.validate_claim_evidence_matrix(matrix, study_root=root)
    assert result["valid"] is False
    assert any("line anchor must resolve exactly once" in error for error in result["errors"])


def test_duplicate_key_in_referenced_json_is_rejected(tmp_path: Path) -> None:
    root = _copy_evidence_tree(tmp_path)
    source = root / "pilot_runs/PILOT_RETENTION_SUMMARY_2026-07-18.json"
    source.write_text(
        '{"retained_summary":{"result_count":136,"result_count":136}}\n',
        encoding="utf-8",
    )

    fields, rows = _read_rows()
    row = next(row for row in rows if row["claim_id"] == "C013")
    refs = _refs(row)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for ref in refs:
        ref["sha256"] = digest
    _set_refs(row, refs)
    matrix = root / "matrix.csv"
    _write_rows(matrix, fields, rows)

    result = VALIDATOR.validate_claim_evidence_matrix(matrix, study_root=root)
    assert result["valid"] is False
    assert any("DuplicateKeyError" in error for error in result["errors"])


def test_c005_requires_all_three_primary_source_anchors(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        row = next(row for row in rows if row["claim_id"] == "C005")
        _set_refs(row, _refs(row)[:2])

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("C005" in error and "S01-S03" in error for error in result["errors"])


def test_c043_narrative_count_drift_is_rejected(tmp_path: Path) -> None:
    def mutate(_fields, rows):
        row = next(row for row in rows if row["claim_id"] == "C043")
        row["provisional_claim"] = row["provisional_claim"].replace(
            "185 compatible", "186 compatible"
        )

    matrix = _mutated_matrix(tmp_path, mutate)
    result = VALIDATOR.validate_claim_evidence_matrix(matrix)
    assert result["valid"] is False
    assert any("claim counts" in error for error in result["errors"])


def test_c043_source_count_drift_is_rejected_even_with_updated_hash(tmp_path: Path) -> None:
    root = _copy_evidence_tree(tmp_path)
    source = root / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["compatibility_counts"]["COMPATIBLE"] = 184
    source.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    fields, rows = _read_rows()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    for row in rows:
        refs = _refs(row)
        changed = False
        for ref in refs:
            if ref["path"] == "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json":
                ref["sha256"] = digest
                changed = True
        if changed:
            _set_refs(row, refs)
    matrix = root / "matrix.csv"
    _write_rows(matrix, fields, rows)

    result = VALIDATOR.validate_claim_evidence_matrix(matrix, study_root=root)
    assert result["valid"] is False
    assert any("claim counts" in error for error in result["errors"])
