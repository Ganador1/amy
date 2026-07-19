from __future__ import annotations

import json
from pathlib import Path

import pytest

from amy_verifier.github_attestation import GitHubGateRejected, _enforce_p3


STUDY_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((STUDY_ROOT / relative).read_text(encoding="utf-8"))


def test_upstream_audit_is_bound_to_the_pinned_action_and_local_contract() -> None:
    policy = _load("protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json")
    audit = _load("audit/UPSTREAM_ATTESTATION_SEMANTICS_2026-07-13.json")

    assert audit["upstream"]["commit"] == policy["workflow_dependencies"][
        "actions_attest"
    ]["commit"]
    assert audit["observed_default_provenance"]["predicate_type"] == policy[
        "statement"
    ]["p3_predicate_type"]
    assert audit["current_local_p3_contract"][
        "compatible_with_pinned_default_predicate"
    ] is False
    assert "externalParameters.source.dirty" in audit[
        "observed_default_provenance"
    ]["absent_from_default_predicate"]


def test_attestation_profile_decision_selects_but_does_not_freeze_recommended_profile() -> None:
    decision = _load("protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json")
    candidate_ids = {candidate["id"] for candidate in decision["candidate_profiles"]}

    assert decision["status"] == "selected_for_implementation_not_frozen"
    assert decision["selected_profile"] == decision["recommended_profile"]
    assert decision["recommended_profile"] in candidate_ids
    assert candidate_ids == {
        "standard_provenance_plus_authenticated_manifest_metadata",
        "dual_standard_and_custom_attestations",
        "custom_slsa_build_type",
        "reduce_p3_to_default_fields_only",
    }


def test_selected_p3_requires_manifest_metadata_beyond_default_provenance() -> None:
    repository = "https://github.com/Ganador1/amy"
    identity = (
        f"{repository}/.github/workflows/attest-verifiable-study.yml@refs/tags/v1.0.0"
    )
    policy = {
        "tool": {},
        "subject": {},
        "identity": {
            "repository_uri": repository,
            "source_digest": "a" * 40,
            "source_ref": "refs/tags/v1.0.0",
            "certificate_identity": identity,
        },
        "trust": {},
        "statement": {"p3_predicate_type": "https://slsa.dev/provenance/v1"},
        "manifest": {
            "schema_version": "0.2.0-draft",
            "build_metadata_schema_version": "amy.build-metadata.v1",
            "assertion_scope": "workflow-authored-not-independently-certified",
        },
        "provenance": {
            "build_type": "https://actions.github.io/buildtypes/workflow/v1",
            "source_repository_uri": repository,
            "source_revision": "a" * 40,
            "source_ref": "refs/tags/v1.0.0",
            "workflow_path": ".github/workflows/attest-verifiable-study.yml",
            "builder_id": identity,
            "resolved_source_dependency_uri": (
                f"git+{repository}@refs/tags/v1.0.0"
            ),
            "manifest_assertions": {},
        },
        "limits": {"json_max_depth": 32},
    }
    default_statement = {
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                "externalParameters": {
                    "workflow": {
                        "repository": repository,
                        "ref": "refs/tags/v1.0.0",
                        "path": ".github/workflows/attest-verifiable-study.yml",
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": f"git+{repository}@refs/tags/v1.0.0",
                        "digest": {"gitCommit": "a" * 40},
                    }
                ],
            },
            "runDetails": {"builder": {"id": policy["provenance"]["builder_id"]}},
        },
    }

    with pytest.raises(GitHubGateRejected) as error:
        _enforce_p3(
            default_statement,
            policy,
            b'{"schema_version":"0.2.0-draft"}',
        )
    assert error.value.code == "PROVENANCE_INVALID"
