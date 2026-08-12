from __future__ import annotations

from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator

from .json_tools import bounded_regular_file_read, parse_json_bytes
from .model import VerificationReject
from .path_policy import hash_payload, observe_payload_tree, validate_manifest_paths


def parse_p0_manifest(raw: bytes, policy: dict[str, Any]) -> Any:
    return parse_json_bytes(
        raw,
        max_depth=policy["limits"]["json_max_depth"],
        reject_duplicate_keys=False,
        failure_check="manifest_json_syntax",
    )


def validate_p1_manifest(
    raw: bytes,
    *,
    root: Path,
    policy: dict[str, Any],
    schema: dict[str, Any],
    checks: dict[str, str],
) -> dict[str, Any]:
    manifest = parse_json_bytes(
        raw,
        max_depth=policy["limits"]["json_max_depth"],
        reject_duplicate_keys=True,
        failure_check="manifest_json_syntax",
    )
    checks["manifest_json_syntax"] = "PASS"

    try:
        canonical = rfc8785.dumps(manifest)
    except Exception as exc:
        raise VerificationReject(
            "MANIFEST_NONCANONICAL",
            "manifest_canonicality",
            "manifest cannot be represented under RFC 8785",
            {"error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if canonical != raw:
        raise VerificationReject(
            "MANIFEST_NONCANONICAL",
            "manifest_canonicality",
            "manifest bytes are not the RFC 8785 representation",
        )
    checks["manifest_canonicality"] = "PASS"

    validation_errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if validation_errors:
        error = validation_errors[0]
        raise VerificationReject(
            "SCHEMA_INVALID",
            "manifest_schema",
            "manifest failed the frozen JSON Schema",
            {
                "json_path": [str(part) for part in error.absolute_path],
                "message": error.message,
                "error_count": len(validation_errors),
            },
        )
    checks["manifest_schema"] = "PASS"

    payloads = manifest["payloads"]
    paths = validate_manifest_paths(
        [entry["path"] for entry in payloads],
        max_bytes=policy["limits"]["path_max_utf8_bytes"],
        max_components=policy["limits"]["path_max_components"],
    )
    checks["path_safety"] = "PASS"

    kind = manifest["release"]["kind"]
    required_roles = set(
        policy["manifest"]["required_roles_by_release_kind"].get(kind, [])
    )
    observed_roles = {entry["role"] for entry in payloads}
    missing_roles = sorted(required_roles - observed_roles)
    if missing_roles:
        raise VerificationReject(
            "REQUIRED_ROLE_MISSING",
            "closed_world_inventory",
            "manifest omits one or more required semantic roles",
            {"missing_roles": missing_roles},
        )

    observations = observe_payload_tree(
        root,
        max_count=policy["limits"]["payload_file_max_count"],
        max_total_bytes=policy["limits"]["payload_total_max_bytes"],
    )
    manifest_paths = set(paths)
    observed_paths = set(observations)
    missing_paths = sorted(manifest_paths - observed_paths)
    if missing_paths:
        raise VerificationReject(
            "PAYLOAD_MISSING",
            "closed_world_inventory",
            "one or more manifest-listed payloads are missing",
            {"missing_paths": missing_paths},
        )
    unexpected_paths = sorted(observed_paths - manifest_paths)
    if unexpected_paths:
        raise VerificationReject(
            "UNEXPECTED_FILE",
            "closed_world_inventory",
            "payload tree contains one or more unlisted entries",
            {"unexpected_paths": unexpected_paths},
        )

    for path in paths:
        observation = observations[path]
        if observation.kind == "symlink":
            raise VerificationReject(
                "SYMLINK_FORBIDDEN", "path_safety", f"symlink payload: {path}"
            )
        if observation.kind != "regular":
            raise VerificationReject(
                "NONREGULAR_FILE", "path_safety", f"non-regular payload: {path}"
            )
        if observation.stat_result.st_nlink != 1:
            raise VerificationReject(
                "HARDLINK_FORBIDDEN", "path_safety", f"multiply linked payload: {path}"
            )
    checks["closed_world_inventory"] = "PASS"

    entries = {entry["path"]: entry for entry in payloads}
    for path in paths:
        observed_size, observed_digest = hash_payload(
            root,
            path,
            observations[path],
            max_bytes=policy["limits"]["single_payload_max_bytes"],
        )
        entry = entries[path]
        if observed_size != entry["bytes"]:
            raise VerificationReject(
                "SIZE_MISMATCH",
                "payload_digests",
                f"payload byte size differs from manifest: {path}",
                {"expected": entry["bytes"], "observed": observed_size},
            )
        if observed_digest != entry["sha256"]:
            raise VerificationReject(
                "DIGEST_MISMATCH",
                "payload_digests",
                f"payload SHA-256 differs from manifest: {path}",
                {"expected": entry["sha256"], "observed": observed_digest},
            )

    try:
        final_observations = observe_payload_tree(
            root,
            max_count=policy["limits"]["payload_file_max_count"],
            max_total_bytes=policy["limits"]["payload_total_max_bytes"],
        )
    except VerificationReject as exc:
        raise VerificationReject(
            "INPUT_CHANGED",
            "payload_digests",
            "payload tree changed after the initial inventory",
            {"final_scan_reason": exc.reason},
        ) from exc
    identity = lambda observation: (
        observation.kind,
        observation.stat_result.st_dev,
        observation.stat_result.st_ino,
        observation.stat_result.st_mode,
        observation.stat_result.st_size,
        observation.stat_result.st_mtime_ns,
        observation.stat_result.st_nlink,
    )
    initial_identity = {path: identity(value) for path, value in observations.items()}
    final_identity = {
        path: identity(value) for path, value in final_observations.items()
    }
    if initial_identity != final_identity:
        changed_paths = sorted(
            path
            for path in set(initial_identity) | set(final_identity)
            if initial_identity.get(path) != final_identity.get(path)
        )
        raise VerificationReject(
            "INPUT_CHANGED",
            "payload_digests",
            "payload tree changed after hashing",
            {"changed_paths": changed_paths[:20], "changed_path_count": len(changed_paths)},
        )
    checks["payload_digests"] = "PASS"
    return manifest


def load_schema(path: Path) -> dict[str, Any]:
    try:
        raw = bounded_regular_file_read(path, 1024 * 1024, check="bounded_input")
        value = parse_json_bytes(
            raw,
            max_depth=64,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
        )
    except VerificationReject as exc:
        raise RuntimeError(
            f"manifest schema could not be loaded safely: {exc.reason}: {exc.message}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError("manifest schema must be a JSON object")
    return value
