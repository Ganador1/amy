from __future__ import annotations

import importlib.util
import json
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_DRAFT.json"
BUILDER_PATH = STUDY_ROOT / "scripts/build_compatibility_matrix.py"
VALIDATOR_PATH = STUDY_ROOT / "scripts/validate_compatibility_matrix.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compatibility_matrix_is_complete_and_outcome_blinded() -> None:
    result = _load(VALIDATOR_PATH, "compatibility_validator").validate(MATRIX_PATH)
    assert result["valid"], result["errors"]
    assert result["candidate_unit_count"] == 204
    assert result["compatibility_counts"] == {
        "COMPATIBLE": 174,
        "PENDING": 24,
        "NOT_COMPATIBLE": 6,
    }
    assert result["outcome_blinded"] is True


def test_retained_matrix_equals_fresh_deterministic_builder_output() -> None:
    builder = _load(BUILDER_PATH, "compatibility_builder")
    fresh = builder.build_matrix(
        builder.DEFAULT_BASE_REGISTRY,
        builder.DEFAULT_PREREQUISITES,
        builder.DEFAULT_CATALOG,
        builder.DEFAULT_BASE_RUN,
    )
    retained = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert fresh == retained


def test_s1_public_keyless_transparency_rows_are_not_mislabeled_as_failures() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    rows = [
        row for row in matrix["rows"] if row["operator_id"] == "TRANSPARENCY-MISSING-001"
    ]
    assert len(rows) == 6
    assert {row["compatibility"] for row in rows} == {"NOT_COMPATIBLE"}
    assert all(row["blocking_false"] == ["public_keyless_profile_frozen"] for row in rows)


def test_pending_rows_are_not_counted_as_frozen_compatible_units() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert matrix["status"] == "draft_with_pending_prerequisites_not_frozen"
    assert matrix["compatibility_counts"]["PENDING"] == 24
    assert matrix["planned_if_all_pending_resolve_true"] == 198
