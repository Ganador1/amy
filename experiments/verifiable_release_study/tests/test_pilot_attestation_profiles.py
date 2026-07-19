from __future__ import annotations

import hashlib
import json
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator

from amy_verifier import ImplementationIdentity, verify_release
from amy_verifier.fixture_crypto import (
    fixture_trust_policy,
    make_fixture_bundle,
    make_statement,
)


STUDY_ROOT = Path(__file__).resolve().parents[1]
BASE_POLICY = json.loads(
    (STUDY_ROOT / "protocol" / "TRUST_POLICY_DRAFT.json").read_text(encoding="utf-8")
)
MANIFEST_SCHEMA_PATH = STUDY_ROOT / "schemas" / "manifest.schema.json"
RESULT_SCHEMA = json.loads(
    (STUDY_ROOT / "schemas" / "verifier-result.schema.json").read_text(encoding="utf-8")
)
IDENTITY = ImplementationIdentity("0.3.1.dev0", "0" * 40, "1" * 64, False)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clean_release(root: Path) -> dict:
    sources = {
        "payload/analysis.py": (b"print('pilot')\n", "text/x-python", "analysis_code"),
        "payload/data.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/result.json": (b'{"sum":3}\n', "application/json", "analysis_output"),
    }
    payloads = []
    for relative, (raw, media_type, role) in sorted(sources.items()):
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


def _policy(root: Path) -> tuple[dict, Path]:
    policy = fixture_trust_policy(BASE_POLICY)
    path = root / "pilot-trust-policy.json"
    path.write_bytes(rfc8785.dumps(policy))
    return policy, path


def _attest(root: Path, policy: dict, *, statement: dict | bytes | None = None, **bundle_options) -> None:
    manifest_raw = (root / "MANIFEST.jcs.json").read_bytes()
    statement_value = make_statement(manifest_raw, policy) if statement is None else statement
    statement_raw = statement_value if isinstance(statement_value, bytes) else rfc8785.dumps(statement_value)
    (root / "attestation.sigstore.json").write_bytes(
        make_fixture_bundle(statement_raw, **bundle_options)
    )


def _verify(root: Path, policy_path: Path, profile: str, case_id: str) -> dict:
    result = verify_release(
        root,
        profile_id=profile,
        case_id=case_id,
        case_archive_sha256="2" * 64,
        trust_policy_path=policy_path,
        implementation=IDENTITY,
        manifest_schema_path=MANIFEST_SCHEMA_PATH,
        attestation_backend="pilot_fixture",
    )
    errors = list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result))
    assert not errors, [error.message for error in errors]
    return result


def _assert_outcome(result: dict, decision: str, reason: str) -> None:
    assert (result["decision"], result["primary_reason"]) == (decision, reason), result


def test_clean_fixture_is_accepted_by_p2_and_p3(tmp_path: Path) -> None:
    _clean_release(tmp_path)
    policy, policy_path = _policy(tmp_path)
    _attest(tmp_path, policy)

    _assert_outcome(_verify(tmp_path, policy_path, "P2", "CLEAN-001"), "ACCEPT", "OK")
    p3 = _verify(tmp_path, policy_path, "P3", "CLEAN-001")
    _assert_outcome(p3, "ACCEPT", "OK")
    assert p3["checks"]["signature_crypto"] == "PASS"
    assert p3["checks"]["payload_digests"] == "PASS"


def test_signature_only_accepts_payload_bitflip_but_p3_rejects(tmp_path: Path) -> None:
    _clean_release(tmp_path)
    policy, policy_path = _policy(tmp_path)
    _attest(tmp_path, policy)
    path = tmp_path / "payload" / "data.csv"
    changed = bytearray(path.read_bytes())
    changed[0] ^= 1
    path.write_bytes(changed)

    _assert_outcome(
        _verify(tmp_path, policy_path, "P2", "CONTENT-BITFLIP-001"), "ACCEPT", "OK"
    )
    _assert_outcome(
        _verify(tmp_path, policy_path, "P3", "CONTENT-BITFLIP-001"),
        "REJECT",
        "DIGEST_MISMATCH",
    )


def test_original_attestation_rejects_coherent_manifest_substitution(tmp_path: Path) -> None:
    manifest = _clean_release(tmp_path)
    policy, policy_path = _policy(tmp_path)
    _attest(tmp_path, policy)
    replacement = b"x,y\n9,8\n"
    (tmp_path / "payload" / "data.csv").write_bytes(replacement)
    entry = next(item for item in manifest["payloads"] if item["path"] == "payload/data.csv")
    entry["bytes"] = len(replacement)
    entry["sha256"] = _sha256(replacement)
    (tmp_path / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))

    for profile in ("P2", "P3"):
        _assert_outcome(
            _verify(tmp_path, policy_path, profile, "SUBSTITUTION-COHERENT-001"),
            "REJECT",
            "SUBJECT_MISMATCH",
        )


def test_p2_accepts_wrong_predicate_while_p3_rejects(tmp_path: Path) -> None:
    _clean_release(tmp_path)
    policy, policy_path = _policy(tmp_path)
    statement = make_statement(
        (tmp_path / "MANIFEST.jcs.json").read_bytes(),
        policy,
        predicate_type="https://example.invalid/predicate/v1",
    )
    _attest(tmp_path, policy, statement=statement)

    _assert_outcome(
        _verify(tmp_path, policy_path, "P2", "PREDICATE-WRONG-TYPE-001"), "ACCEPT", "OK"
    )
    _assert_outcome(
        _verify(tmp_path, policy_path, "P3", "PREDICATE-WRONG-TYPE-001"),
        "REJECT",
        "PREDICATE_TYPE_UNSUPPORTED",
    )


def test_cryptographic_identity_and_evidence_failures_are_distinct(tmp_path: Path) -> None:
    cases = [
        ("SIGNATURE-CORRUPT-001", {"corrupt_signature": True}, "SIGNATURE_INVALID"),
        ("TRANSPARENCY-MISSING-001", {"include_transparency": False}, "TRANSPARENCY_INVALID"),
        ("CERTIFICATE-TIME-001", {"certificate_time_valid": False}, "CERTIFICATE_TIME_INVALID"),
        ("SUBSTITUTION-UNAUTHORIZED-001", {"signer": "unauthorized"}, "SIGNER_UNAUTHORIZED"),
        ("IDENTITY-WORKFLOW-001", {"signer": "wrong_workflow"}, "BUILDER_UNAUTHORIZED"),
        ("SIGNATURE-ALGORITHM-001", {"algorithm": "ed448"}, "ALGORITHM_UNAPPROVED"),
    ]
    for index, (case_id, options, expected_reason) in enumerate(cases):
        root = tmp_path / f"case-{index}"
        _clean_release(root)
        policy, policy_path = _policy(root)
        _attest(root, policy, **options)
        for profile in ("P2", "P3"):
            _assert_outcome(
                _verify(root, policy_path, profile, case_id), "REJECT", expected_reason
            )


def test_missing_malformed_bundle_and_authenticated_statement_are_distinct(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    _clean_release(root)
    _, policy_path = _policy(root)
    for profile in ("P2", "P3"):
        _assert_outcome(
            _verify(root, policy_path, profile, "ATTESTATION-MISSING-001"),
            "REJECT",
            "ATTESTATION_MISSING",
        )

    root = tmp_path / "bad-bundle"
    _clean_release(root)
    _, policy_path = _policy(root)
    (root / "attestation.sigstore.json").write_bytes(b"{")
    for profile in ("P2", "P3"):
        _assert_outcome(
            _verify(root, policy_path, profile, "ATTESTATION-MALFORMED-001"),
            "REJECT",
            "ATTESTATION_INVALID",
        )

    root = tmp_path / "bad-statement"
    _clean_release(root)
    policy, policy_path = _policy(root)
    _attest(root, policy, statement=b"{")
    for profile in ("P2", "P3"):
        _assert_outcome(
            _verify(root, policy_path, profile, "STATEMENT-MALFORMED-001"),
            "REJECT",
            "ATTESTATION_INVALID",
        )


def test_p3_provenance_policy_rejects_source_dirty_and_material_mutations(tmp_path: Path) -> None:
    variants = [
        ({"source_revision": "e" * 40}, "SOURCE-WRONG-REVISION-001", "SOURCE_MISMATCH"),
        ({"dirty": True}, "BUILD-DIRTY-001", "DIRTY_BUILD"),
        (
            {"material_overrides": {"dependency_lock_sha256": "f" * 64}},
            "MATERIAL-LOCK-MISMATCH-001",
            "MATERIAL_MISMATCH",
        ),
    ]
    for index, (statement_options, case_id, reason) in enumerate(variants):
        root = tmp_path / f"provenance-{index}"
        _clean_release(root)
        policy, policy_path = _policy(root)
        statement = make_statement(
            (root / "MANIFEST.jcs.json").read_bytes(), policy, **statement_options
        )
        _attest(root, policy, statement=statement)
        _assert_outcome(_verify(root, policy_path, "P2", case_id), "ACCEPT", "OK")
        _assert_outcome(_verify(root, policy_path, "P3", case_id), "REJECT", reason)
