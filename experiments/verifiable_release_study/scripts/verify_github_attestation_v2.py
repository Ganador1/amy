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
from amy_verifier.json_tools import bounded_regular_file_read, parse_json_bytes
from amy_verifier.model import VerificationReject


def _load_result_schema(path: Path) -> tuple[dict, bytes]:
    try:
        raw = bounded_regular_file_read(path, 1024 * 1024, check="bounded_input")
        value = parse_json_bytes(
            raw,
            max_depth=128,
            reject_duplicate_keys=True,
            failure_check="bounded_input",
            invalid_reason="JSON_INVALID",
            duplicate_reason="DUPLICATE_JSON_KEY",
        )
    except VerificationReject as exc:
        raise GitHubGateConfigurationError(
            f"v2 production result schema could not be loaded safely: {exc.message}"
        ) from exc
    if not isinstance(value, dict):
        raise GitHubGateConfigurationError(
            "v2 production result schema is not a JSON object"
        )
    try:
        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise GitHubGateConfigurationError(
            f"v2 production result schema is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    return value, raw


def _result_validation_errors(output: dict, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        error.message
        for error in sorted(
            validator.iter_errors(output),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                error.message,
            ),
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one release with the externally pinned, schema-closed v2 "
            "GitHub/Sigstore policy."
        )
    )
    parser.add_argument("release_root", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("trusted_root", type=Path)
    parser.add_argument("--profile", choices=("P2", "P3"), default="P3")
    parser.add_argument(
        "--expected-policy-sha256",
        required=True,
        help="Externally frozen policy SHA-256, normally copied from the R0 identity record",
    )
    parser.add_argument(
        "--policy-schema",
        type=Path,
        required=True,
        help="Exact policy schema whose digest is bound inside the externally pinned policy",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        help="Frozen production manifest schema; mandatory for P3",
    )
    parser.add_argument(
        "--result-schema",
        type=Path,
        required=True,
        help="Exact terminal-result schema whose digest is bound inside the policy",
    )
    parser.add_argument("--gh", default="gh", help="Path to the exact frozen GitHub CLI binary")
    args = parser.parse_args()

    schema: dict | None = None
    identity: dict[str, str] | None = None
    output_contract_ready = False
    exit_code = 2
    output: dict[str, object]
    try:
        schema, result_schema_raw = _load_result_schema(args.result_schema)
        document = load_github_policy_v2(
            args.policy,
            args.policy_schema,
            args.result_schema,
            expected_policy_sha256=args.expected_policy_sha256,
        )
        identity = policy_contract_identity_v2(document)
        if hashlib.sha256(result_schema_raw).hexdigest() != identity["result_schema_sha256"]:
            raise GitHubGateConfigurationError(
                "v2 production result schema differs from the externally pinned policy"
            )
        declared_version = (
            ((schema.get("$defs") or {}).get("schemaVersion") or {}).get("const")
        )
        if declared_version != RESULT_SCHEMA_VERSION:
            raise GitHubGateConfigurationError(
                "v2 production result schema does not declare the expected version"
            )
        output_contract_ready = True
        require_frozen_policy_v2(document)
        if args.profile == "P3":
            if args.manifest_schema is None:
                raise GitHubGateConfigurationError(
                    "--manifest-schema is mandatory for production P3"
                )
            evidence = verify_github_p3_release_v2(
                args.release_root,
                args.trusted_root,
                args.manifest_schema,
                policy=document,
                gh_binary=args.gh,
            )
        else:
            evidence = verify_github_manifest_attestation_v2(
                args.release_root / "MANIFEST.jcs.json",
                args.release_root / "attestation.sigstore.json",
                args.trusted_root,
                profile_id="P2",
                policy=document,
                gh_binary=args.gh,
            )
        output = evidence_to_json_v2(evidence)
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

    if not output_contract_ready or schema is None or identity is None:
        message = output.get("error", "v2 output contract could not be established")
        print(
            "unstructured verifier error because the externally pinned v2 output "
            f"contract could not be established: {message}",
            file=sys.stderr,
        )
        return 2

    output.update(identity)
    errors = _result_validation_errors(output, schema)
    if errors:
        output = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "decision": "ERROR",
            "error": (
                "GitHubGateToolError: v2 production output failed its frozen schema: "
                + errors[0]
            ),
            **identity,
        }
        exit_code = 2
        fallback_errors = _result_validation_errors(output, schema)
        if fallback_errors:
            raise RuntimeError(
                "v2 production output and schema-error fallback are both invalid: "
                + fallback_errors[0]
            )
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
