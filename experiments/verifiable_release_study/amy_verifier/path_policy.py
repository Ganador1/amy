from __future__ import annotations

import hashlib
import errno
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model import VerificationReject


WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class PayloadObservation:
    path: str
    kind: str
    stat_result: os.stat_result


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _raise_changed_on_path_race(exc: OSError, logical_path: str) -> None:
    race_errnos = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
    if hasattr(errno, "ESTALE"):
        race_errnos.add(errno.ESTALE)
    if exc.errno in race_errnos:
        raise VerificationReject(
            "INPUT_CHANGED",
            "path_safety",
            f"payload path changed during descriptor traversal: {logical_path}",
        ) from exc
    raise exc


def validate_logical_path(path: str, *, max_bytes: int, max_components: int) -> str:
    if path != unicodedata.normalize("NFC", path):
        raise VerificationReject("UNSAFE_PATH", "path_safety", "path is not Unicode NFC")
    if not path.startswith("payload/") or path == "payload/":
        raise VerificationReject(
            "UNSAFE_PATH", "path_safety", "path must begin with payload/"
        )
    if len(path.encode("utf-8")) > max_bytes:
        raise VerificationReject(
            "UNSAFE_PATH", "path_safety", "path exceeds UTF-8 byte limit"
        )
    if "\\" in path or "\x00" in path:
        raise VerificationReject(
            "UNSAFE_PATH", "path_safety", "path contains a forbidden separator or NUL"
        )
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in path):
        raise VerificationReject(
            "UNSAFE_PATH", "path_safety", "path contains a control/format/surrogate code point"
        )
    components = path.split("/")
    if len(components) > max_components:
        raise VerificationReject("UNSAFE_PATH", "path_safety", "path has too many components")
    for component in components:
        if component in {"", ".", ".."}:
            raise VerificationReject(
                "UNSAFE_PATH", "path_safety", "path contains an empty or dot component"
            )
        if component.endswith((" ", ".")) or ":" in component:
            raise VerificationReject(
                "UNSAFE_PATH", "path_safety", "path component is not portable"
            )
        basename = component.split(".", 1)[0].upper()
        if basename in WINDOWS_RESERVED:
            raise VerificationReject(
                "UNSAFE_PATH", "path_safety", "path uses a reserved device basename"
            )
    return path


def validate_manifest_paths(
    paths: Iterable[str], *, max_bytes: int, max_components: int
) -> list[str]:
    validated = [
        validate_logical_path(path, max_bytes=max_bytes, max_components=max_components)
        for path in paths
    ]
    if validated != sorted(validated, key=lambda value: value.encode("utf-8")):
        raise VerificationReject(
            "SCHEMA_INVALID", "path_safety", "manifest payload paths are not sorted"
        )
    if len(validated) != len(set(validated)):
        raise VerificationReject(
            "DUPLICATE_PATH", "path_safety", "manifest contains an exact duplicate path"
        )
    folded: dict[str, str] = {}
    for path in validated:
        collision_key = path.casefold()
        if collision_key in folded:
            raise VerificationReject(
                "DUPLICATE_PATH",
                "path_safety",
                "manifest paths collide under Unicode casefold",
                {"first": folded[collision_key], "second": path},
            )
        folded[collision_key] = path
    return validated


def observe_payload_tree(root: Path, *, max_count: int, max_total_bytes: int) -> dict[str, PayloadObservation]:
    payload_root = root / "payload"
    try:
        root_stat = payload_root.lstat()
    except FileNotFoundError as exc:
        raise VerificationReject(
            "PAYLOAD_MISSING", "closed_world_inventory", "payload directory is missing"
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise VerificationReject(
            "UNSAFE_PATH", "path_safety", "payload root is not a real directory"
        )

    if not hasattr(os, "O_NOFOLLOW") or os.scandir not in os.supports_fd:
        raise RuntimeError(
            "descriptor-relative scandir and O_NOFOLLOW are required by the verifier"
        )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | os.O_NOFOLLOW
    )
    try:
        root_fd = os.open(payload_root, directory_flags)
    except OSError as exc:
        _raise_changed_on_path_race(exc, "payload")
        raise AssertionError("unreachable")

    open_descriptors = {root_fd}
    observations: dict[str, PayloadObservation] = {}
    total_bytes = 0
    scanned_entry_count = 0
    try:
        opened_root = os.fstat(root_fd)
        if _stat_identity(opened_root) != _stat_identity(root_stat):
            raise VerificationReject(
                "INPUT_CHANGED", "path_safety", "payload root changed before open"
            )
        stack: list[tuple[int, str, os.stat_result]] = [
            (root_fd, "payload", opened_root)
        ]
        while stack:
            directory_fd, logical_directory, expected_directory = stack.pop()
            if _stat_identity(os.fstat(directory_fd)) != _stat_identity(expected_directory):
                raise VerificationReject(
                    "INPUT_CHANGED",
                    "path_safety",
                    f"payload directory changed before scan: {logical_directory}",
                )
            try:
                with os.scandir(directory_fd) as iterator:
                    entries = sorted(iterator, key=lambda entry: os.fsencode(entry.name))
            except OSError as exc:
                _raise_changed_on_path_race(exc, logical_directory)
                raise AssertionError("unreachable")
            if _stat_identity(os.fstat(directory_fd)) != _stat_identity(expected_directory):
                raise VerificationReject(
                    "INPUT_CHANGED",
                    "path_safety",
                    f"payload directory changed while scanning: {logical_directory}",
                )
            for entry in entries:
                scanned_entry_count += 1
                if scanned_entry_count > max_count:
                    raise VerificationReject(
                        "RESOURCE_LIMIT",
                        "bounded_input",
                        "payload entry count exceeds the policy limit",
                        {"max_count": max_count},
                    )
                logical_path = f"{logical_directory}/{entry.name}"
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    _raise_changed_on_path_race(exc, logical_path)
                    raise AssertionError("unreachable")
                if stat.S_ISDIR(entry_stat.st_mode) and not stat.S_ISLNK(entry_stat.st_mode):
                    try:
                        child_fd = os.open(entry.name, directory_flags, dir_fd=directory_fd)
                    except OSError as exc:
                        _raise_changed_on_path_race(exc, logical_path)
                        raise AssertionError("unreachable")
                    open_descriptors.add(child_fd)
                    opened_child = os.fstat(child_fd)
                    if _stat_identity(opened_child) != _stat_identity(entry_stat):
                        raise VerificationReject(
                            "INPUT_CHANGED",
                            "path_safety",
                            f"payload directory changed before open: {logical_path}",
                        )
                    if opened_child.st_dev != opened_root.st_dev:
                        raise VerificationReject(
                            "UNSAFE_PATH",
                            "path_safety",
                            "payload tree crosses a filesystem device",
                        )
                    stack.append((child_fd, logical_path, opened_child))
                    continue
                if stat.S_ISLNK(entry_stat.st_mode):
                    kind = "symlink"
                elif stat.S_ISREG(entry_stat.st_mode):
                    kind = "regular"
                else:
                    kind = "nonregular"
                observations[logical_path] = PayloadObservation(
                    logical_path, kind, entry_stat
                )
                total_bytes += max(0, entry_stat.st_size)
                if total_bytes > max_total_bytes:
                    raise VerificationReject(
                        "RESOURCE_LIMIT",
                        "bounded_input",
                        "payload observed bytes exceed the policy limit",
                        {"max_total_bytes": max_total_bytes},
                    )
        return observations
    finally:
        for descriptor in open_descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_payload_beneath(payload_root: Path, logical_path: str) -> tuple[int, os.stat_result]:
    components = logical_path.split("/")[1:]
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("O_NOFOLLOW is required by the verifier")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= os.O_NOFOLLOW
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    directory_fd = os.open(payload_root, directory_flags)
    try:
        for component in components[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(components[-1], file_flags, dir_fd=directory_fd)
        return file_fd, os.fstat(file_fd)
    finally:
        os.close(directory_fd)


def hash_payload(
    root: Path,
    logical_path: str,
    observation: PayloadObservation,
    *,
    max_bytes: int,
) -> tuple[int, str]:
    if observation.kind == "symlink":
        raise VerificationReject(
            "SYMLINK_FORBIDDEN", "path_safety", f"symlink payload: {logical_path}"
        )
    if observation.kind != "regular":
        raise VerificationReject(
            "NONREGULAR_FILE", "path_safety", f"non-regular payload: {logical_path}"
        )
    if observation.stat_result.st_nlink != 1:
        raise VerificationReject(
            "HARDLINK_FORBIDDEN", "path_safety", f"multiply linked payload: {logical_path}"
        )
    if observation.stat_result.st_size > max_bytes:
        raise VerificationReject(
            "RESOURCE_LIMIT",
            "bounded_input",
            f"payload exceeds individual byte limit: {logical_path}",
        )

    try:
        descriptor, opened = _open_payload_beneath(root / "payload", logical_path)
    except OSError as exc:
        _raise_changed_on_path_race(exc, logical_path)
        raise AssertionError("unreachable")
    try:
        expected_identity = (
            observation.stat_result.st_dev,
            observation.stat_result.st_ino,
            observation.stat_result.st_mode,
            observation.stat_result.st_size,
            observation.stat_result.st_mtime_ns,
            observation.stat_result.st_nlink,
        )
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_nlink,
        )
        if expected_identity != opened_identity:
            raise VerificationReject(
                "INPUT_CHANGED", "payload_digests", f"payload changed before open: {logical_path}"
            )
        digest = hashlib.sha256()
        observed_size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            observed_size += len(chunk)
            if observed_size > max_bytes:
                raise VerificationReject(
                    "RESOURCE_LIMIT", "bounded_input", f"payload grew past limit: {logical_path}"
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        )
        if after_identity != opened_identity or observed_size != after.st_size:
            raise VerificationReject(
                "INPUT_CHANGED", "payload_digests", f"payload changed while hashing: {logical_path}"
            )
        return observed_size, digest.hexdigest()
    finally:
        os.close(descriptor)
