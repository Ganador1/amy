from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator

from amy_verifier import ImplementationIdentity, verify_release
from amy_verifier import json_tools, manifest as manifest_module, path_policy as path_policy_module
import amy_verifier.verifier as verifier_module
from amy_verifier.fixture_crypto import fixture_trust_policy
from amy_verifier.github_attestation import GitHubGateToolError, _run
from amy_verifier.model import VerificationReject


STUDY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = STUDY_ROOT / "protocol/TRUST_POLICY_DRAFT.json"
SCHEMA_PATH = STUDY_ROOT / "schemas/manifest.schema.json"
RESULT_SCHEMA = json.loads(
    (STUDY_ROOT / "schemas/verifier-result.schema.json").read_text(encoding="utf-8")
)
IDENTITY = ImplementationIdentity("0.3.1.dev0", "0" * 40, "1" * 64, False)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clean_release(root: Path) -> None:
    files = {
        "payload/analysis.py": (b"print('pilot')\n", "text/x-python", "analysis_code"),
        "payload/data.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/nested/result.json": (
            b'{"sum":3}\n',
            "application/json",
            "analysis_output",
        ),
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
        "release": {"id": "race-fixture", "version": "0.1.0", "kind": "benchmark_case"},
        "payloads": payloads,
    }
    (root / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))


def _verify(
    root: Path,
    *,
    policy_path: Path = POLICY_PATH,
    schema_path: Path = SCHEMA_PATH,
) -> dict:
    result = verify_release(
        root,
        profile_id="P1",
        case_id="ROBUSTNESS-TEST-001",
        case_archive_sha256="2" * 64,
        trust_policy_path=policy_path,
        implementation=IDENTITY,
        manifest_schema_path=schema_path,
    )
    errors = list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result))
    assert not errors, [error.message for error in errors]
    return result


def test_swap_to_symlink_between_lstat_and_open_is_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "input.json"
    replacement = tmp_path / "replacement.json"
    target.write_bytes(b"{}")
    replacement.write_bytes(b"{}")
    real_open = json_tools.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(replacement.name)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(json_tools.os, "open", racing_open)
    with pytest.raises(VerificationReject) as error:
        json_tools.bounded_regular_file_read(target, 1024, check="bounded_input")
    assert error.value.reason == "INPUT_CHANGED"


def _assert_named_input_swap_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    target = tmp_path / name
    replacement = tmp_path / f"replacement-{name}"
    target.write_bytes(b"{}")
    replacement.write_bytes(b"{}")
    real_open = json_tools.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(replacement.name)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(json_tools.os, "open", racing_open)
    with pytest.raises(VerificationReject) as error:
        json_tools.bounded_regular_file_read(target, 1024, check="bounded_input")
    assert error.value.reason == "INPUT_CHANGED"


def test_attestation_bundle_swap_is_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_named_input_swap_is_rejected(
        tmp_path, monkeypatch, "attestation.sigstore.json"
    )


def test_trusted_root_swap_is_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_named_input_swap_is_rejected(tmp_path, monkeypatch, "trusted_root.jsonl")


def test_growth_during_bounded_read_is_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "growing.bin"
    target.write_bytes(b"a" * (2 * 1024 * 1024))
    real_read = json_tools.os.read
    injected = False

    def racing_read(descriptor: int, amount: int) -> bytes:
        nonlocal injected
        chunk = real_read(descriptor, amount)
        if chunk and not injected:
            injected = True
            with target.open("ab") as handle:
                handle.write(b"b")
                handle.flush()
        return chunk

    monkeypatch.setattr(json_tools.os, "read", racing_read)
    with pytest.raises(VerificationReject) as error:
        json_tools.bounded_regular_file_read(
            target, 4 * 1024 * 1024, check="bounded_input"
        )
    assert error.value.reason == "INPUT_CHANGED"


def test_final_rescan_rejects_file_added_after_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_release(tmp_path)
    real_hash = manifest_module.hash_payload

    def hash_then_add(*args, **kwargs):
        result = real_hash(*args, **kwargs)
        if args[1] == "payload/nested/result.json":
            (tmp_path / "payload/late.txt").write_bytes(b"late")
        return result

    monkeypatch.setattr(manifest_module, "hash_payload", hash_then_add)
    result = _verify(tmp_path)
    assert (result["decision"], result["primary_reason"]) == (
        "REJECT",
        "INPUT_CHANGED",
    )


def test_final_rescan_rejects_payload_changed_after_its_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_release(tmp_path)
    real_hash = manifest_module.hash_payload

    def hash_then_mutate(*args, **kwargs):
        result = real_hash(*args, **kwargs)
        if args[1] == "payload/nested/result.json":
            (tmp_path / "payload/analysis.py").write_bytes(b"print('evil!')\n")
        return result

    monkeypatch.setattr(manifest_module, "hash_payload", hash_then_mutate)
    result = _verify(tmp_path)
    assert (result["decision"], result["primary_reason"]) == (
        "REJECT",
        "INPUT_CHANGED",
    )


def test_injected_hash_io_failure_maps_to_error_not_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_release(tmp_path)

    def fail_hash(*args, **kwargs):
        raise OSError("injected read failure")

    monkeypatch.setattr(manifest_module, "hash_payload", fail_hash)
    result = _verify(tmp_path)
    assert (result["decision"], result["primary_reason"]) == (
        "ERROR",
        "INTERNAL_ERROR",
    )


def test_intermediate_directory_swap_is_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_release(tmp_path)
    real_open = path_policy_module.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "nested" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            nested = tmp_path / "payload/nested"
            parked = tmp_path / "payload/nested-original"
            nested.rename(parked)
            nested.symlink_to(parked.name, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(path_policy_module.os, "open", racing_open)
    result = _verify(tmp_path)
    assert (result["decision"], result["primary_reason"]) == (
        "REJECT",
        "INPUT_CHANGED",
    )


def test_injected_crypto_backend_failure_maps_to_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_release(tmp_path)
    base_policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    policy = fixture_trust_policy(base_policy)
    policy_path = tmp_path / "fixture-policy.json"
    policy_path.write_bytes(rfc8785.dumps(policy))
    (tmp_path / "attestation.sigstore.json").write_bytes(b"{}")

    def fail_crypto(*args, **kwargs):
        raise RuntimeError("injected cryptographic backend failure")

    monkeypatch.setattr(verifier_module, "verify_pilot_attestation", fail_crypto)
    result = verify_release(
        tmp_path,
        profile_id="P2",
        case_id="ROBUSTNESS-CRYPTO-001",
        case_archive_sha256="2" * 64,
        trust_policy_path=policy_path,
        implementation=IDENTITY,
        manifest_schema_path=SCHEMA_PATH,
        attestation_backend="pilot_fixture",
    )
    errors = list(Draft202012Validator(RESULT_SCHEMA).iter_errors(result))
    assert not errors, [error.message for error in errors]
    assert (result["decision"], result["primary_reason"]) == (
        "ERROR",
        "INTERNAL_ERROR",
    )


def test_github_cli_timeout_is_tool_error_not_policy_rejection() -> None:
    def timeout_runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    with pytest.raises(GitHubGateToolError, match="exceeded"):
        _run(timeout_runner, ("gh", "attestation", "verify"), timeout=1, env={})


def test_missing_trust_policy_produces_schema_valid_error_record(tmp_path: Path) -> None:
    _clean_release(tmp_path)
    result = _verify(tmp_path, policy_path=tmp_path / "missing-policy.json")
    assert (result["decision"], result["primary_reason"]) == (
        "ERROR",
        "INTERNAL_ERROR",
    )
    assert result["input"]["trust_policy_sha256"] is None


def test_missing_manifest_schema_produces_schema_valid_error_record(tmp_path: Path) -> None:
    _clean_release(tmp_path)
    result = _verify(tmp_path, schema_path=tmp_path / "missing-schema.json")
    assert (result["decision"], result["primary_reason"]) == (
        "ERROR",
        "INTERNAL_ERROR",
    )
    assert result["input"]["trust_policy_sha256"] == _sha256(POLICY_PATH.read_bytes())
