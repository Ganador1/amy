#!/usr/bin/env python3
"""Mechanically verify an R0 review packet against externally supplied hashes.

This command performs no network access and no signature, reviewer-authorization,
competence, independence, or scientific-truth verification.  It cannot close
RG-004.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
SUBJECT_MANIFEST_NAME = "R0_REVIEW_SUBJECT_MANIFEST.jcs.json"
PACKET_NAME = "R0_REVIEW_PACKET.tar"
REVIEW_SCHEMA_PATH = STUDY_ROOT / "schemas/r0-human-review-record.schema.json"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = 256 * 1024 * 1024
MAX_REVIEW_RECORD_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROLE_RE = re.compile(
    r"^(?:base|catalog|compatibility|distribution|implementation|oracle|policy|"
    r"proposition|protocol|schema|test)(?:\.[a-z0-9_]+)+$"
)


class _DuplicateKeyError(ValueError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_regular(path: Path, max_bytes: int) -> bytes:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"input is not a regular non-symlink file: {path}")
    if before.st_size > max_bytes:
        raise ValueError(f"input exceeds {max_bytes} bytes: {path}")
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("O_NOFOLLOW is required for fail-closed packet verification")
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(
            before
        ):
            raise ValueError(f"input changed before read: {path}")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > max_bytes:
                raise ValueError(f"input exceeded {max_bytes} bytes while reading: {path}")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _file_identity(after) != _file_identity(opened) or observed != after.st_size:
            raise ValueError(f"input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object name: {key}")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _strict_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonstandard_constant,
    )


def _safe_member_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return None
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        return None
    return value


def _validate_manifest_shape(manifest: Any, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        errors.append("subject manifest root is not an object")
        return []
    expected_top = {
        "schema_version",
        "status",
        "gate_id",
        "gate_status_after_build",
        "canonicalization",
        "artifact_count",
        "artifact_categories",
        "artifacts",
        "archive_contract",
        "read_boundary",
        "claim_boundary",
    }
    if set(manifest) != expected_top:
        errors.append("subject manifest top-level fields differ from the closed contract")
    constants = {
        "schema_version": "amy.r0-human-review-subject-manifest.v1-draft",
        "status": "preparation_only_unreviewed_not_frozen",
        "gate_id": "RG-004",
        "gate_status_after_build": "open",
        "canonicalization": "RFC8785_JCS",
    }
    for field, expected in constants.items():
        if manifest.get(field) != expected:
            errors.append(f"subject manifest {field} differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("subject manifest artifacts is not an array")
        return []
    if manifest.get("artifact_count") != len(artifacts):
        errors.append("subject manifest artifact_count differs from its rows")

    paths: list[str] = []
    categories: set[str] = set()
    valid_rows: list[dict[str, Any]] = []
    for index, row in enumerate(artifacts):
        if not isinstance(row, dict) or set(row) != {
            "path",
            "raw_sha256",
            "byte_length",
            "role",
        }:
            errors.append(f"artifact row {index} differs from the closed contract")
            continue
        path = _safe_member_name(row.get("path"))
        digest = row.get("raw_sha256")
        length = row.get("byte_length")
        role = row.get("role")
        if path is None or path in {SUBJECT_MANIFEST_NAME, PACKET_NAME}:
            errors.append(f"artifact row {index} has an unsafe or reserved path")
            continue
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            errors.append(f"artifact row {index} has an invalid SHA-256")
            continue
        if not isinstance(length, int) or isinstance(length, bool) or length < 0:
            errors.append(f"artifact row {index} has an invalid byte length")
            continue
        if not isinstance(role, str) or ROLE_RE.fullmatch(role) is None:
            errors.append(f"artifact row {index} has an invalid role")
            continue
        paths.append(path)
        categories.add(role.split(".", 1)[0])
        valid_rows.append(row)
    if len(paths) != len(set(paths)):
        errors.append("subject manifest contains duplicate artifact paths")
    if paths != sorted(paths, key=lambda item: item.encode("utf-8")):
        errors.append("subject manifest artifact paths are not UTF-8-bytewise sorted")
    if manifest.get("artifact_categories") != sorted(
        categories, key=lambda item: item.encode("utf-8")
    ):
        errors.append("subject manifest artifact categories differ")

    expected_archive = {
        "format": "USTAR",
        "compression": "none",
        "member_order": "UTF-8_bytewise_path_order",
        "regular_file_mode": "0644",
        "mtime": 0,
        "uid": 0,
        "gid": 0,
        "uname": "",
        "gname": "",
        "subject_manifest_member": SUBJECT_MANIFEST_NAME,
    }
    if manifest.get("archive_contract") != expected_archive:
        errors.append("subject manifest archive contract differs")
    expected_boundary = {
        "explicit_subject_paths_only": True,
        "directory_discovery_used": False,
        "repository_distribution_files_read": True,
        "synthetic_engineering_receipts_read": False,
        "empirical_or_confirmatory_run_outputs_read": False,
        "confirmatory_outputs_read": False,
        "confirmatory_cases_generated_or_executed": False,
        "independent_human_review_performed": False,
    }
    if manifest.get("read_boundary") != expected_boundary:
        errors.append("subject manifest read boundary differs")
    if not isinstance(manifest.get("claim_boundary"), str):
        errors.append("subject manifest claim boundary is missing")
    return valid_rows


def _validate_archive(
    packet_raw: bytes,
    manifest_raw: bytes,
    artifact_rows: list[dict[str, Any]],
    errors: list[str],
) -> int:
    if len(packet_raw) < 263 or packet_raw[257:263] != b"ustar\x00":
        errors.append("packet does not expose the expected USTAR magic")
    expected_names = sorted(
        [SUBJECT_MANIFEST_NAME, *(str(row["path"]) for row in artifact_rows)],
        key=lambda item: item.encode("utf-8"),
    )
    archived: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(packet_raw), mode="r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if names != expected_names:
                errors.append("packet member order or coverage differs from the manifest")
            if len(names) != len(set(names)):
                errors.append("packet contains duplicate member names")
            for member in members:
                if (
                    not member.isreg()
                    or member.mode != 0o644
                    or member.mtime != 0
                    or member.uid != 0
                    or member.gid != 0
                    or member.uname != ""
                    or member.gname != ""
                ):
                    errors.append(f"packet member metadata differs: {member.name}")
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    errors.append(f"packet member cannot be read: {member.name}")
                    continue
                archived[member.name] = handle.read()
    except (tarfile.TarError, OSError, ValueError) as exc:
        errors.append(f"packet is not a readable uncompressed USTAR archive: {exc}")
        return 0

    if archived.get(SUBJECT_MANIFEST_NAME) != manifest_raw:
        errors.append("packet manifest member differs from the external manifest bytes")
    for row in artifact_rows:
        path = str(row["path"])
        raw = archived.get(path)
        if raw is None:
            errors.append(f"packet is missing artifact bytes: {path}")
            continue
        if len(raw) != row["byte_length"]:
            errors.append(f"packet artifact byte length differs: {path}")
        if _sha256(raw) != row["raw_sha256"]:
            errors.append(f"packet artifact SHA-256 differs: {path}")
    return len(archived)


def validate(
    packet_directory: Path,
    expected_manifest_sha256: str,
    expected_packet_sha256: str,
    review_record_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if SHA256_RE.fullmatch(expected_manifest_sha256) is None:
        raise ValueError("expected manifest SHA-256 must be 64 lowercase hex characters")
    if SHA256_RE.fullmatch(expected_packet_sha256) is None:
        raise ValueError("expected packet SHA-256 must be 64 lowercase hex characters")

    manifest_path = packet_directory / SUBJECT_MANIFEST_NAME
    packet_path = packet_directory / PACKET_NAME
    manifest_raw = b""
    packet_raw = b""
    try:
        manifest_raw = _read_regular(manifest_path, MAX_MANIFEST_BYTES)
    except (OSError, ValueError, RuntimeError) as exc:
        errors.append(f"subject manifest read failed: {exc}")
    try:
        packet_raw = _read_regular(packet_path, MAX_PACKET_BYTES)
    except (OSError, ValueError, RuntimeError) as exc:
        errors.append(f"packet read failed: {exc}")

    observed_manifest_sha = _sha256(manifest_raw) if manifest_raw else None
    observed_packet_sha = _sha256(packet_raw) if packet_raw else None
    manifest_hash_matches = observed_manifest_sha == expected_manifest_sha256
    packet_hash_matches = observed_packet_sha == expected_packet_sha256
    if not manifest_hash_matches:
        errors.append("subject manifest SHA-256 differs from the externally supplied value")
    if not packet_hash_matches:
        errors.append("packet SHA-256 differs from the externally supplied value")

    manifest: Any = {}
    manifest_canonical = False
    artifact_rows: list[dict[str, Any]] = []
    if manifest_raw:
        try:
            manifest = _strict_json(manifest_raw)
            manifest_canonical = rfc8785.dumps(manifest) == manifest_raw
            if not manifest_canonical:
                errors.append("subject manifest bytes are not RFC 8785 canonical JSON")
            artifact_rows = _validate_manifest_shape(manifest, errors)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"subject manifest is not strict unambiguous JSON: {exc}")

    archive_error_start = len(errors)
    archive_member_count = 0
    if packet_raw and manifest_raw and artifact_rows:
        archive_member_count = _validate_archive(
            packet_raw, manifest_raw, artifact_rows, errors
        )
    archive_contract_valid = (
        len(errors) == archive_error_start
        and archive_member_count == len(artifact_rows) + 1
    )

    review_record = {
        "supplied": review_record_path is not None,
        "path": str(review_record_path) if review_record_path is not None else None,
        "schema_valid": None,
        "record_status": None,
        "subject_binding_matches": None,
        "human_review_claimed": False,
    }
    if review_record_path is not None:
        try:
            record_raw = _read_regular(review_record_path, MAX_REVIEW_RECORD_BYTES)
            record = _strict_json(record_raw)
            review_schema = _strict_json(
                _read_regular(REVIEW_SCHEMA_PATH, MAX_REVIEW_RECORD_BYTES)
            )
            Draft202012Validator.check_schema(review_schema)
            schema_errors = list(
                Draft202012Validator(
                    review_schema, format_checker=FormatChecker()
                ).iter_errors(record)
            )
            review_record["schema_valid"] = not schema_errors
            review_record["record_status"] = (
                record.get("record_status") if isinstance(record, dict) else None
            )
            if schema_errors:
                errors.append(f"review record schema invalid: {schema_errors[0].message}")
            if isinstance(record, dict) and record.get("record_status") == "submitted":
                binding = record.get("subject_binding") or {}
                binding_matches = (
                    binding.get("subject_manifest_sha256")
                    == expected_manifest_sha256
                    and binding.get("packet_sha256") == expected_packet_sha256
                )
                review_record["subject_binding_matches"] = binding_matches
                review_record["human_review_claimed"] = (
                    record.get("independent_human_review_occurred") is True
                )
                if not binding_matches:
                    errors.append(
                        "submitted review record does not bind both externally supplied hashes"
                    )
            elif isinstance(record, dict) and record.get("record_status") == (
                "template_unreviewed"
            ):
                review_record["human_review_claimed"] = False
            else:
                errors.append("review record has an unsupported status")
        except (
            OSError,
            RuntimeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            errors.append(f"review record verification failed: {exc}")
            review_record["schema_valid"] = False

    valid = not errors
    if not valid:
        status = "invalid"
    elif review_record["record_status"] == "submitted":
        status = "mechanical_integrity_valid_submitted_record_present"
    else:
        status = "mechanical_integrity_valid_unreviewed"
    return {
        "schema_version": "amy.r0-review-packet-verification.v1-draft",
        "valid": valid,
        "status": status,
        "errors": errors,
        "subject_manifest": {
            "path": str(manifest_path),
            "expected_sha256": expected_manifest_sha256,
            "observed_sha256": observed_manifest_sha,
            "byte_length": len(manifest_raw),
            "hash_matches": manifest_hash_matches,
        },
        "packet": {
            "path": str(packet_path),
            "expected_sha256": expected_packet_sha256,
            "observed_sha256": observed_packet_sha,
            "byte_length": len(packet_raw),
            "hash_matches": packet_hash_matches,
        },
        "artifact_count": len(artifact_rows),
        "archive_member_count": archive_member_count,
        "manifest_canonical": manifest_canonical,
        "archive_contract_valid": archive_contract_valid,
        "review_record": review_record,
        "detached_authentication_verified": False,
        "reviewer_authorization_verified": False,
        "reviewer_competence_verified": False,
        "rg004_complete": False,
        "confirmatory_outputs_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify R0 review-packet mechanics against two externally supplied hashes; "
            "this does not verify signatures or close RG-004."
        )
    )
    parser.add_argument("--packet-directory", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-packet-sha256", required=True)
    parser.add_argument("--review-record", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(
        args.packet_directory.resolve(),
        args.expected_manifest_sha256,
        args.expected_packet_sha256,
        args.review_record.resolve() if args.review_record else None,
    )
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
