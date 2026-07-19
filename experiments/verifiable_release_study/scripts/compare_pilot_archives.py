#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def compare(first: Path, second: Path) -> dict:
    first_archives = {path.name: path for path in (first / "archives").glob("*.tar")}
    second_archives = {path.name: path for path in (second / "archives").glob("*.tar")}
    names = sorted(set(first_archives) | set(second_archives))
    records = []
    for name in names:
        first_path = first_archives.get(name)
        second_path = second_archives.get(name)
        first_hash = sha256(first_path) if first_path else None
        second_hash = sha256(second_path) if second_path else None
        records.append(
            {
                "archive": name,
                "first_sha256": first_hash,
                "second_sha256": second_hash,
                "identical": first_hash is not None and first_hash == second_hash,
            }
        )
    return {
        "first_run": first.name,
        "second_run": second.name,
        "first_archive_count": len(first_archives),
        "second_archive_count": len(second_archives),
        "same_name_set": set(first_archives) == set(second_archives),
        "all_archives_identical": bool(records) and all(record["identical"] for record in records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.first.resolve(), args.second.resolve())
    raw = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0 if result["same_name_set"] and result["all_archives_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
