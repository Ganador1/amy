#!/usr/bin/env python3
"""Run base-aware mutation engineering checks and emit a fail-closed receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))
DEFAULT_OUTPUT = (
    STUDY_ROOT / "development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-13.json"
)
TEST_PATH = "tests/test_selected_profile_base_aware_mutations.py"
SCHEMA_PATH = STUDY_ROOT / "schemas/base-aware-mutation-development-check.schema.json"
BASES_PATH = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"

from amy_verifier.selected_profile_fixture import selected_fixture_policy
from amy_verifier.selected_profile_mutations import (
    MutationPlanUnavailable,
    resolve_mutation_plan,
)


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_strict_object,
        parse_constant=_reject_constant,
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_paths() -> list[Path]:
    paths = list((STUDY_ROOT / "amy_verifier").glob("*.py"))
    paths.extend(
        STUDY_ROOT / relative
        for relative in (
            TEST_PATH,
            "corpus/BASE_REGISTRY_DRAFT.json",
            "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json",
            "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
            "schemas/base-aware-mutation-development-check.schema.json",
            "scripts/run_base_aware_mutation_development_check.py",
            "scripts/validate_base_aware_mutation_development_check.py",
            "pyproject.toml",
            "uv.lock",
        )
    )
    return sorted(
        set(paths), key=lambda path: path.relative_to(STUDY_ROOT).as_posix().encode("utf-8")
    )


def _inventory() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in _source_paths():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"source is not a regular non-symlink file: {path}")
        raw = path.read_bytes()
        result.append(
            {
                "path": path.relative_to(STUDY_ROOT).as_posix(),
                "bytes": len(raw),
                "sha256": _sha(raw),
            }
        )
    return result


def _git_identity() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=STUDY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=STUDY_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    return {"commit": commit, "dirty_or_untracked": dirty}


def _resolution() -> tuple[dict[str, int], list[dict[str, str]]]:
    bases = _strict_json(BASES_PATH.read_bytes())["bases"]
    cases = _strict_json(CATALOG_PATH.read_bytes())["cases"]
    policy = selected_fixture_policy()
    resolved = 0
    unavailable: list[dict[str, str]] = []
    for base in bases:
        for case in cases:
            try:
                resolve_mutation_plan(case["id"], base=base, policy=policy)
            except MutationPlanUnavailable as exc:
                unavailable.append(
                    {
                        "base_id": base["id"],
                        "operator_id": case["id"],
                        "reason_code": exc.reason_code,
                    }
                )
            else:
                resolved += 1
    return (
        {
            "base_count": len(bases),
            "operator_count": len(cases),
            "base_operator_plan_count": len(bases) * len(cases),
            "resolved_plan_count": resolved,
            "unavailable_plan_count": len(unavailable),
        },
        unavailable,
    )


def run() -> dict[str, Any]:
    inventory_before = _inventory()
    inventory_pre_sha = _sha(rfc8785.dumps(inventory_before))
    resolution, unavailable = _resolution()
    command = [sys.executable, "-m", "pytest", "-q", TEST_PATH]
    started_at = _utc_now()
    completed = subprocess.run(
        command,
        cwd=STUDY_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=False,
        timeout=120,
        check=False,
    )
    ended_at = _utc_now()
    inventory_after = _inventory()
    inventory_post_sha = _sha(rfc8785.dumps(inventory_after))
    if inventory_after != inventory_before:
        raise RuntimeError("base-aware source inventory changed during test execution")
    stdout = completed.stdout.decode("utf-8", errors="strict")
    stderr = completed.stderr.decode("utf-8", errors="strict")
    match = re.search(r"(?:^|\s)(\d+) passed(?:[,\s]|$)", stdout)
    passed = int(match.group(1)) if match else None
    return {
        "schema_version": "amy.base-aware-mutation-development-check.v1-draft",
        "classification": (
            "pre_registration_base_aware_disposable_fixture_test_not_confirmatory"
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "command": command,
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "git": _git_identity(),
        },
        "source_inventory": inventory_before,
        "source_inventory_pre_sha256": inventory_pre_sha,
        "source_inventory_post_sha256": inventory_post_sha,
        "source_inventory_unchanged_during_execution": True,
        "execution": {
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stdout_sha256": _sha(completed.stdout),
            "stderr": stderr,
            "stderr_sha256": _sha(completed.stderr),
            "passed_test_count": passed,
        },
        "declared_coverage": {
            **resolution,
            "disposable_target_dependent_execution_count": 65,
            "policy_fixture_collision_tested": True,
            "forged_plan_rejection_tested": True,
        },
        "unavailable_plans": unavailable,
        "boundaries": {
            "confirmatory_case_archives_created": False,
            "confirmatory_outcomes_read": False,
            "verifier_invoked_by_base_aware_test": False,
            "oracle_join_performed": False,
            "registered_result_ledger_written": False,
            "production_sigstore_conformance_established": False,
            "independent_review_performed": False,
        },
        "decision": "NO-GO",
        "manuscript_claims_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = run()
    schema = _strict_json(SCHEMA_PATH.read_bytes())
    Draft202012Validator.check_schema(schema)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record)
    )
    if errors:
        raise RuntimeError("base-aware receipt schema error: " + errors[0].message)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(record["execution"]["stdout"])
    sys.stderr.write(record["execution"]["stderr"])
    return int(record["execution"]["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
