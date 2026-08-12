#!/usr/bin/env python3
"""Independently validate a retained exploratory R0 clean-base build."""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.base_corpus import sha256_bytes, sha256_file, snapshot_tree


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in name
        and "\x00" not in name
    )


def validate_archive(archive_path: Path, release_root: Path) -> list[str]:
    errors: list[str] = []
    release_entries: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(release_root.rglob("*")):
        relative = path.relative_to(release_root).as_posix()
        if path.is_dir():
            release_entries[relative] = ("directory", None)
        elif path.is_file():
            release_entries[relative] = ("regular", path.read_bytes())
        else:
            errors.append(f"release contains unsupported object: {relative}")

    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            errors.append("archive contains duplicate member names")
        if names != sorted(names, key=lambda name: name.encode("utf-8")):
            errors.append("archive member order is not UTF-8 byte ascending")
        archive_entries: dict[str, tuple[str, bytes | None]] = {}
        for member in members:
            if not safe_member_name(member.name):
                errors.append(f"unsafe archive member: {member.name!r}")
                continue
            if member.uid != 0 or member.gid != 0 or member.uname or member.gname:
                errors.append(f"noncanonical owner metadata: {member.name}")
            if member.mtime != 0:
                errors.append(f"nonzero archive timestamp: {member.name}")
            if member.isdir():
                if member.mode != 0o755:
                    errors.append(f"noncanonical directory mode: {member.name}")
                archive_entries[member.name] = ("directory", None)
            elif member.isreg():
                if member.mode != 0o644:
                    errors.append(f"noncanonical regular-file mode: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    errors.append(f"regular archive member cannot be read: {member.name}")
                    continue
                archive_entries[member.name] = ("regular", extracted.read())
            else:
                errors.append(f"unsupported archive member type: {member.name}")
        if archive_entries != release_entries:
            missing = sorted(set(release_entries) - set(archive_entries))
            extra = sorted(set(archive_entries) - set(release_entries))
            changed = sorted(
                name
                for name in set(release_entries) & set(archive_entries)
                if release_entries[name] != archive_entries[name]
            )
            errors.append(
                f"archive/release mismatch: missing={missing}, extra={extra}, changed={changed}"
            )
    return errors


def validate(run: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary = load_json(run / "summary.json")
    input_registry = load_json(run / "base_registry_input.json")
    generated_registry = load_json(run / "base_registry_generated.json")
    schema = load_json(STUDY_ROOT / "schemas/manifest.schema.json")
    result_schema = load_json(STUDY_ROOT / "schemas/verifier-result.schema.json")
    result_validator = Draft202012Validator(result_schema)

    if summary.get("classification") != "exploratory_R0_base_inputs_only_no_adversarial_cases":
        errors.append("run classification is not exploratory R0-only")
    if summary.get("confirmatory_cases_generated") is not False:
        errors.append("run does not explicitly deny confirmatory case generation")
    if (run / "cases").exists() or (run / "expected_vs_observed.csv").exists():
        errors.append("R0 base run contains derived-case artifacts")
    if summary.get("input_registry_sha256") != sha256_file(run / "base_registry_input.json"):
        errors.append("input registry hash mismatch")
    if summary.get("fixture_policy_sha256") != sha256_file(
        run / "fixture_trust_policy.jcs.json"
    ):
        errors.append("fixture policy hash mismatch")
    if summary.get("license_notice_sha256") != sha256_file(
        run / "LICENSE-CC0-1.0-NOTICE.txt"
    ):
        errors.append("license notice hash mismatch")
    source_archive = run / str(summary.get("source_archive_path", ""))
    if not source_archive.is_file() or summary.get("source_archive_sha256") != sha256_file(
        source_archive
    ):
        errors.append("source archive hash mismatch")

    input_by_id = {base["id"]: base for base in input_registry.get("bases", [])}
    generated_by_id = {base["id"]: base for base in generated_registry.get("bases", [])}
    records = summary.get("base_records") or []
    if summary.get("base_count") != len(records):
        errors.append("summary base count mismatch")
    if set(input_by_id) != set(generated_by_id):
        errors.append("input/generated base ID sets differ")
    if {record.get("base_id") for record in records} != set(input_by_id):
        errors.append("summary/input base ID sets differ")

    validated_bases: list[dict[str, Any]] = []
    for record in records:
        base_id = record["base_id"]
        release_root = run / "bases" / base_id / "release"
        archive_path = run / record["archive_path"]
        if not release_root.is_dir() or not archive_path.is_file():
            errors.append(f"{base_id}: release or archive missing")
            continue
        archive_digest = sha256_file(archive_path)
        if archive_digest != record.get("archive_sha256"):
            errors.append(f"{base_id}: archive hash mismatch")
        if archive_path.stat().st_size != record.get("archive_bytes"):
            errors.append(f"{base_id}: archive size mismatch")
        errors.extend(f"{base_id}: {error}" for error in validate_archive(archive_path, release_root))

        actual_tree = snapshot_tree(release_root)
        retained_tree = load_json(run / "bases" / base_id / "tree.json")
        if actual_tree != retained_tree:
            errors.append(f"{base_id}: retained tree differs from release")
        tree_digest = sha256_bytes(rfc8785.dumps(actual_tree))
        if tree_digest != record.get("tree_sha256"):
            errors.append(f"{base_id}: tree hash mismatch")

        manifest_path = release_root / "MANIFEST.jcs.json"
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        if rfc8785.dumps(manifest) != manifest_raw:
            errors.append(f"{base_id}: manifest is not exact RFC 8785 JCS")
        manifest_errors = sorted(
            Draft202012Validator(schema).iter_errors(manifest),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if manifest_errors:
            errors.append(
                f"{base_id}: manifest schema errors: "
                + "; ".join(error.message for error in manifest_errors)
            )
        manifest_digest = sha256_bytes(manifest_raw)
        if manifest_digest != record.get("manifest_sha256"):
            errors.append(f"{base_id}: manifest hash mismatch")

        observed_files = {
            path.relative_to(release_root).as_posix(): path
            for path in release_root.rglob("*")
            if path.is_file() and path.name not in {"MANIFEST.jcs.json", "attestation.sigstore.json"}
        }
        declared_paths = {entry["path"] for entry in manifest.get("payloads", [])}
        if set(observed_files) != declared_paths:
            errors.append(f"{base_id}: closed-world payload inventory mismatch")
        for entry in manifest.get("payloads", []):
            path = observed_files.get(entry["path"])
            if path is None:
                continue
            if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
                errors.append(f"{base_id}: payload digest/size mismatch: {entry['path']}")

        generated = generated_by_id.get(base_id, {})
        expected_pairs = {
            "expected_base_archive_sha256": archive_digest,
            "expected_manifest_sha256": manifest_digest,
            "expected_tree_sha256": tree_digest,
        }
        for field, expected in expected_pairs.items():
            if generated.get(field) != expected:
                errors.append(f"{base_id}: generated registry {field} mismatch")
            if input_by_id.get(base_id, {}).get(field) is not None:
                warnings.append(f"{base_id}: input draft unexpectedly prefilled {field}")

        clean_results: dict[str, dict[str, str]] = {}
        for profile in ("P0", "P1", "P2", "P3"):
            result_path = run / "bases" / base_id / "clean_results" / f"{profile}.json"
            result = load_json(result_path)
            schema_errors = sorted(
                result_validator.iter_errors(result),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if schema_errors:
                errors.append(f"{base_id}/{profile}: invalid result schema")
            if (result.get("input") or {}).get("case_archive_sha256") != archive_digest:
                errors.append(f"{base_id}/{profile}: result/archive binding mismatch")
            observed = {
                "decision": result.get("decision"),
                "primary_reason": result.get("primary_reason"),
            }
            clean_results[profile] = observed
            if observed != {"decision": "ACCEPT", "primary_reason": "OK"}:
                errors.append(f"{base_id}/{profile}: clean base did not ACCEPT/OK")
            if record.get("clean_profile_results", {}).get(profile) != observed:
                errors.append(f"{base_id}/{profile}: summary/result mismatch")

        validated_bases.append(
            {
                "base_id": base_id,
                "archive_sha256": archive_digest,
                "manifest_sha256": manifest_digest,
                "tree_sha256": tree_digest,
                "payload_count": len(declared_paths),
                "clean_profile_results": clean_results,
            }
        )

    if summary.get("all_clean_profiles_accept") is not True:
        errors.append("summary does not assert all clean profiles accept")
    return {
        "valid": not errors,
        "classification": summary.get("classification"),
        "confirmatory_cases_generated": summary.get("confirmatory_cases_generated"),
        "base_count": len(validated_bases),
        "validated_bases": validated_bases,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.run)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
