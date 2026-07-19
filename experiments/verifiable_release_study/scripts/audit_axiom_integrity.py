#!/usr/bin/env python3
"""Read-only AXIOM boundary, producer, and retained-artifact audit.

The scanner never imports or executes Atlas/AXIOM, contacts a service, loads a
model, or reads runtime secret values.  It binds findings to current source and
artifact bytes and keeps labels, integrity, authentication, and scientific
validity separate.  Output is deterministic for a fixed repository snapshot.
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
import warnings
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = STUDY_ROOT.parents[1]
EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "site-packages",
    "external_tools",
    "tests",
    "venv",
}

warnings.filterwarnings("ignore", category=SyntaxWarning)

SCIENTIFIC_ARTIFACT_EXCLUSIONS = {
    "atlas/artifacts/reports/AXIOM_APP_REORGANIZATION_FINAL_REPORT.json",
    "atlas/monitoring/grafana/dashboards/axiom-services.json",
    "atlas/monitoring/grafana/provisioning/dashboards/axiom-dashboard.json",
}

FIELD_GROUPS = {
    "authentication": {
        "attestation",
        "attestations",
        "certificate",
        "certificates",
        "dsse",
        "public_key_fingerprint",
        "signature",
        "signatures",
        "sigstore_bundle",
    },
    "content_digest": {
        "artifact_digest",
        "checksum",
        "content_hash",
        "digest",
        "file_hash",
        "hash",
        "sha256",
        "sha512",
    },
    "dependency_identity": {
        "dependencies",
        "dependency_lock",
        "dependency_versions",
        "lockfile",
        "packages",
        "pip_freeze",
        "requirements",
    },
    "environment_identity": {
        "container_digest",
        "environment",
        "environment_digest",
        "execution_image",
        "hardware",
        "operating_system",
        "platform",
    },
    "model_immutable_identity": {
        "model_commit",
        "model_digest",
        "model_revision",
        "model_sha256",
        "weights_digest",
    },
    "producer_identity": {
        "command",
        "producer",
        "producer_script",
        "script",
        "workflow_command",
    },
    "provenance": {
        "lineage",
        "provenance",
        "provenance_record",
    },
    "raw_exchange": {
        "raw_request",
        "raw_response",
        "request_bytes",
        "request_digest",
        "response_bytes",
        "response_digest",
    },
    "seed": {"random_seed", "rng_seed", "seed"},
    "source_revision": {
        "commit",
        "git_commit",
        "git_sha",
        "repository_commit",
        "source_revision",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_if_regular_file(path: Path) -> str | None:
    """Return a digest only for a present regular, non-symlink input."""
    if not path.is_file() or path.is_symlink():
        return None
    return sha256(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


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


def recursive_values(value: Any, key_name: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == key_name.lower():
                values.append(item)
            values.extend(recursive_values(item, key_name))
    elif isinstance(value, list):
        for item in value:
            values.extend(recursive_values(item, key_name))
    return values


def iter_json_nodes(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key in sorted(value):
            yield from iter_json_nodes(value[key], f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_json_nodes(item, f"{path}[{index}]")


def python_paths(atlas: Path) -> list[Path]:
    # The install/deployment boundary is root modules plus app*/scripts*; examples
    # are added because several retained AXIOM artifacts name them as producers.
    paths = sorted(atlas.glob("*.py"))
    for scope in (atlas / "app", atlas / "scripts", atlas / "examples"):
        if not scope.is_dir():
            continue
        for directory, children, files in os.walk(scope, topdown=True):
            children[:] = sorted(name for name in children if name not in EXCLUDED_DIRECTORIES)
            paths.extend(
                Path(directory) / name for name in sorted(files) if name.endswith(".py")
            )
    return sorted(paths)


def function_evidence(path: Path, function_name: str) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
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


def source_call_sites(path: Path) -> dict[str, list[dict[str, Any]]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    groups: dict[str, list[dict[str, Any]]] = {"network": [], "random": []}
    network = re.compile(
        r"^(?:requests|httpx|aiohttp|urllib\.request|self\.session)\."
        r"(?:get|post|request|urlopen)$|(?:^|\.)urlopen$"
    )
    random = re.compile(r"(?:^|\.)(?:random|rand|randn|randint|choice|shuffle)$")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func) or ""
        item = {
            "line": node.lineno,
            "call": name,
            "code": lines[node.lineno - 1].strip() if node.lineno <= len(lines) else "",
        }
        if network.search(name):
            groups["network"].append(item)
        if random.search(name):
            groups["random"].append(item)
    return {key: sorted(value, key=lambda item: item["line"]) for key, value in groups.items()}


def fastapi_metadata(path: Path) -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or (dotted_name(value.func) or "").split(".")[-1] != "FastAPI":
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [dotted_name(target) for target in targets]
        if "app" not in names:
            continue
        kwargs = {keyword.arg: literal(keyword.value) for keyword in value.keywords if keyword.arg}
        records.append(
            {
                "line": node.lineno,
                "title": kwargs.get("title"),
                "version": kwargs.get("version"),
                "description": kwargs.get("description"),
            }
        )
    return records


def syntax_status(path: Path) -> dict[str, Any]:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return {
            "parseable": False,
            "error": type(exc).__name__,
            "line": getattr(exc, "lineno", None),
            "offset": getattr(exc, "offset", None),
            "sha256": sha256(path),
        }
    return {"parseable": True, "sha256": sha256(path)}


def audit_project_boundary(root: Path, atlas: Path, tracked: set[str]) -> dict[str, Any]:
    pyproject_path = atlas / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get("project") or {}
    paths = python_paths(atlas)
    class_records: list[dict[str, Any]] = []
    axiom_route_literals: list[dict[str, Any]] = []
    parse_failures: list[dict[str, str]] = []
    for path in paths:
        rel = relative(path, root)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "axiom" in node.name.lower():
                class_records.append({"path": rel, "line": node.lineno, "class": node.name})
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.lower().startswith("/axiom"):
                    axiom_route_literals.append(
                        {"path": rel, "line": node.lineno, "value": node.value}
                    )

    root_main = atlas / "main.py"
    app_main = atlas / "app/main.py"
    dockerfile = atlas / "Dockerfile"
    compose = atlas / "config/docker-compose.yml"
    docker_text = dockerfile.read_text(encoding="utf-8")
    compose_text = compose.read_text(encoding="utf-8")
    docker_entry_match = re.search(r'"([A-Za-z0-9_.]+:app)"', docker_text)
    base_images = re.findall(r"(?m)^FROM\s+([^\s]+)", docker_text)
    compose_images = re.findall(r"(?m)^\s*image:\s*([^\s#]+)", compose_text)
    credential_names: list[str] = []
    for line in compose_text.splitlines():
        match = re.search(r"(?:^|[-\s])([A-Z0-9_]*(?:PASSWORD|SECRET_KEY|AUTH)[A-Z0-9_]*)=([^\s]+)", line)
        if match and not re.fullmatch(r"\$\{[^}]+\}", match.group(2)):
            credential_names.append(match.group(1))
        url_match = re.search(r"(?:^|[-\s])([A-Z0-9_]*URL)=([^\s]+)", line)
        if url_match and re.search(r"//[^/:\s]+:[^@\s]+@", url_match.group(2)):
            credential_names.append(url_match.group(1))

    root_evidence = {
        name: function_evidence(root_main, name)
        for name in ("lifespan", "health_check", "detailed_status", "get_metrics")
    }
    lifespan_source = str(root_evidence["lifespan"].get("source", ""))
    health_source = str(root_evidence["health_check"].get("source", ""))
    status_source = str(root_evidence["detailed_status"].get("source", ""))
    metrics_source = str(root_evidence["get_metrics"].get("source", ""))
    middleware_setup = atlas / "app/middleware/setup.py"
    middleware_status = syntax_status(middleware_setup)
    direct_import_blockers = []
    for entry_path in (root_main, app_main):
        entry_source = entry_path.read_text(encoding="utf-8")
        if "from app.middleware.setup import configure_security_middleware" in entry_source and not middleware_status["parseable"]:
            direct_import_blockers.append(
                {
                    "entry_module": relative(entry_path, root),
                    "imported_module": "app.middleware.setup",
                    "imported_path": relative(middleware_setup, root),
                    **middleware_status,
                }
            )

    source_hash_paths = [pyproject_path, root_main, app_main, dockerfile, compose]
    return {
        "package_metadata": {
            "name": project.get("name"),
            "version": project.get("version"),
            "development_status_classifiers": [
                item for item in project.get("classifiers", []) if str(item).startswith("Development Status")
            ],
            "console_entry_points": project.get("scripts") or {},
            "setuptools_package_include": ["app*", "scripts*"],
        },
        "independent_axiom_surface": {
            "top_level_axiom_python_package_exists": (atlas / "axiom").is_dir(),
            "console_entry_point_count": len(project.get("scripts") or {}),
            "route_string_literals_starting_with_axiom": axiom_route_literals,
            "axiom_named_classes": sorted(class_records, key=lambda item: (item["path"], item["line"])),
            "interpretation": (
                "Within the scanned source tree, AXIOM is a package/project and class/demo label over Atlas app code; no separate top-level axiom package, console entry point, or /axiom route literal was found."
            ),
        },
        "python_scan": {
            "files": len(paths),
            "scope": ["atlas/*.py", "atlas/app/**/*.py", "atlas/scripts/**/*.py", "atlas/examples/**/*.py"],
            "parse_failures": parse_failures,
            "imports_or_executes_atlas": False,
        },
        "fastapi_apps": {
            relative(root_main, root): fastapi_metadata(root_main),
            relative(app_main, root): fastapi_metadata(app_main),
        },
        "deployment": {
            "docker_entry_point": docker_entry_match.group(1) if docker_entry_match else None,
            "docker_base_images": base_images,
            "docker_base_images_pinned_by_digest": sum("@sha256:" in image for image in base_images),
            "compose_images": compose_images,
            "compose_images_pinned_by_digest": sum("@sha256:" in image for image in compose_images),
            "compose_explicit_latest_images": [image for image in compose_images if image.endswith(":latest")],
            "hardcoded_credential_like_variable_names": sorted(set(credential_names)),
            "credential_values_recorded": False,
            "compose_declared_context": ".",
            "compose_declared_dockerfile": "Dockerfile",
            "compose_file_relative_dockerfile_exists": (compose.parent / "Dockerfile").is_file(),
            "direct_import_syntax_blockers": direct_import_blockers,
            "docker_entry_point_has_direct_syntax_blocker": any(
                item["entry_module"] == "atlas/main.py" for item in direct_import_blockers
            ),
        },
        "source_facts": {
            "startup_catches_general_exception_and_continues": (
                "except Exception as e:" in lifespan_source and "Continuar sin servicios" in lifespan_source
            ),
            "root_health_returns_literal_healthy": '"status": "healthy"' in health_source,
            "root_health_reports_amy_2_0_0": (
                '"service": "A.M.Y"' in health_source and '"version": "2.0.0"' in health_source
            ),
            "root_status_hardcodes_modules_active": status_source.count('"active"') >= 4,
            "root_status_uses_estimated_performance_strings": status_source.count("estimated") >= 3,
            "root_metrics_contains_unmeasured_improvement_ranges": (
                "60-80%" in metrics_source and "40-60%" in metrics_source and "2-3x faster" in metrics_source
            ),
        },
        "function_evidence": root_evidence,
        "source_sha256": {relative(path, root): sha256(path) for path in source_hash_paths},
        "tracked_source_files": sum(relative(path, root) in tracked for path in source_hash_paths),
    }


def classify_axiom_json(rel: str) -> str:
    if rel in SCIENTIFIC_ARTIFACT_EXCLUSIONS:
        if "/monitoring/" in rel:
            return "monitoring_configuration"
        return "administrative_report"
    if rel.endswith("axiom_complete_analysis_summary.json"):
        return "capability_claim_summary"
    return "scientific_or_demo_output"


def producer_paths(rel: str) -> list[str]:
    name = Path(rel).name
    mapping: list[tuple[re.Pattern[str], list[str]]] = [
        (re.compile(r"^axiom_autonomous_research_report_hf\.json$"), ["atlas/scripts/test_axiom_autonomous_hf.py"]),
        (re.compile(r"^axiom_meta_41_demo_results_\d+\.json$"), ["atlas/scripts/experiments/demo_advanced_ai_integration.py"]),
        (re.compile(r"^axiom_real_data_comprehensive_demo\.json$"), ["atlas/scripts/experiments/axiom_real_data_demo.py"]),
        (re.compile(r"^AXIOM_APP_REORGANIZATION_FINAL_REPORT\.json$"), ["atlas/scripts/utils/generate_final_report.py"]),
        (re.compile(r"^axiom_scientific_demo_results\.json$"), ["atlas/examples/scientific_demo.py"]),
        (re.compile(r"^axiom_demo_report_\d{8}_\d{6}\.json$"), ["atlas/examples/axiom_real_data_comprehensive_demo.py"]),
        (re.compile(r"^axiom_real_data_report_\d{8}_\d{6}\.json$"), ["atlas/examples/axiom_complete_real_data_demo.py", "atlas/examples/real_astronomical_data_demo.py"]),
        (re.compile(r"^axiom_scientific_workflow_\d{8}_\d{6}\.json$"), ["atlas/examples/axiom_scientific_workflow_example.py", "atlas/examples/real_astronomical_data_demo.py"]),
    ]
    for pattern, producers in mapping:
        if pattern.match(name):
            return producers
    return []


def axiom_json_paths(atlas: Path) -> list[Path]:
    paths: list[Path] = []
    for directory, children, files in os.walk(atlas, topdown=True):
        children[:] = sorted(name for name in children if name not in EXCLUDED_DIRECTORIES)
        for name in sorted(files):
            if name.lower().endswith(".json") and "axiom" in name.lower():
                paths.append(Path(directory) / name)
    return sorted(paths)


def artifact_field_coverage(keys: set[str]) -> dict[str, list[str]]:
    return {
        group: sorted(keys & names)
        for group, names in FIELD_GROUPS.items()
    }


def literal_source_records(path: Path) -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    records: list[dict[str, Any]] = []
    for parent in ast.walk(tree):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            candidate: Any = None
            name: str | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                candidate = literal(node.value)
            elif isinstance(node, ast.Return):
                name = f"$return:{parent.name}"
                candidate = literal(node.value) if node.value else None
            if not isinstance(candidate, (dict, list)):
                continue
            encoded = canonical_json(candidate)
            if len(encoded) < 80:
                continue
            records.append(
                {
                    "function": parent.name,
                    "variable": name,
                    "line": node.lineno,
                    "canonical_bytes": len(encoded),
                    "canonical_sha256": sha256_bytes(encoded),
                }
            )
    unique: dict[tuple[str, int, str], dict[str, Any]] = {}
    for record in records:
        key = (record["function"], record["line"], record["canonical_sha256"])
        unique[key] = record
    return sorted(unique.values(), key=lambda item: (item["line"], item["function"]))


def match_json_to_source_literals(value: Any, source_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for record in source_records:
        by_hash.setdefault(record["canonical_sha256"], []).append(record)
    matches: list[dict[str, Any]] = []
    for json_path, node in iter_json_nodes(value):
        if not isinstance(node, (dict, list)):
            continue
        encoded = canonical_json(node)
        if len(encoded) < 80:
            continue
        digest = sha256_bytes(encoded)
        for source in by_hash.get(digest, []):
            matches.append(
                {
                    "json_path": json_path,
                    "source_function": source["function"],
                    "source_variable": source["variable"],
                    "source_line": source["line"],
                    "canonical_bytes": len(encoded),
                    "canonical_sha256": digest,
                }
            )
    return sorted(matches, key=lambda item: (item["json_path"], item["source_line"]))


def audit_axiom_json(root: Path, atlas: Path, tracked: set[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    parse_failures: list[dict[str, str]] = []
    inventory: list[tuple[str, str]] = []
    parsed: dict[str, Any] = {}
    for path in axiom_json_paths(atlas):
        rel = relative(path, root)
        digest = sha256(path)
        inventory.append((rel, digest))
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_failures.append({"path": rel, "error": type(exc).__name__})
            continue
        parsed[rel] = value
        keys = recursive_keys(value)
        producers = producer_paths(rel)
        records.append(
            {
                "path": rel,
                "classification": classify_axiom_json(rel),
                "bytes": path.stat().st_size,
                "sha256": digest,
                "git_tracked": rel in tracked,
                "git_ignored": git_ignored(root, path),
                "top_level_type": type(value).__name__,
                "top_level_keys": sorted(value) if isinstance(value, dict) else [],
                "field_coverage": artifact_field_coverage(keys),
                "producer_paths": producers,
                "producer_sha256": {
                    producer: sha256(root / producer)
                    for producer in producers
                    if (root / producer).is_file()
                },
            }
        )

    scientific = [
        record
        for record in records
        if record["classification"] not in {"monitoring_configuration", "administrative_report"}
    ]
    summary = {
        "axiom_named_json_files": len(records) + len(parse_failures),
        "parseable_json_files": len(records),
        "scientific_or_claim_artifacts": len(scientific),
        "git_tracked_artifacts": sum(record["git_tracked"] for record in records),
        "git_ignored_artifacts": sum(record["git_ignored"] for record in records),
        "scientific_artifacts_with_content_digest_fields": sum(
            bool(record["field_coverage"]["content_digest"]) for record in scientific
        ),
        "scientific_artifacts_with_authentication_fields": sum(
            bool(record["field_coverage"]["authentication"]) for record in scientific
        ),
        "scientific_artifacts_with_provenance_fields": sum(
            bool(record["field_coverage"]["provenance"]) for record in scientific
        ),
        "scientific_artifacts_with_source_revision_fields": sum(
            bool(record["field_coverage"]["source_revision"]) for record in scientific
        ),
        "scientific_artifacts_with_seed_fields": sum(
            bool(record["field_coverage"]["seed"]) for record in scientific
        ),
        "scientific_artifacts_with_dependency_identity_fields": sum(
            bool(record["field_coverage"]["dependency_identity"]) for record in scientific
        ),
        "scientific_artifacts_with_model_immutable_identity_fields": sum(
            bool(record["field_coverage"]["model_immutable_identity"]) for record in scientific
        ),
        "scientific_artifacts_with_raw_exchange_fields": sum(
            bool(record["field_coverage"]["raw_exchange"]) for record in scientific
        ),
        "artifacts_without_identified_producer": sum(not record["producer_paths"] for record in records),
    }
    return {
        "summary": summary,
        "audited_inventory_sha256": inventory_sha256(inventory),
        "parse_failures": parse_failures,
        "artifacts": records,
        "parsed": parsed,
        "interpretation_limit": (
            "A source-like key, timestamp, model alias, or matching current byte digest would not by itself authenticate origin, establish historical time, or validate a scientific claim."
        ),
    }


def audit_critical_claims(root: Path, json_audit: dict[str, Any]) -> dict[str, Any]:
    parsed = json_audit["parsed"]

    complete_rel = "atlas/artifacts/demos/axiom_complete_demo_20250921_213324.json"
    complete = parsed.get(complete_rel, {})
    final = complete.get("final_assessment", {}) if isinstance(complete, dict) else {}
    upstream = {
        "hypothesis_generated": bool((complete.get("hypothesis") or {}).get("success")),
        "research_cycle_completed": bool((complete.get("research_cycle") or {}).get("success")),
        "tools_corroborated": bool((complete.get("corroboration") or {}).get("success")),
    }
    contradictions = [
        {
            "claim": key,
            "upstream_success": upstream[key],
            "final_assessment": final.get(key),
        }
        for key in upstream
        if upstream[key] is False and final.get(key) is True
    ]

    empty_positive: list[dict[str, Any]] = []
    for rel, value in sorted(parsed.items()):
        if not re.search(r"/axiom_demo_report_\d{8}_\d{6}\.json$", rel):
            continue
        metrics = value.get("technical_metrics") or {}
        findings = value.get("scientific_findings") or []
        positive = [item for item in findings if re.search(r"(?i)exitosa|confirmaci[oó]n|tiempo real", str(item))]
        if value.get("objects_analyzed") == 0 and metrics.get("total_queries") == 0 and positive:
            empty_positive.append(
                {
                    "path": rel,
                    "objects_analyzed": 0,
                    "total_queries": 0,
                    "successful_connections": metrics.get("successful_connections"),
                    "positive_findings": positive,
                }
            )

    literal_rel = "atlas/artifacts/demos/axiom_real_data_comprehensive_demo.json"
    literal_demo = parsed.get(literal_rel, {})
    literal_source_path = root / "atlas/scripts/experiments/axiom_real_data_demo.py"
    source_literals = literal_source_records(literal_source_path)
    literal_matches = match_json_to_source_literals(literal_demo, source_literals)
    literal_calls = source_call_sites(literal_source_path)

    real_report_rel = "atlas/reports/axiom_real_data_report_20250925_010355.json"
    real_report = parsed.get(real_report_rel, {})
    workflow_rel = "atlas/reports/axiom_scientific_workflow_20250925_010548.json"
    workflow = parsed.get(workflow_rel, {})
    connector = root / "atlas/examples/real_astronomical_data_demo.py"
    connector_methods = {
        "get_nasa_apod": "network_response",
        "get_iss_position": "network_response_plus_embedded_orbital_constants",
        "get_people_in_space": "network_response",
        "get_solar_system_data": "source_embedded_literal_catalog",
        "get_bright_stars_data": "source_embedded_literal_catalog",
        "get_exoplanet_data": "source_embedded_literal_catalog",
        "get_messier_objects": "source_embedded_literal_catalog",
    }
    connector_evidence = {
        name: {"classification": classification, **function_evidence(connector, name)}
        for name, classification in connector_methods.items()
    }
    real_report_producer = root / "atlas/examples/axiom_complete_real_data_demo.py"
    real_report_function = function_evidence(real_report_producer, "generate_comprehensive_report")
    real_report_function_source = str(real_report_function.get("source", ""))

    autonomous_rel = "atlas/archive/json_results/axiom_autonomous_research_report_hf.json"
    autonomous = parsed.get(autonomous_rel, {})
    history = autonomous.get("workflow_history") or [] if isinstance(autonomous, dict) else []
    history_keys = recursive_keys(history)
    autonomous_model_aliases = sorted(
        {str(item.get("model")) for item in history if isinstance(item, dict) and item.get("model")}
    )

    capability_rel = "atlas/artifacts/reports/axiom_complete_analysis_summary.json"
    capability = parsed.get(capability_rel, {})
    scientific_demo_rel = "atlas/data/results/axiom_scientific_demo_results.json"
    scientific_demo = parsed.get(scientific_demo_rel, {})
    result_groups = ["chemistry", "quantum_physics", "quantum_computing", "scientific_ai"]

    return {
        "failed_upstream_but_final_true": {
            "artifact": complete_rel,
            "artifact_sha256": sha256_if_regular_file(root / complete_rel),
            "contradiction_count": len(contradictions),
            "contradictions": contradictions,
            "dft_validation_is_not_linked_to_an_executable_record": not bool(
                recursive_keys(complete) & FIELD_GROUPS["provenance"]
            ),
            "named_peer_reviewers_are_unauthenticated_strings": bool(
                (complete.get("peer_review") or {}).get("reviewers")
            ) and not bool(recursive_keys(complete) & FIELD_GROUPS["authentication"]),
        },
        "zero_data_positive_reports": {
            "count": len(empty_positive),
            "reports": empty_positive,
        },
        "literal_multidomain_real_data_demo": {
            "artifact": literal_rel,
            "producer": relative(literal_source_path, root),
            "producer_sha256": sha256(literal_source_path),
            "producer_network_call_count": len(literal_calls["network"]),
            "producer_random_call_count": len(literal_calls["random"]),
            "source_literal_subtree_match_count": len(literal_matches),
            "source_literal_subtree_matches": literal_matches,
            "real_data_examples_exactly_equal_source_return_literal": any(
                match["json_path"] == "$.real_data_examples"
                and match["source_variable"] == "$return:load_real_data_examples"
                for match in literal_matches
            ),
            "peer_review_explicitly_labeled_simulation_in_source": (
                "# Peer review simulation" in literal_source_path.read_text(encoding="utf-8")
            ),
            "interpretation": (
                "This establishes source-embedded demo data and simulated outputs, not fabrication of external experiments; the artifact must not be cited as measured evidence."
            ),
        },
        "astronomy_real_data_report": {
            "artifact": real_report_rel,
            "artifact_sha256": sha256_if_regular_file(root / real_report_rel),
            "declared_data_source_count": len(real_report.get("data_sources") or []),
            "network_backed_connector_methods": sum(
                classification.startswith("network_response") for classification in connector_methods.values()
            ),
            "source_embedded_catalog_methods": sum(
                classification == "source_embedded_literal_catalog" for classification in connector_methods.values()
            ),
            "analysis_results_empty": real_report.get("analysis_results") == {},
            "real_data_verification_value": real_report.get("real_data_verification"),
            "producer_sets_real_data_verification_unconditionally_true": (
                "'real_data_verification': True" in real_report_function_source
            ),
            "report_contains_raw_api_responses": bool(
                recursive_keys(real_report) & FIELD_GROUPS["raw_exchange"]
            ),
            "report_contains_content_digests": bool(
                recursive_keys(real_report) & FIELD_GROUPS["content_digest"]
            ),
            "producer_function_evidence": real_report_function,
            "connector_method_evidence": connector_evidence,
        },
        "astronomy_scientific_workflow": {
            "artifact": workflow_rel,
            "artifact_sha256": sha256_if_regular_file(root / workflow_rel),
            "declared_data_sources": (workflow.get("data_sources") or {}).get("real_time_data", []),
            "total_objects": (workflow.get("data_sources") or {}).get("total_objects"),
            "habitability_statistics": (
                ((workflow.get("analysis_results") or {}).get("habitability_analysis") or {}).get("statistics")
            ),
            "habitability_is_descriptive_for_embedded_four_planet_sample": (
                ((((workflow.get("analysis_results") or {}).get("habitability_analysis") or {}).get("statistics") or {}).get("total_planets") == 4)
            ),
            "content_digest_fields": sorted(
                recursive_keys(workflow) & FIELD_GROUPS["content_digest"]
            ),
            "source_revision_fields": sorted(
                recursive_keys(workflow) & FIELD_GROUPS["source_revision"]
            ),
        },
        "autonomous_hf_report": {
            "artifact": autonomous_rel,
            "artifact_sha256": sha256_if_regular_file(root / autonomous_rel),
            "workflow_steps": len(history),
            "provider_labels": sorted(
                {str(item.get("provider")) for item in history if isinstance(item, dict)}
            ),
            "model_aliases": autonomous_model_aliases,
            "history_records_prompt_and_response_lengths_only": (
                {"prompt_length", "response_length"}.issubset(history_keys)
                and not bool(history_keys & FIELD_GROUPS["raw_exchange"])
            ),
            "immutable_model_identity_fields": sorted(
                recursive_keys(autonomous) & FIELD_GROUPS["model_immutable_identity"]
            ),
            "source_revision_fields": sorted(
                recursive_keys(autonomous) & FIELD_GROUPS["source_revision"]
            ),
            "seed_fields": sorted(recursive_keys(autonomous) & FIELD_GROUPS["seed"]),
            "authentication_fields": sorted(
                recursive_keys(autonomous) & FIELD_GROUPS["authentication"]
            ),
            "interpretation": (
                "Provider/model labels and generated text are inspectable, but aliases without endpoint/revision/digest and full exchange metadata do not permit immutable model attribution or bitwise replay."
            ),
        },
        "scientific_http_demo": {
            "artifact": scientific_demo_rel,
            "artifact_sha256": sha256_if_regular_file(root / scientific_demo_rel),
            "nonempty_result_groups": {
                group: len(scientific_demo.get(group) or {}) for group in result_groups
            },
            "successful_result_flags": sum(value is True for value in recursive_values(scientific_demo, "success")),
            "failed_result_flags": sum(value is False for value in recursive_values(scientific_demo, "success")),
            "content_digest_fields": sorted(
                recursive_keys(scientific_demo) & FIELD_GROUPS["content_digest"]
            ),
            "authentication_fields": sorted(
                recursive_keys(scientific_demo) & FIELD_GROUPS["authentication"]
            ),
        },
        "capability_claim_summary": {
            "artifact": capability_rel,
            "artifact_sha256": sha256_if_regular_file(root / capability_rel),
            "final_verdict": capability.get("final_verdict"),
            "scientific_impact_claims": capability.get("scientific_impact"),
            "identified_producer": bool(producer_paths(capability_rel)),
            "content_digest_fields": sorted(
                recursive_keys(capability) & FIELD_GROUPS["content_digest"]
            ),
            "provenance_fields": sorted(
                recursive_keys(capability) & FIELD_GROUPS["provenance"]
            ),
        },
    }


def build_audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    atlas = root / "atlas"
    if not (atlas / "pyproject.toml").is_file() or not (atlas / "app").is_dir():
        raise RuntimeError(f"Atlas package tree not found below {root}")
    tracked = set(git(root, "ls-files").splitlines())
    tracked_status = git(root, "status", "--porcelain=v1", "--untracked-files=no")
    project_boundary = audit_project_boundary(root, atlas, tracked)
    json_audit = audit_axiom_json(root, atlas, tracked)
    parsed = json_audit.pop("parsed")
    json_for_claims = {**json_audit, "parsed": parsed}
    critical_claims = audit_critical_claims(root, json_for_claims)
    return {
        "schema_version": "axiom.integrity-audit.v1",
        "classification": "exploratory_pre_registration_read_only",
        "safety": {
            "imports_atlas_or_axiom": False,
            "executes_product_code": False,
            "runs_demos_or_experiments": False,
            "uses_network": False,
            "loads_models": False,
            "reads_runtime_secret_values": False,
            "records_credential_values": False,
            "mutates_audited_artifacts": False,
        },
        "repository": {
            "git_commit": git(root, "rev-parse", "HEAD"),
            "git_object_format": git(root, "rev-parse", "--show-object-format"),
            "git_describe": git(root, "describe", "--tags", "--always", "--dirty"),
            "tracked_worktree_dirty": bool(tracked_status),
            "tracked_status_sha256": sha256_bytes(tracked_status.encode("utf-8")),
        },
        "project_boundary": project_boundary,
        "axiom_named_json_artifacts": json_audit,
        "critical_claim_checks": critical_claims,
        "trust_boundary": {
            "project_identity": "derived from current package, entry-point, route, deployment, and source bytes",
            "current_byte_integrity": "auditor-computed SHA-256 inventories current bytes only",
            "authentication": "not established for the retained AXIOM scientific or claim artifacts",
            "historical_time": "not established by mutable local timestamps",
            "scientific_truth": "never inferred from labels, successful HTTP status, digests, signatures, or generated prose",
            "independent_peer_review": "not established by simulated or unauthenticated reviewer-name strings",
            "independent_reproduction": "not performed by this audit",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_audit(args.repository_root)
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
