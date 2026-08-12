#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

STUDY_ROOT = Path(__file__).resolve().parents[1]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.github_attestation import (
    GitHubGateConfigurationError,
    GitHubGateRejected,
    GitHubGateToolError,
    evidence_to_json,
    load_github_policy,
    verify_github_manifest_attestation,
    verify_github_p3_release,
)
from amy_verifier.json_tools import bounded_regular_file_read, parse_json_bytes
from amy_verifier.model import VerificationReject


RESULT_SCHEMA_VERSION = "amy.production-verification-result.v1-draft"


def _load_result_schema(path: Path) -> tuple[dict, bytes]:
    try:
        raw = bounded_regular_file_read(path, 1024 * 1024, check="bounded_input")
        value = parse_json_bytes(
            raw,
            max_depth=64,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(
            f"production result schema could not be loaded safely: {exc.message}"
        ) from exc
    if not isinstance(value, dict):
        raise GitHubGateConfigurationError("production result schema is not a JSON object")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise GitHubGateConfigurationError(
            f"production result schema is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    return value, raw


def _result_validation_errors(output: dict, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        error.message
        for error in sorted(
            validator.iter_errors(output),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify one manifest against an archived GitHub/Sigstore bundle and trust root."
    )
    parser.add_argument("release_root", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("trusted_root", type=Path)
    parser.add_argument("--profile", choices=("P2", "P3"), default="P3")
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        help="Frozen production manifest schema; mandatory for P3",
    )
    parser.add_argument(
        "--result-schema",
        type=Path,
        required=True,
        help="Frozen schema used to validate the emitted production decision",
    )
    parser.add_argument("--gh", default="gh", help="Path to the exact frozen GitHub CLI binary")
    args = parser.parse_args()

    schema: dict | None = None
    policy_sha256: str | None = None
    exit_code = 2
    try:
        schema, result_schema_raw = _load_result_schema(args.result_schema)
        policy, policy_raw = load_github_policy(args.policy)
        policy_sha256 = hashlib.sha256(policy_raw).hexdigest()
        result_policy = policy.get("result")
        if not isinstance(result_policy, dict):
            raise GitHubGateConfigurationError("production result policy is absent")
        if result_policy.get("schema_version") != RESULT_SCHEMA_VERSION:
            raise GitHubGateConfigurationError("production result-schema version is not frozen")
        if hashlib.sha256(result_schema_raw).hexdigest() != result_policy.get("schema_sha256"):
            raise GitHubGateConfigurationError(
                "production result schema differs from the frozen policy"
            )
        if args.profile == "P3":
            if args.manifest_schema is None:
                raise GitHubGateConfigurationError(
                    "--manifest-schema is mandatory for production P3"
                )
            evidence = verify_github_p3_release(
                args.release_root,
                args.trusted_root,
                args.manifest_schema,
                policy=policy,
                gh_binary=args.gh,
            )
        else:
            evidence = verify_github_manifest_attestation(
                args.release_root / "MANIFEST.jcs.json",
                args.release_root / "attestation.sigstore.json",
                args.trusted_root,
                profile_id="P2",
                policy=policy,
                gh_binary=args.gh,
            )
        output = evidence_to_json(evidence)
        exit_code = 0
    except GitHubGateRejected as exc:
        output = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "decision": "REJECT",
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
        exit_code = 1
    except (GitHubGateConfigurationError, GitHubGateToolError) as exc:
        output = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "decision": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }

    if policy_sha256 is not None:
        output["policy_sha256"] = policy_sha256
    if schema is None:
        print(
            "unstructured verifier error because the production result schema "
            f"could not be loaded: {output['error']}",
            file=sys.stderr,
        )
        return 2
    errors = _result_validation_errors(output, schema)
    if errors:
        output = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "decision": "ERROR",
            "error": (
                "GitHubGateToolError: production output failed its frozen schema: "
                + errors[0]
            ),
        }
        if policy_sha256 is not None:
            output["policy_sha256"] = policy_sha256
        exit_code = 2
        fallback_errors = _result_validation_errors(output, schema)
        if fallback_errors:
            raise RuntimeError(
                "production output and schema-error fallback are both invalid: "
                + fallback_errors[0]
            )
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
