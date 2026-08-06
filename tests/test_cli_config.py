#!/usr/bin/env python3
"""Tests for the --config arg-ordering fix (2026-06-29 claims-polish review).

Before: main() called load_config() (default config.yaml) BEFORE parsing
--config, so a custom --config crashed if config.yaml was absent, and the
default was loaded twice. resolve_config() now parses first and loads the
resolved path exactly once.
"""
import os

import pytest
import yaml

import amy


def _write_cfg(path, goal="default goal"):
    path.write_text(yaml.safe_dump({"mission": {"goal": goal, "description": "d"}}), encoding="utf-8")


def test_custom_config_used_even_when_default_absent(tmp_path, monkeypatch):
    # No config.yaml in cwd — only the custom one exists.
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "config_kimi.yaml"
    _write_cfg(custom, goal="kimi goal")
    assert not (tmp_path / "config.yaml").exists()

    cfg = amy.resolve_config(["--config", "config_kimi.yaml"])
    assert cfg["mission"]["goal"] == "kimi goal"  # loaded the custom file, no crash


def test_default_config_loaded_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path / "config.yaml", goal="default goal")
    calls = {"n": 0}
    real_load = amy.load_config

    def counting_load(path="config.yaml"):
        calls["n"] += 1
        return real_load(path)

    monkeypatch.setattr(amy, "load_config", counting_load)
    cfg = amy.resolve_config([])
    assert cfg["mission"]["goal"] == "default goal"
    assert calls["n"] == 1, "config was loaded more than once"


def test_goal_override_applies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path / "config.yaml", goal="old goal")
    cfg = amy.resolve_config(["--goal", "brand new goal"])
    assert cfg["mission"]["goal"] == "brand new goal"


def test_missing_custom_config_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        amy.resolve_config(["--config", "does_not_exist.yaml"])


def test_default_config_falls_back_to_installed_data_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "installed"
    installed_config = data_root / "share" / "amy" / "config.yaml"
    installed_config.parent.mkdir(parents=True)
    _write_cfg(installed_config, goal="installed default")
    monkeypatch.setattr(
        amy.sysconfig,
        "get_path",
        lambda name: str(data_root) if name == "data" else None,
    )

    cfg = amy.resolve_config([])

    assert cfg["mission"]["goal"] == "installed default"
