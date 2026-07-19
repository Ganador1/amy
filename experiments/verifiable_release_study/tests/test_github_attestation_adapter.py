from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

import amy_verifier.github_attestation as github_attestation
from amy_verifier.github_attestation import (
    GitHubAttestationEvidence,
    GitHubGateConfigurationError,
    GitHubGateRejected,
    build_gh_verify_command,
    extract_untrusted_predicate_type,
    validate_verified_output,
    verify_github_manifest_attestation,
    verify_github_p3_release,
)


COMMIT = "a" * 40
TREE = "b" * 40
SOURCE_SNAPSHOT_SHA256 = "c" * 64
LOCK_SHA256 = "d" * 64
IMAGE_SHA256 = "e" * 64
REF = "refs/tags/amy-study-v0.1.0"
REPOSITORY_URI = "https://github.com/Ganador1/amy"
IDENTITY = (
    "https://github.com/Ganador1/amy/"
    ".github/workflows/attest-verifiable-study.yml@refs/tags/amy-study-v0.1.0"
)


def _policy() -> dict:
    return {
        "tool": {
            "version": "2.96.0",
            "binary_sha256_by_platform": {"test-platform": "f" * 64},
            "binary_max_bytes": 268435456,
            "timeout_seconds": 120,
        },
        "subject": {
            "name": "MANIFEST.jcs.json",
            "digest_algorithm": "sha256",
            "allow_additional_subjects": False,
        },
        "identity": {
            "repository": "Ganador1/amy",
            "repository_uri": REPOSITORY_URI,
            "repository_owner_uri": "https://github.com/Ganador1",
            "certificate_identity": IDENTITY,
            "oidc_issuer": "https://token.actions.githubusercontent.com",
            "signer_digest": COMMIT,
            "source_digest": COMMIT,
            "source_ref": REF,
            "event_name": "push",
            "visibility": "public",
        },
        "trust": {
            "trusted_root_sha256": "b" * 64,
            "certificate_issuer_organization": "sigstore.dev",
            "required_timestamp_type": "Tlog",
            "required_timestamp_uri": "https://rekor.sigstore.dev",
            "allowed_bundle_media_types": [
                "application/vnd.dev.sigstore.bundle.v0.3+json"
            ],
            "allowed_verification_result_media_types": [
                "application/vnd.dev.sigstore.verificationresult+json;version=0.1"
            ],
        },
        "statement": {
            "type": "https://in-toto.io/Statement/v1",
            "p3_predicate_type": "https://slsa.dev/provenance/v1",
        },
        "manifest": {
            "schema_version": "0.2.0-draft",
            "schema_sha256": "0" * 64,
            "build_metadata_schema_version": "amy.build-metadata.v1",
            "assertion_scope": "workflow-authored-not-independently-certified",
            "required_roles_by_release_kind": {
                "software_release": ["environment_lock", "source_code"]
            },
        },
        "provenance": {
            "build_type": "https://actions.github.io/buildtypes/workflow/v1",
            "source_repository_uri": REPOSITORY_URI,
            "source_revision": COMMIT,
            "source_ref": REF,
            "workflow_path": ".github/workflows/attest-verifiable-study.yml",
            "builder_id": IDENTITY,
            "resolved_source_dependency_uri": f"git+{REPOSITORY_URI}@{REF}",
            "manifest_assertions": {
                "source": {
                    "repository_uri": REPOSITORY_URI,
                    "revision": COMMIT,
                    "ref": REF,
                    "git_object_format": "sha1",
                    "tree": TREE,
                    "dirty": False,
                    "snapshot": {
                        "path": "payload/source/source.tar",
                        "sha256": SOURCE_SNAPSHOT_SHA256,
                        "format": "application/x-tar",
                        "assurance": "exact-opaque-bytes-no-git-tree-equivalence-claim",
                        "required_payload_role": "source_code",
                    },
                },
                "dependency_lock": {
                    "path": "payload/environment/uv.lock",
                    "sha256": LOCK_SHA256,
                    "required_payload_role": "environment_lock",
                },
                "execution_image": {
                    "reference": "ghcr.io/astral-sh/uv",
                    "digest": f"sha256:{IMAGE_SHA256}",
                },
            },
        },
        "limits": {
            "manifest_max_bytes": 8192,
            "attestation_max_bytes": 4096,
            "trusted_root_max_bytes": 4096,
            "dsse_statement_max_bytes": 2048,
            "gh_output_max_bytes": 8192,
            "json_max_depth": 32,
            "payload_file_max_count": 100,
            "single_payload_max_bytes": 4096,
            "payload_total_max_bytes": 8192,
            "path_max_utf8_bytes": 240,
            "path_max_components": 64,
        },
    }


def _manifest(
    *,
    lock_sha256: str = LOCK_SHA256,
    source_snapshot_sha256: str = SOURCE_SNAPSHOT_SHA256,
) -> bytes:
    value = {
        "schema_version": "0.2.0-draft",
        "release": {"id": "test-release", "version": "0.1.0", "kind": "software_release"},
        "build_metadata": {
            "schema_version": "amy.build-metadata.v1",
            "assertion_scope": "workflow-authored-not-independently-certified",
            "source": {
                "repository_uri": REPOSITORY_URI,
                "revision": COMMIT,
                "ref": REF,
                "git_object_format": "sha1",
                "tree": TREE,
                "dirty": False,
                "snapshot": {
                    "path": "payload/source/source.tar",
                    "sha256": source_snapshot_sha256,
                    "format": "application/x-tar",
                    "assurance": "exact-opaque-bytes-no-git-tree-equivalence-claim",
                },
            },
            "dependency_lock": {
                "path": "payload/environment/uv.lock",
                "sha256": lock_sha256,
            },
            "execution_image": {
                "reference": "ghcr.io/astral-sh/uv",
                "digest": f"sha256:{IMAGE_SHA256}",
            },
        },
        "payloads": [
            {
                "path": "payload/environment/uv.lock",
                "bytes": 4,
                "sha256": lock_sha256,
                "media_type": "text/plain",
                "role": "environment_lock",
            },
            {
                "path": "payload/source/source.tar",
                "bytes": 4,
                "sha256": source_snapshot_sha256,
                "media_type": "application/x-tar",
                "role": "source_code",
            },
        ],
    }
    return rfc8785.dumps(value)


def _statement(manifest_raw: bytes) -> dict:
    return {
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
                "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                "externalParameters": {
                    "workflow": {
                        "repository": REPOSITORY_URI,
                        "path": ".github/workflows/attest-verifiable-study.yml",
                        "ref": REF,
                    },
                },
                "resolvedDependencies": [
                    {
                        "uri": f"git+{REPOSITORY_URI}@{REF}",
                        "digest": {"gitCommit": COMMIT},
                    }
                ],
            },
            "runDetails": {"builder": {"id": IDENTITY}},
        },
    }


def _output(manifest_raw: bytes) -> list[dict]:
    certificate = {
        "certificateIssuer": "CN=sigstore-intermediate,O=sigstore.dev",
        "issuer": "https://token.actions.githubusercontent.com",
        "subjectAlternativeName": IDENTITY,
        "sourceRepositoryURI": REPOSITORY_URI,
        "sourceRepositoryOwnerURI": "https://github.com/Ganador1",
        "buildSignerDigest": COMMIT,
        "sourceRepositoryDigest": COMMIT,
        "sourceRepositoryRef": REF,
        "runnerEnvironment": "github-hosted",
        "githubWorkflowTrigger": "push",
        "sourceRepositoryVisibilityAtSigning": "public",
    }
    return [
        {
            "attestation": {
                "bundle": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}
            },
            "verificationResult": {
                "mediaType": "application/vnd.dev.sigstore.verificationresult+json;version=0.1",
                "signature": {"certificate": certificate},
                "verifiedTimestamps": [
                    {
                        "type": "Tlog",
                        "uri": "https://rekor.sigstore.dev",
                        "timestamp": "2026-07-13T00:00:00Z",
                    }
                ],
                "statement": _statement(manifest_raw),
            },
        }
    ]


def test_extract_untrusted_predicate_type_only_selects_the_signed_candidate() -> None:
    statement = _statement(b"manifest")
    bundle = {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {},
        "dsseEnvelope": {
            "payload": base64.b64encode(
                json.dumps(statement, separators=(",", ":")).encode()
            ).decode(),
            "payloadType": "application/vnd.in-toto+json",
            "signatures": [],
        },
    }
    raw = json.dumps(bundle, separators=(",", ":")).encode()
    assert (
        extract_untrusted_predicate_type(raw, max_depth=32, max_statement=8192)
        == "https://slsa.dev/provenance/v1"
    )


def test_p3_enforces_subject_identity_transparency_and_materials() -> None:
    manifest = _manifest()
    statement, certificate, timestamps = validate_verified_output(
        _output(manifest),
        profile_id="P3",
        manifest_raw=manifest,
        policy=_policy(),
        predicate_type="https://slsa.dev/provenance/v1",
    )
    assert statement["subject"][0]["digest"]["sha256"] == hashlib.sha256(manifest).hexdigest()
    assert certificate["sourceRepositoryDigest"] == COMMIT
    assert timestamps[0]["type"] == "Tlog"


def test_p2_does_not_enforce_predicate_material_semantics() -> None:
    manifest = _manifest(lock_sha256="0" * 64)
    output = _output(manifest)
    validate_verified_output(
        output,
        profile_id="P2",
        manifest_raw=manifest,
        policy=_policy(),
        predicate_type="https://slsa.dev/provenance/v1",
    )
    with pytest.raises(GitHubGateRejected, match="dependency lock differs"):
        validate_verified_output(
            output,
            profile_id="P3",
            manifest_raw=manifest,
            policy=_policy(),
            predicate_type="https://slsa.dev/provenance/v1",
        )


def test_exact_certificate_identity_is_used_instead_of_workflow_prefix() -> None:
    command = build_gh_verify_command(
        Path("/opt/gh"),
        Path("/tmp/MANIFEST.jcs.json"),
        Path("/tmp/attestation.sigstore.json"),
        Path("/tmp/trusted_root.jsonl"),
        _policy(),
        "https://slsa.dev/provenance/v1",
    )
    assert "--cert-identity" in command
    assert "--signer-workflow" not in command
    assert command[command.index("--cert-identity") + 1] == IDENTITY
    assert command[command.index("--source-digest") + 1] == COMMIT
    assert command[command.index("--signer-digest") + 1] == COMMIT


def test_attestation_only_api_refuses_to_label_an_incomplete_check_as_p3() -> None:
    with pytest.raises(GitHubGateConfigurationError, match="use verify_github_p3_release"):
        verify_github_manifest_attestation(
            Path("missing-manifest"),
            Path("missing-bundle"),
            Path("missing-root"),
            profile_id="P3",
            policy=_policy(),
        )


def test_production_p3_runs_p1_and_rejects_changed_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_raw = b"src\n"
    lock_raw = b"lock"
    source_sha256 = hashlib.sha256(source_raw).hexdigest()
    lock_sha256 = hashlib.sha256(lock_raw).hexdigest()
    manifest_raw = _manifest(
        lock_sha256=lock_sha256,
        source_snapshot_sha256=source_sha256,
    )
    release_root = tmp_path / "release"
    (release_root / "payload/source").mkdir(parents=True)
    (release_root / "payload/environment").mkdir(parents=True)
    (release_root / "payload/source/source.tar").write_bytes(source_raw)
    (release_root / "payload/environment/uv.lock").write_bytes(lock_raw)
    (release_root / "MANIFEST.jcs.json").write_bytes(manifest_raw)

    schema_path = Path(__file__).resolve().parents[1] / (
        "schemas/manifest-production-v0.2.schema.json"
    )
    policy = _policy()
    policy["manifest"]["schema_sha256"] = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    policy["provenance"]["manifest_assertions"]["source"]["snapshot"][
        "sha256"
    ] = source_sha256
    policy["provenance"]["manifest_assertions"]["dependency_lock"][
        "sha256"
    ] = lock_sha256

    def fake_attestation(*args, **kwargs):
        return GitHubAttestationEvidence(
            profile_id="P3",
            manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            bundle_sha256="1" * 64,
            trusted_root_sha256="2" * 64,
            predicate_type="https://slsa.dev/provenance/v1",
            certificate={},
            verified_timestamps=[],
            statement={},
            gh_version="2.96.0",
            gh_binary_sha256="3" * 64,
            gh_command=("gh",),
        )

    monkeypatch.setattr(
        github_attestation,
        "_verify_github_manifest_attestation",
        fake_attestation,
    )
    evidence = verify_github_p3_release(
        release_root,
        tmp_path / "trusted-root.jsonl",
        schema_path,
        policy=policy,
    )
    assert evidence.p1_checks
    assert set(evidence.p1_checks.values()) == {"PASS"}

    (release_root / "payload/environment/uv.lock").write_bytes(b"evil")
    with pytest.raises(GitHubGateRejected) as error:
        verify_github_p3_release(
            release_root,
            tmp_path / "trusted-root.jsonl",
            schema_path,
            policy=policy,
        )
    assert error.value.code == "DIGEST_MISMATCH"
