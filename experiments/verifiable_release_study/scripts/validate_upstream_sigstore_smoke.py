#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = STUDY_ROOT / "production_pilot_runs/github_cli_2.96.0_upstream_smoke"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    errors: list[str] = []
    ledger = json.loads((RUN_ROOT / "input_hashes.json").read_text(encoding="utf-8"))
    for entry in ledger["retained_files"]:
        path = RUN_ROOT / entry["path"]
        if not path.is_file():
            errors.append(f"missing retained file: {entry['path']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            errors.append(f"size mismatch: {entry['path']}")
        if sha256(path) != entry["sha256"]:
            errors.append(f"SHA-256 mismatch: {entry['path']}")

    result = json.loads((RUN_ROOT / "result.json").read_text(encoding="utf-8"))
    expected_subject = ledger["subject"]["sha256"]
    fixed_expectations = {
        "decision": "ACCEPT",
        "profile_id": "P2",
        "manifest_sha256": expected_subject,
        "predicate_type": "https://slsa.dev/provenance/v1",
        "trusted_root_sha256": ledger["retained_files"][3]["sha256"],
    }
    for key, expected in fixed_expectations.items():
        if result.get(key) != expected:
            errors.append(f"result field mismatch: {key}")
    certificate = result.get("certificate") or {}
    if certificate.get("sourceRepositoryURI") != "https://github.com/cli/cli":
        errors.append("unexpected certificate source repository")
    if certificate.get("sourceRepositoryDigest") != ledger["tool"]["source_commit"]:
        errors.append("unexpected certificate source digest")
    if result.get("tool", {}).get("binary_sha256") != ledger["tool"]["linux_binary_sha256"]:
        errors.append("unexpected gh binary digest")
    timestamps = result.get("verified_timestamps") or []
    if not any(
        item.get("type") == "Tlog" and item.get("uri") == "https://rekor.sigstore.dev"
        for item in timestamps
        if isinstance(item, dict)
    ):
        errors.append("public Rekor timestamp is absent")

    output = {
        "valid": not errors,
        "classification": ledger["classification"],
        "decision": result.get("decision"),
        "profile_id": result.get("profile_id"),
        "retained_file_count": len(ledger["retained_files"]),
        "errors": errors,
        "limitations": ledger["limitations"],
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
