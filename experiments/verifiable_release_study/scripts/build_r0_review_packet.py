#!/usr/bin/env python3
"""Build an unreviewed, deterministic subject packet for future RG-004 review.

This builder reads an explicit source/contract set plus exact synthetic
base-aware and RG-006 NO-GO receipts. It does not discover files, execute a
verifier, inspect an empirical or confirmatory case run, or claim that human
review occurred.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Sequence

import rfc8785


STUDY_ROOT = Path(__file__).resolve().parents[1]
SUBJECT_MANIFEST_NAME = "R0_REVIEW_SUBJECT_MANIFEST.jcs.json"
PACKET_NAME = "R0_REVIEW_PACKET.tar"
MAX_SUBJECT_BYTES = 64 * 1024 * 1024

# This tuple is the complete review surface.  It is intentionally explicit and
# UTF-8-bytewise sorted: no glob, directory walk, run-output lookup, or import of
# study implementation code participates in packet construction.
SUBJECTS: tuple[tuple[str, str], ...] = (
    ("CHANGELOG.md", "protocol.design_chronology"),
    ("README.md", "protocol.study_status"),
    ("amy_verifier/__init__.py", "implementation.package_boundary"),
    ("amy_verifier/attestation.py", "implementation.fixture_attestation"),
    ("amy_verifier/base_corpus.py", "implementation.base_constructor"),
    ("amy_verifier/confirmatory_runner.py", "implementation.confirmatory_runner_contract"),
    ("amy_verifier/fixture_crypto.py", "implementation.fixture_crypto"),
    ("amy_verifier/github_attestation.py", "implementation.production_core"),
    ("amy_verifier/github_attestation_v2.py", "implementation.production_adapter"),
    ("amy_verifier/github_attestation_v2_core.py", "implementation.production_core_v2"),
    ("amy_verifier/json_tools.py", "implementation.fail_closed_json_io"),
    ("amy_verifier/manifest.py", "implementation.manifest_verifier"),
    ("amy_verifier/model.py", "implementation.result_model"),
    ("amy_verifier/path_policy.py", "implementation.path_policy"),
    ("amy_verifier/pilot.py", "implementation.fixture_builder"),
    ("amy_verifier/selected_profile_evaluator.py", "implementation.result_evaluator"),
    ("amy_verifier/selected_profile_fixture.py", "implementation.selected_verifier"),
    ("amy_verifier/selected_profile_mutations.py", "implementation.mutation_generator"),
    ("amy_verifier/selected_profile_oracle.py", "implementation.oracle_renderer"),
    ("amy_verifier/verifier.py", "implementation.fixture_verifier_core"),
    ("corpus/BASE_REGISTRY_DRAFT.json", "base.registry"),
    ("corpus/COMPATIBILITY_MATRIX_DRAFT.json", "compatibility.historical_matrix"),
    ("corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json", "compatibility.matrix"),
    (
        "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_VALIDATION.json",
        "compatibility.same_author_validation",
    ),
    (
        "corpus/COMPATIBILITY_MATRIX_VALIDATION.json",
        "compatibility.historical_validation",
    ),
    ("corpus/README.md", "base.boundary_documentation"),
    ("dummy_analysis/DUMMY_ANALYSIS_SUMMARY.json", "proposition.dummy_analysis_output"),
    ("dummy_analysis/DUMMY_OBSERVATION_LEDGER.json", "proposition.dummy_analysis_input"),
    ("evidence/CLAIM_EVIDENCE_MATRIX.csv", "protocol.claim_ledger"),
    ("evidence/SOURCE_LEDGER.md", "protocol.source_ledger"),
    ("paper/MANUSCRIPT_SKELETON.md", "protocol.manuscript_skeleton"),
    ("paper/lint_manuscript.py", "implementation.manuscript_linter"),
    ("preregistration/OSF_PREREGISTRATION_DRAFT.md", "protocol.preregistration_draft"),
    ("protocol/ATTACK_CATALOG.json", "catalog.historical"),
    ("protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json", "catalog.selected_profile"),
    (
        "protocol/ATTACK_CATALOG_SELECTED_PROFILE_VALIDATION.json",
        "catalog.same_author_validation",
    ),
    ("protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json", "policy.profile_selection"),
    ("protocol/CLAIM_BOUNDARIES.md", "protocol.claim_boundaries"),
    (
        "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
        "protocol.confirmatory_runner_contract",
    ),
    ("protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE.json", "policy.fixture_base"),
    ("protocol/GITHUB_ATTESTATION_POLICY_TEMPLATE_V2.json", "policy.production_template"),
    ("protocol/LIMITATIONS_AND_BOUNDARIES.md", "protocol.limitations"),
    ("protocol/MODEL_REVIEW_PROTOCOL.json", "protocol.model_review"),
    ("protocol/PATH_POLICY_DRAFT.md", "policy.filesystem"),
    (
        "protocol/PREREQUISITE_REGISTRY_DRAFT.json",
        "compatibility.historical_prerequisites",
    ),
    (
        "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json",
        "compatibility.prerequisites",
    ),
    ("protocol/PRE_R0_CLOSURE_LEDGER.json", "protocol.pre_r0_closure_ledger"),
    (
        "protocol/PRE_R0_CLOSURE_LEDGER_VALIDATION.json",
        "protocol.pre_r0_closure_validation",
    ),
    ("protocol/PRODUCTION_REASON_CODES_DRAFT.json", "policy.production_reason_codes"),
    ("protocol/PRODUCTION_SIGSTORE_GATE_DRAFT.md", "policy.production_gate"),
    ("protocol/PROPOSITION_MATRIX_DRAFT.json", "proposition.matrix"),
    ("protocol/PROTOCOL_DRAFT.md", "protocol.study_design"),
    ("protocol/R0_HUMAN_REVIEW_RECORD_TEMPLATE.json", "protocol.review_record_template"),
    (
        "protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json",
        "policy.reviewer_identity",
    ),
    (
        "protocol/R0_REVIEWER_IDENTITY_POLICY_VALIDATION.json",
        "policy.reviewer_identity_validation",
    ),
    ("protocol/REASON_CODES.json", "policy.reason_codes"),
    ("protocol/REGISTRATION_GATES.json", "protocol.registration_gates"),
    ("protocol/RELEASE_LINEAGE_CONTRACT_DRAFT.json", "protocol.release_lineage"),
    ("protocol/RELEASE_LINEAGE_VALIDATION.json", "protocol.release_lineage_validation"),
    ("protocol/ROBUSTNESS_CATALOG_DRAFT.json", "protocol.robustness_catalog"),
    ("protocol/RUN_EXECUTION_POLICY_DRAFT.json", "policy.run_execution"),
    ("protocol/RUN_EXECUTION_POLICY_VALIDATION.json", "policy.run_execution_validation"),
    ("protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json", "policy.selected_fixture"),
    ("protocol/SELECTED_PROFILE_ORACLE_DRAFT.json", "oracle.rows"),
    (
        "protocol/SELECTED_PROFILE_ORACLE_VALIDATION.json",
        "oracle.same_author_validation",
    ),
    ("protocol/THREAT_MODEL.md", "protocol.threat_model"),
    ("protocol/TRUST_POLICY_DRAFT.json", "policy.fixture_trust"),
    ("protocol/VERSIONING_AND_SIGNING_POLICY.md", "policy.versioning_and_signing"),
    ("pyproject.toml", "implementation.dependency_contract"),
    ("reviews/R0_REVIEW_PACKET_DRAFT.md", "protocol.review_packet_instructions"),
    ("schemas/analysis-summary.schema.json", "schema.analysis_summary"),
    (
        "schemas/base-aware-mutation-development-check.schema.json",
        "schema.base_aware_mutation_development_check",
    ),
    ("schemas/environment-attempt-record.schema.json", "schema.environment_attempt"),
    ("schemas/github-attestation-policy-v2.schema.json", "schema.production_policy"),
    (
        "schemas/github-production-verification-result-v2.schema.json",
        "schema.production_result",
    ),
    (
        "schemas/github-production-verification-result.schema.json",
        "schema.production_result_historical",
    ),
    (
        "schemas/infrastructure-classification.schema.json",
        "schema.infrastructure_classification",
    ),
    ("schemas/manifest-production-v0.2.schema.json", "schema.production_manifest"),
    ("schemas/manifest.schema.json", "schema.fixture_manifest"),
    ("schemas/model-review-protocol.schema.json", "schema.model_review_protocol"),
    ("schemas/model-review-response.schema.json", "schema.model_review_response"),
    ("schemas/observation-ledger.schema.json", "schema.observation_ledger"),
    ("schemas/official-attempt-selection.schema.json", "schema.official_attempt_selection"),
    (
        "schemas/pre-r0-closure-ledger-validation.schema.json",
        "schema.pre_r0_closure_validation",
    ),
    ("schemas/pre-r0-closure-ledger.schema.json", "schema.pre_r0_closure_ledger"),
    ("schemas/process-isolation-record.schema.json", "schema.process_isolation"),
    ("schemas/r0-human-review-record.schema.json", "schema.human_review_record"),
    (
        "schemas/r0-review-packet-verification.schema.json",
        "schema.review_packet_verification",
    ),
    (
        "schemas/r0-reviewer-identity-policy-validation.schema.json",
        "schema.reviewer_identity_policy_validation",
    ),
    (
        "schemas/r0-reviewer-identity-policy.schema.json",
        "schema.reviewer_identity_policy",
    ),
    ("schemas/release-lineage-contract.schema.json", "schema.release_lineage"),
    ("schemas/release-lineage-validation.schema.json", "schema.release_lineage_validation"),
    (
        "schemas/rg006-contract-test-record-v2.schema.json",
        "schema.rg006_contract_test_historical_v2",
    ),
    (
        "schemas/rg006-contract-test-record-v3.schema.json",
        "schema.rg006_contract_test_active_v3",
    ),
    (
        "schemas/rg006-contract-test-record.schema.json",
        "schema.rg006_contract_test_historical_v1",
    ),
    ("schemas/run-execution-policy-validation.schema.json", "schema.run_execution_validation"),
    ("schemas/run-execution-policy.schema.json", "schema.run_execution"),
    ("schemas/scientific-intent-event.schema.json", "schema.scientific_intent_event"),
    (
        "schemas/selected-profile-development-check.schema.json",
        "schema.development_check",
    ),
    ("schemas/selected-profile-fixture-result.schema.json", "schema.fixture_result"),
    ("schemas/selected-profile-oracle.schema.json", "schema.oracle"),
    ("schemas/verifier-result.schema.json", "schema.fixture_result_historical"),
    ("scripts/analyze_observation_ledger.py", "implementation.analysis"),
    ("scripts/build_compatibility_matrix.py", "implementation.historical_compatibility_builder"),
    ("scripts/build_dummy_analysis_fixture.py", "implementation.dummy_analysis_builder"),
    ("scripts/build_r0_bases.py", "implementation.historical_base_builder"),
    ("scripts/build_r0_review_packet.py", "implementation.packet_builder"),
    ("scripts/build_selected_profile_bases.py", "implementation.base_builder"),
    ("scripts/build_selected_profile_catalog.py", "implementation.catalog_builder"),
    (
        "scripts/build_selected_profile_compatibility_matrix.py",
        "implementation.compatibility_builder",
    ),
    ("scripts/build_selected_profile_oracle.py", "implementation.oracle_builder"),
    ("scripts/probe_filesystem_capabilities.py", "implementation.environment_probe"),
    (
        "scripts/run_base_aware_mutation_development_check.py",
        "implementation.base_aware_mutation_test_runner",
    ),
    ("scripts/run_model_review_batch.py", "implementation.model_review_runner"),
    ("scripts/run_pilot.py", "implementation.historical_pilot_runner"),
    ("scripts/run_rg006_contract_tests.py", "implementation.runner_contract_test_runner"),
    (
        "scripts/run_selected_profile_development_checks.py",
        "implementation.development_check_runner",
    ),
    (
        "scripts/validate_base_aware_mutation_development_check.py",
        "implementation.base_aware_mutation_test_validator",
    ),
    ("scripts/validate_claim_evidence_matrix.py", "implementation.claim_evidence_validator"),
    ("scripts/validate_compatibility_matrix.py", "implementation.historical_compatibility_validator"),
    ("scripts/validate_model_review_batch.py", "implementation.model_review_validator"),
    ("scripts/validate_pilot_run.py", "implementation.historical_pilot_validator"),
    (
        "scripts/validate_pre_r0_closure_ledger.py",
        "implementation.pre_r0_closure_validator",
    ),
    ("scripts/validate_protocol.py", "implementation.protocol_validator"),
    ("scripts/validate_r0_base_run.py", "implementation.historical_base_validator"),
    (
        "scripts/validate_r0_reviewer_identity_policy.py",
        "implementation.reviewer_identity_policy_validator",
    ),
    ("scripts/validate_release_lineage_contract.py", "implementation.release_lineage_validator"),
    ("scripts/validate_robustness_run.py", "implementation.robustness_validator"),
    ("scripts/validate_run_execution_policy.py", "implementation.run_policy_validator"),
    ("scripts/validate_selected_profile_base_run.py", "implementation.base_validator"),
    ("scripts/validate_selected_profile_catalog.py", "implementation.catalog_validator"),
    (
        "scripts/validate_selected_profile_compatibility_matrix.py",
        "implementation.compatibility_validator",
    ),
    (
        "scripts/validate_selected_profile_development_check.py",
        "implementation.development_check_validator",
    ),
    ("scripts/validate_selected_profile_oracle.py", "implementation.oracle_validator"),
    ("scripts/verify_github_attestation.py", "implementation.production_cli_historical"),
    ("scripts/verify_github_attestation_v2.py", "implementation.production_cli"),
    ("scripts/verify_r0_review_packet.py", "implementation.review_packet_verifier"),
    ("tests/test_attestation_profile_decision.py", "test.profile_selection"),
    (
        "tests/test_base_aware_mutation_development_record.py",
        "test.base_aware_mutation_development_record",
    ),
    ("tests/test_claim_evidence_matrix.py", "test.claim_evidence_matrix"),
    ("tests/test_compatibility_matrix.py", "test.historical_compatibility"),
    ("tests/test_confirmatory_runner_contract.py", "test.confirmatory_runner_contract"),
    ("tests/test_dummy_analysis.py", "test.dummy_analysis"),
    ("tests/test_environment_capabilities.py", "test.environment_capabilities"),
    ("tests/test_full_pilot.py", "test.fixture_end_to_end"),
    ("tests/test_github_attestation_adapter.py", "test.production_core"),
    ("tests/test_github_attestation_v2.py", "test.production_adapter"),
    ("tests/test_jcs_and_dsse_vectors.py", "test.canonicalization_vectors"),
    ("tests/test_manuscript_skeleton.py", "test.manuscript_skeleton"),
    ("tests/test_model_review_protocol.py", "test.model_review_protocol"),
    ("tests/test_p0_p1_verifier.py", "test.fixture_p0_p1"),
    ("tests/test_pilot_attestation_profiles.py", "test.fixture_p2_p3"),
    ("tests/test_pre_r0_closure_ledger.py", "test.pre_r0_closure_ledger"),
    ("tests/test_production_result_schema.py", "test.production_result_contract"),
    ("tests/test_protocol_contract.py", "test.protocol_contract"),
    ("tests/test_r0_base_design.py", "test.base_design"),
    ("tests/test_r0_human_review_contract.py", "test.review_contract"),
    ("tests/test_release_lineage_contract.py", "test.release_lineage"),
    ("tests/test_robustness_run_record.py", "test.robustness_record"),
    ("tests/test_run_execution_policy.py", "test.run_execution_policy"),
    ("tests/test_selected_profile_base_run.py", "test.base_contract"),
    ("tests/test_selected_profile_catalog.py", "test.catalog_contract"),
    (
        "tests/test_selected_profile_compatibility_matrix.py",
        "test.compatibility_contract",
    ),
    (
        "tests/test_selected_profile_development_record.py",
        "test.development_record",
    ),
    ("tests/test_selected_profile_fixture.py", "test.selected_verifier"),
    (
        "tests/test_selected_profile_full_generator_oracle.py",
        "test.generator_oracle_contract",
    ),
    ("tests/test_toctou_and_fault_injection.py", "test.robustness"),
    ("uv.lock", "implementation.dependency_lock"),
)

# Distribution/governance files live at the repository root. They remain an
# explicit, bounded packet surface and use the same stable no-symlink reader.
DISTRIBUTION_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("CONTRIBUTING.md", "distribution.contribution_instructions"),
    ("LICENSE", "distribution.license"),
    ("SECURITY.md", "distribution.security_contact"),
)

ROLE_PATTERN = re.compile(
    r"^(?:base|catalog|compatibility|distribution|implementation|oracle|policy|"
    r"proposition|protocol|schema|test)(?:\.[a-z0-9_]+)+$"
)
FORBIDDEN_OUTPUT_ROOTS = frozenset(
    {
        "base_pilot_runs",
        "confirmatory",
        "confirmatory_outputs",
        "confirmatory_runs",
        "development_checks",
        "pilot_runs",
        "production_pilot_runs",
        "r1",
        "r2",
        "raw_results",
        "results",
        "robustness_runs",
        "selected_profile_base_runs",
    }
)
EXPLICIT_NONCONFIRMATORY_ENGINEERING_SUBJECTS = frozenset(
    {
        "amy_verifier/confirmatory_runner.py",
        "protocol/CONFIRMATORY_RUNNER_CONTRACT_DRAFT.md",
        "tests/test_confirmatory_runner_contract.py",
    }
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_sort_key(value: str) -> bytes:
    return value.encode("utf-8")


def _validate_logical_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError(f"subject path is not a safe relative POSIX path: {value!r}")
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise ValueError(f"subject path is not canonical: {value!r}")
    lowered_parts = tuple(part.casefold() for part in logical.parts)
    forbidden = any(part in FORBIDDEN_OUTPUT_ROOTS for part in lowered_parts) or any(
        "confirmatory" in part for part in lowered_parts
    )
    if forbidden and value not in EXPLICIT_NONCONFIRMATORY_ENGINEERING_SUBJECTS:
        raise ValueError(f"confirmatory/run-output subject paths are forbidden: {value}")
    return logical


def _validate_subject_specs(
    subjects: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    normalized = tuple(subjects)
    paths: list[str] = []
    for specification in normalized:
        if not isinstance(specification, tuple) or len(specification) != 2:
            raise ValueError("each subject specification must be a (path, role) tuple")
        logical_path, role = specification
        _validate_logical_path(logical_path)
        if not isinstance(role, str) or ROLE_PATTERN.fullmatch(role) is None:
            raise ValueError(f"invalid subject role for {logical_path!r}: {role!r}")
        paths.append(logical_path)
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate subject path")
    if paths != sorted(paths, key=_path_sort_key):
        raise ValueError("subject paths must be explicitly UTF-8-bytewise sorted")
    return normalized


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_subject(study_root: Path, logical: PurePosixPath) -> bytes:
    root_stat = study_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("study root must be a real directory, not a symlink")

    candidate = study_root
    before: os.stat_result | None = None
    for index, part in enumerate(logical.parts):
        candidate = candidate / part
        try:
            observed = candidate.lstat()
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise FileNotFoundError(f"missing subject path: {logical.as_posix()}") from exc
        if stat.S_ISLNK(observed.st_mode):
            raise ValueError(f"symlink subject path is forbidden: {logical.as_posix()}")
        if index < len(logical.parts) - 1:
            if not stat.S_ISDIR(observed.st_mode):
                raise ValueError(
                    f"non-directory subject ancestor is forbidden: {logical.as_posix()}"
                )
        else:
            before = observed

    assert before is not None
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"nonregular subject path is forbidden: {logical.as_posix()}")
    if before.st_size > MAX_SUBJECT_BYTES:
        raise ValueError(
            f"subject exceeds {MAX_SUBJECT_BYTES} bytes: {logical.as_posix()}"
        )
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("O_NOFOLLOW is required for fail-closed packet construction")

    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValueError(f"subject changed before open: {logical.as_posix()}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(before):
            raise ValueError(f"subject changed before read: {logical.as_posix()}")
        chunks: list[bytes] = []
        observed_bytes = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            observed_bytes += len(chunk)
            if observed_bytes > MAX_SUBJECT_BYTES:
                raise ValueError(
                    f"subject exceeded {MAX_SUBJECT_BYTES} bytes while reading: "
                    f"{logical.as_posix()}"
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _file_identity(after) != _file_identity(opened) or observed_bytes != after.st_size:
            raise ValueError(f"subject changed while reading: {logical.as_posix()}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _reject_local_absolute_paths(raw: bytes, logical_path: str) -> None:
    """Keep host-specific filesystem coordinates out of public subjects."""
    unix_markers = (
        b"/" + b"Users" + b"/",
        b"/" + b"Volumes" + b"/",
        b"/" + b"home" + b"/",
    )
    windows_users = re.compile(rb"[A-Za-z]:\\\\Users\\\\", flags=re.IGNORECASE)
    if any(marker in raw for marker in unix_markers) or windows_users.search(raw):
        raise ValueError(
            f"subject contains a host-local absolute path: {logical_path}"
        )


def _collect_subjects(
    study_root: Path,
    subjects: Sequence[tuple[str, str]],
) -> tuple[list[dict[str, object]], dict[str, bytes]]:
    specifications = _validate_subject_specs(subjects)
    records: list[dict[str, object]] = []
    contents: dict[str, bytes] = {}
    for relative, role in specifications:
        raw = _read_subject(study_root, _validate_logical_path(relative))
        _reject_local_absolute_paths(raw, relative)
        contents[relative] = raw
        records.append(
            {
                "path": relative,
                "raw_sha256": _sha256(raw),
                "byte_length": len(raw),
                "role": role,
            }
        )
    return records, contents


def _subject_manifest(
    records: list[dict[str, object]],
    *,
    repository_distribution_files_read: bool,
) -> dict[str, object]:
    categories = sorted(
        {str(record["role"]).split(".", 1)[0] for record in records},
        key=_path_sort_key,
    )
    return {
        "schema_version": "amy.r0-human-review-subject-manifest.v1-draft",
        "status": "preparation_only_unreviewed_not_frozen",
        "gate_id": "RG-004",
        "gate_status_after_build": "open",
        "canonicalization": "RFC8785_JCS",
        "artifact_count": len(records),
        "artifact_categories": categories,
        "artifacts": records,
        "archive_contract": {
            "format": "USTAR",
            "compression": "none",
            "member_order": "UTF-8_bytewise_path_order",
            "regular_file_mode": "0644",
            "mtime": 0,
            "uid": 0,
            "gid": 0,
            "uname": "",
            "gname": "",
            "subject_manifest_member": SUBJECT_MANIFEST_NAME,
        },
        "read_boundary": {
            "explicit_subject_paths_only": True,
            "directory_discovery_used": False,
            "repository_distribution_files_read": (
                repository_distribution_files_read
            ),
            "synthetic_engineering_receipts_read": False,
            "empirical_or_confirmatory_run_outputs_read": False,
            "confirmatory_outputs_read": False,
            "confirmatory_cases_generated_or_executed": False,
            "independent_human_review_performed": False,
        },
        "claim_boundary": (
            "Packet construction identifies draft subject bytes only; it is not "
            "independent review, registration, freeze, verification evidence, or "
            "evidence of scientific truth."
        ),
    }


def _write_ustar(destination: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(destination, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(members, key=_path_sort_key):
            raw = members[name]
            info = tarfile.TarInfo(name)
            info.type = tarfile.REGTYPE
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))


def build(
    output: Path,
    *,
    study_root: Path = STUDY_ROOT,
    subjects: Sequence[tuple[str, str]] = SUBJECTS,
    repository_root: Path | None = None,
    distribution_subjects: Sequence[tuple[str, str]] = DISTRIBUTION_SUBJECTS,
) -> dict[str, object]:
    """Write exactly one canonical manifest and one deterministic USTAR packet."""

    study_root = study_root.absolute()
    repository_root = (
        repository_root.absolute()
        if repository_root is not None
        else study_root.parents[1]
    )
    output = output.absolute()
    if os.path.lexists(output):
        raise FileExistsError(f"output already exists: {output}")

    records, contents = _collect_subjects(study_root, subjects)
    distribution_records, distribution_contents = _collect_subjects(
        repository_root,
        distribution_subjects,
    )
    duplicate_paths = set(contents) & set(distribution_contents)
    if duplicate_paths:
        raise ValueError(
            "duplicate packet subject path across study and repository roots: "
            + ", ".join(sorted(duplicate_paths, key=_path_sort_key))
        )
    records.extend(distribution_records)
    records.sort(key=lambda record: _path_sort_key(str(record["path"])))
    contents.update(distribution_contents)
    manifest_raw = rfc8785.dumps(
        _subject_manifest(
            records,
            repository_distribution_files_read=bool(distribution_subjects),
        )
    )
    members = dict(contents)
    if SUBJECT_MANIFEST_NAME in members or PACKET_NAME in members:
        raise ValueError("subject path collides with a reserved packet member")
    members[SUBJECT_MANIFEST_NAME] = manifest_raw

    output.mkdir(mode=0o755)
    manifest_path = output / SUBJECT_MANIFEST_NAME
    packet_path = output / PACKET_NAME
    manifest_path.write_bytes(manifest_raw)
    _write_ustar(packet_path, members)
    packet_raw = packet_path.read_bytes()
    return {
        "status": "preparation_only_unreviewed_not_frozen",
        "independent_human_review_performed": False,
        "subject_manifest_path": str(manifest_path),
        "subject_manifest_sha256": _sha256(manifest_raw),
        "subject_manifest_byte_length": len(manifest_raw),
        "packet_path": str(packet_path),
        "packet_sha256": _sha256(packet_raw),
        "packet_byte_length": len(packet_raw),
        "artifact_count": len(records),
        "archive_member_count": len(members),
        "confirmatory_outputs_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the preparation-only deterministic RG-004 review packet."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
