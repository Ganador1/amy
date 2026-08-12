#!/usr/bin/env python3
"""Build the deterministic, outcome-unread selected-profile draft oracle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.selected_profile_oracle import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_RESULT_SCHEMA_PATH,
    build_selected_profile_oracle,
)


DEFAULT_OUTPUT = DEFAULT_CATALOG_PATH.parent / "SELECTED_PROFILE_ORACLE_DRAFT.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--result-schema", type=Path, default=DEFAULT_RESULT_SCHEMA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    oracle = build_selected_profile_oracle(
        args.catalog.resolve(), args.result_schema.resolve()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
