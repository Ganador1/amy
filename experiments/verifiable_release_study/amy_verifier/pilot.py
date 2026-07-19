from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import locale
import os
import platform
import shutil
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cryptography
import jsonschema
import rfc8785
from jsonschema import Draft202012Validator

from .fixture_crypto import fixture_trust_policy, make_fixture_bundle, make_statement
from .verifier import ImplementationIdentity, verify_release


STUDY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = (
    "README.md",
    "CHANGELOG.md",
    "protocol/PROTOCOL_DRAFT.md",
    "protocol/THREAT_MODEL.md",
    "protocol/VERSIONING_AND_SIGNING_POLICY.md",
    "protocol/PATH_POLICY_DRAFT.md",
    "protocol/CLAIM_BOUNDARIES.md",
    "protocol/LIMITATIONS_AND_BOUNDARIES.md",
    "protocol/ATTACK_CATALOG.json",
    "protocol/REASON_CODES.json",
    "protocol/TRUST_POLICY_DRAFT.json",
    "schemas/manifest.schema.json",
    "schemas/manifest-production-v0.2.schema.json",
    "schemas/verifier-result.schema.json",
    "preregistration/OSF_PREREGISTRATION_DRAFT.md",
    "evidence/SOURCE_LEDGER.md",
    "evidence/CLAIM_EVIDENCE_MATRIX.csv",
    "pyproject.toml",
    "uv.lock",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "MANIFEST.jcs.json").read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: dict[str, Any], *, canonical: bool = True) -> None:
    path = root / "MANIFEST.jcs.json"
    if canonical:
        path.write_bytes(rfc8785.dumps(manifest))
    else:
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _payload_entry(path: str, raw: bytes, media_type: str, role: str) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "media_type": media_type,
        "role": role,
    }


def build_clean_release(root: Path, policy: dict[str, Any]) -> None:
    files = {
        "payload/analysis.py": (b"print('pilot')\n", "text/x-python", "analysis_code"),
        "payload/data-copy.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/data.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/results/result.json": (
            b'{"sum":3}\n',
            "application/json",
            "analysis_output",
        ),
    }
    payloads = []
    for relative, (raw, media_type, role) in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        payloads.append(_payload_entry(relative, raw, media_type, role))
    manifest = {
        "schema_version": "0.1.0-draft",
        "release": {"id": "pilot-clean", "version": "0.1.0", "kind": "benchmark_case"},
        "payloads": payloads,
    }
    _write_manifest(root, manifest)
    attest_current_manifest(root, policy)


def attest_current_manifest(
    root: Path,
    policy: dict[str, Any],
    *,
    statement: dict[str, Any] | bytes | None = None,
    statement_options: dict[str, Any] | None = None,
    bundle_options: dict[str, Any] | None = None,
) -> None:
    manifest_raw = (root / "MANIFEST.jcs.json").read_bytes()
    if statement is None:
        statement = make_statement(manifest_raw, policy, **(statement_options or {}))
    statement_raw = statement if isinstance(statement, bytes) else rfc8785.dumps(statement)
    bundle = make_fixture_bundle(statement_raw, **(bundle_options or {}))
    (root / "attestation.sigstore.json").write_bytes(bundle)


def _coherent_replace(root: Path) -> None:
    manifest = _manifest(root)
    replacement = b"x,y\n9,8\n"
    (root / "payload" / "data.csv").write_bytes(replacement)
    entry = next(item for item in manifest["payloads"] if item["path"] == "payload/data.csv")
    entry.update(bytes=len(replacement), sha256=_sha256(replacement))
    _write_manifest(root, manifest)


def _mutate(case_id: str, root: Path, policy: dict[str, Any]) -> None:
    if case_id == "CLEAN-001":
        return
    if case_id == "MANIFEST-MISSING-001":
        (root / "MANIFEST.jcs.json").unlink()
        return
    if case_id == "CONTENT-BITFLIP-001":
        path = root / "payload" / "data.csv"
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.write_bytes(raw)
        return
    if case_id == "CONTENT-TRUNCATE-001":
        path = root / "payload" / "data.csv"
        path.write_bytes(path.read_bytes()[:-1])
        return
    if case_id == "CONTENT-SAME-SIZE-001":
        path = root / "payload" / "data.csv"
        path.write_bytes(b"a,b\n9,8\n")
        return
    if case_id == "INVENTORY-MISSING-001":
        (root / "payload" / "results" / "result.json").unlink()
        return
    if case_id == "INVENTORY-EXTRA-001":
        (root / "payload" / "unlisted.txt").write_bytes(b"unlisted\n")
        return
    if case_id == "INVENTORY-OMIT-ROLE-001":
        manifest = _manifest(root)
        manifest["payloads"] = [
            item for item in manifest["payloads"] if item["role"] != "analysis_code"
        ]
        (root / "payload" / "analysis.py").unlink()
        _write_manifest(root, manifest)
        attest_current_manifest(root, policy)
        return
    if case_id == "SUBSTITUTION-COHERENT-001":
        _coherent_replace(root)
        return
    if case_id == "SUBSTITUTION-UNAUTHORIZED-001":
        _coherent_replace(root)
        attest_current_manifest(root, policy, bundle_options={"signer": "unauthorized"})
        return
    if case_id == "MANIFEST-MALFORMED-001":
        (root / "MANIFEST.jcs.json").write_bytes(b'{"broken":')
        attest_current_manifest(root, policy)
        return
    if case_id == "MANIFEST-DUPLICATE-KEY-001":
        raw = (root / "MANIFEST.jcs.json").read_bytes()
        raw = raw.replace(
            b'{"payloads":',
            b'{"schema_version":"0.1.0-draft","payloads":',
            1,
        )
        (root / "MANIFEST.jcs.json").write_bytes(raw)
        attest_current_manifest(root, policy)
        return
    if case_id == "MANIFEST-SCHEMA-001":
        manifest = _manifest(root)
        manifest["release"]["id"] = "NOT-LOWERCASE"
        _write_manifest(root, manifest)
        attest_current_manifest(root, policy)
        return
    if case_id == "MANIFEST-NONCANONICAL-001":
        manifest = _manifest(root)
        _write_manifest(root, manifest, canonical=False)
        attest_current_manifest(root, policy)
        return
    if case_id == "MANIFEST-SELF-HASH-001":
        manifest = _manifest(root)
        manifest["manifest_sha256"] = "0" * 64
        _write_manifest(root, manifest)
        attest_current_manifest(root, policy)
        return
    if case_id == "PATH-PARENT-001":
        manifest = _manifest(root)
        manifest["payloads"].append(
            _payload_entry("payload/../escape.txt", b"escape", "text/plain", "raw_data")
        )
        manifest["payloads"].sort(key=lambda item: item["path"].encode("utf-8"))
        _write_manifest(root, manifest)
        attest_current_manifest(root, policy)
        return
    if case_id == "PATH-DUPLICATE-NORMALIZED-001":
        manifest = _manifest(root)
        original = next(item for item in manifest["payloads"] if item["path"] == "payload/data.csv")
        duplicate = dict(original)
        duplicate["path"] = "payload/DATA.csv"
        manifest["payloads"].append(duplicate)
        manifest["payloads"].sort(key=lambda item: item["path"].encode("utf-8"))
        _write_manifest(root, manifest)
        attest_current_manifest(root, policy)
        return
    if case_id == "PATH-SYMLINK-001":
        path = root / "payload" / "data.csv"
        path.unlink()
        path.symlink_to("../../outside.csv")
        return
    if case_id == "PATH-HARDLINK-001":
        path = root / "payload" / "data.csv"
        path.unlink()
        os.link(root / "payload" / "data-copy.csv", path)
        return
    if case_id == "PATH-NONREGULAR-001":
        path = root / "payload" / "data.csv"
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
        attest_current_manifest(root, policy, statement=b"{")
        return
    if case_id == "SIGNATURE-CORRUPT-001":
        attest_current_manifest(root, policy, bundle_options={"corrupt_signature": True})
        return
    if case_id == "SIGNATURE-ALGORITHM-001":
        attest_current_manifest(root, policy, bundle_options={"algorithm": "ed448"})
        return
    if case_id == "CERTIFICATE-TIME-001":
        attest_current_manifest(root, policy, bundle_options={"certificate_time_valid": False})
        return
    if case_id == "IDENTITY-WORKFLOW-001":
        attest_current_manifest(root, policy, bundle_options={"signer": "wrong_workflow"})
        return
    if case_id == "SUBJECT-REPLAY-001":
        replay_statement = make_statement(b"another valid manifest", policy)
        attest_current_manifest(root, policy, statement=replay_statement)
        return
    if case_id == "TRANSPARENCY-MISSING-001":
        attest_current_manifest(root, policy, bundle_options={"include_transparency": False})
        return
    if case_id == "PREDICATE-WRONG-TYPE-001":
        attest_current_manifest(
            root,
            policy,
            statement_options={"predicate_type": "https://example.invalid/predicate/v1"},
        )
        return
    if case_id == "SOURCE-WRONG-REVISION-001":
        attest_current_manifest(root, policy, statement_options={"source_revision": "e" * 40})
        return
    if case_id == "BUILD-DIRTY-001":
        attest_current_manifest(root, policy, statement_options={"dirty": True})
        return
    if case_id == "MATERIAL-LOCK-MISMATCH-001":
        attest_current_manifest(
            root,
            policy,
            statement_options={
                "material_overrides": {"dependency_lock_sha256": "f" * 64}
            },
        )
        return
    if case_id == "RESOURCE-MANIFEST-LIMIT-001":
        limit = policy["limits"]["manifest_max_bytes"]
        (root / "MANIFEST.jcs.json").write_bytes(b" " * (limit + 1))
        return
    raise KeyError(f"no pilot mutation implementation for {case_id}")


def _snapshot_tree(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix().encode()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            kind = "directory"
            record: dict[str, Any] = {"path": relative, "kind": kind}
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
            record = {"path": relative, "kind": "nonregular", "mode": stat.S_IFMT(info.st_mode)}
        records.append(record)
    return records


def _tar_tree(root: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    inode_first_path: dict[tuple[int, int], str] = {}
    with tarfile.open(destination, mode="w", format=tarfile.PAX_FORMAT) as archive:
        paths = [root / "payload"] if (root / "payload").exists() else []
        paths.extend(path for path in root.rglob("*") if path != root / "payload")
        for path in sorted(set(paths), key=lambda value: value.relative_to(root).as_posix().encode()):
            relative = path.relative_to(root).as_posix()
            source_stat = path.lstat()
            info = tarfile.TarInfo(relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            if stat.S_ISDIR(source_stat.st_mode):
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            elif stat.S_ISLNK(source_stat.st_mode):
                info.type = tarfile.SYMTYPE
                info.mode = 0o777
                info.linkname = os.readlink(path)
                archive.addfile(info)
            elif stat.S_ISFIFO(source_stat.st_mode):
                info.type = tarfile.FIFOTYPE
                info.mode = 0o644
                archive.addfile(info)
            elif stat.S_ISREG(source_stat.st_mode):
                inode_key = (source_stat.st_dev, source_stat.st_ino)
                if source_stat.st_nlink > 1 and inode_key in inode_first_path:
                    info.type = tarfile.LNKTYPE
                    info.mode = 0o644
                    info.linkname = inode_first_path[inode_key]
                    archive.addfile(info)
                else:
                    inode_first_path[inode_key] = relative
                    raw = path.read_bytes()
                    info.type = tarfile.REGTYPE
                    info.mode = 0o644
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            else:
                raise RuntimeError(f"unsupported pilot archive file type: {relative}")
    return _sha256(destination.read_bytes())


def _source_archive(destination: Path) -> str:
    include = [
        STUDY_ROOT / "amy_verifier",
        STUDY_ROOT / "scripts",
        STUDY_ROOT / "schemas",
        STUDY_ROOT / "protocol",
        STUDY_ROOT / "pyproject.toml",
        STUDY_ROOT / "uv.lock",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, mode="w", format=tarfile.PAX_FORMAT) as archive:
        files: list[Path] = []
        for path in include:
            if path.is_dir():
                files.extend(
                    candidate
                    for candidate in path.rglob("*")
                    if candidate.is_file() and "__pycache__" not in candidate.parts
                )
            else:
                files.append(path)
        for path in sorted(set(files), key=lambda value: value.relative_to(STUDY_ROOT).as_posix().encode()):
            relative = path.relative_to(STUDY_ROOT).as_posix()
            raw = path.read_bytes()
            info = tarfile.TarInfo(relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return _sha256(destination.read_bytes())


def _git_identity() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=STUDY_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=STUDY_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    return commit, dirty


def _environment() -> dict[str, Any]:
    return {
        "recorded_at": _utc_now(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "locale": locale.setlocale(locale.LC_ALL, None),
        "timezone_env": os.environ.get("TZ"),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("cryptography", "jsonschema", "pytest", "rfc8785")
        },
        "cryptography_version": cryptography.__version__,
        "jsonschema_version": importlib.metadata.version("jsonschema"),
    }


def run_pilot(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    contract_records = []
    for relative in CONTRACT_FILES:
        raw = (STUDY_ROOT / relative).read_bytes()
        destination = output_dir / "contracts" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        contract_records.append({"path": relative, "bytes": len(raw), "sha256": _sha256(raw)})
    _write_json(output_dir / "contract_hashes.json", contract_records)

    catalog = json.loads(
        (output_dir / "contracts" / "protocol" / "ATTACK_CATALOG.json").read_text(
            encoding="utf-8"
        )
    )
    base_policy = json.loads(
        (output_dir / "contracts" / "protocol" / "TRUST_POLICY_DRAFT.json").read_text(
            encoding="utf-8"
        )
    )
    policy = fixture_trust_policy(base_policy)
    policy_path = output_dir / "pilot_fixture_trust_policy.jcs.json"
    policy_path.write_bytes(rfc8785.dumps(policy))
    _write_json(output_dir / "environment.json", _environment())

    source_archive_path = output_dir / "source" / "pilot_source.tar"
    source_archive_sha256 = _source_archive(source_archive_path)
    git_commit, dirty = _git_identity()
    implementation = ImplementationIdentity(
        version="0.3.1.dev0",
        git_commit=git_commit,
        source_archive_sha256=source_archive_sha256,
        dirty=dirty,
    )

    base_root = output_dir / "base_clean" / "release"
    build_clean_release(base_root, policy)
    base_snapshot = _snapshot_tree(base_root)
    _write_json(output_dir / "base_clean" / "tree.json", base_snapshot)

    result_schema = json.loads(
        (output_dir / "contracts" / "schemas" / "verifier-result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result_validator = Draft202012Validator(result_schema)
    result_paths: list[Path] = []
    case_records: list[dict[str, Any]] = []
    for case in catalog["cases"]:
        case_id = case["id"]
        release_root = output_dir / "cases" / case_id / "release"
        shutil.copytree(base_root, release_root, symlinks=True)
        before = _snapshot_tree(release_root)
        _mutate(case_id, release_root, policy)
        after = _snapshot_tree(release_root)
        archive_path = output_dir / "archives" / f"{case_id}.tar"
        archive_sha256 = _tar_tree(release_root, archive_path)
        mutation_record = {
            "case_id": case_id,
            "catalog_operation": case["operation"],
            "prerequisites": case["prerequisites"],
            "base_tree_sha256": _sha256(rfc8785.dumps(before)),
            "mutated_tree_sha256": _sha256(rfc8785.dumps(after)),
            "archive_path": str(archive_path.relative_to(output_dir)),
            "archive_sha256": archive_sha256,
            "before": before,
            "after": after,
        }
        _write_json(output_dir / "cases" / case_id / "mutation_record.json", mutation_record)
        case_records.append(mutation_record)

        for profile_id in ("P0", "P1", "P2", "P3"):
            result = verify_release(
                release_root,
                profile_id=profile_id,
                case_id=case_id,
                case_archive_sha256=archive_sha256,
                trust_policy_path=policy_path,
                implementation=implementation,
            manifest_schema_path=output_dir / "contracts" / "schemas" / "manifest.schema.json",
                attestation_backend="pilot_fixture" if profile_id in {"P2", "P3"} else None,
            )
            schema_errors = sorted(
                result_validator.iter_errors(result),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if schema_errors:
                raise RuntimeError(
                    f"invalid result {case_id}/{profile_id}: "
                    + "; ".join(error.message for error in schema_errors)
                )
            result_path = output_dir / "results" / case_id / f"{profile_id}.json"
            _write_json(result_path, result)
            result_paths.append(result_path)

    result_hashes = []
    for path in sorted(result_paths):
        raw = path.read_bytes()
        result_hashes.append(
            {"path": str(path.relative_to(output_dir)), "sha256": _sha256(raw), "bytes": len(raw)}
        )
        path.chmod(0o444)
    _write_json(output_dir / "result_hashes.json", result_hashes)

    rows: list[dict[str, Any]] = []
    conformance_mismatches = 0
    target_misses = 0
    clean_failures = 0
    for case in catalog["cases"]:
        for profile_id in ("P0", "P1", "P2", "P3"):
            result_path = output_dir / "results" / case["id"] / f"{profile_id}.json"
            observed = json.loads(result_path.read_text(encoding="utf-8"))
            expected = case["profile_expectations"][profile_id]
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
            rows.append(
                {
                    "case_id": case["id"],
                    "family": case["family"],
                    "kind": case["kind"],
                    "profile_id": profile_id,
                    "target_decision": case["target_decision"],
                    "expected_decision": expected["decision"],
                    "expected_primary_reason": expected["primary_reason"],
                    "observed_decision": observed["decision"],
                    "observed_primary_reason": observed["primary_reason"],
                    "profile_conforms": str(conforms).lower(),
                    "target_miss": str(target_miss).lower(),
                    "clean_failure": str(clean_failure).lower(),
                    "result_sha256": _sha256(result_path.read_bytes()),
                }
            )
    matrix_path = output_dir / "expected_vs_observed.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "pilot_only": True,
        "confirmatory_evidence": False,
        "started_from_draft_contract": catalog["catalog_version"],
        "completed_at": _utc_now(),
        "case_count": len(catalog["cases"]),
        "profile_count": 4,
        "result_count": len(rows),
        "profile_conformance_mismatches": conformance_mismatches,
        "target_misses_across_all_profiles": target_misses,
        "clean_failures": clean_failures,
        "source_archive_sha256": source_archive_sha256,
        "trust_policy_sha256": _sha256(policy_path.read_bytes()),
        "catalog_sha256": _sha256(
            (output_dir / "contracts" / "protocol" / "ATTACK_CATALOG.json").read_bytes()
        ),
        "contract_hash_ledger_sha256": _sha256((output_dir / "contract_hashes.json").read_bytes()),
        "result_hash_ledger_sha256": _sha256((output_dir / "result_hashes.json").read_bytes()),
        "matrix_sha256": _sha256(matrix_path.read_bytes()),
        "note": "Exploratory synthetic pilot; results may change the draft and cannot enter confirmatory denominators.",
    }
    _write_json(output_dir / "summary.json", summary)
    return summary
