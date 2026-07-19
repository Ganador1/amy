#!/usr/bin/env python3
"""Separately replay a retained selected-profile clean-base R0 run."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.base_corpus import (
    CC0_NOTICE,
    render_recipe,
    sha256_bytes,
    sha256_file,
    snapshot_tree,
)
from amy_verifier.model import CHECK_NAMES, PROFILE_CHECKS
from amy_verifier.selected_profile_fixture import (
    selected_fixture_policy,
    verify_selected_fixture_release,
)


BASE_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
OVERLAY = STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json"
MANIFEST_SCHEMA = STUDY_ROOT / "schemas/manifest-production-v0.2.schema.json"
RESULT_SCHEMA = STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_member_name(name: str) -> bool:
    logical = PurePosixPath(name)
    return (
        bool(name)
        and not logical.is_absolute()
        and all(part not in {"", ".", ".."} for part in logical.parts)
        and "\\" not in name
        and "\x00" not in name
    )


def _render_overlay_payload(specification: dict[str, Any]) -> bytes:
    """Independent renderer for the deliberately tiny overlay recipe language."""

    if "utf8_text" in specification:
        text = specification["utf8_text"]
        if not isinstance(text, str):
            raise ValueError("overlay utf8_text is not a string")
        return text.encode("utf-8")
    recipe = specification.get("recipe")
    if not isinstance(recipe, dict) or recipe.get("type") != "ustar_single_utf8_file_v1":
        raise ValueError("unsupported overlay recipe")
    name = recipe.get("member_path")
    text = recipe.get("utf8_text")
    if not isinstance(name, str) or not _safe_member_name(name) or not isinstance(text, str):
        raise ValueError("invalid deterministic USTAR recipe")
    raw = text.encode("utf-8")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo(name)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.mode = 0o644
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def _archive_entries(archive_path: Path) -> tuple[dict[str, tuple[str, bytes | None]], list[str]]:
    errors: list[str] = []
    entries: dict[str, tuple[str, bytes | None]] = {}
    try:
        archive = tarfile.open(archive_path, "r:")
    except (tarfile.TarError, OSError) as exc:
        return {}, [f"archive cannot be parsed: {type(exc).__name__}: {exc}"]
    with archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            errors.append("archive contains duplicate member names")
        if names != sorted(names, key=lambda value: value.encode("utf-8")):
            errors.append("archive member order is not UTF-8 byte ascending")
        for member in members:
            if not _safe_member_name(member.name):
                errors.append(f"unsafe archive member: {member.name!r}")
                continue
            if member.uid != 0 or member.gid != 0 or member.uname or member.gname:
                errors.append(f"noncanonical owner metadata: {member.name}")
            if member.mtime != 0:
                errors.append(f"nonzero archive timestamp: {member.name}")
            if member.isdir():
                if member.mode != 0o755:
                    errors.append(f"noncanonical directory mode: {member.name}")
                entries[member.name] = ("directory", None)
            elif member.isreg():
                if member.mode != 0o644:
                    errors.append(f"noncanonical regular-file mode: {member.name}")
                handle = archive.extractfile(member)
                if handle is None:
                    errors.append(f"regular member cannot be read: {member.name}")
                    continue
                entries[member.name] = ("regular", handle.read())
            else:
                errors.append(f"unsupported archive member type: {member.name}")
    return entries, errors


def _release_entries(root: Path) -> tuple[dict[str, tuple[str, bytes | None]], list[str]]:
    entries: dict[str, tuple[str, bytes | None]] = {}
    errors: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and not path.is_symlink():
            entries[relative] = ("directory", None)
        elif path.is_file() and not path.is_symlink():
            entries[relative] = ("regular", path.read_bytes())
        else:
            errors.append(f"release contains unsupported object: {relative}")
    return entries, errors


def _expected_build_metadata(policy: dict[str, Any]) -> dict[str, Any]:
    assertions = policy["provenance"]["manifest_assertions"]
    source = assertions["source"]
    snapshot = source["snapshot"]
    return {
        "schema_version": policy["manifest"]["build_metadata_schema_version"],
        "assertion_scope": policy["manifest"]["assertion_scope"],
        "source": {
            "repository_uri": source["repository_uri"],
            "revision": source["revision"],
            "ref": source["ref"],
            "git_object_format": source["git_object_format"],
            "tree": source["tree"],
            "dirty": source["dirty"],
            "snapshot": {
                "path": snapshot["path"],
                "sha256": snapshot["sha256"],
                "format": snapshot["format"],
                "assurance": snapshot["assurance"],
            },
        },
        "dependency_lock": {
            "path": assertions["dependency_lock"]["path"],
            "sha256": assertions["dependency_lock"]["sha256"],
        },
        "execution_image": dict(assertions["execution_image"]),
    }


def _expected_payloads(
    base: dict[str, Any], overlay: dict[str, Any]
) -> dict[str, tuple[bytes, str, str]]:
    expected: dict[str, tuple[bytes, str, str]] = {}
    for entry in base["payloads"]:
        path = entry["path"]
        if path in expected:
            raise ValueError(f"{base['id']}: duplicate blueprint path")
        expected[path] = (
            render_recipe(entry["recipe"]),
            entry["media_type"],
            entry["role"],
        )
    for name, fixture in overlay["payload_fixtures"].items():
        path = fixture["path"]
        if path in expected:
            raise ValueError(f"{base['id']}: fixture/blueprint path collision: {path}")
        raw = _render_overlay_payload(fixture)
        if len(raw) != fixture["bytes"] or sha256_bytes(raw) != fixture["sha256"]:
            raise ValueError(f"overlay fixture declaration mismatch: {name}")
        expected[path] = (raw, fixture["media_type"], fixture["role"])
    return expected


def _validate_source_archive(
    run: Path, summary: dict[str, Any]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    current_source_drift: list[str] = []
    archive_path = run / str(summary.get("source_archive_path", ""))
    manifest_path = run / str(summary.get("source_manifest_path", ""))
    if not archive_path.is_file() or not manifest_path.is_file():
        return ["source archive or source manifest is missing"], current_source_drift
    if sha256_file(archive_path) != summary.get("source_archive_sha256"):
        errors.append("source archive hash mismatch")
    if sha256_file(manifest_path) != summary.get("source_manifest_sha256"):
        errors.append("source manifest hash mismatch")
    records = load_json(manifest_path)
    record_by_path = {record.get("path"): record for record in records}
    if len(record_by_path) != len(records):
        errors.append("source manifest contains duplicate paths")
    entries, archive_errors = _archive_entries(archive_path)
    errors.extend(f"source {error}" for error in archive_errors)
    regular = {name: raw for name, (kind, raw) in entries.items() if kind == "regular"}
    if set(regular) != set(record_by_path):
        errors.append("source archive/member-manifest path sets differ")
    if any(kind != "regular" for kind, _ in entries.values()):
        errors.append("source archive unexpectedly contains directories")
    for logical, record in record_by_path.items():
        raw = regular.get(logical)
        if raw is None:
            continue
        if len(raw) != record.get("bytes") or sha256_bytes(raw) != record.get("sha256"):
            errors.append(f"source archive record mismatch: {logical}")
        current = STUDY_ROOT / str(logical)
        if not current.is_file() or current.read_bytes() != raw:
            current_source_drift.append(str(logical))
    return errors, sorted(current_source_drift)


def validate(run: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary = load_json(run / "summary.json")
    registry = load_json(run / "base_registry_input.json")
    overlay = load_json(run / "selected_fixture_overlay_input.json")
    current_registry = load_json(BASE_REGISTRY)
    current_overlay = load_json(OVERLAY)
    policy = selected_fixture_policy(OVERLAY)
    manifest_schema = load_json(MANIFEST_SCHEMA)
    result_schema = load_json(RESULT_SCHEMA)
    result_validator = Draft202012Validator(result_schema)

    expected_classification = (
        "exploratory_R0_selected_profile_clean_bases_no_adversarial_cases"
    )
    if summary.get("classification") != expected_classification:
        errors.append("selected base run classification differs")
    if summary.get("confirmatory_cases_generated") is not False:
        errors.append("run does not deny confirmatory case generation")
    if summary.get("confirmatory_outcomes_read") is not False:
        errors.append("run does not deny confirmatory outcome access")
    if summary.get("production_sigstore_conformance") is not False:
        errors.append("controlled fixture is mislabeled as production Sigstore")
    if (run / "cases").exists() or (run / "expected_vs_observed.csv").exists():
        errors.append("clean-base run contains derived-case artifacts")
    if registry != current_registry or overlay != current_overlay:
        errors.append("retained selected-base inputs differ from current draft inputs")

    effective_policy_path = run / "effective_fixture_policy.jcs.json"
    if not effective_policy_path.is_file():
        errors.append("effective fixture policy is missing")
    elif effective_policy_path.read_bytes() != rfc8785.dumps(policy):
        errors.append("retained effective fixture policy differs from deterministic replay")
    expected_input_hashes = {
        "base_registry": sha256_file(BASE_REGISTRY),
        "selected_fixture_overlay": sha256_file(OVERLAY),
        "effective_fixture_policy": sha256_file(effective_policy_path),
        "manifest_schema": sha256_file(MANIFEST_SCHEMA),
        "result_schema": sha256_file(RESULT_SCHEMA),
    }
    if summary.get("input_sha256") != expected_input_hashes:
        errors.append("selected base run input hashes differ")
    if summary.get("license_notice_sha256") != sha256_bytes(CC0_NOTICE):
        errors.append("license notice declaration differs")
    if not (run / "LICENSE-CC0-1.0-NOTICE.txt").is_file() or sha256_file(
        run / "LICENSE-CC0-1.0-NOTICE.txt"
    ) != sha256_bytes(CC0_NOTICE):
        errors.append("retained license notice differs")
    source_archive_errors, current_source_drift = _validate_source_archive(run, summary)
    errors.extend(source_archive_errors)
    if current_source_drift:
        warnings.append(
            "retained source snapshot differs from the current study source at "
            f"{len(current_source_drift)} path(s): {', '.join(current_source_drift)}"
        )

    base_by_id = {base["id"]: base for base in registry.get("bases") or []}
    records = summary.get("base_records") or []
    if summary.get("base_count") != 6 or len(records) != 6:
        errors.append("selected run does not contain exactly six base records")
    if [record.get("base_id") for record in records] != sorted(base_by_id):
        errors.append("selected run records are not the sorted complete base set")

    validated_bases: list[dict[str, Any]] = []
    for record in records:
        base_id = record.get("base_id")
        base = base_by_id.get(base_id)
        if base is None:
            continue
        release_root = run / "bases" / base_id / "release"
        archive_path = run / str(record.get("archive_path", ""))
        if not release_root.is_dir() or not archive_path.is_file():
            errors.append(f"{base_id}: release or archive is missing")
            continue
        release_entries, release_errors = _release_entries(release_root)
        archive_entries, archive_errors = _archive_entries(archive_path)
        errors.extend(f"{base_id}: {error}" for error in release_errors + archive_errors)
        if archive_entries != release_entries:
            errors.append(f"{base_id}: deterministic archive differs from release tree")
        if sha256_file(archive_path) != record.get("archive_sha256"):
            errors.append(f"{base_id}: archive hash mismatch")
        if archive_path.stat().st_size != record.get("archive_bytes"):
            errors.append(f"{base_id}: archive byte count mismatch")

        retained_tree = load_json(run / "bases" / base_id / "tree.json")
        actual_tree = snapshot_tree(release_root)
        if retained_tree != actual_tree:
            errors.append(f"{base_id}: retained tree differs from release")
        tree_sha256 = sha256_bytes(rfc8785.dumps(actual_tree))
        if tree_sha256 != record.get("tree_sha256"):
            errors.append(f"{base_id}: tree hash mismatch")

        manifest_path = release_root / "MANIFEST.jcs.json"
        attestation_path = release_root / "attestation.sigstore.json"
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        if rfc8785.dumps(manifest) != manifest_raw:
            errors.append(f"{base_id}: manifest is not exact RFC 8785 JCS")
        schema_errors = sorted(
            Draft202012Validator(manifest_schema).iter_errors(manifest),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if schema_errors:
            errors.append(f"{base_id}: production manifest schema validation failed")
        if manifest.get("release") != base["release"]:
            errors.append(f"{base_id}: release identity differs from blueprint")
        if manifest.get("build_metadata") != _expected_build_metadata(policy):
            errors.append(f"{base_id}: selected build metadata differs from policy")

        try:
            expected_payloads = _expected_payloads(base, overlay)
        except ValueError as exc:
            errors.append(str(exc))
            expected_payloads = {}
        payload_entries = {entry.get("path"): entry for entry in manifest.get("payloads") or []}
        if len(payload_entries) != len(manifest.get("payloads") or []):
            errors.append(f"{base_id}: duplicate manifest payload path")
        if set(payload_entries) != set(expected_payloads):
            errors.append(f"{base_id}: manifest payload set differs from blueprint plus fixtures")
        observed_payload_paths = {
            path.relative_to(release_root).as_posix()
            for path in release_root.rglob("*")
            if path.is_file()
            and path.name not in {"MANIFEST.jcs.json", "attestation.sigstore.json"}
        }
        if observed_payload_paths != set(expected_payloads):
            errors.append(f"{base_id}: payload tree differs from blueprint plus fixtures")
        for logical, (raw, media_type, role) in expected_payloads.items():
            path = release_root / logical
            entry = payload_entries.get(logical) or {}
            expected_entry = {
                "path": logical,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "media_type": media_type,
                "role": role,
            }
            if not path.is_file() or path.read_bytes() != raw:
                errors.append(f"{base_id}: expected payload bytes differ: {logical}")
            if entry != expected_entry:
                errors.append(f"{base_id}: expected payload entry differs: {logical}")

        source_fixture = overlay["payload_fixtures"]["source_snapshot"]
        source_path = release_root / source_fixture["path"]
        try:
            source_members, source_errors = _archive_entries(source_path)
            errors.extend(f"{base_id}: source snapshot {error}" for error in source_errors)
            if set(source_members) != {source_fixture["recipe"]["member_path"]}:
                errors.append(f"{base_id}: source snapshot USTAR member set differs")
        except (KeyError, OSError, tarfile.TarError) as exc:
            errors.append(f"{base_id}: source snapshot is not the declared USTAR: {exc}")

        manifest_sha256 = sha256_bytes(manifest_raw)
        attestation_sha256 = sha256_file(attestation_path)
        if manifest_sha256 != record.get("manifest_sha256"):
            errors.append(f"{base_id}: manifest hash mismatch")
        if attestation_sha256 != record.get("attestation_sha256"):
            errors.append(f"{base_id}: attestation hash mismatch")

        clean_results: dict[str, dict[str, str]] = {}
        for profile_id in ("P0", "P1", "P2", "P3"):
            result_path = run / "bases" / base_id / "clean_results" / f"{profile_id}.json"
            retained_result = load_json(result_path)
            result_errors = list(result_validator.iter_errors(retained_result))
            if result_errors:
                errors.append(f"{base_id}/{profile_id}: retained result schema invalid")
            replayed = verify_selected_fixture_release(
                release_root,
                profile_id=profile_id,
                policy=policy,
                manifest_schema_path=MANIFEST_SCHEMA,
            )
            if replayed != retained_result:
                errors.append(f"{base_id}/{profile_id}: verifier replay differs")
            observed = {
                "decision": retained_result.get("decision"),
                "primary_reason": retained_result.get("primary_reason"),
            }
            clean_results[profile_id] = observed
            if observed != {"decision": "ACCEPT", "primary_reason": "OK"}:
                errors.append(f"{base_id}/{profile_id}: clean selected base did not ACCEPT/OK")
            expected_checks = {
                name: "PASS" if name in PROFILE_CHECKS[profile_id] else "NOT_REQUIRED"
                for name in CHECK_NAMES
            }
            if retained_result.get("checks") != expected_checks:
                errors.append(f"{base_id}/{profile_id}: clean check vector differs")
            summary_result = (record.get("clean_profile_results") or {}).get(profile_id)
            expected_summary = {
                **observed,
                "result_sha256": sha256_file(result_path),
            }
            if summary_result != expected_summary:
                errors.append(f"{base_id}/{profile_id}: summary/result binding differs")

        expected_counts = {
            "blueprint_payload_count": len(base["payloads"]),
            "injected_fixture_payload_count": len(overlay["payload_fixtures"]),
            "total_payload_count": len(expected_payloads),
        }
        for field, expected in expected_counts.items():
            if record.get(field) != expected:
                errors.append(f"{base_id}: payload count mismatch for {field}")
        validated_bases.append(
            {
                "base_id": base_id,
                "archive_sha256": record.get("archive_sha256"),
                "manifest_sha256": manifest_sha256,
                "attestation_sha256": attestation_sha256,
                "tree_sha256": tree_sha256,
                "clean_profile_results": clean_results,
            }
        )

    if summary.get("all_clean_profiles_accept") is not True:
        errors.append("summary does not assert all clean profiles accept")
    if summary.get("repository_dirty") is not True:
        warnings.append("run does not record the current study as dirty/untracked")
    return {
        "schema_version": "amy.selected-profile-r0-base-validation.v1-draft",
        "valid": not errors,
        "classification": summary.get("classification"),
        "confirmatory_cases_generated": summary.get("confirmatory_cases_generated"),
        "confirmatory_outcomes_read": summary.get("confirmatory_outcomes_read"),
        "production_sigstore_conformance": summary.get("production_sigstore_conformance"),
        "run_summary_sha256": sha256_file(run / "summary.json"),
        "retained_source_archive_self_valid": not source_archive_errors,
        "retained_source_matches_current_study": not current_source_drift,
        "retained_source_drift_paths": current_source_drift,
        "base_count": len(validated_bases),
        "validated_bases": validated_bases,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.run.resolve())
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
