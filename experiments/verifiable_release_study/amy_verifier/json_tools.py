from __future__ import annotations

import json
import errno
import os
import stat
from pathlib import Path
from typing import Any

from .model import VerificationReject


class _DuplicateKey(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _check_nesting(text: str, max_depth: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > max_depth:
                raise VerificationReject(
                    "RESOURCE_LIMIT",
                    "bounded_input",
                    f"JSON nesting exceeds {max_depth}",
                    {"max_depth": max_depth},
                )
        elif character in "]}":
            depth = max(0, depth - 1)


def parse_json_bytes(
    raw: bytes,
    *,
    max_depth: int,
    reject_duplicate_keys: bool,
    failure_check: str,
    invalid_reason: str = "JSON_INVALID",
    duplicate_reason: str = "DUPLICATE_JSON_KEY",
) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise VerificationReject(
            invalid_reason,
            failure_check,
            "JSON input is not strict UTF-8",
            {"offset": exc.start},
        ) from exc
    _check_nesting(text, max_depth)
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_without_duplicates if reject_duplicate_keys else None,
            parse_constant=_reject_constant,
        )
    except _DuplicateKey as exc:
        raise VerificationReject(
            duplicate_reason,
            failure_check,
            "JSON object contains a duplicate name",
            {"key": str(exc)},
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationReject(
            invalid_reason,
            failure_check,
            "JSON input is malformed",
            {"error": str(exc)},
        ) from exc


def bounded_regular_file_read(path: Path, max_bytes: int, *, check: str) -> bytes:
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise VerificationReject(
            "INPUT_MISSING", check, f"required input is missing: {path.name}"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise VerificationReject(
            "INPUT_MISSING",
            check,
            f"required input is not a regular non-symlink file: {path.name}",
        )
    if before.st_size > max_bytes:
        raise VerificationReject(
            "RESOURCE_LIMIT",
            check,
            f"{path.name} exceeds the byte limit",
            {"observed_bytes": before.st_size, "max_bytes": max_bytes},
        )

    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("O_NOFOLLOW is required by the frozen verifier environment")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        race_errnos = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
        if hasattr(errno, "ESTALE"):
            race_errnos.add(errno.ESTALE)
        if exc.errno in race_errnos:
            raise VerificationReject(
                "INPUT_CHANGED", check, f"{path.name} changed before it was opened"
            ) from exc
        raise
    try:
        opened = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        )
        identity_opened = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_nlink,
        )
        if identity_opened != identity_before:
            raise VerificationReject(
                "INPUT_CHANGED", check, f"{path.name} changed before it was opened"
            )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > max_bytes:
                raise VerificationReject(
                    "RESOURCE_LIMIT",
                    check,
                    f"{path.name} exceeded the byte limit while reading",
                    {"max_bytes": max_bytes},
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        )
        if identity_after != identity_opened or observed != after.st_size:
            raise VerificationReject(
                "INPUT_CHANGED", check, f"{path.name} changed while it was read"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)
