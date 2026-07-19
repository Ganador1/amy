#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import stat
import tarfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate(run: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    if summary.get("pilot_only") is not True or summary.get("confirmatory_evidence") is not False:
        errors.append("run is not explicitly marked pilot-only/non-confirmatory")

    contract_ledger_path = run / "contract_hashes.json"
    result_ledger_path = run / "result_hashes.json"
    matrix_path = run / "expected_vs_observed.csv"
    if sha256(contract_ledger_path) != summary.get("contract_hash_ledger_sha256"):
        errors.append("contract hash ledger differs from summary")
    if sha256(result_ledger_path) != summary.get("result_hash_ledger_sha256"):
        errors.append("result hash ledger differs from summary")
    if sha256(matrix_path) != summary.get("matrix_sha256"):
        errors.append("matrix differs from summary")

    contract_records = json.loads(contract_ledger_path.read_text(encoding="utf-8"))
    for record in contract_records:
        path = run / "contracts" / record["path"]
        if not path.is_file():
            errors.append(f"missing archived contract: {record['path']}")
            continue
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            errors.append(f"archived contract hash/size mismatch: {record['path']}")

    catalog_path = run / "contracts" / "protocol" / "ATTACK_CATALOG.json"
    schema_path = run / "contracts" / "schemas" / "verifier-result.schema.json"
    if sha256(catalog_path) != summary.get("catalog_sha256"):
        errors.append("archived catalog differs from summary")
    if sha256(run / "pilot_fixture_trust_policy.jcs.json") != summary.get("trust_policy_sha256"):
        errors.append("fixture trust policy differs from summary")
    if sha256(run / "source" / "pilot_source.tar") != summary.get("source_archive_sha256"):
        errors.append("source archive differs from summary")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_by_id = {case["id"]: case for case in catalog["cases"]}
    result_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result_validator = Draft202012Validator(result_schema)
    result_ledger = json.loads(result_ledger_path.read_text(encoding="utf-8"))
    result_hash_by_path = {record["path"]: record for record in result_ledger}
    if len(result_hash_by_path) != len(result_ledger):
        errors.append("result hash ledger contains duplicate paths")

    actual_results: dict[tuple[str, str], dict[str, Any]] = {}
    for relative, record in result_hash_by_path.items():
        path = run / relative
        if not path.is_file():
            errors.append(f"missing result: {relative}")
            continue
        if path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            errors.append(f"result hash/size mismatch: {relative}")
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            errors.append(f"result remained writable: {relative}")
        result = json.loads(path.read_text(encoding="utf-8"))
        schema_errors = list(result_validator.iter_errors(result))
        if schema_errors:
            errors.append(
                f"result schema failure {relative}: "
                + "; ".join(error.message for error in schema_errors)
            )
        key = (result.get("case_id"), result.get("profile_id"))
        if key in actual_results:
            errors.append(f"duplicate result key: {key}")
        actual_results[key] = result

    expected_keys = {
        (case_id, profile)
        for case_id in catalog_by_id
        for profile in ("P0", "P1", "P2", "P3")
    }
    if set(actual_results) != expected_keys:
        missing = sorted(expected_keys - set(actual_results))
        extra = sorted(set(actual_results) - expected_keys)
        errors.append(f"result key set mismatch; missing={missing}, extra={extra}")

    with matrix_path.open(encoding="utf-8", newline="") as handle:
        matrix_rows = list(csv.DictReader(handle))
    matrix_by_key = {(row["case_id"], row["profile_id"]): row for row in matrix_rows}
    if len(matrix_by_key) != len(matrix_rows) or set(matrix_by_key) != expected_keys:
        errors.append("matrix key set is incomplete or duplicated")

    conformance_mismatches = 0
    target_misses = 0
    clean_failures = 0
    for key in sorted(expected_keys):
        case_id, profile = key
        case = catalog_by_id[case_id]
        expected = case["profile_expectations"][profile]
        observed = actual_results.get(key)
        row = matrix_by_key.get(key)
        if observed is None or row is None:
            continue
        conforms = (
            observed["decision"] == expected["decision"]
            and observed["primary_reason"] == expected["primary_reason"]
        )
        target_miss = (
            (case["target_decision"] == "REJECT" and observed["decision"] != "REJECT")
            or (case["target_decision"] == "ACCEPT" and observed["decision"] != "ACCEPT")
        )
        clean_failure = case["kind"] == "clean" and observed["decision"] != "ACCEPT"
        conformance_mismatches += int(not conforms)
        target_misses += int(target_miss)
        clean_failures += int(clean_failure)
        expected_row_values = {
            "expected_decision": expected["decision"],
            "expected_primary_reason": expected["primary_reason"],
            "observed_decision": observed["decision"],
            "observed_primary_reason": observed["primary_reason"],
            "profile_conforms": str(conforms).lower(),
            "target_miss": str(target_miss).lower(),
            "clean_failure": str(clean_failure).lower(),
            "result_sha256": sha256(
                run / "results" / case_id / f"{profile}.json"
            ),
        }
        for field, expected_value in expected_row_values.items():
            if row[field] != expected_value:
                errors.append(f"matrix mismatch {case_id}/{profile}/{field}")

    for field, observed_value in (
        ("profile_conformance_mismatches", conformance_mismatches),
        ("target_misses_across_all_profiles", target_misses),
        ("clean_failures", clean_failures),
        ("result_count", len(actual_results)),
        ("case_count", len(catalog_by_id)),
    ):
        if summary.get(field) != observed_value:
            errors.append(f"summary field {field} differs from recomputation")

    private_markers = (b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
    policy_raw = (run / "pilot_fixture_trust_policy.jcs.json").read_bytes()
    if any(marker in policy_raw for marker in private_markers):
        errors.append("fixture trust policy contains PEM private key material")

    for case_id in sorted(catalog_by_id):
        archive_path = run / "archives" / f"{case_id}.tar"
        mutation_path = run / "cases" / case_id / "mutation_record.json"
        mutation = json.loads(mutation_path.read_text(encoding="utf-8"))
        archive_hash = sha256(archive_path)
        if mutation.get("archive_sha256") != archive_hash:
            errors.append(f"case archive hash mismatch: {case_id}")
        for profile in ("P0", "P1", "P2", "P3"):
            result = actual_results.get((case_id, profile))
            if result and result["input"]["case_archive_sha256"] != archive_hash:
                errors.append(f"result/archive binding mismatch: {case_id}/{profile}")
        with tarfile.open(archive_path) as archive:
            seen_names: set[str] = set()
            for member in archive.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    errors.append(f"unsafe archive member name: {case_id}/{member.name}")
                if member.name in seen_names:
                    errors.append(f"duplicate archive member: {case_id}/{member.name}")
                seen_names.add(member.name)
                if member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        raw = extracted.read()
                        if any(marker in raw for marker in private_markers):
                            errors.append(f"case archive contains PEM private key: {case_id}/{member.name}")

    return {
        "valid": not errors,
        "run": str(run),
        "case_count": len(catalog_by_id),
        "result_count": len(actual_results),
        "profile_conformance_mismatches": conformance_mismatches,
        "target_misses_across_all_profiles": target_misses,
        "clean_failures": clean_failures,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.run.resolve())
    print(json.dumps(result, indent=None if args.compact else 2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
