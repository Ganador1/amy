from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from amy_verifier.selected_profile_fixture import (
    apply_selected_profile_mutation,
    attest_selected_manifest,
    build_clean_selected_release,
    selected_fixture_policy,
    verify_selected_fixture_release,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _result(root: Path, policy: dict, profile: str) -> tuple[str, str]:
    result = verify_selected_fixture_release(root, profile_id=profile, policy=policy)
    return result["decision"], result["primary_reason"]


def test_selected_fixture_policy_is_fully_instantiated_and_explicitly_nonproduction() -> None:
    policy = selected_fixture_policy()
    all_text = str(policy)
    assert "TBD-BEFORE-REGISTRATION" not in all_text
    assert policy["fixture_overlay"]["cryptographic_boundary"][
        "production_sigstore_conformance"
    ] is False
    assert policy["statement"]["attestation_mode"] == (
        "actions_attest_default_slsa_provenance"
    )
    assert "materials" not in policy["provenance"]
    snapshot = policy["provenance"]["manifest_assertions"]["source"]["snapshot"]
    assert snapshot["assurance"] == (
        "exact-opaque-bytes-no-git-tree-equivalence-claim"
    )


def test_selected_fixture_clean_release_is_accepted_by_all_four_profiles(
    tmp_path: Path,
) -> None:
    policy = selected_fixture_policy()
    build_clean_selected_release(tmp_path, policy)
    attest_selected_manifest(tmp_path, policy)
    for profile in ("P0", "P1", "P2", "P3"):
        assert _result(tmp_path, policy, profile) == ("ACCEPT", "OK")


@pytest.mark.parametrize(
    ("case_id", "p1", "p3_reason"),
    [
        ("PREDICATE-WRONG-TYPE-001", ("ACCEPT", "OK"), "PREDICATE_TYPE_UNSUPPORTED"),
        ("SOURCE-WRONG-REVISION-001", ("ACCEPT", "OK"), "SOURCE_MISMATCH"),
        ("WORKFLOW-PARAMETER-MISMATCH-001", ("ACCEPT", "OK"), "BUILDER_UNAUTHORIZED"),
        ("BUILDER-PREDICATE-MISMATCH-001", ("ACCEPT", "OK"), "BUILDER_UNAUTHORIZED"),
        ("BUILD-DIRTY-001", ("ACCEPT", "OK"), "DIRTY_BUILD"),
        ("SOURCE-TREE-MISMATCH-001", ("ACCEPT", "OK"), "MATERIAL_MISMATCH"),
        ("MATERIAL-LOCK-MISMATCH-001", ("ACCEPT", "OK"), "MATERIAL_MISMATCH"),
        ("SNAPSHOT-DIGEST-MISMATCH-001", ("ACCEPT", "OK"), "MATERIAL_MISMATCH"),
        ("SNAPSHOT-ROLE-MISMATCH-001", ("ACCEPT", "OK"), "MATERIAL_MISMATCH"),
        ("EXECUTION-IMAGE-MISMATCH-001", ("ACCEPT", "OK"), "MATERIAL_MISMATCH"),
        ("BUILD-METADATA-MISSING-001", ("REJECT", "SCHEMA_INVALID"), "PROVENANCE_INVALID"),
    ],
)
def test_selected_fixture_mutations_preserve_p2_ablation_and_enforce_p3(
    tmp_path: Path,
    case_id: str,
    p1: tuple[str, str],
    p3_reason: str,
) -> None:
    policy = selected_fixture_policy()
    build_clean_selected_release(tmp_path, policy)
    attest_selected_manifest(tmp_path, policy)
    apply_selected_profile_mutation(case_id, tmp_path, policy)

    assert _result(tmp_path, policy, "P0") == ("ACCEPT", "OK")
    assert _result(tmp_path, policy, "P1") == p1
    assert _result(tmp_path, policy, "P2") == ("ACCEPT", "OK")
    assert _result(tmp_path, policy, "P3") == ("REJECT", p3_reason)


def test_selected_fixture_addition_does_not_modify_retained_v03_contract_hashes() -> None:
    expected = {
        "protocol/REASON_CODES.json": (
            "5ea73e4cea02ec265fadeb2995879ef0c8dad99e0308212b67e5a8e9bc89b02b"
        ),
        "schemas/verifier-result.schema.json": (
            "73e7ef19b85a27a497f9f15c6f1c4e34c8d6efcb8ad54522124321c214b01f35"
        ),
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((STUDY_ROOT / relative).read_bytes()).hexdigest() == digest
