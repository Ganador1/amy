"""Development-only mutation generator for the selected-profile catalog.

This module deliberately contains no profile expectations and reads no result
files.  It mutates controlled temporary fixtures only; confirmatory case
archives are generated after registration by a separately frozen runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import rfc8785

from .selected_profile_fixture import (
    _load_manifest,
    _write_manifest,
    attest_selected_manifest,
    make_selected_statement,
)


SUPPORTED_CASE_IDS = frozenset(
    {
        "ATTESTATION-MALFORMED-001",
        "ATTESTATION-MISSING-001",
        "BUILD-DIRTY-001",
        "BUILD-METADATA-MISSING-001",
        "BUILDER-PREDICATE-MISMATCH-001",
        "CERTIFICATE-TIME-001",
        "CLEAN-001",
        "CONTENT-BITFLIP-001",
        "CONTENT-SAME-SIZE-001",
        "CONTENT-TRUNCATE-001",
        "EXECUTION-IMAGE-MISMATCH-001",
        "IDENTITY-WORKFLOW-001",
        "INVENTORY-EXTRA-001",
        "INVENTORY-MISSING-001",
        "INVENTORY-OMIT-ROLE-001",
        "MANIFEST-DUPLICATE-KEY-001",
        "MANIFEST-MALFORMED-001",
        "MANIFEST-MISSING-001",
        "MANIFEST-NONCANONICAL-001",
        "MANIFEST-SCHEMA-001",
        "MANIFEST-SELF-HASH-001",
        "MATERIAL-LOCK-MISMATCH-001",
        "PATH-DUPLICATE-NORMALIZED-001",
        "PATH-HARDLINK-001",
        "PATH-NONREGULAR-001",
        "PATH-PARENT-001",
        "PATH-SYMLINK-001",
        "PREDICATE-WRONG-TYPE-001",
        "RESOURCE-MANIFEST-LIMIT-001",
        "SIGNATURE-ALGORITHM-001",
        "SIGNATURE-CORRUPT-001",
        "SNAPSHOT-DIGEST-MISMATCH-001",
        "SNAPSHOT-ROLE-MISMATCH-001",
        "SOURCE-TREE-MISMATCH-001",
        "SOURCE-WRONG-REVISION-001",
        "STATEMENT-MALFORMED-001",
        "SUBJECT-REPLAY-001",
        "SUBSTITUTION-COHERENT-001",
        "SUBSTITUTION-UNAUTHORIZED-001",
        "TRANSPARENCY-MISSING-001",
        "WORKFLOW-PARAMETER-MISMATCH-001",
    }
)

DEFAULT_MUTATION_TARGETS = {
    "primary_nonempty_payload": "payload/data.csv",
    "same_bytes_source": "payload/data-copy.csv",
    "hardlink_target": "payload/data.csv",
    "nested_payload": "payload/results/result.json",
    "sole_required_role_payload": "payload/analysis.py",
}
REQUIRED_MUTATION_TARGET_KEYS = frozenset(
    {
        "primary_nonempty_payload",
        "same_bytes_source",
        "nested_payload",
        "sole_required_role_payload",
    }
)
ALLOWED_MUTATION_TARGET_KEYS = REQUIRED_MUTATION_TARGET_KEYS | {"hardlink_target"}
GENERIC_PAYLOADS = (
    {"path": "payload/analysis.py", "role": "analysis_code"},
    {"path": "payload/data-copy.csv", "role": "raw_data"},
    {"path": "payload/data.csv", "role": "raw_data"},
    {"path": "payload/results/result.json", "role": "analysis_output"},
)


@dataclass(frozen=True)
class MutationPlan:
    schema_version: str
    base_id: str
    case_id: str
    mutation_targets_sha256: str
    target_path: str | None
    source_path: str | None
    target_role: str | None
    generated_path: str | None
    generated_path_strategy: str | None
    symlink_target: str | None
    contains_expected_or_observed_decisions: bool = False
    confirmatory_evidence: bool = False

    def record(self) -> dict[str, Any]:
        return asdict(self)

    def sha256(self) -> str:
        return _sha256(rfc8785.dumps(self.record()))


class MutationPlanUnavailable(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _payload_entry(path: str, raw: bytes, media_type: str, role: str) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "media_type": media_type,
        "role": role,
    }


def _canonical_payload_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError(f"mutation target is not a canonical payload path: {value!r}")
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
        or not logical.parts
        or logical.parts[0] != "payload"
    ):
        raise ValueError(f"mutation target is not a canonical payload path: {value!r}")
    return value


def normalize_mutation_targets(
    mutation_targets: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return a closed, canonical target map without consulting outcomes."""

    supplied = dict(DEFAULT_MUTATION_TARGETS if mutation_targets is None else mutation_targets)
    unknown = set(supplied) - ALLOWED_MUTATION_TARGET_KEYS
    missing = REQUIRED_MUTATION_TARGET_KEYS - set(supplied)
    if unknown or missing:
        raise ValueError(
            "mutation target keys differ: "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    normalized = {
        key: _canonical_payload_path(value) for key, value in supplied.items()
    }
    normalized.setdefault(
        "hardlink_target", normalized["primary_nonempty_payload"]
    )
    if normalized["same_bytes_source"] == normalized["hardlink_target"]:
        raise ValueError("hardlink source and target must be different paths")
    return normalized


def _target(root: Path, targets: Mapping[str, str], name: str) -> Path:
    logical = PurePosixPath(targets[name])
    return root.joinpath(*logical.parts)


def _validate_plan_against_manifest(root: Path, plan: MutationPlan) -> None:
    manifest = _load_manifest(root)
    payloads = [
        item for item in manifest.get("payloads", []) if isinstance(item, dict)
    ]
    payload_paths = {item.get("path") for item in payloads}
    referenced = {
        value for value in (plan.target_path, plan.source_path) if value is not None
    }
    missing = sorted(referenced - payload_paths)
    if missing:
        raise ValueError(f"mutation plan paths are absent from the clean manifest: {missing}")
    if plan.target_role is not None:
        matching = [item for item in payloads if item.get("role") == plan.target_role]
        if len(matching) != 1 or matching[0].get("path") != plan.target_path:
            raise ValueError("mutation plan target role is not unique at its target path")


def _different_same_length(raw: bytes, domain: bytes) -> bytes:
    if not raw:
        raise ValueError("mutation target must contain at least one byte")
    changed = bytearray(raw)
    index = hashlib.sha256(domain + raw).digest()[0] % len(changed)
    changed[index] ^= 1
    return bytes(changed)


def _casefold_duplicate_path(value: str) -> str:
    logical = PurePosixPath(value)
    name = logical.name
    candidate_name = name.upper()
    if candidate_name == name:
        candidate_name = name.lower()
    if candidate_name == name or candidate_name.casefold() != name.casefold():
        raise ValueError(f"cannot derive a case-only duplicate for target: {value}")
    return logical.with_name(candidate_name).as_posix()


def _outside_symlink_target(value: str) -> str:
    parent_depth = len(PurePosixPath(value).parent.parts)
    return "../" * (parent_depth + 1) + "amy-outside-target.bin"


def _collision_free_generated_path(
    base_id: str, case_id: str, payload_paths: set[str]
) -> str:
    preferred = "payload/unlisted.txt"
    if preferred not in payload_paths:
        return preferred
    for counter in range(65_536):
        seed = hashlib.sha256(
            f"{base_id}\x00{case_id}\x00{counter}".encode("utf-8")
        ).hexdigest()[:16]
        candidate = f"payload/__amy_generated__/unlisted-{seed}.bin"
        if candidate not in payload_paths:
            return candidate
    raise ValueError("no deterministic collision-free generated path is available")


def resolve_mutation_plan(
    case_id: str,
    *,
    base: Mapping[str, Any] | None = None,
    mutation_targets: Mapping[str, str] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> MutationPlan:
    """Resolve base-specific paths without reading an oracle, result, or outcome."""

    if case_id not in SUPPORTED_CASE_IDS:
        raise KeyError(f"no selected-profile mutation implementation for {case_id}")
    if base is not None and mutation_targets is not None:
        raise ValueError("supply either a base blueprint or mutation_targets, not both")
    if base is None:
        base_id = "GENERIC-DEVELOPMENT-FIXTURE"
        payloads = list(GENERIC_PAYLOADS)
        targets = normalize_mutation_targets(mutation_targets)
    else:
        base_id = base.get("id")
        if not isinstance(base_id, str) or not base_id:
            raise ValueError("base blueprint has no stable ID")
        payloads = base.get("payloads")
        if not isinstance(payloads, list) or not payloads:
            raise ValueError(f"{base_id}: base blueprint has no payloads")
        targets = normalize_mutation_targets(base.get("mutation_targets"))

    payload_by_path: dict[str, Mapping[str, Any]] = {}
    for item in payloads:
        if not isinstance(item, Mapping):
            raise ValueError(f"{base_id}: payload specification is not an object")
        path = _canonical_payload_path(item.get("path"))
        if path in payload_by_path:
            raise ValueError(f"{base_id}: duplicate payload path in blueprint: {path}")
        payload_by_path[path] = item
    effective_payloads = list(payload_by_path.values())
    effective_payload_paths = set(payload_by_path)
    if policy is not None:
        fixtures = policy.get("fixture_payloads")
        if not isinstance(fixtures, Mapping):
            raise ValueError("selected policy has no fixture_payloads mapping")
        for fixture in fixtures.values():
            if not isinstance(fixture, Mapping):
                raise ValueError("selected fixture payload is not an object")
            fixture_path = _canonical_payload_path(fixture.get("path"))
            if fixture_path in payload_by_path:
                raise MutationPlanUnavailable(
                    "FIXTURE_PATH_COLLISION",
                    f"{base_id}: fixture path collides with blueprint: {fixture_path}",
                )
            effective_payloads.append(fixture)
            effective_payload_paths.add(fixture_path)
    missing = sorted(set(targets.values()) - set(payload_by_path))
    if missing:
        raise ValueError(f"{base_id}: mutation targets are absent from blueprint: {missing}")

    primary_cases = {
        "CONTENT-BITFLIP-001",
        "CONTENT-TRUNCATE-001",
        "CONTENT-SAME-SIZE-001",
        "PATH-DUPLICATE-NORMALIZED-001",
        "PATH-NONREGULAR-001",
        "PATH-SYMLINK-001",
        "SUBSTITUTION-COHERENT-001",
        "SUBSTITUTION-UNAUTHORIZED-001",
    }
    target_path: str | None = None
    source_path: str | None = None
    target_role: str | None = None
    generated_path: str | None = None
    generated_strategy: str | None = None
    symlink_target: str | None = None
    if case_id in primary_cases:
        target_path = targets["primary_nonempty_payload"]
    elif case_id == "INVENTORY-MISSING-001":
        target_path = targets["nested_payload"]
    elif case_id == "INVENTORY-OMIT-ROLE-001":
        target_path = targets["sole_required_role_payload"]
        role = payload_by_path[target_path].get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"{base_id}: sole-role target has no role")
        if sum(item.get("role") == role for item in effective_payloads) != 1:
            raise MutationPlanUnavailable(
                "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
                f"{base_id}: sole-role target role {role!r} is not unique after fixture injection",
            )
        target_role = role
    elif case_id == "PATH-HARDLINK-001":
        target_path = targets["hardlink_target"]
        source_path = targets["same_bytes_source"]

    payload_paths = effective_payload_paths
    if case_id == "INVENTORY-EXTRA-001":
        generated_path = _collision_free_generated_path(base_id, case_id, payload_paths)
        generated_strategy = "DETERMINISTIC_UNLISTED_PAYLOAD"
    elif case_id == "PATH-PARENT-001":
        generated_path = "payload/../amy-parent-escape.txt"
        generated_strategy = "INTENTIONAL_PARENT_SEGMENT_MANIFEST_ENTRY"
    elif case_id == "PATH-DUPLICATE-NORMALIZED-001":
        generated_path = _casefold_duplicate_path(target_path or "")
        if generated_path in payload_paths:
            raise ValueError(f"{base_id}: casefold duplicate path collides exactly")
        generated_strategy = "CASEFOLD_DUPLICATE_OF_TARGET"
    elif case_id == "PATH-SYMLINK-001":
        symlink_target = _outside_symlink_target(target_path or "")

    plan = MutationPlan(
        schema_version="amy.selected-profile-mutation-plan.v1-draft",
        base_id=base_id,
        case_id=case_id,
        mutation_targets_sha256=_sha256(rfc8785.dumps(targets)),
        target_path=target_path,
        source_path=source_path,
        target_role=target_role,
        generated_path=generated_path,
        generated_path_strategy=generated_strategy,
        symlink_target=symlink_target,
    )
    if plan.contains_expected_or_observed_decisions or plan.confirmatory_evidence:
        raise AssertionError("mutation plan crossed its outcome-free boundary")
    return plan


def _coherent_replace(root: Path, targets: Mapping[str, str]) -> None:
    manifest = _load_manifest(root)
    logical = targets["primary_nonempty_payload"]
    path = _target(root, targets, "primary_nonempty_payload")
    replacement = _different_same_length(
        path.read_bytes(), b"amy.selected-profile.coherent-replacement.v1\x00"
    )
    path.write_bytes(replacement)
    entry = next(item for item in manifest["payloads"] if item["path"] == logical)
    entry.update(bytes=len(replacement), sha256=_sha256(replacement))
    _write_manifest(root, manifest)


def _reattest_manifest(root: Path, policy: dict[str, Any], manifest: dict[str, Any]) -> None:
    _write_manifest(root, manifest)
    attest_selected_manifest(root, policy)


def apply_selected_profile_mutation(
    case_id: str,
    root: Path,
    policy: dict[str, Any],
    *,
    base: Mapping[str, Any] | None = None,
    mutation_plan: MutationPlan | None = None,
) -> None:
    """Apply exactly one selected-profile operator to an attested clean fixture."""

    expected_plan = resolve_mutation_plan(case_id, base=base, policy=policy)
    plan = mutation_plan or expected_plan
    if plan != expected_plan:
        raise ValueError("supplied mutation plan differs from deterministic resolution")
    if plan.case_id != case_id:
        raise ValueError("mutation plan case ID differs from requested case")
    if base is not None and plan.base_id != base.get("id"):
        raise ValueError("mutation plan base ID differs from supplied blueprint")
    _validate_plan_against_manifest(root, plan)

    if case_id == "CLEAN-001":
        return
    if case_id == "MANIFEST-MISSING-001":
        (root / "MANIFEST.jcs.json").unlink()
        return
    if case_id == "CONTENT-BITFLIP-001":
        path = root / (plan.target_path or "")
        path.write_bytes(
            _different_same_length(
                path.read_bytes(), b"amy.selected-profile.bitflip.v1\x00"
            )
        )
        return
    if case_id == "CONTENT-TRUNCATE-001":
        path = root / (plan.target_path or "")
        raw = path.read_bytes()
        if not raw:
            raise ValueError("truncate target must contain at least one byte")
        path.write_bytes(raw[:-1])
        return
    if case_id == "CONTENT-SAME-SIZE-001":
        path = root / (plan.target_path or "")
        path.write_bytes(
            _different_same_length(
                path.read_bytes(), b"amy.selected-profile.same-size.v1\x00"
            )
        )
        return
    if case_id == "INVENTORY-MISSING-001":
        (root / (plan.target_path or "")).unlink()
        return
    if case_id == "INVENTORY-EXTRA-001":
        path = root / (plan.generated_path or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(b"unlisted\n")
        return
    if case_id == "INVENTORY-OMIT-ROLE-001":
        manifest = _load_manifest(root)
        manifest["payloads"] = [
            item for item in manifest["payloads"] if item["path"] != plan.target_path
        ]
        (root / (plan.target_path or "")).unlink()
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "SUBSTITUTION-COHERENT-001":
        _coherent_replace(root, {"primary_nonempty_payload": plan.target_path or ""})
        return
    if case_id == "SUBSTITUTION-UNAUTHORIZED-001":
        _coherent_replace(root, {"primary_nonempty_payload": plan.target_path or ""})
        attest_selected_manifest(root, policy, bundle_options={"signer": "unauthorized"})
        return
    if case_id == "MANIFEST-MALFORMED-001":
        (root / "MANIFEST.jcs.json").write_bytes(b'{"broken":')
        attest_selected_manifest(root, policy)
        return
    if case_id == "MANIFEST-DUPLICATE-KEY-001":
        path = root / "MANIFEST.jcs.json"
        raw = path.read_bytes()
        manifest = json.loads(raw)
        prefix = rfc8785.dumps({"schema_version": manifest["schema_version"]})[:-1] + b","
        if not raw.startswith(b"{"):
            raise RuntimeError("canonical selected manifest is not an object")
        path.write_bytes(prefix + raw[1:])
        attest_selected_manifest(root, policy)
        return
    if case_id == "MANIFEST-SCHEMA-001":
        manifest = _load_manifest(root)
        manifest["release"]["id"] = "NOT-LOWERCASE"
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "MANIFEST-NONCANONICAL-001":
        manifest = _load_manifest(root)
        (root / "MANIFEST.jcs.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        attest_selected_manifest(root, policy)
        return
    if case_id == "MANIFEST-SELF-HASH-001":
        manifest = _load_manifest(root)
        manifest["manifest_sha256"] = "0" * 64
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "PATH-PARENT-001":
        manifest = _load_manifest(root)
        manifest["payloads"].append(
            _payload_entry(
                plan.generated_path or "",
                b"escape",
                "text/plain",
                "raw_data",
            )
        )
        manifest["payloads"].sort(key=lambda item: item["path"].encode("utf-8"))
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "PATH-DUPLICATE-NORMALIZED-001":
        manifest = _load_manifest(root)
        original = next(
            item for item in manifest["payloads"] if item["path"] == plan.target_path
        )
        duplicate = dict(original)
        duplicate["path"] = plan.generated_path
        manifest["payloads"].append(duplicate)
        manifest["payloads"].sort(key=lambda item: item["path"].encode("utf-8"))
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "PATH-SYMLINK-001":
        path = root / (plan.target_path or "")
        path.unlink()
        path.symlink_to(plan.symlink_target or "")
        return
    if case_id == "PATH-HARDLINK-001":
        path = root / (plan.target_path or "")
        source = root / (plan.source_path or "")
        if path.read_bytes() != source.read_bytes():
            raise ValueError("hardlink source and target bytes differ before mutation")
        path.unlink()
        os.link(source, path)
        return
    if case_id == "PATH-NONREGULAR-001":
        path = root / (plan.target_path or "")
        path.unlink()
        os.mkfifo(path)
        return
    if case_id == "ATTESTATION-MISSING-001":
        (root / "attestation.sigstore.json").unlink()
        return
    if case_id == "ATTESTATION-MALFORMED-001":
        (root / "attestation.sigstore.json").write_bytes(b"{")
        return
    if case_id == "STATEMENT-MALFORMED-001":
        attest_selected_manifest(root, policy, statement=b"{")
        return
    if case_id == "SIGNATURE-CORRUPT-001":
        attest_selected_manifest(root, policy, bundle_options={"corrupt_signature": True})
        return
    if case_id == "SIGNATURE-ALGORITHM-001":
        attest_selected_manifest(root, policy, bundle_options={"algorithm": "ed448"})
        return
    if case_id == "CERTIFICATE-TIME-001":
        attest_selected_manifest(
            root, policy, bundle_options={"certificate_time_valid": False}
        )
        return
    if case_id == "IDENTITY-WORKFLOW-001":
        attest_selected_manifest(root, policy, bundle_options={"signer": "wrong_workflow"})
        return
    if case_id == "SUBJECT-REPLAY-001":
        statement = make_selected_statement(b"another valid manifest", policy)
        attest_selected_manifest(root, policy, statement=statement)
        return
    if case_id == "TRANSPARENCY-MISSING-001":
        attest_selected_manifest(root, policy, bundle_options={"include_transparency": False})
        return
    if case_id == "PREDICATE-WRONG-TYPE-001":
        attest_selected_manifest(
            root,
            policy,
            statement_options={"predicate_type": "https://example.invalid/predicate/v1"},
        )
        return
    if case_id == "SOURCE-WRONG-REVISION-001":
        attest_selected_manifest(root, policy, statement_options={"source_revision": "e" * 40})
        return
    if case_id == "WORKFLOW-PARAMETER-MISMATCH-001":
        attest_selected_manifest(
            root,
            policy,
            statement_options={"workflow_path": ".github/workflows/wrong.yml"},
        )
        return
    if case_id == "BUILDER-PREDICATE-MISMATCH-001":
        attest_selected_manifest(
            root,
            policy,
            statement_options={"builder_id": "https://example.invalid/untrusted-builder"},
        )
        return

    if case_id in {
        "BUILD-DIRTY-001",
        "BUILD-METADATA-MISSING-001",
        "EXECUTION-IMAGE-MISMATCH-001",
        "MATERIAL-LOCK-MISMATCH-001",
        "SNAPSHOT-DIGEST-MISMATCH-001",
        "SNAPSHOT-ROLE-MISMATCH-001",
        "SOURCE-TREE-MISMATCH-001",
    }:
        manifest = _load_manifest(root)
        if case_id == "BUILD-DIRTY-001":
            manifest["build_metadata"]["source"]["dirty"] = True
        elif case_id == "BUILD-METADATA-MISSING-001":
            manifest.pop("build_metadata")
        elif case_id == "EXECUTION-IMAGE-MISMATCH-001":
            manifest["build_metadata"]["execution_image"]["digest"] = f"sha256:{'e' * 64}"
        elif case_id == "MATERIAL-LOCK-MISMATCH-001":
            manifest["build_metadata"]["dependency_lock"]["sha256"] = "e" * 64
        elif case_id == "SNAPSHOT-DIGEST-MISMATCH-001":
            manifest["build_metadata"]["source"]["snapshot"]["sha256"] = "e" * 64
        elif case_id == "SNAPSHOT-ROLE-MISMATCH-001":
            snapshot_path = manifest["build_metadata"]["source"]["snapshot"]["path"]
            entry = next(
                item for item in manifest["payloads"] if item["path"] == snapshot_path
            )
            entry["role"] = "raw_data"
        elif case_id == "SOURCE-TREE-MISMATCH-001":
            manifest["build_metadata"]["source"]["tree"] = "e" * 40
        _reattest_manifest(root, policy, manifest)
        return
    if case_id == "RESOURCE-MANIFEST-LIMIT-001":
        limit = policy["limits"]["manifest_max_bytes"]
        (root / "MANIFEST.jcs.json").write_bytes(b" " * (limit + 1))
        return
    raise KeyError(f"no selected-profile mutation implementation for {case_id}")


def snapshot_tree(root: Path) -> list[dict[str, Any]]:
    """Return a deterministic, content-oriented tree observation."""

    records: list[dict[str, Any]] = []
    for path in sorted(
        root.rglob("*"), key=lambda value: value.relative_to(root).as_posix().encode("utf-8")
    ):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            record: dict[str, Any] = {"path": relative, "kind": "directory"}
        elif stat.S_ISLNK(info.st_mode):
            record = {"path": relative, "kind": "symlink", "target": os.readlink(path)}
        elif stat.S_ISREG(info.st_mode):
            raw = path.read_bytes()
            record = {
                "path": relative,
                "kind": "regular",
                "bytes": len(raw),
                "sha256": _sha256(raw),
                "link_count": info.st_nlink,
            }
        else:
            record = {
                "path": relative,
                "kind": "nonregular",
                "mode": stat.S_IFMT(info.st_mode),
            }
        records.append(record)
    return records


def mutation_observation(
    case_id: str,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe actual tree changes without joining any expected result label."""

    before_by_path = {record["path"]: record for record in before}
    after_by_path = {record["path"]: record for record in after}
    changed_paths = sorted(
        path
        for path in set(before_by_path) | set(after_by_path)
        if before_by_path.get(path) != after_by_path.get(path)
    )
    added_paths = sorted(set(after_by_path) - set(before_by_path))
    removed_paths = sorted(set(before_by_path) - set(after_by_path))
    payload_digest_changes = sorted(
        path
        for path in set(before_by_path) & set(after_by_path)
        if path.startswith("payload/")
        and before_by_path[path].get("sha256") != after_by_path[path].get("sha256")
    )
    return {
        "case_id": case_id,
        "base_tree_sha256": _sha256(rfc8785.dumps(before)),
        "mutated_tree_sha256": _sha256(rfc8785.dumps(after)),
        "changed_paths": changed_paths,
        "added_paths": added_paths,
        "removed_paths": removed_paths,
        "payload_digest_changed_paths": payload_digest_changes,
        "contains_expected_or_observed_decisions": False,
        "confirmatory_evidence": False,
    }
