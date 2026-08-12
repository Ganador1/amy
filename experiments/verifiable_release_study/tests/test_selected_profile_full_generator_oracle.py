from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

from amy_verifier.selected_profile_evaluator import evaluate_selected_profile_result
from amy_verifier.selected_profile_fixture import (
    attest_selected_manifest,
    build_clean_selected_release,
    selected_fixture_policy,
    verify_selected_fixture_release,
)
from amy_verifier.selected_profile_mutations import (
    SUPPORTED_CASE_IDS,
    apply_selected_profile_mutation,
    mutation_observation,
    snapshot_tree,
)
from amy_verifier.selected_profile_oracle import build_selected_profile_oracle


STUDY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
ORACLE_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
ORACLE_SCHEMA_PATH = STUDY_ROOT / "schemas/selected-profile-oracle.schema.json"
RESULT_SCHEMA_PATH = STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json"


EXPECTED_CHANGED_PATHS = {
    "ATTESTATION-MALFORMED-001": {"attestation.sigstore.json"},
    "ATTESTATION-MISSING-001": {"attestation.sigstore.json"},
    "BUILD-DIRTY-001": {"MANIFEST.jcs.json", "attestation.sigstore.json"},
    "BUILD-METADATA-MISSING-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "BUILDER-PREDICATE-MISMATCH-001": {"attestation.sigstore.json"},
    "CERTIFICATE-TIME-001": {"attestation.sigstore.json"},
    "CLEAN-001": set(),
    "CONTENT-BITFLIP-001": {"payload/data.csv"},
    "CONTENT-SAME-SIZE-001": {"payload/data.csv"},
    "CONTENT-TRUNCATE-001": {"payload/data.csv"},
    "EXECUTION-IMAGE-MISMATCH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "IDENTITY-WORKFLOW-001": {"attestation.sigstore.json"},
    "INVENTORY-EXTRA-001": {"payload/unlisted.txt"},
    "INVENTORY-MISSING-001": {"payload/results/result.json"},
    "INVENTORY-OMIT-ROLE-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
        "payload/analysis.py",
    },
    "MANIFEST-DUPLICATE-KEY-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "MANIFEST-MALFORMED-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "MANIFEST-MISSING-001": {"MANIFEST.jcs.json"},
    "MANIFEST-NONCANONICAL-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "MANIFEST-SCHEMA-001": {"MANIFEST.jcs.json", "attestation.sigstore.json"},
    "MANIFEST-SELF-HASH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "MATERIAL-LOCK-MISMATCH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "PATH-DUPLICATE-NORMALIZED-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "PATH-HARDLINK-001": {"payload/data-copy.csv", "payload/data.csv"},
    "PATH-NONREGULAR-001": {"payload/data.csv"},
    "PATH-PARENT-001": {"MANIFEST.jcs.json", "attestation.sigstore.json"},
    "PATH-SYMLINK-001": {"payload/data.csv"},
    "PREDICATE-WRONG-TYPE-001": {"attestation.sigstore.json"},
    "RESOURCE-MANIFEST-LIMIT-001": {"MANIFEST.jcs.json"},
    "SIGNATURE-ALGORITHM-001": {"attestation.sigstore.json"},
    "SIGNATURE-CORRUPT-001": {"attestation.sigstore.json"},
    "SNAPSHOT-DIGEST-MISMATCH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "SNAPSHOT-ROLE-MISMATCH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "SOURCE-TREE-MISMATCH-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
    },
    "SOURCE-WRONG-REVISION-001": {"attestation.sigstore.json"},
    "STATEMENT-MALFORMED-001": {"attestation.sigstore.json"},
    "SUBJECT-REPLAY-001": {"attestation.sigstore.json"},
    "SUBSTITUTION-COHERENT-001": {"MANIFEST.jcs.json", "payload/data.csv"},
    "SUBSTITUTION-UNAUTHORIZED-001": {
        "MANIFEST.jcs.json",
        "attestation.sigstore.json",
        "payload/data.csv",
    },
    "TRANSPARENCY-MISSING-001": {"attestation.sigstore.json"},
    "WORKFLOW-PARAMETER-MISMATCH-001": {"attestation.sigstore.json"},
}


SEMANTIC_MANIFEST_OR_STATEMENT_CASES = {
    "BUILD-DIRTY-001",
    "BUILD-METADATA-MISSING-001",
    "BUILDER-PREDICATE-MISMATCH-001",
    "EXECUTION-IMAGE-MISMATCH-001",
    "MATERIAL-LOCK-MISMATCH-001",
    "PREDICATE-WRONG-TYPE-001",
    "SNAPSHOT-DIGEST-MISMATCH-001",
    "SNAPSHOT-ROLE-MISMATCH-001",
    "SOURCE-TREE-MISMATCH-001",
    "SOURCE-WRONG-REVISION-001",
    "WORKFLOW-PARAMETER-MISMATCH-001",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _statement(root: Path) -> dict:
    bundle = _load(root / "attestation.sigstore.json")
    return json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_diff_pointers(before: object, after: object, pointer: str = "") -> set[str]:
    if type(before) is not type(after):
        return {pointer or "/"}
    if isinstance(before, dict):
        changed: set[str] = set()
        for key in set(before) | set(after):
            child = f"{pointer}/{_pointer_token(key)}"
            if key not in before or key not in after:
                changed.add(child)
            else:
                changed.update(_json_diff_pointers(before[key], after[key], child))
        return changed
    if isinstance(before, list):
        if len(before) != len(after):
            return {pointer or "/"}
        changed = set()
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            changed.update(_json_diff_pointers(left, right, f"{pointer}/{index}"))
        return changed
    return set() if before == after else {pointer or "/"}


def test_selected_oracle_is_schema_closed_deterministic_and_outcome_unread() -> None:
    retained = _load(ORACLE_PATH)
    fresh = build_selected_profile_oracle()
    schema = _load(ORACLE_SCHEMA_PATH)
    assert retained == fresh
    assert list(Draft202012Validator(schema).iter_errors(retained)) == []
    assert retained["case_count"] == 41
    assert retained["row_count"] == 164
    assert retained["derivation_boundary"] == {
        "source_fields": ["cases[].id", "cases[].profile_expectations"],
        "observed_results_read": False,
        "confirmatory_cases_read": False,
        "confirmatory_cases_executed": False,
        "target_decisions_used_as_profile_expectations": False,
        "implementation_behavior_used_to_generate_rows": False,
        "independent_human_review_complete": False,
        "classification": "pre_registration_expected_implementation_behavior",
    }
    assert not {
        "observed_decision",
        "observed_primary_reason",
        "target_decision",
        "profile_conforms",
    } & {key for row in retained["rows"] for key in row}


def test_oracle_reason_vocabulary_equals_the_closed_result_contract() -> None:
    oracle_schema = _load(ORACLE_SCHEMA_PATH)
    result_schema = _load(RESULT_SCHEMA_PATH)
    oracle_reasons = set(
        oracle_schema["$defs"]["oracleRow"]["properties"][
            "expected_primary_reason"
        ]["enum"]
    )
    result_reasons = set(result_schema["$defs"]["reasonCode"]["enum"])
    assert oracle_reasons == result_reasons - {"INTERNAL_ERROR"}


def test_full_selected_generator_matches_164_draft_oracle_rows_in_temporary_development_fixtures() -> None:
    catalog = _load(CATALOG_PATH)
    oracle = _load(ORACLE_PATH)
    result_schema = _load(RESULT_SCHEMA_PATH)
    result_validator = Draft202012Validator(result_schema)
    policy = selected_fixture_policy()
    catalog_ids = {case["id"] for case in catalog["cases"]}
    assert catalog_ids == set(SUPPORTED_CASE_IDS) == set(EXPECTED_CHANGED_PATHS)
    oracle_by_key = {
        (row["case_id"], row["profile_id"]): row for row in oracle["rows"]
    }
    assert len(oracle_by_key) == 164

    evaluated = []
    observations = {}
    for case in catalog["cases"]:
        case_id = case["id"]
        with tempfile.TemporaryDirectory(prefix="amy-selected-development-") as directory:
            release = Path(directory) / "release"
            build_clean_selected_release(release, policy)
            attest_selected_manifest(release, policy)
            before = snapshot_tree(release)
            apply_selected_profile_mutation(case_id, release, policy)
            after = snapshot_tree(release)
            observation = mutation_observation(case_id, before, after)
            observations[case_id] = observation
            assert set(observation["changed_paths"]) == EXPECTED_CHANGED_PATHS[case_id]
            assert observation["contains_expected_or_observed_decisions"] is False
            assert observation["confirmatory_evidence"] is False

            for profile_id in ("P0", "P1", "P2", "P3"):
                result = verify_selected_fixture_release(
                    release, profile_id=profile_id, policy=policy
                )
                assert list(result_validator.iter_errors(result)) == []
                assert result["boundary"] == (
                    "controlled_fixture_not_production_sigstore_not_confirmatory"
                )
                evaluated.append(
                    evaluate_selected_profile_result(
                        case_id, result, oracle_by_key[(case_id, profile_id)]
                    )
                )

    assert len(evaluated) == 164
    assert all(row["profile_conforms"] for row in evaluated)
    for case_id in SEMANTIC_MANIFEST_OR_STATEMENT_CASES:
        assert observations[case_id]["payload_digest_changed_paths"] == []
        assert all(
            not path.startswith("payload/")
            for path in observations[case_id]["changed_paths"]
        )


def test_eleven_semantic_mutations_change_only_the_catalogued_authenticated_pointer() -> None:
    catalog = _load(CATALOG_PATH)
    by_id = {case["id"]: case for case in catalog["cases"]}
    policy = selected_fixture_policy()
    for case_id in sorted(SEMANTIC_MANIFEST_OR_STATEMENT_CASES):
        with tempfile.TemporaryDirectory(prefix="amy-selected-isolation-") as directory:
            release = Path(directory) / "release"
            build_clean_selected_release(release, policy)
            attest_selected_manifest(release, policy)
            manifest_before = _load(release / "MANIFEST.jcs.json")
            statement_before = _statement(release)
            apply_selected_profile_mutation(case_id, release, policy)
            manifest_after = _load(release / "MANIFEST.jcs.json")
            statement_after = _statement(release)
            contract = by_id[case_id]["mutation_contract"]

            if contract["authenticated_object"] == "manifest":
                changed = _json_diff_pointers(manifest_before, manifest_after)
                assert _json_diff_pointers(statement_before, statement_after) == {
                    "/subject/0/digest/sha256"
                }
                if case_id == "SNAPSHOT-ROLE-MISMATCH-001":
                    snapshot_path = manifest_before["build_metadata"]["source"][
                        "snapshot"
                    ]["path"]
                    snapshot_index = next(
                        index
                        for index, entry in enumerate(manifest_before["payloads"])
                        if entry["path"] == snapshot_path
                    )
                    assert changed == {f"/payloads/{snapshot_index}/role"}
                    assert contract["json_pointer"] == "/payloads/{snapshot-entry}/role"
                else:
                    assert changed == {contract["json_pointer"]}
            else:
                assert _json_diff_pointers(manifest_before, manifest_after) == set()
                assert _json_diff_pointers(statement_before, statement_after) == {
                    contract["json_pointer"]
                }
            assert contract["reattest_after_mutation"] is True
            assert contract["payload_bytes_changed"] is False


def test_all_41_mutations_replay_to_identical_same_environment_tree_observations() -> None:
    policy = selected_fixture_policy()
    for case_id in sorted(SUPPORTED_CASE_IDS):
        snapshots = []
        for _ in range(2):
            with tempfile.TemporaryDirectory(
                prefix="amy-selected-determinism-"
            ) as directory:
                release = Path(directory) / "release"
                build_clean_selected_release(release, policy)
                attest_selected_manifest(release, policy)
                apply_selected_profile_mutation(case_id, release, policy)
                snapshots.append(snapshot_tree(release))
        assert snapshots[0] == snapshots[1], case_id


def test_evaluator_never_counts_error_as_expected_reject() -> None:
    row = next(
        row
        for row in _load(ORACLE_PATH)["rows"]
        if row["case_id"] == "CONTENT-BITFLIP-001" and row["profile_id"] == "P1"
    )
    observed = {
        "profile_id": "P1",
        "decision": "ERROR",
        "primary_reason": "INTERNAL_ERROR",
    }
    evaluated = evaluate_selected_profile_result(
        "CONTENT-BITFLIP-001", observed, row
    )
    assert evaluated["profile_conforms"] is False
    assert evaluated["error_satisfies_expected_reject"] is False
