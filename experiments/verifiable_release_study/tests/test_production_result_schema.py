from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "amy.production-verification-result.v1-draft"
P1_CHECKS = {
    "manifest_json_syntax": "PASS",
    "manifest_canonicality": "PASS",
    "manifest_schema": "PASS",
    "path_safety": "PASS",
    "closed_world_inventory": "PASS",
    "payload_digests": "PASS",
}


def _load(relative: str) -> dict:
    return json.loads((STUDY_ROOT / relative).read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        _load("schemas/github-production-verification-result.schema.json"),
        format_checker=FormatChecker(),
    )


def test_production_result_reason_enum_matches_versioned_registries() -> None:
    schema = _load("schemas/github-production-verification-result.schema.json")
    base = _load("protocol/REASON_CODES.json")
    extension = _load("protocol/PRODUCTION_REASON_CODES_DRAFT.json")
    expected = {
        entry["code"]
        for entry in base["codes"] + extension["additional_codes"]
        if entry["decision"] == "REJECT"
    }
    assert set(schema["$defs"]["reasonCode"]["enum"]) == expected


def test_production_acceptance_schema_separates_p2_from_integrated_p3() -> None:
    p2 = _load("production_pilot_runs/github_cli_2.96.0_upstream_smoke/result.json")
    p2["schema_version"] = SCHEMA_VERSION
    validator = _validator()
    assert list(validator.iter_errors(p2)) == []

    p3 = copy.deepcopy(p2)
    p3["profile_id"] = "P3"
    p3["manifest_schema_sha256"] = "a" * 64
    p3["p1_checks"] = dict(P1_CHECKS)
    assert list(validator.iter_errors(p3)) == []

    incomplete_p3 = copy.deepcopy(p3)
    incomplete_p3.pop("p1_checks")
    assert list(validator.iter_errors(incomplete_p3))

    mislabeled_p2 = copy.deepcopy(p2)
    mislabeled_p2["p1_checks"] = dict(P1_CHECKS)
    assert list(validator.iter_errors(mislabeled_p2))


def test_production_reject_and_error_outputs_are_schema_closed() -> None:
    validator = _validator()
    rejection = {
        "schema_version": SCHEMA_VERSION,
        "decision": "REJECT",
        "code": "DIGEST_MISMATCH",
        "message": "payload differs",
        "details": {"path": "payload/data.bin"},
        "policy_sha256": "b" * 64,
    }
    error = {
        "schema_version": SCHEMA_VERSION,
        "decision": "ERROR",
        "error": "GitHubGateToolError: verifier unavailable",
    }
    assert list(validator.iter_errors(rejection)) == []
    assert list(validator.iter_errors(error)) == []

    unknown = dict(rejection, code="UNREGISTERED")
    assert list(validator.iter_errors(unknown))
    extra = dict(error, unexpected=True)
    assert list(validator.iter_errors(extra))


def test_production_cli_runs_directly_and_emits_a_schema_valid_rejection(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(STUDY_ROOT / "scripts/verify_github_attestation.py"),
            str(tmp_path / "missing-release"),
            str(STUDY_ROOT / "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json"),
            str(tmp_path / "missing-root"),
            "--profile",
            "P2",
            "--result-schema",
            str(STUDY_ROOT / "schemas/github-production-verification-result.schema.json"),
        ],
        cwd=STUDY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 1, completed.stderr
    output = json.loads(completed.stdout)
    assert output["decision"] == "REJECT"
    assert output["code"] == "INPUT_MISSING"
    assert list(_validator().iter_errors(output)) == []


def test_production_cli_emits_no_unvalidated_json_when_result_schema_is_missing(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(STUDY_ROOT / "scripts/verify_github_attestation.py"),
            str(tmp_path / "missing-release"),
            str(STUDY_ROOT / "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json"),
            str(tmp_path / "missing-root"),
            "--profile",
            "P2",
            "--result-schema",
            str(tmp_path / "missing-result-schema.json"),
        ],
        cwd=STUDY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "could not be loaded" in completed.stderr
