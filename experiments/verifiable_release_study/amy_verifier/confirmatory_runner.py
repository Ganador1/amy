"""Pre-decode attempt classification and process-isolation primitives.

This module deliberately cannot start a confirmatory R1 run.  Its executable
primitive accepts only ``contract_test_no_confirmatory_evidence`` so the
process, clock, output-capture, and attempt-selection contracts can be tested
before R0 is frozen.  A future registered adapter must bind the frozen inputs
and explicitly widen that gate; changing this byte is itself an R0 change.

The classifier and selector APIs receive metadata dictionaries, never result
bytes, oracle rows, or decoded verifier decisions.  This local API boundary
does not exclude reads by another process or prove outcome blindness.
"""

from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import re
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import rfc8785


CONTRACT_TEST_CLASSIFICATION = "contract_test_no_confirmatory_evidence"
SUPPORTED_RECORD_CLASSIFICATIONS = {
    CONTRACT_TEST_CLASSIFICATION,
    "confirmatory_R1",
    "external_reproduction",
}
RETRY_ELIGIBLE = "RETRY_ELIGIBLE"
NOT_RETRY_ELIGIBLE = "NOT_RETRY_ELIGIBLE"
INVALID_CLASSIFICATION = "INVALID_CLASSIFICATION"
INFRASTRUCTURE_PREDICATES = (
    "INFRA-JOB-NOT-STARTED",
    "INFRA-EXTERNAL-RUNNER-LOSS",
    "INFRA-PRELOCK-ACQUISITION-FAILURE",
    "INFRA-PREFLIGHT-STORAGE-FAILURE",
)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTENT_EVENT_NAME = re.compile(r"^intent-([0-9]{16})\.jcs\.json$")
_MAX_EINTR_RETRIES = 32
_INTENT_LOG_NAME = ".scientific-intent-log"


class RunnerContractError(ValueError):
    """Raised when a caller crosses a frozen runner boundary."""


@dataclass(frozen=True)
class ContinuousClock:
    clock_id: str
    resolution_ns: int
    now_ns: Callable[[], int]


_DARWIN_CLOCK: ContinuousClock | None = None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def continuous_clock() -> ContinuousClock:
    """Return a monotonic clock that includes host suspension, or fail closed."""

    global _DARWIN_CLOCK
    if sys.platform.startswith("linux"):
        clock_id = getattr(time, "CLOCK_BOOTTIME", None)
        if clock_id is None or not hasattr(time, "clock_gettime_ns"):
            raise RunnerContractError("Linux CLOCK_BOOTTIME is unavailable")
        resolution = max(1, int(time.clock_getres(clock_id) * 1_000_000_000))
        return ContinuousClock(
            "linux_CLOCK_BOOTTIME",
            resolution,
            lambda: time.clock_gettime_ns(clock_id),
        )

    if sys.platform == "darwin":
        if _DARWIN_CLOCK is not None:
            return _DARWIN_CLOCK

        class MachTimebaseInfo(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        continuous = library.mach_continuous_time
        continuous.argtypes = []
        continuous.restype = ctypes.c_uint64
        timebase = library.mach_timebase_info
        timebase.argtypes = [ctypes.POINTER(MachTimebaseInfo)]
        timebase.restype = ctypes.c_int
        info = MachTimebaseInfo()
        status = int(timebase(ctypes.byref(info)))
        if status != 0 or info.numer == 0 or info.denom == 0:
            raise RunnerContractError("mach_timebase_info failed")

        numerator = int(info.numer)
        denominator = int(info.denom)

        def now_ns() -> int:
            return int(continuous()) * numerator // denominator

        resolution = max(1, (numerator + denominator - 1) // denominator)
        _DARWIN_CLOCK = ContinuousClock(
            "darwin_mach_continuous_time", resolution, now_ns
        )
        return _DARWIN_CLOCK

    raise RunnerContractError(
        f"no registered suspend-aware monotonic clock for platform {sys.platform!r}"
    )


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    interruptions = 0
    while view:
        try:
            written = os.write(descriptor, view)
        except InterruptedError:
            interruptions += 1
            if interruptions > _MAX_EINTR_RETRIES:
                raise RunnerContractError("write interrupted too many times")
            continue
        if written <= 0:
            raise OSError("short write while sealing runner artifact")
        view = view[written:]


def _fsync(descriptor: int) -> None:
    interruptions = 0
    while True:
        try:
            os.fsync(descriptor)
            return
        except InterruptedError:
            interruptions += 1
            if interruptions > _MAX_EINTR_RETRIES:
                raise RunnerContractError("fsync interrupted too many times")
            continue


def _rename_noreplace_raw(directory_fd: int, source: str, destination: str) -> None:
    """Invoke the platform's atomic same-directory no-replace rename."""

    encoded_source = os.fsencode(source)
    encoded_destination = os.fsencode(destination)
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        renameatx_np = library.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        rename_excl = 0x00000004
        status = int(
            renameatx_np(
                directory_fd,
                encoded_source,
                directory_fd,
                encoded_destination,
                rename_excl,
            )
        )
    elif sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        if not hasattr(library, "renameat2"):
            raise RunnerContractError("Linux renameat2(RENAME_NOREPLACE) is required")
        renameat2 = library.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        rename_noreplace = 1
        status = int(
            renameat2(
                directory_fd,
                encoded_source,
                directory_fd,
                encoded_destination,
                rename_noreplace,
            )
        )
    else:
        raise RunnerContractError(
            f"no atomic no-replace rename registered for {sys.platform!r}"
        )
    if status != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def _rename_noreplace_at(directory_fd: int, source: str, destination: str) -> None:
    """Retry only EINTR around an atomic no-replace rename."""

    interruptions = 0
    while True:
        try:
            _rename_noreplace_raw(directory_fd, source, destination)
            return
        except InterruptedError:
            interruptions += 1
            if interruptions > _MAX_EINTR_RETRIES:
                raise RunnerContractError(
                    "no-replace rename interrupted too many times"
                )
            continue


def _open_existing_directory(path: Path) -> tuple[int, os.stat_result]:
    if not path.is_absolute():
        raise RunnerContractError(f"directory path must be absolute: {path}")
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise RunnerContractError(f"directory path is not normalized: {path}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise RunnerContractError("O_NOFOLLOW is required")
    flags |= os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise RunnerContractError(f"not a directory: {path}")
        return descriptor, opened
    except Exception:
        os.close(descriptor)
        raise


def _hash_regular_file(path: Path, *, max_bytes: int = 512 * 1024 * 1024) -> tuple[str, os.stat_result]:
    parent_fd, _ = _open_existing_directory(path.parent)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise RunnerContractError("executable is not a bounded regular file")
        digest = hashlib.sha256()
        observed = 0
        while True:
            try:
                chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - observed))
            except InterruptedError:
                continue
            if not chunk:
                break
            observed += len(chunk)
            if observed > max_bytes:
                raise RunnerContractError("executable exceeded hash byte limit")
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_nlink,
        )
        if identity(before) != identity(after) or observed != after.st_size:
            raise RunnerContractError("executable changed while hashing")
        return digest.hexdigest(), after
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _directory_identity(value: os.stat_result) -> dict[str, str]:
    return {
        "device_decimal": str(int(value.st_dev)),
        "inode_decimal": str(int(value.st_ino)),
        "mode_octal": format(stat.S_IMODE(value.st_mode), "04o"),
        "mtime_ns_decimal": str(int(value.st_mtime_ns)),
    }


def _command_commitments(
    argv: Sequence[str], environment: Mapping[str, str], cwd_stat: os.stat_result
) -> dict[str, str]:
    return {
        "argv_jcs_sha256": sha256_bytes(rfc8785.dumps(list(argv))),
        "environment_jcs_sha256": sha256_bytes(rfc8785.dumps(dict(environment))),
        "cwd_root_identity_jcs_sha256": sha256_bytes(
            rfc8785.dumps(_directory_identity(cwd_stat))
        ),
    }


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RunnerContractError(f"{label} SHA-256 is malformed")


def _wait_bounded(
    process: subprocess.Popen[bytes], timeout_seconds: float, label: str
) -> int:
    """Wait no longer than the caller-supplied interval or fail closed."""

    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RunnerContractError(f"{label} exceeded the bounded wait") from exc


def _verify_regular_file_at(
    directory_fd: int, name: str, *, expected_bytes: int, expected_sha256: str
) -> None:
    """Re-read a sealed regular file and verify its final retained bytes."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        opened = os.fstat(descriptor)
        entry_before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise RunnerContractError(f"retained artifact is not a closed file: {name}")
        if (opened.st_dev, opened.st_ino) != (entry_before.st_dev, entry_before.st_ino):
            raise RunnerContractError(f"retained artifact entry differs from opened file: {name}")
        digest = hashlib.sha256()
        observed = 0
        while True:
            try:
                chunk = os.read(descriptor, 1024 * 1024)
            except InterruptedError:
                continue
            if not chunk:
                break
            observed += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        entry_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise RunnerContractError(f"retained artifact changed while verifying: {name}")
        if (after.st_dev, after.st_ino) != (entry_after.st_dev, entry_after.st_ino):
            raise RunnerContractError(f"retained artifact entry changed while verifying: {name}")
        if observed != expected_bytes or digest.hexdigest() != expected_sha256:
            raise RunnerContractError(f"retained artifact differs from capture: {name}")
    finally:
        os.close(descriptor)


def validate_process_isolation_record(record: Mapping[str, Any]) -> list[str]:
    """Recompute cross-field invariants that JSON Schema cannot express."""

    errors: list[str] = []
    clock = record.get("clock") or {}
    process = record.get("process") or {}
    command = record.get("command") or {}
    scientific_intent = record.get("scientific_intent") or {}
    boundaries = record.get("boundaries") or {}
    try:
        started = clock["started_continuous_us"]
        ended = clock["ended_continuous_us"]
        elapsed = clock["elapsed_us"]
        timeout_limit = clock["timeout_limit_us"]
        if ended < started:
            errors.append("ended continuous time precedes start")
        if elapsed != ended - started:
            errors.append("elapsed time differs from end minus start")
        if clock["deadline_continuous_us"] != started + timeout_limit:
            errors.append("deadline differs from start plus timeout limit")
        reaped = clock["direct_child_reaped_continuous_us"]
        if not (started <= reaped <= ended):
            errors.append("direct-child reap time is outside the execution interval")
        event_flags = (
            ("sigterm_sent_continuous_us", "sigterm_sent"),
            ("sigkill_sent_continuous_us", "sigkill_sent"),
            ("capture_pipes_closed_continuous_us", "capture_pipes_forcibly_closed"),
        )
        for event_field, flag_field in event_flags:
            event = clock[event_field]
            flag = process[flag_field]
            if (event is None) == bool(flag):
                errors.append(f"{event_field} presence differs from {flag_field}")
            if event is not None and not (started <= event <= ended):
                errors.append(f"{event_field} is outside the execution interval")
        ordered_events = [
            value
            for value in (
                clock["sigterm_sent_continuous_us"],
                clock["sigkill_sent_continuous_us"],
                clock["capture_pipes_closed_continuous_us"],
                reaped,
            )
            if value is not None
        ]
        if ordered_events != sorted(ordered_events):
            errors.append("termination/reap events are not monotonic")
    except (KeyError, TypeError):
        errors.append("timing record is missing required typed fields")
    if clock.get("elapsed_equals_end_minus_start") is not True:
        errors.append("elapsed invariant marker is false")
    if clock.get("all_waits_bounded") is not True:
        errors.append("bounded-wait marker is false")
    if command.get("pre_spawn_commitments_verified") is not True:
        errors.append("pre-spawn commitment marker is false")
    for field in (
        "persisted_before_spawn",
        "log_revalidated_before_spawn",
        "advisory_append_lock_held_through_spawn",
    ):
        if scientific_intent.get(field) is not True:
            errors.append(f"scientific-intent marker is false: {field}")
    if scientific_intent.get("sequence", 0) < 1:
        errors.append("scientific-intent sequence is invalid")
    for field in ("event_sha256", "guard_epoch_id", "event_path"):
        if not scientific_intent.get(field):
            errors.append(f"scientific-intent identity is missing: {field}")
    if process.get("reaped") is not True:
        errors.append("direct child was not reaped")
    if any(
        item.get("final_bytes_reverified_by_runner") is not True
        for item in record.get("raw_artifacts") or []
    ):
        errors.append("one or more retained raw artifacts were not reverified")
    for field in (
        "same_uid_external_read_or_mutation_excluded",
        "outcome_blindness_established",
    ):
        if boundaries.get(field) is not False:
            errors.append(f"unsupported boundary claimed true: {field}")
    return errors


def _atomic_write_new_at(directory_fd: int, name: str, raw: bytes) -> None:
    if not _SAFE_NAME.fullmatch(name):
        raise RunnerContractError(f"unsafe artifact name: {name!r}")
    temporary = f".{name}.tmp-{os.getpid()}-{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
    created = os.fstat(descriptor)
    published = False
    try:
        _write_all(descriptor, raw)
        _fsync(descriptor)
        _rename_noreplace_at(directory_fd, temporary, name)
        published = True
        _fsync(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        # A failed pre-publication attempt deliberately leaves its uniquely
        # named temporary behind.  Removing by pathname would let a concurrent
        # same-UID process substitute an unrelated file before cleanup.  A
        # future recovery scanner may quarantine only identity-checked debris.
        # Never unlink ``name`` after publication or on ambiguous failure.
    if not published:
        raise RunnerContractError("atomic publication did not complete")
    final_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    final_descriptor = os.open(name, final_flags, dir_fd=directory_fd)
    try:
        final_stat = os.fstat(final_descriptor)
        entry_before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(final_stat.st_mode)
            or final_stat.st_nlink != 1
            or final_stat.st_size != len(raw)
            or (final_stat.st_dev, final_stat.st_ino) != (created.st_dev, created.st_ino)
            or (entry_before.st_dev, entry_before.st_ino)
            != (final_stat.st_dev, final_stat.st_ino)
        ):
            raise RunnerContractError("published artifact identity is not closed")
        digest = hashlib.sha256()
        while True:
            try:
                chunk = os.read(final_descriptor, 1024 * 1024)
            except InterruptedError:
                continue
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != sha256_bytes(raw):
            raise RunnerContractError("published artifact bytes changed during sealing")
        entry_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        after = os.fstat(final_descriptor)
        if (entry_after.st_dev, entry_after.st_ino) != (after.st_dev, after.st_ino):
            raise RunnerContractError("published artifact entry changed during sealing")
    finally:
        os.close(final_descriptor)


def write_new_jcs(path: Path, value: Any) -> dict[str, Any]:
    """Durably create one canonical JSON file without replacing prior bytes."""

    raw = rfc8785.dumps(value)
    parent_fd, _ = _open_existing_directory(path.parent)
    try:
        _atomic_write_new_at(parent_fd, path.name, raw)
    finally:
        os.close(parent_fd)
    return {"path": path.as_posix(), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def _strict_json(raw: bytes, *, label: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RunnerContractError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RunnerContractError(f"{label} contains non-standard number {value}")
            ),
        )
    except RunnerContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerContractError(f"{label} is not strict JSON") from exc


def _intent_boundaries() -> dict[str, bool]:
    return {
        "local_file_and_directory_fsync_completed_before_spawn": True,
        "advisory_append_lock_held_through_spawn": True,
        "same_uid_tamper_excluded": False,
        "rollback_detection_established": False,
        "external_time_order_established": False,
        "power_loss_durability_established": False,
        "confirmatory_execution_permitted": False,
    }


def _validate_scientific_intent_event(event: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(event, dict):
        return ["event is not an object"]
    expected_keys = {
        "schema_version",
        "classification",
        "event_type",
        "guard_epoch_id",
        "sequence",
        "parent_event_sha256",
        "spawn_id",
        "command",
        "boundaries",
    }
    if set(event) != expected_keys:
        errors.append("event fields are not closed")
    if event.get("schema_version") != "amy.scientific-intent-event.v1-draft":
        errors.append("event schema version differs")
    if event.get("classification") != CONTRACT_TEST_CLASSIFICATION:
        errors.append("event classification differs")
    if event.get("event_type") != "SCIENTIFIC_INTENT":
        errors.append("event type differs")
    for field in ("guard_epoch_id", "spawn_id"):
        value = event.get(field)
        if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value):
            errors.append(f"unsafe {field}")
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not (1 <= sequence <= 10**12):
        errors.append("event sequence is outside the closed range")
    parent = event.get("parent_event_sha256")
    if parent is not None and (
        not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{64}", parent) is None
    ):
        errors.append("parent event SHA-256 is invalid")
    command = event.get("command")
    command_keys = {
        "argv_jcs_sha256",
        "executable_sha256",
        "environment_jcs_sha256",
        "cwd_root_identity_jcs_sha256",
        "output_name",
    }
    if not isinstance(command, dict) or set(command) != command_keys:
        errors.append("event command fields are not closed")
    else:
        for field in command_keys - {"output_name"}:
            value = command.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                errors.append(f"event command {field} is invalid")
        if command.get("output_name") != event.get("spawn_id"):
            errors.append("event command output_name differs from spawn_id")
    if event.get("boundaries") != _intent_boundaries():
        errors.append("event boundaries differ")
    return errors


def _read_regular_file_at(directory_fd: int, name: str, *, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(descriptor)
        entry_before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > max_bytes
            or (before.st_dev, before.st_ino) != (entry_before.st_dev, entry_before.st_ino)
        ):
            raise RunnerContractError(f"intent-log entry {name!r} is not closed")
        chunks: list[bytes] = []
        total = 0
        interruptions = 0
        while True:
            try:
                chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
            except InterruptedError:
                interruptions += 1
                if interruptions > _MAX_EINTR_RETRIES:
                    raise RunnerContractError("persistent EINTR while reading intent log")
                continue
            interruptions = 0
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RunnerContractError(f"intent-log entry {name!r} exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        entry_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (after.st_dev, after.st_ino) != (entry_after.st_dev, entry_after.st_ino)
        ):
            raise RunnerContractError(f"intent-log entry {name!r} changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _scan_scientific_intent_log_at(
    directory_fd: int, *, expected_guard_epoch_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise RunnerContractError("cannot enumerate scientific-intent log") from exc
    parsed: list[tuple[int, str]] = []
    for name in names:
        match = _INTENT_EVENT_NAME.fullmatch(name)
        if match is None:
            raise RunnerContractError(f"ambiguous scientific-intent log entry: {name!r}")
        parsed.append((int(match.group(1)), name))
    parsed.sort()
    expected_sequences = list(range(1, len(parsed) + 1))
    if [sequence for sequence, _ in parsed] != expected_sequences:
        raise RunnerContractError("scientific-intent log contains a gap or duplicate sequence")
    events: list[dict[str, Any]] = []
    parent: str | None = None
    spawn_ids: set[str] = set()
    for sequence, name in parsed:
        raw = _read_regular_file_at(directory_fd, name, max_bytes=64 * 1024)
        event = _strict_json(raw, label=f"scientific-intent event {name}")
        if rfc8785.dumps(event) != raw:
            raise RunnerContractError(f"scientific-intent event {name!r} is not canonical JCS")
        errors = _validate_scientific_intent_event(event)
        if errors:
            raise RunnerContractError("invalid scientific-intent event: " + "; ".join(errors))
        if event["sequence"] != sequence:
            raise RunnerContractError("scientific-intent filename/sequence mismatch")
        if event["guard_epoch_id"] != expected_guard_epoch_id:
            raise RunnerContractError("scientific-intent guard epoch differs")
        if event["parent_event_sha256"] != parent:
            raise RunnerContractError("scientific-intent parent chain differs")
        if event["spawn_id"] in spawn_ids:
            raise RunnerContractError("scientific-intent spawn_id is duplicated")
        spawn_ids.add(event["spawn_id"])
        parent = sha256_bytes(raw)
        events.append(event)
    return events, parent


def inspect_scientific_intent_log(path: Path) -> dict[str, Any]:
    """Reconstruct one local intent chain; this is not external authentication."""

    directory_fd, directory_stat = _open_existing_directory(path)
    try:
        guard_epoch_id = "contract-test-" + sha256_bytes(
            rfc8785.dumps({"device": directory_stat.st_dev, "inode": directory_stat.st_ino})
        )[:32]
        events, head = _scan_scientific_intent_log_at(
            directory_fd, expected_guard_epoch_id=guard_epoch_id
        )
        return {
            "guard_epoch_id": guard_epoch_id,
            "event_count": len(events),
            "head_sha256": head,
            "spawn_ids": [event["spawn_id"] for event in events],
        }
    finally:
        os.close(directory_fd)


def _open_scientific_intent_log(output_parent: Path) -> tuple[int, str]:
    parent_fd, _ = _open_existing_directory(output_parent)
    try:
        try:
            os.mkdir(_INTENT_LOG_NAME, 0o700, dir_fd=parent_fd)
            _fsync(parent_fd)
        except FileExistsError:
            pass
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | os.O_NOFOLLOW
        )
        directory_fd = os.open(_INTENT_LOG_NAME, flags, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    directory_stat = os.fstat(directory_fd)
    guard_epoch_id = "contract-test-" + sha256_bytes(
        rfc8785.dumps({"device": directory_stat.st_dev, "inode": directory_stat.st_ino})
    )[:32]
    return directory_fd, guard_epoch_id


def _append_scientific_intent_at(
    directory_fd: int,
    *,
    guard_epoch_id: str,
    spawn_id: str,
    executable_sha256: str,
    command_commitments: Mapping[str, str],
) -> dict[str, Any]:
    events, parent = _scan_scientific_intent_log_at(
        directory_fd, expected_guard_epoch_id=guard_epoch_id
    )
    if spawn_id in {event["spawn_id"] for event in events}:
        raise RunnerContractError("scientific intent already exists for this spawn_id")
    sequence = len(events) + 1
    event = {
        "schema_version": "amy.scientific-intent-event.v1-draft",
        "classification": CONTRACT_TEST_CLASSIFICATION,
        "event_type": "SCIENTIFIC_INTENT",
        "guard_epoch_id": guard_epoch_id,
        "sequence": sequence,
        "parent_event_sha256": parent,
        "spawn_id": spawn_id,
        "command": {
            "argv_jcs_sha256": command_commitments["argv_jcs_sha256"],
            "executable_sha256": executable_sha256,
            "environment_jcs_sha256": command_commitments["environment_jcs_sha256"],
            "cwd_root_identity_jcs_sha256": command_commitments[
                "cwd_root_identity_jcs_sha256"
            ],
            "output_name": spawn_id,
        },
        "boundaries": _intent_boundaries(),
    }
    errors = _validate_scientific_intent_event(event)
    if errors:
        raise RunnerContractError("invalid generated scientific intent: " + "; ".join(errors))
    raw = rfc8785.dumps(event)
    event_sha256 = sha256_bytes(raw)
    name = f"intent-{sequence:016d}.jcs.json"
    _atomic_write_new_at(directory_fd, name, raw)
    reloaded, head = _scan_scientific_intent_log_at(
        directory_fd, expected_guard_epoch_id=guard_epoch_id
    )
    if len(reloaded) != sequence or head != event_sha256 or reloaded[-1] != event:
        raise RunnerContractError("scientific-intent log changed before spawn")
    return {
        "log_path": _INTENT_LOG_NAME,
        "event_path": f"{_INTENT_LOG_NAME}/{name}",
        "guard_epoch_id": guard_epoch_id,
        "sequence": sequence,
        "event_sha256": event_sha256,
        "parent_event_sha256": parent,
        "persisted_before_spawn": True,
        "log_revalidated_before_spawn": True,
        "advisory_append_lock_held_through_spawn": True,
    }


def _validate_command(
    argv: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    expected_executable_sha256: str,
    expected_argv_jcs_sha256: str,
    expected_environment_jcs_sha256: str,
    expected_cwd_root_identity_jcs_sha256: str,
) -> tuple[list[str], dict[str, str], os.stat_result, str, dict[str, str]]:
    if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise RunnerContractError("argv must be a nonempty sequence of nonempty strings")
    executable = Path(argv[0])
    if not executable.is_absolute():
        raise RunnerContractError("argv[0] must be an absolute executable path")
    _require_sha256(expected_executable_sha256, "expected executable")
    _require_sha256(expected_argv_jcs_sha256, "expected argv JCS")
    _require_sha256(expected_environment_jcs_sha256, "expected environment JCS")
    _require_sha256(
        expected_cwd_root_identity_jcs_sha256, "expected cwd-root identity JCS"
    )
    executable_sha256, executable_stat = _hash_regular_file(executable)
    if executable_sha256 != expected_executable_sha256:
        raise RunnerContractError("executable SHA-256 differs from the registered value")
    if not os.access(executable, os.X_OK):
        raise RunnerContractError("argv[0] is not executable")
    # The validation descriptor is intentionally closed before spawn.  The
    # frozen image/no-writer boundary, not this check, must prevent cwd races.
    validation_fd, cwd_stat = _open_existing_directory(cwd)
    os.close(validation_fd)
    normalized_environment: dict[str, str] = {}
    for key, value in environment.items():
        if not isinstance(key, str) or not _SAFE_ENV_NAME.fullmatch(key):
            raise RunnerContractError(f"unsafe environment name: {key!r}")
        if not isinstance(value, str) or "\x00" in value:
            raise RunnerContractError(f"unsafe environment value for {key}")
        normalized_environment[key] = value
    normalized_argv = list(argv)
    commitments = _command_commitments(normalized_argv, normalized_environment, cwd_stat)
    expected_commitments = {
        "argv_jcs_sha256": expected_argv_jcs_sha256,
        "environment_jcs_sha256": expected_environment_jcs_sha256,
        "cwd_root_identity_jcs_sha256": expected_cwd_root_identity_jcs_sha256,
    }
    for field, expected in expected_commitments.items():
        if commitments[field] != expected:
            raise RunnerContractError(f"{field} differs from the registered commitment")
    return normalized_argv, normalized_environment, cwd_stat, executable_sha256, commitments


def _signal_process_group(process: subprocess.Popen[bytes], member: signal.Signals) -> bool:
    try:
        os.killpg(process.pid, member)
        return True
    except ProcessLookupError:
        return False


def run_contract_test_process(
    *,
    classification: str,
    argv: Sequence[str],
    expected_executable_sha256: str,
    expected_argv_jcs_sha256: str,
    expected_environment_jcs_sha256: str,
    expected_cwd_root_identity_jcs_sha256: str,
    cwd: Path,
    environment: Mapping[str, str],
    output_parent: Path,
    output_name: str,
    timeout_seconds: float,
    termination_grace_seconds: float,
    reap_timeout_seconds: float,
    max_output_bytes_per_stream: int,
    max_total_output_bytes: int,
) -> dict[str, Any]:
    """Run one nonconfirmatory command without decoding its output bytes."""

    if classification != CONTRACT_TEST_CLASSIFICATION:
        raise RunnerContractError(
            "confirmatory execution is disabled until a newly frozen adapter is registered"
        )
    if not _SAFE_NAME.fullmatch(output_name):
        raise RunnerContractError("unsafe output directory name")
    if not (0 < timeout_seconds <= 60):
        raise RunnerContractError("contract-test timeout must be in (0, 60] seconds")
    if not (0 < termination_grace_seconds <= 10):
        raise RunnerContractError("termination grace must be in (0, 10] seconds")
    if not (0 < reap_timeout_seconds <= 10):
        raise RunnerContractError("reap timeout must be in (0, 10] seconds")
    if not (0 < max_output_bytes_per_stream <= 16 * 1024 * 1024):
        raise RunnerContractError("contract-test output limit is outside the closed range")
    if not (
        max_output_bytes_per_stream
        <= max_total_output_bytes
        <= 2 * max_output_bytes_per_stream
    ):
        raise RunnerContractError("aggregate output limit is outside the closed range")

    (
        normalized_argv,
        normalized_environment,
        cwd_before,
        executable_sha256,
        command_commitments,
    ) = _validate_command(
        argv,
        cwd,
        environment,
        expected_executable_sha256,
        expected_argv_jcs_sha256,
        expected_environment_jcs_sha256,
        expected_cwd_root_identity_jcs_sha256,
    )
    parent_fd, _ = _open_existing_directory(output_parent)
    try:
        os.mkdir(output_name, 0o700, dir_fd=parent_fd)
        _fsync(parent_fd)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | os.O_NOFOLLOW
        )
        output_fd = os.open(output_name, directory_flags, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    output = output_parent / output_name
    stdout_fd = stderr_fd = -1
    scientific_intent: dict[str, Any] | None = None
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    clock = continuous_clock()
    started_wall = utc_now()
    started_ns = clock.now_ns()
    timeout_triggered = False
    output_limit_exceeded = False
    sigterm_sent = False
    sigkill_sent = False
    capture_pipes_forcibly_closed = False
    sigterm_sent_ns: int | None = None
    sigkill_sent_ns: int | None = None
    capture_pipes_closed_ns: int | None = None
    reaped_ns: int | None = None
    stream_state: dict[str, dict[str, Any]] = {
        "stdout": {"captured": 0, "observed": 0, "digest": hashlib.sha256(), "truncated": False},
        "stderr": {"captured": 0, "observed": 0, "digest": hashlib.sha256(), "truncated": False},
    }
    try:
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        file_flags |= os.O_NOFOLLOW
        stdout_fd = os.open("stdout.raw", file_flags, 0o600, dir_fd=output_fd)
        stderr_fd = os.open("stderr.raw", file_flags, 0o600, dir_fd=output_fd)
        intent_fd, guard_epoch_id = _open_scientific_intent_log(output_parent)
        lock_acquired = False
        try:
            try:
                fcntl.flock(intent_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except BlockingIOError as exc:
                raise RunnerContractError(
                    "scientific-intent log is already locked by another spawn"
                ) from exc
            scientific_intent = _append_scientific_intent_at(
                intent_fd,
                guard_epoch_id=guard_epoch_id,
                spawn_id=output_name,
                executable_sha256=executable_sha256,
                command_commitments=command_commitments,
            )
            process = subprocess.Popen(
                normalized_argv,
                cwd=cwd,
                env=normalized_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                pass_fds=(),
                start_new_session=True,
                umask=0o077,
                text=False,
            )
        finally:
            if lock_acquired:
                fcntl.flock(intent_fd, fcntl.LOCK_UN)
            os.close(intent_fd)
        assert process.stdout is not None and process.stderr is not None
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)

        deadline_ns = started_ns + int(timeout_seconds * 1_000_000_000)
        terminate_deadline_ns: int | None = None
        capture_force_close_deadline_ns: int | None = None
        while selector.get_map() or process.poll() is None:
            now_ns = clock.now_ns()
            if not timeout_triggered and now_ns >= deadline_ns:
                timeout_triggered = True
                sigterm_sent = _signal_process_group(process, signal.SIGTERM)
                if sigterm_sent:
                    sigterm_sent_ns = now_ns
                terminate_deadline_ns = now_ns + int(
                    termination_grace_seconds * 1_000_000_000
                )
            if (
                terminate_deadline_ns is not None
                and now_ns >= terminate_deadline_ns
            ):
                sigkill_sent = (
                    _signal_process_group(process, signal.SIGKILL) or sigkill_sent
                )
                if sigkill_sent and sigkill_sent_ns is None:
                    sigkill_sent_ns = now_ns
                terminate_deadline_ns = None
                capture_force_close_deadline_ns = now_ns + int(
                    termination_grace_seconds * 1_000_000_000
                )
            if (
                capture_force_close_deadline_ns is not None
                and now_ns >= capture_force_close_deadline_ns
            ):
                open_streams = list(selector.get_map().values())
                capture_pipes_forcibly_closed = bool(open_streams)
                if capture_pipes_forcibly_closed:
                    capture_pipes_closed_ns = now_ns
                for key in open_streams:
                    stream = key.fileobj
                    selector.unregister(stream)
                    stream.close()
                _signal_process_group(process, signal.SIGKILL)
                break

            events = selector.select(timeout=0.02)
            for key, _ in events:
                stream = key.fileobj
                name = key.data
                try:
                    chunk = os.read(stream.fileno(), 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                state = stream_state[name]
                state["observed"] += len(chunk)
                stream_remaining = max_output_bytes_per_stream - state["captured"]
                total_captured = sum(item["captured"] for item in stream_state.values())
                total_remaining = max_total_output_bytes - total_captured
                retained = chunk[: max(0, min(stream_remaining, total_remaining))]
                if retained:
                    target = stdout_fd if name == "stdout" else stderr_fd
                    _write_all(target, retained)
                    state["digest"].update(retained)
                    state["captured"] += len(retained)
                if len(retained) != len(chunk):
                    state["truncated"] = True
                    output_limit_exceeded = True
                    if (
                        terminate_deadline_ns is None
                        and capture_force_close_deadline_ns is None
                    ):
                        signal_ns = clock.now_ns()
                        signal_delivered = _signal_process_group(
                            process, signal.SIGTERM
                        )
                        sigterm_sent = signal_delivered or sigterm_sent
                        if signal_delivered and sigterm_sent_ns is None:
                            sigterm_sent_ns = signal_ns
                        terminate_deadline_ns = signal_ns + int(
                            termination_grace_seconds * 1_000_000_000
                        )

        try:
            return_code = _wait_bounded(process, reap_timeout_seconds, "direct-child reap")
        except RunnerContractError:
            now_ns = clock.now_ns()
            sigkill_sent = _signal_process_group(process, signal.SIGKILL) or sigkill_sent
            if sigkill_sent and sigkill_sent_ns is None:
                sigkill_sent_ns = now_ns
            return_code = _wait_bounded(
                process, reap_timeout_seconds, "direct-child reap after SIGKILL"
            )
        reaped_ns = clock.now_ns()
        # A process that deliberately leaves descendants behind cannot keep
        # the session alive.  This is process-group cleanup, not a sandbox: a
        # malicious descendant can still create a new session.
        _signal_process_group(process, signal.SIGTERM)
        ended_ns = clock.now_ns()
        ended_wall = utc_now()
        _fsync(stdout_fd)
        _fsync(stderr_fd)
        os.fchmod(stdout_fd, 0o400)
        os.fchmod(stderr_fd, 0o400)
        _fsync(stdout_fd)
        _fsync(stderr_fd)
        os.close(stdout_fd)
        stdout_fd = -1
        os.close(stderr_fd)
        stderr_fd = -1
        _fsync(output_fd)
        for name, state in stream_state.items():
            _verify_regular_file_at(
                output_fd,
                f"{name}.raw",
                expected_bytes=state["captured"],
                expected_sha256=state["digest"].hexdigest(),
            )
        cwd_after_fd, cwd_after = _open_existing_directory(cwd)
        os.close(cwd_after_fd)
        if (
            cwd_after.st_dev,
            cwd_after.st_ino,
            cwd_after.st_mode,
            cwd_after.st_mtime_ns,
        ) != (
            cwd_before.st_dev,
            cwd_before.st_ino,
            cwd_before.st_mode,
            cwd_before.st_mtime_ns,
        ):
            raise RunnerContractError("working directory identity changed during process")
        executable_after_sha256, _ = _hash_regular_file(Path(normalized_argv[0]))
        if executable_after_sha256 != executable_sha256:
            raise RunnerContractError("executable identity changed during process")

        exit_code = return_code if return_code >= 0 else None
        exit_signal = -return_code if return_code < 0 else None
        started_us = started_ns // 1_000
        ended_us = ended_ns // 1_000
        deadline_us = deadline_ns // 1_000
        record = {
            "schema_version": "amy.process-isolation-record.v1-draft",
            "classification": classification,
            "clock": {
                "clock_id": clock.clock_id,
                "resolution_ns": clock.resolution_ns,
                "started_continuous_us": started_us,
                "ended_continuous_us": ended_us,
                "elapsed_us": ended_us - started_us,
                "deadline_continuous_us": deadline_us,
                "timeout_limit_us": int(timeout_seconds * 1_000_000),
                "termination_grace_limit_us": int(
                    termination_grace_seconds * 1_000_000
                ),
                "reap_limit_us": int(reap_timeout_seconds * 1_000_000),
                "sigterm_sent_continuous_us": (
                    sigterm_sent_ns // 1_000 if sigterm_sent_ns is not None else None
                ),
                "sigkill_sent_continuous_us": (
                    sigkill_sent_ns // 1_000 if sigkill_sent_ns is not None else None
                ),
                "capture_pipes_closed_continuous_us": (
                    capture_pipes_closed_ns // 1_000
                    if capture_pipes_closed_ns is not None
                    else None
                ),
                "direct_child_reaped_continuous_us": (
                    reaped_ns // 1_000 if reaped_ns is not None else None
                ),
                "elapsed_equals_end_minus_start": True,
                "all_waits_bounded": True,
                "started_wall_utc": started_wall,
                "ended_wall_utc": ended_wall,
            },
            "command": {
                "argv_jcs_sha256": command_commitments["argv_jcs_sha256"],
                "executable_sha256": executable_sha256,
                "environment_jcs_sha256": command_commitments[
                    "environment_jcs_sha256"
                ],
                "cwd_root_identity_jcs_sha256": command_commitments[
                    "cwd_root_identity_jcs_sha256"
                ],
                "pre_spawn_commitments_verified": True,
            },
            "scientific_intent": scientific_intent,
            "isolation": {
                "shell_used": False,
                "start_new_session": True,
                "close_fds": True,
                "stdin_devnull": True,
                "pass_fds_empty": True,
                "umask_077": True,
                "network_isolation_verified_by_runner": False,
                "filesystem_sandbox_verified_by_runner": False,
                "process_tree_containment_verified_by_runner": False,
                "transitive_cwd_snapshot_verified_by_runner": False,
            },
            "process": {
                "spawned": True,
                "pid": process.pid,
                "exit_code": exit_code,
                "exit_signal": exit_signal,
                "timeout_triggered": timeout_triggered,
                "output_limit_exceeded": output_limit_exceeded,
                "sigterm_sent": sigterm_sent,
                "sigkill_sent": sigkill_sent,
                "capture_pipes_forcibly_closed": capture_pipes_forcibly_closed,
                "reaped": process.poll() is not None,
            },
            "raw_artifacts": [
                {
                    "path": f"{output_name}/{name}.raw",
                    "role": name,
                    "observed_bytes": state["observed"],
                    "captured_bytes": state["captured"],
                    "sha256": state["digest"].hexdigest(),
                    "truncated": state["truncated"],
                    "decoded_by_runner": False,
                    "final_bytes_reverified_by_runner": True,
                }
                for name, state in stream_state.items()
            ],
            "boundaries": {
                "confirmatory_execution_permitted": False,
                "confirmatory_outcomes_read": False,
                "result_bytes_decoded": False,
                "oracle_read": False,
                "independent_review_performed": False,
                "same_uid_external_read_or_mutation_excluded": False,
                "outcome_blindness_established": False,
            },
        }
        semantic_errors = validate_process_isolation_record(record)
        if semantic_errors:
            raise RunnerContractError(
                "invalid process-isolation receipt: " + "; ".join(semantic_errors)
            )
        metadata_raw = rfc8785.dumps(record)
        _atomic_write_new_at(output_fd, "process-metadata.jcs.json", metadata_raw)
        metadata = {
            "path": (output / "process-metadata.jcs.json").as_posix(),
            "bytes": len(metadata_raw),
            "sha256": sha256_bytes(metadata_raw),
        }
        return {"record": record, "record_file": metadata}
    finally:
        selector.close()
        for descriptor in (stdout_fd, stderr_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if process is not None and process.poll() is None:
            _signal_process_group(process, signal.SIGKILL)
            try:
                _wait_bounded(process, reap_timeout_seconds, "finally cleanup reap")
            except RunnerContractError:
                # The function has no process-tree containment authority.  Do
                # not turn cleanup into an unbounded wait or claim success.
                pass
        os.close(output_fd)


def build_classifier_view(attempt: Mapping[str, Any]) -> dict[str, Any]:
    """Project an attempt to the only fields the classifier may receive."""

    return {
        "schema_version": "amy.infrastructure-classifier-view.v1-draft",
        "classification": attempt["classification"],
        "attempt_id": attempt["attempt_id"],
        "environment_id": attempt["environment_id"],
        "attempt_number": attempt["attempt_number"],
        "attempt_state": attempt["attempt_state"],
        "attempt_record_jcs_sha256": sha256_bytes(rfc8785.dumps(attempt)),
        "clock": dict(attempt["clock"]),
        "attempt_two_authorization": dict(attempt["attempt_two_authorization"]),
        "process": dict(attempt["process"]),
        "signals": dict(attempt["signals"]),
        "outcome_guard": dict(attempt["outcome_guard"]),
    }


def _classification_guards(classifier_view: Mapping[str, Any]) -> list[str]:
    signals = classifier_view["signals"]
    process = classifier_view["process"]
    guard = classifier_view["outcome_guard"]
    failures: list[str] = []
    if signals["outcomes_exposed_to_selection_process"]:
        failures.append("OUTCOMES_EXPOSED_BEFORE_SELECTION")
    if signals["result_bytes_decoded_before_selection"]:
        failures.append("RESULT_BYTES_DECODED_BEFORE_SELECTION")
    if signals["oracle_join_performed_before_selection"]:
        failures.append("ORACLE_JOINED_BEFORE_SELECTION")
    if guard["scientific_intent_event_count"] != signals["scientific_intent_event_count"]:
        failures.append("SCIENTIFIC_INTENT_COUNT_MISMATCH")
    if guard["result_decode_event_count"] != 0:
        failures.append("GUARD_RECORDED_RESULT_DECODE")
    if guard["oracle_join_event_count"] != 0:
        failures.append("GUARD_RECORDED_ORACLE_JOIN")
    if guard["human_outcome_read_event_count"] != 0:
        failures.append("GUARD_RECORDED_HUMAN_OUTCOME_READ")
    if guard["decode_capability_released"]:
        failures.append("DECODE_CAPABILITY_RELEASED_BEFORE_SELECTION")
    if classifier_view["attempt_state"] == "PRESTART_ABORTED" and (
        process["spawned"]
        or process["pid"] is not None
        or process["exit_code"] is not None
        or process["exit_signal"] is not None
        or process["reaped"]
        or signals["run_started_marker"]
        or signals["case_execution_started"]
        or signals["run_completed_marker"]
        or signals["scientific_intent_event_count"] != 0
        or signals["terminal_scientific_event_count"] != 0
    ):
        failures.append("ATTEMPT_PROCESS_STATE_CONTRADICTION")
    return failures


def classify_infrastructure_before_decode(
    classifier_view: Mapping[str, Any],
    *,
    attempt_record_sha256: str,
    attempt_record_schema_sha256: str,
    run_policy_sha256: str,
    classifier_sha256: str,
    classification_schema_sha256: str,
) -> dict[str, Any]:
    """Classify one attempt using only the closed pre-decode metadata shape."""

    classification = classifier_view["classification"]
    if classification not in SUPPORTED_RECORD_CLASSIFICATIONS:
        raise RunnerContractError("unsupported attempt classification")
    signals = classifier_view["signals"]
    guard_failures = _classification_guards(classifier_view)
    if classifier_view["attempt_record_jcs_sha256"] != attempt_record_sha256:
        guard_failures.append("ATTEMPT_RECORD_HASH_MISMATCH")
    clock = continuous_clock()
    classified_us = clock.now_ns() // 1_000
    attempt_clock = classifier_view["clock"]
    if attempt_clock["clock_id"] != clock.clock_id:
        guard_failures.append("CLASSIFICATION_CLOCK_ID_MISMATCH")
    if classified_us < attempt_clock["ended_continuous_us"]:
        guard_failures.append("CLASSIFICATION_CLOCK_PRECEDES_ATTEMPT_END")
    predicate_matches: list[str] = []

    zero_start = (
        classifier_view["attempt_state"] == "PRESTART_ABORTED"
        and not signals["run_started_marker"]
        and not signals["case_execution_started"]
        and signals["scientific_intent_event_count"] == 0
        and signals["terminal_scientific_event_count"] == 0
    )
    if not guard_failures and zero_start:
        if signals["provider_job_state"] in {"not_scheduled", "runner_unavailable"}:
            predicate_matches.append("INFRA-JOB-NOT-STARTED")
        if (
            signals["provider_job_state"] in {"runner_lost", "provider_cancelled"}
            and signals["external_cancellation_actor"] == "provider"
            and signals["host_heartbeat_state"] == "lost"
            and not signals["operator_cancellation_requested"]
        ):
            predicate_matches.append("INFRA-EXTERNAL-RUNNER-LOSS")
        if (
            signals["input_acquisition_status"] == "failed"
            and not signals["input_lock_completed"]
            and not signals["input_hash_mismatch"]
        ):
            predicate_matches.append("INFRA-PRELOCK-ACQUISITION-FAILURE")
        if signals["preflight_storage_probe"] == "failed":
            predicate_matches.append("INFRA-PREFLIGHT-STORAGE-FAILURE")

    if guard_failures:
        status = INVALID_CLASSIFICATION
        predicate_id = None
        permitted = False
        reason_codes = guard_failures
    elif len(predicate_matches) > 1:
        status = INVALID_CLASSIFICATION
        predicate_id = None
        permitted = False
        reason_codes = ["AMBIGUOUS_INFRASTRUCTURE_PREDICATES"]
    elif len(predicate_matches) == 1:
        status = RETRY_ELIGIBLE
        predicate_id = predicate_matches[0]
        permitted = True
        reason_codes = ["EXACTLY_ONE_PRESTART_PREDICATE_MATCHED"]
    else:
        status = NOT_RETRY_ELIGIBLE
        predicate_id = None
        permitted = False
        if signals["operator_cancellation_requested"]:
            reason_codes = ["OPERATOR_CANCELLATION_NONRETRYABLE"]
        elif signals["input_hash_mismatch"]:
            reason_codes = ["INPUT_HASH_MISMATCH_NONRETRYABLE"]
        elif signals["case_execution_started"] or signals["run_started_marker"]:
            reason_codes = ["SCIENTIFIC_EXECUTION_STARTED_NONRETRYABLE"]
        elif signals["terminal_scientific_event_count"]:
            reason_codes = ["TERMINAL_SCIENTIFIC_EVENT_NONRETRYABLE"]
        else:
            reason_codes = ["NO_ELIGIBLE_PRESTART_PREDICATE"]

    return {
        "schema_version": "amy.infrastructure-classification.v1-draft",
        "classification": classification,
        "attempt_id": classifier_view["attempt_id"],
        "environment_id": classifier_view["environment_id"],
        "attempt_number": classifier_view["attempt_number"],
        "bindings": {
            "attempt_record_sha256": attempt_record_sha256,
            "attempt_record_schema_sha256": attempt_record_schema_sha256,
            "run_policy_sha256": run_policy_sha256,
            "classifier_sha256": classifier_sha256,
            "classification_schema_sha256": classification_schema_sha256,
            "classifier_view_sha256": sha256_bytes(rfc8785.dumps(classifier_view)),
        },
        "temporal_boundary": {
            "clock_id": clock.clock_id,
            "attempt_ended_continuous_us": attempt_clock["ended_continuous_us"],
            "classified_continuous_us": classified_us,
            "classified_wall_utc": utc_now(),
            "classification_record_must_be_persisted_before_attempt_two": True,
            "external_temporal_order_authenticated": False,
            "external_temporal_order_attestation_sha256": None,
        },
        "observed_signals": dict(signals),
        "observed_process": dict(classifier_view["process"]),
        "outcome_guard": dict(classifier_view["outcome_guard"]),
        "verdict": {
            "status": status,
            "predicate_id": predicate_id,
            "complete_environment_rerun_permitted": permitted,
            "reason_codes": reason_codes,
        },
        "boundaries": {
            "attempt_record_finalized_before_classification": True,
            "result_bytes_received_by_classifier": False,
            "result_bytes_decoded_by_classifier": False,
            "oracle_received_by_classifier": False,
            "decision_fields_received_by_classifier": False,
            # This is only the result of the local API/counter guard.  The
            # limitations below explicitly leave external access unexcluded,
            # and the campaign seal cannot treat this as authenticated order.
            "classification_finished_before_result_decode": not guard_failures,
        },
        "limitations": {
            "provider_signal_authenticity_verified": False,
            "external_outcome_access_excluded": False,
            "operator_identity_authenticated": False,
            "cryptographic_signature_verified": False,
            "independent_review_performed": False,
        },
    }


def select_official_attempt_before_decode(
    attempts: Sequence[Mapping[str, Any]],
    *,
    run_policy_sha256: str,
    selector_sha256: str,
    selection_schema_sha256: str,
) -> dict[str, Any]:
    """Select the official attempt without receiving any scientific result bytes."""

    if not attempts or len(attempts) > 16:
        raise RunnerContractError("selection requires between one and sixteen retained attempts")
    ordered = sorted(attempts, key=lambda item: item["attempt_record"]["attempt_number"])
    numbers = [item["attempt_record"]["attempt_number"] for item in ordered]
    if numbers[0] != 1 or len(numbers) != len(set(numbers)):
        raise RunnerContractError("attempt records require unique ordinals including attempt one")
    environment_ids = {item["attempt_record"]["environment_id"] for item in ordered}
    classifications = {item["attempt_record"]["classification"] for item in ordered}
    if len(environment_ids) != 1 or len(classifications) != 1:
        raise RunnerContractError("attempts do not share environment/classification")
    for item in ordered:
        attempt = item["attempt_record"]
        classification = item["classification_record"]
        recomputed_attempt_sha256 = sha256_bytes(rfc8785.dumps(attempt))
        recomputed_classification_sha256 = sha256_bytes(
            rfc8785.dumps(classification)
        )
        if item["attempt_record_sha256"] != recomputed_attempt_sha256:
            raise RunnerContractError("supplied attempt-record hash differs from exact bytes")
        if item["classification_record_sha256"] != recomputed_classification_sha256:
            raise RunnerContractError(
                "supplied classification-record hash differs from exact bytes"
            )
        if classification["attempt_id"] != attempt["attempt_id"]:
            raise RunnerContractError("classification attempt ID differs")
        if classification["attempt_number"] != attempt["attempt_number"]:
            raise RunnerContractError("classification attempt number differs")
        if (
            classification["bindings"]["attempt_record_sha256"]
            != item["attempt_record_sha256"]
        ):
            raise RunnerContractError("classification attempt hash differs")
        if classification["bindings"]["run_policy_sha256"] != run_policy_sha256:
            raise RunnerContractError("classification run-policy hash differs")

    first_item = ordered[0]
    second_item = next(
        (item for item in ordered if item["attempt_record"]["attempt_number"] == 2),
        None,
    )
    first_status = first_item["classification_record"]["verdict"]["status"]
    second_status = (
        second_item["classification_record"]["verdict"]["status"]
        if second_item is not None
        else None
    )
    first_authorization = ordered[0]["attempt_record"]["attempt_two_authorization"]
    if first_authorization != {
        "status": "NOT_APPLICABLE",
        "attempt_one_classification_sha256": None,
    }:
        raise RunnerContractError("attempt one has an invalid attempt-two authorization shape")
    supplied_attempt_two_binding_valid: bool | None = None
    if second_item is not None:
        second_authorization = second_item["attempt_record"]["attempt_two_authorization"]
        supplied_attempt_two_binding_valid = (
            second_authorization["status"] == "AUTHORIZED"
            and second_authorization["attempt_one_classification_sha256"]
            == first_item["classification_record_sha256"]
        )
    unauthorized_attempt_numbers = [number for number in numbers if number > 2]
    if second_item is not None and (
        first_status != RETRY_ELIGIBLE or not supplied_attempt_two_binding_valid
    ):
        unauthorized_attempt_numbers.insert(0, 2)

    if first_status == INVALID_CLASSIFICATION:
        disposition = "NO_OFFICIAL_ATTEMPT"
        official = None
        attempt_two_slot_authorized = False
        reason = "ATTEMPT_1_CLASSIFICATION_INVALID"
    elif first_status == RETRY_ELIGIBLE:
        attempt_two_slot_authorized = True
        if second_item is None:
            disposition = "NO_OFFICIAL_ATTEMPT"
            official = None
            reason = "AUTHORIZED_ATTEMPT_2_MISSING"
        elif not supplied_attempt_two_binding_valid:
            disposition = "NO_OFFICIAL_ATTEMPT"
            official = None
            reason = "ATTEMPT_2_AUTHORIZATION_BINDING_INVALID"
        elif second_status == INVALID_CLASSIFICATION:
            disposition = "NO_OFFICIAL_ATTEMPT"
            official = None
            reason = "ATTEMPT_2_CLASSIFICATION_INVALID"
        elif second_status == RETRY_ELIGIBLE:
            disposition = "NO_OFFICIAL_ATTEMPT"
            official = None
            reason = "BOTH_ATTEMPTS_RETRY_ELIGIBLE_PRESTART"
        else:
            disposition = "ATTEMPT_2_OFFICIAL"
            official = 2
            reason = "ATTEMPT_2_REPLACES_ELIGIBLE_PRESTART_ATTEMPT_1"
    else:
        disposition = "ATTEMPT_1_OFFICIAL"
        official = 1
        attempt_two_slot_authorized = False
        reason = (
            "UNAUTHORIZED_LATER_ATTEMPTS_RETAINED_EXPLORATORY"
            if unauthorized_attempt_numbers
            else "ATTEMPT_1_NOT_RETRY_ELIGIBLE"
        )

    input_attempts = []
    for item in ordered:
        attempt = item["attempt_record"]
        classification = item["classification_record"]
        input_attempts.append(
            {
                "attempt_id": attempt["attempt_id"],
                "attempt_number": attempt["attempt_number"],
                "attempt_record_sha256": item["attempt_record_sha256"],
                "classification_record_sha256": item[
                    "classification_record_sha256"
                ],
                "classification_status": classification["verdict"]["status"],
                "predicate_id": classification["verdict"]["predicate_id"],
                "attempt_two_authorization_status": attempt[
                    "attempt_two_authorization"
                ]["status"],
                "attempt_one_classification_sha256": attempt[
                    "attempt_two_authorization"
                ]["attempt_one_classification_sha256"],
            }
        )

    return {
        "schema_version": "amy.environment-attempt-selection-intermediate.v1-draft",
        "classification": next(iter(classifications)),
        "environment_id": next(iter(environment_ids)),
        "bindings": {
            "run_policy_sha256": run_policy_sha256,
            "selector_sha256": selector_sha256,
            "selection_schema_sha256": selection_schema_sha256,
        },
        "input_attempts": input_attempts,
        "selection": {
            "disposition": disposition,
            "official_attempt_number": official,
            "attempt_two_slot_authorized": attempt_two_slot_authorized,
            "supplied_attempt_two_binding_valid": supplied_attempt_two_binding_valid,
            "unauthorized_attempt_numbers": unauthorized_attempt_numbers,
            "reason_code": reason,
            "candidate_for_campaign_decode_authorization": official is not None,
        },
        "boundaries": {
            "selection_computed_without_result_bytes": True,
            "selection_computed_without_oracle": True,
            "selection_computed_without_decision_fields": True,
            "all_supplied_attempts_retained": True,
            "this_exact_record_must_be_durably_persisted_before_result_decode": True,
        },
        "limitations": {
            "record_is_a_cryptographic_signature": False,
            "operator_identity_authenticated": False,
            "external_outcome_access_excluded": False,
            "independent_review_performed": False,
            "rg006_complete": False,
        },
    }


def build_campaign_selection_seal_before_decode(
    environment_attempts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    required_environment_ids: Sequence[str],
    phase_id: str,
    campaign_outcome_guard: Mapping[str, Any],
    run_policy_sha256: str,
    selector_sha256: str,
    selection_schema_sha256: str,
    outcome_guard_policy_sha256: str,
) -> dict[str, Any]:
    """Build one cross-environment seal before any candidate outcome decode."""

    required = list(required_environment_ids)
    if required != ["ENV-AUTHOR", "ENV-LINUX-PINNED"]:
        raise RunnerContractError("campaign environment order differs from the R1 policy")
    if list(environment_attempts) != required:
        raise RunnerContractError("campaign attempt sets are missing, extra, or out of order")
    if phase_id != "R1":
        raise RunnerContractError("current campaign seal contract is R1-only")

    selections: list[dict[str, Any]] = []
    classification_guards: list[Mapping[str, Any]] = []
    classification_boundaries: list[Mapping[str, Any]] = []
    for environment_id in required:
        values = environment_attempts[environment_id]
        selection = select_official_attempt_before_decode(
            values,
            run_policy_sha256=run_policy_sha256,
            selector_sha256=selector_sha256,
            selection_schema_sha256=selection_schema_sha256,
        )
        if selection["environment_id"] != environment_id:
            raise RunnerContractError("campaign environment and selection differ")
        selections.append(selection)
        for value in values:
            classification_guards.append(value["classification_record"]["outcome_guard"])
            classification_boundaries.append(value["classification_record"]["boundaries"])

    guard_epoch_id = campaign_outcome_guard["guard_epoch_id"]
    guard_counters_locally_consistent = (
        campaign_outcome_guard["scientific_intent_event_count"]
        == sum(item["scientific_intent_event_count"] for item in classification_guards)
        and
        campaign_outcome_guard["result_decode_event_count"] == 0
        and campaign_outcome_guard["oracle_join_event_count"] == 0
        and campaign_outcome_guard["human_outcome_read_event_count"] == 0
        and campaign_outcome_guard["decode_capability_released"] is False
        and all(item["guard_epoch_id"] == guard_epoch_id for item in classification_guards)
        and all(
            campaign_outcome_guard["checkpoint_sequence"] > item["checkpoint_sequence"]
            for item in classification_guards
        )
    )
    # No capability-separated vault or authenticated temporal anchor exists.
    # A locally consistent counter set therefore cannot establish pre-decode
    # ordering or authorize release.
    predecode_release_prevention_technically_enforced = False
    seal_status = "INVALID_FAIL_CLOSED"
    candidate_attempt_ids: list[str] = []
    environment_rows: list[dict[str, Any]] = []
    for selection in selections:
        official_number = selection["selection"]["official_attempt_number"]
        official_row = next(
            (
                item
                for item in selection["input_attempts"]
                if item["attempt_number"] == official_number
            ),
            None,
        )
        official_id = official_row["attempt_id"] if official_row is not None else None
        official_hash = (
            official_row["attempt_record_sha256"] if official_row is not None else None
        )
        if (
            guard_counters_locally_consistent
            and predecode_release_prevention_technically_enforced
            and official_id is not None
        ):
            candidate_attempt_ids.append(official_id)
        environment_rows.append(
            {
                "environment_id": selection["environment_id"],
                "input_attempts": selection["input_attempts"],
                "disposition": selection["selection"]["disposition"],
                "official_attempt_id": official_id,
                "official_attempt_record_sha256": official_hash,
                "reason_code": selection["selection"]["reason_code"],
            }
        )

    return {
        "schema_version": "amy.official-attempt-selection-seal.v1-draft",
        "record_status": "FINAL",
        "classification": CONTRACT_TEST_CLASSIFICATION,
        "phase_id": phase_id,
        "seal_status": seal_status,
        "bindings": {
            "run_policy_sha256": run_policy_sha256,
            "selector_sha256": selector_sha256,
            "selection_schema_sha256": selection_schema_sha256,
            "outcome_guard_policy_sha256": outcome_guard_policy_sha256,
        },
        "required_environment_ids": required,
        "environment_selections": environment_rows,
        "outcome_guard": dict(campaign_outcome_guard),
        "candidate_decode_attempt_ids_after_external_authentication": candidate_attempt_ids,
        "read_scope": {
            "result_bytes_received": False,
            "result_bytes_decoded": False,
            "oracle_received_or_joined": False,
            "decision_fields_received": False,
            "human_override_used": False,
        },
        "authentication": {
            "detached_authentication_verified": False,
            "external_temporal_anchor_verified": False,
            "decode_capability_released": False,
        },
        "boundaries": {
            "all_required_environments_selected_together": True,
            "guard_counters_locally_consistent": guard_counters_locally_consistent,
            "result_release_prevention_technically_enforced": False,
            "no_environment_result_released_before_campaign_selection": False,
            "this_exact_record_must_be_durably_persisted_and_externally_authenticated_before_decode": True,
            "all_supplied_attempts_retained": True,
        },
        "limitations": {
            "record_is_a_cryptographic_signature": False,
            "operator_identity_authenticated": False,
            "hidden_attempts_excluded": False,
            "external_outcome_access_excluded": False,
            "independent_review_performed": False,
            "rg006_complete": False,
        },
    }
