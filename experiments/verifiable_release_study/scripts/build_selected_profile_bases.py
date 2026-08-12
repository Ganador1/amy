#!/usr/bin/env python3
"""Build clean R0 bases under the selected P3 semantic contract only."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import locale
import os
import platform
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.base_corpus import (
    CC0_NOTICE,
    sha256_bytes,
    sha256_file,
    snapshot_tree,
    write_deterministic_archive,
)
from amy_verifier.selected_profile_fixture import (
    attest_selected_manifest,
    build_selected_release_from_base,
    selected_fixture_policy,
    verify_selected_fixture_release,
)


DEFAULT_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
DEFAULT_OVERLAY = STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json"
MANIFEST_SCHEMA = STUDY_ROOT / "schemas/manifest-production-v0.2.schema.json"
RESULT_SCHEMA = STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json"
SOURCE_INPUTS = (
    "amy_verifier",
    "scripts/build_selected_profile_bases.py",
    "scripts/validate_selected_profile_base_run.py",
    "corpus/BASE_REGISTRY_DRAFT.json",
    "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json",
    "protocol/REASON_CODES.json",
    "protocol/PRODUCTION_REASON_CODES_DRAFT.json",
    "schemas/manifest-production-v0.2.schema.json",
    "schemas/selected-profile-fixture-result.schema.json",
    "pyproject.toml",
    "uv.lock",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_identity() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=STUDY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=STUDY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    )
    return commit, dirty


def source_paths() -> list[Path]:
    paths: list[Path] = []
    for relative in SOURCE_INPUTS:
        path = STUDY_ROOT / relative
        if path.is_dir():
            paths.extend(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and "__pycache__" not in candidate.parts
                and candidate.suffix != ".pyc"
            )
        else:
            paths.append(path)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"selected base source inputs missing: {missing}")
    return sorted(
        set(paths),
        key=lambda item: item.relative_to(STUDY_ROOT).as_posix().encode("utf-8"),
    )


def write_source_archive(destination: Path) -> tuple[str, list[dict[str, Any]]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        for path in source_paths():
            raw = path.read_bytes()
            logical = path.relative_to(STUDY_ROOT).as_posix()
            info = tarfile.TarInfo(logical)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
            records.append(
                {"path": logical, "bytes": len(raw), "sha256": sha256_bytes(raw)}
            )
    return sha256_file(destination), records


def environment_record() -> dict[str, Any]:
    return {
        "recorded_at": utc_now(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "locale": locale.setlocale(locale.LC_ALL, None),
        "timezone_env": os.environ.get("TZ"),
    }


def _validate_registry_shape(registry: dict[str, Any]) -> None:
    bases = registry.get("bases")
    if registry.get("classification") != "R0_inputs_only_no_confirmatory_cases":
        raise ValueError("base registry is not classified as R0-only")
    if not isinstance(bases, list) or len(bases) != 6:
        raise ValueError("selected run requires the six reviewed base blueprints")
    ids = [base.get("id") for base in bases]
    if len(ids) != len(set(ids)):
        raise ValueError("base registry contains duplicate IDs")


def build(
    output: Path,
    registry_path: Path = DEFAULT_REGISTRY,
    overlay_path: Path = DEFAULT_OVERLAY,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    _validate_registry_shape(registry)
    policy = selected_fixture_policy(overlay_path)
    manifest_schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(result_schema)
    result_validator = Draft202012Validator(result_schema)
    if policy["manifest"]["schema_sha256"] != sha256_file(MANIFEST_SCHEMA):
        raise RuntimeError("effective policy manifest-schema hash differs")

    output.mkdir(parents=True)
    (output / "LICENSE-CC0-1.0-NOTICE.txt").write_bytes(CC0_NOTICE)
    (output / "base_registry_input.json").write_bytes(registry_path.read_bytes())
    (output / "selected_fixture_overlay_input.json").write_bytes(
        overlay_path.read_bytes()
    )
    effective_policy_path = output / "effective_fixture_policy.jcs.json"
    effective_policy_path.write_bytes(rfc8785.dumps(policy))
    write_json(output / "environment.json", environment_record())

    source_archive_path = output / "source/selected_base_generator_source.tar"
    source_archive_sha256, source_records = write_source_archive(source_archive_path)
    write_json(output / "source/source_manifest.json", source_records)
    commit, dirty = git_identity()

    base_records: list[dict[str, Any]] = []
    for base in sorted(registry["bases"], key=lambda item: item["id"].encode("ascii")):
        base_id = base["id"]
        release_root = output / "bases" / base_id / "release"
        manifest = build_selected_release_from_base(release_root, base, policy)
        attest_selected_manifest(release_root, policy)
        manifest_raw = (release_root / "MANIFEST.jcs.json").read_bytes()
        attestation_raw = (release_root / "attestation.sigstore.json").read_bytes()

        manifest_errors = sorted(
            Draft202012Validator(manifest_schema).iter_errors(manifest),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if manifest_errors:
            raise RuntimeError(
                f"{base_id}: selected manifest schema errors: "
                + "; ".join(error.message for error in manifest_errors)
            )

        tree = snapshot_tree(release_root)
        tree_raw = rfc8785.dumps(tree)
        write_json(output / "bases" / base_id / "tree.json", tree)
        archive_path = output / "archives" / f"{base_id}.tar"
        archive_sha256 = write_deterministic_archive(release_root, archive_path)

        clean_profile_results: dict[str, dict[str, Any]] = {}
        for profile_id in ("P0", "P1", "P2", "P3"):
            result = verify_selected_fixture_release(
                release_root,
                profile_id=profile_id,
                policy=policy,
                manifest_schema_path=MANIFEST_SCHEMA,
            )
            schema_errors = sorted(
                result_validator.iter_errors(result),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if schema_errors:
                raise RuntimeError(
                    f"{base_id}/{profile_id}: invalid selected-fixture result: "
                    + "; ".join(error.message for error in schema_errors)
                )
            if result["decision"] != "ACCEPT" or result["primary_reason"] != "OK":
                raise RuntimeError(f"{base_id}/{profile_id}: clean selected base rejected")
            result_path = (
                output / "bases" / base_id / "clean_results" / f"{profile_id}.json"
            )
            write_json(result_path, result)
            clean_profile_results[profile_id] = {
                "decision": result["decision"],
                "primary_reason": result["primary_reason"],
                "result_sha256": sha256_file(result_path),
            }

        base_records.append(
            {
                "base_id": base_id,
                "release_kind": base["release"]["kind"],
                "blueprint_payload_count": len(base["payloads"]),
                "injected_fixture_payload_count": len(policy["fixture_payloads"]),
                "total_payload_count": len(manifest["payloads"]),
                "manifest_sha256": sha256_bytes(manifest_raw),
                "attestation_sha256": sha256_bytes(attestation_raw),
                "tree_sha256": sha256_bytes(tree_raw),
                "archive_path": f"archives/{base_id}.tar",
                "archive_bytes": archive_path.stat().st_size,
                "archive_sha256": archive_sha256,
                "clean_profile_results": clean_profile_results,
            }
        )

    summary = {
        "schema_version": "amy.selected-profile-r0-base-build.v1-draft",
        "classification": (
            "exploratory_R0_selected_profile_clean_bases_no_adversarial_cases"
        ),
        "selected_profile": (
            "standard_provenance_plus_authenticated_manifest_metadata"
        ),
        "confirmatory_cases_generated": False,
        "confirmatory_outcomes_read": False,
        "production_sigstore_conformance": False,
        "base_count": len(base_records),
        "base_records": base_records,
        "all_clean_profiles_accept": True,
        "input_sha256": {
            "base_registry": sha256_file(registry_path),
            "selected_fixture_overlay": sha256_file(overlay_path),
            "effective_fixture_policy": sha256_file(effective_policy_path),
            "manifest_schema": sha256_file(MANIFEST_SCHEMA),
            "result_schema": sha256_file(RESULT_SCHEMA),
        },
        "source_archive_path": "source/selected_base_generator_source.tar",
        "source_archive_sha256": source_archive_sha256,
        "source_manifest_path": "source/source_manifest.json",
        "source_manifest_sha256": sha256_file(
            output / "source/source_manifest.json"
        ),
        "license_notice_sha256": sha256_bytes(CC0_NOTICE),
        "repository_commit": commit,
        "repository_dirty": dirty,
        "limitations": [
            "The cryptographic envelope is deterministic public test PKI, not production Sigstore.",
            "The two injected provenance payloads are controlled fixtures, not observations about the six blueprints.",
            "The source snapshot is a valid deterministic USTAR whose exact bytes are hashed; no Git-tree equivalence is claimed.",
            "This R0 run contains clean bases only and must not be reported as confirmatory evidence."
        ],
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    args = parser.parse_args()
    summary = build(args.output.resolve(), args.registry.resolve(), args.overlay.resolve())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
