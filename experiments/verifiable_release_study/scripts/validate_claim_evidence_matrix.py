#!/usr/bin/env python3
"""Fail-closed validation for the claim-to-evidence matrix.

The validator resolves evidence only from exact study-relative regular files.
Every allowed claim must cite canonical JSON references carrying an exact path,
an RFC 6901 JSON Pointer or unique full-line anchor, and the SHA-256 of the
referenced file bytes.  Resolution proves identity and addressability, not the
scientific truth or sufficiency of the cited evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = STUDY_ROOT / "evidence/CLAIM_EVIDENCE_MATRIX.csv"

FIELDNAMES = [
    "claim_id",
    "status",
    "provisional_claim",
    "evidence_required",
    "current_evidence",
    "allowed_now",
    "notes",
]
STATUSES = {
    "OBSERVED",
    "REPRODUCED",
    "SPECIFIED",
    "TESTED",
    "INFERRED",
    "EXTERNAL",
    "UNKNOWN",
}
ALLOWABLE_STATUSES = STATUSES - {"SPECIFIED", "UNKNOWN"}
EXPECTED_CLAIM_IDS = [f"C{index:03d}" for index in range(1, 48)]
REFERENCE_KEYS = {"locator", "path", "sha256"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


class DuplicateKeyError(ValueError):
    """Raised when strict JSON contains a duplicate object member."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json_loads(raw: str | bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_reject_duplicate_keys)


def _canonical_references(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _decode_pointer_token(token: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(token):
        if token[index] != "~":
            output.append(token[index])
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ValueError("invalid RFC 6901 escape")
        output.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(output)


def _resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be non-empty and start with '/'")
    current = document
    for encoded_token in pointer[1:].split("/"):
        token = _decode_pointer_token(encoded_token)
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError(f"invalid array index: {token}")
            index = int(token)
            if index >= len(current):
                raise IndexError(index)
            current = current[index]
        else:
            raise TypeError(f"cannot descend through {type(current).__name__}")
    return current


def _safe_regular_file(study_root: Path, relative_text: str) -> Path:
    if not relative_text or "\\" in relative_text:
        raise ValueError("path must be a non-empty POSIX relative path")
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or relative.as_posix() != relative_text:
        raise ValueError("path must be canonical and relative")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("path contains an unsafe component")

    root = study_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError("referenced path does not exist") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("symlinks are forbidden in evidence paths")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("evidence path escapes the study root") from exc
    if not resolved.is_file():
        raise ValueError("evidence path is not a regular file")
    return resolved


def _read_bounded(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_EVIDENCE_BYTES:
        raise ValueError(f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes")
    raw = path.read_bytes()
    if len(raw) != size:
        raise ValueError("evidence file changed while being read")
    return raw


def _validate_reference(
    reference: Any, *, study_root: Path, claim_id: str
) -> tuple[str, str, Any]:
    if not isinstance(reference, dict) or set(reference) != REFERENCE_KEYS:
        raise ValueError(f"{claim_id}: evidence reference must have exact keys")
    if not all(isinstance(reference[key], str) for key in REFERENCE_KEYS):
        raise ValueError(f"{claim_id}: evidence reference values must be strings")

    relative_path = reference["path"]
    locator = reference["locator"]
    expected_sha256 = reference["sha256"]
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ValueError(f"{claim_id}: evidence SHA-256 is not lowercase hex")

    path = _safe_regular_file(study_root, relative_path)
    raw = _read_bounded(path)
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError(
            f"{claim_id}: evidence SHA-256 mismatch for {relative_path}: "
            f"{observed_sha256} != {expected_sha256}"
        )

    if locator.startswith("json_pointer:"):
        pointer = locator.removeprefix("json_pointer:")
        document = _strict_json_loads(raw)
        resolved_value = _resolve_json_pointer(document, pointer)
    elif locator.startswith("line_anchor:"):
        anchor = locator.removeprefix("line_anchor:")
        if not anchor or "\n" in anchor or "\r" in anchor:
            raise ValueError(f"{claim_id}: line anchor must be one non-empty line")
        text = raw.decode("utf-8")
        matches = sum(line == anchor for line in text.splitlines())
        if matches != 1:
            raise ValueError(
                f"{claim_id}: line anchor must resolve exactly once; observed {matches}"
            )
        resolved_value = anchor
    else:
        raise ValueError(f"{claim_id}: unsupported evidence locator")

    return relative_path, locator, resolved_value


def _validate_special_claims(
    rows_by_id: dict[str, dict[str, str]],
    resolved: dict[str, dict[tuple[str, str], Any]],
) -> None:
    c005_expected = {
        (
            "evidence/SOURCE_LEDGER.md",
            f"line_anchor:| S0{index} | "
            + {
                1: "[NIST FIPS 180-4, Secure Hash Standard](https://csrc.nist.gov/files/pubs/fips/180-4/final/docs/fips180-4.pdf) | Defines approved secure hash algorithms used to compute message digests |",
                2: "[NIST FIPS 186-5, Digital Signature Standard](https://csrc.nist.gov/pubs/fips/186-5/final) | Digital signatures detect unauthorized modification and authenticate a signatory under the signature model |",
                3: "[NIST Digital Signatures overview](https://csrc.nist.gov/Projects/digital-signatures) | Separates signer assurance from assurance that signed information was not modified after signing |",
            }[index],
        )
        for index in (1, 2, 3)
    }
    if set(resolved.get("C005", {})) != c005_expected:
        raise ValueError("C005: exact S01-S03 primary-source anchors are required")

    c043_refs = resolved.get("C043", {})
    count_key = (
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json",
        "json_pointer:/compatibility_counts",
    )
    unit_key = (
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json",
        "json_pointer:/candidate_unit_count",
    )
    invariant_key = (
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json",
        "json_pointer:/counterfactual_outcome_fields_invariant",
    )
    catalog_key = (
        "protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json",
        "json_pointer:/summary",
    )
    required = {count_key, unit_key, invariant_key, catalog_key}
    if not required.issubset(c043_refs):
        raise ValueError("C043: exact matrix and catalog evidence pointers are required")

    counts = c043_refs[count_key]
    unit_count = c043_refs[unit_key]
    invariant = c043_refs[invariant_key]
    catalog = c043_refs[catalog_key]
    if not isinstance(counts, dict) or not isinstance(catalog, dict):
        raise ValueError("C043: referenced count summaries must be JSON objects")
    observed = (
        counts.get("COMPATIBLE"),
        counts.get("PENDING"),
        counts.get("NOT_COMPATIBLE"),
    )
    match = re.search(
        r"complete ([0-9]+)-row compatibility matrix with ([0-9]+) compatible, "
        r"([0-9]+) pending, and ([0-9]+) structurally non-compatible units",
        rows_by_id["C043"]["provisional_claim"],
    )
    if match is None:
        raise ValueError("C043: claim does not expose the required count wording")
    claimed = tuple(int(value) for value in match.groups())
    expected = (unit_count, *observed)
    if claimed != expected:
        raise ValueError(f"C043: claim counts {claimed} != evidence counts {expected}")
    if invariant is not True:
        raise ValueError("C043: counterfactual outcome-field invariance is not true")
    if (
        catalog.get("historical_case_count") != 34
        or catalog.get("preserved_case_id_count") != 34
        or catalog.get("added_case_count") != 7
    ):
        raise ValueError("C043: catalog history/addition counts do not match the claim")


def validate_claim_evidence_matrix(
    matrix_path: Path = MATRIX_PATH, *, study_root: Path = STUDY_ROOT
) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, str]] = []
    resolved: dict[str, dict[tuple[str, str], Any]] = {}

    try:
        with matrix_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != FIELDNAMES:
                raise ValueError(
                    f"CSV header {reader.fieldnames!r} != required {FIELDNAMES!r}"
                )
            for line_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise ValueError(f"line {line_number}: unexpected extra CSV fields")
                row = {key: value for key, value in raw_row.items()}
                if any(value is None or value == "" for value in row.values()):
                    raise ValueError(f"line {line_number}: empty CSV field")
                rows.append(row)
    except Exception as exc:
        errors.append(f"matrix parse failed: {type(exc).__name__}: {exc}")

    if not errors:
        ids = [row["claim_id"] for row in rows]
        if ids != EXPECTED_CLAIM_IDS:
            errors.append("claim IDs must be exactly C001..C047 in ascending order")
        if len(ids) != len(set(ids)):
            errors.append("duplicate claim IDs")

        for row in rows:
            claim_id = row["claim_id"]
            if row["status"] not in STATUSES:
                errors.append(f"{claim_id}: unsupported status {row['status']!r}")
            if row["allowed_now"] not in {"yes", "no"}:
                errors.append(f"{claim_id}: allowed_now must be yes or no")
            if row["allowed_now"] == "yes" and row["status"] not in ALLOWABLE_STATUSES:
                errors.append(f"{claim_id}: status cannot authorize a current claim")

            try:
                references = _strict_json_loads(row["current_evidence"])
                if not isinstance(references, list):
                    raise ValueError("current_evidence must be a JSON array")
                if _canonical_references(references) != row["current_evidence"]:
                    raise ValueError("current_evidence must use canonical JSON serialization")
                if row["allowed_now"] == "yes" and not references:
                    raise ValueError("allowed claim has no evidence references")
                if row["allowed_now"] == "no" and references:
                    raise ValueError("non-authorized claim must not cite current evidence")

                claim_refs: dict[tuple[str, str], Any] = {}
                for reference in references:
                    path, locator, value = _validate_reference(
                        reference, study_root=study_root, claim_id=claim_id
                    )
                    key = (path, locator)
                    if key in claim_refs:
                        raise ValueError("duplicate evidence reference")
                    claim_refs[key] = value
                resolved[claim_id] = claim_refs
            except Exception as exc:
                errors.append(f"{claim_id}: {type(exc).__name__}: {exc}")

    rows_by_id = {row["claim_id"]: row for row in rows}
    if not errors:
        try:
            _validate_special_claims(rows_by_id, resolved)
        except Exception as exc:
            errors.append(f"special claim validation failed: {type(exc).__name__}: {exc}")

    matrix_raw = matrix_path.read_bytes() if matrix_path.is_file() else b""
    return {
        "schema_version": "amy.claim-evidence-matrix-validation.v1",
        "valid": not errors,
        "decision": "VALID" if not errors else "INVALID",
        "matrix_path": os.path.relpath(matrix_path, study_root),
        "matrix_sha256": hashlib.sha256(matrix_raw).hexdigest(),
        "claim_count": len(rows),
        "allowed_claim_count": sum(row.get("allowed_now") == "yes" for row in rows),
        "resolved_reference_count": sum(len(values) for values in resolved.values()),
        "semantic_checks": {
            "c005_exact_primary_source_anchors": not errors,
            "c043_counts_derived_from_referenced_evidence": not errors,
        },
        "boundaries": {
            "evidence_identity_and_locator_resolution_only": True,
            "semantic_sufficiency_established_for_all_claims": False,
            "independent_review_performed": False,
            "scientific_claims_authorized_by_validator": False,
            "network_used": False,
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate_claim_evidence_matrix(args.matrix)
    if args.compact:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
