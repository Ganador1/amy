#!/usr/bin/env python3
"""Mechanically validate a retained model-review attempt set.

This validator checks byte identity and declared boundaries. It does not assess
model competence, verify findings, contact Ollama, or turn advisory text into
scientific evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import rfc8785


STUDY_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = STUDY_ROOT / "protocol/MODEL_REVIEW_PROTOCOL.json"
RESPONSE_SCHEMA_PATH = STUDY_ROOT / "schemas/model-review-response.schema.json"


class DuplicateKeyError(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(path: Path, *, require_jcs: bool = False) -> tuple[Any, bytes]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"not a regular non-symlink file: {path}")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=strict_object)
    if require_jcs and rfc8785.dumps(value) != raw:
        raise ValueError(f"file is not exact RFC 8785 JSON: {path}")
    return value, raw


def safe_child(batch: Path, relative: str) -> Path:
    logical = Path(relative)
    if logical.is_absolute() or ".." in logical.parts or not logical.parts:
        raise ValueError(f"unsafe batch-relative path: {relative}")
    path = batch / logical
    try:
        path.resolve().relative_to(batch.resolve())
    except ValueError as exc:
        raise ValueError(f"batch path escapes root: {relative}") from exc
    return path


def validate(batch: Path) -> dict[str, Any]:
    errors: list[str] = []
    batch = batch.resolve()
    try:
        metadata, metadata_raw = load(batch / "batch_metadata.jcs.json", require_jcs=True)
        summary, summary_raw = load(batch / "summary.jcs.json", require_jcs=True)
    except Exception as exc:
        return {
            "schema_version": "amy.model-review-batch-validation.v1",
            "classification": "same_worktree_mechanical_validation_not_independent_review",
            "valid": False,
            "errors": [f"batch root parse failure: {type(exc).__name__}: {exc}"],
            "batch_directory": str(batch),
            "attempt_count": 0,
            "request_hashes_match": False,
            "response_hashes_match": False,
            "separate_records_match_summary": False,
            "protocol_binding_matches": False,
            "response_schema_binding_matches": False,
            "source_inventory_commitments_match": False,
            "decision": "NO-GO",
            "boundaries": {
                "network_used": False,
                "model_findings_verified": False,
                "independent_review_performed": False,
                "manuscript_claims_authorized": False,
            },
        }

    protocol_sha = sha256(PROTOCOL_PATH.read_bytes())
    response_schema_sha = sha256(RESPONSE_SCHEMA_PATH.read_bytes())
    protocol_matches = (
        metadata.get("protocol", {}).get("sha256") == protocol_sha
        and summary.get("protocol_sha256") == protocol_sha
    )
    if not protocol_matches:
        errors.append("protocol SHA-256 binding differs")
    response_schema_matches = (
        metadata.get("response_schema", {}).get("sha256") == response_schema_sha
        and all(
            record.get("response_schema_sha256") == response_schema_sha
            for record in (summary.get("records") or [])
            if isinstance(record, dict)
        )
    )
    if not response_schema_matches:
        errors.append("response-schema SHA-256 binding differs")

    records = summary.get("records") or []
    if not isinstance(records, list):
        records = []
        errors.append("summary records is not an array")
    expected_slots = [f"MR-{index:02d}" for index in range(1, 11)]
    if [record.get("slot_id") for record in records if isinstance(record, dict)] != expected_slots:
        errors.append("attempt slots are missing, extra, duplicated, or out of order")

    request_hashes_match = True
    response_hashes_match = True
    records_match = True
    for record in records:
        if not isinstance(record, dict):
            records_match = False
            continue
        for field, aggregate in (
            ("request", "request"),
            ("response", "response"),
        ):
            commitment = record.get(field) or {}
            try:
                path = safe_child(batch, commitment["path"])
                raw = path.read_bytes()
                matches = (
                    len(raw) == commitment["bytes"]
                    and sha256(raw) == commitment["sha256"]
                )
                if field == "request":
                    request_hashes_match = request_hashes_match and matches
                    parsed = json.loads(raw, object_pairs_hook=strict_object)
                    request_hashes_match = request_hashes_match and rfc8785.dumps(parsed) == raw
                else:
                    response_hashes_match = response_hashes_match and matches
            except Exception as exc:
                if field == "request":
                    request_hashes_match = False
                else:
                    response_hashes_match = False
                errors.append(
                    f"{record.get('slot_id')} {aggregate} verification failed: "
                    f"{type(exc).__name__}: {exc}"
                )
        model_label = str(record.get("model_label", ""))
        stem = f"{record.get('slot_id')}-{model_label.replace(':', '_')}"
        record_path = batch / "records" / f"{stem}.jcs.json"
        try:
            separate, separate_raw = load(record_path, require_jcs=True)
            records_match = records_match and separate == record
            if rfc8785.dumps(record) != separate_raw:
                records_match = False
        except Exception as exc:
            records_match = False
            errors.append(
                f"{record.get('slot_id')} separate record failed: {type(exc).__name__}: {exc}"
            )
    if not request_hashes_match:
        errors.append("one or more request commitments differ")
    if not response_hashes_match:
        errors.append("one or more response commitments differ")
    if not records_match:
        errors.append("one or more separate records differ from summary")

    inventory = metadata.get("source_inventory") or []
    inventory_sha = sha256(rfc8785.dumps(inventory))
    inventory_matches = (
        inventory_sha == metadata.get("source_inventory_pre_sha256")
        and inventory_sha == summary.get("source_inventory_pre_sha256")
        and summary.get("source_inventory_pre_sha256")
        == summary.get("source_inventory_post_sha256")
        and summary.get("source_inventory_unchanged") is True
    )
    if not inventory_matches:
        errors.append("source inventory commitments differ")

    if summary.get("attempt_count") != len(records) or summary.get("slot_count") != 10:
        errors.append("attempt or slot count differs")
    if summary.get("http_success_count") == 0 and summary.get("closed_response_count") != 0:
        errors.append("closed response exists without HTTP success")
    boundaries = summary.get("boundaries") or {}
    required_false = (
        "retries_performed", "failed_slots_replaced", "confirmatory_inputs_read",
        "model_votes_used", "findings_verified", "independent_human_review_performed",
        "manuscript_claims_authorized",
    )
    if any(boundaries.get(field) is not False for field in required_false):
        errors.append("summary boundary differs from all-false contract")

    environment = metadata.get("environment") or {}
    for name in ("version", "tags"):
        path = batch / "environment" / f"api_{name}.raw.json"
        raw = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        if raw is None or sha256(raw) != environment.get(f"{name}_sha256"):
            errors.append(f"environment {name} response hash differs")

    return {
        "schema_version": "amy.model-review-batch-validation.v1",
        "classification": "same_worktree_mechanical_validation_not_independent_review",
        "valid": not errors,
        "errors": sorted(set(errors)),
        "batch_directory": str(batch),
        "metadata_sha256": sha256(metadata_raw),
        "summary_sha256": sha256(summary_raw),
        "attempt_count": len(records),
        "request_hashes_match": request_hashes_match,
        "response_hashes_match": response_hashes_match,
        "separate_records_match_summary": records_match,
        "protocol_binding_matches": protocol_matches,
        "response_schema_binding_matches": response_schema_matches,
        "source_inventory_commitments_match": inventory_matches,
        "batch_status": summary.get("status"),
        "http_success_count": summary.get("http_success_count"),
        "error_count": summary.get("error_count"),
        "closed_response_count": summary.get("closed_response_count"),
        "decision": "NO-GO",
        "boundaries": {
            "network_used": False,
            "model_findings_verified": False,
            "independent_review_performed": False,
            "manuscript_claims_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.batch)
    rendered = rfc8785.dumps(result)
    if args.output:
        with args.output.open("xb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
    else:
        print(rendered.decode("utf-8"))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
