from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator

from amy_verifier.selected_profile_fixture import (
    attest_selected_manifest,
    build_selected_release_from_base,
    render_selected_fixture_payload,
    selected_fixture_policy,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
RUN = (
    STUDY_ROOT
    / "selected_profile_base_runs/r0_selected_bases_20260713T101851Z"
)
VALIDATOR = STUDY_ROOT / "scripts/validate_selected_profile_base_run.py"
COMPARISON_SCRIPT = STUDY_ROOT / "scripts/compare_selected_profile_base_runs.py"
COMPARISON = (
    STUDY_ROOT / "selected_profile_base_runs/SELECTED_RUN_COMPARISON_2026-07-13.json"
)
CURRENT_REPLAY = (
    STUDY_ROOT
    / "selected_profile_base_runs/R0_SELECTED_BASES_CURRENT_REPLAY_2026-07-13.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "selected_profile_base_run_validator", VALIDATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_source_fixture_is_a_real_deterministic_ustar() -> None:
    overlay = json.loads(
        (STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json").read_text()
    )
    fixture = overlay["payload_fixtures"]["source_snapshot"]
    raw = render_selected_fixture_payload(fixture)
    assert len(raw) == fixture["bytes"] == 10240
    assert hashlib.sha256(raw).hexdigest() == fixture["sha256"]
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = archive.getmembers()
        assert [(member.name, member.size, member.mode) for member in members] == [
            ("SNAPSHOT.txt", 45, 0o644)
        ]
        handle = archive.extractfile(members[0])
        assert handle is not None
        assert handle.read() == b"AMY selected-profile fixture source snapshot\n"


def test_selected_fixture_paths_do_not_collide_with_any_reviewed_blueprint() -> None:
    registry = json.loads((STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json").read_text())
    policy = selected_fixture_policy()
    fixture_paths = {
        fixture["path"] for fixture in policy["fixture_payloads"].values()
    }
    assert fixture_paths == {
        "payload/source/source.tar",
        "payload/provenance/dependency.lock",
    }
    for base in registry["bases"]:
        assert fixture_paths.isdisjoint(entry["path"] for entry in base["payloads"])


def test_selected_base_constructor_rejects_reserved_path_collision(
    tmp_path: Path,
) -> None:
    registry = json.loads((STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json").read_text())
    base = copy.deepcopy(registry["bases"][0])
    base["payloads"].append(
        {
            "path": "payload/source/source.tar",
            "media_type": "application/octet-stream",
            "role": "configuration",
            "recipe": {"type": "empty"},
        }
    )
    with pytest.raises(ValueError, match="fixture path collides"):
        build_selected_release_from_base(tmp_path / "release", base, selected_fixture_policy())


def test_selected_release_bytes_and_attestation_are_deterministic(tmp_path: Path) -> None:
    registry = json.loads((STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json").read_text())
    policy = selected_fixture_policy()
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        manifest = build_selected_release_from_base(root, registry["bases"][0], policy)
        assert rfc8785.dumps(manifest) == (root / "MANIFEST.jcs.json").read_bytes()
        attest_selected_manifest(root, policy)
    for relative in ("MANIFEST.jcs.json", "attestation.sigstore.json"):
        assert (roots[0] / relative).read_bytes() == (roots[1] / relative).read_bytes()


def test_selected_fixture_result_schema_vocabulary_matches_versioned_registries() -> None:
    schema = json.loads(
        (STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json").read_text()
    )
    base = json.loads((STUDY_ROOT / "protocol/REASON_CODES.json").read_text())
    extension = json.loads(
        (STUDY_ROOT / "protocol/PRODUCTION_REASON_CODES_DRAFT.json").read_text()
    )
    expected = {entry["code"] for entry in base["codes"]} | {
        entry["code"] for entry in extension["additional_codes"]
    }
    assert set(schema["$defs"]["reasonCode"]["enum"]) == expected
    assert set(schema["$defs"]["rejectReasonCode"]["enum"]) == expected - {
        "OK",
        "INTERNAL_ERROR",
    }


def test_retained_selected_profile_base_run_replays_cleanly() -> None:
    result = _load_validator().validate(RUN)
    assert result["valid"], result["errors"]
    assert result["base_count"] == 6
    assert result["confirmatory_cases_generated"] is False
    assert result["confirmatory_outcomes_read"] is False
    assert result["production_sigstore_conformance"] is False
    assert result["retained_source_archive_self_valid"] is True
    assert result["retained_source_matches_current_study"] is False
    assert result["retained_source_drift_paths"] == [
        "amy_verifier/github_attestation.py",
        "amy_verifier/selected_profile_fixture.py",
        "scripts/validate_selected_profile_base_run.py",
    ]
    assert len(result["warnings"]) == 1
    assert "retained source snapshot differs" in result["warnings"][0]


def test_current_replay_record_preserves_internal_validity_and_discloses_source_drift() -> None:
    retained = json.loads(CURRENT_REPLAY.read_text(encoding="utf-8"))
    fresh = _load_validator().validate(RUN)
    assert retained == fresh
    assert retained["valid"] is True
    assert retained["retained_source_archive_self_valid"] is True
    assert retained["retained_source_matches_current_study"] is False
    assert len(retained["retained_source_drift_paths"]) == 3


def test_all_24_retained_clean_results_use_the_closed_fixture_schema() -> None:
    schema = json.loads(
        (STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    paths = sorted(RUN.glob("bases/*/clean_results/P*.json"))
    assert len(paths) == 24
    for path in paths:
        result = json.loads(path.read_text())
        assert list(validator.iter_errors(result)) == []
        assert (result["decision"], result["primary_reason"]) == ("ACCEPT", "OK")


def test_terminology_hardening_run_preserves_all_base_archive_and_result_bytes() -> None:
    spec = importlib.util.spec_from_file_location(
        "selected_profile_run_comparison", COMPARISON_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    retained = json.loads(COMPARISON.read_text())
    fresh = module.compare()
    assert fresh == retained
    assert retained["valid"] is True
    assert retained["base_archive_and_result_inventories_identical"] is True
    assert retained["source_archive_sha256"]["identical"] is False
    assert retained["confirmatory_cases_generated"] is False
