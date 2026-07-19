#!/usr/bin/env python3
"""Run one frozen ten-slot Ollama review batch and retain every attempt.

The outputs are exploratory advisory records.  This harness cannot read
confirmatory roots, retry a failed slot, replace a model, synthesize findings,
or authorize changes to the protocol, oracle, compatibility matrix, or paper.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = STUDY_ROOT / "protocol/MODEL_REVIEW_PROTOCOL.json"
PROTOCOL_SCHEMA_PATH = STUDY_ROOT / "schemas/model-review-protocol.schema.json"
RESPONSE_SCHEMA_PATH = STUDY_ROOT / "schemas/model-review-response.schema.json"
MAX_SOURCE_BYTES_PER_SLOT = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
FORBIDDEN_INPUT_ROOTS = {
    "confirmatory", "confirmatory_outputs", "confirmatory_runs", "r1", "r2",
    "raw_results", "results", "robustness_runs", "selected_profile_base_runs",
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class DuplicateKeyError(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> tuple[Any, bytes]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"input is not a regular non-symlink file: {path}")
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=strict_object), raw


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    rendered = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    if not rendered or not SAFE_NAME.fullmatch(rendered):
        raise ValueError(f"unsafe slug source: {value!r}")
    return rendered


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def validate_endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("endpoint must be an HTTP loopback Ollama endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint credentials, query, and fragment are forbidden")
    if parsed.port not in {None, 11434}:
        raise ValueError("endpoint port must be 11434")
    return value.rstrip("/")


def load_contracts() -> tuple[dict[str, Any], bytes, dict[str, Any], bytes]:
    protocol, protocol_raw = load_json(PROTOCOL_PATH)
    protocol_schema, _ = load_json(PROTOCOL_SCHEMA_PATH)
    response_schema, response_schema_raw = load_json(RESPONSE_SCHEMA_PATH)
    Draft202012Validator.check_schema(protocol_schema)
    Draft202012Validator.check_schema(response_schema)
    errors = list(Draft202012Validator(protocol_schema).iter_errors(protocol))
    if errors:
        raise ValueError(f"model-review protocol schema failure: {errors[0].message}")
    keys = protocol["response_contract"]["required_top_level_keys"]
    if keys != list(response_schema["required"]):
        raise ValueError("protocol response keys differ from response schema")
    slots = protocol["review_slots"]
    if [slot["slot_id"] for slot in slots] != [f"MR-{index:02d}" for index in range(1, 11)]:
        raise ValueError("review slots must be MR-01 through MR-10 in order")
    if len({slot["model_label"] for slot in slots}) != 10:
        raise ValueError("review model labels must be unique")
    return protocol, protocol_raw, response_schema, response_schema_raw


def safe_source(relative: str) -> tuple[bytes, dict[str, Any]]:
    logical = Path(relative)
    if logical.is_absolute() or ".." in logical.parts or not logical.parts:
        raise ValueError(f"unsafe source path: {relative}")
    if logical.parts[0] in FORBIDDEN_INPUT_ROOTS:
        raise ValueError(f"forbidden review input root: {relative}")
    path = STUDY_ROOT / logical
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"review source is not a regular non-symlink file: {relative}")
    raw = path.read_bytes()
    raw.decode("utf-8", errors="strict")
    return raw, {"path": relative, "bytes": len(raw), "sha256": sha256(raw)}


def slot_sources(protocol: Mapping[str, Any], slot: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    ordered: list[str] = []
    seen: set[str] = set()
    for relative in [*protocol["common_source_paths"], *slot["source_paths"]]:
        if relative not in seen:
            ordered.append(relative)
            seen.add(relative)
    blocks: list[str] = []
    inventory: list[dict[str, Any]] = []
    total = 0
    for relative in ordered:
        raw, record = safe_source(relative)
        total += len(raw)
        if total > MAX_SOURCE_BYTES_PER_SLOT:
            raise ValueError(f"{slot['slot_id']} source corpus exceeds byte limit")
        inventory.append(record)
        blocks.append(f"\n===== {relative} | sha256={record['sha256']} =====\n{raw.decode('utf-8')}\n")
    return "".join(blocks), inventory


def union_inventory(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    paths = {
        relative
        for slot in protocol["review_slots"]
        for relative in [*protocol["common_source_paths"], *slot["source_paths"]]
    }
    return [safe_source(relative)[1] for relative in sorted(paths, key=lambda item: item.encode("utf-8"))]


def fetch_raw(url: str, timeout: float) -> tuple[int | None, bytes, str | None, bool]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            complete = len(raw) <= MAX_RESPONSE_BYTES
            return response.status, raw[:MAX_RESPONSE_BYTES], None if complete else "RESPONSE_LIMIT_EXCEEDED", complete
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        complete = len(raw) <= MAX_RESPONSE_BYTES
        return exc.code, raw[:MAX_RESPONSE_BYTES], f"HTTPError: {exc}", complete
    except Exception as exc:
        return None, b"", f"{type(exc).__name__}: {exc}", True


def request_payload(
    protocol: Mapping[str, Any],
    protocol_sha256: str,
    response_schema: Mapping[str, Any],
    response_schema_sha256: str,
    slot: Mapping[str, Any],
) -> tuple[bytes, list[dict[str, Any]]]:
    corpus, inventory = slot_sources(protocol, slot)
    task = protocol["response_contract"]["task_template"].format(
        question=slot["question"]
    )
    user = (
        f"protocol_id={protocol['protocol_id']}\n"
        f"protocol_sha256={protocol_sha256}\n"
        f"slot_id={slot['slot_id']}\n"
        f"role={slot['role']}\n"
        f"response_schema_sha256={response_schema_sha256}\n\n"
        f"{task}\n\nSUPPLIED CURRENT BYTES FOLLOW\n{corpus}\nEND SUPPLIED CURRENT BYTES"
    )
    execution = protocol["execution"]
    payload = {
        "model": slot["model_label"],
        "messages": [
            {"role": "system", "content": protocol["response_contract"]["system_prompt"]},
            {"role": "user", "content": user},
        ],
        "stream": execution["stream"],
        "think": execution["think"],
        "format": dict(response_schema),
        "options": {
            "temperature": execution["temperature"],
            "num_predict": execution["num_predict"],
        },
    }
    return rfc8785.dumps(payload), inventory


def run_slot(
    *,
    endpoint: str,
    batch_dir: Path,
    protocol: Mapping[str, Any],
    protocol_sha256: str,
    response_schema: Mapping[str, Any],
    response_schema_sha256: str,
    slot: Mapping[str, Any],
) -> dict[str, Any]:
    slot_id = slot["slot_id"]
    label_slug = slug(slot["model_label"])
    stem = f"{slot_id}-{label_slug}"
    request_raw, inventory = request_payload(
        protocol, protocol_sha256, response_schema, response_schema_sha256, slot
    )
    request_path = batch_dir / "requests" / f"{stem}.jcs.json"
    response_path = batch_dir / "responses" / f"{stem}.raw.json"
    write_new(request_path, request_raw)
    started_at = utc_now()
    started_ns = time.monotonic_ns()
    status: int | None = None
    error: str | None = None
    response_raw = b""
    response_complete = True
    try:
        request = urllib.request.Request(
            f"{endpoint}/api/chat",
            data=request_raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            request, timeout=protocol["execution"]["timeout_seconds"]
        ) as response:
            status = response.status
            observed = response.read(MAX_RESPONSE_BYTES + 1)
            response_complete = len(observed) <= MAX_RESPONSE_BYTES
            response_raw = observed[:MAX_RESPONSE_BYTES]
            if not response_complete:
                error = "RESPONSE_LIMIT_EXCEEDED"
    except urllib.error.HTTPError as exc:
        status = exc.code
        observed = exc.read(MAX_RESPONSE_BYTES + 1)
        response_complete = len(observed) <= MAX_RESPONSE_BYTES
        response_raw = observed[:MAX_RESPONSE_BYTES]
        error = f"HTTPError: {exc}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    ended_at = utc_now()
    elapsed_us = (time.monotonic_ns() - started_ns) // 1000
    write_new(response_path, response_raw)

    envelope: Any = None
    content_raw: bytes | None = None
    content_schema_valid = False
    content_errors: list[str] = []
    provider: dict[str, Any] = {
        "reported_model": None,
        "created_at": None,
        "done_reason": None,
    }
    if response_raw:
        try:
            envelope = json.loads(response_raw, object_pairs_hook=strict_object)
            provider = {
                "reported_model": envelope.get("model"),
                "created_at": envelope.get("created_at"),
                "done_reason": envelope.get("done_reason"),
            }
            content = ((envelope.get("message") or {}).get("content"))
            if isinstance(content, str):
                content_raw = content.encode("utf-8")
                parsed_content = json.loads(content, object_pairs_hook=strict_object)
                schema_errors = list(
                    Draft202012Validator(response_schema).iter_errors(parsed_content)
                )
                content_errors = sorted(error.message for error in schema_errors)
                content_schema_valid = not schema_errors
            else:
                content_errors = ["assistant message content is not a string"]
        except Exception as exc:
            content_errors = [f"{type(exc).__name__}: {exc}"]

    record = {
        "schema_version": "amy.model-review-attempt-record.v1",
        "classification": "exploratory_advisory_not_scientific_evidence",
        "slot_id": slot_id,
        "model_label": slot["model_label"],
        "role": slot["role"],
        "protocol_sha256": protocol_sha256,
        "response_schema_sha256": response_schema_sha256,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_us": elapsed_us,
        "http_status": status,
        "error": error,
        "request": {
            "path": request_path.relative_to(batch_dir).as_posix(),
            "bytes": len(request_raw),
            "sha256": sha256(request_raw),
        },
        "response": {
            "path": response_path.relative_to(batch_dir).as_posix(),
            "bytes": len(response_raw),
            "sha256": sha256(response_raw),
            "complete_within_limit": response_complete,
        },
        "source_inventory": inventory,
        "assistant_content": {
            "present": content_raw is not None,
            "bytes": len(content_raw or b""),
            "sha256": sha256(content_raw or b""),
            "closed_schema_valid": content_schema_valid,
            "validation_errors": content_errors,
        },
        "provider_reported": provider,
        "boundaries": {
            "attempt_number": 1,
            "retry_performed": False,
            "replacement_model_used": False,
            "confirmatory_inputs_read": False,
            "model_output_is_ground_truth": False,
            "independent_human_review_performed": False,
            "manuscript_claims_authorized": False,
        },
    }
    write_new(
        batch_dir / "records" / f"{stem}.jcs.json", rfc8785.dumps(record)
    )
    return record


def validate_only() -> dict[str, Any]:
    protocol, protocol_raw, response_schema, response_schema_raw = load_contracts()
    inventory = union_inventory(protocol)
    prepared = []
    for slot in protocol["review_slots"]:
        raw, sources = request_payload(
            protocol, sha256(protocol_raw), response_schema,
            sha256(response_schema_raw), slot
        )
        prepared.append(
            {
                "slot_id": slot["slot_id"],
                "model_label": slot["model_label"],
                "request_bytes": len(raw),
                "request_sha256": sha256(raw),
                "source_count": len(sources),
            }
        )
    return {
        "valid": True,
        "protocol_sha256": sha256(protocol_raw),
        "response_schema_sha256": sha256(response_schema_raw),
        "slot_count": len(prepared),
        "union_source_count": len(inventory),
        "union_source_inventory_sha256": sha256(rfc8785.dumps(inventory)),
        "prepared_requests": prepared,
        "confirmatory_inputs_read": False,
        "network_used": False,
        "manuscript_claims_authorized": False,
    }


def run(endpoint: str, output_root: Path) -> dict[str, Any]:
    endpoint = validate_endpoint(endpoint)
    protocol, protocol_raw, response_schema, response_schema_raw = load_contracts()
    protocol_sha = sha256(protocol_raw)
    response_schema_sha = sha256(response_schema_raw)
    inventory_before = union_inventory(protocol)
    inventory_before_sha = sha256(rfc8785.dumps(inventory_before))
    batch_id = datetime.now(timezone.utc).strftime("model_review_%Y%m%dT%H%M%SZ")
    batch_dir = output_root / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)

    version_status, version_raw, version_error, version_complete = fetch_raw(
        f"{endpoint}/api/version", 10.0
    )
    tags_status, tags_raw, tags_error, tags_complete = fetch_raw(
        f"{endpoint}/api/tags", 30.0
    )
    write_new(batch_dir / "environment" / "api_version.raw.json", version_raw)
    write_new(batch_dir / "environment" / "api_tags.raw.json", tags_raw)
    metadata = {
        "schema_version": "amy.model-review-batch-metadata.v1",
        "classification": "exploratory_advisory_not_scientific_evidence",
        "batch_id": batch_id,
        "started_at": utc_now(),
        "endpoint": endpoint,
        "protocol": {"path": PROTOCOL_PATH.relative_to(STUDY_ROOT).as_posix(), "sha256": protocol_sha},
        "response_schema": {"path": RESPONSE_SCHEMA_PATH.relative_to(STUDY_ROOT).as_posix(), "sha256": response_schema_sha},
        "source_inventory_pre_sha256": inventory_before_sha,
        "source_inventory": inventory_before,
        "environment": {
            "version_http_status": version_status,
            "version_error": version_error,
            "version_response_complete": version_complete,
            "version_sha256": sha256(version_raw),
            "tags_http_status": tags_status,
            "tags_error": tags_error,
            "tags_response_complete": tags_complete,
            "tags_sha256": sha256(tags_raw),
        },
        "boundaries": {
            "confirmatory_inputs_read": False,
            "confirmatory_outputs_read": False,
            "model_outputs_are_ground_truth": False,
            "manuscript_claims_authorized": False,
        },
    }
    write_new(batch_dir / "batch_metadata.jcs.json", rfc8785.dumps(metadata))

    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [
            pool.submit(
                run_slot,
                endpoint=endpoint,
                batch_dir=batch_dir,
                protocol=protocol,
                protocol_sha256=protocol_sha,
                response_schema=response_schema,
                response_schema_sha256=response_schema_sha,
                slot=slot,
            )
            for slot in protocol["review_slots"]
        ]
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: item["slot_id"])
    inventory_after = union_inventory(protocol)
    inventory_after_sha = sha256(rfc8785.dumps(inventory_after))
    unchanged = inventory_after == inventory_before
    http_success_count = sum(record["http_status"] == 200 for record in records)
    error_count = sum(record["error"] is not None for record in records)
    closed_response_count = sum(
        record["assistant_content"]["closed_schema_valid"] for record in records
    )
    if not unchanged or len(records) != 10:
        batch_status = "INVALID_INCOMPLETE_OR_SOURCE_DRIFT"
    elif http_success_count == 10 and error_count == 0 and closed_response_count == 10:
        batch_status = "COMPLETE_ADVISORY_BATCH"
    else:
        batch_status = "COMPLETE_ATTEMPT_SET_WITH_FAILURES"
    summary = {
        "schema_version": "amy.model-review-batch-summary.v1",
        "classification": "exploratory_advisory_not_scientific_evidence",
        "batch_id": batch_id,
        "ended_at": utc_now(),
        "protocol_sha256": protocol_sha,
        "slot_count": 10,
        "attempt_count": len(records),
        "http_success_count": http_success_count,
        "error_count": error_count,
        "closed_response_count": closed_response_count,
        "source_inventory_pre_sha256": inventory_before_sha,
        "source_inventory_post_sha256": inventory_after_sha,
        "source_inventory_unchanged": unchanged,
        "records": records,
        "status": batch_status,
        "boundaries": {
            "retries_performed": False,
            "failed_slots_replaced": False,
            "confirmatory_inputs_read": False,
            "model_votes_used": False,
            "findings_verified": False,
            "independent_human_review_performed": False,
            "manuscript_claims_authorized": False,
        },
    }
    write_new(batch_dir / "summary.jcs.json", rfc8785.dumps(summary))
    return {"batch_directory": str(batch_dir), **summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--output-root", type=Path, default=STUDY_ROOT / "reviews")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    result = validate_only() if args.validate_only else run(args.endpoint, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
