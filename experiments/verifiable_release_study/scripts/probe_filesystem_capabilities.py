#!/usr/bin/env python3
"""Probe filesystem primitives required by path-safety cases without networking."""

from __future__ import annotations

import argparse
import errno
import json
import os
import platform
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable


def normalized_error(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "errno_name": errno.errorcode.get(getattr(exc, "errno", None)),
    }


def execute_probe(callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        details = callback()
    except BaseException as exc:  # probe must report rather than crash
        return {"supported": False, "error": normalized_error(exc)}
    return {"supported": True, "details": details}


def probe(environment_id: str, recorded_at: str, expected_image: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="amy-fs-probe-") as temporary:
        root = Path(temporary)

        def regular_file() -> dict[str, Any]:
            path = root / "regular.txt"
            path.write_bytes(b"fixture")
            observed = path.lstat()
            return {
                "is_regular": stat.S_ISREG(observed.st_mode),
                "bytes": observed.st_size,
            }

        def symlink() -> dict[str, Any]:
            target = root / "symlink-target.txt"
            link = root / "symlink.txt"
            target.write_bytes(b"target")
            link.symlink_to(target.name)
            observed = link.lstat()
            return {
                "is_symlink": stat.S_ISLNK(observed.st_mode),
                "target": os.readlink(link),
            }

        def nofollow() -> dict[str, Any]:
            if not hasattr(os, "O_NOFOLLOW"):
                raise NotImplementedError("O_NOFOLLOW is unavailable")
            target = root / "nofollow-target.txt"
            link = root / "nofollow-link.txt"
            target.write_bytes(b"target")
            link.symlink_to(target.name)
            try:
                descriptor = os.open(link, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as exc:
                if exc.errno not in {errno.ELOOP, errno.EMLINK}:
                    raise
                return {
                    "symlink_open_blocked": True,
                    "errno": exc.errno,
                    "errno_name": errno.errorcode.get(exc.errno),
                }
            else:
                os.close(descriptor)
                raise RuntimeError("O_NOFOLLOW unexpectedly opened a symlink")

        def hardlink() -> dict[str, Any]:
            source = root / "hardlink-source.txt"
            link = root / "hardlink-target.txt"
            source.write_bytes(b"same-inode")
            os.link(source, link)
            source_stat = source.stat()
            link_stat = link.stat()
            if (source_stat.st_dev, source_stat.st_ino) != (
                link_stat.st_dev,
                link_stat.st_ino,
            ):
                raise RuntimeError("hardlink did not preserve device/inode")
            if source_stat.st_nlink < 2 or link_stat.st_nlink < 2:
                raise RuntimeError("hardlink count is below two")
            return {"same_device_inode": True, "minimum_link_count": 2}

        def fifo() -> dict[str, Any]:
            if not hasattr(os, "mkfifo"):
                raise NotImplementedError("mkfifo is unavailable")
            path = root / "fixture.fifo"
            os.mkfifo(path, 0o600)
            observed = path.lstat()
            if not stat.S_ISFIFO(observed.st_mode):
                raise RuntimeError("mkfifo result is not a FIFO")
            return {"is_fifo": True}

        def dir_fd() -> dict[str, Any]:
            if os.open not in os.supports_dir_fd:
                raise NotImplementedError("os.open does not support dir_fd")
            path = root / "dirfd.txt"
            path.write_bytes(b"dir-fd")
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(root, directory_flags)
            try:
                descriptor = os.open("dirfd.txt", os.O_RDONLY, dir_fd=directory)
                try:
                    raw = os.read(descriptor, 32)
                finally:
                    os.close(descriptor)
            finally:
                os.close(directory)
            if raw != b"dir-fd":
                raise RuntimeError("dir_fd opened unexpected bytes")
            return {"relative_open_succeeded": True}

        details = {
            "regular_files": execute_probe(regular_file),
            "symlink": execute_probe(symlink),
            "O_NOFOLLOW": execute_probe(nofollow),
            "hardlink": execute_probe(hardlink),
            "fifo": execute_probe(fifo),
            "dir_fd": execute_probe(dir_fd),
        }
    capabilities = {
        "regular_files": details["regular_files"]["supported"],
        "filesystem_supports_symlink": (
            details["symlink"]["supported"] and details["O_NOFOLLOW"]["supported"]
        ),
        "filesystem_supports_hardlink": details["hardlink"]["supported"],
        "filesystem_supports_fifo": details["fifo"]["supported"],
        "dir_fd": details["dir_fd"]["supported"],
        "O_NOFOLLOW": details["O_NOFOLLOW"]["supported"],
    }
    return {
        "schema_version": "amy.filesystem-capability-probe.v1",
        "classification": "R0_environment_compatibility_evidence",
        "environment_id": environment_id,
        "recorded_at": recorded_at,
        "expected_image": expected_image,
        "runtime": {
            "os_name": os.name,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
        },
        "network_required_by_probe": False,
        "capabilities": capabilities,
        "all_required_supported": all(capabilities.values()),
        "probe_details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--expected-image")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = probe(args.environment_id, args.recorded_at, args.expected_image)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0 if result["all_required_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
