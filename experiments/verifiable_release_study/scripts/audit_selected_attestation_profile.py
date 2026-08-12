#!/usr/bin/env python3
"""Deterministic static audit of the selected production attestation profile.

This scanner reads the study contract, implementation, tests, and retained
production-smoke records. It does not invoke GitHub CLI, verify a signature,
contact a network service, execute a workflow, or inspect confirmatory results.
Its claims are therefore bounded to present bytes and explicit code structure.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = STUDY_ROOT.parents[1]
SELECTED_PROFILE = "standard_provenance_plus_authenticated_manifest_metadata"
SOURCE_SNAPSHOT_FORMAT = "application/x-tar"
SOURCE_SNAPSHOT_ASSURANCE = "exact-opaque-bytes-no-git-tree-equivalence-claim"
HISTORICAL_V1_SHA256 = {
    "schemas/github-production-verification-result.schema.json": (
        "64eef1a87da45dff355047963ebe762dfced1a2ba7e60be9a87dfcc28a1e2c18"
    ),
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json": (
        "68ea605c25a8e73ebe955a1bfd3977a309f13b40b9a112aee6b2e9bc5cd38c26"
    ),
    "production_pilot_runs/github_cli_2.96.0_upstream_smoke/result.json": (
        "444615e874774a01679e55098885a5e790d78a70a8f5fa0cc39caab28e545baa"
    ),
    "scripts/verify_github_attestation.py": (
        "9fbfa1ff99f8e5308cae741acfa6a5c683b0c36adaa68bfe930dee61ee49993b"
    ),
    "amy_verifier/github_attestation.py": (
        "6731d83c0ea94d0ce2029ce529a175c3eb9cd1d17e9698b090f47a72044fe6ac"
    ),
}

CONTRACT_PATHS = (
    "protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json",
    # Historical v1 bytes remain inputs to the retained smoke and invariants.
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json",
    "schemas/github-production-verification-result.schema.json",
    "amy_verifier/github_attestation.py",
    "scripts/verify_github_attestation.py",
    # Current pre-registration production contract is the non-destructive v2 line.
    "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json",
    "schemas/github-attestation-policy-v2.schema.json",
    "schemas/github-production-verification-result-v2.schema.json",
    "amy_verifier/github_attestation_v2.py",
    "amy_verifier/github_attestation_v2_core.py",
    "scripts/verify_github_attestation_v2.py",
    "protocol/PRODUCTION_REASON_CODES_DRAFT.json",
    "protocol/REASON_CODES.json",
    "protocol/REGISTRATION_GATES.json",
    "schemas/manifest-production-v0.2.schema.json",
    "amy_verifier/manifest.py",
    "amy_verifier/path_policy.py",
    "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
    "schemas/selected-profile-fixture-result.schema.json",
    "schemas/selected-profile-oracle.schema.json",
    "schemas/selected-profile-development-check.schema.json",
    "schemas/base-aware-mutation-development-check.schema.json",
    "amy_verifier/selected_profile_fixture.py",
    "amy_verifier/selected_profile_mutations.py",
    "amy_verifier/selected_profile_oracle.py",
    "amy_verifier/selected_profile_evaluator.py",
    "scripts/build_selected_profile_catalog.py",
    "scripts/validate_selected_profile_catalog.py",
    "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json",
    "protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json",
    "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json",
    "protocol/SELECTED_PROFILE_ORACLE_VALIDATION.json",
    "scripts/build_selected_profile_oracle.py",
    "scripts/validate_selected_profile_oracle.py",
    "scripts/run_selected_profile_development_checks.py",
    "scripts/validate_selected_profile_development_check.py",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-13.json",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_2026-07-13.json",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_2026-07-15.json",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_2026-07-15.json",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_V2_2026-07-15T034921Z.json",
    "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_V2_2026-07-15T034921Z.json",
    "scripts/run_base_aware_mutation_development_check.py",
    "scripts/validate_base_aware_mutation_development_check.py",
    "development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-13.json",
    "development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_2026-07-13.json",
    "development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-15.json",
    "development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_2026-07-15.json",
    "development_checks/BASE_AWARE_MUTATION_PLANS_V2_2026-07-15T034921Z.json",
    "development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_V2_2026-07-15T034921Z.json",
    "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json",
    "scripts/build_selected_profile_bases.py",
    "scripts/validate_selected_profile_base_run.py",
    "scripts/compare_selected_profile_base_runs.py",
    "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/summary.json",
    "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/validation.json",
    "selected_profile_base_runs/SELECTED_RUN_COMPARISON_2026-07-13.json",
    "selected_profile_base_runs/R0_SELECTED_BASES_CURRENT_REPLAY_2026-07-13.json",
    "scripts/build_selected_profile_compatibility_matrix.py",
    "scripts/validate_selected_profile_compatibility_matrix.py",
    "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json",
    "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json",
    "tests/test_attestation_profile_decision.py",
    "tests/test_github_attestation_adapter.py",
    "tests/test_github_attestation_v2.py",
    "tests/test_selected_profile_fixture.py",
    "tests/test_selected_profile_base_run.py",
    "tests/test_selected_profile_catalog.py",
    "tests/test_selected_profile_full_generator_oracle.py",
    "tests/test_selected_profile_development_record.py",
    "tests/test_selected_profile_base_aware_mutations.py",
    "tests/test_base_aware_mutation_development_record.py",
    "tests/test_selected_profile_compatibility_matrix.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_json(relative: str) -> Any:
    return json.loads((STUDY_ROOT / relative).read_text(encoding="utf-8"))


def walk_strings(value: Any, location: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from walk_strings(value[key], f"{location}.{key}")


def object_schemas_without_additional_properties(
    value: Any, location: str = "$"
) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if value.get("type") == "object" and "additionalProperties" not in value:
            found.append(location)
        for key, item in value.items():
            found.extend(
                object_schemas_without_additional_properties(item, f"{location}.{key}")
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(
                object_schemas_without_additional_properties(item, f"{location}[{index}]")
            )
    return found


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise ValueError(f"function not found: {name}")


def function_calls(node: ast.AST) -> list[str]:
    return sorted(
        {
            name
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            if (name := dotted_name(call.func)) is not None
        }
    )


def dotted_references(node: ast.AST) -> list[str]:
    return sorted(
        {
            name
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute)
            if (name := dotted_name(child)) is not None
        }
    )


def function_call_count(node: ast.AST, name: str) -> int:
    return sum(
        1
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and dotted_name(call.func) == name
    )


def call_keyword_names(node: ast.AST, name: str) -> set[str]:
    found: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and dotted_name(call.func) == name:
            found.update(keyword.arg for keyword in call.keywords if keyword.arg is not None)
    return found


def function_string_literals(node: ast.AST) -> list[str]:
    return sorted(
        {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
    )


def rejection_codes(tree: ast.Module) -> list[str]:
    codes: set[str] = set()
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or dotted_name(call.func) != "GitHubGateRejected":
            continue
        if call.args and isinstance(call.args[0], ast.Constant):
            value = call.args[0].value
            if isinstance(value, str):
                codes.add(value)
    return sorted(codes)


def test_functions(tree: ast.Module) -> list[str]:
    return sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def p1_check_keys(node: ast.FunctionDef) -> list[str]:
    for assignment in ast.walk(node):
        if not isinstance(assignment, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "checks" for target in assignment.targets):
            continue
        if not isinstance(assignment.value, ast.Dict):
            continue
        keys = [key.value for key in assignment.value.keys if isinstance(key, ast.Constant)]
        if keys and all(isinstance(key, str) for key in keys):
            return sorted(keys)
    return []


def source_snapshot_references() -> list[str]:
    references: list[str] = []
    included_suffixes = {".json", ".md", ".py"}
    excluded_parts = {".git", ".pytest_cache", ".venv", "__pycache__", "audit"}
    for path in sorted(STUDY_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in included_suffixes:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if SOURCE_SNAPSHOT_ASSURANCE in text:
            references.append(path.relative_to(STUDY_ROOT).as_posix())
    return references


def retained_production_results(policy: dict[str, Any]) -> list[dict[str, Any]]:
    repository_uri = (policy.get("identity") or {}).get("repository_uri")
    records: list[dict[str, Any]] = []
    for path in sorted((STUDY_ROOT / "production_pilot_runs").glob("**/result.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            records.append(
                {
                    "path": path.relative_to(STUDY_ROOT).as_posix(),
                    "sha256": sha256(path),
                    "parse_error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        certificate = value.get("certificate") if isinstance(value, dict) else None
        observed_repository = (
            certificate.get("sourceRepositoryURI") if isinstance(certificate, dict) else None
        )
        records.append(
            {
                "path": path.relative_to(STUDY_ROOT).as_posix(),
                "sha256": sha256(path),
                "decision": value.get("decision") if isinstance(value, dict) else None,
                "profile_id": value.get("profile_id") if isinstance(value, dict) else None,
                "source_repository_uri": observed_repository,
                "is_selected_repository_p3": bool(
                    isinstance(value, dict)
                    and value.get("profile_id") == "P3"
                    and observed_repository == repository_uri
                ),
            }
        )
    return records


def build_audit() -> dict[str, Any]:
    decision = load_json("protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json")
    historical_policy = load_json("protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json")
    policy = load_json("protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json")
    reasons = load_json("protocol/REASON_CODES.json")
    production_reasons = load_json("protocol/PRODUCTION_REASON_CODES_DRAFT.json")
    gates = load_json("protocol/REGISTRATION_GATES.json")
    selected_overlay = load_json("protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json")
    selected_catalog_validation = load_json(
        "protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json"
    )
    selected_oracle_validation = load_json(
        "protocol/SELECTED_PROFILE_ORACLE_VALIDATION.json"
    )
    selected_development_validation = load_json(
        "development_checks/SELECTED_PROFILE_FULL_GENERATOR_ORACLE_VALIDATION_V2_2026-07-15T034921Z.json"
    )
    base_aware_record = load_json(
        "development_checks/BASE_AWARE_MUTATION_PLANS_2026-07-13.json"
    )
    base_aware_validation = load_json(
        "development_checks/BASE_AWARE_MUTATION_PLANS_VALIDATION_V2_2026-07-15T034921Z.json"
    )
    selected_base_validation = load_json(
        "selected_profile_base_runs/r0_selected_bases_20260713T101851Z/validation.json"
    )
    selected_base_comparison = load_json(
        "selected_profile_base_runs/SELECTED_RUN_COMPARISON_2026-07-13.json"
    )
    selected_base_current_replay = load_json(
        "selected_profile_base_runs/R0_SELECTED_BASES_CURRENT_REPLAY_2026-07-13.json"
    )
    selected_compatibility_validation = load_json(
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json"
    )
    schema_path = STUDY_ROOT / "schemas/manifest-production-v0.2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    policy_schema_path = STUDY_ROOT / "schemas/github-attestation-policy-v2.schema.json"
    policy_schema = json.loads(policy_schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(policy_schema)
    result_schema_path = (
        STUDY_ROOT / "schemas/github-production-verification-result-v2.schema.json"
    )
    result_schema = json.loads(result_schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(result_schema)
    historical_result_schema_path = (
        STUDY_ROOT / "schemas/github-production-verification-result.schema.json"
    )
    historical_result_schema = json.loads(
        historical_result_schema_path.read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(historical_result_schema)

    adapter_path = STUDY_ROOT / "amy_verifier/github_attestation.py"
    manifest_path = STUDY_ROOT / "amy_verifier/manifest.py"
    adapter_source = adapter_path.read_text(encoding="utf-8")
    v2_adapter_path = STUDY_ROOT / "amy_verifier/github_attestation_v2.py"
    v2_adapter_source = v2_adapter_path.read_text(encoding="utf-8")
    v2_core_path = STUDY_ROOT / "amy_verifier/github_attestation_v2_core.py"
    v2_core_source = v2_core_path.read_text(encoding="utf-8")
    manifest_source = manifest_path.read_text(encoding="utf-8")
    adapter_tree = ast.parse(adapter_source, filename=str(adapter_path))
    v2_adapter_tree = ast.parse(v2_adapter_source, filename=str(v2_adapter_path))
    v2_core_tree = ast.parse(v2_core_source, filename=str(v2_core_path))
    manifest_tree = ast.parse(manifest_source, filename=str(manifest_path))
    v2_cli_path = STUDY_ROOT / "scripts/verify_github_attestation_v2.py"
    v2_cli_source = v2_cli_path.read_text(encoding="utf-8")
    cli_tree = ast.parse(v2_cli_source, filename=str(v2_cli_path))
    adapter_tests_tree = ast.parse(
        (STUDY_ROOT / "tests/test_github_attestation_adapter.py").read_text(encoding="utf-8")
    )
    decision_tests_tree = ast.parse(
        (STUDY_ROOT / "tests/test_attestation_profile_decision.py").read_text(
            encoding="utf-8"
        )
    )
    v2_tests_tree = ast.parse(
        (STUDY_ROOT / "tests/test_github_attestation_v2.py").read_text(
            encoding="utf-8"
        )
    )

    enforce_p3 = function_node(v2_core_tree, "_enforce_p3")
    enforce_manifest = function_node(v2_core_tree, "_enforce_manifest_assertions")
    low_level = function_node(v2_core_tree, "verify_github_manifest_attestation")
    integrated = function_node(v2_core_tree, "verify_github_p3_release")
    v2_loader = function_node(v2_adapter_tree, "load_github_policy_v2")
    v2_materialize = function_node(v2_adapter_tree, "_materialize_document")
    v2_low_level = function_node(
        v2_adapter_tree, "verify_github_manifest_attestation_v2"
    )
    v2_integrated = function_node(v2_adapter_tree, "verify_github_p3_release_v2")
    v2_serializer = function_node(v2_adapter_tree, "evidence_to_json_v2")
    p1 = function_node(manifest_tree, "validate_p1_manifest")
    cli_main = function_node(cli_tree, "main")
    integrated_test = function_node(
        adapter_tests_tree,
        "test_production_p3_runs_p1_and_rejects_changed_payload",
    )

    base_codes = {entry["code"] for entry in reasons.get("codes", [])}
    extra_codes = {
        entry["code"] for entry in production_reasons.get("additional_codes", [])
    }
    observed_rejection_codes = set(rejection_codes(v2_core_tree))
    policy_schema_validation_errors = list(
        Draft202012Validator(
            policy_schema, format_checker=FormatChecker()
        ).iter_errors(policy)
    )
    policy_schema_open_object_locations = object_schemas_without_additional_properties(
        policy_schema
    )

    schema_properties = schema.get("properties") or {}
    build_metadata = (schema.get("$defs") or {}).get("buildMetadata") or {}
    build_properties = build_metadata.get("properties") or {}
    source_properties = ((build_properties.get("source") or {}).get("properties") or {})
    snapshot_properties = ((source_properties.get("snapshot") or {}).get("properties") or {})
    policy_manifest = policy.get("manifest") or {}
    policy_result = policy.get("result") or {}
    policy_statement = policy.get("statement") or {}
    policy_provenance = policy.get("provenance") or {}
    policy_identity = policy.get("identity") or {}
    required_roles = policy_manifest.get("required_roles_by_release_kind") or {}
    release_kinds = set(
        (((schema_properties.get("release") or {}).get("properties") or {}).get("kind") or {}).get(
            "enum", []
        )
    )

    workflow_relative = policy_provenance.get("workflow_path")
    workflow_path = (
        REPOSITORY_ROOT / workflow_relative
        if isinstance(workflow_relative, str)
        else REPOSITORY_ROOT / "__invalid_workflow_path__"
    )
    tbd_locations = [
        location
        for location, text in walk_strings(policy)
        if "TBD-BEFORE-REGISTRATION" in text
    ]
    gate_by_id = {
        gate.get("id"): gate for gate in gates.get("gates", []) if isinstance(gate, dict)
    }
    production_results = retained_production_results(policy)
    real_amy_p3_records = [
        record for record in production_results if record.get("is_selected_repository_p3")
    ]

    integrated_calls = function_calls(integrated)
    low_level_literals = function_string_literals(low_level)
    enforce_manifest_calls = function_calls(enforce_manifest)
    enforce_manifest_literals = set(function_string_literals(enforce_manifest))
    p1_calls = function_calls(p1)
    snapshot_references = source_snapshot_references()
    archive_semantic_symbols = {
        "tarfile",
        "TarFile",
        "git",
        "git_archive",
        "git_tree",
        "recompute_git_tree",
        "validate_source_snapshot",
    }
    scoped_semantic_calls = sorted(
        call
        for call in set(enforce_manifest_calls) | set(integrated_calls) | set(p1_calls)
        if call.rsplit(".", 1)[-1] in archive_semantic_symbols
    )

    implementation_controls = {
        "standard_default_predicate_type_fixed": (
            policy_statement.get("attestation_mode")
            == "actions_attest_default_slsa_provenance"
            and policy_statement.get("p3_predicate_type")
            == "https://slsa.dev/provenance/v1"
        ),
        "custom_slsa_materials_removed": "materials" not in policy_provenance,
        "sole_manifest_subject_required": (
            (policy.get("subject") or {}).get("allow_additional_subjects") is False
        ),
        "manifest_schema_hash_bound": policy_manifest.get("schema_sha256") == sha256(schema_path),
        "policy_v2_schema_valid": not policy_schema_validation_errors,
        "policy_v2_schema_closes_typed_objects": not policy_schema_open_object_locations,
        "policy_v2_schema_hash_bound": (
            (policy.get("policy_schema") or {}).get("schema_sha256")
            == sha256(policy_schema_path)
        ),
        "production_result_schema_hash_bound": (
            policy_result.get("schema_sha256") == sha256(result_schema_path)
        ),
        "historical_v1_bytes_preserved": all(
            sha256(STUDY_ROOT / relative) == expected
            for relative, expected in HISTORICAL_V1_SHA256.items()
        ),
        "build_metadata_required_and_schema_closed": (
            "build_metadata" in set(schema.get("required") or [])
            and build_metadata.get("additionalProperties") is False
        ),
        "workflow_authored_scope_explicit": (
            (build_properties.get("assertion_scope") or {}).get("const")
            == "workflow-authored-not-independently-certified"
        ),
        "snapshot_and_lock_cross_binding_called": (
            "_enforce_manifest_assertions" in function_calls(enforce_p3)
            and "payload_by_path.get" in enforce_manifest_calls
            and {
                "dependency lock",
                "required_payload_role",
                "sha256",
                "source snapshot",
            }.issubset(enforce_manifest_literals)
        ),
        "attestation_only_api_refuses_p3": (
            "attestation-only verification is P2; use verify_github_p3_release for P3"
            in low_level_literals
        ),
        "integrated_p3_calls_authenticated_verifier": (
            "_verify_github_manifest_attestation" in integrated_calls
        ),
        "integrated_p3_calls_p1": "validate_p1_manifest" in integrated_calls,
        "integrated_p3_checks_manifest_before_and_after_p1": (
            function_call_count(integrated, "bounded_regular_file_read") >= 3
            and "INPUT_CHANGED" in function_string_literals(integrated)
        ),
        "integrated_p3_exposes_schema_and_p1_evidence": (
            "replace" in integrated_calls
            and {"manifest_schema_sha256", "p1_checks"}.issubset(
                call_keyword_names(integrated, "replace")
            )
        ),
        "all_adapter_rejection_codes_registered": not (
            observed_rejection_codes - base_codes - extra_codes
        ),
        "release_kind_role_policy_complete": set(required_roles) == release_kinds,
        "cli_requires_schema_for_p3": (
            "--manifest-schema is mandatory for production P3"
            in function_string_literals(cli_main)
            and "verify_github_p3_release_v2" in function_calls(cli_main)
        ),
        "cli_validates_every_structured_result": (
            "--result-schema" in function_string_literals(cli_main)
            and "_result_validation_errors" in function_calls(cli_main)
            and policy_result.get("schema_version")
            == "amy.production-verification-result.v2-draft"
        ),
        "cli_suppresses_unvalidated_json_without_result_schema": (
            any(
                value.startswith(
                    "unstructured verifier error because the externally pinned v2 output"
                )
                for value in function_string_literals(cli_main)
            )
            and "sys.stderr" in dotted_references(cli_main)
        ),
        "v2_loader_requires_external_policy_sha": (
            "expected_policy_sha256" in function_string_literals(v2_loader)
            and "_require_sha256" in function_calls(v2_loader)
            and "_sha256" in function_calls(v2_loader)
        ),
        "v2_materialization_revalidates_immutable_bytes": (
            {
                "_parse_object",
                "_schema_errors",
                "_sha256",
                "_validate_policy_schema_identity",
                "_validate_result_schema",
                "_validate_schema",
            }.issubset(function_calls(v2_materialize))
        ),
        "v2_wrappers_require_frozen_document": (
            call_keyword_names(v2_low_level, "_materialize_document").issuperset(
                {"require_frozen"}
            )
            and call_keyword_names(v2_integrated, "_materialize_document").issuperset(
                {"require_frozen"}
            )
        ),
        "v2_evidence_carries_complete_contract_identity": (
            {
                "policy_sha256",
                "policy_schema_sha256",
                "result_schema_sha256",
            }.issubset(function_string_literals(v2_serializer))
            and {"_schema_errors", "_validate_result_schema"}.issubset(
                function_calls(v2_serializer)
            )
            and all(
                {
                    "policy_sha256",
                    "policy_schema_sha256",
                    "result_schema_sha256",
                }.issubset(
                    set(
                        ((result_schema.get("$defs") or {}).get(variant) or {}).get(
                            "required"
                        )
                        or []
                    )
                )
                for variant in ("accept", "reject", "error")
            )
        ),
        "v2_cli_binds_policy_and_result_contracts_before_output": (
            "--expected-policy-sha256" in function_string_literals(cli_main)
            and "--policy-schema" in function_string_literals(cli_main)
            and "--result-schema" in function_string_literals(cli_main)
            and "output_contract_ready" in v2_cli_source
            and "policy_contract_identity_v2" in function_calls(cli_main)
        ),
    }

    snapshot_semantics = {
        "declared_format": (snapshot_properties.get("format") or {}).get("const"),
        "declared_assurance": (snapshot_properties.get("assurance") or {}).get("const"),
        "format_references": snapshot_references,
        "snapshot_digest_cross_bound_to_manifest_payload": implementation_controls[
            "snapshot_and_lock_cross_binding_called"
        ],
        "snapshot_payload_bytes_hashed_by_p1": "hash_payload" in p1_calls,
        "archive_or_git_tree_semantic_calls_in_p3_p1_scope": scoped_semantic_calls,
        "archive_interior_inspected": bool(scoped_semantic_calls),
        "declared_git_tree_recomputed_from_snapshot": bool(scoped_semantic_calls),
        "git_tree_equivalence_claimed_by_selected_profile": False,
        "claim_boundary_matches_implementation": (
            (snapshot_properties.get("format") or {}).get("const")
            == SOURCE_SNAPSHOT_FORMAT
            and (snapshot_properties.get("assurance") or {}).get("const")
            == SOURCE_SNAPSHOT_ASSURANCE
            and not scoped_semantic_calls
        ),
        "bounded_conclusion": (
            "The selected verifier binds and recomputes the snapshot file digest, but the "
            "selected profile explicitly treats the tar as opaque bytes and makes no claim "
            "that its members reconstruct the declared Git tree."
        ),
    }

    test_names = sorted(
        set(test_functions(adapter_tests_tree))
        | set(test_functions(decision_tests_tree))
        | set(test_functions(v2_tests_tree))
    )
    integrated_test_calls = function_calls(integrated_test)
    test_contract = {
        "test_functions": test_names,
        "selected_profile_test_present": (
            "test_attestation_profile_decision_selects_but_does_not_freeze_recommended_profile"
            in test_names
        ),
        "default_predicate_missing_manifest_metadata_rejection_test_present": (
            "test_selected_p3_requires_manifest_metadata_beyond_default_provenance"
            in test_names
        ),
        "attestation_only_p3_refusal_test_present": (
            "test_attestation_only_api_refuses_to_label_an_incomplete_check_as_p3"
            in test_names
        ),
        "integrated_p1_payload_mutation_test_present": (
            "test_production_p3_runs_p1_and_rejects_changed_payload" in test_names
        ),
        "v2_external_policy_digest_rejection_test_present": (
            "test_v2_loader_rejects_wrong_external_policy_digest" in test_names
        ),
        "v2_template_refusal_test_present": (
            "test_v2_template_cannot_reach_underlying_verifier" in test_names
        ),
        "v2_mutable_policy_bypass_test_present": (
            "test_v2_api_rejects_plain_dict_policy" in test_names
        ),
        "v2_evidence_snapshot_test_present": (
            "test_v2_wrapper_snapshots_evidence_and_always_binds_contract_hashes"
            in test_names
        ),
        "v2_result_schema_substitution_test_present": (
            "test_v2_loader_rejects_result_schema_bytes_not_bound_by_policy"
            in test_names
        ),
        "v2_library_result_validation_test_present": (
            "test_v2_library_serializer_enforces_exact_result_schema" in test_names
        ),
        "v2_duplicate_policy_schema_test_present": (
            "test_v2_loader_rejects_duplicate_policy_schema_key" in test_names
        ),
        "v2_cross_field_consistency_test_present": (
            "test_v2_frozen_runtime_rejects_cross_field_mismatch" in test_names
        ),
        "historical_v1_invariant_test_present": (
            "test_historical_v1_artifacts_remain_byte_identical" in test_names
        ),
        "integrated_test_mocks_cryptographic_verifier": (
            "monkeypatch.setattr" in integrated_test_calls
            and "_verify_github_manifest_attestation"
            in function_string_literals(integrated_test)
        ),
        "integrated_test_expected_reason": (
            "DIGEST_MISMATCH"
            if "DIGEST_MISMATCH" in function_string_literals(integrated_test)
            else None
        ),
        "real_selected_repository_p3_records": real_amy_p3_records,
        "real_selected_repository_p3_record_count": len(real_amy_p3_records),
        "bounded_conclusion": (
            "Static test inventory and synthetic/mocked behavior do not establish a real "
            "A.M.Y GitHub/Sigstore P3 execution."
        ),
    }

    fixture_snapshot_spec = selected_overlay["payload_fixtures"]["source_snapshot"]
    fixture_snapshot_path = (
        STUDY_ROOT
        / "selected_profile_base_runs/r0_selected_bases_20260713T101851Z"
        / "bases/B01-TABULAR/release"
        / fixture_snapshot_spec["path"]
    )
    fixture_snapshot_members: list[dict[str, Any]] = []
    fixture_snapshot_error: str | None = None
    try:
        with tarfile.open(fixture_snapshot_path, "r:") as fixture_archive:
            for member in fixture_archive.getmembers():
                handle = fixture_archive.extractfile(member) if member.isreg() else None
                raw = handle.read() if handle is not None else None
                fixture_snapshot_members.append(
                    {
                        "name": member.name,
                        "regular": member.isreg(),
                        "bytes": len(raw) if raw is not None else None,
                        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
                        "mode": member.mode,
                        "uid": member.uid,
                        "gid": member.gid,
                        "mtime": member.mtime,
                    }
                )
    except (OSError, tarfile.TarError) as exc:
        fixture_snapshot_error = f"{type(exc).__name__}: {exc}"
    fixture_recipe = fixture_snapshot_spec.get("recipe") or {}
    expected_fixture_member_raw = str(fixture_recipe.get("utf8_text", "")).encode(
        "utf-8"
    )
    fixture_snapshot_is_valid_deterministic_ustar = bool(
        fixture_snapshot_error is None
        and fixture_snapshot_path.stat().st_size == fixture_snapshot_spec.get("bytes")
        and sha256(fixture_snapshot_path) == fixture_snapshot_spec.get("sha256")
        and fixture_snapshot_members
        == [
            {
                "name": fixture_recipe.get("member_path"),
                "regular": True,
                "bytes": len(expected_fixture_member_raw),
                "sha256": hashlib.sha256(expected_fixture_member_raw).hexdigest(),
                "mode": 0o644,
                "uid": 0,
                "gid": 0,
                "mtime": 0,
            }
        ]
    )
    selected_clean_result_count = sum(
        len((record.get("clean_profile_results") or {}))
        for record in selected_base_validation.get("validated_bases", [])
    )
    selected_catalog_summary = selected_catalog_validation.get("summary") or {}
    selected_migration = {
        "classification": "controlled_S1_migration_not_production_sigstore",
        "fixture_snapshot": {
            "path": fixture_snapshot_path.relative_to(STUDY_ROOT).as_posix(),
            "declared_media_type": fixture_snapshot_spec.get("media_type"),
            "declared_bytes": fixture_snapshot_spec.get("bytes"),
            "declared_sha256": fixture_snapshot_spec.get("sha256"),
            "observed_bytes": fixture_snapshot_path.stat().st_size,
            "observed_sha256": sha256(fixture_snapshot_path),
            "members": fixture_snapshot_members,
            "parse_error": fixture_snapshot_error,
            "valid_deterministic_ustar": fixture_snapshot_is_valid_deterministic_ustar,
            "git_tree_equivalence_claimed": False,
        },
        "clean_bases": {
            "validation_valid": selected_base_validation.get("valid"),
            "base_count": selected_base_validation.get("base_count"),
            "clean_profile_result_count": selected_clean_result_count,
            "confirmatory_cases_generated": selected_base_validation.get(
                "confirmatory_cases_generated"
            ),
            "confirmatory_outcomes_read": selected_base_validation.get(
                "confirmatory_outcomes_read"
            ),
            "production_sigstore_conformance": selected_base_validation.get(
                "production_sigstore_conformance"
            ),
            "retained_run_comparison_valid": selected_base_comparison.get("valid"),
            "retained_base_archive_result_files_identical": (
                selected_base_comparison.get(
                    "base_archive_and_result_inventories_identical"
                )
            ),
            "retained_source_archives_identical": (
                (selected_base_comparison.get("source_archive_sha256") or {}).get(
                    "identical"
                )
            ),
            "current_replay_valid": selected_base_current_replay.get("valid"),
            "retained_source_archive_self_valid": selected_base_current_replay.get(
                "retained_source_archive_self_valid"
            ),
            "retained_source_matches_current_study": selected_base_current_replay.get(
                "retained_source_matches_current_study"
            ),
            "retained_source_drift_paths": selected_base_current_replay.get(
                "retained_source_drift_paths"
            ),
        },
        "catalog": {
            "validation_valid": selected_catalog_validation.get("valid"),
            "historical_case_count": selected_catalog_summary.get(
                "historical_case_count"
            ),
            "selected_case_count": selected_catalog_summary.get("selected_case_count"),
            "preserved_case_id_count": selected_catalog_summary.get(
                "preserved_case_id_count"
            ),
            "added_case_count": selected_catalog_summary.get("added_case_count"),
            "migrated_semantic_case_count": selected_catalog_summary.get(
                "migrated_semantic_case_count"
            ),
            "implemented_generator_case_count": selected_catalog_summary.get(
                "implemented_generator_case_count"
            ),
            "confirmatory_cases_executed": selected_catalog_summary.get(
                "confirmatory_cases_executed"
            ),
            "confirmatory_outcomes_read": selected_catalog_summary.get(
                "confirmatory_outcomes_read"
            ),
        },
        "oracle": {
            "validation_valid": selected_oracle_validation.get("valid"),
            "case_count": selected_oracle_validation.get("case_count"),
            "row_count": selected_oracle_validation.get("row_count"),
            "module_separation_static_check": selected_oracle_validation.get(
                "module_separation_static_check"
            ),
            "confirmatory_cases_executed": selected_oracle_validation.get(
                "confirmatory_cases_executed"
            ),
            "confirmatory_outcomes_read": selected_oracle_validation.get(
                "confirmatory_outcomes_read"
            ),
            "independent_human_review_complete": selected_oracle_validation.get(
                "independent_human_review_complete"
            ),
        },
        "development_execution": {
            "validation_valid": selected_development_validation.get("valid"),
            "pytest_passed_count": selected_development_validation.get(
                "pytest_passed_count"
            ),
            "case_count": selected_development_validation.get("catalog_case_count"),
            "oracle_row_count": selected_development_validation.get("oracle_row_count"),
            "case_profile_evaluations": selected_development_validation.get(
                "development_case_profile_evaluations"
            ),
            "confirmatory_evidence": selected_development_validation.get(
                "confirmatory_evidence"
            ),
            "production_sigstore_conformance": selected_development_validation.get(
                "production_sigstore_conformance"
            ),
            "independent_oracle_review": selected_development_validation.get(
                "independent_oracle_review"
            ),
            "source_inventory_unchanged_during_execution": (
                selected_development_validation.get(
                    "source_inventory_unchanged_during_execution"
                )
            ),
        },
        "base_aware_mutation_plans": {
            "validation_valid": base_aware_validation.get("valid"),
            "passed_test_count": base_aware_validation.get("passed_test_count"),
            "resolved_plan_count": base_aware_validation.get("resolved_plan_count"),
            "unavailable_plan_count": base_aware_validation.get(
                "unavailable_plan_count"
            ),
            "disposable_target_dependent_execution_count": (
                (base_aware_record.get("declared_coverage") or {}).get(
                    "disposable_target_dependent_execution_count"
                )
            ),
            "policy_fixture_collision_tested": (
                (base_aware_record.get("declared_coverage") or {}).get(
                    "policy_fixture_collision_tested"
                )
            ),
            "forged_plan_rejection_tested": (
                (base_aware_record.get("declared_coverage") or {}).get(
                    "forged_plan_rejection_tested"
                )
            ),
            "source_inventory_unchanged_during_execution": base_aware_record.get(
                "source_inventory_unchanged_during_execution"
            ),
            "unavailable_plans": base_aware_record.get("unavailable_plans"),
            "boundaries": base_aware_record.get("boundaries"),
            "decision": base_aware_record.get("decision"),
            "manuscript_claims_authorized": base_aware_record.get(
                "manuscript_claims_authorized"
            ),
        },
        "compatibility": {
            "validation_valid": selected_compatibility_validation.get("valid"),
            "candidate_unit_count": selected_compatibility_validation.get(
                "candidate_unit_count"
            ),
            "compatibility_counts": selected_compatibility_validation.get(
                "compatibility_counts"
            ),
            "mutation_plan_counts": selected_compatibility_validation.get(
                "mutation_plan_counts"
            ),
            "outcome_blinded": selected_compatibility_validation.get(
                "outcome_blinded"
            ),
            "counterfactual_outcome_fields_invariant": (
                selected_compatibility_validation.get(
                    "counterfactual_outcome_fields_invariant"
                )
            ),
            "confirmatory_cases_generated": selected_compatibility_validation.get(
                "confirmatory_cases_generated"
            ),
            "confirmatory_outcomes_read": selected_compatibility_validation.get(
                "confirmatory_outcomes_read"
            ),
        },
        "full_41_case_generator_migration_complete": (
            (decision.get("implementation_state") or {}).get(
                "full_41_case_generator_migration_complete"
            )
        ),
        "pilot_profile_migration_complete": (
            (decision.get("implementation_state") or {}).get(
                "pilot_profile_migration_complete"
            )
        ),
        "bounded_conclusion": (
            "Selected-profile clean bases, all 41 temporary-fixture mutation branches, "
            "245 resolved base-aware plans plus one exact unavailable plan, a "
            "schema-closed 164-row catalog-derived draft oracle, and compatibility "
            "metadata now exist under controlled public PKI. Independent oracle review, "
            "the frozen six-base case runner, and production Sigstore execution remain "
            "incomplete."
        ),
    }

    open_blockers: list[dict[str, str]] = []
    if tbd_locations:
        open_blockers.append(
            {
                "id": "release_policy_tbd_values",
                "evidence": f"{len(tbd_locations)} policy string locations remain unresolved",
            }
        )
    if not workflow_path.is_file():
        open_blockers.append(
            {
                "id": "release_workflow_absent",
                "evidence": str(workflow_relative),
            }
        )
    if not real_amy_p3_records:
        open_blockers.append(
            {
                "id": "real_amy_p3_absent",
                "evidence": "no retained P3 result for the selected repository",
            }
        )
    state = decision.get("implementation_state") or {}
    if state.get("independent_human_review_complete") is not True:
        open_blockers.append(
            {"id": "independent_review_incomplete", "evidence": "decision implementation_state"}
        )
    if state.get("pilot_profile_migration_complete") is not True:
        open_blockers.append(
            {
                "id": "s1_registered_runner_migration_incomplete",
                "evidence": (
                    "the 41-case generic temporary-fixture generator, 245 resolved "
                    "base-aware plans, and 164-row draft oracle exist, but the frozen "
                    "six-base post-registration case runner and its independent review "
                    "do not"
                ),
            }
        )
    production_result_schemas = sorted(
        path.relative_to(STUDY_ROOT).as_posix()
        for path in (STUDY_ROOT / "schemas").glob("*production*result*.json")
    )
    if not production_result_schemas:
        open_blockers.append(
            {
                "id": "production_result_schema_absent",
                "evidence": "no schemas/*production*result*.json file",
            }
        )

    inputs: dict[str, dict[str, Any]] = {}
    for relative in CONTRACT_PATHS:
        path = STUDY_ROOT / relative
        inputs[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    fixture_snapshot_relative = fixture_snapshot_path.relative_to(STUDY_ROOT).as_posix()
    inputs[fixture_snapshot_relative] = {
        "bytes": fixture_snapshot_path.stat().st_size,
        "sha256": sha256(fixture_snapshot_path),
    }
    for record in production_results:
        relative = record["path"]
        path = STUDY_ROOT / relative
        inputs[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    return {
        "schema_version": "amy.selected-attestation-profile-audit.v1",
        "classification": "pre_registration_static_and_retained_record_audit",
        "safety": {
            "network_used": False,
            "github_cli_invoked": False,
            "signature_verified": False,
            "workflow_executed": False,
            "confirmatory_results_read": False,
        },
        "scope": {
            "selected_profile": SELECTED_PROFILE,
            "repository_root": str(REPOSITORY_ROOT),
            "study_root": str(STUDY_ROOT),
            "inputs": inputs,
        },
        "selection": {
            "status": decision.get("status"),
            "selected_profile": decision.get("selected_profile"),
            "recommended_profile": decision.get("recommended_profile"),
            "selected_before_confirmatory_outcomes": (
                (decision.get("selection_record") or {}).get(
                    "confirmatory_outcomes_observed"
                )
                is False
            ),
            "profile_selected_but_not_frozen": (
                decision.get("selected_profile") == SELECTED_PROFILE
                and decision.get("status") == "selected_for_implementation_not_frozen"
            ),
        },
        "policy_and_schema": {
            "schema_valid_draft_2020_12": True,
            "current_policy_contract_version": policy.get("schema_version"),
            "current_policy_status": policy.get("status"),
            "current_policy_path": "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json",
            "current_policy_sha256": sha256(
                STUDY_ROOT / "protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json"
            ),
            "policy_schema_valid_draft_2020_12": not policy_schema_validation_errors,
            "policy_schema_path": (policy.get("policy_schema") or {}).get(
                "schema_path"
            ),
            "policy_schema_sha256_expected": (policy.get("policy_schema") or {}).get(
                "schema_sha256"
            ),
            "policy_schema_sha256_observed": sha256(policy_schema_path),
            "policy_schema_hash_matches": (
                (policy.get("policy_schema") or {}).get("schema_sha256")
                == sha256(policy_schema_path)
            ),
            "policy_schema_typed_object_openings": policy_schema_open_object_locations,
            "schema_path": policy_manifest.get("schema_path"),
            "schema_sha256_expected": policy_manifest.get("schema_sha256"),
            "schema_sha256_observed": sha256(schema_path),
            "schema_hash_matches": policy_manifest.get("schema_sha256") == sha256(schema_path),
            "result_schema_path": policy_result.get("schema_path"),
            "result_schema_sha256_expected": policy_result.get("schema_sha256"),
            "result_schema_sha256_observed": sha256(result_schema_path),
            "result_schema_hash_matches": (
                policy_result.get("schema_sha256") == sha256(result_schema_path)
            ),
            "source_repository_uri": policy_identity.get("repository_uri"),
            "unresolved_tbd_locations": tbd_locations,
            "unresolved_tbd_count": len(tbd_locations),
            "workflow_path": str(workflow_relative),
            "workflow_exists": workflow_path.is_file(),
            "production_result_schemas": production_result_schemas,
            "historical_v1_policy_version": historical_policy.get("policy_version"),
            "historical_v1_result_schema_path": (
                historical_result_schema_path.relative_to(STUDY_ROOT).as_posix()
            ),
            "historical_v1_artifact_sha256_expected": HISTORICAL_V1_SHA256,
            "historical_v1_artifact_sha256_observed": {
                relative: sha256(STUDY_ROOT / relative)
                for relative in HISTORICAL_V1_SHA256
            },
            "historical_v1_bytes_preserved": all(
                sha256(STUDY_ROOT / relative) == expected
                for relative, expected in HISTORICAL_V1_SHA256.items()
            ),
        },
        "implementation": {
            "controls": implementation_controls,
            "all_listed_controls_present": all(implementation_controls.values()),
            "integrated_p1_check_keys": p1_check_keys(integrated),
            "adapter_rejection_codes": sorted(observed_rejection_codes),
            "registered_base_reason_codes": sorted(base_codes),
            "registered_production_reason_codes": sorted(extra_codes),
            "unregistered_adapter_rejection_codes": sorted(
                observed_rejection_codes - base_codes - extra_codes
            ),
            "integrated_p3_calls": integrated_calls,
            "p1_calls": p1_calls,
        },
        "source_snapshot_semantics": snapshot_semantics,
        "selected_s1_migration": selected_migration,
        "tests_and_retained_runs": {
            **test_contract,
            "retained_production_results": production_results,
        },
        "registration": {
            "registry_status": gates.get("status"),
            "rg_009_status": (gate_by_id.get("RG-009") or {}).get("status"),
            "rg_010_status": (gate_by_id.get("RG-010") or {}).get("status"),
            "open_blockers": open_blockers,
            "open_blocker_count": len(open_blockers),
            "freeze_permitted_now": False,
        },
        "bounded_conclusions": [
            "The selected production code path is structurally integrated with P1 and refuses attestation-only P3 labeling.",
            "The current v2 wrapper requires an externally expected policy SHA-256, revalidates immutable policy/schema bytes at use, and binds policy, policy-schema, and result-schema digests into every structured result.",
            "The historical v1 policy, result schema, CLI, adapter, and retained real P2 result remain byte-identical and are not reinterpreted as v2 evidence.",
            "The retained behavioral evidence for integrated P3 is synthetic and mocks the cryptographic verifier.",
            "The only retained real Sigstore record in scope is P2 for GitHub CLI, not A.M.Y P3.",
            selected_migration["bounded_conclusion"],
            snapshot_semantics["bounded_conclusion"],
            "No registration, production-readiness, scientific-truth, or real-A.M.Y-P3 claim follows from this audit.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_audit()
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
