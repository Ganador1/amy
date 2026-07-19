from __future__ import annotations

import ast
import copy
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

import amy_verifier.confirmatory_runner as runner_module

from amy_verifier.confirmatory_runner import (
    CONTRACT_TEST_CLASSIFICATION,
    INVALID_CLASSIFICATION,
    NOT_RETRY_ELIGIBLE,
    RETRY_ELIGIBLE,
    RunnerContractError,
    build_classifier_view,
    build_campaign_selection_seal_before_decode,
    classify_infrastructure_before_decode,
    continuous_clock,
    inspect_scientific_intent_log,
    run_contract_test_process,
    select_official_attempt_before_decode,
    sha256_bytes,
    validate_process_isolation_record,
    write_new_jcs,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
PROCESS_SCHEMA = STUDY_ROOT / "schemas/process-isolation-record.schema.json"
INTENT_SCHEMA = STUDY_ROOT / "schemas/scientific-intent-event.schema.json"
ATTEMPT_SCHEMA = STUDY_ROOT / "schemas/environment-attempt-record.schema.json"
CLASSIFICATION_SCHEMA = STUDY_ROOT / "schemas/infrastructure-classification.schema.json"
SELECTION_SCHEMA = STUDY_ROOT / "schemas/official-attempt-selection.schema.json"
RUN_POLICY = STUDY_ROOT / "protocol/RUN_EXECUTION_POLICY_DRAFT.json"
RUNNER_SOURCE = STUDY_ROOT / "amy_verifier/confirmatory_runner.py"
RG006_TEST_RUNNER = STUDY_ROOT / "scripts/run_rg006_contract_tests.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _command_commitments(
    argv: list[str], cwd: Path, environment: dict[str, str]
) -> dict[str, str]:
    observed = cwd.stat()
    cwd_identity = {
        "device_decimal": str(int(observed.st_dev)),
        "inode_decimal": str(int(observed.st_ino)),
        "mode_octal": format(observed.st_mode & 0o7777, "04o"),
        "mtime_ns_decimal": str(int(observed.st_mtime_ns)),
    }
    return {
        "expected_argv_jcs_sha256": sha256_bytes(rfc8785.dumps(argv)),
        "expected_environment_jcs_sha256": sha256_bytes(
            rfc8785.dumps(environment)
        ),
        "expected_cwd_root_identity_jcs_sha256": sha256_bytes(
            rfc8785.dumps(cwd_identity)
        ),
    }


def _run_simple_process(cwd: Path, output: Path, name: str) -> dict[str, Any]:
    executable = str(Path(sys.executable).resolve())
    argv = [executable, "-c", "pass"]
    environment = {"PYTHONUTF8": "1"}
    return run_contract_test_process(
        classification=CONTRACT_TEST_CLASSIFICATION,
        argv=argv,
        expected_executable_sha256=_sha(Path(executable)),
        **_command_commitments(argv, cwd, environment),
        cwd=cwd,
        environment=environment,
        output_parent=output,
        output_name=name,
        timeout_seconds=2,
        termination_grace_seconds=0.1,
        reap_timeout_seconds=0.1,
        max_output_bytes_per_stream=1024,
        max_total_output_bytes=2048,
    )
def _schema_errors(path: Path, value: dict[str, Any]) -> list[Any]:
    return list(
        Draft202012Validator(
            _load(path), format_checker=FormatChecker()
        ).iter_errors(value)
    )


def _signals(state: str) -> dict[str, Any]:
    if state == "E":
        return {
            "provider_job_id": "provider-job-fixture",
            "provider_job_state": "not_scheduled",
            "external_cancellation_actor": "none",
            "host_heartbeat_state": "not_started",
            "image_pull_status": "not_started",
            "input_acquisition_status": "not_started",
            "input_lock_completed": False,
            "preflight_storage_probe": "not_run",
            "run_started_marker": False,
            "case_execution_started": False,
            "run_completed_marker": False,
            "terminal_scientific_event_count": 0,
            "scientific_intent_event_count": 0,
            "outcomes_exposed_to_selection_process": False,
            "result_bytes_decoded_before_selection": False,
            "oracle_join_performed_before_selection": False,
            "operator_cancellation_requested": False,
            "input_hash_mismatch": False,
        }
    if state == "U":
        value = _signals("E")
        value["outcomes_exposed_to_selection_process"] = True
        return value
    if state != "N":
        raise AssertionError(state)
    return {
        "provider_job_id": "provider-job-fixture",
        "provider_job_state": "completed",
        "external_cancellation_actor": "none",
        "host_heartbeat_state": "present",
        "image_pull_status": "succeeded",
        "input_acquisition_status": "complete",
        "input_lock_completed": True,
        "preflight_storage_probe": "passed",
        "run_started_marker": True,
        "case_execution_started": True,
        "run_completed_marker": True,
        "terminal_scientific_event_count": 1,
        "scientific_intent_event_count": 1,
        "outcomes_exposed_to_selection_process": False,
        "result_bytes_decoded_before_selection": False,
        "oracle_join_performed_before_selection": False,
        "operator_cancellation_requested": False,
        "input_hash_mismatch": False,
    }


def _attempt(
    state: str,
    number: int,
    *,
    environment_id: str = "ENV-AUTHOR",
    authorization_status: str = "NOT_APPLICABLE",
    authorization_sha256: str | None = None,
) -> dict[str, Any]:
    clock = continuous_clock()
    now_us = clock.now_ns() // 1_000
    return {
        "schema_version": "amy.environment-attempt-record.v1-draft",
        "classification": CONTRACT_TEST_CLASSIFICATION,
        "attempt_id": f"{environment_id}-A{number}",
        "environment_id": environment_id,
        "attempt_number": number,
        "attempt_state": "PRESTART_ABORTED" if state in {"E", "U"} else "COMPLETED",
        "bindings": {
            "run_execution_policy_sha256": _sha(RUN_POLICY),
            "release_lineage_contract_sha256": "1" * 64,
            "registered_input_manifest_sha256": "2" * 64,
            "command_plan_sha256": "3" * 64,
            "runner_sha256": _sha(RUNNER_SOURCE),
            "attempt_record_schema_sha256": _sha(ATTEMPT_SCHEMA),
        },
        "attempt_two_authorization": {
            "status": authorization_status,
            "attempt_one_classification_sha256": authorization_sha256,
        },
        "clock": {
            "clock_id": clock.clock_id,
            "resolution_ns": clock.resolution_ns,
            "started_continuous_us": now_us - 2,
            "ended_continuous_us": now_us - 1,
            "elapsed_us": 1,
            "started_wall_utc": "2026-07-13T16:30:00Z",
            "ended_wall_utc": "2026-07-13T16:30:01Z",
        },
        "isolation": {
            "shell_used": False,
            "start_new_session": True,
            "close_fds": True,
            "stdin_devnull": True,
            "environment_allowlist_sha256": "4" * 64,
            "cwd_identity_sha256": "5" * 64,
            "network_isolation_verified_by_runner": False,
            "filesystem_sandbox_verified_by_runner": False,
        },
        "process": {
            "spawned": state == "N",
            "pid": 123 if state == "N" else None,
            "exit_code": 0 if state == "N" else None,
            "exit_signal": None,
            "timeout_triggered": False,
            "output_limit_exceeded": False,
            "sigterm_sent": False,
            "sigkill_sent": False,
            "reaped": state == "N",
        },
        "signals": _signals(state),
        "outcome_guard": {
            "guard_epoch_id": "contract-test-guard-epoch",
            "checkpoint_sequence": number,
            "log_head_sha256": "6" * 64,
            "scientific_intent_event_count": 0 if state in {"E", "U"} else 1,
            "result_decode_event_count": 1 if state == "U" else 0,
            "oracle_join_event_count": 0,
            "human_outcome_read_event_count": 0,
            "decode_capability_released": False,
        },
        "raw_artifacts": [],
        "boundaries": {
            "record_finalized_before_result_decoding": True,
            "selection_not_yet_performed": True,
            "confirmatory_outcomes_read_by_runner": False,
            "oracle_read_by_runner": False,
            "independent_review_performed": False,
        },
        "limitations": {
            "network_absence_proven": False,
            "provider_signals_authenticated": False,
            "external_outcome_access_excluded": False,
            "operator_identity_authenticated": False,
            "cryptographic_signature_verified": False,
        },
    }


def _classify(attempt: dict[str, Any]) -> dict[str, Any]:
    raw = rfc8785.dumps(attempt)
    return classify_infrastructure_before_decode(
        build_classifier_view(attempt),
        attempt_record_sha256=sha256_bytes(raw),
        attempt_record_schema_sha256=_sha(ATTEMPT_SCHEMA),
        run_policy_sha256=_sha(RUN_POLICY),
        classifier_sha256=_sha(RUNNER_SOURCE),
        classification_schema_sha256=_sha(CLASSIFICATION_SCHEMA),
    )


def _selection_inputs(
    first_state: str,
    second_state: str | None,
    *,
    environment_id: str = "ENV-AUTHOR",
) -> list[dict[str, Any]]:
    first_attempt = _attempt(first_state, 1, environment_id=environment_id)
    first_classification = _classify(first_attempt)
    first_classification_raw = rfc8785.dumps(first_classification)
    values = [
        {
            "attempt_record": first_attempt,
            "attempt_record_sha256": sha256_bytes(rfc8785.dumps(first_attempt)),
            "classification_record": first_classification,
            "classification_record_sha256": sha256_bytes(first_classification_raw),
        }
    ]
    if second_state is not None:
        authorized = first_state == "E"
        second_attempt = _attempt(
            second_state,
            2,
            environment_id=environment_id,
            authorization_status="AUTHORIZED" if authorized else "MISSING_UNAUTHORIZED",
            authorization_sha256=(
                sha256_bytes(first_classification_raw) if authorized else None
            ),
        )
        second_classification = _classify(second_attempt)
        values.append(
            {
                "attempt_record": second_attempt,
                "attempt_record_sha256": sha256_bytes(rfc8785.dumps(second_attempt)),
                "classification_record": second_classification,
                "classification_record_sha256": sha256_bytes(
                    rfc8785.dumps(second_classification)
                ),
            }
        )
    return values


def _select(values: list[dict[str, Any]]) -> dict[str, Any]:
    return select_official_attempt_before_decode(
        values,
        run_policy_sha256=_sha(RUN_POLICY),
        selector_sha256=_sha(RUNNER_SOURCE),
        selection_schema_sha256=_sha(SELECTION_SCHEMA),
    )


def test_all_rg006_schemas_are_valid_and_every_object_is_closed() -> None:
    for path in (
        PROCESS_SCHEMA,
        INTENT_SCHEMA,
        ATTEMPT_SCHEMA,
        CLASSIFICATION_SCHEMA,
        SELECTION_SCHEMA,
    ):
        schema = _load(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)

        def inspect(value: Any, pointer: str = "") -> None:
            if isinstance(value, dict):
                if value.get("type") == "object":
                    assert value.get("additionalProperties") is False, (
                        path.name,
                        pointer or "/",
                    )
                for key, child in value.items():
                    inspect(child, f"{pointer}/{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inspect(child, f"{pointer}/{index}")

        inspect(schema)


def test_suspend_aware_clock_is_explicit_and_monotonic() -> None:
    clock = continuous_clock()
    first = clock.now_ns()
    second = clock.now_ns()
    assert second >= first
    assert clock.resolution_ns >= 1
    if sys.platform == "darwin":
        assert clock.clock_id == "darwin_mach_continuous_time"
    elif sys.platform.startswith("linux"):
        assert clock.clock_id == "linux_CLOCK_BOOTTIME"
    else:  # pragma: no cover - fail-closed platform guard
        raise AssertionError("test should not run on an unsupported platform")


def test_process_primitive_refuses_confirmatory_classification(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    argv = [str(Path(sys.executable).resolve()), "-c", "pass"]
    environment: dict[str, str] = {}
    with pytest.raises(RunnerContractError, match="confirmatory execution is disabled"):
        run_contract_test_process(
            classification="confirmatory_R1",
            argv=argv,
            expected_executable_sha256=_sha(Path(sys.executable).resolve()),
            **_command_commitments(argv, cwd, environment),
            cwd=cwd,
            environment=environment,
            output_parent=output,
            output_name="forbidden",
            timeout_seconds=1,
            termination_grace_seconds=0.1,
            reap_timeout_seconds=0.1,
            max_output_bytes_per_stream=1024,
            max_total_output_bytes=2048,
        )
    assert list(output.iterdir()) == []


def test_process_isolated_capture_is_raw_canonical_and_environment_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    monkeypatch.setenv("PARENT_SECRET_SHOULD_NOT_LEAK", "secret")
    script = (
        "import json,os,sys;"
        "sys.stdout.buffer.write(json.dumps({"
        "'allowed':os.environ.get('ONLY_ALLOWED'),"
        "'secret':os.environ.get('PARENT_SECRET_SHOULD_NOT_LEAK')},"
        "sort_keys=True).encode());"
        "sys.stderr.buffer.write(b'raw-stderr')"
    )
    argv = [str(Path(sys.executable).resolve()), "-c", script]
    environment = {"ONLY_ALLOWED": "visible", "PYTHONUTF8": "1"}
    result = run_contract_test_process(
        classification=CONTRACT_TEST_CLASSIFICATION,
        argv=argv,
        expected_executable_sha256=_sha(Path(sys.executable).resolve()),
        **_command_commitments(argv, cwd, environment),
        cwd=cwd,
        environment=environment,
        output_parent=output,
        output_name="attempt-fixture",
        timeout_seconds=5,
        termination_grace_seconds=0.2,
        reap_timeout_seconds=0.2,
        max_output_bytes_per_stream=4096,
        max_total_output_bytes=8192,
    )
    record = result["record"]
    assert _schema_errors(PROCESS_SCHEMA, record) == []
    assert record["boundaries"] == {
        "confirmatory_execution_permitted": False,
        "confirmatory_outcomes_read": False,
        "result_bytes_decoded": False,
        "oracle_read": False,
        "independent_review_performed": False,
        "same_uid_external_read_or_mutation_excluded": False,
        "outcome_blindness_established": False,
    }
    attempt_dir = output / "attempt-fixture"
    stdout_raw = (attempt_dir / "stdout.raw").read_bytes()
    stderr_raw = (attempt_dir / "stderr.raw").read_bytes()
    # Decoding here is a contract-test assertion after the runner has returned;
    # the runner itself only hashed and persisted bytes.
    assert json.loads(stdout_raw) == {"allowed": "visible", "secret": None}
    assert stderr_raw == b"raw-stderr"
    metadata_raw = (attempt_dir / "process-metadata.jcs.json").read_bytes()
    assert metadata_raw == rfc8785.dumps(record)
    assert result["record_file"]["sha256"] == sha256_bytes(metadata_raw)
    assert all(not item["decoded_by_runner"] for item in record["raw_artifacts"])
    assert all(
        item["final_bytes_reverified_by_runner"]
        for item in record["raw_artifacts"]
    )
    clock = record["clock"]
    assert clock["elapsed_us"] == (
        clock["ended_continuous_us"] - clock["started_continuous_us"]
    )
    assert clock["deadline_continuous_us"] == (
        clock["started_continuous_us"] + clock["timeout_limit_us"]
    )
    assert clock["all_waits_bounded"] is True
    assert record["command"]["pre_spawn_commitments_verified"] is True
    assert validate_process_isolation_record(record) == []
    tampered_timing = copy.deepcopy(record)
    tampered_timing["clock"]["elapsed_us"] += 1
    assert "elapsed time differs from end minus start" in validate_process_isolation_record(
        tampered_timing
    )


def test_scientific_intent_event_is_schema_valid_and_bound_to_process(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    result = _run_simple_process(cwd, output, "intent-one")
    receipt = result["record"]["scientific_intent"]
    event_path = output / receipt["event_path"]
    raw = event_path.read_bytes()
    event = json.loads(raw)
    assert raw == rfc8785.dumps(event)
    assert _schema_errors(INTENT_SCHEMA, event) == []
    assert receipt["event_sha256"] == sha256_bytes(raw)
    assert event["command"]["output_name"] == "intent-one"
    assert event["boundaries"]["power_loss_durability_established"] is False
    assert event["boundaries"]["rollback_detection_established"] is False
    reconstructed = inspect_scientific_intent_log(output / ".scientific-intent-log")
    assert reconstructed == {
        "guard_epoch_id": receipt["guard_epoch_id"],
        "event_count": 1,
        "head_sha256": receipt["event_sha256"],
        "spawn_ids": ["intent-one"],
    }


def test_scientific_intent_chain_is_contiguous_and_parent_bound(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    first = _run_simple_process(cwd, output, "intent-one")["record"]["scientific_intent"]
    second = _run_simple_process(cwd, output, "intent-two")["record"]["scientific_intent"]
    assert first["sequence"] == 1
    assert first["parent_event_sha256"] is None
    assert second["sequence"] == 2
    assert second["parent_event_sha256"] == first["event_sha256"]
    reconstructed = inspect_scientific_intent_log(output / ".scientific-intent-log")
    assert reconstructed["event_count"] == 2
    assert reconstructed["head_sha256"] == second["event_sha256"]
    assert reconstructed["spawn_ids"] == ["intent-one", "intent-two"]


@pytest.mark.parametrize("tamper", ["unexpected", "gap", "corrupt"])
def test_ambiguous_or_corrupt_intent_log_prevents_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    _run_simple_process(cwd, output, "intent-one")
    log = output / ".scientific-intent-log"
    event = log / "intent-0000000000000001.jcs.json"
    if tamper == "unexpected":
        (log / ".debris").write_bytes(b"ambiguous")
    elif tamper == "gap":
        event.rename(log / "intent-0000000000000002.jcs.json")
    else:
        event.unlink()
        event.write_bytes(b"{}")

    popen_called = False

    def forbidden_popen(*args: Any, **kwargs: Any) -> Any:
        nonlocal popen_called
        popen_called = True
        raise AssertionError("spawn must not be reached")

    monkeypatch.setattr(runner_module.subprocess, "Popen", forbidden_popen)
    with pytest.raises(RunnerContractError):
        _run_simple_process(cwd, output, "intent-two")
    assert popen_called is False


def test_intent_append_lock_prevents_concurrent_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    _run_simple_process(cwd, output, "intent-one")
    lock_fd = os.open(output / ".scientific-intent-log", os.O_RDONLY)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("spawn must not be reached")
        ),
    )
    try:
        with pytest.raises(RunnerContractError, match="already locked"):
            _run_simple_process(cwd, output, "intent-two")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def test_popen_failure_retains_intent_and_blocks_same_spawn_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    real_popen = runner_module.subprocess.Popen
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic spawn failure")),
    )
    with pytest.raises(OSError, match="synthetic spawn failure"):
        _run_simple_process(cwd, output, "spawn-fails")
    reconstructed = inspect_scientific_intent_log(output / ".scientific-intent-log")
    assert reconstructed["event_count"] == 1
    assert reconstructed["spawn_ids"] == ["spawn-fails"]
    assert not (output / "spawn-fails/process-metadata.jcs.json").exists()
    monkeypatch.setattr(runner_module.subprocess, "Popen", real_popen)
    with pytest.raises(FileExistsError):
        _run_simple_process(cwd, output, "spawn-fails")
    assert inspect_scientific_intent_log(output / ".scientific-intent-log")[
        "event_count"
    ] == 1


def test_intent_publication_failure_prevents_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    real_atomic = runner_module._atomic_write_new_at
    popen_called = False

    def failing_atomic(directory_fd: int, name: str, raw: bytes) -> None:
        if name.startswith("intent-"):
            raise OSError(errno.ENOSPC, "synthetic intent ENOSPC")
        real_atomic(directory_fd, name, raw)

    def forbidden_popen(*args: Any, **kwargs: Any) -> Any:
        nonlocal popen_called
        popen_called = True
        raise AssertionError("spawn must not be reached")

    monkeypatch.setattr(runner_module, "_atomic_write_new_at", failing_atomic)
    monkeypatch.setattr(runner_module.subprocess, "Popen", forbidden_popen)
    with pytest.raises(OSError) as exc_info:
        _run_simple_process(cwd, output, "intent-enospc")
    assert exc_info.value.errno == errno.ENOSPC
    assert popen_called is False


def test_process_crash_after_intent_before_spawn_retains_event(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    executable = str(Path(sys.executable).resolve())
    argv = [executable, "-c", "pass"]
    environment = {"PYTHONUTF8": "1"}
    commitments = _command_commitments(argv, cwd, environment)
    worker = f"""
import os
from pathlib import Path
import amy_verifier.confirmatory_runner as runner
runner.subprocess.Popen = lambda *args, **kwargs: os._exit(91)
runner.run_contract_test_process(
    classification=runner.CONTRACT_TEST_CLASSIFICATION,
    argv={argv!r},
    expected_executable_sha256={_sha(Path(executable))!r},
    expected_argv_jcs_sha256={commitments['expected_argv_jcs_sha256']!r},
    expected_environment_jcs_sha256={commitments['expected_environment_jcs_sha256']!r},
    expected_cwd_root_identity_jcs_sha256={commitments['expected_cwd_root_identity_jcs_sha256']!r},
    cwd=Path({str(cwd)!r}),
    environment={environment!r},
    output_parent=Path({str(output)!r}),
    output_name='crash-before-spawn',
    timeout_seconds=2,
    termination_grace_seconds=0.1,
    reap_timeout_seconds=0.1,
    max_output_bytes_per_stream=1024,
    max_total_output_bytes=2048,
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", worker],
        cwd=STUDY_ROOT,
        env={**os.environ, "PYTHONPATH": str(STUDY_ROOT)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 91
    reconstructed = inspect_scientific_intent_log(output / ".scientific-intent-log")
    assert reconstructed["event_count"] == 1
    assert reconstructed["spawn_ids"] == ["crash-before-spawn"]
    assert not (output / "crash-before-spawn/process-metadata.jcs.json").exists()


def test_process_output_limit_and_timeout_are_retained(tmp_path: Path) -> None:
    executable = str(Path(sys.executable).resolve())
    for name, script, timeout, expected in (
        (
            "output-limit",
            "import sys;sys.stdout.buffer.write(b'x'*10000);sys.stdout.flush()",
            5,
            "output_limit_exceeded",
        ),
        ("timeout", "import time;time.sleep(2)", 0.05, "timeout_triggered"),
    ):
        cwd = tmp_path / f"cwd-{name}"
        output = tmp_path / f"output-{name}"
        cwd.mkdir()
        output.mkdir()
        argv = [executable, "-c", script]
        environment = {"PYTHONUTF8": "1"}
        result = run_contract_test_process(
            classification=CONTRACT_TEST_CLASSIFICATION,
            argv=argv,
            expected_executable_sha256=_sha(Path(executable)),
            **_command_commitments(argv, cwd, environment),
            cwd=cwd,
            environment=environment,
            output_parent=output,
            output_name=name,
            timeout_seconds=timeout,
            termination_grace_seconds=0.05,
            reap_timeout_seconds=0.05,
            max_output_bytes_per_stream=128,
            max_total_output_bytes=256,
        )["record"]
        assert result["process"][expected] is True
        assert result["process"]["reaped"] is True
        if name == "output-limit":
            stdout = next(item for item in result["raw_artifacts"] if item["role"] == "stdout")
            assert stdout["truncated"] is True
            assert stdout["captured_bytes"] == 128
            assert stdout["observed_bytes"] >= 128


def test_descendant_inheriting_capture_pipes_cannot_hold_runner_open(
    tmp_path: Path,
) -> None:
    tree = ast.parse(RUNNER_SOURCE.read_text(encoding="utf-8"))
    wait_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "wait"
    ]
    assert wait_calls
    assert all(any(keyword.arg == "timeout" for keyword in node.keywords) for node in wait_calls)
    cwd = tmp_path / "cwd-grandchild"
    output = tmp_path / "output-grandchild"
    cwd.mkdir()
    output.mkdir()
    executable = str(Path(sys.executable).resolve())
    child = (
        "import os,subprocess,sys;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "os._exit(0)"
    )
    argv = [executable, "-c", child]
    environment = {"PYTHONUTF8": "1"}
    started = time.monotonic()
    record = run_contract_test_process(
        classification=CONTRACT_TEST_CLASSIFICATION,
        argv=argv,
        expected_executable_sha256=_sha(Path(executable)),
        **_command_commitments(argv, cwd, environment),
        cwd=cwd,
        environment=environment,
        output_parent=output,
        output_name="inherited-pipes",
        timeout_seconds=0.05,
        termination_grace_seconds=0.05,
        reap_timeout_seconds=0.05,
        max_output_bytes_per_stream=1024,
        max_total_output_bytes=2048,
    )["record"]
    assert time.monotonic() - started < 2
    assert record["process"]["timeout_triggered"] is True
    assert record["process"]["sigterm_sent"] is True
    assert record["process"]["reaped"] is True
    assert _schema_errors(PROCESS_SCHEMA, record) == []


def test_inheritable_file_socket_and_parent_injection_do_not_reach_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    output = tmp_path / "output"
    cwd.mkdir()
    output.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"descriptor-secret")
    source_fd = os.open(sentinel, os.O_RDONLY)
    file_fd = fcntl.fcntl(source_fd, fcntl.F_DUPFD, 200)
    left, right = socket.socketpair()
    socket_fd = fcntl.fcntl(left.fileno(), fcntl.F_DUPFD, 220)
    os.set_inheritable(file_fd, True)
    os.set_inheritable(socket_fd, True)
    for key in (
        "PYTHONPATH",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "SSH_AUTH_SOCK",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(key, "injection-canary")
    executable = str(Path(sys.executable).resolve())
    grandchild = (
        "import json,os,sys;"
        "out=[];"
        "[(out.append(os.read(int(fd),17)==b'descriptor-secret') "
        "if __import__('os').path.exists('/dev/fd/'+fd) else out.append(False)) "
        "for fd in sys.argv[1:]];"
        "print(json.dumps(out))"
    )
    child = (
        "import json,os,subprocess,sys;"
        "fds=sys.argv[1:3];"
        "direct=[];"
        "[(direct.append(os.read(int(fd),17)==b'descriptor-secret') "
        "if os.path.exists('/dev/fd/'+fd) else direct.append(False)) for fd in fds];"
        "nested=subprocess.check_output([sys.executable,'-c',sys.argv[3],*fds],"
        "env={'PYTHONUTF8':'1'},close_fds=True,text=True);"
        "print(json.dumps({'direct':direct,'nested':json.loads(nested),"
        "'injected':[key for key in "
        "['PYTHONPATH','LD_PRELOAD','DYLD_INSERT_LIBRARIES','SSH_AUTH_SOCK',"
        "'HTTP_PROXY','HTTPS_PROXY'] if key in os.environ]},sort_keys=True))"
    )
    argv = [executable, "-c", child, str(file_fd), str(socket_fd), grandchild]
    environment = {"PYTHONUTF8": "1"}
    try:
        record = run_contract_test_process(
            classification=CONTRACT_TEST_CLASSIFICATION,
            argv=argv,
            expected_executable_sha256=_sha(Path(executable)),
            **_command_commitments(argv, cwd, environment),
            cwd=cwd,
            environment=environment,
            output_parent=output,
            output_name="descriptor-test",
            timeout_seconds=5,
            termination_grace_seconds=0.2,
            reap_timeout_seconds=0.2,
            max_output_bytes_per_stream=4096,
            max_total_output_bytes=8192,
        )["record"]
    finally:
        os.close(file_fd)
        os.close(source_fd)
        os.close(socket_fd)
        left.close()
        right.close()
    observed = json.loads((output / "descriptor-test/stdout.raw").read_bytes())
    assert observed == {"direct": [False, False], "injected": [], "nested": [False, False]}
    assert record["isolation"]["pass_fds_empty"] is True
    assert record["isolation"]["process_tree_containment_verified_by_runner"] is False


def test_executable_hash_and_symlinked_output_parent_fail_closed(tmp_path: Path) -> None:
    executable = str(Path(sys.executable).resolve())
    cwd = tmp_path / "cwd"
    real_output = tmp_path / "real-output"
    linked_output = tmp_path / "linked-output"
    cwd.mkdir()
    real_output.mkdir()
    linked_output.symlink_to(real_output, target_is_directory=True)
    common = {
        "classification": CONTRACT_TEST_CLASSIFICATION,
        "argv": [executable, "-c", "pass"],
        "cwd": cwd,
        "environment": {"PYTHONUTF8": "1"},
        "output_name": "attempt",
        "timeout_seconds": 1,
        "termination_grace_seconds": 0.1,
        "reap_timeout_seconds": 0.1,
        "max_output_bytes_per_stream": 1024,
        "max_total_output_bytes": 2048,
    }
    common.update(_command_commitments(common["argv"], cwd, common["environment"]))
    for field in (
        "expected_argv_jcs_sha256",
        "expected_environment_jcs_sha256",
        "expected_cwd_root_identity_jcs_sha256",
    ):
        tampered = dict(common)
        tampered[field] = "0" * 64
        with pytest.raises(RunnerContractError, match="registered commitment"):
            run_contract_test_process(
                **tampered,
                expected_executable_sha256=_sha(Path(executable)),
                output_parent=real_output,
            )
        assert list(real_output.iterdir()) == []
    with pytest.raises(RunnerContractError, match="executable SHA-256 differs"):
        run_contract_test_process(
            **common,
            expected_executable_sha256="0" * 64,
            output_parent=real_output,
        )
    with pytest.raises(OSError):
        run_contract_test_process(
            **common,
            expected_executable_sha256=_sha(Path(executable)),
            output_parent=linked_output,
        )
    assert list(real_output.iterdir()) == []


def test_atomic_jcs_creation_never_replaces_existing_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "seal.jcs.json"
    destination.write_bytes(b"pre-existing")
    with pytest.raises(FileExistsError):
        write_new_jcs(destination, {"replacement": True})
    assert destination.read_bytes() == b"pre-existing"


@pytest.mark.parametrize("fault_errno", [errno.ENOSPC, errno.EDQUOT, errno.EIO])
@pytest.mark.parametrize(
    ("boundary", "operation", "call_number", "final_expected", "temporary_expected"),
    [
        ("temporary write", "write", 1, False, True),
        ("temporary file fsync", "fsync", 1, False, True),
        ("no-replace rename", "rename", 1, False, True),
        ("published-name directory fsync", "fsync", 2, True, False),
    ],
)
def test_atomic_publication_storage_faults_never_substitute_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_errno: int,
    boundary: str,
    operation: str,
    call_number: int,
    final_expected: bool,
    temporary_expected: bool,
) -> None:
    destination = tmp_path / "faulted.jcs.json"
    expected = rfc8785.dumps({"bounded": True, "fault": fault_errno})
    owner = runner_module if operation == "rename" else runner_module.os
    attribute = "_rename_noreplace_raw" if operation == "rename" else operation
    original = getattr(owner, attribute)
    calls = 0
    injections = 0

    def inject(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls, injections
        calls += 1
        if calls == call_number:
            injections += 1
            raise OSError(fault_errno, f"injected {boundary}")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attribute, inject)
    with pytest.raises(OSError) as captured:
        runner_module.write_new_jcs(destination, {"bounded": True, "fault": fault_errno})
    assert captured.value.errno == fault_errno
    assert injections == 1
    assert calls >= call_number

    temporary_names = list(tmp_path.glob(".faulted.jcs.json.tmp-*"))
    assert destination.exists() is final_expected
    assert bool(temporary_names) is temporary_expected
    if final_expected:
        assert destination.read_bytes() == expected
        expected_links = 2 if temporary_expected else 1
        assert destination.stat().st_nlink == expected_links
    else:
        assert all(item.stat().st_nlink == 1 for item in temporary_names)


@pytest.mark.parametrize(
    ("boundary", "operation", "call_number"),
    [
        ("temporary write", "write", 1),
        ("temporary file fsync", "fsync", 1),
        ("no-replace rename", "rename", 1),
        ("published-name directory fsync", "fsync", 2),
    ],
)
def test_atomic_publication_retries_one_interrupted_syscall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    operation: str,
    call_number: int,
) -> None:
    destination = tmp_path / "interrupted.jcs.json"
    owner = runner_module if operation == "rename" else runner_module.os
    attribute = "_rename_noreplace_raw" if operation == "rename" else operation
    original = getattr(owner, attribute)
    calls = 0
    injected = False

    def interrupt_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls, injected
        calls += 1
        if calls == call_number and not injected:
            injected = True
            raise InterruptedError(errno.EINTR, f"injected {boundary}")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attribute, interrupt_once)
    receipt = runner_module.write_new_jcs(destination, {"interrupted": boundary})
    expected = rfc8785.dumps({"interrupted": boundary})
    assert injected is True
    assert destination.read_bytes() == expected
    assert destination.stat().st_nlink == 1
    assert receipt["sha256"] == hashlib.sha256(expected).hexdigest()
    assert list(tmp_path.glob(".interrupted.jcs.json.tmp-*")) == []


@pytest.mark.parametrize("operation", ["write", "fsync", "rename"])
def test_atomic_publication_bounds_persistent_eintr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    destination = tmp_path / f"persistent-{operation}.jcs.json"
    owner = runner_module if operation == "rename" else runner_module.os
    attribute = "_rename_noreplace_raw" if operation == "rename" else operation
    calls = 0

    def always_interrupt(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise InterruptedError(errno.EINTR, f"persistent {operation}")

    monkeypatch.setattr(owner, attribute, always_interrupt)
    with pytest.raises(RunnerContractError, match="interrupted too many times"):
        runner_module.write_new_jcs(destination, {"persistent": operation})
    assert calls == runner_module._MAX_EINTR_RETRIES + 1
    assert not destination.exists()
    assert len(list(tmp_path.glob(f".{destination.name}.tmp-*"))) == 1


def test_atomic_publication_detects_same_uid_final_entry_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "published.jcs.json"
    displaced = tmp_path / "displaced-new-bytes.jcs.json"
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"pre-existing-victim")
    original = runner_module._rename_noreplace_raw

    def substitute_after_publish(directory_fd: int, source: str, name: str) -> None:
        original(directory_fd, source, name)
        os.rename(
            name,
            displaced.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.rename(
            victim.name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )

    monkeypatch.setattr(
        runner_module, "_rename_noreplace_raw", substitute_after_publish
    )
    with pytest.raises(RunnerContractError, match="identity is not closed"):
        runner_module.write_new_jcs(destination, {"new": "bytes"})
    assert destination.read_bytes() == b"pre-existing-victim"
    assert displaced.read_bytes() == rfc8785.dumps({"new": "bytes"})
    assert not victim.exists()


@pytest.mark.parametrize(
    ("crash_point", "final_expected", "temporary_expected"),
    [
        ("before_rename", False, True),
        ("after_rename", True, False),
        ("after_directory_fsync", True, False),
    ],
)
def test_atomic_publication_process_crash_states_are_non_substitutive(
    tmp_path: Path,
    crash_point: str,
    final_expected: bool,
    temporary_expected: bool,
) -> None:
    script = r'''\
import os
import sys
from pathlib import Path
import amy_verifier.confirmatory_runner as runner

root = Path(sys.argv[1])
point = sys.argv[2]
original_rename = runner._rename_noreplace_raw
original_fsync = runner._fsync

if point in {"before_rename", "after_rename"}:
    def crash_rename(directory_fd, source, destination):
        if point == "before_rename":
            os._exit(91)
        original_rename(directory_fd, source, destination)
        os._exit(91)
    runner._rename_noreplace_raw = crash_rename
elif point == "after_directory_fsync":
    calls = 0
    def crash_fsync(descriptor):
        global calls
        original_fsync(descriptor)
        calls += 1
        if calls == 2:
            os._exit(91)
    runner._fsync = crash_fsync

runner.write_new_jcs(root / "crash.jcs.json", {"crash": point})
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), crash_point],
        cwd=STUDY_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 91
    destination = tmp_path / "crash.jcs.json"
    temporaries = list(tmp_path.glob(".crash.jcs.json.tmp-*"))
    assert destination.exists() is final_expected
    assert bool(temporaries) is temporary_expected
    if final_expected:
        assert destination.read_bytes() == rfc8785.dumps({"crash": crash_point})
        assert destination.stat().st_nlink == 1


@pytest.mark.parametrize(
    ("first", "second", "disposition", "official"),
    [
        ("N", None, "ATTEMPT_1_OFFICIAL", 1),
        ("N", "N", "ATTEMPT_1_OFFICIAL", 1),
        ("N", "E", "ATTEMPT_1_OFFICIAL", 1),
        ("N", "U", "ATTEMPT_1_OFFICIAL", 1),
        ("E", None, "NO_OFFICIAL_ATTEMPT", None),
        ("E", "N", "ATTEMPT_2_OFFICIAL", 2),
        ("E", "E", "NO_OFFICIAL_ATTEMPT", None),
        ("E", "U", "NO_OFFICIAL_ATTEMPT", None),
        ("U", None, "NO_OFFICIAL_ATTEMPT", None),
        ("U", "N", "NO_OFFICIAL_ATTEMPT", None),
        ("U", "E", "NO_OFFICIAL_ATTEMPT", None),
        ("U", "U", "NO_OFFICIAL_ATTEMPT", None),
    ],
)
def test_complete_attempt_selection_truth_table(
    first: str,
    second: str | None,
    disposition: str,
    official: int | None,
) -> None:
    values = _selection_inputs(first, second)
    for item in values:
        assert _schema_errors(ATTEMPT_SCHEMA, item["attempt_record"]) == []
        assert _schema_errors(CLASSIFICATION_SCHEMA, item["classification_record"]) == []
    selected = _select(values)
    assert selected["selection"]["disposition"] == disposition
    assert selected["selection"]["official_attempt_number"] == official
    assert selected["selection"]["candidate_for_campaign_decode_authorization"] is (
        official is not None
    )
    assert selected["boundaries"]["selection_computed_without_result_bytes"] is True
    assert selected["limitations"]["rg006_complete"] is False


def test_one_campaign_seal_covers_both_environments_before_any_decode() -> None:
    environment_attempts = {
        "ENV-AUTHOR": _selection_inputs("N", None, environment_id="ENV-AUTHOR"),
        "ENV-LINUX-PINNED": _selection_inputs(
            "E", "N", environment_id="ENV-LINUX-PINNED"
        ),
    }
    guard = {
        "guard_epoch_id": "contract-test-guard-epoch",
        "checkpoint_sequence": 100,
        "log_head_sha256": "7" * 64,
        "scientific_intent_event_count": 2,
        "result_decode_event_count": 0,
        "oracle_join_event_count": 0,
        "human_outcome_read_event_count": 0,
        "decode_capability_released": False,
    }
    seal = build_campaign_selection_seal_before_decode(
        environment_attempts,
        required_environment_ids=["ENV-AUTHOR", "ENV-LINUX-PINNED"],
        phase_id="R1",
        campaign_outcome_guard=guard,
        run_policy_sha256=_sha(RUN_POLICY),
        selector_sha256=_sha(RUNNER_SOURCE),
        selection_schema_sha256=_sha(SELECTION_SCHEMA),
        outcome_guard_policy_sha256="8" * 64,
    )
    assert _schema_errors(SELECTION_SCHEMA, seal) == []
    assert seal["seal_status"] == "INVALID_FAIL_CLOSED"
    assert seal["candidate_decode_attempt_ids_after_external_authentication"] == []
    assert seal["boundaries"]["guard_counters_locally_consistent"] is True
    assert (
        seal["boundaries"]["result_release_prevention_technically_enforced"]
        is False
    )
    assert (
        seal["boundaries"][
            "no_environment_result_released_before_campaign_selection"
        ]
        is False
    )
    assert seal["authentication"]["detached_authentication_verified"] is False
    assert seal["authentication"]["decode_capability_released"] is False
    assert seal["limitations"]["rg006_complete"] is False

    dirty_guard = dict(guard)
    dirty_guard["result_decode_event_count"] = 1
    invalid = build_campaign_selection_seal_before_decode(
        environment_attempts,
        required_environment_ids=["ENV-AUTHOR", "ENV-LINUX-PINNED"],
        phase_id="R1",
        campaign_outcome_guard=dirty_guard,
        run_policy_sha256=_sha(RUN_POLICY),
        selector_sha256=_sha(RUNNER_SOURCE),
        selection_schema_sha256=_sha(SELECTION_SCHEMA),
        outcome_guard_policy_sha256="8" * 64,
    )
    assert invalid["seal_status"] == "INVALID_FAIL_CLOSED"
    assert invalid["candidate_decode_attempt_ids_after_external_authentication"] == []
    assert invalid["boundaries"]["guard_counters_locally_consistent"] is False


def test_classifier_rejects_predicate_overlap_and_midrun_zero_terminal_event() -> None:
    overlap = _attempt("E", 1)
    overlap["signals"]["input_acquisition_status"] = "failed"
    classified_overlap = _classify(overlap)
    assert classified_overlap["verdict"]["status"] == INVALID_CLASSIFICATION
    assert classified_overlap["verdict"]["reason_codes"] == [
        "AMBIGUOUS_INFRASTRUCTURE_PREDICATES"
    ]

    midrun = _attempt("E", 1)
    midrun["attempt_state"] = "STARTED_INCOMPLETE"
    midrun["signals"]["provider_job_state"] = "runner_lost"
    midrun["signals"]["external_cancellation_actor"] = "provider"
    midrun["signals"]["host_heartbeat_state"] = "lost"
    midrun["signals"]["run_started_marker"] = True
    midrun["signals"]["case_execution_started"] = True
    classified_midrun = _classify(midrun)
    assert classified_midrun["verdict"]["status"] == NOT_RETRY_ELIGIBLE
    assert classified_midrun["verdict"]["complete_environment_rerun_permitted"] is False


def test_attempt_two_must_bind_persisted_attempt_one_classification() -> None:
    values = _selection_inputs("E", "N")
    tampered = copy.deepcopy(values)
    tampered[1]["attempt_record"]["attempt_two_authorization"][
        "attempt_one_classification_sha256"
    ] = "f" * 64
    tampered[1]["attempt_record_sha256"] = sha256_bytes(
        rfc8785.dumps(tampered[1]["attempt_record"])
    )
    tampered[1]["classification_record"] = _classify(
        tampered[1]["attempt_record"]
    )
    tampered[1]["classification_record_sha256"] = sha256_bytes(
        rfc8785.dumps(tampered[1]["classification_record"])
    )
    selected = _select(tampered)
    assert selected["selection"]["disposition"] == "NO_OFFICIAL_ATTEMPT"
    assert selected["selection"]["reason_code"] == (
        "ATTEMPT_2_AUTHORIZATION_BINDING_INVALID"
    )
    assert selected["selection"]["supplied_attempt_two_binding_valid"] is False


def test_third_attempt_is_retained_but_cannot_replace_and_duplicates_are_rejected() -> None:
    values = _selection_inputs("E", "N")
    third_attempt = _attempt(
        "N",
        3,
        authorization_status="MISSING_UNAUTHORIZED",
        authorization_sha256=None,
    )
    third_classification = _classify(third_attempt)
    third = {
        "attempt_record": third_attempt,
        "attempt_record_sha256": sha256_bytes(rfc8785.dumps(third_attempt)),
        "classification_record": third_classification,
        "classification_record_sha256": sha256_bytes(
            rfc8785.dumps(third_classification)
        ),
    }
    selected = _select([*values, third])
    assert selected["selection"]["disposition"] == "ATTEMPT_2_OFFICIAL"
    assert selected["selection"]["unauthorized_attempt_numbers"] == [3]
    assert [item["attempt_number"] for item in selected["input_attempts"]] == [1, 2, 3]

    other_environment = _selection_inputs(
        "N", None, environment_id="ENV-LINUX-PINNED"
    )
    seal = build_campaign_selection_seal_before_decode(
        {
            "ENV-AUTHOR": [*values, third],
            "ENV-LINUX-PINNED": other_environment,
        },
        required_environment_ids=["ENV-AUTHOR", "ENV-LINUX-PINNED"],
        phase_id="R1",
        campaign_outcome_guard={
            "guard_epoch_id": "contract-test-guard-epoch",
            "checkpoint_sequence": 100,
            "log_head_sha256": "7" * 64,
            "scientific_intent_event_count": 3,
            "result_decode_event_count": 0,
            "oracle_join_event_count": 0,
            "human_outcome_read_event_count": 0,
            "decode_capability_released": False,
        },
        run_policy_sha256=_sha(RUN_POLICY),
        selector_sha256=_sha(RUNNER_SOURCE),
        selection_schema_sha256=_sha(SELECTION_SCHEMA),
        outcome_guard_policy_sha256="8" * 64,
    )
    assert _schema_errors(SELECTION_SCHEMA, seal) == []
    assert len(seal["environment_selections"][0]["input_attempts"]) == 3

    duplicate = copy.deepcopy(third)
    duplicate["attempt_record"]["attempt_number"] = 2
    with pytest.raises(RunnerContractError, match="unique ordinals"):
        _select([*values, duplicate])


def test_classification_does_not_receive_result_or_oracle_fields() -> None:
    attempt = _attempt("E", 1)
    classified = _classify(attempt)
    assert classified["verdict"]["status"] == RETRY_ELIGIBLE
    forbidden = {
        "decision",
        "primary_reason",
        "expected_decision",
        "oracle_row",
        "result_stdout",
        "result_stderr",
    }
    assert forbidden.isdisjoint(classified["observed_signals"])
    assert classified["boundaries"]["result_bytes_received_by_classifier"] is False
    assert classified["temporal_boundary"]["external_temporal_order_authenticated"] is False


def test_prestart_process_contradiction_is_schema_invalid_and_classifier_invalid() -> None:
    attempt = _attempt("E", 1)
    attempt["process"].update(
        {"spawned": True, "pid": 123, "exit_code": 0, "reaped": True}
    )
    assert _schema_errors(ATTEMPT_SCHEMA, attempt)
    classified = _classify(attempt)
    assert classified["verdict"]["status"] == INVALID_CLASSIFICATION
    assert "ATTEMPT_PROCESS_STATE_CONTRADICTION" in classified["verdict"][
        "reason_codes"
    ]
    assert classified["observed_process"]["spawned"] is True
    assert _schema_errors(CLASSIFICATION_SCHEMA, classified) == []


def test_exact_record_hashes_are_recomputed_before_classification_and_selection() -> None:
    attempt = _attempt("E", 1)
    classified = classify_infrastructure_before_decode(
        build_classifier_view(attempt),
        attempt_record_sha256="0" * 64,
        attempt_record_schema_sha256=_sha(ATTEMPT_SCHEMA),
        run_policy_sha256=_sha(RUN_POLICY),
        classifier_sha256=_sha(RUNNER_SOURCE),
        classification_schema_sha256=_sha(CLASSIFICATION_SCHEMA),
    )
    assert classified["verdict"]["status"] == INVALID_CLASSIFICATION
    assert "ATTEMPT_RECORD_HASH_MISMATCH" in classified["verdict"]["reason_codes"]
    assert _schema_errors(CLASSIFICATION_SCHEMA, classified) == []

    values = _selection_inputs("N", None)
    values[0]["attempt_record_sha256"] = "0" * 64
    with pytest.raises(RunnerContractError, match="exact bytes"):
        _select(values)


def test_rg006_receipt_rejects_source_inventory_toctou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location("rg006_receipt_runner", RG006_TEST_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = [{"path": "source.py", "bytes": 1, "sha256": "1" * 64}]
    after = [{"path": "source.py", "bytes": 1, "sha256": "2" * 64}]
    inventories = iter((before, after))
    monkeypatch.setattr(module, "source_inventory", lambda: next(inventories))
    monkeypatch.setattr(module, "verify_typed_policy_bindings", lambda: 15)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"52 passed in 0.01s\n",
            stderr=b"",
        ),
    )
    with pytest.raises(RuntimeError, match="changed during contract-test execution"):
        module.run()
