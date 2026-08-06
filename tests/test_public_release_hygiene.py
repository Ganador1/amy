#!/usr/bin/env python3
"""Release hygiene tests for the public repository surface."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_URL = "https://github.com/Ganador1/A.M.Y"


def _load_secret_hygiene_module():
    module_path = ROOT / "scripts" / "diagnostics" / "verify_secret_hygiene.py"
    spec = importlib.util.spec_from_file_location("verify_secret_hygiene", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return [
        line
        for line in proc.stdout.splitlines()
        if line and (ROOT / line).exists()
    ]


def test_public_metadata_points_to_current_repository_and_license():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["urls"] == {
        "Homepage": REPOSITORY_URL,
        "Documentation": f"{REPOSITORY_URL}/blob/main/README.md",
        "Repository": REPOSITORY_URL,
    }

    public_readme = (ROOT / "README_PUBLIC.md").read_text(encoding="utf-8")
    assert f"git clone {REPOSITORY_URL}.git" in public_readme
    assert "Apache-2.0" in public_readme
    assert "MIT" not in public_readme
    assert "tuusuario" not in public_readme
    assert "Pre-release" not in public_readme
    assert "v0.9.0" not in public_readme
    assert "84+" not in public_readme
    assert "100+" in public_readme
    assert "94 herramientas" not in public_readme


def test_public_readme_does_not_link_missing_repository_docs():
    public_readme = (ROOT / "README_PUBLIC.md").read_text(encoding="utf-8")
    missing = []
    for target in re.findall(r"\]\(([^)]+\.md)\)", public_readme):
        if target.startswith(("http://", "https://")):
            continue
        if not (ROOT / target).exists():
            missing.append(target)
    assert missing == []


def test_public_entrypoint_titles_are_project_name_only():
    assert (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0] == "# A.M.Y"
    assert (ROOT / "README_PUBLIC.md").read_text(encoding="utf-8").splitlines()[0] == "# A.M.Y"


def test_secret_hygiene_scans_repository_root_and_no_live_kubernetes_secret_is_tracked():
    verifier = _load_secret_hygiene_module()
    assert verifier.ROOT == ROOT

    tracked_manifests = [
        Path(path)
        for path in _tracked_files()
        if path.startswith("atlas/kubernetes/") and path.endswith((".yml", ".yaml"))
    ]
    live_secret_manifests = []
    for rel_path in tracked_manifests:
        if ".example." in rel_path.name:
            continue
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        if re.search(r"(?m)^kind:\s*Secret\s*$", text):
            live_secret_manifests.append(rel_path.as_posix())

    assert live_secret_manifests == []
    assert (ROOT / "atlas" / "kubernetes" / "secret.example.yml").exists()


def test_public_experiment_papers_do_not_publish_known_invalid_outputs():
    bad_patterns = (
        "Unknown operation",
        "zero tool failures",
        "output SHA-256: unavailable",
        "0.000 g/mol",
    )
    offenders = []
    for paper in sorted((ROOT / "experiments" / "ab_test").glob("**/papers/*.md")):
        text = paper.read_text(encoding="utf-8")
        for pattern in bad_patterns:
            if pattern in text:
                offenders.append(f"{paper.relative_to(ROOT)}: {pattern}")

    assert offenders == []


def test_release_hygiene_workflow_runs_public_checks():
    workflow = ROOT / ".github" / "workflows" / "release-hygiene.yml"
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    assert "tests/test_public_release_hygiene.py" in text
    assert "scripts/diagnostics/verify_secret_hygiene.py" in text


def test_public_docs_do_not_carry_assistant_or_model_brand_markers():
    forbidden = (
        "".join(chr(code) for code in (99, 111, 100, 101, 120)),
        "".join(chr(code) for code in (103, 112, 116)),
    )
    public_docs = (
        "README.md",
        "README_PUBLIC.md",
        "ATLAS_TOOL_GUIDE.md",
        "RELEASE_CHECKLIST.md",
        "pyproject.toml",
    )
    offenders = []
    for rel_path in public_docs:
        text = (ROOT / rel_path).read_text(encoding="utf-8").lower()
        for marker in forbidden:
            if marker in text:
                offenders.append(rel_path)
                break

    assert offenders == []
