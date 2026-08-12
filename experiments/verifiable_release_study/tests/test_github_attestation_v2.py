from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import amy_verifier.github_attestation as github_attestation_v1
import amy_verifier.github_attestation_v2 as github_attestation_v2
import amy_verifier.github_attestation_v2_core as github_attestation_v2_core
from amy_verifier.github_attestation_v2_core import (
    GitHubAttestationEvidence,
    GitHubGateConfigurationError,
    GitHubGateRejected,
    validate_verified_output,
)
from amy_verifier.github_attestation_v2 import (
    RESULT_SCHEMA_VERSION,
    evidence_to_json_v2,
    load_github_policy_v2,
    policy_contract_identity_v2,
    require_frozen_policy_v2,
    verify_github_manifest_attestation_v2,
    verify_github_p3_release_v2,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA_PATH = STUDY_ROOT / "schemas/github-attestation-policy-v2.schema.json"
RESULT_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/github-production-verification-result-v2.schema.json"
)
TEMPLATE_PATH = STUDY_ROOT / "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json"
V1_INVARIANTS = {
    "schemas/github-production-verification-result.schema.json": (
        "64eef1a87da45dff355047963ebe762dfced1a2ba7e60be9a87dfcc28a1e2c18"
    ),
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json": (
        "68ea605c25a8e73ebe955a1bfd3977a309f13b40b9a112aee6b2e9bc5cd38c26"
    ),
    "production_pilot_runs/github_cli_2.96.0_upstream_smoke/result.json": (
        "444615e874774a01679e55098885a5e790d78a70a8f5fa0cc39caab28e545baa"
    ),
    "scripts/verify_github_attestation.py": (
        "9fbfa1ff99f8e5308cae741acfa6a5c683b0c36adaa68bfe930dee61ee49993b"
    ),
    "amy_verifier/github_attestation.py": (
        "6731d83c0ea94d0ce2029ce529a175c3eb9cd1d17e9698b090f47a72044fe6ac"
    ),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_validator() -> Draft202012Validator:
    return Draft202012Validator(
        _load(POLICY_SCHEMA_PATH), format_checker=FormatChecker()
    )


def _result_validator() -> Draft202012Validator:
    return Draft202012Validator(
        _load(RESULT_SCHEMA_PATH), format_checker=FormatChecker()
    )


def _frozen_policy() -> dict:
    policy = copy.deepcopy(_load(TEMPLATE_PATH))
    revision = "1" * 40
    source_ref = "refs/tags/paper-v1.0.0"
    certificate_identity = (
        "https://github.com/Ganador1/amy/.github/workflows/"
        "attest-verifiable-study.yml@refs/tags/paper-v1.0.0"
    )
    policy["policy_version"] = "1.0.0"
    policy["status"] = "release_specific_frozen"
    policy["identity"].update(
        {
            "repository_id": "893146956",
            "repository_owner_id": "179343756",
            "certificate_identity": certificate_identity,
            "signer_digest": revision,
            "source_digest": revision,
            "source_ref": source_ref,
        }
    )
    policy["trust"]["trusted_root_sha256"] = "2" * 64
    policy["provenance"].update(
        {
            "source_revision": revision,
            "source_ref": source_ref,
            "builder_id": certificate_identity,
            "resolved_source_dependency_uri": (
                "git+https://github.com/Ganador1/amy@" + source_ref
            ),
        }
    )
    asserted_source = policy["provenance"]["manifest_assertions"]["source"]
    asserted_source.update(
        {
            "revision": revision,
            "ref": source_ref,
            "tree": "3" * 40,
        }
    )
    asserted_source["snapshot"]["sha256"] = "4" * 64
    policy["provenance"]["manifest_assertions"]["dependency_lock"]["sha256"] = (
        "5" * 64
    )
    return policy


def _write_policy(path: Path, value: dict) -> str:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return _sha256(path)


def _load_frozen_document(tmp_path: Path):
    path = tmp_path / "policy-v2.json"
    expected = _write_policy(path, _frozen_policy())
    return load_github_policy_v2(
        path,
        POLICY_SCHEMA_PATH,
        RESULT_SCHEMA_PATH,
        expected_policy_sha256=expected,
    )


def _sample_evidence() -> GitHubAttestationEvidence:
    manifest_sha256 = "a" * 64
    return GitHubAttestationEvidence(
        profile_id="P2",
        manifest_sha256=manifest_sha256,
        bundle_sha256="b" * 64,
        trusted_root_sha256="2" * 64,
        predicate_type="https://slsa.dev/provenance/v1",
        certificate={
            "certificateIssuer": "CN=sigstore-intermediate,O=sigstore.dev",
            "issuer": "https://token.actions.githubusercontent.com",
            "subjectAlternativeName": (
                "https://github.com/Ganador1/amy/.github/workflows/"
                "attest-verifiable-study.yml@refs/tags/paper-v1.0.0"
            ),
            "sourceRepositoryURI": "https://github.com/Ganador1/amy",
            "sourceRepositoryOwnerURI": "https://github.com/Ganador1",
            "sourceRepositoryIdentifier": "893146956",
            "sourceRepositoryOwnerIdentifier": "179343756",
            "buildSignerDigest": "1" * 40,
            "sourceRepositoryDigest": "1" * 40,
            "sourceRepositoryRef": "refs/tags/paper-v1.0.0",
            "runnerEnvironment": "github-hosted",
            "githubWorkflowTrigger": "push",
            "sourceRepositoryVisibilityAtSigning": "public",
        },
        verified_timestamps=[
            {
                "type": "Tlog",
                "uri": "https://rekor.sigstore.dev",
                "timestamp": "2026-07-13T12:00:00Z",
            }
        ],
        statement={
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [
                {
                    "name": "MANIFEST.jcs.json",
                    "digest": {"sha256": manifest_sha256},
                }
            ],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {},
        },
        gh_version="2.96.0",
        gh_binary_sha256="6" * 64,
        gh_command=("gh", "attestation", "verify", "MANIFEST.jcs.json"),
    )


def _verified_output(manifest_raw: bytes, policy: dict) -> list[dict]:
    identity = policy["identity"]
    provenance = policy["provenance"]
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": "MANIFEST.jcs.json",
                "digest": {"sha256": hashlib.sha256(manifest_raw).hexdigest()},
            }
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": provenance["build_type"],
                "externalParameters": {
                    "workflow": {
                        "repository": identity["repository_uri"],
                        "path": provenance["workflow_path"],
                        "ref": identity["source_ref"],
                    }
                },
                "internalParameters": {
                    "github": {
                        "event_name": identity["event_name"],
                        "repository_id": identity["repository_id"],
                        "repository_owner_id": identity["repository_owner_id"],
                        "runner_environment": "github-hosted",
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": provenance["resolved_source_dependency_uri"],
                        "digest": {"gitCommit": identity["source_digest"]},
                    }
                ],
            },
            "runDetails": {"builder": {"id": provenance["builder_id"]}},
        },
    }
    certificate = {
        "certificateIssuer": "CN=sigstore-intermediate,O=sigstore.dev",
        "issuer": identity["oidc_issuer"],
        "subjectAlternativeName": identity["certificate_identity"],
        "sourceRepositoryURI": identity["repository_uri"],
        "sourceRepositoryOwnerURI": identity["repository_owner_uri"],
        "sourceRepositoryIdentifier": identity["repository_id"],
        "sourceRepositoryOwnerIdentifier": identity["repository_owner_id"],
        "buildSignerDigest": identity["signer_digest"],
        "sourceRepositoryDigest": identity["source_digest"],
        "sourceRepositoryRef": identity["source_ref"],
        "runnerEnvironment": "github-hosted",
        "githubWorkflowTrigger": identity["event_name"],
        "sourceRepositoryVisibilityAtSigning": identity["visibility"],
    }
    return [
        {
            "attestation": {
                "bundle": {
                    "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"
                }
            },
            "verificationResult": {
                "mediaType": (
                    "application/vnd.dev.sigstore.verificationresult+json;version=0.1"
                ),
                "signature": {"certificate": certificate},
                "verifiedTimestamps": [
                    {"type": "Tlog", "uri": "https://rekor.sigstore.dev"}
                ],
                "statement": statement,
            },
        }
    ]


def test_v2_policy_schema_is_valid_closed_and_template_validates() -> None:
    schema = _load(POLICY_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    template = _load(TEMPLATE_PATH)
    assert list(_policy_validator().iter_errors(template)) == []

    extra_top = copy.deepcopy(template)
    extra_top["unmodeled"] = True
    assert list(_policy_validator().iter_errors(extra_top))
    extra_nested = copy.deepcopy(template)
    extra_nested["identity"]["unmodeled"] = True
    assert list(_policy_validator().iter_errors(extra_nested))


def test_v2_frozen_policy_schema_rejects_placeholders_and_accepts_instantiation() -> None:
    mislabeled = copy.deepcopy(_load(TEMPLATE_PATH))
    mislabeled["policy_version"] = "1.0.0"
    mislabeled["status"] = "release_specific_frozen"
    assert list(_policy_validator().iter_errors(mislabeled))
    assert list(_policy_validator().iter_errors(_frozen_policy())) == []


def test_v2_policy_requires_immutable_repository_and_owner_ids() -> None:
    frozen = _frozen_policy()
    for field in ("repository_id", "repository_owner_id"):
        missing = copy.deepcopy(frozen)
        missing["identity"].pop(field)
        assert list(_policy_validator().iter_errors(missing))

        invalid = copy.deepcopy(frozen)
        invalid["identity"][field] = "0"
        assert list(_policy_validator().iter_errors(invalid))


def test_v2_result_requires_immutable_repository_and_owner_ids() -> None:
    evidence = github_attestation_v2._bind_evidence(
        _sample_evidence(),
        github_attestation_v2.GitHubPolicyDocumentV2(
            policy_raw=b"{}",
            policy_schema_raw=b"{}",
            result_schema_raw=RESULT_SCHEMA_PATH.read_bytes(),
            expected_policy_sha256="0" * 64,
            policy_sha256="0" * 64,
            policy_schema_sha256="0" * 64,
            result_schema_sha256=_sha256(RESULT_SCHEMA_PATH),
        ),
    )
    result = json.loads(evidence.verified_accept_json)
    result.update(
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "policy_sha256": "a" * 64,
            "policy_schema_sha256": "b" * 64,
            "result_schema_sha256": "c" * 64,
        }
    )
    for field in (
        "sourceRepositoryIdentifier",
        "sourceRepositoryOwnerIdentifier",
    ):
        missing = copy.deepcopy(result)
        missing["certificate"].pop(field)
        assert list(_result_validator().iter_errors(missing))


@pytest.mark.parametrize(
    "field",
    ["sourceRepositoryIdentifier", "sourceRepositoryOwnerIdentifier"],
)
def test_v2_certificate_rejects_mutated_immutable_ids(field: str) -> None:
    policy = _frozen_policy()
    manifest_raw = b"exact manifest bytes"
    output = _verified_output(manifest_raw, policy)
    output[0]["verificationResult"]["signature"]["certificate"][field] = "999999999"
    with pytest.raises(GitHubGateRejected) as error:
        validate_verified_output(
            output,
            profile_id="P2",
            manifest_raw=manifest_raw,
            policy=policy,
            predicate_type="https://slsa.dev/provenance/v1",
        )
    assert error.value.code == "SIGNER_UNAUTHORIZED"


@pytest.mark.parametrize("field", ["repository_id", "repository_owner_id"])
def test_v2_p3_rejects_mutated_authenticated_internal_ids(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _frozen_policy()
    manifest_raw = b"exact manifest bytes"
    output = _verified_output(manifest_raw, policy)
    github_parameters = output[0]["verificationResult"]["statement"]["predicate"][
        "buildDefinition"
    ]["internalParameters"]["github"]
    github_parameters[field] = "999999999"
    monkeypatch.setattr(
        github_attestation_v2_core,
        "_enforce_manifest_assertions",
        lambda *args: None,
    )
    with pytest.raises(GitHubGateRejected) as error:
        validate_verified_output(
            output,
            profile_id="P3",
            manifest_raw=manifest_raw,
            policy=policy,
            predicate_type="https://slsa.dev/provenance/v1",
        )
    assert error.value.code == "SIGNER_UNAUTHORIZED"


def test_v2_p3_accepts_matching_certificate_and_authenticated_internal_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _frozen_policy()
    manifest_raw = b"exact manifest bytes"
    output = _verified_output(manifest_raw, policy)
    monkeypatch.setattr(
        github_attestation_v2_core,
        "_enforce_manifest_assertions",
        lambda *args: None,
    )
    statement, certificate, _ = validate_verified_output(
        output,
        profile_id="P3",
        manifest_raw=manifest_raw,
        policy=policy,
        predicate_type="https://slsa.dev/provenance/v1",
    )
    assert certificate["sourceRepositoryIdentifier"] == policy["identity"][
        "repository_id"
    ]
    assert statement["predicate"]["buildDefinition"]["internalParameters"][
        "github"
    ]["repository_owner_id"] == policy["identity"]["repository_owner_id"]


def test_v2_workflow_pins_remain_explicit_no_go_without_authenticated_bytes(
    tmp_path: Path,
) -> None:
    unsupported_claim = _frozen_policy()
    unsupported_claim["workflow_dependency_assurance"]["verification_status"] = (
        "VERIFIED_AUTHENTICATED_WORKFLOW_BYTES"
    )
    unsupported_claim["workflow_dependency_assurance"][
        "pins_are_authorization_evidence"
    ] = True
    assert list(_policy_validator().iter_errors(unsupported_claim))

    document = _load_frozen_document(tmp_path)
    with pytest.raises(
        GitHubGateConfigurationError,
        match="workflow dependency pins are NO-GO: authenticated workflow bytes are absent",
    ):
        require_frozen_policy_v2(document)


def test_only_v2_production_apis_exclude_runner_injection() -> None:
    assert (
        github_attestation_v2.verify_github_manifest_attestation
        is github_attestation_v2_core.verify_github_manifest_attestation
    )
    assert (
        github_attestation_v2.verify_github_p3_release
        is github_attestation_v2_core.verify_github_p3_release
    )
    v2_production_apis = (
        verify_github_manifest_attestation_v2,
        verify_github_p3_release_v2,
        github_attestation_v2_core.verify_github_manifest_attestation,
        github_attestation_v2_core.verify_github_p3_release,
    )
    for function in v2_production_apis:
        assert "runner" not in inspect.signature(function).parameters

    for legacy_api in (
        github_attestation_v1.verify_github_manifest_attestation,
        github_attestation_v1.verify_github_p3_release,
    ):
        assert "runner" in inspect.signature(legacy_api).parameters

    with pytest.raises(TypeError, match="unexpected keyword argument 'runner'"):
        verify_github_manifest_attestation_v2(
            Path("manifest"),
            Path("bundle"),
            Path("root"),
            profile_id="P2",
            policy=None,  # type: ignore[arg-type]
            runner=lambda *args, **kwargs: None,  # type: ignore[call-arg]
        )


def test_v2_result_schema_accepts_historical_shape_with_v2_identity() -> None:
    result = _load(
        STUDY_ROOT
        / "production_pilot_runs/github_cli_2.96.0_upstream_smoke/result.json"
    )
    result.update(
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "policy_sha256": "a" * 64,
            "policy_schema_sha256": "b" * 64,
            "result_schema_sha256": "c" * 64,
        }
    )
    assert list(_result_validator().iter_errors(result)) == []
    for field in (
        "policy_sha256",
        "policy_schema_sha256",
        "result_schema_sha256",
    ):
        incomplete = dict(result)
        incomplete.pop(field)
        assert list(_result_validator().iter_errors(incomplete))


def test_v2_reason_enum_matches_versioned_registries() -> None:
    schema = _load(RESULT_SCHEMA_PATH)
    base = _load(STUDY_ROOT / "protocol/REASON_CODES.json")
    extension = _load(STUDY_ROOT / "protocol/PRODUCTION_REASON_CODES_DRAFT.json")
    expected = {
        entry["code"]
        for entry in base["codes"] + extension["additional_codes"]
        if entry["decision"] == "REJECT"
    }
    assert set(schema["$defs"]["reasonCode"]["enum"]) == expected


def test_v2_loader_rejects_wrong_external_policy_digest(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    _write_policy(policy_path, _frozen_policy())
    with pytest.raises(GitHubGateConfigurationError, match="externally expected"):
        load_github_policy_v2(
            policy_path,
            POLICY_SCHEMA_PATH,
            RESULT_SCHEMA_PATH,
            expected_policy_sha256="0" * 64,
        )


def test_v2_loader_rejects_duplicate_policy_key(tmp_path: Path) -> None:
    raw = TEMPLATE_PATH.read_bytes().replace(
        b'"policy_version": "0.2.0-draft",',
        b'"policy_version": "0.2.0-draft",\n  "policy_version": "0.2.0-draft",',
        1,
    )
    policy_path = tmp_path / "duplicate-policy.json"
    policy_path.write_bytes(raw)
    with pytest.raises(GitHubGateConfigurationError, match="duplicate"):
        load_github_policy_v2(
            policy_path,
            POLICY_SCHEMA_PATH,
            RESULT_SCHEMA_PATH,
            expected_policy_sha256=hashlib.sha256(raw).hexdigest(),
        )


def test_v2_loader_rejects_duplicate_policy_schema_key(tmp_path: Path) -> None:
    raw = POLICY_SCHEMA_PATH.read_bytes().replace(
        b'"$schema": "https://json-schema.org/draft/2020-12/schema",',
        b'"$schema": "https://json-schema.org/draft/2020-12/schema",\n'
        b'  "$schema": "https://json-schema.org/draft/2020-12/schema",',
        1,
    )
    schema_path = tmp_path / "duplicate-policy-schema.json"
    schema_path.write_bytes(raw)
    with pytest.raises(GitHubGateConfigurationError, match="duplicate"):
        load_github_policy_v2(
            TEMPLATE_PATH,
            schema_path,
            RESULT_SCHEMA_PATH,
            expected_policy_sha256=_sha256(TEMPLATE_PATH),
        )


def test_v2_loader_rejects_policy_schema_hash_mismatch(tmp_path: Path) -> None:
    policy = _frozen_policy()
    policy["policy_schema"]["schema_sha256"] = "0" * 64
    policy_path = tmp_path / "wrong-schema-hash-policy.json"
    expected = _write_policy(policy_path, policy)
    with pytest.raises(GitHubGateConfigurationError, match="schema differs"):
        load_github_policy_v2(
            policy_path,
            POLICY_SCHEMA_PATH,
            RESULT_SCHEMA_PATH,
            expected_policy_sha256=expected,
        )


def test_v2_loader_rejects_result_schema_bytes_not_bound_by_policy(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "policy.json"
    expected = _write_policy(policy_path, _frozen_policy())
    with pytest.raises(GitHubGateConfigurationError, match="result schema differs"):
        load_github_policy_v2(
            policy_path,
            POLICY_SCHEMA_PATH,
            STUDY_ROOT / "schemas/github-production-verification-result.schema.json",
            expected_policy_sha256=expected,
        )


def test_v2_loader_rejects_schema_unknown_field(tmp_path: Path) -> None:
    policy = _frozen_policy()
    policy["trust"]["unmodeled"] = "unsafe"
    policy_path = tmp_path / "unknown-field-policy.json"
    expected = _write_policy(policy_path, policy)
    with pytest.raises(GitHubGateConfigurationError, match="closed schema"):
        load_github_policy_v2(
            policy_path,
            POLICY_SCHEMA_PATH,
            RESULT_SCHEMA_PATH,
            expected_policy_sha256=expected,
        )


def test_v2_template_cannot_reach_underlying_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _sha256(TEMPLATE_PATH)
    document = load_github_policy_v2(
        TEMPLATE_PATH,
        POLICY_SCHEMA_PATH,
        RESULT_SCHEMA_PATH,
        expected_policy_sha256=expected,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("underlying verifier must not run for a template")

    monkeypatch.setattr(
        github_attestation_v2, "verify_github_manifest_attestation", fail_if_called
    )
    with pytest.raises(GitHubGateConfigurationError, match="template"):
        verify_github_manifest_attestation_v2(
            Path("missing-manifest"),
            Path("missing-bundle"),
            Path("missing-root"),
            profile_id="P2",
            policy=document,
        )


def test_v2_api_rejects_plain_dict_policy() -> None:
    with pytest.raises(GitHubGateConfigurationError, match="GitHubPolicyDocumentV2"):
        verify_github_manifest_attestation_v2(
            Path("missing-manifest"),
            Path("missing-bundle"),
            Path("missing-root"),
            profile_id="P2",
            policy=_frozen_policy(),  # type: ignore[arg-type]
        )


def test_v2_document_detects_post_load_byte_tampering(tmp_path: Path) -> None:
    document = _load_frozen_document(tmp_path)
    tampered = replace(document, policy_raw=document.policy_raw + b" ")
    with pytest.raises(GitHubGateConfigurationError, match="externally expected"):
        require_frozen_policy_v2(tampered)


def test_v2_frozen_runtime_rejects_cross_field_mismatch(tmp_path: Path) -> None:
    policy = _frozen_policy()
    policy["provenance"]["source_ref"] = "refs/tags/different-v1.0.0"
    policy_path = tmp_path / "cross-field-mismatch.json"
    expected = _write_policy(policy_path, policy)
    document = load_github_policy_v2(
        policy_path,
        POLICY_SCHEMA_PATH,
        RESULT_SCHEMA_PATH,
        expected_policy_sha256=expected,
    )
    with pytest.raises(GitHubGateConfigurationError, match="source ref mismatch"):
        require_frozen_policy_v2(document)


def test_v2_wrapper_snapshots_evidence_and_always_binds_contract_hashes(
    tmp_path: Path,
) -> None:
    document = _load_frozen_document(tmp_path)
    underlying = _sample_evidence()
    evidence = github_attestation_v2._bind_evidence(underlying, document)
    underlying.certificate["sourceRepositoryURI"] = "https://example.invalid/tampered"
    output = evidence_to_json_v2(evidence)
    identity = policy_contract_identity_v2(document)
    assert output["certificate"]["sourceRepositoryURI"] == (
        "https://github.com/Ganador1/amy"
    )
    assert {key: output[key] for key in identity} == identity
    assert list(_result_validator().iter_errors(output)) == []


def test_v2_binding_rejects_structurally_similar_legacy_v1_evidence(
    tmp_path: Path,
) -> None:
    document = _load_frozen_document(tmp_path)
    legacy = github_attestation_v1.GitHubAttestationEvidence(
        **vars(_sample_evidence())
    )
    with pytest.raises(
        GitHubGateConfigurationError,
        match="isolated v2 core",
    ):
        github_attestation_v2._bind_evidence(legacy, document)  # type: ignore[arg-type]


def test_v2_library_serializer_enforces_exact_result_schema(
    tmp_path: Path,
) -> None:
    document = _load_frozen_document(tmp_path)
    underlying = _sample_evidence()
    underlying.certificate["unmodeled"] = "must not escape through library API"
    evidence = github_attestation_v2._bind_evidence(underlying, document)
    with pytest.raises(GitHubGateConfigurationError, match="exact result schema"):
        evidence_to_json_v2(evidence)


def test_v2_cli_template_emits_schema_valid_identity_bound_error() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(STUDY_ROOT / "scripts/verify_github_attestation_v2.py"),
            "/tmp/missing-release",
            str(TEMPLATE_PATH),
            "/tmp/missing-root",
            "--profile",
            "P2",
            "--expected-policy-sha256",
            _sha256(TEMPLATE_PATH),
            "--policy-schema",
            str(POLICY_SCHEMA_PATH),
            "--result-schema",
            str(RESULT_SCHEMA_PATH),
        ],
        cwd=STUDY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2, completed.stderr
    output = json.loads(completed.stdout)
    assert output["decision"] == "ERROR"
    assert "template" in output["error"]
    assert output["policy_sha256"] == _sha256(TEMPLATE_PATH)
    assert output["policy_schema_sha256"] == _sha256(POLICY_SCHEMA_PATH)
    assert output["result_schema_sha256"] == _sha256(RESULT_SCHEMA_PATH)
    assert list(_result_validator().iter_errors(output)) == []


@pytest.mark.parametrize(
    ("extra_args", "expected_fragment"),
    [
        (["--expected-policy-sha256", "0" * 64], "externally expected"),
        (
            [
                "--expected-policy-sha256",
                "__REAL_POLICY_SHA__",
                "--policy-schema",
                "/tmp/missing-policy-schema.json",
            ],
            "could not be loaded safely",
        ),
    ],
)
def test_v2_cli_suppresses_unbound_json(
    extra_args: list[str], expected_fragment: str
) -> None:
    policy_sha = _sha256(TEMPLATE_PATH)
    expanded = [policy_sha if value == "__REAL_POLICY_SHA__" else value for value in extra_args]
    command = [
        sys.executable,
        str(STUDY_ROOT / "scripts/verify_github_attestation_v2.py"),
        "/tmp/missing-release",
        str(TEMPLATE_PATH),
        "/tmp/missing-root",
        "--profile",
        "P2",
        "--policy-schema",
        str(POLICY_SCHEMA_PATH),
        "--result-schema",
        str(RESULT_SCHEMA_PATH),
    ]
    command.extend(expanded)
    completed = subprocess.run(
        command,
        cwd=STUDY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert expected_fragment in completed.stderr


def test_v2_cli_suppresses_json_for_result_schema_not_bound_by_policy() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(STUDY_ROOT / "scripts/verify_github_attestation_v2.py"),
            "/tmp/missing-release",
            str(TEMPLATE_PATH),
            "/tmp/missing-root",
            "--profile",
            "P2",
            "--expected-policy-sha256",
            _sha256(TEMPLATE_PATH),
            "--policy-schema",
            str(POLICY_SCHEMA_PATH),
            "--result-schema",
            str(
                STUDY_ROOT
                / "schemas/github-production-verification-result.schema.json"
            ),
        ],
        cwd=STUDY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "differs from the externally pinned policy" in completed.stderr


def test_historical_v1_artifacts_remain_byte_identical() -> None:
    assert {
        relative: _sha256(STUDY_ROOT / relative)
        for relative in V1_INVARIANTS
    } == V1_INVARIANTS
