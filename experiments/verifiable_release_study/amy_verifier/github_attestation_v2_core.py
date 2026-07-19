from __future__ import annotations

import base64
import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

# Exception compatibility lets the existing CLI catch V2 failures. No V1
# verifier function or evidence class crosses this module boundary.
from .github_attestation import (
    GitHubGateConfigurationError,
    GitHubGateError,
    GitHubGateRejected,
    GitHubGateToolError,
)
from .json_tools import bounded_regular_file_read, parse_json_bytes
from .manifest import validate_p1_manifest
from .model import VerificationReject


@dataclass(frozen=True)
class GitHubAttestationEvidence:
    profile_id: str
    manifest_sha256: str
    bundle_sha256: str
    trusted_root_sha256: str
    predicate_type: str
    certificate: dict[str, Any]
    verified_timestamps: list[dict[str, Any]]
    statement: dict[str, Any]
    gh_version: str
    gh_binary_sha256: str
    gh_command: tuple[str, ...]
    manifest_schema_sha256: str | None = None
    p1_checks: dict[str, str] | None = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }
    return f"{system}-{aliases.get(machine, machine)}"


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitHubGateConfigurationError(f"{label} must be a JSON object")
    return value


def _require_authenticated_mapping(
    value: Any,
    label: str,
    required_keys: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required_keys:
        missing = (
            sorted(required_keys - set(value))
            if isinstance(value, dict)
            else sorted(required_keys)
        )
        unexpected = sorted(set(value) - required_keys) if isinstance(value, dict) else []
        raise GitHubGateRejected(
            "PROVENANCE_INVALID",
            f"authenticated {label} has missing or unexpected fields",
            {"missing": missing, "unexpected": unexpected},
        )
    return value


def _require_text(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubGateConfigurationError(f"{label}.{key} must be a non-empty string")
    if "TBD-BEFORE-REGISTRATION" in value:
        raise GitHubGateConfigurationError(f"{label}.{key} is not frozen")
    return value


def _require_hex(value: str, lengths: set[int], label: str) -> str:
    if len(value) not in lengths or re.fullmatch(r"[0-9a-f]+", value) is None:
        raise GitHubGateConfigurationError(
            f"{label} must be lowercase hexadecimal with length {sorted(lengths)}"
        )
    return value


def _policy_sections(policy: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        _require_mapping(policy.get(name), name)
        for name in (
            "tool",
            "subject",
            "identity",
            "trust",
            "statement",
            "provenance",
            "limits",
        )
    )


def load_github_policy(path: Path, *, max_bytes: int = 1024 * 1024) -> tuple[dict[str, Any], bytes]:
    try:
        raw = bounded_regular_file_read(path, max_bytes, check="bounded_input")
        value = parse_json_bytes(
            raw,
            max_depth=32,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(exc.message) from exc
    if not isinstance(value, dict):
        raise GitHubGateConfigurationError("GitHub attestation policy must be a JSON object")
    _policy_sections(value)
    return value, raw


def extract_untrusted_predicate_type(
    bundle_raw: bytes, *, max_depth: int, max_statement: int
) -> str:
    """Extract only the candidate type needed by gh; nothing returned here is trusted."""

    try:
        bundle = parse_json_bytes(
            bundle_raw,
            max_depth=max_depth,
            reject_duplicate_keys=True,
            failure_check="attestation_structure",
            invalid_reason="ATTESTATION_INVALID",
            duplicate_reason="ATTESTATION_INVALID",
        )
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc
    if not isinstance(bundle, dict):
        raise GitHubGateRejected("ATTESTATION_INVALID", "Sigstore bundle is not an object")
    envelope = bundle.get("dsseEnvelope")
    if not isinstance(envelope, dict):
        raise GitHubGateRejected("ATTESTATION_INVALID", "Sigstore bundle has no DSSE envelope")
    encoded = envelope.get("payload")
    if not isinstance(encoded, str):
        raise GitHubGateRejected("ATTESTATION_INVALID", "DSSE payload is not base64 text")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise GitHubGateRejected("ATTESTATION_INVALID", "DSSE payload is not valid base64") from exc
    if len(payload) > max_statement:
        raise GitHubGateRejected(
            "RESOURCE_LIMIT",
            "DSSE Statement exceeds the byte limit",
            {"observed_bytes": len(payload), "max_bytes": max_statement},
        )
    try:
        statement = parse_json_bytes(
            payload,
            max_depth=max_depth,
            reject_duplicate_keys=True,
            failure_check="attestation_structure",
            invalid_reason="ATTESTATION_INVALID",
            duplicate_reason="ATTESTATION_INVALID",
        )
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc
    predicate_type = statement.get("predicateType") if isinstance(statement, dict) else None
    if (
        not isinstance(predicate_type, str)
        or len(predicate_type) > 2048
        or re.fullmatch(r"https://[^\s\x00-\x1f\x7f]+", predicate_type) is None
    ):
        raise GitHubGateRejected(
            "ATTESTATION_INVALID", "candidate predicateType is not a bounded HTTPS URI"
        )
    return predicate_type


def build_gh_verify_command(
    gh_path: Path,
    manifest_path: Path,
    bundle_path: Path,
    trusted_root_path: Path,
    policy: dict[str, Any],
    predicate_type: str,
) -> tuple[str, ...]:
    _, subject, identity, _, _, _, _ = _policy_sections(policy)
    if _require_text(subject, "digest_algorithm", "subject") != "sha256":
        raise GitHubGateConfigurationError("production subject digest must be sha256")
    command = (
        str(gh_path),
        "attestation",
        "verify",
        str(manifest_path),
        "--digest-alg",
        "sha256",
        "--bundle",
        str(bundle_path),
        "--custom-trusted-root",
        str(trusted_root_path),
        "--repo",
        _require_text(identity, "repository", "identity"),
        "--cert-identity",
        _require_text(identity, "certificate_identity", "identity"),
        "--cert-oidc-issuer",
        _require_text(identity, "oidc_issuer", "identity"),
        "--signer-digest",
        _require_hex(
            _require_text(identity, "signer_digest", "identity"), {40, 64}, "identity.signer_digest"
        ),
        "--source-digest",
        _require_hex(
            _require_text(identity, "source_digest", "identity"), {40, 64}, "identity.source_digest"
        ),
        "--source-ref",
        _require_text(identity, "source_ref", "identity"),
        "--predicate-type",
        predicate_type,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    )
    return command


def _material_map(predicate: dict[str, Any]) -> dict[str, dict[str, str]]:
    definition = predicate.get("buildDefinition")
    dependencies = definition.get("resolvedDependencies") if isinstance(definition, dict) else None
    if not isinstance(dependencies, list):
        raise GitHubGateRejected("PROVENANCE_INVALID", "resolvedDependencies is missing")
    found: dict[str, dict[str, str]] = {}
    for item in dependencies:
        if not isinstance(item, dict) or not isinstance(item.get("uri"), str):
            raise GitHubGateRejected("PROVENANCE_INVALID", "a resolved dependency is malformed")
        uri = item["uri"]
        digest = item.get("digest")
        if uri in found or not isinstance(digest, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in digest.items()
        ):
            raise GitHubGateRejected("PROVENANCE_INVALID", "resolved dependencies are ambiguous")
        found[uri] = digest
    return found


def _enforce_manifest_assertions(
    manifest_raw: bytes,
    policy: dict[str, Any],
    provenance: dict[str, Any],
) -> None:
    manifest_policy = _require_mapping(policy.get("manifest"), "manifest")
    limits = _require_mapping(policy.get("limits"), "limits")
    try:
        manifest = parse_json_bytes(
            manifest_raw,
            max_depth=int(limits["json_max_depth"]),
            reject_duplicate_keys=True,
            failure_check="provenance_policy",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubGateConfigurationError("production JSON limits are incomplete") from exc
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc
    if not isinstance(manifest, dict):
        raise GitHubGateRejected("PROVENANCE_INVALID", "authenticated manifest is not an object")
    if manifest.get("schema_version") != _require_text(
        manifest_policy, "schema_version", "manifest"
    ):
        raise GitHubGateRejected(
            "PROVENANCE_INVALID", "authenticated manifest schema version is not authorized"
        )

    metadata = _require_authenticated_mapping(
        manifest.get("build_metadata"),
        "build_metadata",
        {
            "schema_version",
            "assertion_scope",
            "source",
            "dependency_lock",
            "execution_image",
        },
    )
    if metadata.get("schema_version") != _require_text(
        manifest_policy, "build_metadata_schema_version", "manifest"
    ):
        raise GitHubGateRejected(
            "PROVENANCE_INVALID", "authenticated build-metadata schema is not authorized"
        )
    if metadata.get("assertion_scope") != _require_text(
        manifest_policy, "assertion_scope", "manifest"
    ):
        raise GitHubGateRejected(
            "PROVENANCE_INVALID", "build-metadata assertion scope is not explicit"
        )

    expected = _require_mapping(
        provenance.get("manifest_assertions"), "provenance.manifest_assertions"
    )
    expected_source = _require_mapping(expected.get("source"), "manifest_assertions.source")
    source = _require_authenticated_mapping(
        metadata.get("source"),
        "build_metadata.source",
        {
            "repository_uri",
            "revision",
            "ref",
            "git_object_format",
            "tree",
            "dirty",
            "snapshot",
        },
    )
    expected_revision = _require_hex(
        _require_text(expected_source, "revision", "manifest_assertions.source"),
        {40, 64},
        "manifest_assertions.source.revision",
    )
    expected_tree = _require_hex(
        _require_text(expected_source, "tree", "manifest_assertions.source"),
        {40, 64},
        "manifest_assertions.source.tree",
    )
    expected_source_identity = {
        "repository_uri": _require_text(
            expected_source, "repository_uri", "manifest_assertions.source"
        ),
        "revision": expected_revision,
        "ref": _require_text(expected_source, "ref", "manifest_assertions.source"),
    }
    if any(source.get(key) != value for key, value in expected_source_identity.items()):
        raise GitHubGateRejected(
            "SOURCE_MISMATCH", "authenticated manifest source identity differs from policy"
        )
    if source.get("dirty") is not False or expected_source.get("dirty") is not False:
        raise GitHubGateRejected(
            "DIRTY_BUILD", "official manifest metadata does not assert a clean source"
        )
    expected_object_format = _require_text(
        expected_source, "git_object_format", "manifest_assertions.source"
    )
    required_oid_length = 40 if expected_object_format == "sha1" else 64
    if expected_object_format not in {"sha1", "sha256"}:
        raise GitHubGateConfigurationError("unsupported Git object format in policy")
    if len(expected_revision) != required_oid_length or len(expected_tree) != required_oid_length:
        raise GitHubGateConfigurationError(
            "source revision/tree length differs from the frozen Git object format"
        )
    if (
        source.get("git_object_format") != expected_object_format
        or source.get("tree") != expected_tree
    ):
        raise GitHubGateRejected(
            "MATERIAL_MISMATCH", "authenticated Git object format or tree differs from policy"
        )

    payloads = manifest.get("payloads")
    if not isinstance(payloads, list):
        raise GitHubGateRejected("PROVENANCE_INVALID", "authenticated payload inventory is absent")
    payload_by_path: dict[str, dict[str, Any]] = {}
    for entry in payloads:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise GitHubGateRejected(
                "PROVENANCE_INVALID", "authenticated payload inventory is malformed"
            )
        if entry["path"] in payload_by_path:
            raise GitHubGateRejected(
                "PROVENANCE_INVALID", "authenticated payload inventory has duplicate paths"
            )
        payload_by_path[entry["path"]] = entry

    expected_snapshot = _require_mapping(
        expected_source.get("snapshot"), "manifest_assertions.source.snapshot"
    )
    snapshot = _require_authenticated_mapping(
        source.get("snapshot"),
        "build_metadata.source.snapshot",
        {"path", "sha256", "format", "assurance"},
    )
    snapshot_expected_value = {
        "path": _require_text(expected_snapshot, "path", "manifest_assertions.source.snapshot"),
        "sha256": _require_hex(
            _require_text(expected_snapshot, "sha256", "manifest_assertions.source.snapshot"),
            {64},
            "manifest_assertions.source.snapshot.sha256",
        ),
        "format": _require_text(
            expected_snapshot, "format", "manifest_assertions.source.snapshot"
        ),
        "assurance": _require_text(
            expected_snapshot, "assurance", "manifest_assertions.source.snapshot"
        ),
    }
    if snapshot != snapshot_expected_value:
        raise GitHubGateRejected(
            "MATERIAL_MISMATCH", "authenticated source snapshot differs from policy"
        )

    expected_lock = _require_mapping(
        expected.get("dependency_lock"), "manifest_assertions.dependency_lock"
    )
    dependency_lock = _require_authenticated_mapping(
        metadata.get("dependency_lock"),
        "build_metadata.dependency_lock",
        {"path", "sha256"},
    )
    lock_expected_value = {
        "path": _require_text(expected_lock, "path", "manifest_assertions.dependency_lock"),
        "sha256": _require_hex(
            _require_text(expected_lock, "sha256", "manifest_assertions.dependency_lock"),
            {64},
            "manifest_assertions.dependency_lock.sha256",
        ),
    }
    if dependency_lock != lock_expected_value:
        raise GitHubGateRejected(
            "MATERIAL_MISMATCH", "authenticated dependency lock differs from policy"
        )

    for label, value, policy_value in (
        ("source snapshot", snapshot, expected_snapshot),
        ("dependency lock", dependency_lock, expected_lock),
    ):
        entry = payload_by_path.get(value["path"])
        required_role = _require_text(policy_value, "required_payload_role", label)
        if (
            not isinstance(entry, dict)
            or entry.get("sha256") != value["sha256"]
            or entry.get("role") != required_role
        ):
            raise GitHubGateRejected(
                "MATERIAL_MISMATCH",
                f"authenticated {label} is not cross-bound to its required payload entry",
            )

    expected_image = _require_mapping(
        expected.get("execution_image"), "manifest_assertions.execution_image"
    )
    execution_image = _require_authenticated_mapping(
        metadata.get("execution_image"),
        "build_metadata.execution_image",
        {"reference", "digest"},
    )
    image_expected_value = {
        "reference": _require_text(
            expected_image, "reference", "manifest_assertions.execution_image"
        ),
        "digest": _require_text(
            expected_image, "digest", "manifest_assertions.execution_image"
        ),
    }
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_expected_value["digest"]) is None:
        raise GitHubGateConfigurationError("execution-image digest is not a frozen SHA-256")
    if execution_image != image_expected_value:
        raise GitHubGateRejected(
            "MATERIAL_MISMATCH", "authenticated execution image differs from policy"
        )


def _enforce_p3(
    statement: dict[str, Any],
    policy: dict[str, Any],
    manifest_raw: bytes,
) -> None:
    _, _, identity, _, statement_policy, provenance, _ = _policy_sections(policy)
    expected_type = _require_text(statement_policy, "p3_predicate_type", "statement")
    if statement.get("predicateType") != expected_type:
        raise GitHubGateRejected("PREDICATE_TYPE_UNSUPPORTED", "P3 predicate type mismatch")
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise GitHubGateRejected("PROVENANCE_INVALID", "authenticated predicate is not an object")
    definition = predicate.get("buildDefinition")
    details = predicate.get("runDetails")
    if not isinstance(definition, dict) or not isinstance(details, dict):
        raise GitHubGateRejected("PROVENANCE_INVALID", "SLSA provenance structure is incomplete")
    if definition.get("buildType") != _require_text(provenance, "build_type", "provenance"):
        raise GitHubGateRejected("PROVENANCE_INVALID", "build type is not authorized")
    internal = _require_authenticated_mapping(
        definition.get("internalParameters"),
        "buildDefinition.internalParameters",
        {"github"},
    )
    github_internal = _require_authenticated_mapping(
        internal.get("github"),
        "buildDefinition.internalParameters.github",
        {
            "event_name",
            "repository_id",
            "repository_owner_id",
            "runner_environment",
        },
    )
    expected_internal = {
        "event_name": _require_text(identity, "event_name", "identity"),
        "repository_id": _require_text(identity, "repository_id", "identity"),
        "repository_owner_id": _require_text(
            identity, "repository_owner_id", "identity"
        ),
        "runner_environment": "github-hosted",
    }
    if github_internal != expected_internal:
        raise GitHubGateRejected(
            "SIGNER_UNAUTHORIZED",
            "authenticated immutable repository identifiers differ from policy",
        )
    repository = _require_text(provenance, "source_repository_uri", "provenance")
    revision = _require_hex(
        _require_text(provenance, "source_revision", "provenance"),
        {40, 64},
        "provenance.source_revision",
    )
    source_ref = _require_text(provenance, "source_ref", "provenance")
    if _require_text(identity, "repository_uri", "identity") != repository:
        raise GitHubGateConfigurationError("identity/provenance repository URI mismatch")
    if _require_text(identity, "source_digest", "identity") != revision:
        raise GitHubGateConfigurationError("identity/provenance source revision mismatch")
    if _require_text(identity, "source_ref", "identity") != source_ref:
        raise GitHubGateConfigurationError("identity/provenance source ref mismatch")

    expected_workflow = {
        "repository": repository,
        "path": _require_text(provenance, "workflow_path", "provenance"),
        "ref": source_ref,
    }
    external = definition.get("externalParameters")
    if external != {"workflow": expected_workflow}:
        raise GitHubGateRejected("BUILDER_UNAUTHORIZED", "authenticated workflow policy mismatch")
    builder = details.get("builder")
    expected_builder = _require_text(provenance, "builder_id", "provenance")
    if expected_builder != _require_text(identity, "certificate_identity", "identity"):
        raise GitHubGateConfigurationError("builder and certificate identity policy mismatch")
    if not isinstance(builder, dict) or builder.get("id") != expected_builder:
        raise GitHubGateRejected("BUILDER_UNAUTHORIZED", "authenticated builder policy mismatch")

    observed = _material_map(predicate)
    source_dependency_uri = _require_text(
        provenance, "resolved_source_dependency_uri", "provenance"
    )
    expected_dependency_uri = f"git+{repository}@{source_ref}"
    if source_dependency_uri != expected_dependency_uri:
        raise GitHubGateConfigurationError("resolved source dependency URI is inconsistent")
    if len(observed) != 1 or observed.get(source_dependency_uri) != {"gitCommit": revision}:
        raise GitHubGateRejected(
            "SOURCE_MISMATCH", "resolved source dependency does not match the frozen revision"
        )
    _enforce_manifest_assertions(manifest_raw, policy, provenance)


def validate_verified_output(
    output: Any,
    *,
    profile_id: str,
    manifest_raw: bytes,
    policy: dict[str, Any],
    predicate_type: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    _, subject_policy, identity, trust, statement_policy, _, _ = _policy_sections(policy)
    if not isinstance(output, list) or len(output) != 1 or not isinstance(output[0], dict):
        raise GitHubGateRejected(
            "ATTESTATION_AMBIGUOUS", "exactly one verified attestation is required"
        )
    result = output[0].get("verificationResult")
    if not isinstance(result, dict):
        raise GitHubGateToolError("gh success output has no verificationResult")
    attestation = output[0].get("attestation")
    bundle = attestation.get("bundle") if isinstance(attestation, dict) else None
    allowed_bundle_types = trust.get("allowed_bundle_media_types")
    if (
        not isinstance(bundle, dict)
        or not isinstance(allowed_bundle_types, list)
        or bundle.get("mediaType") not in allowed_bundle_types
    ):
        raise GitHubGateRejected("ATTESTATION_INVALID", "Sigstore bundle media type is not frozen")
    allowed_result_types = trust.get("allowed_verification_result_media_types")
    if (
        not isinstance(allowed_result_types, list)
        or result.get("mediaType") not in allowed_result_types
    ):
        raise GitHubGateRejected(
            "ATTESTATION_INVALID", "verification-result media type is not frozen"
        )
    signature = result.get("signature")
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    if not isinstance(certificate, dict):
        raise GitHubGateToolError("gh success output has no parsed certificate")
    expected_certificate = {
        "issuer": _require_text(identity, "oidc_issuer", "identity"),
        "subjectAlternativeName": _require_text(identity, "certificate_identity", "identity"),
        "sourceRepositoryURI": _require_text(identity, "repository_uri", "identity"),
        "sourceRepositoryOwnerURI": _require_text(identity, "repository_owner_uri", "identity"),
        "sourceRepositoryIdentifier": _require_text(identity, "repository_id", "identity"),
        "sourceRepositoryOwnerIdentifier": _require_text(
            identity, "repository_owner_id", "identity"
        ),
        "buildSignerDigest": _require_text(identity, "signer_digest", "identity"),
        "sourceRepositoryDigest": _require_text(identity, "source_digest", "identity"),
        "sourceRepositoryRef": _require_text(identity, "source_ref", "identity"),
        "runnerEnvironment": "github-hosted",
        "githubWorkflowTrigger": _require_text(identity, "event_name", "identity"),
        "sourceRepositoryVisibilityAtSigning": _require_text(identity, "visibility", "identity"),
    }
    for key, expected in expected_certificate.items():
        if certificate.get(key) != expected:
            raise GitHubGateRejected("SIGNER_UNAUTHORIZED", f"certificate field mismatch: {key}")
    issuer_dn = certificate.get("certificateIssuer")
    required_org = _require_text(trust, "certificate_issuer_organization", "trust")
    if not isinstance(issuer_dn, str) or not (
        issuer_dn == f"O={required_org}" or issuer_dn.endswith(f",O={required_org}")
    ):
        raise GitHubGateRejected("SIGNER_UNAUTHORIZED", "certificate authority profile mismatch")

    timestamps = result.get("verifiedTimestamps")
    if not isinstance(timestamps, list) or not all(isinstance(item, dict) for item in timestamps):
        raise GitHubGateToolError("gh success output has malformed verifiedTimestamps")
    required_type = _require_text(trust, "required_timestamp_type", "trust")
    required_uri = _require_text(trust, "required_timestamp_uri", "trust")
    if not any(
        item.get("type") == required_type and item.get("uri") == required_uri
        for item in timestamps
    ):
        raise GitHubGateRejected(
            "TRANSPARENCY_INVALID", "required public transparency evidence is absent"
        )

    statement = result.get("statement")
    if not isinstance(statement, dict):
        raise GitHubGateToolError("gh success output has no authenticated Statement")
    if statement.get("_type") != _require_text(statement_policy, "type", "statement"):
        raise GitHubGateRejected("ATTESTATION_INVALID", "authenticated payload is not Statement v1")
    if statement.get("predicateType") != predicate_type:
        raise GitHubGateRejected(
            "ATTESTATION_INVALID", "verified predicate type differs from requested type"
        )
    subjects = statement.get("subject")
    digest = _sha256(manifest_raw)
    expected_subject = {
        "name": _require_text(subject_policy, "name", "subject"),
        "digest": {"sha256": digest},
    }
    allow_additional = subject_policy.get("allow_additional_subjects")
    if not isinstance(allow_additional, bool):
        raise GitHubGateConfigurationError("subject.allow_additional_subjects must be boolean")
    if not isinstance(subjects, list):
        raise GitHubGateRejected("SUBJECT_MISMATCH", "Statement subject is not an array")
    if (allow_additional and subjects.count(expected_subject) != 1) or (
        not allow_additional and subjects != [expected_subject]
    ):
        raise GitHubGateRejected(
            "SUBJECT_MISMATCH", "Statement does not bind the exact manifest bytes"
        )
    if profile_id == "P3":
        _enforce_p3(statement, policy, manifest_raw)
    return statement, certificate, timestamps


def _write_private(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating private verifier input")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _resolve_gh(gh_binary: str) -> Path:
    candidate = shutil.which(gh_binary) if os.sep not in gh_binary else gh_binary
    if not candidate:
        raise GitHubGateConfigurationError(f"GitHub CLI executable not found: {gh_binary}")
    path = Path(candidate).resolve()
    if not path.is_file():
        raise GitHubGateConfigurationError(f"GitHub CLI path is not a regular file: {path}")
    return path


def _run(
    command: Sequence[str],
    *,
    timeout: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubGateToolError(f"GitHub CLI exceeded the {timeout}s timeout") from exc
    except OSError as exc:
        raise GitHubGateToolError(f"GitHub CLI could not be executed: {exc}") from exc


def _verify_github_manifest_attestation(
    manifest_path: Path,
    bundle_path: Path,
    trusted_root_path: Path,
    *,
    profile_id: str,
    policy: dict[str, Any],
    gh_binary: str = "gh",
) -> GitHubAttestationEvidence:
    if profile_id not in {"P2", "P3"}:
        raise GitHubGateConfigurationError("GitHub attestation gate supports only P2 or P3")
    tool, _, _, trust, statement_policy, _, limits = _policy_sections(policy)
    try:
        manifest_raw = bounded_regular_file_read(
            manifest_path, int(limits["manifest_max_bytes"]), check="bounded_input"
        )
        bundle_raw = bounded_regular_file_read(
            bundle_path, int(limits["attestation_max_bytes"]), check="bounded_input"
        )
        root_raw = bounded_regular_file_read(
            trusted_root_path, int(limits["trusted_root_max_bytes"]), check="bounded_input"
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubGateConfigurationError("production byte limits are incomplete") from exc
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc

    trusted_root_sha256 = _sha256(root_raw)
    expected_root = _require_hex(
        _require_text(trust, "trusted_root_sha256", "trust"), {64}, "trust.trusted_root_sha256"
    )
    if trusted_root_sha256 != expected_root:
        raise GitHubGateRejected("TRUST_ROOT_MISMATCH", "archived trusted-root digest mismatch")

    if profile_id == "P3":
        predicate_type = _require_text(statement_policy, "p3_predicate_type", "statement")
    else:
        predicate_type = extract_untrusted_predicate_type(
            bundle_raw,
            max_depth=int(limits["json_max_depth"]),
            max_statement=int(limits["dsse_statement_max_bytes"]),
        )

    gh_source_path = _resolve_gh(gh_binary)
    binary_max_bytes = tool.get("binary_max_bytes")
    if (
        not isinstance(binary_max_bytes, int)
        or isinstance(binary_max_bytes, bool)
        or not 1 <= binary_max_bytes <= 512 * 1024 * 1024
    ):
        raise GitHubGateConfigurationError(
            "tool.binary_max_bytes must be an integer from 1 to 536870912"
        )
    try:
        gh_binary_raw = bounded_regular_file_read(
            gh_source_path, binary_max_bytes, check="bounded_input"
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(
            f"cannot freeze GitHub CLI bytes: {exc.message}"
        ) from exc
    gh_binary_sha256 = _sha256(gh_binary_raw)
    binary_hashes = _require_mapping(
        tool.get("binary_sha256_by_platform"), "tool.binary_sha256_by_platform"
    )
    platform_key = _platform_key()
    expected_binary = _require_hex(
        _require_text(binary_hashes, platform_key, "tool.binary_sha256_by_platform"),
        {64},
        f"tool.binary_sha256_by_platform.{platform_key}",
    )
    if gh_binary_sha256 != expected_binary:
        raise GitHubGateConfigurationError("GitHub CLI binary hash differs from the frozen tool")

    timeout = tool.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 600:
        raise GitHubGateConfigurationError("tool.timeout_seconds must be an integer from 1 to 600")
    expected_version = _require_text(tool, "version", "tool")
    with tempfile.TemporaryDirectory(prefix="amy-gh-attestation-") as temporary:
        temp_root = Path(temporary)
        exact_gh = temp_root / "gh"
        exact_manifest = temp_root / "MANIFEST.jcs.json"
        exact_bundle = temp_root / "attestation.sigstore.json"
        exact_trust = temp_root / "trusted_root.jsonl"
        _write_private(exact_gh, gh_binary_raw, mode=0o700)
        _write_private(exact_manifest, manifest_raw)
        _write_private(exact_bundle, bundle_raw)
        _write_private(exact_trust, root_raw)

        env = dict(os.environ)
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)
        env.update(
            {
                "GH_CONFIG_DIR": str(temp_root / "gh-config"),
                "GH_NO_UPDATE_NOTIFIER": "1",
                "NO_COLOR": "1",
            }
        )
        version_result = _run((str(exact_gh), "--version"), timeout=10, env=env)
        if version_result.returncode != 0:
            raise GitHubGateToolError("GitHub CLI version check failed")
        first_line = version_result.stdout.decode("utf-8", errors="replace").splitlines()[:1]
        match = re.fullmatch(
            r"gh version ([0-9]+\.[0-9]+\.[0-9]+)(?: .*)?",
            first_line[0] if first_line else "",
        )
        if match is None or match.group(1) != expected_version:
            raise GitHubGateConfigurationError("GitHub CLI version differs from the frozen tool")
        command = build_gh_verify_command(
            exact_gh, exact_manifest, exact_bundle, exact_trust, policy, predicate_type
        )
        completed = _run(command, timeout=timeout, env=env)
        normalized_command = tuple(
            {
                str(exact_gh): "gh",
                str(exact_manifest): "MANIFEST.jcs.json",
                str(exact_bundle): "attestation.sigstore.json",
                str(exact_trust): "trusted_root.jsonl",
            }.get(argument, argument)
            for argument in command
        )
    stderr = completed.stderr.decode("utf-8", errors="replace")[-8192:]
    if completed.returncode != 0:
        raise GitHubGateRejected(
            "ATTESTATION_INVALID",
            "GitHub/Sigstore verification rejected the manifest or attestation",
            {"exit_code": completed.returncode, "stderr_tail": stderr},
        )
    max_output = int(limits.get("gh_output_max_bytes", 32 * 1024 * 1024))
    if len(completed.stdout) > max_output:
        raise GitHubGateToolError("GitHub CLI JSON output exceeded the frozen byte limit")
    try:
        output = parse_json_bytes(
            completed.stdout,
            max_depth=int(limits["json_max_depth"]),
            reject_duplicate_keys=True,
            failure_check="attestation_structure",
            invalid_reason="ATTESTATION_INVALID",
            duplicate_reason="ATTESTATION_INVALID",
        )
    except VerificationReject as exc:
        raise GitHubGateToolError(f"GitHub CLI returned invalid JSON: {exc.message}") from exc
    statement, certificate, timestamps = validate_verified_output(
        output,
        profile_id=profile_id,
        manifest_raw=manifest_raw,
        policy=policy,
        predicate_type=predicate_type,
    )
    return GitHubAttestationEvidence(
        profile_id=profile_id,
        manifest_sha256=_sha256(manifest_raw),
        bundle_sha256=_sha256(bundle_raw),
        trusted_root_sha256=trusted_root_sha256,
        predicate_type=predicate_type,
        certificate=certificate,
        verified_timestamps=timestamps,
        statement=statement,
        gh_version=expected_version,
        gh_binary_sha256=gh_binary_sha256,
        gh_command=normalized_command,
    )


def verify_github_manifest_attestation(
    manifest_path: Path,
    bundle_path: Path,
    trusted_root_path: Path,
    *,
    profile_id: str,
    policy: dict[str, Any],
    gh_binary: str = "gh",
) -> GitHubAttestationEvidence:
    """Verify the signature-only P2 profile.

    Production P3 is intentionally unavailable through this lower-level API:
    callers must use :func:`verify_github_p3_release`, which also executes P1
    over the current payload tree.
    """

    if profile_id != "P2":
        raise GitHubGateConfigurationError(
            "attestation-only verification is P2; use verify_github_p3_release for P3"
        )
    return _verify_github_manifest_attestation(
        manifest_path,
        bundle_path,
        trusted_root_path,
        profile_id=profile_id,
        policy=policy,
        gh_binary=gh_binary,
    )


def verify_github_p3_release(
    release_root: Path,
    trusted_root_path: Path,
    manifest_schema_path: Path,
    *,
    policy: dict[str, Any],
    gh_binary: str = "gh",
) -> GitHubAttestationEvidence:
    """Verify production P3: authenticated provenance plus complete P1 payload checks."""

    manifest_path = release_root / "MANIFEST.jcs.json"
    bundle_path = release_root / "attestation.sigstore.json"
    manifest_policy = _require_mapping(policy.get("manifest"), "manifest")
    try:
        schema_raw = bounded_regular_file_read(
            manifest_schema_path, 1024 * 1024, check="bounded_input"
        )
        schema = parse_json_bytes(
            schema_raw,
            max_depth=64,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(
            f"production manifest schema could not be loaded safely: {exc.message}"
        ) from exc
    if not isinstance(schema, dict):
        raise GitHubGateConfigurationError("production manifest schema is not a JSON object")
    schema_sha256 = _sha256(schema_raw)
    expected_schema_sha256 = _require_hex(
        _require_text(manifest_policy, "schema_sha256", "manifest"),
        {64},
        "manifest.schema_sha256",
    )
    if schema_sha256 != expected_schema_sha256:
        raise GitHubGateConfigurationError(
            "production manifest schema differs from the frozen policy"
        )

    evidence = _verify_github_manifest_attestation(
        manifest_path,
        bundle_path,
        trusted_root_path,
        profile_id="P3",
        policy=policy,
        gh_binary=gh_binary,
    )
    limits = _require_mapping(policy.get("limits"), "limits")
    try:
        manifest_raw = bounded_regular_file_read(
            manifest_path, int(limits["manifest_max_bytes"]), check="bounded_input"
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubGateConfigurationError("production manifest byte limit is incomplete") from exc
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc
    if _sha256(manifest_raw) != evidence.manifest_sha256:
        raise GitHubGateRejected(
            "INPUT_CHANGED", "manifest changed between attestation and payload verification"
        )

    checks = {
        "manifest_json_syntax": "NOT_RUN",
        "manifest_canonicality": "NOT_RUN",
        "manifest_schema": "NOT_RUN",
        "path_safety": "NOT_RUN",
        "closed_world_inventory": "NOT_RUN",
        "payload_digests": "NOT_RUN",
    }
    try:
        validate_p1_manifest(
            manifest_raw,
            root=release_root,
            policy=policy,
            schema=schema,
            checks=checks,
        )
    except VerificationReject as exc:
        raise GitHubGateRejected(exc.reason, exc.message, exc.details) from exc
    try:
        final_manifest_raw = bounded_regular_file_read(
            manifest_path, int(limits["manifest_max_bytes"]), check="bounded_input"
        )
    except VerificationReject as exc:
        raise GitHubGateRejected(
            "INPUT_CHANGED",
            "manifest became unavailable after payload verification",
            {"final_reason": exc.reason},
        ) from exc
    if final_manifest_raw != manifest_raw:
        raise GitHubGateRejected(
            "INPUT_CHANGED", "manifest changed during payload verification"
        )
    incomplete = sorted(name for name, state in checks.items() if state != "PASS")
    if incomplete:
        raise GitHubGateToolError(f"P1 checks did not terminate: {incomplete}")
    return replace(
        evidence,
        manifest_schema_sha256=schema_sha256,
        p1_checks=checks,
    )


def evidence_to_json(evidence: GitHubAttestationEvidence) -> dict[str, Any]:
    result = {
        "schema_version": "amy.production-verification-result.v1-draft",
        "decision": "ACCEPT",
        "profile_id": evidence.profile_id,
        "manifest_sha256": evidence.manifest_sha256,
        "bundle_sha256": evidence.bundle_sha256,
        "trusted_root_sha256": evidence.trusted_root_sha256,
        "predicate_type": evidence.predicate_type,
        "certificate": evidence.certificate,
        "verified_timestamps": evidence.verified_timestamps,
        "statement": evidence.statement,
        "tool": {
            "name": "gh",
            "version": evidence.gh_version,
            "binary_sha256": evidence.gh_binary_sha256,
            "argv": list(evidence.gh_command),
        },
    }
    if evidence.manifest_schema_sha256 is not None:
        result["manifest_schema_sha256"] = evidence.manifest_schema_sha256
    if evidence.p1_checks is not None:
        result["p1_checks"] = evidence.p1_checks
    return result
