#!/usr/bin/env python3
"""Build clean R0 base inputs only; this never generates adversarial cases."""

from __future__ import annotations

import argparse
import copy
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
    build_clean_base,
    load_draft_inputs,
    sha256_bytes,
    sha256_file,
    snapshot_tree,
    validate_registry,
    write_deterministic_archive,
)
from amy_verifier.verifier import ImplementationIdentity, verify_release


DEFAULT_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
DEFAULT_POLICY = STUDY_ROOT / "protocol/TRUST_POLICY_DRAFT.json"
MANIFEST_SCHEMA = STUDY_ROOT / "schemas/manifest.schema.json"
SOURCE_INPUTS = (
    "amy_verifier",
    "scripts/build_r0_bases.py",
    "corpus/BASE_REGISTRY_DRAFT.json",
    "protocol/TRUST_POLICY_DRAFT.json",
    "schemas/manifest.schema.json",
    "schemas/verifier-result.schema.json",
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
    return sorted(
        set(paths), key=lambda item: item.relative_to(STUDY_ROOT).as_posix().encode()
    )


def write_source_archive(destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        for path in source_paths():
            raw = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(STUDY_ROOT).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return sha256_file(destination)


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


def build(output: Path, registry_path: Path, trust_policy_path: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    registry, fixture_policy = load_draft_inputs(registry_path, trust_policy_path)
    registry_errors = validate_registry(registry, fixture_policy)
    if registry_errors:
        raise ValueError("invalid base registry: " + "; ".join(registry_errors))

    output.mkdir(parents=True)
    (output / "LICENSE-CC0-1.0-NOTICE.txt").write_bytes(CC0_NOTICE)
    (output / "base_registry_input.json").write_bytes(registry_path.read_bytes())
    policy_path = output / "fixture_trust_policy.jcs.json"
    policy_path.write_bytes(rfc8785.dumps(fixture_policy))
    write_json(output / "environment.json", environment_record())

    source_archive_path = output / "source/r0_base_generator_source.tar"
    source_archive_sha256 = write_source_archive(source_archive_path)
    commit, dirty = git_identity()
    implementation = ImplementationIdentity(
        version="0.4.0.dev0",
        git_commit=commit,
        source_archive_sha256=source_archive_sha256,
        dirty=dirty,
    )
    schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    result_schema = json.loads(
        (STUDY_ROOT / "schemas/verifier-result.schema.json").read_text(encoding="utf-8")
    )
    result_validator = Draft202012Validator(result_schema)
    generated_registry = copy.deepcopy(registry)
    generated_by_id = {base["id"]: base for base in generated_registry["bases"]}
    base_records: list[dict[str, Any]] = []

    for base in sorted(registry["bases"], key=lambda item: item["id"].encode("ascii")):
        base_id = base["id"]
        release_root = output / "bases" / base_id / "release"
        record = build_clean_base(release_root, base, fixture_policy, schema)
        tree = snapshot_tree(release_root)
        tree_raw = rfc8785.dumps(tree)
        write_json(output / "bases" / base_id / "tree.json", tree)
        archive_path = output / "archives" / f"{base_id}.tar"
        archive_sha256 = write_deterministic_archive(release_root, archive_path)

        profile_results: dict[str, dict[str, str]] = {}
        for profile_id in ("P0", "P1", "P2", "P3"):
            result = verify_release(
                release_root,
                profile_id=profile_id,
                case_id=f"R0-{base_id}-CLEAN",
                case_archive_sha256=archive_sha256,
                trust_policy_path=policy_path,
                implementation=implementation,
                manifest_schema_path=MANIFEST_SCHEMA,
                attestation_backend="pilot_fixture" if profile_id in {"P2", "P3"} else None,
            )
            schema_errors = sorted(
                result_validator.iter_errors(result),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if schema_errors:
                raise RuntimeError(
                    f"{base_id}/{profile_id}: invalid verifier result: "
                    + "; ".join(error.message for error in schema_errors)
                )
            profile_results[profile_id] = {
                "decision": result["decision"],
                "primary_reason": result["primary_reason"],
            }
            write_json(output / "bases" / base_id / "clean_results" / f"{profile_id}.json", result)
        if any(
            result != {"decision": "ACCEPT", "primary_reason": "OK"}
            for result in profile_results.values()
        ):
            raise RuntimeError(f"{base_id}: one or more profiles rejected the clean base")

        manifest_sha256 = record["manifest_sha256"]
        tree_sha256 = sha256_bytes(tree_raw)
        generated = generated_by_id[base_id]
        generated["expected_base_archive_sha256"] = archive_sha256
        generated["expected_manifest_sha256"] = manifest_sha256
        generated["expected_tree_sha256"] = tree_sha256
        base_records.append(
            {
                **record,
                "tree_sha256": tree_sha256,
                "archive_path": f"archives/{base_id}.tar",
                "archive_bytes": archive_path.stat().st_size,
                "archive_sha256": archive_sha256,
                "clean_profile_results": profile_results,
            }
        )

    generated_registry["status"] = "generated_exploratory_not_frozen"
    write_json(output / "base_registry_generated.json", generated_registry)
    summary = {
        "schema_version": "amy.r0-base-build.v1",
        "classification": "exploratory_R0_base_inputs_only_no_adversarial_cases",
        "confirmatory_cases_generated": False,
        "base_count": len(base_records),
        "base_records": base_records,
        "all_clean_profiles_accept": True,
        "source_archive_path": "source/r0_base_generator_source.tar",
        "source_archive_sha256": source_archive_sha256,
        "input_registry_sha256": sha256_file(registry_path),
        "fixture_policy_sha256": sha256_file(policy_path),
        "license_notice_sha256": sha256_bytes(CC0_NOTICE),
        "repository_commit": commit,
        "repository_dirty": dirty,
        "limitations": [
            "The controlled test PKI is public fixture material and is not production Sigstore.",
            "These are R0 clean base inputs only; no derived confirmatory mutation case exists.",
            "This exploratory generation may change before independent review and registration."
        ],
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--trust-policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()
    summary = build(args.output, args.registry, args.trust_policy)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
