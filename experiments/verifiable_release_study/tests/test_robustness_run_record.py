from __future__ import annotations

import importlib.util
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = STUDY_ROOT / "scripts/validate_robustness_run.py"
RECORD = STUDY_ROOT / "robustness_runs/engineering_20260713T072737Z/RESULT.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location("robustness_run_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_cross_platform_robustness_run_is_hash_valid() -> None:
    result = _load_validator().validate(RECORD)
    assert result["valid"], result["errors"]
    assert result["scheduled_case_count"] == 12
    assert result["implemented_case_count"] == 12
    assert result["environment_count"] == 2
