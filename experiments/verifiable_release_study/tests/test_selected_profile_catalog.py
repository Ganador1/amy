from __future__ import annotations

import importlib.util
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = STUDY_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_profile_catalog_replays_without_reading_outcomes(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    validator = _load_script("validate_selected_profile_catalog")
    result = validator.validate(
        STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json",
        STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json",
    )
    assert result["valid"], result["errors"]
    assert result["summary"]["confirmatory_outcomes_read"] is False
    assert result["summary"]["confirmatory_cases_executed"] is False
    assert result["summary"]["historical_case_count"] == 34
    assert result["summary"]["selected_case_count"] == 41
    assert result["summary"]["added_case_count"] == 7
    assert result["summary"]["implemented_generator_case_count"] == 41


def test_selected_profile_catalog_preserves_p2_ablation_and_opaque_snapshot_scope(
    monkeypatch,
) -> None:
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    builder = _load_script("build_selected_profile_catalog")
    catalog = builder.build_catalog()
    by_id = {case["id"]: case for case in catalog["cases"]}
    migrated = _load_script("validate_selected_profile_catalog").MIGRATED_CASE_IDS
    for case_id in migrated:
        assert by_id[case_id]["profile_expectations"]["P2"] == {
            "decision": "ACCEPT",
            "primary_reason": "OK",
        }
        assert by_id[case_id]["profile_expectations"]["P3"]["decision"] == "REJECT"
    assert catalog["manifest_contract"]["source_snapshot_assurance"] == (
        "exact-opaque-bytes-no-git-tree-equivalence-claim"
    )
    assert catalog["profile_selection"]["custom_slsa_materials"] is False


def test_catalog_validator_rejects_duplicate_json_object_names(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    retained = (
        STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
    ).read_text(encoding="utf-8")
    duplicate = retained.replace(
        '  "catalog_version": "0.4.0-draft",',
        '  "catalog_version": "0.4.0-draft",\n'
        '  "catalog_version": "ambiguous-duplicate",',
        1,
    )
    assert duplicate != retained
    path = tmp_path / "duplicate-catalog.json"
    path.write_text(duplicate, encoding="utf-8")

    validator = _load_script("validate_selected_profile_catalog")
    result = validator.validate(
        path,
        STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json",
    )
    assert result["valid"] is False
    assert any("duplicate JSON object name" in error for error in result["errors"])


def test_oracle_validator_rejects_duplicate_json_object_names(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(STUDY_ROOT / "scripts"))
    retained = (
        STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
    ).read_text(encoding="utf-8")
    duplicate = retained.replace(
        '  "case_count": 41,',
        '  "case_count": 41,\n  "case_count": 999,',
        1,
    )
    assert duplicate != retained
    path = tmp_path / "duplicate-oracle.json"
    path.write_text(duplicate, encoding="utf-8")

    validator = _load_script("validate_selected_profile_oracle")
    result = validator.validate(path)
    assert result["valid"] is False
    assert any("duplicate JSON object name" in error for error in result["errors"])
