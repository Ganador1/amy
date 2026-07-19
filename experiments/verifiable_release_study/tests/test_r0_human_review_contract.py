from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker


STUDY_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = STUDY_ROOT / "scripts/build_r0_review_packet.py"
PACKET_VERIFIER_PATH = STUDY_ROOT / "scripts/verify_r0_review_packet.py"
REVIEWER_POLICY_VALIDATOR_PATH = (
    STUDY_ROOT / "scripts/validate_r0_reviewer_identity_policy.py"
)
SCHEMA_PATH = STUDY_ROOT / "schemas/r0-human-review-record.schema.json"
PACKET_VERIFICATION_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/r0-review-packet-verification.schema.json"
)
REVIEWER_POLICY_PATH = (
    STUDY_ROOT / "protocol/R0_REVIEWER_IDENTITY_POLICY_TEMPLATE.json"
)
REVIEWER_POLICY_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/r0-reviewer-identity-policy.schema.json"
)
REVIEWER_POLICY_VALIDATION_SCHEMA_PATH = (
    STUDY_ROOT / "schemas/r0-reviewer-identity-policy-validation.schema.json"
)
TEMPLATE_PATH = STUDY_ROOT / "protocol/R0_HUMAN_REVIEW_RECORD_TEMPLATE.json"
CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
ORACLE_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_ORACLE_DRAFT.json"
PROPOSITIONS_PATH = STUDY_ROOT / "protocol/PROPOSITION_MATRIX_DRAFT.json"
COMPATIBILITY_PATH = (
    STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
)


def _load_builder():
    specification = importlib.util.spec_from_file_location(
        "r0_review_packet_builder", BUILDER_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_packet_verifier():
    specification = importlib.util.spec_from_file_location(
        "r0_review_packet_verifier", PACKET_VERIFIER_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_reviewer_policy_validator():
    specification = importlib.util.spec_from_file_location(
        "r0_reviewer_policy_validator", REVIEWER_POLICY_VALIDATOR_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load(SCHEMA_PATH), format_checker=FormatChecker())


def _errors(instance: dict[str, Any]) -> list[Any]:
    return sorted(
        _validator().iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )


def _submitted_record() -> dict[str, Any]:
    record = copy.deepcopy(_load(TEMPLATE_PATH))
    record["record_status"] = "submitted"
    record["independent_human_review_occurred"] = True
    record["subject_binding"] = {
        "subject_manifest_path": "R0_REVIEW_SUBJECT_MANIFEST.jcs.json",
        "subject_manifest_sha256": "a" * 64,
        "packet_path": "R0_REVIEW_PACKET.tar",
        "packet_sha256": "b" * 64,
        "hash_source": "externally_supplied_and_must_be_compared_by_consumer",
    }
    record["reviewer"] = {
        "name": "Example Independent Reviewer",
        "affiliation": "Example Research Integrity Laboratory",
        "identity": {
            "kind": "email",
            "value": "reviewer@example.invalid",
        },
        "qualification": {
            "summary": (
                "Experienced reviewer of cryptographic artifact-verification "
                "and reproducible-computing contracts."
            ),
            "relevant_experience": [
                "Independent review of fail-closed verification systems"
            ],
            "evidence_uris": [],
        },
    }
    record["declarations"] = {
        "did_not_implement_verifier": True,
        "did_not_implement_mutation_generator": True,
        "did_not_implement_analysis": True,
        "did_not_author_catalog_cases": True,
        "did_not_author_oracle_expectations": True,
        "did_not_author_propositions": True,
        "did_not_author_manuscript_skeleton": True,
        "project_author_or_investigator": False,
        "confirmatory_outcomes_accessed": False,
        "subject_write_access_during_review": False,
        "prior_development_case_outcomes_accessed": False,
        "employment_or_supervisory_conflict": False,
        "shared_funding_conflict": False,
        "financial_or_consulting_conflict": False,
        "personal_or_competing_interest": False,
        "compensation_disclosure": "No compensation received.",
        "conflict_of_interest_present": False,
        "disqualifying_conflict_present": False,
        "conflict_disclosure": "None declared.",
        "independence_statement": (
            "I did not implement the reviewed verifier, generator, or analysis; "
            "did not author the catalog, oracle expectations, propositions, or "
            "manuscript skeleton; and reviewed the identified exact subject bytes without access to "
            "confirmatory outcomes or write access to the subject files."
        ),
    }
    record["reviewed_at"] = "2026-07-13T18:30:00-04:00"
    for decision in record["catalog_case_decisions"].values():
        decision.update(decision="AGREE", rationale=None)
    for decision in record["oracle_row_decisions"].values():
        decision.update(decision="AGREE", rationale=None)
    for decision in record["proposition_decisions"].values():
        decision.update(decision="AGREE", rationale=None)
    compatibility = record["compatibility_policy_decisions"]
    for decision in compatibility["matrix_row_decisions"].values():
        decision.update(decision="AGREE", rationale=None)
    for decision in compatibility["policy_decisions"].values():
        decision.update(decision="AGREE", rationale=None)
    record["manuscript_skeleton_decision"].update(
        decision="AGREE", rationale=None
    )
    record["findings"] = []
    record["overall_decision"] = "APPROVE"
    return record


@pytest.fixture(scope="module")
def deterministic_builds(tmp_path_factory):
    builder = _load_builder()
    parent = tmp_path_factory.mktemp("r0-review-packet")
    first = builder.build(parent / "first")
    second = builder.build(parent / "second")
    return builder, first, second


def test_subject_list_is_explicit_sorted_and_covers_every_required_role() -> None:
    builder = _load_builder()
    paths = [path for path, _ in builder.SUBJECTS]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert len(paths) == len(set(paths))
    assert {
        role.split(".", 1)[0] for _, role in builder.SUBJECTS
    } == {
        "base",
        "catalog",
        "compatibility",
        "implementation",
        "oracle",
        "policy",
        "proposition",
        "protocol",
        "schema",
        "test",
    }
    assert all((STUDY_ROOT / path).is_file() for path in paths)


def test_subject_list_closes_local_python_import_dependencies() -> None:
    builder = _load_builder()
    subject_paths = {path for path, _ in builder.SUBJECTS}
    missing: list[tuple[str, str]] = []
    for relative in sorted(subject_paths):
        if not relative.endswith(".py"):
            continue
        source_path = STUDY_ROOT / relative
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level and relative.startswith("amy_verifier/"):
                    package_parts = Path(relative).parent.parts
                    retained = package_parts[: len(package_parts) - node.level + 1]
                    candidates.append(".".join((*retained, node.module)))
                else:
                    candidates.append(node.module)
            for module_name in candidates:
                expected: str | None = None
                if module_name == "amy_verifier":
                    expected = "amy_verifier/__init__.py"
                elif module_name.startswith("amy_verifier."):
                    expected = module_name.replace(".", "/") + ".py"
                elif "." not in module_name and (
                    STUDY_ROOT / "scripts" / f"{module_name}.py"
                ).is_file():
                    expected = f"scripts/{module_name}.py"
                if expected is not None and expected not in subject_paths:
                    missing.append((relative, expected))
    assert not missing, missing


def test_deterministic_rebuild_is_byte_identical(deterministic_builds) -> None:
    builder, first, second = deterministic_builds
    first_manifest = Path(first["subject_manifest_path"]).read_bytes()
    second_manifest = Path(second["subject_manifest_path"]).read_bytes()
    first_packet = Path(first["packet_path"]).read_bytes()
    second_packet = Path(second["packet_path"]).read_bytes()
    assert first_manifest == second_manifest
    assert first_packet == second_packet
    assert first["subject_manifest_sha256"] == second["subject_manifest_sha256"]
    assert first["packet_sha256"] == second["packet_sha256"]
    assert first["status"] == "preparation_only_unreviewed_not_frozen"
    assert first["independent_human_review_performed"] is False
    assert first["confirmatory_outputs_read"] is False
    assert first["archive_member_count"] == len(builder.SUBJECTS) + 1


def test_archive_members_are_exact_manifest_identities_and_normalized_ustar(
    deterministic_builds,
) -> None:
    builder, first, _ = deterministic_builds
    manifest_path = Path(first["subject_manifest_path"])
    packet_path = Path(first["packet_path"])
    manifest_raw = manifest_path.read_bytes()
    packet_raw = packet_path.read_bytes()
    manifest = json.loads(manifest_raw)

    assert manifest_raw == rfc8785.dumps(manifest)
    assert hashlib.sha256(manifest_raw).hexdigest() == first["subject_manifest_sha256"]
    assert hashlib.sha256(packet_raw).hexdigest() == first["packet_sha256"]
    assert packet_raw[257:263] == b"ustar\x00"

    expected_names = sorted(
        [builder.SUBJECT_MANIFEST_NAME, *(path for path, _ in builder.SUBJECTS)],
        key=lambda value: value.encode("utf-8"),
    )
    with tarfile.open(packet_path, mode="r:") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == expected_names
        archived: dict[str, bytes] = {}
        for member in members:
            assert member.isreg()
            assert member.mode == 0o644
            assert member.mtime == 0
            assert member.uid == 0
            assert member.gid == 0
            assert member.uname == ""
            assert member.gname == ""
            handle = archive.extractfile(member)
            assert handle is not None
            archived[member.name] = handle.read()

    assert archived[builder.SUBJECT_MANIFEST_NAME] == manifest_raw
    records = manifest["artifacts"]
    assert [record["path"] for record in records] == [
        path for path, _ in builder.SUBJECTS
    ]
    assert manifest["artifact_count"] == len(records) == len(builder.SUBJECTS)
    roles = dict(builder.SUBJECTS)
    for record in records:
        raw = archived[record["path"]]
        assert raw == (STUDY_ROOT / record["path"]).read_bytes()
        assert record["raw_sha256"] == hashlib.sha256(raw).hexdigest()
        assert record["byte_length"] == len(raw)
        assert record["role"] == roles[record["path"]]


def test_builder_rejects_missing_duplicate_symlink_nonregular_and_unsorted_paths(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"a")
    (root / "b.txt").write_bytes(b"b")
    (root / "directory").mkdir()
    os.symlink("a.txt", root / "link.txt")
    (root / "real-parent").mkdir()
    (root / "real-parent" / "nested.txt").write_bytes(b"nested")
    os.symlink("real-parent", root / "linked-parent")

    with pytest.raises(FileNotFoundError, match="missing subject path"):
        builder._collect_subjects(root, (("missing.txt", "test.fixture"),))
    with pytest.raises(ValueError, match="duplicate subject path"):
        builder._collect_subjects(
            root,
            (("a.txt", "test.fixture"), ("a.txt", "test.duplicate")),
        )
    with pytest.raises(ValueError, match="symlink subject path"):
        builder._collect_subjects(root, (("link.txt", "test.fixture"),))
    with pytest.raises(ValueError, match="symlink subject path"):
        builder._collect_subjects(
            root, (("linked-parent/nested.txt", "test.fixture"),)
        )
    with pytest.raises(ValueError, match="nonregular subject path"):
        builder._collect_subjects(root, (("directory", "test.fixture"),))
    with pytest.raises(ValueError, match="explicitly UTF-8-bytewise sorted"):
        builder._collect_subjects(
            root,
            (("b.txt", "test.fixture"), ("a.txt", "test.fixture")),
        )


def test_schema_is_draft_2020_12_and_every_declared_object_is_closed() -> None:
    schema = _load(SCHEMA_PATH)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)

    def inspect(value: Any, pointer: str = "") -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False, pointer or "/"
            for key, child in value.items():
                inspect(child, f"{pointer}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{pointer}/{index}")

    inspect(schema)

    template = _load(TEMPLATE_PATH)
    unknown_top = copy.deepcopy(template)
    unknown_top["signature"] = "embedded-signature-is-forbidden"
    assert _errors(unknown_top)
    unknown_nested = copy.deepcopy(template)
    unknown_nested["subject_binding"]["record_sha256"] = "0" * 64
    assert _errors(unknown_nested)
    assert "signature" not in schema["properties"]
    assert "sigstore_bundle" not in schema["properties"]
    assert "record_sha256" not in schema["properties"]
    assert "self_hash" not in schema["properties"]

    packet_verification_schema = _load(PACKET_VERIFICATION_SCHEMA_PATH)
    Draft202012Validator.check_schema(packet_verification_schema)
    reviewer_policy_schema = _load(REVIEWER_POLICY_SCHEMA_PATH)
    reviewer_policy_validation_schema = _load(
        REVIEWER_POLICY_VALIDATION_SCHEMA_PATH
    )
    Draft202012Validator.check_schema(reviewer_policy_schema)
    Draft202012Validator.check_schema(reviewer_policy_validation_schema)


def test_template_has_exact_current_coverage_and_validates_only_unreviewed() -> None:
    template = _load(TEMPLATE_PATH)
    catalog = _load(CATALOG_PATH)
    oracle = _load(ORACLE_PATH)
    propositions = _load(PROPOSITIONS_PATH)
    compatibility = _load(COMPATIBILITY_PATH)

    expected_catalog_keys = {case["id"] for case in catalog["cases"]}
    expected_oracle_keys = {
        f"{row['case_id']}::{row['profile_id']}" for row in oracle["rows"]
    }
    expected_proposition_keys = {
        proposition["id"] for proposition in propositions["propositions"]
    }
    expected_compatibility_keys = {
        row["unit_id"] for row in compatibility["rows"]
    }
    assert set(template["catalog_case_decisions"]) == expected_catalog_keys
    assert len(expected_catalog_keys) == 41
    assert set(template["oracle_row_decisions"]) == expected_oracle_keys
    assert len(expected_oracle_keys) == 164
    assert set(template["proposition_decisions"]) == expected_proposition_keys
    assert len(expected_proposition_keys) == 12
    assert set(
        template["compatibility_policy_decisions"]["matrix_row_decisions"]
    ) == expected_compatibility_keys
    assert len(expected_compatibility_keys) == 246
    assert len(
        template["compatibility_policy_decisions"]["policy_decisions"]
    ) == 7
    assert template["manuscript_skeleton_decision"] == {
        "decision": "NOT_REVIEWED",
        "rationale": None,
    }
    assert not _errors(template)
    assert template["record_status"] == "template_unreviewed"
    assert template["independent_human_review_occurred"] is False
    assert template["overall_decision"] == "NOT_REVIEWED"

    fake = copy.deepcopy(template)
    fake["record_status"] = "submitted"
    fake["independent_human_review_occurred"] = True
    fake["overall_decision"] = "APPROVE"
    assert _errors(fake)


def test_complete_submitted_record_validates_but_fake_approval_fails_closed() -> None:
    submitted = _submitted_record()
    assert not _errors(submitted)

    counterfactuals: list[dict[str, Any]] = []
    missing_identity = copy.deepcopy(submitted)
    del missing_identity["reviewer"]["identity"]
    counterfactuals.append(missing_identity)
    missing_qualification = copy.deepcopy(submitted)
    del missing_qualification["reviewer"]["qualification"]
    counterfactuals.append(missing_qualification)
    missing_nonimplementer = copy.deepcopy(submitted)
    del missing_nonimplementer["declarations"]["did_not_implement_verifier"]
    counterfactuals.append(missing_nonimplementer)
    missing_conflict = copy.deepcopy(submitted)
    del missing_conflict["declarations"]["conflict_disclosure"]
    counterfactuals.append(missing_conflict)
    disqualifying_conflict = copy.deepcopy(submitted)
    disqualifying_conflict["declarations"]["disqualifying_conflict_present"] = True
    counterfactuals.append(disqualifying_conflict)
    catalog_author = copy.deepcopy(submitted)
    catalog_author["declarations"]["did_not_author_catalog_cases"] = False
    counterfactuals.append(catalog_author)
    manuscript_author = copy.deepcopy(submitted)
    manuscript_author["declarations"]["did_not_author_manuscript_skeleton"] = False
    counterfactuals.append(manuscript_author)
    project_author = copy.deepcopy(submitted)
    project_author["declarations"]["project_author_or_investigator"] = True
    counterfactuals.append(project_author)
    confirmatory_access = copy.deepcopy(submitted)
    confirmatory_access["declarations"]["confirmatory_outcomes_accessed"] = True
    counterfactuals.append(confirmatory_access)
    subject_write_access = copy.deepcopy(submitted)
    subject_write_access["declarations"]["subject_write_access_during_review"] = True
    counterfactuals.append(subject_write_access)
    development_case_outcome_access = copy.deepcopy(submitted)
    development_case_outcome_access["declarations"][
        "prior_development_case_outcomes_accessed"
    ] = True
    counterfactuals.append(development_case_outcome_access)
    hidden_detailed_conflict = copy.deepcopy(submitted)
    hidden_detailed_conflict["declarations"]["employment_or_supervisory_conflict"] = True
    counterfactuals.append(hidden_detailed_conflict)
    missing_catalog_coverage = copy.deepcopy(submitted)
    missing_catalog_coverage["catalog_case_decisions"].pop(
        next(iter(missing_catalog_coverage["catalog_case_decisions"]))
    )
    counterfactuals.append(missing_catalog_coverage)
    missing_oracle_coverage = copy.deepcopy(submitted)
    missing_oracle_coverage["oracle_row_decisions"].pop(
        next(iter(missing_oracle_coverage["oracle_row_decisions"]))
    )
    counterfactuals.append(missing_oracle_coverage)
    missing_proposition_coverage = copy.deepcopy(submitted)
    missing_proposition_coverage["proposition_decisions"].pop("PR-012")
    counterfactuals.append(missing_proposition_coverage)
    missing_compatibility_coverage = copy.deepcopy(submitted)
    missing_compatibility_coverage["compatibility_policy_decisions"][
        "matrix_row_decisions"
    ].pop(
        next(
            iter(
                missing_compatibility_coverage["compatibility_policy_decisions"][
                    "matrix_row_decisions"
                ]
            )
        )
    )
    counterfactuals.append(missing_compatibility_coverage)
    missing_policy_decision = copy.deepcopy(submitted)
    del missing_policy_decision["compatibility_policy_decisions"][
        "policy_decisions"
    ]["outcome_blindness"]
    counterfactuals.append(missing_policy_decision)
    missing_manuscript_decision = copy.deepcopy(submitted)
    del missing_manuscript_decision["manuscript_skeleton_decision"]
    counterfactuals.append(missing_manuscript_decision)
    unapproved_manuscript = copy.deepcopy(submitted)
    unapproved_manuscript["manuscript_skeleton_decision"] = {
        "decision": "REQUIRES_CHANGE",
        "rationale": "The manuscript diverges from the reviewed protocol.",
    }
    counterfactuals.append(unapproved_manuscript)
    missing_external_hash = copy.deepcopy(submitted)
    missing_external_hash["subject_binding"]["packet_sha256"] = None
    counterfactuals.append(missing_external_hash)
    invalid_timestamp = copy.deepcopy(submitted)
    invalid_timestamp["reviewed_at"] = "2026-07-13"
    counterfactuals.append(invalid_timestamp)

    for counterfactual in counterfactuals:
        assert _errors(counterfactual)


def test_disagreement_and_required_change_entries_require_rationale() -> None:
    record = _submitted_record()
    key = next(iter(record["oracle_row_decisions"]))
    record["oracle_row_decisions"][key] = {
        "decision": "DISAGREE",
        "rationale": None,
    }
    record["overall_decision"] = "REQUIRES_CHANGES"
    record["findings"] = [
        {
            "id": "HRF-001",
            "scope": "ORACLE_ROW",
            "references": [key],
            "disposition": "REQUIRED_CHANGE",
            "summary": "The oracle expectation requires correction.",
            "rationale": "The stated profile contract leads to a different result.",
            "required_change": "Revise the row and rebuild a newly identified packet.",
        }
    ]
    assert _errors(record)

    record["oracle_row_decisions"][key]["rationale"] = (
        "The stated profile contract leads to a different expected decision."
    )
    assert not _errors(record)

    record["findings"][0]["rationale"] = None
    assert _errors(record)


def test_no_confirmatory_or_run_output_path_can_enter_the_packet(
    deterministic_builds, tmp_path: Path
) -> None:
    builder, first, _ = deterministic_builds
    subject_paths = {path for path, _ in builder.SUBJECTS}
    assert builder.EXPLICIT_NONCONFIRMATORY_ENGINEERING_SUBJECTS <= subject_paths
    for path, _ in builder.SUBJECTS:
        if path in builder.EXPLICIT_NONCONFIRMATORY_ENGINEERING_SUBJECTS:
            continue
        parts = [part.casefold() for part in Path(path).parts]
        assert parts[0] not in builder.FORBIDDEN_OUTPUT_ROOTS
        assert all("confirmatory" not in part for part in parts)

    manifest = json.loads(Path(first["subject_manifest_path"]).read_bytes())
    assert manifest["read_boundary"] == {
        "explicit_subject_paths_only": True,
        "directory_discovery_used": False,
        "synthetic_engineering_receipts_read": False,
        "empirical_or_confirmatory_run_outputs_read": False,
        "confirmatory_outputs_read": False,
        "confirmatory_cases_generated_or_executed": False,
        "independent_human_review_performed": False,
    }

    root = tmp_path / "root"
    (root / "confirmatory_outputs").mkdir(parents=True)
    (root / "confirmatory_outputs/result.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="confirmatory/run-output"):
        builder.build(
            tmp_path / "forbidden-output",
            study_root=root,
            subjects=(("confirmatory_outputs/result.json", "test.forbidden"),),
        )


@pytest.mark.parametrize(
    "local_path",
    [
        "/" + "Users" + "/example/private/file.json",
        "/" + "Volumes" + "/private-disk/repository/file.json",
        "/" + "home" + "/example/repository/file.json",
        "C:" + "\\\\" + "Users" + "\\\\" + "example" + "\\\\" + "file.json",
    ],
)
def test_host_local_absolute_paths_cannot_enter_public_packet(
    tmp_path: Path, local_path: str
) -> None:
    builder = _load_builder()
    root = tmp_path / "root"
    root.mkdir()
    (root / "subject.txt").write_text(local_path, encoding="utf-8")

    with pytest.raises(ValueError, match="host-local absolute path"):
        builder.build(
            tmp_path / "packet",
            study_root=root,
            subjects=(("subject.txt", "test.local_path"),),
        )


def test_packet_verifier_binds_external_hashes_and_detects_inner_tampering(
    deterministic_builds, tmp_path: Path
) -> None:
    _, first, _ = deterministic_builds
    verifier = _load_packet_verifier()
    packet_directory = Path(first["packet_path"]).parent
    result = verifier.validate(
        packet_directory,
        first["subject_manifest_sha256"],
        first["packet_sha256"],
    )
    assert result["valid"], result["errors"]
    assert result["status"] == "mechanical_integrity_valid_unreviewed"
    assert result["detached_authentication_verified"] is False
    assert result["reviewer_authorization_verified"] is False
    assert result["reviewer_competence_verified"] is False
    assert result["rg004_complete"] is False
    assert not list(
        Draft202012Validator(_load(PACKET_VERIFICATION_SCHEMA_PATH)).iter_errors(
            result
        )
    )

    template_result = verifier.validate(
        packet_directory,
        first["subject_manifest_sha256"],
        first["packet_sha256"],
        TEMPLATE_PATH,
    )
    assert template_result["valid"], template_result["errors"]
    assert template_result["review_record"] == {
        "supplied": True,
        "path": str(TEMPLATE_PATH),
        "schema_valid": True,
        "record_status": "template_unreviewed",
        "subject_binding_matches": None,
        "human_review_claimed": False,
    }

    wrong_external_hash = verifier.validate(
        packet_directory,
        "c" * 64,
        first["packet_sha256"],
    )
    assert wrong_external_hash["valid"] is False
    assert any("externally supplied" in error for error in wrong_external_hash["errors"])

    tampered_directory = tmp_path / "tampered"
    tampered_directory.mkdir()
    manifest_raw = Path(first["subject_manifest_path"]).read_bytes()
    (tampered_directory / verifier.SUBJECT_MANIFEST_NAME).write_bytes(manifest_raw)
    packet_raw = bytearray(Path(first["packet_path"]).read_bytes())
    with tarfile.open(Path(first["packet_path"]), mode="r:") as archive:
        target = next(
            member
            for member in archive.getmembers()
            if member.name != verifier.SUBJECT_MANIFEST_NAME and member.size > 0
        )
    packet_raw[target.offset_data] ^= 1
    tampered_packet = bytes(packet_raw)
    (tampered_directory / verifier.PACKET_NAME).write_bytes(tampered_packet)
    tampered_result = verifier.validate(
        tampered_directory,
        first["subject_manifest_sha256"],
        hashlib.sha256(tampered_packet).hexdigest(),
    )
    assert tampered_result["valid"] is False
    assert tampered_result["packet"]["hash_matches"] is True
    assert any("artifact SHA-256 differs" in error for error in tampered_result["errors"])


def test_reviewer_identity_policy_is_no_go_until_exact_safe_inputs_are_frozen(
    tmp_path: Path,
) -> None:
    validator = _load_reviewer_policy_validator()
    template = _load(REVIEWER_POLICY_PATH)
    policy_schema = _load(REVIEWER_POLICY_SCHEMA_PATH)
    assert not list(
        Draft202012Validator(
            policy_schema, format_checker=FormatChecker()
        ).iter_errors(template)
    )

    result = validator.validate()
    assert result["valid"], result["errors"]
    assert result["decision"] == "NO-GO"
    assert result["freeze_permitted"] is False
    assert result["authentication_execution_permitted"] is False
    assert result["selected_version_not_known_vulnerable"] is False
    assert result["rg004_complete"] is False
    assert not list(
        Draft202012Validator(
            _load(REVIEWER_POLICY_VALIDATION_SCHEMA_PATH)
        ).iter_errors(result)
    )

    assert validator.version_not_known_vulnerable("2.6.1") is False
    assert validator.version_not_known_vulnerable("2.6.2") is True
    assert validator.version_not_known_vulnerable("3.0.3") is False
    assert validator.version_not_known_vulnerable("3.0.4") is True
    assert validator.version_not_known_vulnerable("4.0.0") is False

    frozen = copy.deepcopy(template)
    frozen["status"] = "frozen_authorized_for_authentication_only"
    frozen["identity"].update(
        certificate_identity="reviewer@example.invalid",
        certificate_oidc_issuer="https://accounts.example.invalid",
        authorized_by="Example gate authority",
        authorization_record_uri="https://example.invalid/reviewer-authorization.json",
        authorization_record_sha256="a" * 64,
    )
    frozen["trusted_root"].update(
        sha256="b" * 64,
        source_uri="https://example.invalid/trusted_root.json",
        acquired_at="2026-07-13T20:00:00-04:00",
    )
    frozen["tool"].update(
        selected_version="3.0.4",
        platform="linux-amd64",
        binary_sha256="c" * 64,
        release_uri="https://github.com/sigstore/cosign/releases/tag/v3.0.4",
    )
    frozen["security_floor"]["selected_version_reviewed_against_advisory"] = True
    frozen["decision_boundary"].update(
        policy_freeze_permitted=True,
        authentication_execution_permitted=True,
    )
    frozen_path = tmp_path / "frozen-reviewer-policy.json"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    frozen_result = validator.validate(frozen_path, REVIEWER_POLICY_SCHEMA_PATH)
    assert frozen_result["valid"], frozen_result["errors"]
    assert frozen_result["decision"] == "GO-FOR-AUTHENTICATION-ONLY"
    assert frozen_result["rg004_complete"] is False

    vulnerable = copy.deepcopy(frozen)
    vulnerable["tool"]["selected_version"] = "3.0.3"
    vulnerable["tool"]["release_uri"] = (
        "https://github.com/sigstore/cosign/releases/tag/v3.0.3"
    )
    vulnerable_path = tmp_path / "vulnerable-reviewer-policy.json"
    vulnerable_path.write_text(json.dumps(vulnerable), encoding="utf-8")
    vulnerable_result = validator.validate(
        vulnerable_path, REVIEWER_POLICY_SCHEMA_PATH
    )
    assert vulnerable_result["valid"] is False
    assert vulnerable_result["authentication_execution_permitted"] is False
    assert any("known-vulnerable" in error for error in vulnerable_result["errors"])
