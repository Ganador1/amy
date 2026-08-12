from __future__ import annotations

import hashlib
import json
import posixpath
import tempfile
from pathlib import Path

import rfc8785

from amy_verifier.selected_profile_fixture import (
    attest_selected_manifest,
    build_selected_release_from_base,
    selected_fixture_policy,
)
from amy_verifier.selected_profile_mutations import (
    MutationPlan,
    MutationPlanUnavailable,
    apply_selected_profile_mutation,
    mutation_observation,
    resolve_mutation_plan,
    snapshot_tree,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
BASE_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
CATALOG = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"

PRIMARY_CASES = {
    "CONTENT-BITFLIP-001",
    "CONTENT-TRUNCATE-001",
    "CONTENT-SAME-SIZE-001",
    "PATH-DUPLICATE-NORMALIZED-001",
    "PATH-NONREGULAR-001",
    "PATH-SYMLINK-001",
    "SUBSTITUTION-COHERENT-001",
    "SUBSTITUTION-UNAUTHORIZED-001",
}
PRIMARY_TREE_MUTATION_CASES = PRIMARY_CASES - {"PATH-DUPLICATE-NORMALIZED-001"}
TARGET_DEPENDENT_CASES = PRIMARY_CASES | {
    "INVENTORY-MISSING-001",
    "INVENTORY-OMIT-ROLE-001",
    "PATH-HARDLINK-001",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_246_base_operator_plans_resolve_or_fail_structurally_without_outcomes() -> None:
    bases = _load(BASE_REGISTRY)["bases"]
    cases = _load(CATALOG)["cases"]
    policy = selected_fixture_policy()
    plans: list[MutationPlan] = []
    unavailable: list[tuple[str, str, str]] = []
    for base in bases:
        payload_by_path = {item["path"]: item for item in base["payloads"]}
        targets = base["mutation_targets"]
        for case in cases:
            try:
                plan = resolve_mutation_plan(case["id"], base=base, policy=policy)
            except MutationPlanUnavailable as exc:
                unavailable.append((base["id"], case["id"], exc.reason_code))
                continue
            plans.append(plan)
            record = plan.record()
            assert plan.base_id == base["id"]
            assert plan.case_id == case["id"]
            assert plan.sha256() == hashlib.sha256(rfc8785.dumps(record)).hexdigest()
            assert record["contains_expected_or_observed_decisions"] is False
            assert record["confirmatory_evidence"] is False
            assert not {
                "decision",
                "primary_reason",
                "expected_decision",
                "expected_primary_reason",
                "oracle_row",
                "observed_result",
            } & set(record)

            if case["id"] in PRIMARY_CASES:
                assert plan.target_path == targets["primary_nonempty_payload"]
            elif case["id"] == "INVENTORY-MISSING-001":
                assert plan.target_path == targets["nested_payload"]
            elif case["id"] == "INVENTORY-OMIT-ROLE-001":
                assert plan.target_path == targets["sole_required_role_payload"]
                assert plan.target_role == payload_by_path[plan.target_path]["role"]
                assert sum(
                    item["role"] == plan.target_role for item in base["payloads"]
                ) == 1
            elif case["id"] == "PATH-HARDLINK-001":
                assert plan.target_path == targets.get(
                    "hardlink_target", targets["primary_nonempty_payload"]
                )
                assert plan.source_path == targets["same_bytes_source"]

            if case["id"] == "PATH-SYMLINK-001":
                joined = posixpath.normpath(
                    posixpath.join(
                        posixpath.dirname(plan.target_path or ""),
                        plan.symlink_target or "",
                    )
                )
                assert joined.startswith("../")
            if case["id"] == "INVENTORY-EXTRA-001":
                assert plan.generated_path not in payload_by_path

    assert len(plans) == 245
    assert len({(plan.base_id, plan.case_id) for plan in plans}) == 245
    assert unavailable == [
        (
            "B04-SOFTWARE",
            "INVENTORY-OMIT-ROLE-001",
            "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
        )
    ]


def test_65_compatible_target_dependent_mutations_apply_to_disposable_fixtures_only() -> None:
    bases = _load(BASE_REGISTRY)["bases"]
    policy = selected_fixture_policy()
    executed = 0
    for base in bases:
        targets = base["mutation_targets"]
        for case_id in sorted(TARGET_DEPENDENT_CASES):
            with tempfile.TemporaryDirectory(
                prefix="amy-base-aware-development-"
            ) as directory:
                release = Path(directory) / "release"
                build_selected_release_from_base(release, base, policy)
                attest_selected_manifest(release, policy)
                try:
                    plan = resolve_mutation_plan(case_id, base=base, policy=policy)
                except MutationPlanUnavailable:
                    assert (base["id"], case_id) == (
                        "B04-SOFTWARE",
                        "INVENTORY-OMIT-ROLE-001",
                    )
                    continue
                before = snapshot_tree(release)
                apply_selected_profile_mutation(
                    case_id,
                    release,
                    policy,
                    base=base,
                    mutation_plan=plan,
                )
                after = snapshot_tree(release)
                observation = mutation_observation(case_id, before, after)
                assert observation["contains_expected_or_observed_decisions"] is False
                assert observation["confirmatory_evidence"] is False
                assert observation["changed_paths"]

                if case_id in PRIMARY_TREE_MUTATION_CASES:
                    assert targets["primary_nonempty_payload"] in observation["changed_paths"]
                elif case_id == "PATH-DUPLICATE-NORMALIZED-001":
                    assert observation["changed_paths"] == [
                        "MANIFEST.jcs.json",
                        "attestation.sigstore.json",
                    ]
                elif case_id == "INVENTORY-MISSING-001":
                    assert targets["nested_payload"] in observation["removed_paths"]
                elif case_id == "INVENTORY-OMIT-ROLE-001":
                    assert targets["sole_required_role_payload"] in observation[
                        "removed_paths"
                    ]
                elif case_id == "PATH-HARDLINK-001":
                    target = targets.get(
                        "hardlink_target", targets["primary_nonempty_payload"]
                    )
                    source = targets["same_bytes_source"]
                    assert (release / target).stat().st_nlink == 2
                    assert (release / source).stat().st_nlink == 2
                executed += 1

    assert executed == 65


def test_plan_rejects_unknown_missing_and_unsafe_targets() -> None:
    base = _load(BASE_REGISTRY)["bases"][0]
    unsafe = json.loads(json.dumps(base))
    unsafe["mutation_targets"]["primary_nonempty_payload"] = "payload/../escape"
    try:
        resolve_mutation_plan("CONTENT-BITFLIP-001", base=unsafe)
    except ValueError as exc:
        assert "canonical payload path" in str(exc)
    else:
        raise AssertionError("unsafe mutation target was accepted")

    unknown = json.loads(json.dumps(base))
    unknown["mutation_targets"]["unexpected"] = "payload/data/observations.csv"
    try:
        resolve_mutation_plan("CONTENT-BITFLIP-001", base=unknown)
    except ValueError as exc:
        assert "unknown=['unexpected']" in str(exc)
    else:
        raise AssertionError("unknown mutation target key was accepted")


def test_generated_paths_include_policy_fixtures_and_forged_plans_are_rejected() -> None:
    base = _load(BASE_REGISTRY)["bases"][0]
    policy = selected_fixture_policy()
    policy["fixture_payloads"]["collision_fixture"] = {
        "path": "payload/unlisted.txt",
        "role": "supporting_material",
        "media_type": "application/octet-stream",
        "content_b64": "Y29sbGlzaW9uCg==",
    }
    plan = resolve_mutation_plan("INVENTORY-EXTRA-001", base=base, policy=policy)
    fixture_paths = {
        item["path"] for item in policy["fixture_payloads"].values()
    }
    assert plan.generated_path not in fixture_paths
    assert plan.generated_path_strategy == "DETERMINISTIC_UNLISTED_PAYLOAD"

    clean_policy = selected_fixture_policy()
    with tempfile.TemporaryDirectory(prefix="amy-forged-plan-development-") as directory:
        release = Path(directory) / "release"
        build_selected_release_from_base(release, base, clean_policy)
        attest_selected_manifest(release, clean_policy)
        expected = resolve_mutation_plan(
            "INVENTORY-EXTRA-001", base=base, policy=clean_policy
        )
        forged_record = expected.record()
        forged_record["generated_path"] = "../outside-release.bin"
        forged = MutationPlan(**forged_record)
        try:
            apply_selected_profile_mutation(
                "INVENTORY-EXTRA-001",
                release,
                clean_policy,
                base=base,
                mutation_plan=forged,
            )
        except ValueError as exc:
            assert "differs from deterministic resolution" in str(exc)
        else:
            raise AssertionError("forged mutation plan was accepted")
        assert not (Path(directory) / "outside-release.bin").exists()
