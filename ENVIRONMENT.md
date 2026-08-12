# A.M.Y Environment Layout

A.M.Y uses **two Python environments** by design. They are not interchangeable.

## 1. `.venv` — A.M.Y runtime

- **Python**: 3.13 or 3.14
- **Purpose**: Runs the A.M.Y cognitive cycle, heartbeat, memory, paper generation, tests.
- **Install**: `.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e ".[test]"`
- **Used by**: `amy.py`, scripts under `scripts/run/`, and tests under `tests/`.

## 2. `atlas/.venv_new` — Atlas worker

- **Python**: 3.13 (parts of the Atlas scientific stack do not yet support 3.14)
- **Purpose**: Runs Atlas tools (sympy, rdkit, brian2, libsbml, scipy, etc.) as subprocess workers spawned by A.M.Y.
- **Install**: `python3.13 -m venv atlas/.venv_new && atlas/.venv_new/bin/pip install -r atlas/requirements.txt`
- **Referenced by**: `core/atlas_tools.py` (ATLAS_VENV_PYTHON), `core/atlas_bridge.py`.

## 3. `atlas/.venv` — DEPRECATED

The older `atlas/.venv` is no longer referenced by A.M.Y. It is ignored by
Git; archive or remove it manually only after confirming that no external
workflow still uses it.

## Why two environments?

A.M.Y subprocess-spawns Atlas tools to keep scientific computations isolated from cognitive state. The version split is forced by ecosystem compatibility (Python 3.14 is too new for parts of the science stack).

## Quick sanity check

```bash
# A.M.Y venv runs tests:
.venv/bin/python -m pytest tests/test_atlas_misuse_guard.py -q

# Atlas venv runs tools:
atlas/.venv_new/bin/python -c "import sympy, numpy, scipy; print('OK')"
```
