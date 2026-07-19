from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_DRAFT.json"
BASE_REGISTRY_PATH = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
PROBE_SCRIPT = STUDY_ROOT / "scripts/probe_filesystem_capabilities.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retained_probes_cover_every_planned_environment_and_match_hashes() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    bases = json.loads(BASE_REGISTRY_PATH.read_text(encoding="utf-8"))
    contract = registry["environment_probe_contract"]

    assert contract["script_path"] == "scripts/probe_filesystem_capabilities.py"
    assert contract["script_sha256"] == _sha256(PROBE_SCRIPT)

    planned = {entry["id"]: entry for entry in bases["planned_environments"]}
    retained = {entry["environment_id"]: entry for entry in contract["records"]}
    assert set(retained) == set(planned) == {"ENV-AUTHOR", "ENV-LINUX-PINNED"}

    for environment_id, record_contract in retained.items():
        path = STUDY_ROOT / record_contract["path"]
        assert record_contract["sha256"] == _sha256(path)
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["environment_id"] == environment_id
        assert record["network_required_by_probe"] is False
        assert record["all_required_supported"] is True
        assert record["expected_image"] == planned[environment_id].get("image")
        assert all(record["capabilities"].values())


def test_filesystem_prerequisites_are_true_only_with_all_probe_evidence() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    contract_paths = {entry["path"] for entry in registry["environment_probe_contract"]["records"]}
    prerequisites = {entry["id"]: entry for entry in registry["prerequisites"]}

    for prerequisite_id in (
        "filesystem_supports_fifo",
        "filesystem_supports_hardlink",
        "filesystem_supports_symlink",
    ):
        prerequisite = prerequisites[prerequisite_id]
        assert prerequisite["source"] == "required_environment_probes"
        assert prerequisite["draft_state"] == "TRUE"
        assert set(prerequisite["evidence_paths"]) == contract_paths


def test_probe_implementation_passes_in_current_test_environment() -> None:
    module = _load_module(PROBE_SCRIPT, "filesystem_capability_probe")
    result = module.probe("TEST-ENVIRONMENT", "1970-01-01T00:00:00Z", None)
    assert result["network_required_by_probe"] is False
    assert result["all_required_supported"] is True
    assert all(result["capabilities"].values())
