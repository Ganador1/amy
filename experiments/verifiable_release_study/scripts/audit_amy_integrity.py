#!/usr/bin/env python3
"""Read-only integrity and provenance audit for the A.M.Y repository.

The scanner deliberately does not import A.M.Y, contact network services, run
experiments, load model objects, or read secret values.  It distinguishes a
currently matching checksum from authenticated provenance and from scientific
reproducibility.  Output is deterministic for a fixed repository byte snapshot.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = STUDY_ROOT.parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEX128_RE = re.compile(r"^[0-9a-f]{32}$")
PACKAGE_DIRECTORIES = (
    "core",
    "cognition",
    "memory",
    "senses",
    "skills",
    "communication",
    "sandbox",
    "evolution",
)
EXCLUDED_DIRECTORY_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".worktrees",
    "__pycache__",
    "node_modules",
    "site-packages",
    "test_env",
    "venv",
}
AUTHENTICATION_KEYS = {
    "attestation",
    "certificate",
    "dsse",
    "hmac_signature",
    "signature",
    "signatures",
    "sigstore_bundle",
}
SOURCE_REVISION_KEYS = {
    "commit",
    "git_commit",
    "git_sha",
    "repository_commit",
    "source_revision",
}
SOURCE_DIGEST_KEYS = {"code_sha256", "script_sha256", "source_sha256"}
INPUT_DIGEST_KEYS = {
    "dataset_sha256",
    "input_hash",
    "input_sha256",
    "inputs_sha256",
}
DEPENDENCY_DIGEST_KEYS = {
    "dependency_lock_sha256",
    "environment_lock_sha256",
    "lock_sha256",
    "requirements_sha256",
    "uv_lock_sha256",
}
DEPENDENCY_VERSION_KEYS = {"dependencies", "packages", "pip_freeze", "requirements"}
CONTAINER_DIGEST_KEYS = {"container_digest", "execution_image_digest", "image_digest"}
SEED_KEYS = {"random_seed", "seed"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed with {completed.returncode}")
    return completed.stdout.strip()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def inventory_sha256(entries: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for path, file_digest in sorted(entries):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def recursive_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key).lower())
            keys.update(recursive_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(recursive_keys(item))
    return keys


def count_key_coverage(records: list[set[str]], names: set[str]) -> int:
    return sum(bool(keys & names) for keys in records)


def source_paths(root: Path) -> list[Path]:
    paths = [root / "amy.py"]
    for name in PACKAGE_DIRECTORIES:
        package = root / name
        if package.is_dir():
            for directory, child_directories, files in os.walk(package, topdown=True):
                child_directories[:] = sorted(
                    child
                    for child in child_directories
                    if child not in EXCLUDED_DIRECTORY_NAMES
                )
                paths.extend(
                    Path(directory) / filename
                    for filename in sorted(files)
                    if filename.endswith(".py")
                )
    return sorted(path for path in paths if path.is_file())


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def function_evidence(path: Path, function_name: str) -> dict[str, Any]:
    """Return a hash-bound source segment for one named function or method."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if candidates:
        minimum_indent = min(node.col_offset for node in candidates)
        candidates = [node for node in candidates if node.col_offset == minimum_indent]
    if len(candidates) != 1:
        return {"found": False, "candidate_count": len(candidates)}
    node = candidates[0]
    lines = source.splitlines(keepends=True)
    segment = "".join(lines[node.lineno - 1 : node.end_lineno])
    return {
        "found": True,
        "start_line": node.lineno,
        "end_line": node.end_lineno,
        "source_sha256": sha256_bytes(segment.encode("utf-8")),
        "source": segment,
    }


def audit_static_code(root: Path, tracked: set[str]) -> dict[str, Any]:
    paths = source_paths(root)
    call_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hash_algorithms: Counter[str] = Counter()
    parse_failures: list[dict[str, str]] = []
    source_hashes: dict[str, str] = {}
    group_patterns = {
        "unsafe_deserialization": re.compile(
            r"(?:^|\.)(?:pickle|joblib)\.(?:load|loads)$|(?:^|\.)torch\.load$"
        ),
        "subprocess_execution": re.compile(
            r"^(?:subprocess\.(?:run|Popen|check_output)|"
            r"asyncio\.create_subprocess_exec)$"
        ),
        "dynamic_evaluation": re.compile(r"^(?:eval|exec)$"),
        "network_io": re.compile(
            r"(?:^|\.)(?:urlopen|request|requests\.(?:get|post|request)|"
            r"httpx\.(?:get|post|request|AsyncClient)|AsyncClient)$"
        ),
        "provenance_hmac": re.compile(
            r"(?:^|\.)(?:sign_provenance|verify_provenance|hmac\.new)$"
        ),
    }
    for path in paths:
        rel = relative(path, root)
        source_hashes[rel] = sha256(path)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted_name(node.func)
            if not name:
                continue
            for group, pattern in group_patterns.items():
                if pattern.search(name):
                    line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                    call_groups[group].append(
                        {"path": rel, "line": node.lineno, "call": name, "code": line}
                    )
            if name.startswith("hashlib."):
                hash_algorithms[name.removeprefix("hashlib.")] += 1

    workflow_paths = sorted((root / ".github/workflows").glob("*.y*ml"))
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in workflow_paths
    )
    signing_path = root / "core/security_hardening.py"
    manager_path = root / "core/provenance.py"
    generator_path = root / "communication/paper_generator.py"
    numeric_path = root / "communication/numeric_verifier.py"
    hmac_sign = function_evidence(signing_path, "sign_provenance") if signing_path.is_file() else {}
    hmac_verify = function_evidence(signing_path, "verify_provenance") if signing_path.is_file() else {}
    manager_verify = function_evidence(manager_path, "verify_experiment_id") if manager_path.is_file() else {}
    gate_hash = function_evidence(generator_path, "_provenance_output_hash") if generator_path.is_file() else {}
    prepublication_gate = function_evidence(generator_path, "_prepublication_gate") if generator_path.is_file() else {}
    numeric_verify = function_evidence(numeric_path, "verify_text") if numeric_path.is_file() else {}

    signing_text = signing_path.read_text(encoding="utf-8") if signing_path.is_file() else ""
    gate_hash_source = str(gate_hash.get("source", ""))
    manager_verify_source = str(manager_verify.get("source", ""))
    numeric_verify_source = str(numeric_verify.get("source", ""))
    source_facts = {
        "hmac_helper_present": signing_path.is_file(),
        "hmac_helper_git_tracked": relative(signing_path, root) in tracked,
        "active_provenance_manager_calls_sign_provenance": (
            "sign_provenance(" in manager_path.read_text(encoding="utf-8")
            if manager_path.is_file()
            else False
        ),
        "paper_gate_calls_verify_provenance": (
            "verify_provenance(" in generator_path.read_text(encoding="utf-8")
            if generator_path.is_file()
            else False
        ),
        "hmac_key_environment_variable_named": (
            "AMY_PROVENANCE_HMAC_KEY" if "AMY_PROVENANCE_HMAC_KEY" in signing_text else None
        ),
        "hmac_helper_has_random_per_process_fallback": "_secrets.token_hex(32)" in signing_text,
        "hmac_verify_reads_output_txt": "output.txt" in str(hmac_verify.get("source", "")),
        "manager_verify_reads_output_txt": "output.txt" in manager_verify_source,
        "manager_verify_requires_stored_output_hash": "output_hash" in manager_verify_source,
        "paper_gate_hash_reader_reads_output_txt": "output.txt" in gate_hash_source,
        "paper_gate_hash_reader_recomputes_sha256": (
            "hashlib" in gate_hash_source or "sha256(" in gate_hash_source
        ),
        "paper_gate_hash_reader_accepts_declared_64_hex_format": (
            "fullmatch" in gate_hash_source and "{64}" in gate_hash_source
        ),
        "numeric_verifier_treats_nonempty_experiment_id_list_as_explicit_provenance": (
            "has_explicit_provenance = bool(experiment_ids)" in numeric_verify_source
        ),
        "numeric_verifier_resolves_each_experiment_record": (
            "EXPERIMENTS_DIR" in numeric_verify_source
            or "provenance.json" in numeric_verify_source
        ),
        "active_workflow_mentions_sigstore_or_attestation": bool(
            re.search(r"(?i)\b(?:sigstore|cosign|attest(?:ation)?|gh attestation)\b", workflow_text)
        ),
        "active_workflow_mentions_hmac_provenance_verification": bool(
            re.search(r"verify_provenance|hmac_signature", workflow_text)
        ),
    }
    return {
        "scope": {
            "python_files_scanned": len(paths),
            "package_directories": list(PACKAGE_DIRECTORIES),
            "imports_amy": False,
        },
        "source_snapshot_sha256": inventory_sha256(source_hashes.items()),
        "source_sha256": dict(sorted(source_hashes.items())),
        "tracked_source_files": sum(path in tracked for path in source_hashes),
        "untracked_source_files": sorted(path for path in source_hashes if path not in tracked),
        "parse_failures": parse_failures,
        "call_sites": {key: sorted(value, key=lambda item: (item["path"], item["line"])) for key, value in sorted(call_groups.items())},
        "direct_hashlib_constructor_counts": dict(sorted(hash_algorithms.items())),
        "workflow_files": [relative(path, root) for path in workflow_paths],
        "source_facts": source_facts,
        "function_evidence": {
            "core.security_hardening.sign_provenance": hmac_sign,
            "core.security_hardening.verify_provenance": hmac_verify,
            "core.provenance.ProvenanceManager.verify_experiment_id": manager_verify,
            "communication.paper_generator._provenance_output_hash": gate_hash,
            "communication.paper_generator.PaperGenerator._prepublication_gate": prepublication_gate,
            "communication.numeric_verifier.NumericVerifier.verify_text": numeric_verify,
        },
    }


def audit_directory_provenance(root: Path) -> dict[str, Any]:
    base = root / "data/experiments"
    paths = sorted(base.glob("*/provenance.json"))
    parse_failures: list[dict[str, str]] = []
    missing_outputs: list[str] = []
    digest_failures: list[dict[str, Any]] = []
    malformed_digests: list[dict[str, Any]] = []
    id_mismatches: list[dict[str, str]] = []
    length_mismatches: list[dict[str, Any]] = []
    missing_output_lengths: list[str] = []
    authenticated_records: list[str] = []
    test_like_records: list[str] = []
    inventory: list[tuple[str, str]] = []
    output_digests: Counter[str] = Counter()
    output_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    success_values: Counter[str] = Counter()
    success_true_with_error_marker: list[dict[str, Any]] = []
    direct_prime_limit_checks = 0
    direct_prime_limit_mismatches: list[dict[str, Any]] = []
    key_sets: list[set[str]] = []
    schema_versions: Counter[str] = Counter()
    exact_matches = 0
    output_files = 0

    for path in paths:
        rel = relative(path, root)
        prov_digest = sha256(path)
        inventory.append((rel, prov_digest))
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        if not isinstance(record, dict):
            parse_failures.append({"path": rel, "error": "top_level_not_object"})
            continue
        keys = recursive_keys(record)
        key_sets.append(keys)
        schema_versions[str(record.get("provenance_version", "MISSING"))] += 1
        if keys & AUTHENTICATION_KEYS:
            authenticated_records.append(rel)
        expected_id = path.parent.name
        if re.search(r"(?:^|[_-])(?:test|fixture|tmp)(?:$|[_-])", expected_id, re.IGNORECASE):
            test_like_records.append(rel)
        observed_id = str(record.get("experiment_id", ""))
        if observed_id != expected_id:
            id_mismatches.append(
                {"path": rel, "directory_id": expected_id, "record_id": observed_id}
            )
        output_path = path.parent / "output.txt"
        if not output_path.is_file():
            missing_outputs.append(relative(output_path, root))
            continue
        output_files += 1
        output_digest = sha256(output_path)
        inventory.append((relative(output_path, root), output_digest))
        output_digests[output_digest] += 1
        tool = record.get("tool") or {}
        declared_input = str(tool.get("input", ""))
        declared_success = tool.get("success", "MISSING")
        success_values[str(declared_success)] += 1
        output_groups[output_digest].append(
            {
                "path": rel,
                "tool_name": str(tool.get("name", "")),
                "declared_input_sha256": sha256_bytes(declared_input.encode("utf-8")),
                "declared_success": declared_success,
            }
        )
        expected_digest = tool.get("output_hash")
        if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
            malformed_digests.append({"path": rel, "stored_output_hash": expected_digest})
        elif expected_digest == output_digest:
            exact_matches += 1
        else:
            digest_failures.append(
                {
                    "path": rel,
                    "stored_output_sha256": expected_digest,
                    "actual_output_sha256": output_digest,
                }
            )
        try:
            output_text = output_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            output_text = None
        if output_text is not None and declared_success is True and re.search(
            r"(?im)^\s*error\s*:|\bunknown operation\b|\btool not found\b|"
            r"\bnot implemented\b|\bmock output\b|\bplaceholder\b",
            output_text,
        ):
            success_true_with_error_marker.append(
                {
                    "path": rel,
                    "tool_name": str(tool.get("name", "")),
                    "declared_input_sha256": sha256_bytes(declared_input.encode("utf-8")),
                    "output_sha256": output_digest,
                }
            )
        if (
            output_text is not None
            and str(tool.get("name", "")) == "prime_gap_analysis"
            and re.fullmatch(r"[0-9][0-9_]*", declared_input.strip())
        ):
            reported_match = re.search(r"Prime gap analysis up to (\d+)", output_text)
            requested_limit = int(declared_input.strip().replace("_", ""))
            if reported_match and requested_limit <= 10_000_000:
                direct_prime_limit_checks += 1
                reported_limit = int(reported_match.group(1))
                if reported_limit != requested_limit:
                    direct_prime_limit_mismatches.append(
                        {
                            "path": rel,
                            "declared_input_limit": requested_limit,
                            "reported_output_limit": reported_limit,
                            "declared_success": declared_success,
                            "timestamp": record.get("timestamp"),
                            "output_sha256": output_digest,
                        }
                    )
        stored_length = ((record.get("tool") or {}).get("output_length"))
        if stored_length is None:
            missing_output_lengths.append(rel)
        elif output_text is not None and stored_length != len(output_text):
            length_mismatches.append(
                {
                    "path": rel,
                    "stored_character_length": stored_length,
                    "actual_character_length": len(output_text),
                }
            )

    duplicate_groups: list[dict[str, Any]] = []
    for digest, count in output_digests.most_common():
        if count <= 1:
            continue
        records = output_groups[digest]
        tool_names = sorted({item["tool_name"] for item in records})
        input_digests = sorted({item["declared_input_sha256"] for item in records})
        tool_input_pairs = sorted(
            {(item["tool_name"], item["declared_input_sha256"]) for item in records}
        )
        duplicate_groups.append(
            {
                "output_sha256": digest,
                "record_count": count,
                "unique_tool_names": tool_names,
                "unique_declared_input_sha256_count": len(input_digests),
                "unique_tool_input_pair_count": len(tool_input_pairs),
                "declared_success_true_count": sum(
                    item["declared_success"] is True for item in records
                ),
                "declared_success_false_count": sum(
                    item["declared_success"] is False for item in records
                ),
                "sample_record_paths": [item["path"] for item in records[:5]],
            }
        )
    heterogeneous_duplicate_groups = [
        group
        for group in duplicate_groups
        if group["unique_tool_input_pair_count"] > 1
    ]
    coverage = {
        "environment_object": sum("environment" in keys for keys in key_sets),
        "source_revision": count_key_coverage(key_sets, SOURCE_REVISION_KEYS),
        "source_file_digest": count_key_coverage(key_sets, SOURCE_DIGEST_KEYS),
        "input_digest": count_key_coverage(key_sets, INPUT_DIGEST_KEYS),
        "dependency_lock_digest": count_key_coverage(key_sets, DEPENDENCY_DIGEST_KEYS),
        "dependency_versions": count_key_coverage(key_sets, DEPENDENCY_VERSION_KEYS),
        "container_image_digest": count_key_coverage(key_sets, CONTAINER_DIGEST_KEYS),
        "random_seed": count_key_coverage(key_sets, SEED_KEYS),
        "authentication_material": count_key_coverage(key_sets, AUTHENTICATION_KEYS),
    }
    return {
        "record_family": "data/experiments/<experiment_id>/provenance.json + output.txt",
        "summary": {
            "provenance_records": len(paths),
            "parseable_object_records": len(key_sets),
            "output_files": output_files,
            "well_formed_stored_output_sha256": len(paths) - len(parse_failures) - len(malformed_digests),
            "stored_output_sha256_matches_current_bytes": exact_matches,
            "stored_output_sha256_mismatches": len(digest_failures),
            "authenticated_records": len(authenticated_records),
            "unique_current_output_sha256": len(output_digests),
            "duplicate_output_digest_groups": len(duplicate_groups),
            "records_in_duplicate_output_digest_groups": sum(item["record_count"] for item in duplicate_groups),
            "maximum_records_sharing_one_output_digest": max(output_digests.values(), default=0),
            "duplicate_output_groups_with_multiple_tool_input_pairs": len(
                heterogeneous_duplicate_groups
            ),
            "records_in_duplicate_groups_with_multiple_tool_input_pairs": sum(
                item["record_count"] for item in heterogeneous_duplicate_groups
            ),
            "records_with_test_fixture_or_tmp_like_id": len(test_like_records),
            "records_missing_declared_output_length": len(missing_output_lengths),
            "declared_success_counts": dict(sorted(success_values.items())),
            "declared_success_true_with_error_or_unusable_marker": len(
                success_true_with_error_marker
            ),
            "direct_numeric_prime_limit_checks": direct_prime_limit_checks,
            "direct_numeric_prime_limit_mismatches": len(direct_prime_limit_mismatches),
        },
        "coverage": coverage,
        "provenance_version_counts": dict(sorted(schema_versions.items())),
        "audited_inventory_sha256": inventory_sha256(inventory),
        "parse_failures": parse_failures,
        "missing_outputs": missing_outputs,
        "malformed_stored_output_digests": malformed_digests,
        "output_digest_failures": digest_failures,
        "experiment_id_mismatches": id_mismatches,
        "output_length_mismatches": length_mismatches,
        "records_missing_declared_output_length": missing_output_lengths,
        "records_with_test_fixture_or_tmp_like_id": test_like_records,
        "declared_success_true_with_error_or_unusable_marker": success_true_with_error_marker,
        "direct_numeric_prime_limit_mismatches": direct_prime_limit_mismatches,
        "authenticated_record_paths": authenticated_records,
        "largest_duplicate_output_groups": duplicate_groups[:25],
        "duplicate_output_groups_with_multiple_tool_input_pairs": heterogeneous_duplicate_groups,
        "interpretation_limits": [
            "A matching stored SHA-256 establishes current byte equality with the unauthenticated declaration; it does not establish who made the declaration.",
            "The record family does not by itself establish that declared inputs, environment fields, or tool identity are truthful.",
            "Duplicate output digests may be legitimate repeated computations and are not treated as fabrication evidence.",
        ],
    }


def flat_experiment_identifier(record: dict[str, Any]) -> str | None:
    if "code" not in record:
        return None
    payload = json.dumps(
        {"code": record.get("code"), "inputs": record.get("inputs") or {}},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def audit_flat_experiments(root: Path) -> dict[str, Any]:
    base = root / "data/experiments"
    paths = sorted(base.glob("*.json"))
    parse_failures: list[dict[str, str]] = []
    id_failures: list[dict[str, Any]] = []
    inventory: list[tuple[str, str]] = []
    key_sets: list[set[str]] = []
    executed_code_present = 0
    executed_code_differs = 0
    successful = 0
    result_file_count = 0
    for path in paths:
        rel = relative(path, root)
        file_digest = sha256(path)
        inventory.append((rel, file_digest))
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        if not isinstance(record, dict):
            parse_failures.append({"path": rel, "error": "top_level_not_object"})
            continue
        keys = recursive_keys(record)
        key_sets.append(keys)
        observed = str(record.get("experiment_id", ""))
        expected = flat_experiment_identifier(record)
        filename_id = path.stem
        if expected != observed or observed != filename_id or not HEX128_RE.fullmatch(observed):
            id_failures.append(
                {
                    "path": rel,
                    "filename_id": filename_id,
                    "record_id": observed,
                    "recomputed_code_inputs_id": expected,
                }
            )
        if "executed_code" in record:
            executed_code_present += 1
            if record.get("executed_code") != record.get("code"):
                executed_code_differs += 1
        successful += record.get("success") is True
        result_files = record.get("result_files")
        if isinstance(result_files, dict):
            result_file_count += len(result_files)

    coverage = {
        "source_revision": count_key_coverage(key_sets, SOURCE_REVISION_KEYS),
        "source_file_digest": count_key_coverage(key_sets, SOURCE_DIGEST_KEYS),
        "input_digest": count_key_coverage(key_sets, INPUT_DIGEST_KEYS),
        "output_digest": sum(bool(keys & {"output_hash", "output_sha256"}) for keys in key_sets),
        "dependency_lock_digest": count_key_coverage(key_sets, DEPENDENCY_DIGEST_KEYS),
        "dependency_versions": count_key_coverage(key_sets, DEPENDENCY_VERSION_KEYS),
        "environment": sum("environment" in keys for keys in key_sets),
        "container_image_digest": count_key_coverage(key_sets, CONTAINER_DIGEST_KEYS),
        "random_seed": count_key_coverage(key_sets, SEED_KEYS),
        "authentication_material": count_key_coverage(key_sets, AUTHENTICATION_KEYS),
    }
    return {
        "record_family": "data/experiments/<128-bit-code-input-id>.json",
        "identifier_definition": "first 32 hexadecimal characters of SHA-256(json.dumps({code, inputs}, sort_keys=True))",
        "identifier_binds": ["generated_code", "declared_inputs"],
        "identifier_does_not_bind": [
            "hypothesis",
            "language",
            "executed_or_repaired_code",
            "output",
            "dependencies",
            "execution_environment",
            "random_seed_unless_present_in_code_or_inputs",
        ],
        "summary": {
            "records": len(paths),
            "parseable_object_records": len(key_sets),
            "identifier_recomputation_matches": len(paths) - len(parse_failures) - len(id_failures),
            "identifier_failures": len(id_failures),
            "successful_records": successful,
            "records_with_executed_code": executed_code_present,
            "records_where_executed_code_differs": executed_code_differs,
            "embedded_result_files": result_file_count,
        },
        "coverage": coverage,
        "audited_inventory_sha256": inventory_sha256(inventory),
        "parse_failures": parse_failures,
        "identifier_failures": id_failures,
        "interpretation_limits": [
            "The truncated identifier is a content label for selected declared fields, not an authenticated signature.",
            "A matching identifier does not establish that the code ran or that stored outputs came from that code.",
        ],
    }


def walk_manifest_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for top in (root / "papers", root / "experiments"):
        if not top.is_dir():
            continue
        for directory, child_directories, files in os.walk(top, topdown=True):
            child_directories[:] = sorted(
                name
                for name in child_directories
                if name not in EXCLUDED_DIRECTORY_NAMES
                and not (
                    Path(directory).resolve() == (root / "experiments").resolve()
                    and name == "verifiable_release_study"
                )
            )
            if "manifest.json" in files:
                paths.append(Path(directory) / "manifest.json")
    return sorted(set(paths))


def paper_output_root(manifest_path: Path) -> Path:
    for parent in manifest_path.parents:
        if parent.name in {"paper", "papers"}:
            return parent
    return manifest_path.parent


def manifest_references(manifest: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for table in manifest.get("tables", []) if isinstance(manifest.get("tables"), list) else []:
        if isinstance(table, dict):
            for key in ("csv_path", "json_path"):
                if isinstance(table.get(key), str):
                    references.append(table[key])
    for figure in manifest.get("figures", []) if isinstance(manifest.get("figures"), list) else []:
        if isinstance(figure, dict) and isinstance(figure.get("path"), str):
            references.append(figure["path"])
    if isinstance(manifest.get("literature_audit_path"), str):
        references.append(manifest["literature_audit_path"])
    return references


def digest_metadata_count(value: Any) -> int:
    count = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"(?i)(?:sha(?:256|512)?|hash|digest|checksum|signature)", str(key)):
                count += 1
            count += digest_metadata_count(item)
    elif isinstance(value, list):
        count += sum(digest_metadata_count(item) for item in value)
    return count


def audit_publication_manifests(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    inventory: list[tuple[str, str]] = []
    parse_failures: list[dict[str, str]] = []
    for path in walk_manifest_paths(root):
        rel = relative(path, root)
        file_digest = sha256(path)
        inventory.append((rel, file_digest))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        if not isinstance(manifest, dict):
            parse_failures.append({"path": rel, "error": "top_level_not_object"})
            continue
        base = paper_output_root(path)
        references: list[dict[str, Any]] = []
        for declared in manifest_references(manifest):
            resolved = base / declared
            exists = resolved.is_file()
            actual = sha256(resolved) if exists else None
            if exists:
                inventory.append((relative(resolved, root), actual or ""))
            references.append(
                {
                    "declared_path": declared,
                    "resolved_path": relative(resolved, root),
                    "exists": exists,
                    "auditor_computed_sha256": actual,
                }
            )
        records.append(
            {
                "path": rel,
                "file_sha256": file_digest,
                "declared_digest_or_signature_field_count": digest_metadata_count(manifest),
                "references": references,
            }
        )
    all_references = [item for record in records for item in record["references"]]
    return {
        "summary": {
            "manifest_files": len(records) + len(parse_failures),
            "parseable_object_manifests": len(records),
            "manifests_with_any_declared_digest_or_signature_field": sum(
                record["declared_digest_or_signature_field_count"] > 0 for record in records
            ),
            "referenced_files": len(all_references),
            "referenced_files_present": sum(item["exists"] for item in all_references),
            "referenced_files_missing": sum(not item["exists"] for item in all_references),
        },
        "audited_inventory_sha256": inventory_sha256(inventory),
        "parse_failures": parse_failures,
        "manifests": records,
        "interpretation_limit": (
            "Auditor-computed digests inventory current bytes; because the manifests do not authenticate those digests, they are not release signatures or historical provenance."
        ),
    }


def checksum_manifests(root: Path) -> list[Path]:
    paths: list[Path] = []
    experiments = root / "experiments"
    if not experiments.is_dir():
        return paths
    for directory, child_directories, files in os.walk(experiments, topdown=True):
        child_directories[:] = sorted(
            name
            for name in child_directories
            if name not in EXCLUDED_DIRECTORY_NAMES
            and not (
                Path(directory).resolve() == experiments.resolve()
                and name == "verifiable_release_study"
            )
        )
        for name in sorted(files):
            if name == "MANIFEST.sha256":
                paths.append(Path(directory) / name)
    return sorted(paths)


def audit_checksum_manifests(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    inventory: list[tuple[str, str]] = []
    line_re = re.compile(r"^([0-9a-f]{64})  (.+)$")
    for path in checksum_manifests(root):
        rel = relative(path, root)
        manifest_digest = sha256(path)
        inventory.append((rel, manifest_digest))
        entries: list[dict[str, Any]] = []
        malformed_lines: list[int] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = line_re.fullmatch(line)
            if not match:
                malformed_lines.append(line_number)
                continue
            expected, declared = match.groups()
            candidate = path.parent / declared
            exists = candidate.is_file()
            actual = sha256(candidate) if exists else None
            if exists:
                inventory.append((relative(candidate, root), actual or ""))
            entries.append(
                {
                    "declared_path": declared,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                    "exists": exists,
                    "matches": actual == expected,
                }
            )
        records.append(
            {
                "path": rel,
                "file_sha256": manifest_digest,
                "malformed_line_numbers": malformed_lines,
                "entries": entries,
            }
        )
    entries = [item for record in records for item in record["entries"]]
    return {
        "summary": {
            "checksum_manifest_files": len(records),
            "entries": len(entries),
            "current_digest_matches": sum(item["matches"] for item in entries),
            "current_digest_failures": sum(not item["matches"] for item in entries),
            "signed_or_attested_manifest_files": 0,
        },
        "audited_inventory_sha256": inventory_sha256(inventory),
        "manifests": records,
        "interpretation_limit": (
            "A matching unsigned checksum manifest detects accidental change relative to its present declaration but does not authenticate an author, release identity, or publication time."
        ),
    }


def audit_paper_watermarks(root: Path) -> dict[str, Any]:
    paths = sorted((root / "papers").glob("*.md")) if (root / "papers").is_dir() else []
    marker = "\n\n---\n\n## Provenance Watermark\n"
    body_re = re.compile(r"(?m)^body_sha256: ([0-9a-f]{64})$")
    with_watermark = 0
    matching = 0
    mismatches: list[dict[str, Any]] = []
    inventory: list[tuple[str, str]] = []
    for path in paths:
        rel = relative(path, root)
        inventory.append((rel, sha256(path)))
        text = path.read_text(encoding="utf-8", errors="replace")
        if marker not in text:
            continue
        with_watermark += 1
        body, _ = text.split(marker, 1)
        match = body_re.search(text)
        expected = match.group(1) if match else None
        actual = sha256_bytes(body.encode("utf-8"))
        if expected == actual:
            matching += 1
        else:
            mismatches.append(
                {"path": rel, "stored_body_sha256": expected, "actual_body_sha256": actual}
            )
    return {
        "summary": {
            "top_level_markdown_papers": len(paths),
            "papers_with_watermark": with_watermark,
            "watermark_body_sha256_matches": matching,
            "watermark_body_sha256_failures": len(mismatches),
            "cryptographically_authenticated_watermarks": 0,
        },
        "audited_inventory_sha256": inventory_sha256(inventory),
        "mismatches": mismatches,
        "interpretation_limit": (
            "The watermark body digest is self-declared inside the same mutable manuscript and has no signature; a matching value is an internal consistency check, not author authentication."
        ),
    }


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file() or not (root / "amy.py").is_file():
        raise RuntimeError(f"A.M.Y package metadata or entry point not found below {root}")
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    tracked = set(git(root, "ls-files").splitlines())
    tracked_status = git(root, "status", "--porcelain=v1", "--untracked-files=no")
    project = pyproject.get("project") or {}
    scripts = project.get("scripts") or {}
    version_match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        (root / "amy.py").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    return {
        "schema_version": "amy.integrity-audit.v1",
        "classification": "exploratory_pre_registration_read_only",
        "safety": {
            "imports_amy": False,
            "executes_product_code": False,
            "runs_experiments": False,
            "uses_network": False,
            "deserializes_models": False,
            "reads_secret_values": False,
            "mutates_audited_artifacts": False,
        },
        "repository": {
            "git_commit": git(root, "rev-parse", "HEAD"),
            "git_object_format": git(root, "rev-parse", "--show-object-format"),
            "git_describe": git(root, "describe", "--tags", "--always", "--dirty"),
            "tracked_worktree_dirty": bool(tracked_status),
            "tracked_status_sha256": sha256_bytes(tracked_status.encode("utf-8")),
            "pyproject_sha256": sha256(pyproject_path),
            "declared_project_version": project.get("version"),
            "entry_module_version": version_match.group(1) if version_match else None,
            "console_entry_point": scripts.get("amy"),
        },
        "static_code": audit_static_code(root, tracked),
        "directory_provenance": audit_directory_provenance(root),
        "flat_experiments": audit_flat_experiments(root),
        "publication_manifests": audit_publication_manifests(root),
        "checksum_release_manifests": audit_checksum_manifests(root),
        "paper_watermarks": audit_paper_watermarks(root),
        "trust_boundary": {
            "current_byte_integrity": "recomputed by this read-only auditor where an expected digest exists",
            "authentication": "not established for A.M.Y provenance records, publication manifests, checksum manifests, or paper watermarks",
            "scientific_truth": "never inferred from a matching digest or signature",
            "historical_time": "not established by mutable local timestamps",
            "independent_reproduction": "not performed by this audit",
        },
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
