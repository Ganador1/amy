#!/usr/bin/env python3
"""Validate the static RG-004 reviewer-identity policy without authenticating."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = STUDY_ROOT / "protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json"
DEFAULT_SCHEMA = STUDY_ROOT / "schemas/r0-reviewer-identity-policy.schema.json"
VALIDATION_SCHEMA = (
    STUDY_ROOT / "schemas/r0-reviewer-identity-policy-validation.schema.json"
)
SOURCE_LEDGER = STUDY_ROOT / "evidence/SOURCE_LEDGER.md"
EXPECTED_SOURCE_IDS = {"S14", "S15", "S25", "S45", "S46"}
EXPECTED_REQUIRED_FLAGS = [
    "--bundle",
    "--trusted-root",
    "--certificate-identity",
    "--certificate-oidc-issuer",
]
EXPECTED_FORBIDDEN_FLAGS = [
    "--certificate-identity-regexp",
    "--certificate-oidc-issuer-regexp",
    "--insecure-ignore-sct",
    "--insecure-ignore-tlog",
]


class _DuplicateKeyError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object name: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _load_strict(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonstandard_constant,
    )


def version_not_known_vulnerable(value: Any) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
        return False
    major, minor, patch = (int(part) for part in value.split("."))
    if major == 2:
        return (major, minor, patch) >= (2, 6, 2)
    if major == 3:
        return (major, minor, patch) >= (3, 0, 4)
    return False


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(STUDY_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def validate(
    policy_path: Path = DEFAULT_POLICY,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        policy = _load_strict(policy_path)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        errors.append(f"policy is not strict unambiguous JSON: {exc}")
    try:
        schema = _load_strict(schema_path)
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        schema = {}
        errors.append(f"policy schema is invalid: {type(exc).__name__}: {exc}")

    if schema:
        schema_errors = sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(policy),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        errors.extend(f"schema: {error.message}" for error in schema_errors)

    sources = policy.get("source_basis") or [] if isinstance(policy, dict) else []
    source_ids = {
        source.get("source_id")
        for source in sources
        if isinstance(source, dict)
    }
    source_basis_complete = source_ids == EXPECTED_SOURCE_IDS and all(
        f"| {source_id} |" in SOURCE_LEDGER.read_text(encoding="utf-8")
        for source_id in EXPECTED_SOURCE_IDS
    )
    if not source_basis_complete:
        errors.append("reviewer-identity policy source basis is incomplete")

    floor = policy.get("security_floor") or {} if isinstance(policy, dict) else {}
    security_floor_valid = (
        floor.get("advisory_uri")
        == "https://github.com/sigstore/cosign/security/advisories/GHSA-whqx-f9j3-ch6m"
        and floor.get("rejected_version_ranges") == ["<=2.6.1", "<=3.0.3"]
        and floor.get("minimum_patched_version_by_major")
        == {"2": "2.6.2", "3": "3.0.4"}
    )
    if not security_floor_valid:
        errors.append("reviewer-identity policy security floor differs")

    tool = policy.get("tool") or {} if isinstance(policy, dict) else {}
    if tool.get("required_flags") != EXPECTED_REQUIRED_FLAGS:
        errors.append("reviewer authentication required flags differ")
    if tool.get("forbidden_flags") != EXPECTED_FORBIDDEN_FLAGS:
        errors.append("reviewer authentication forbidden flags differ")
    if tool.get("network_allowed_during_verification") is not False:
        errors.append("reviewer authentication must be offline after input acquisition")

    selected_version_safe = version_not_known_vulnerable(
        tool.get("selected_version")
    )
    status = policy.get("status") if isinstance(policy, dict) else None
    boundary = policy.get("decision_boundary") or {} if isinstance(policy, dict) else {}
    if status == "frozen_authorized_for_authentication_only":
        if not selected_version_safe:
            errors.append("frozen policy selects an unsupported or known-vulnerable Cosign version")
        release_uri = tool.get("release_uri")
        if not isinstance(release_uri, str) or not release_uri.rstrip("/").endswith(
            f"/v{tool.get('selected_version')}"
        ):
            errors.append("frozen Cosign release URI does not match selected version")
        if floor.get("selected_version_reviewed_against_advisory") is not True:
            errors.append("frozen Cosign version was not reviewed against the advisory")
    elif status != "template_not_authorized_not_frozen":
        errors.append("reviewer-identity policy status is unsupported")

    freeze_permitted = (
        not errors
        and status == "frozen_authorized_for_authentication_only"
        and selected_version_safe
        and boundary.get("policy_freeze_permitted") is True
    )
    authentication_permitted = (
        freeze_permitted
        and boundary.get("authentication_execution_permitted") is True
    )
    return {
        "schema_version": "amy.r0-reviewer-identity-policy-validation.v1-draft",
        "valid": not errors,
        "errors": errors,
        "policy_path": _display_path(policy_path),
        "policy_sha256": _sha256(policy_path),
        "policy_schema_path": _display_path(schema_path),
        "policy_schema_sha256": _sha256(schema_path),
        "validation_schema_path": _display_path(VALIDATION_SCHEMA),
        "validation_schema_sha256": _sha256(VALIDATION_SCHEMA),
        "source_ledger_sha256": _sha256(SOURCE_LEDGER),
        "validator_sha256": _sha256(Path(__file__).resolve()),
        "policy_status": status,
        "source_basis_complete": source_basis_complete,
        "security_floor_valid": security_floor_valid,
        "selected_version_not_known_vulnerable": selected_version_safe,
        "freeze_permitted": freeze_permitted,
        "authentication_execution_permitted": authentication_permitted,
        "decision": (
            "GO-FOR-AUTHENTICATION-ONLY"
            if authentication_permitted
            else "NO-GO"
        ),
        "rg004_complete": False,
        "read_scope": {
            "network_used": False,
            "signature_bundle_read": False,
            "review_record_read": False,
            "confirmatory_outputs_read": False,
            "authentication_executed": False,
        },
        "limitations": [
            "This validator checks a static policy and does not execute Cosign.",
            "No review record, signature bundle, trusted-root bytes, or reviewer credential is authenticated here.",
            "Even successful future authentication cannot establish reviewer competence, care, independence, disclosure truth, or scientific correctness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.policy.resolve(), args.schema.resolve())
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
