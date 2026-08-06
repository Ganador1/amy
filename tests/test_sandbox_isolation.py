#!/usr/bin/env python3
"""Hermetic tests for the sandbox isolation guarantees.

These cover the security-critical contracts of sandbox/executor.py without
needing Docker or the network:

- bash is routed through the SAME isolation gate as python (it used to return
  before the gate, running on the host even under fail-closed config);
- the hardened-subprocess and bash fallback tiers run in a throwaway cwd, so a
  relative-path write cannot clobber the repo;
- require_isolation fails CLOSED when Docker is requested but unavailable, and
  only downgrades to subprocess when require_isolation is False;
- _safety_block fails closed if the safety kernel cannot be evaluated;
- the dynamic-import escape (importlib.import_module) is now blocked statically.
"""
import sys
from pathlib import Path

import pytest
import yaml

from sandbox.executor import SandboxExecutor

ROOT = Path(__file__).resolve().parent.parent


def test_shipped_config_is_fail_closed_and_docker_image_matches_runtime():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sandbox = config["sandbox"]

    assert sandbox["use_docker"] is True
    assert sandbox["require_isolation"] is True
    assert sandbox["allow_network"] is False
    assert sandbox["allow_subprocess"] is False
    assert (ROOT / "sandbox" / "Dockerfile").read_text(
        encoding="utf-8"
    ).startswith("FROM python:3.13-slim")


# ── Throwaway-cwd containment (python + bash fallback tiers) ──────────────────

async def test_subprocess_tier_runs_in_throwaway_cwd():
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    res = await ex.execute("import os; print(os.getcwd())", language="python")
    assert res["success"], res
    assert "amy_sbx_" in res["stdout"]


async def test_subprocess_tier_relative_write_cannot_clobber_repo():
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    target = ROOT / "core" / "_pwn_marker_py.txt"
    assert not target.exists()
    await ex.execute("open('core/_pwn_marker_py.txt','w').write('x')", language="python")
    # The write either fails (no core/ in the throwaway cwd) or lands in the
    # throwaway dir — either way it must NOT appear under the real repo.
    assert not target.exists(), "sandbox python wrote into the repo's core/"


async def test_bash_tier_runs_in_throwaway_cwd():
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    res = await ex.execute("pwd", language="bash")
    assert res["success"], res
    assert "amy_sbx_" in res["stdout"]


async def test_bash_relative_write_cannot_clobber_repo():
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    target = ROOT / "core" / "_pwn_marker_bash.txt"
    assert not target.exists()
    await ex.execute("echo CLOBBERED > core/_pwn_marker_bash.txt", language="bash")
    assert not target.exists(), "sandbox bash wrote into the repo's core/"


# ── Docker fail-closed gate applies to ALL languages ─────────────────────────

@pytest.mark.parametrize("language", ["python", "bash"])
async def test_require_isolation_fails_closed_when_docker_unavailable(monkeypatch, language):
    monkeypatch.setattr(SandboxExecutor, "_docker_available", staticmethod(lambda: False))
    ex = SandboxExecutor({"use_docker": True, "require_isolation": True})
    code = "print(1)" if language == "python" else "echo hi"
    res = await ex.execute(code, language=language)
    assert res["success"] is False
    # Critically, the bash path must ALSO be refused, not run on the host.
    assert "require_isolation" in res["stderr"], res


@pytest.mark.parametrize("language", ["python", "bash"])
async def test_downgrade_to_subprocess_when_isolation_not_required(monkeypatch, language):
    monkeypatch.setattr(SandboxExecutor, "_docker_available", staticmethod(lambda: False))
    ex = SandboxExecutor({"use_docker": True, "require_isolation": False})
    code = "print('ok')" if language == "python" else "echo ok"
    res = await ex.execute(code, language=language)
    assert res["success"] is True, res
    assert "ok" in res["stdout"]


# ── Fail-closed when the safety kernel cannot be evaluated ────────────────────

async def test_safety_block_fails_closed_when_kernel_unimportable(monkeypatch):
    # Make `from core.safety_kernel import ...` raise inside _safety_block.
    monkeypatch.setitem(sys.modules, "core.safety_kernel", None)
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    res = await ex.execute("print(1)", language="python")
    assert res["success"] is False
    assert "safety kernel unavailable" in res["stderr"], res


# ── Dynamic-import escape is blocked statically (defense-in-depth) ────────────

async def test_importlib_dynamic_subprocess_import_is_blocked():
    ex = SandboxExecutor({"use_docker": False, "require_isolation": False})
    code = "import importlib; m = importlib.import_module('subprocess'); m.run(['id'])"
    res = await ex.execute(code, language="python")
    assert res["success"] is False
    assert "Blocked by safety policy" in res["stderr"], res
