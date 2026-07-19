#!/usr/bin/env python3
"""Run and retain the selected 41-case/164-row development-only checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    STUDY_ROOT
    / "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-13.json"
)
TEST_PATH = "tests/test_selected_profile_full_generator_oracle.py"
SCHEMA_PATH = STUDY_ROOT / "schemas/selected-profile-development-check.schema.json"


class DuplicateKeyError(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=strict_object,
        parse_constant=reject_constant,
    )


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def source_paths() -> list[Path]:
    paths = sorted((STUDY_ROOT / "amy_verifier").glob("*.py"))
    paths.extend(
        STUDY_ROOT / relative
        for relative in (
            TEST_PATH,
            "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json",
            "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json",
            "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
            "schemas/manifest-production-v0.2.schema.json",
            "schemas/selected-profile-fixture-result.schema.json",
            "schemas/selected-profile-oracle.schema.json",
            "schemas/selected-profile-development-check.schema.json",
            "scripts/run_selected_profile_development_checks.py",
            "scripts/validate_selected_profile_development_check.py",
            "pyproject.toml",
            "uv.lock",
        )
    )
    return sorted(set(paths), key=lambda path: path.relative_to(STUDY_ROOT).as_posix())


def source_inventory() -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in source_paths():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"source is not a regular non-symlink file: {path}")
        raw = path.read_bytes()
        inventory.append(
            {
                "path": path.relative_to(STUDY_ROOT).as_posix(),
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )
    return inventory


def git_identity() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=STUDY_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=STUDY_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    return {"commit": commit, "dirty_or_untracked": dirty}


def run() -> dict[str, Any]:
    inventory_before = source_inventory()
    inventory_pre_sha256 = sha256_bytes(rfc8785.dumps(inventory_before))
    oracle = strict_json(
        (STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json").read_bytes()
    )
    catalog = strict_json(
        (STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json").read_bytes()
    )
    command = [sys.executable, "-m", "pytest", "-q", TEST_PATH]
    started_at = utc_now()
    completed = subprocess.run(
        command,
        cwd=STUDY_ROOT,
        stdin=subprocess.DEVNULL,
        text=False,
        capture_output=True,
        timeout=120,
        check=False,
    )
    ended_at = utc_now()
    inventory_after = source_inventory()
    inventory_post_sha256 = sha256_bytes(rfc8785.dumps(inventory_after))
    if inventory_after != inventory_before:
        raise RuntimeError(
            "selected-profile source inventory changed during development checks"
        )
    stdout = completed.stdout.decode("utf-8", errors="strict")
    stderr = completed.stderr.decode("utf-8", errors="strict")
    return {
        "schema_version": "amy.selected-profile-development-check.v2-draft",
        "classification": (
            "pre_registration_disposable_fixture_development_check_not_confirmatory"
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "command": command,
        "command_contract": f"python -m pytest -q {TEST_PATH}",
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "git": git_identity(),
        },
        "source_inventory": inventory_before,
        "source_inventory_pre_sha256": inventory_pre_sha256,
        "source_inventory_post_sha256": inventory_post_sha256,
        "source_inventory_unchanged_during_execution": True,
        "execution": {
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stderr": stderr,
            "stderr_sha256": sha256_bytes(completed.stderr),
        },
        "declared_coverage": {
            "catalog_case_count": len(catalog.get("cases") or []),
            "oracle_row_count": len(oracle.get("rows") or []),
            "development_case_profile_evaluations": 164,
            "semantic_authenticated_pointer_isolation_cases": 11,
            "same_environment_tree_replay_cases": 41,
        },
        "boundaries": {
            "confirmatory_case_archives_created": False,
            "confirmatory_outcomes_read": False,
            "production_sigstore_conformance": False,
            "real_amy_p3_execution": False,
            "independent_oracle_review": False,
            "expected_labels_independently_validated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = run()
    schema = strict_json(SCHEMA_PATH.read_bytes())
    Draft202012Validator.check_schema(schema)
    schema_errors = list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(record)
    )
    if schema_errors:
        raise RuntimeError(
            "selected-profile development receipt schema error: "
            + schema_errors[0].message
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(record["execution"]["stdout"])
    sys.stderr.write(record["execution"]["stderr"])
    return int(record["execution"]["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
