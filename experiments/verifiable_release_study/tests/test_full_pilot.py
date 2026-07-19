from __future__ import annotations

import csv
import json
import tarfile
from pathlib import Path

from amy_verifier.pilot import _snapshot_tree, run_pilot


def test_full_pilot_matches_frozen_draft_expectations_and_archives_replay(tmp_path: Path) -> None:
    output = tmp_path / "pilot"
    summary = run_pilot(output)
    assert summary["case_count"] == 34
    assert summary["result_count"] == 136
    assert summary["profile_conformance_mismatches"] == 0
    assert summary["clean_failures"] == 0

    with (output / "expected_vs_observed.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert all(row["profile_conforms"] == "true" for row in rows)
    assert all(row["observed_decision"] != "ERROR" for row in rows)

    for case_id in ("PATH-HARDLINK-001", "PATH-SYMLINK-001", "PATH-NONREGULAR-001"):
        replay = tmp_path / f"replay-{case_id}"
        replay.mkdir()
        with tarfile.open(output / "archives" / f"{case_id}.tar") as archive:
            archive.extractall(replay, filter="fully_trusted")
        expected = json.loads(
            (output / "cases" / case_id / "mutation_record.json").read_text(encoding="utf-8")
        )["after"]
        assert _snapshot_tree(replay) == expected
