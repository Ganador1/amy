from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = STUDY_ROOT / "protocol/ARTIFACT_RETENTION_POLICY.json"
INDEX_PATH = STUDY_ROOT / "protocol/ARTIFACT_RETENTION_INDEX.jcs.json"
POLICY_SCHEMA_PATH = STUDY_ROOT / "schemas/artifact-retention-policy.schema.json"
INDEX_SCHEMA_PATH = STUDY_ROOT / "schemas/artifact-retention-index.schema.json"
BUILDER_PATH = STUDY_ROOT / "scripts/build_artifact_retention_index.py"
EXPECTED_ROOTS = {
    "audit",
    "pilot_runs",
    "base_pilot_runs",
    "selected_profile_base_runs",
    "production_pilot_runs",
    "robustness_runs",
    "reviews",
}
EXPECTED_STATUSES = {
    "active",
    "historical_valid",
    "historical_invalid",
    "superseded",
    "local_only",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _module():
    specification = importlib.util.spec_from_file_location(
        "artifact_retention_index_test", BUILDER_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _assert_closed_objects(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
        for child in value.values():
            _assert_closed_objects(child)
    elif isinstance(value, list):
        for child in value:
            _assert_closed_objects(child)


def _mini_policy(root: Path, *, absolute_public_path: bool = False) -> Path:
    retained_roots = [f"retained_{index}" for index in range(7)]
    artifacts: list[dict[str, Any]] = []
    for index, retained_root in enumerate(retained_roots):
        directory = root / retained_root
        directory.mkdir()
        content = b"bounded fixture\n"
        if index == 0 and absolute_public_path:
            content = b"/Users/example/private/data.json\n"
        (directory / "artifact.txt").write_bytes(content)
        artifacts.append(
            {
                "id": f"ART-FIXTURE-{index}",
                "family": "audit",
                "path": f"{retained_root}/artifact.txt",
                "kind": "file",
                "status": "active",
                "validator": {
                    "kind": "retention_only",
                    "path": "scripts/build_artifact_retention_index.py",
                    "invocation": "python scripts/build_artifact_retention_index.py --check",
                },
                "reason": "Synthetic bounded fixture used only to test retention-index controls.",
                "source_git": True,
                "public_packet": absolute_public_path and index == 0,
            }
        )
    policy = {
        "schema_version": "amy.artifact-retention-policy.v1",
        "classification": (
            "retention_and_distribution_policy_not_scientific_evidence"
        ),
        "tree_hash_algorithm": "sha256-rfc8785-member-tree-v1",
        "retained_roots": retained_roots,
        "artifacts": artifacts,
        "boundaries": {
            "status_is_scientific_validity": False,
            "tree_hash_is_authentication": False,
            "source_git_is_publication": False,
            "public_packet_is_authorization": False,
            "historical_bytes_may_be_rewritten": False,
        },
    }
    path = root / "policy.json"
    path.write_bytes(rfc8785.dumps(policy))
    return path


def test_retention_schemas_are_closed_and_valid() -> None:
    for path in (POLICY_SCHEMA_PATH, INDEX_SCHEMA_PATH):
        schema = _load(path)
        Draft202012Validator.check_schema(schema)
        _assert_closed_objects(schema)


def test_retained_index_replays_exactly() -> None:
    module = _module()
    replay = module.build_index()
    assert replay["valid"] is True
    assert replay["unindexed_paths"] == []
    assert replay["multiply_indexed_paths"] == []
    assert rfc8785.dumps(replay) == INDEX_PATH.read_bytes()


def test_every_retained_root_child_is_explicitly_indexed() -> None:
    policy = _load(POLICY_PATH)
    assert set(policy["retained_roots"]) == EXPECTED_ROOTS
    rows = policy["artifacts"]
    declared = {row["path"] for row in rows}
    assert {row["status"] for row in rows} == EXPECTED_STATUSES
    assert len(declared) == len(rows)
    assert len({row["id"] for row in rows}) == len(rows)

    for root_name in EXPECTED_ROOTS:
        for child in (STUDY_ROOT / root_name).iterdir():
            assert child.name != ".DS_Store"
            assert f"{root_name}/{child.name}" in declared


def test_unindexed_retained_file_fails_closed(tmp_path: Path) -> None:
    module = _module()
    policy_path = _mini_policy(tmp_path)
    surprise = tmp_path / "retained_0/surprise.txt"
    surprise.write_text("not declared\n", encoding="utf-8")
    result = module.build_index(
        study_root=tmp_path,
        policy_path=policy_path,
        policy_schema_path=POLICY_SCHEMA_PATH,
        index_schema_path=INDEX_SCHEMA_PATH,
    )
    assert result["valid"] is False
    assert result["unindexed_paths"] == ["retained_0/surprise.txt"]
    assert any("not indexed" in error for error in result["errors"])


def test_absolute_path_forbids_public_packet(tmp_path: Path) -> None:
    module = _module()
    policy_path = _mini_policy(tmp_path, absolute_public_path=True)
    result = module.build_index(
        study_root=tmp_path,
        policy_path=policy_path,
        policy_schema_path=POLICY_SCHEMA_PATH,
        index_schema_path=INDEX_SCHEMA_PATH,
    )
    row = next(item for item in result["artifacts"] if item["id"] == "ART-FIXTURE-0")
    assert row["absolute_path_count"] == 1
    assert row["absolute_path_findings"] == [
        {"member_path": ".", "syntax": "posix"}
    ]
    assert row["absolute_path_findings_redacted"] is False
    assert result["valid"] is False
    assert any(
        "public_packet=true is forbidden" in error for error in result["errors"]
    )


def test_tree_digest_ignores_mtime_but_binds_bytes_and_symlink_target(
    tmp_path: Path,
) -> None:
    module = _module()
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    payload = artifact / "payload.txt"
    payload.write_text("alpha\n", encoding="utf-8")
    link = artifact / "link"
    link.symlink_to("payload.txt")

    first = module._artifact_tree(artifact, "directory")
    os.utime(payload, (1_000_000_000, 1_000_000_000))
    second = module._artifact_tree(artifact, "directory")
    assert first["tree_sha256"] == second["tree_sha256"]

    payload.write_text("beta\n", encoding="utf-8")
    third = module._artifact_tree(artifact, "directory")
    assert third["tree_sha256"] != second["tree_sha256"]

    link.unlink()
    link.symlink_to("other.txt")
    fourth = module._artifact_tree(artifact, "directory")
    assert fourth["tree_sha256"] != third["tree_sha256"]


def test_non_git_filesystem_member_blocks_source_git(tmp_path: Path) -> None:
    module = _module()
    policy_path = _mini_policy(tmp_path)
    policy = _load(policy_path)
    policy["artifacts"][0]["path"] = "retained_0"
    policy["artifacts"][0]["kind"] = "directory"
    policy_path.write_bytes(rfc8785.dumps(policy))
    target = tmp_path / "retained_0/artifact.txt"
    target.unlink()
    os.mkfifo(target)
    result = module.build_index(
        study_root=tmp_path,
        policy_path=policy_path,
        policy_schema_path=POLICY_SCHEMA_PATH,
        index_schema_path=INDEX_SCHEMA_PATH,
    )
    row = next(item for item in result["artifacts"] if item["id"] == "ART-FIXTURE-0")
    assert row["non_git_member_count"] == 1
    assert result["valid"] is False
    assert any("cannot be represented by Git" in error for error in result["errors"])


def test_current_policy_publishes_no_unreviewed_artifact() -> None:
    index = _load(INDEX_PATH)
    assert index["summary"]["public_packet_count"] == 0
    assert all(row["public_packet"] is False for row in index["artifacts"])
    local_rows = [row for row in index["artifacts"] if row["source_git"] is False]
    assert local_rows
    assert all(row["absolute_path_findings_redacted"] is True for row in local_rows)
    assert all(row["absolute_path_findings"] == [] for row in local_rows)
    assert index["boundaries"] == {
        "scientific_validity_established": False,
        "authentication_established": False,
        "authorization_established": False,
        "historical_bytes_rewritten": False,
        "absolute_paths_block_public_packet": True,
    }


def test_local_commitment_replays_without_local_custody_and_detects_drift(
    tmp_path: Path,
) -> None:
    module = _module()
    policy_path = _mini_policy(tmp_path)
    policy = _load(policy_path)
    row = policy["artifacts"][0]
    artifact_path = tmp_path / row["path"]
    observed = module._artifact_tree(artifact_path, row["kind"])
    row["source_git"] = False
    row["local_commitment"] = {
        "tree_sha256": observed["tree_sha256"],
        "member_count": observed["member_count"],
        "byte_count": observed["byte_count"],
        "non_git_member_count": observed["non_git_member_count"],
        "absolute_path_count": len(observed["absolute_path_findings"]),
    }
    policy_path.write_bytes(rfc8785.dumps(policy))

    artifact_path.unlink()
    replay = module.build_index(
        study_root=tmp_path,
        policy_path=policy_path,
        policy_schema_path=POLICY_SCHEMA_PATH,
        index_schema_path=INDEX_SCHEMA_PATH,
    )
    replay_row = next(
        item for item in replay["artifacts"] if item["id"] == "ART-FIXTURE-0"
    )
    assert replay["valid"] is True
    assert replay_row["tree_sha256"] == observed["tree_sha256"]
    assert replay_row["absolute_path_findings_redacted"] is True

    artifact_path.write_text("different local bytes\n", encoding="utf-8")
    drift = module.build_index(
        study_root=tmp_path,
        policy_path=policy_path,
        policy_schema_path=POLICY_SCHEMA_PATH,
        index_schema_path=INDEX_SCHEMA_PATH,
    )
    assert drift["valid"] is False
    assert any("local bytes differ" in error for error in drift["errors"])
