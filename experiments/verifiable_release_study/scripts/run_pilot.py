#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STUDY_ROOT_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT_PATH))

from amy_verifier.pilot import STUDY_ROOT, run_pilot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        STUDY_ROOT
        / "pilot_runs"
        / datetime.now(timezone.utc).strftime("pilot_%Y%m%dT%H%M%SZ")
    )
    summary = run_pilot(output)
    print(json.dumps({"output": str(output), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
