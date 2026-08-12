#!/usr/bin/env python3
"""Build and check the deterministic retained-artifact inventory.

The tree digest commits to relative member paths, member kinds, regular-file
byte lengths and SHA-256 digests, and symlink targets. It deliberately excludes
mtime, ownership, and permission bits so a checkout can replay it. The digest
establishes byte identity only; it does not authenticate or validate contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = STUDY_ROOT / "protocol/ARTIFACT_RETENTION_POLICY.json"
INDEX_PATH = STUDY_ROOT / "protocol/ARTIFACT_RETENTION_INDEX.jcs.json"
POLICY_SCHEMA_PATH = STUDY_ROOT / "schemas/artifact-retention-policy.schema.json"
INDEX_SCHEMA_PATH = STUDY_ROOT / "schemas/artifact-retention-index.schema.json"
STATUSES = (
    "active",
    "historical_valid",
    "historical_invalid",
    "superseded",
    "local_only",
)

# Conservative filesystem-path indicators. URLs are intentionally excluded.
POSIX_ABSOLUTE = re.compile(
    rb"(?:^|[\\x00-\\x20\"'=(:,\\[])(/(?!/)(?!api(?:/|$))"
    rb"[A-Za-z0-9._~ @+,:=-]+(?:/[A-Za-z0-9._~ @+,:=-]+)+)"
)
WINDOWS_ABSOLUTE = re.compile(
    rb"(?:^|[\\x00-\\x20\"'=(:,\\[])([A-Za-z]:[\\\\/]"
    rb"[^\\x00\\r\\n\"'<>|]+)"
)


class DuplicateKeyError(ValueError):
    """Raised when a supposedly strict JSON document repeats a key."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> tuple[Any, bytes]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required input is not a regular non-symlink file: {path}")
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=_strict_object), raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sort_paths(paths: Iterable[str]) -> list[str]:
    return sorted(paths, key=lambda value: value.encode("utf-8"))


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def _walk_directory(root: Path) -> list[tuple[str, Path, os.stat_result]]:
    members: list[tuple[str, Path, os.stat_result]] = []

    def visit(directory: Path, relative: PurePosixPath) -> None:
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for child in children:
            child_relative = relative / child.name
            child_path = Path(child.path)
            child_stat = child.stat(follow_symlinks=False)
            members.append((child_relative.as_posix(), child_path, child_stat))
            if stat.S_ISDIR(child_stat.st_mode):
                visit(child_path, child_relative)

    visit(root, PurePosixPath())
    return members


def _absolute_path_findings(raw: bytes, member_path: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if POSIX_ABSOLUTE.search(raw):
        findings.append({"member_path": member_path, "syntax": "posix"})
    if WINDOWS_ABSOLUTE.search(raw):
        findings.append({"member_path": member_path, "syntax": "windows"})
    return findings


def _artifact_tree(path: Path, kind: str) -> dict[str, Any]:
    if kind == "file":
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"artifact is not a regular file: {path}")
        members = [(".", path, path.stat())]
    elif kind == "directory":
        if not path.is_dir() or path.is_symlink():
            raise ValueError(f"artifact is not a real directory: {path}")
        members = _walk_directory(path)
        if not members:
            raise ValueError(f"artifact directory is empty: {path}")
    else:
        raise ValueError(f"unsupported artifact kind: {kind}")

    tree: list[dict[str, Any]] = []
    byte_count = 0
    findings: list[dict[str, str]] = []
    non_git_member_count = 0
    for relative, member_path, member_stat in members:
        if stat.S_ISREG(member_stat.st_mode):
            raw = member_path.read_bytes()
            byte_count += len(raw)
            tree.append(
                {
                    "path": relative,
                    "kind": "file",
                    "byte_count": len(raw),
                    "sha256": _sha256(raw),
                }
            )
            findings.extend(_absolute_path_findings(raw, relative))
        elif stat.S_ISLNK(member_stat.st_mode):
            target = os.readlink(member_path)
            target_raw = os.fsencode(target)
            tree.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target": target,
                    "target_byte_count": len(target_raw),
                    "target_sha256": _sha256(target_raw),
                }
            )
            if Path(target).is_absolute():
                findings.append({"member_path": relative, "syntax": "posix"})
        elif stat.S_ISDIR(member_stat.st_mode):
            tree.append({"path": relative, "kind": "directory"})
        else:
            if stat.S_ISFIFO(member_stat.st_mode):
                member_kind = "fifo"
            elif stat.S_ISSOCK(member_stat.st_mode):
                member_kind = "socket"
            elif stat.S_ISCHR(member_stat.st_mode):
                member_kind = "character_device"
            elif stat.S_ISBLK(member_stat.st_mode):
                member_kind = "block_device"
            else:
                member_kind = "unknown_special"
            non_git_member_count += 1
            tree.append({"path": relative, "kind": member_kind})

    tree.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    findings = sorted(
        {json.dumps(item, sort_keys=True): item for item in findings}.values(),
        key=lambda item: (
            item["member_path"].encode("utf-8"),
            item["syntax"].encode("utf-8"),
        ),
    )
    return {
        "tree_sha256": _sha256(rfc8785.dumps(tree)),
        "member_count": len(tree),
        "byte_count": byte_count,
        "non_git_member_count": non_git_member_count,
        "absolute_path_findings": findings,
    }


def _covered_by(artifact_path: PurePosixPath, candidate: PurePosixPath) -> bool:
    return candidate == artifact_path or artifact_path in candidate.parents


def _retained_members(study_root: Path, retained_roots: list[str]) -> list[str]:
    members: list[str] = []
    for value in retained_roots:
        relative = _safe_relative(value)
        root = study_root / Path(*relative.parts)
        if not root.is_dir() or root.is_symlink():
            continue
        for member_relative, _, member_stat in _walk_directory(root):
            if not stat.S_ISDIR(member_stat.st_mode):
                members.append((relative / member_relative).as_posix())
    return _sort_paths(members)


def build_index(
    *,
    study_root: Path = STUDY_ROOT,
    policy_path: Path = POLICY_PATH,
    policy_schema_path: Path = POLICY_SCHEMA_PATH,
    index_schema_path: Path = INDEX_SCHEMA_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    policy, policy_raw = _load_json(policy_path)
    policy_schema, policy_schema_raw = _load_json(policy_schema_path)
    index_schema, index_schema_raw = _load_json(index_schema_path)
    Draft202012Validator.check_schema(policy_schema)
    Draft202012Validator.check_schema(index_schema)
    errors.extend(
        f"policy schema: {error.message}"
        for error in Draft202012Validator(policy_schema).iter_errors(policy)
    )

    retained_roots = (
        policy.get("retained_roots", []) if isinstance(policy, dict) else []
    )
    retained_roots = (
        retained_roots
        if isinstance(retained_roots, list)
        and all(isinstance(item, str) for item in retained_roots)
        else []
    )
    policy_rows = policy.get("artifacts", []) if isinstance(policy, dict) else []
    policy_rows = policy_rows if isinstance(policy_rows, list) else []

    ids: list[str] = []
    paths: list[str] = []
    artifact_rows: list[dict[str, Any]] = []
    artifact_paths: list[PurePosixPath] = []
    for position, policy_row in enumerate(policy_rows):
        if not isinstance(policy_row, dict):
            errors.append(f"artifact policy row {position} is not an object")
            continue
        artifact_id = policy_row.get("id")
        relative_value = policy_row.get("path")
        kind = policy_row.get("kind")
        if not isinstance(artifact_id, str) or not isinstance(relative_value, str):
            errors.append(f"artifact policy row {position} lacks a usable ID/path")
            continue
        ids.append(artifact_id)
        paths.append(relative_value)
        relative: PurePosixPath
        artifact_path: Path
        try:
            relative = _safe_relative(relative_value)
            artifact_path = study_root / Path(*relative.parts)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{artifact_id}: {exc}")
            continue
        artifact_paths.append(relative)

        source_git = policy_row.get("source_git")
        commitment = policy_row.get("local_commitment")
        local_only = source_git is False
        artifact_present = artifact_path.exists() or artifact_path.is_symlink()
        if artifact_present:
            try:
                observed_tree = _artifact_tree(artifact_path, str(kind))
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f"{artifact_id}: {exc}")
                continue
        elif local_only and isinstance(commitment, dict):
            observed_tree = None
        else:
            errors.append(f"{artifact_id}: artifact path does not exist")
            continue

        if local_only:
            if not isinstance(commitment, dict):
                errors.append(
                    f"{artifact_id}: source_git=false requires a local_commitment"
                )
                continue
            commitment_tree = {
                "tree_sha256": commitment.get("tree_sha256"),
                "member_count": commitment.get("member_count"),
                "byte_count": commitment.get("byte_count"),
                "non_git_member_count": commitment.get("non_git_member_count"),
                "absolute_path_count": commitment.get("absolute_path_count"),
            }
            if observed_tree is not None:
                observed_comparable = {
                    "tree_sha256": observed_tree["tree_sha256"],
                    "member_count": observed_tree["member_count"],
                    "byte_count": observed_tree["byte_count"],
                    "non_git_member_count": observed_tree["non_git_member_count"],
                    "absolute_path_count": len(
                        observed_tree["absolute_path_findings"]
                    ),
                }
                if observed_comparable != commitment_tree:
                    errors.append(
                        f"{artifact_id}: local bytes differ from the committed "
                        "local_commitment"
                    )
            tree = {
                **commitment_tree,
                "absolute_path_findings": [],
            }
        else:
            tree = observed_tree
            assert tree is not None

        row = dict(policy_row)
        row.pop("local_commitment", None)
        row.update(
            {
                "tree_sha256": tree["tree_sha256"],
                "member_count": tree["member_count"],
                "byte_count": tree["byte_count"],
                "non_git_member_count": tree["non_git_member_count"],
                "absolute_path_count": (
                    tree["absolute_path_count"]
                    if local_only
                    else len(tree["absolute_path_findings"])
                ),
                "absolute_path_findings": tree["absolute_path_findings"],
                "absolute_path_findings_redacted": local_only,
            }
        )
        if row.get("public_packet") is True and row["absolute_path_count"]:
            errors.append(
                f"{artifact_id}: public_packet=true is forbidden because "
                "absolute filesystem paths were detected"
            )
        if row.get("source_git") is True and tree["non_git_member_count"]:
            errors.append(
                f"{artifact_id}: source_git=true is forbidden because "
                f"{tree['non_git_member_count']} member(s) cannot be represented by Git"
            )
        if row.get("status") in {"historical_invalid", "superseded", "local_only"}:
            if row.get("public_packet") is True:
                errors.append(
                    f"{artifact_id}: status {row.get('status')} forbids public_packet=true"
                )
        if row.get("status") == "local_only" and row.get("source_git") is True:
            errors.append(f"{artifact_id}: local_only forbids source_git=true")
        artifact_rows.append(row)

    if len(ids) != len(set(ids)):
        errors.append("artifact IDs are not unique")
    if len(paths) != len(set(paths)):
        errors.append("artifact paths are not unique")

    retained_members = _retained_members(study_root, retained_roots)
    unindexed: list[str] = []
    multiply_indexed: list[str] = []
    for member in retained_members:
        member_path = PurePosixPath(member)
        covering = [
            artifact_path
            for artifact_path in artifact_paths
            if _covered_by(artifact_path, member_path)
        ]
        if not covering:
            unindexed.append(member)
        elif len(covering) > 1:
            multiply_indexed.append(member)
    if unindexed:
        errors.append(f"{len(unindexed)} retained filesystem paths are not indexed")
    if multiply_indexed:
        errors.append(
            f"{len(multiply_indexed)} retained filesystem paths are indexed more than once"
        )

    artifact_rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    status_counts = {status: 0 for status in STATUSES}
    for row in artifact_rows:
        status = row.get("status")
        if status in status_counts:
            status_counts[status] += 1

    result: dict[str, Any] = {
        "schema_version": "amy.artifact-retention-index.v1",
        "classification": (
            "deterministic_inventory_not_authentication_or_scientific_validation"
        ),
        "valid": not errors,
        "tree_hash_algorithm": "sha256-rfc8785-member-tree-v1",
        "policy_sha256": _sha256(policy_raw),
        "policy_schema_sha256": _sha256(policy_schema_raw),
        "index_schema_sha256": _sha256(index_schema_raw),
        "retained_roots": retained_roots,
        "summary": {
            "artifact_count": len(artifact_rows),
            "member_count": sum(row["member_count"] for row in artifact_rows),
            "byte_count": sum(row["byte_count"] for row in artifact_rows),
            "source_git_count": sum(row.get("source_git") is True for row in artifact_rows),
            "public_packet_count": sum(
                row.get("public_packet") is True for row in artifact_rows
            ),
            "artifacts_with_absolute_paths": sum(
                row["absolute_path_count"] > 0 for row in artifact_rows
            ),
            "status_counts": status_counts,
        },
        "artifacts": artifact_rows,
        "unindexed_paths": unindexed,
        "multiply_indexed_paths": multiply_indexed,
        "errors": errors,
        "boundaries": {
            "scientific_validity_established": False,
            "authentication_established": False,
            "authorization_established": False,
            "historical_bytes_rewritten": False,
            "absolute_paths_block_public_packet": True,
        },
    }
    schema_errors = [
        f"index schema: {error.message}"
        for error in Draft202012Validator(index_schema).iter_errors(result)
    ]
    if schema_errors:
        result["errors"].extend(schema_errors)
        result["valid"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the retained canonical index exactly matches a fresh build",
    )
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    result = build_index(policy_path=args.policy.resolve())
    canonical = rfc8785.dumps(result)
    if args.check:
        expected = INDEX_PATH.read_bytes() if INDEX_PATH.is_file() else None
        if expected != canonical:
            print("retained artifact index differs from current policy/filesystem")
            return 1
    elif args.output:
        args.output.write_bytes(canonical)
    elif args.compact:
        print(canonical.decode("utf-8"))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
