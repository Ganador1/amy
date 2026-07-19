from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attestation import enforce_p3_provenance, verify_pilot_attestation
from .json_tools import bounded_regular_file_read, parse_json_bytes
from .manifest import load_schema, parse_p0_manifest, validate_p1_manifest
from .model import PROFILE_CHECKS, VerificationReject, initial_check_states
from .path_policy import observe_payload_tree


@dataclass(frozen=True)
class ImplementationIdentity:
    version: str
    git_commit: str
    source_archive_sha256: str
    dirty: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_policy(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = bounded_regular_file_read(path, 1024 * 1024, check="bounded_input")
    value = parse_json_bytes(
        raw,
        max_depth=64,
        reject_duplicate_keys=True,
        failure_check="bounded_input",
    )
    if not isinstance(value, dict):
        raise RuntimeError("trust policy must be a JSON object")
    return value, raw


def _common_preflight(root: Path, policy: dict[str, Any]) -> None:
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise VerificationReject("INPUT_MISSING", "bounded_input", "release root is missing") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise VerificationReject("INPUT_MISSING", "bounded_input", "release root is not a directory")
    payload_root = root / "payload"
    if payload_root.exists():
        observe_payload_tree(
            root,
            max_count=policy["limits"]["payload_file_max_count"],
            max_total_bytes=policy["limits"]["payload_total_max_bytes"],
        )


def verify_release(
    root: Path,
    *,
    profile_id: str,
    case_id: str,
    case_archive_sha256: str,
    trust_policy_path: Path,
    implementation: ImplementationIdentity,
    manifest_schema_path: Path,
    attestation_backend: str | None = None,
) -> dict[str, Any]:
    if profile_id not in PROFILE_CHECKS:
        raise ValueError(f"unknown profile: {profile_id}")

    started_at = _utc_now()
    checks = initial_check_states(profile_id)
    decision = "ERROR"
    primary_reason = "INTERNAL_ERROR"
    details: dict[str, Any] = {}
    policy: dict[str, Any] = {}
    policy_raw: bytes | None = None
    manifest_path = root / "MANIFEST.jcs.json"
    attestation_path = root / "attestation.sigstore.json"
    manifest_raw: bytes | None = None
    attestation_raw: bytes | None = None

    try:
        try:
            policy, policy_raw = _load_policy(trust_policy_path)
        except VerificationReject as exc:
            raise RuntimeError(
                f"trust policy could not be loaded safely: {exc.reason}: {exc.message}"
            ) from exc
        _common_preflight(root, policy)
        manifest_raw = bounded_regular_file_read(
            manifest_path,
            policy["limits"]["manifest_max_bytes"],
            check="bounded_input",
        )
        checks["bounded_input"] = "PASS"

        if profile_id == "P0":
            parse_p0_manifest(manifest_raw, policy)
            checks["manifest_json_syntax"] = "PASS"
        elif profile_id == "P1":
            schema = load_schema(manifest_schema_path)
            validate_p1_manifest(
                manifest_raw,
                root=root,
                policy=policy,
                schema=schema,
                checks=checks,
            )
        else:
            if attestation_backend != "pilot_fixture":
                raise NotImplementedError(
                    "P2/P3 currently require attestation_backend='pilot_fixture'; "
                    "the production GitHub/Sigstore adapter is a separate release gate"
                )
            try:
                attestation_path.lstat()
            except FileNotFoundError as exc:
                raise VerificationReject(
                    "ATTESTATION_MISSING",
                    "attestation_structure",
                    "required attestation bundle is missing",
                ) from exc
            attestation_raw = bounded_regular_file_read(
                attestation_path,
                policy["limits"]["attestation_max_bytes"],
                check="bounded_input",
            )
            evidence = verify_pilot_attestation(
                attestation_raw, manifest_raw, policy, checks
            )
            if profile_id == "P3":
                enforce_p3_provenance(evidence.statement, policy, checks)
                schema = load_schema(manifest_schema_path)
                validate_p1_manifest(
                    manifest_raw,
                    root=root,
                    policy=policy,
                    schema=schema,
                    checks=checks,
                )

        incomplete = [
            name for name in PROFILE_CHECKS[profile_id] if checks[name] != "PASS"
        ]
        if incomplete:
            raise RuntimeError(f"required checks did not terminate: {sorted(incomplete)}")
        decision = "ACCEPT"
        primary_reason = "OK"
    except VerificationReject as exc:
        checks[exc.check] = "FAIL"
        decision = "REJECT"
        primary_reason = exc.reason
        details = {"message": exc.message, **exc.details}
    except Exception as exc:
        decision = "ERROR"
        primary_reason = "INTERNAL_ERROR"
        details = {"error": f"{type(exc).__name__}: {exc}"}

    return {
        "schema_version": "0.3.0-draft",
        "case_id": case_id,
        "profile_id": profile_id,
        "decision": decision,
        "primary_reason": primary_reason,
        "all_reasons": [primary_reason],
        "input": {
            "case_archive_sha256": case_archive_sha256,
            "manifest_sha256": _sha256(manifest_raw) if manifest_raw is not None else None,
            "attestation_sha256": _sha256(attestation_raw) if attestation_raw is not None else None,
            "trust_policy_sha256": (
                _sha256(policy_raw) if policy_raw is not None else None
            ),
        },
        "implementation": {
            "version": implementation.version,
            "git_commit": implementation.git_commit,
            "source_archive_sha256": implementation.source_archive_sha256,
            "dirty": implementation.dirty,
        },
        "checks": checks,
        "started_at": started_at,
        "ended_at": _utc_now(),
        "details": details,
    }
