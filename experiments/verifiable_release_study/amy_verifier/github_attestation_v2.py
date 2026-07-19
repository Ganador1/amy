from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .github_attestation_v2_core import (
    GitHubAttestationEvidence,
    GitHubGateConfigurationError,
    evidence_to_json,
    verify_github_manifest_attestation,
    verify_github_p3_release,
)
from .json_tools import bounded_regular_file_read, parse_json_bytes
from .model import VerificationReject


POLICY_SCHEMA_VERSION = "amy.github-attestation-policy-schema.v2-draft"
POLICY_VERSION = "amy.github-attestation-policy.v2-draft"
RESULT_SCHEMA_VERSION = "amy.production-verification-result.v2-draft"
FROZEN_POLICY_STATUS = "release_specific_frozen"
TBD_MARKER = "TBD-BEFORE-REGISTRATION"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class GitHubPolicyDocumentV2:
    """Immutable bytes for an externally pinned policy and both bound schemas.

    Parsed documents are deliberately not retained: a mutable ``dict`` could be
    changed after validation while preserving an old digest. Every use
    rematerializes and revalidates all exact immutable contract bytes.
    """

    policy_raw: bytes
    policy_schema_raw: bytes
    result_schema_raw: bytes
    expected_policy_sha256: str
    policy_sha256: str
    policy_schema_sha256: str
    result_schema_sha256: str


@dataclass(frozen=True)
class GitHubAttestationEvidenceV2:
    """Immutable isolated-core evidence snapshot plus the exact v2 output contract."""

    verified_accept_json: bytes
    result_schema_raw: bytes
    policy_sha256: str
    policy_schema_sha256: str
    result_schema_sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GitHubGateConfigurationError(f"{label} must be a lowercase SHA-256")
    return value


def _read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    try:
        return bounded_regular_file_read(path, max_bytes, check="bounded_input")
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(
            f"{label} could not be loaded safely: {exc.message}"
        ) from exc


def _parse_object(raw: bytes, label: str, *, max_depth: int) -> dict[str, Any]:
    try:
        value = parse_json_bytes(
            raw,
            max_depth=max_depth,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(f"{label} is invalid: {exc.message}") from exc
    if not isinstance(value, dict):
        raise GitHubGateConfigurationError(f"{label} must be a JSON object")
    return value


def _schema_errors(value: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    return [
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in errors
    ]


def _walk_tbd(value: Any, location: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        if TBD_MARKER in value:
            found.append(location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_tbd(item, f"{location}[{index}]"))
    elif isinstance(value, dict):
        for key in sorted(value):
            found.extend(_walk_tbd(value[key], f"{location}.{key}"))
    return found


def _validate_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise GitHubGateConfigurationError(
            f"GitHub policy schema is invalid: {type(exc).__name__}: {exc}"
        ) from exc


def _validate_result_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise GitHubGateConfigurationError(
            f"v2 result schema is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    declared_version = (
        ((schema.get("$defs") or {}).get("schemaVersion") or {}).get("const")
    )
    if declared_version != RESULT_SCHEMA_VERSION:
        raise GitHubGateConfigurationError(
            "v2 result schema does not declare the expected version"
        )


def _validate_policy_schema_identity(
    policy: dict[str, Any], schema_sha256: str
) -> None:
    identity = policy.get("policy_schema")
    if not isinstance(identity, dict):
        raise GitHubGateConfigurationError("policy_schema identity is absent")
    if identity.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise GitHubGateConfigurationError("policy-schema version is not the v2 contract")
    if identity.get("schema_sha256") != schema_sha256:
        raise GitHubGateConfigurationError(
            "GitHub policy schema differs from the digest declared by the policy"
        )


def _validate_cross_field_consistency(policy: dict[str, Any]) -> None:
    identity = policy["identity"]
    provenance = policy["provenance"]
    asserted_source = provenance["manifest_assertions"]["source"]
    repository = identity["repository_uri"]
    revision = identity["source_digest"]
    source_ref = identity["source_ref"]

    if provenance["source_repository_uri"] != repository:
        raise GitHubGateConfigurationError(
            "identity/provenance repository URI mismatch"
        )
    if provenance["source_revision"] != revision or asserted_source["revision"] != revision:
        raise GitHubGateConfigurationError(
            "identity/provenance/manifest source revision mismatch"
        )
    if provenance["source_ref"] != source_ref or asserted_source["ref"] != source_ref:
        raise GitHubGateConfigurationError(
            "identity/provenance/manifest source ref mismatch"
        )
    if provenance["builder_id"] != identity["certificate_identity"]:
        raise GitHubGateConfigurationError(
            "builder and certificate identity policy mismatch"
        )
    expected_dependency = f"git+{repository}@{source_ref}"
    if provenance["resolved_source_dependency_uri"] != expected_dependency:
        raise GitHubGateConfigurationError(
            "resolved source dependency URI is inconsistent"
        )

    object_format = asserted_source["git_object_format"]
    expected_length = 40 if object_format == "sha1" else 64
    if len(revision) != expected_length or len(asserted_source["tree"]) != expected_length:
        raise GitHubGateConfigurationError(
            "source revision/tree length differs from Git object format"
        )

    archive_platforms = set(policy["tool"]["archive_sha256_by_platform"])
    binary_platforms = set(policy["tool"]["binary_sha256_by_platform"])
    if archive_platforms != binary_platforms:
        raise GitHubGateConfigurationError(
            "tool archive and binary platform maps differ"
        )
    expected_release_url = (
        "https://github.com/cli/cli/releases/tag/v" + policy["tool"]["version"]
    )
    if policy["tool"]["release_url"] != expected_release_url:
        raise GitHubGateConfigurationError(
            "GitHub CLI release URL differs from the frozen version"
        )


def _require_authenticated_workflow_dependency_binding(policy: dict[str, Any]) -> None:
    assurance = policy.get("workflow_dependency_assurance")
    if not isinstance(assurance, dict):
        raise GitHubGateConfigurationError("workflow dependency assurance is absent")
    if (
        assurance.get("verification_status")
        != "NO_GO_AUTHENTICATED_WORKFLOW_BYTES_ABSENT"
        or assurance.get("pins_are_authorization_evidence") is not False
    ):
        raise GitHubGateConfigurationError(
            "workflow dependency policy has an unsupported assurance state"
        )
    raise GitHubGateConfigurationError(
        "workflow dependency pins are NO-GO: authenticated workflow bytes are absent"
    )


def _materialize_document(
    document: GitHubPolicyDocumentV2, *, require_frozen: bool
) -> dict[str, Any]:
    if not isinstance(document, GitHubPolicyDocumentV2):
        raise GitHubGateConfigurationError(
            "v2 verification requires a GitHubPolicyDocumentV2"
        )
    expected = _require_sha256(
        document.expected_policy_sha256, "expected_policy_sha256"
    )
    policy_sha256 = _sha256(document.policy_raw)
    schema_sha256 = _sha256(document.policy_schema_raw)
    result_schema_sha256 = _sha256(document.result_schema_raw)
    if policy_sha256 != expected or document.policy_sha256 != policy_sha256:
        raise GitHubGateConfigurationError(
            "policy bytes differ from the externally expected SHA-256"
        )
    if document.policy_schema_sha256 != schema_sha256:
        raise GitHubGateConfigurationError(
            "policy-schema bytes differ from the validated document identity"
        )
    if document.result_schema_sha256 != result_schema_sha256:
        raise GitHubGateConfigurationError(
            "result-schema bytes differ from the validated document identity"
        )

    schema = _parse_object(
        document.policy_schema_raw, "GitHub policy schema", max_depth=128
    )
    _validate_schema(schema)
    policy = _parse_object(document.policy_raw, "GitHub attestation policy", max_depth=64)
    errors = _schema_errors(policy, schema)
    if errors:
        raise GitHubGateConfigurationError(
            "GitHub attestation policy fails its closed schema: " + errors[0]
        )
    if policy.get("schema_version") != POLICY_VERSION:
        raise GitHubGateConfigurationError("policy document is not the v2 contract")
    _validate_policy_schema_identity(policy, schema_sha256)

    result = policy.get("result")
    if not isinstance(result, dict):
        raise GitHubGateConfigurationError("production result policy is absent")
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise GitHubGateConfigurationError("result-schema version is not the v2 contract")
    result_sha256 = _require_sha256(
        result.get("schema_sha256"), "result.schema_sha256"
    )
    if document.result_schema_sha256 != result_sha256:
        raise GitHubGateConfigurationError(
            "result-schema digest differs from the validated document identity"
        )
    result_schema = _parse_object(
        document.result_schema_raw, "v2 production result schema", max_depth=128
    )
    _validate_result_schema(result_schema)

    if require_frozen:
        if policy.get("status") != FROZEN_POLICY_STATUS:
            raise GitHubGateConfigurationError(
                "v2 policy is a template and is not valid for verification"
            )
        policy_version = policy.get("policy_version")
        if not isinstance(policy_version, str) or "-" in policy_version:
            raise GitHubGateConfigurationError(
                "a frozen v2 policy requires a stable, non-prerelease policy_version"
            )
        unresolved = _walk_tbd(policy)
        if unresolved:
            raise GitHubGateConfigurationError(
                "frozen v2 policy contains unresolved placeholders: " + unresolved[0]
            )
        _validate_cross_field_consistency(policy)
        _require_authenticated_workflow_dependency_binding(policy)
    return policy


def load_github_policy_v2(
    policy_path: Path,
    policy_schema_path: Path,
    result_schema_path: Path,
    *,
    expected_policy_sha256: str,
    policy_max_bytes: int = 1024 * 1024,
    schema_max_bytes: int = 1024 * 1024,
    result_schema_max_bytes: int = 1024 * 1024,
) -> GitHubPolicyDocumentV2:
    """Load a complete v2 contract only when an external digest authorizes it."""

    expected = _require_sha256(expected_policy_sha256, "expected_policy_sha256")
    policy_schema_raw = _read_bounded(
        policy_schema_path, schema_max_bytes, "GitHub policy schema"
    )
    policy_raw = _read_bounded(policy_path, policy_max_bytes, "GitHub attestation policy")
    result_schema_raw = _read_bounded(
        result_schema_path, result_schema_max_bytes, "v2 production result schema"
    )
    policy_sha256 = _sha256(policy_raw)
    if policy_sha256 != expected:
        raise GitHubGateConfigurationError(
            "policy bytes differ from the externally expected SHA-256"
        )

    schema = _parse_object(policy_schema_raw, "GitHub policy schema", max_depth=128)
    _validate_schema(schema)
    policy = _parse_object(policy_raw, "GitHub attestation policy", max_depth=64)
    errors = _schema_errors(policy, schema)
    if errors:
        raise GitHubGateConfigurationError(
            "GitHub attestation policy fails its closed schema: " + errors[0]
        )
    schema_sha256 = _sha256(policy_schema_raw)
    _validate_policy_schema_identity(policy, schema_sha256)
    result = policy.get("result")
    if not isinstance(result, dict):
        raise GitHubGateConfigurationError("production result policy is absent")
    result_sha256 = _require_sha256(
        result.get("schema_sha256"), "result.schema_sha256"
    )
    if _sha256(result_schema_raw) != result_sha256:
        raise GitHubGateConfigurationError(
            "v2 production result schema differs from the externally pinned policy"
        )
    result_schema = _parse_object(
        result_schema_raw, "v2 production result schema", max_depth=128
    )
    _validate_result_schema(result_schema)
    document = GitHubPolicyDocumentV2(
        policy_raw=policy_raw,
        policy_schema_raw=policy_schema_raw,
        result_schema_raw=result_schema_raw,
        expected_policy_sha256=expected,
        policy_sha256=policy_sha256,
        policy_schema_sha256=schema_sha256,
        result_schema_sha256=result_sha256,
    )
    _materialize_document(document, require_frozen=False)
    return document


def require_frozen_policy_v2(document: GitHubPolicyDocumentV2) -> None:
    _materialize_document(document, require_frozen=True)


def policy_contract_identity_v2(
    document: GitHubPolicyDocumentV2,
) -> dict[str, str]:
    _materialize_document(document, require_frozen=False)
    return {
        "policy_sha256": document.policy_sha256,
        "policy_schema_sha256": document.policy_schema_sha256,
        "result_schema_sha256": document.result_schema_sha256,
    }


def _bind_evidence(
    evidence: GitHubAttestationEvidence,
    document: GitHubPolicyDocumentV2,
) -> GitHubAttestationEvidenceV2:
    if not isinstance(evidence, GitHubAttestationEvidence):
        raise GitHubGateConfigurationError(
            "v2 binding requires evidence produced by the isolated v2 core"
        )
    base = evidence_to_json(evidence)
    raw = json.dumps(
        base,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return GitHubAttestationEvidenceV2(
        verified_accept_json=raw,
        result_schema_raw=document.result_schema_raw,
        policy_sha256=document.policy_sha256,
        policy_schema_sha256=document.policy_schema_sha256,
        result_schema_sha256=document.result_schema_sha256,
    )


def verify_github_manifest_attestation_v2(
    manifest_path: Path,
    bundle_path: Path,
    trusted_root_path: Path,
    *,
    profile_id: str,
    policy: GitHubPolicyDocumentV2,
    gh_binary: str = "gh",
) -> GitHubAttestationEvidenceV2:
    policy_value = _materialize_document(policy, require_frozen=True)
    evidence = verify_github_manifest_attestation(
        manifest_path,
        bundle_path,
        trusted_root_path,
        profile_id=profile_id,
        policy=policy_value,
        gh_binary=gh_binary,
    )
    return _bind_evidence(evidence, policy)


def verify_github_p3_release_v2(
    release_root: Path,
    trusted_root_path: Path,
    manifest_schema_path: Path,
    *,
    policy: GitHubPolicyDocumentV2,
    gh_binary: str = "gh",
) -> GitHubAttestationEvidenceV2:
    policy_value = _materialize_document(policy, require_frozen=True)
    evidence = verify_github_p3_release(
        release_root,
        trusted_root_path,
        manifest_schema_path,
        policy=policy_value,
        gh_binary=gh_binary,
    )
    return _bind_evidence(evidence, policy)


def evidence_to_json_v2(
    evidence: GitHubAttestationEvidenceV2,
) -> dict[str, Any]:
    if not isinstance(evidence, GitHubAttestationEvidenceV2):
        raise GitHubGateConfigurationError(
            "v2 serialization requires GitHubAttestationEvidenceV2"
        )
    for label, value in (
        ("policy_sha256", evidence.policy_sha256),
        ("policy_schema_sha256", evidence.policy_schema_sha256),
        ("result_schema_sha256", evidence.result_schema_sha256),
    ):
        _require_sha256(value, label)
    base = _parse_object(
        evidence.verified_accept_json, "verified v2 evidence snapshot", max_depth=128
    )
    if (
        base.get("schema_version") != "amy.production-verification-result.v1-draft"
        or base.get("decision") != "ACCEPT"
    ):
        raise GitHubGateConfigurationError(
            "verified evidence snapshot is not a v1 ACCEPT object"
        )
    base["schema_version"] = RESULT_SCHEMA_VERSION
    base["policy_sha256"] = evidence.policy_sha256
    base["policy_schema_sha256"] = evidence.policy_schema_sha256
    base["result_schema_sha256"] = evidence.result_schema_sha256
    if _sha256(evidence.result_schema_raw) != evidence.result_schema_sha256:
        raise GitHubGateConfigurationError(
            "v2 evidence result-schema bytes differ from its declared digest"
        )
    result_schema = _parse_object(
        evidence.result_schema_raw, "v2 evidence result schema", max_depth=128
    )
    _validate_result_schema(result_schema)
    errors = _schema_errors(base, result_schema)
    if errors:
        raise GitHubGateConfigurationError(
            "v2 ACCEPT evidence fails its exact result schema: " + errors[0]
        )
    return base
