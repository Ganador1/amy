from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator

from amy_verifier import ImplementationIdentity, verify_release


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = STUDY_ROOT / "protocol" / "TRUST_POLICY_DRAFT.json"
MANIFEST_SCHEMA_PATH = STUDY_ROOT / "schemas" / "manifest.schema.json"
RESULT_SCHEMA = json.loads(
    (STUDY_ROOT / "schemas" / "verifier-result.schema.json").read_text(encoding="utf-8")
)
IDENTITY = ImplementationIdentity(
    version="0.3.1.dev0",
    git_commit="0" * 40,
    source_archive_sha256="1" * 64,
    dirty=False,
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_clean_release(root: Path) -> dict:
    files = {
        "payload/analysis.py": (b"print('pilot')\n", "text/x-python", "analysis_code"),
        "payload/data.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/result.json": (b'{"sum":3}\n', "application/json", "analysis_output"),
    }
    payloads = []
    for relative, (raw, media_type, role) in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        payloads.append(
            {
                "path": relative,
                "bytes": len(raw),
                "sha256": _sha256(raw),
                "media_type": media_type,
                "role": role,
            }
        )
    manifest = {
        "schema_version": "0.1.0-draft",
        "release": {"id": "pilot-clean", "version": "0.1.0", "kind": "benchmark_case"},
        "payloads": payloads,
    }
    (root / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))
    return manifest


def _verify(root: Path, profile: str, case_id: str = "CLEAN-001") -> dict:
    result = verify_release(
        root,
        profile_id=profile,
        case_id=case_id,
        case_archive_sha256="2" * 64,
        trust_policy_path=POLICY_PATH,
        implementation=IDENTITY,
        manifest_schema_path=MANIFEST_SCHEMA_PATH,
    )
    errors = list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result))
    assert not errors, [error.message for error in errors]
    return result


def test_clean_release_is_accepted_by_p0_and_p1(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    assert _verify(tmp_path, "P0")["decision"] == "ACCEPT"
    p1 = _verify(tmp_path, "P1")
    assert p1["decision"] == "ACCEPT"
    assert p1["checks"]["payload_digests"] == "PASS"
    assert p1["checks"]["signature_crypto"] == "NOT_REQUIRED"


def test_bitflip_is_invisible_to_p0_and_rejected_by_p1(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    payload = tmp_path / "payload" / "data.csv"
    changed = bytearray(payload.read_bytes())
    changed[-1] ^= 1
    payload.write_bytes(changed)

    assert _verify(tmp_path, "P0", "CONTENT-BITFLIP-001")["decision"] == "ACCEPT"
    p1 = _verify(tmp_path, "P1", "CONTENT-BITFLIP-001")
    assert (p1["decision"], p1["primary_reason"]) == ("REJECT", "DIGEST_MISMATCH")


def test_coherent_unsigned_substitution_is_accepted_by_p1(tmp_path: Path) -> None:
    manifest = _write_clean_release(tmp_path)
    path = tmp_path / "payload" / "data.csv"
    replacement = b"x,y\n9,8\n"
    path.write_bytes(replacement)
    entry = next(item for item in manifest["payloads"] if item["path"] == "payload/data.csv")
    entry["bytes"] = len(replacement)
    entry["sha256"] = _sha256(replacement)
    (tmp_path / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))

    p1 = _verify(tmp_path, "P1", "SUBSTITUTION-COHERENT-001")
    assert (p1["decision"], p1["primary_reason"]) == ("ACCEPT", "OK")


def test_p0_duplicate_key_behavior_is_explicit(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    original = (tmp_path / "MANIFEST.jcs.json").read_bytes()
    duplicate = original.replace(
        b'{"payloads":',
        b'{"schema_version":"0.1.0-draft","payloads":',
        1,
    )
    (tmp_path / "MANIFEST.jcs.json").write_bytes(duplicate)

    assert _verify(tmp_path, "P0", "MANIFEST-DUPLICATE-KEY-001")["decision"] == "ACCEPT"
    p1 = _verify(tmp_path, "P1", "MANIFEST-DUPLICATE-KEY-001")
    assert (p1["decision"], p1["primary_reason"]) == ("REJECT", "DUPLICATE_JSON_KEY")


def test_noncanonical_manifest_is_rejected_only_by_p1(tmp_path: Path) -> None:
    manifest = _write_clean_release(tmp_path)
    (tmp_path / "MANIFEST.jcs.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert _verify(tmp_path, "P0", "MANIFEST-NONCANONICAL-001")["decision"] == "ACCEPT"
    p1 = _verify(tmp_path, "P1", "MANIFEST-NONCANONICAL-001")
    assert (p1["decision"], p1["primary_reason"]) == (
        "REJECT",
        "MANIFEST_NONCANONICAL",
    )


def test_missing_and_extra_inputs_fail_closed(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    (tmp_path / "MANIFEST.jcs.json").unlink()
    for profile in ("P0", "P1"):
        result = _verify(tmp_path, profile, "MANIFEST-MISSING-001")
        assert (result["decision"], result["primary_reason"]) == (
            "REJECT",
            "INPUT_MISSING",
        )

    _write_clean_release(tmp_path)
    (tmp_path / "payload" / "extra.txt").write_text("extra", encoding="utf-8")
    p1 = _verify(tmp_path, "P1", "INVENTORY-EXTRA-001")
    assert (p1["decision"], p1["primary_reason"]) == ("REJECT", "UNEXPECTED_FILE")


def test_symlink_and_hardlink_are_rejected_before_hashing(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    target = tmp_path / "payload" / "data.csv"
    target.unlink()
    target.symlink_to(tmp_path / "outside.csv")
    p1 = _verify(tmp_path, "P1", "PATH-SYMLINK-001")
    assert (p1["decision"], p1["primary_reason"]) == ("REJECT", "SYMLINK_FORBIDDEN")

    root = tmp_path / "hardlink-case"
    _write_clean_release(root)
    listed = root / "payload" / "data.csv"
    raw = listed.read_bytes()
    listed.unlink()
    backing = root / "backing.csv"
    backing.write_bytes(raw)
    os.link(backing, listed)
    p1 = _verify(root, "P1", "PATH-HARDLINK-001")
    assert (p1["decision"], p1["primary_reason"]) == (
        "REJECT",
        "HARDLINK_FORBIDDEN",
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_fifo_is_rejected_without_opening(tmp_path: Path) -> None:
    _write_clean_release(tmp_path)
    path = tmp_path / "payload" / "data.csv"
    path.unlink()
    os.mkfifo(path)
    p1 = _verify(tmp_path, "P1", "PATH-NONREGULAR-001")
    assert (p1["decision"], p1["primary_reason"]) == ("REJECT", "NONREGULAR_FILE")
