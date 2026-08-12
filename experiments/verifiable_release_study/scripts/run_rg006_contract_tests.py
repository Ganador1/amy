#!/usr/bin/env python3
"""Run only synthetic RG-006 engineering tests and emit a NO-GO receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
DEFAULT_OUTPUT = STUDY_ROOT / "development_checks/RG006_RUNNER_CONTRACT_TEST_V3_2026-07-15T034921Z.json"
TEST_PATH = "tests/test_confirmatory_runner_contract.py"
SCHEMA_PATH = STUDY_ROOT / "schemas/rg006-contract-test-record-v3.schema.json"
SOURCE_PATHS = (
    "amy_verifier/confirmatory_runner.py",
    "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
    "protocol/RUN_EXECUTION_POLICY_DRAFT.json",
    "schemas/process-isolation-record.schema.json",
    "schemas/environment-attempt-record.schema.json",
    "schemas/infrastructure-classification.schema.json",
    "schemas/official-attempt-selection.schema.json",
    "schemas/rg006-contract-test-record-v3.schema.json",
    "schemas/run-execution-policy.schema.json",
    "schemas/run-execution-policy-validation.schema.json",
    "schemas/scientific-intent-event.schema.json",
    "scripts/run_rg006_contract_tests.py",
    "scripts/validate_run_execution_policy.py",
    "tests/test_confirmatory_runner_contract.py",
    "tests/test_run_execution_policy.py",
    "pyproject.toml",
    "uv.lock",
)
OPEN_CONTROLS = [
    "DURABLE_SCIENTIFIC_INTENT_LOG",
    "CAPABILITY_SEPARATED_OUTCOME_VAULT",
    "FULL_PROCESS_TREE_CONTAINMENT",
    "OS_ENFORCED_OFFLINE_BOUNDARY",
    "CRASH_AND_STORAGE_FAULT_INJECTION",
    "BASE_AWARE_CASE_GENERATOR",
    "ALL_PROFILE_CHILD_ADAPTERS",
    "CAMPAIGN_SEAL_TO_LEDGER_LINK",
    "EXTERNAL_SELECTION_AUTHENTICATION",
    "QUALIFIED_INDEPENDENT_HUMAN_REVIEW",
    "R0_FREEZE_AND_REGISTRATION",
]
CONTROL_STATUSES = {
    control: {
        "status": "OPEN",
        "evidence_paths": [],
        "limitations": ["No complete closing evidence is retained for this control."],
    }
    for control in OPEN_CONTROLS
}
CONTROL_STATUSES["CRASH_AND_STORAGE_FAULT_INJECTION"] = {
    "status": "PARTIAL",
    "evidence_paths": [
        "amy_verifier/confirmatory_runner.py",
        "tests/test_confirmatory_runner_contract.py",
    ],
    "limitations": [
        "Coverage is limited to atomic JCS publication under synthetic errno injection and process crash; full runner persistence boundaries, recovery, power-loss durability, and cross-filesystem equivalence remain unestablished."
    ],
}
CONTROL_STATUSES["DURABLE_SCIENTIFIC_INTENT_LOG"] = {
    "status": "PARTIAL",
    "evidence_paths": [
        "amy_verifier/confirmatory_runner.py",
        "schemas/scientific-intent-event.schema.json",
        "schemas/process-isolation-record.schema.json",
        "tests/test_confirmatory_runner_contract.py",
    ],
    "limitations": [
        "Coverage is limited to the nonconfirmatory contract-test top-level spawn. Authenticated checkpoints, rollback detection, same-UID exclusion, recovery records, classifier-derived counters, registered generator/profile adapters, and power-loss durability remain unestablished."
    ],
}
POLICY_PATH = STUDY_ROOT / "protocol/RUN_EXECUTION_POLICY_DRAFT.json"


class DuplicateKeyError(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_inventory() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in sorted(SOURCE_PATHS, key=lambda value: value.encode("utf-8")):
        path = STUDY_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"RG-006 source is not a regular non-symlink file: {relative}")
        raw = path.read_bytes()
        records.append({"path": relative, "bytes": len(raw), "sha256": sha256_bytes(raw)})
    return records


def verify_typed_policy_bindings() -> int:
    policy = json.loads(POLICY_PATH.read_bytes(), object_pairs_hook=strict_object)
    contract = policy.get("runner_contract") or {}
    bindings = contract.get("source_bindings") or []
    expected_paths = set(SOURCE_PATHS) - {"protocol/RUN_EXECUTION_POLICY_DRAFT.json"}
    if contract.get("source_binding_count") != len(expected_paths):
        raise RuntimeError("runner-contract source-binding count differs")
    if len(bindings) != len(expected_paths):
        raise RuntimeError("runner-contract source-binding inventory differs")
    roles: set[str] = set()
    observed_paths: set[str] = set()
    for binding in bindings:
        role = binding.get("role")
        relative = binding.get("path")
        if not isinstance(role, str) or role in roles:
            raise RuntimeError("runner-contract binding roles must be unique strings")
        if not isinstance(relative, str) or relative in observed_paths:
            raise RuntimeError("runner-contract binding paths must be unique strings")
        roles.add(role)
        observed_paths.add(relative)
        path = STUDY_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"bound source is not a regular non-symlink file: {relative}")
        if binding.get("sha256") != sha256_bytes(path.read_bytes()):
            raise RuntimeError(f"bound source hash differs: {relative}")
    if observed_paths != expected_paths:
        raise RuntimeError("runner-contract paths differ from the receipt source inventory")
    return len(bindings)


def run() -> dict[str, Any]:
    inventory_before = source_inventory()
    inventory_before_sha256 = sha256_bytes(rfc8785.dumps(inventory_before))
    bound_source_count = verify_typed_policy_bindings()
    command = [sys.executable, "-m", "pytest", "-q", TEST_PATH]
    started_at = utc_now()
    completed = subprocess.run(
        command,
        cwd=STUDY_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=False,
        timeout=120,
        check=False,
    )
    ended_at = utc_now()
    stdout = completed.stdout.decode("utf-8", errors="strict")
    stderr = completed.stderr.decode("utf-8", errors="strict")
    match = re.search(r"(?:^|\s)(\d+) passed(?:[,\s]|$)", stdout)
    passed = int(match.group(1)) if match else None
    inventory_after = source_inventory()
    inventory_after_sha256 = sha256_bytes(rfc8785.dumps(inventory_after))
    if inventory_after != inventory_before:
        raise RuntimeError(
            "RG-006 source inventory changed during contract-test execution"
        )
    return {
        "schema_version": "amy.rg006-contract-test-record.v3-draft",
        "classification": "pre_registration_synthetic_runner_contract_test_not_confirmatory",
        "started_at": started_at,
        "ended_at": ended_at,
        "command": command,
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "source_inventory": inventory_before,
        "source_inventory_pre_sha256": inventory_before_sha256,
        "source_inventory_post_sha256": inventory_after_sha256,
        "source_inventory_unchanged_during_execution": True,
        "execution": {
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stderr": stderr,
            "stderr_sha256": sha256_bytes(completed.stderr),
            "passed_test_count": passed,
        },
        "declared_coverage": {
            "attempt_truth_table_cell_count": 12,
            "required_environment_count": 2,
            "subprocess_contract_tested": True,
            "raw_byte_stream_limits_tested": True,
            "descriptor_and_environment_canaries_tested": True,
            "no_overwrite_tested": True,
            "campaign_selection_tested": True,
            "later_attempt_campaign_seal_tested": True,
            "attempt_process_consistency_tested": True,
            "inherited_capture_pipe_deadline_tested": True,
            "exact_record_hash_recomputation_tested": True,
            "source_inventory_toctou_rejection_tested": True,
            "typed_run_policy_bindings_verified": True,
            "runner_contract_bound_source_count": bound_source_count,
            "storage_errno_fault_cell_count": 12,
            "storage_eintr_transient_cell_count": 4,
            "storage_eintr_persistent_cell_count": 3,
            "storage_process_crash_cell_count": 3,
            "same_uid_entry_substitution_tested": True,
            "atomic_noreplace_rename_tested": True,
            "fault_injection_scope": (
                "atomic_jcs_publication_only_not_all_runner_persistence_boundaries"
            ),
            "intent_event_schema_and_process_binding_tested": True,
            "intent_hash_chain_tested": True,
            "intent_ambiguous_rejection_cell_count": 3,
            "intent_advisory_lock_tested": True,
            "intent_popen_failure_retention_tested": True,
            "intent_publication_failure_prevents_spawn_tested": True,
            "intent_pre_spawn_process_crash_cell_count": 1,
            "intent_log_scope": (
                "contract_test_top_level_spawn_only_no_authenticated_checkpoint_"
                "recovery_or_classifier_derivation"
            ),
        },
        "control_statuses": CONTROL_STATUSES,
        "boundaries": {
            "confirmatory_execution_performed": False,
            "confirmatory_outputs_read": False,
            "benchmark_cases_generated": False,
            "oracle_join_performed": False,
            "production_sigstore_conformance_established": False,
            "network_isolation_established": False,
            "full_process_tree_containment_established": False,
            "external_selection_authentication_established": False,
            "independent_review_performed": False,
            "power_loss_durability_established": False,
            "cross_filesystem_equivalence_established": False,
            "storage_recovery_implemented": False,
            "authenticated_intent_checkpoint_established": False,
            "same_uid_intent_tamper_excluded": False,
            "intent_log_rollback_detection_established": False,
            "intent_classifier_derivation_integrated": False,
        },
        "decision": "NO-GO",
        "open_controls": OPEN_CONTROLS,
        "rg006_complete": False,
        "manuscript_claims_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = run()
    schema = json.loads(SCHEMA_PATH.read_bytes(), object_pairs_hook=strict_object)
    Draft202012Validator.check_schema(schema)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record)
    )
    if errors:
        raise RuntimeError("RG-006 test receipt schema error: " + errors[0].message)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with args.output.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(args.output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    sys.stdout.write(record["execution"]["stdout"])
    sys.stderr.write(record["execution"]["stderr"])
    return int(record["execution"]["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
