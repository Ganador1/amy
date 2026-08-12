#!/usr/bin/env python3
"""Read-only ATLAS integrity audit; never imports ATLAS or deserializes pickle.

The output is deterministic for a fixed repository byte snapshot.  It separates
cryptographic signature validity from artifact-digest validity and reproduces
the publication-package hash exactly as the audited implementation computes it.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = STUDY_ROOT.parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed with {completed.returncode}")
    return completed.stdout.strip()


def git_commit_exists(root: Path, revision: str) -> bool:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    return completed.returncode == 0


def git_ignored(root: Path, path: Path) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", relative(path, root)],
        cwd=root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    return completed.returncode == 0


def signature_payload(manifest: dict[str, Any]) -> bytes:
    clone = {key: value for key, value in manifest.items() if key != "signatures"}
    return json.dumps(clone, sort_keys=True, separators=(",", ":")).encode()


def first_validator_payload_hash(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(signature_payload(manifest)).hexdigest()


def second_validator_payload_hash(manifest: dict[str, Any]) -> str:
    clone = copy.deepcopy(manifest)
    clone.pop("hashes", None)
    clone.pop("signatures", None)
    raw = json.dumps(clone, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def load_public_keys(directory: Path) -> dict[str, Ed25519PublicKey]:
    keys: dict[str, Ed25519PublicKey] = {}
    for path in sorted(directory.glob("*.pem")):
        key = serialization.load_pem_public_key(path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            continue
        der = key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        keys[hashlib.sha256(der).hexdigest()] = key
    return keys


def verify_signature(key: Ed25519PublicKey, signature_b64: str, payload: bytes) -> bool:
    try:
        key.verify(base64.b64decode(signature_b64, validate=True), payload)
    except (InvalidSignature, ValueError):
        return False
    return True


def audit_manifests(root: Path, atlas: Path) -> dict[str, Any]:
    public_keys = load_public_keys(atlas / "keys/public")
    records: list[dict[str, Any]] = []
    for path in sorted((atlas / "models").glob("*.manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        stored_hash = (manifest.get("hashes") or {}).get("manifest_sha256")
        payload = signature_payload(manifest)
        signatures: list[dict[str, Any]] = []
        for entry in manifest.get("signatures", []):
            fingerprint = entry.get("public_key_fingerprint")
            key = public_keys.get(fingerprint)
            valid = bool(
                key
                and isinstance(entry.get("sig"), str)
                and verify_signature(key, entry["sig"], payload)
            )
            timestamp_tamper_valid: bool | None = None
            if key and isinstance(entry.get("sig"), str) and "ts" in entry:
                tampered = copy.deepcopy(manifest)
                tampered["signatures"][0]["ts"] = "2099-01-01T00:00:00Z"
                timestamp_tamper_valid = verify_signature(
                    key, entry["sig"], signature_payload(tampered)
                )
            signatures.append(
                {
                    "algorithm_declared": entry.get("alg"),
                    "fingerprint": fingerprint,
                    "public_key_available": key is not None,
                    "signature_valid": valid,
                    "timestamp_present": "ts" in entry,
                    "timestamp_tamper_signature_valid": timestamp_tamper_valid,
                }
            )

        artifacts: list[dict[str, Any]] = []
        for artifact in manifest.get("artifacts", []):
            declared_path = artifact.get("path")
            resolved = atlas / declared_path if isinstance(declared_path, str) else atlas
            validator_resolved = path.parent / declared_path if isinstance(declared_path, str) else path.parent
            exists = resolved.is_file()
            actual_digest = sha256(resolved) if exists else None
            actual_size = resolved.stat().st_size if exists else None
            artifacts.append(
                {
                    "declared_path": declared_path,
                    "expected_sha256": artifact.get("hash_sha256"),
                    "actual_sha256": actual_digest,
                    "digest_matches": actual_digest == artifact.get("hash_sha256"),
                    "expected_bytes": artifact.get("size_bytes"),
                    "actual_bytes": actual_size,
                    "size_matches": actual_size == artifact.get("size_bytes"),
                    "project_root_resolution_exists": exists,
                    "second_validator_resolution": relative(validator_resolved, root),
                    "second_validator_resolution_exists": validator_resolved.is_file(),
                }
            )

        revision = str(manifest.get("git_commit", ""))
        first_hash = first_validator_payload_hash(manifest)
        second_hash = second_validator_payload_hash(manifest)
        records.append(
            {
                "path": relative(path, root),
                "file_sha256": sha256(path),
                "stored_manifest_sha256": stored_hash,
                "signature_payload_sha256": first_hash,
                "first_validator_hash_matches": stored_hash == first_hash,
                "second_validator_payload_sha256": second_hash,
                "second_validator_hash_matches": stored_hash == second_hash,
                "git_commit": revision,
                "git_commit_exists": git_commit_exists(root, revision),
                "signatures": signatures,
                "artifacts": artifacts,
            }
        )

    all_artifacts = [artifact for record in records for artifact in record["artifacts"]]
    all_signatures = [signature for record in records for signature in record["signatures"]]
    return {
        "public_key_fingerprints": sorted(public_keys),
        "manifests": records,
        "summary": {
            "manifest_count": len(records),
            "manifest_self_hash_matches_first_validator": sum(
                record["first_validator_hash_matches"] for record in records
            ),
            "manifest_self_hash_matches_second_validator": sum(
                record["second_validator_hash_matches"] for record in records
            ),
            "signature_count": len(all_signatures),
            "cryptographically_valid_signatures": sum(
                signature["signature_valid"] for signature in all_signatures
            ),
            "artifacts_checked": len(all_artifacts),
            "artifact_digest_matches": sum(
                artifact["digest_matches"] for artifact in all_artifacts
            ),
            "artifact_digest_failures": sum(
                not artifact["digest_matches"] for artifact in all_artifacts
            ),
            "declared_git_commits_resolved": sum(
                record["git_commit_exists"] for record in records
            ),
        },
    }


def implementation_package_hash(package_path: Path) -> str:
    digest = hashlib.blake2b()
    for path in sorted(package_path.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(package_path).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def load_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def audit_publications(root: Path, atlas: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for package in sorted((atlas / "publications").glob("publication_*")):
        if not package.is_dir():
            continue
        hash_path = package / "package_hash.txt"
        stored_hash = hash_path.read_text(encoding="utf-8").strip() if hash_path.is_file() else None
        manifest = load_json_if_present(package / "manifest.json")
        proof = load_json_if_present(package / "integrity_proof.json")
        current_hash = implementation_package_hash(package)
        records.append(
            {
                "path": relative(package, root),
                "regular_file_count": sum(path.is_file() for path in package.rglob("*")),
                "current_implementation_hash": current_hash,
                "stored_hash": stored_hash,
                "current_matches_stored": stored_hash is not None and current_hash == stored_hash,
                "manifest_package_hash": manifest.get("package_hash") if manifest else None,
                "manifest_matches_stored": bool(
                    manifest and stored_hash and manifest.get("package_hash") == stored_hash
                ),
                "proof_package_hash": proof.get("package_hash") if proof else None,
                "proof_matches_stored": bool(
                    proof and stored_hash and proof.get("package_hash") == stored_hash
                ),
                "blockchain_validation": proof.get("blockchain_validation") if proof else None,
                "self_referential_files_present": sorted(
                    name
                    for name in ("integrity_proof.json", "manifest.json", "package_hash.txt")
                    if (package / name).is_file()
                ),
            }
        )
    with_hash = [record for record in records if record["stored_hash"] is not None]
    return {
        "algorithm_documented_by_code": "BLAKE3",
        "algorithm_actually_instantiated": "BLAKE2b-512",
        "packages": records,
        "summary": {
            "publication_directories": len(records),
            "packages_with_stored_hash": len(with_hash),
            "current_hash_matches": sum(record["current_matches_stored"] for record in with_hash),
            "manifest_matches_stored": sum(record["manifest_matches_stored"] for record in with_hash),
            "proof_matches_stored": sum(record["proof_matches_stored"] for record in with_hash),
            "blockchain_validation_true": sum(
                record["blockchain_validation"] is True for record in records
            ),
        },
    }


def audit_keys(root: Path, atlas: Path) -> dict[str, Any]:
    private_key = atlas / "keys/private/ed25519_private.key"
    public_paths = sorted((atlas / "keys").rglob("*.pem"))
    private_record: dict[str, Any] = {"path": relative(private_key, root), "exists": private_key.is_file()}
    if private_key.is_file():
        mode = stat.S_IMODE(private_key.stat().st_mode)
        private_record.update(
            {
                "bytes": private_key.stat().st_size,
                "mode_octal": f"{mode:04o}",
                "group_or_other_readable": bool(mode & (stat.S_IRGRP | stat.S_IROTH)),
                "git_ignored": git_ignored(root, private_key),
                "content_or_digest_recorded": False,
            }
        )
    return {
        "private_key": private_record,
        "public_keys": [
            {
                "path": relative(path, root),
                "bytes": path.stat().st_size,
                "mode_octal": f"{stat.S_IMODE(path.stat().st_mode):04o}",
                "git_ignored": git_ignored(root, path),
            }
            for path in public_paths
        ],
    }


def audit_model_lineage(root: Path, atlas: Path) -> dict[str, Any]:
    versions_path = atlas / "data/versions.json"
    versions = json.loads(versions_path.read_text(encoding="utf-8"))
    model_path = "models/plausibility_v4_rf.pkl"
    events = [
        {
            key: entry.get(key)
            for key in ("version_id", "data_path", "checksum", "size_bytes", "created_at", "tags")
        }
        for entry in versions
        if isinstance(entry, dict) and entry.get("data_path") == model_path
    ]
    manifest_path = atlas / "models/plausibility_v4_rf.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    training_path = atlas / "scripts/data_processing/train_plausibility_model_v4.py"
    training_lines = training_path.read_text(encoding="utf-8").splitlines()
    parameter_sites: list[dict[str, Any]] = []
    for line_number, line in enumerate(training_lines, 1):
        match = re.search(r"RandomForestClassifier\(n_estimators=(\d+)", line)
        if match:
            parameter_sites.append(
                {"line": line_number, "n_estimators": int(match.group(1))}
            )
    return {
        "versions_file": relative(versions_path, root),
        "model_version_events": events,
        "current_model_sha256": sha256(atlas / model_path),
        "manifest_expected_sha256": manifest["artifacts"][0]["hash_sha256"],
        "manifest_declared_n_estimators": (manifest.get("parameters") or {}).get(
            "n_estimators"
        ),
        "training_script_n_estimators_sites": parameter_sites,
        "model_object_deserialized_for_this_audit": False,
        "interpretation_limit": (
            "The parameter comparison concerns manifest metadata and producer source; "
            "it does not establish the internal parameter of the current pickle."
        ),
    }


def audit_static_code(root: Path, atlas: Path) -> dict[str, Any]:
    pickle_pattern = re.compile(r"\b(?:joblib|pickle)\.(?:load|loads)\s*\(")
    hash_pattern = re.compile(r"\bhashlib\.([A-Za-z0-9_]+)\s*\(")
    pickle_sites: list[dict[str, Any]] = []
    hash_algorithms: Counter[str] = Counter()
    excluded_directory_names = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        "test_env",
        "venv",
    }
    source_paths: list[Path] = []
    for directory, child_directories, files in os.walk(atlas, topdown=True):
        child_directories[:] = sorted(
            name for name in child_directories if name not in excluded_directory_names
        )
        source_paths.extend(
            Path(directory) / name for name in sorted(files) if name.endswith(".py")
        )
    for path in source_paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, 1):
            if pickle_pattern.search(line):
                pickle_sites.append(
                    {"path": relative(path, root), "line": line_number, "code": line.strip()}
                )
            for algorithm in hash_pattern.findall(line):
                hash_algorithms[algorithm] += 1

    root_workflows = sorted((root / ".github/workflows").glob("*.y*ml"))
    nested_workflows = sorted((atlas / ".github/workflows").glob("*.y*ml"))
    root_workflow_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in root_workflows
    )
    claim_needles = (
        "All results are cryptographically verifiable",
        "All artifacts, datasets, and computational steps are cryptographically signed",
        "Distributed consensus",
        "All results were validated using the AXIOM blockchain",
    )
    claim_locations: list[dict[str, Any]] = []
    for path in (atlas / "publications/template.tex", atlas / "docs/guides/manuscript.md"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for needle in claim_needles:
                if needle in line:
                    claim_locations.append(
                        {"path": relative(path, root), "line": line_number, "needle": needle}
                    )
    relevant_sources = [
        STUDY_ROOT / "scripts/audit_atlas_integrity.py",
        atlas / "data/versions.json",
        atlas / "models/plausibility_v4_rf.manifest.json",
        atlas / "app/security/integrity_core.py",
        atlas / "app/security/hmac_integrity.py",
        atlas / "app/validation/blockchain_validation.py",
        atlas / "app/services/literature/publication_generator.py",
        atlas / "scripts/data_processing/train_plausibility_model_v4.py",
        atlas / "scripts/tools/sign_manifest.py",
        atlas / "scripts/qa/verify_manifest_signatures.py",
        atlas / "scripts/qa/validate_manifests.py",
        atlas / "scripts/qa/validate_artifact_manifest.py",
        atlas / "publications/template.tex",
        atlas / "docs/guides/manuscript.md",
        atlas / ".github/workflows/ci.yml",
        root / ".github/workflows/ci.yml",
    ]
    return {
        "static_scan_scope": {
            "python_files_scanned": len(source_paths),
            "excluded_directory_names": sorted(excluded_directory_names),
        },
        "unsafe_deserialization_call_sites": pickle_sites,
        "direct_hashlib_constructor_counts": dict(sorted(hash_algorithms.items())),
        "overbroad_publication_claim_locations": claim_locations,
        "ci": {
            "active_root_workflows": [relative(path, root) for path in root_workflows],
            "nested_atlas_workflows": [relative(path, root) for path in nested_workflows],
            "active_root_mentions_manifest_signature_verifier": (
                "verify_manifest_signatures" in root_workflow_text
            ),
            "active_root_mentions_artifact_manifest_validator": (
                "validate_artifact_manifest" in root_workflow_text
            ),
        },
        "source_sha256": {
            relative(path, root): sha256(path) for path in relevant_sources if path.is_file()
        },
    }


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    atlas = root / "atlas"
    if not (atlas / "models").is_dir():
        raise RuntimeError(f"ATLAS models directory not found below {root}")
    tracked_status = git(root, "status", "--porcelain=v1", "--untracked-files=no")
    return {
        "schema_version": "amy.atlas-integrity-audit.v1",
        "classification": "exploratory_pre_registration_read_only",
        "safety": {
            "imports_atlas": False,
            "deserializes_pickle_or_joblib": False,
            "reads_private_key_content": False,
            "mutates_audited_artifacts": False,
        },
        "repository": {
            "git_commit": git(root, "rev-parse", "HEAD"),
            "git_object_format": git(root, "rev-parse", "--show-object-format"),
            "git_describe": git(root, "describe", "--tags", "--always", "--dirty"),
            "tracked_worktree_dirty": bool(tracked_status),
            "tracked_status_sha256": hashlib.sha256(tracked_status.encode()).hexdigest(),
        },
        "manifests_and_artifacts": audit_manifests(root, atlas),
        "model_lineage": audit_model_lineage(root, atlas),
        "key_handling": audit_keys(root, atlas),
        "publication_packages": audit_publications(root, atlas),
        "static_code": audit_static_code(root, atlas),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_audit(args.repository_root)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
            indent=None if args.compact else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
