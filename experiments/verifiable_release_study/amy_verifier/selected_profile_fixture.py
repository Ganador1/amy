"""Controlled S1 fixture for the selected production-profile semantics.

The cryptographic envelope is the deterministic public pilot PKI. It is not a
Sigstore implementation. The authenticated Statement and manifest, however,
use the selected default-provenance-plus-manifest-metadata contract so the S1
oracle can migrate without changing the retained v0.3 pilot artifacts.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785

from .attestation import verify_pilot_attestation
from .base_corpus import render_recipe
from .fixture_crypto import (
    AUTHORIZED_SAN,
    PAYLOAD_TYPE,
    fixture_trust_policy,
    make_fixture_bundle,
)
from .github_attestation import GitHubGateRejected, _enforce_p3
from .json_tools import bounded_regular_file_read, parse_json_bytes
from .manifest import load_schema, parse_p0_manifest, validate_p1_manifest
from .model import PROFILE_CHECKS, VerificationReject, initial_check_states
from .path_policy import observe_payload_tree


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERLAY_PATH = STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def render_selected_fixture_payload(specification: dict[str, Any]) -> bytes:
    """Render only the two explicit, deterministic selected-profile recipes."""

    if "utf8_text" in specification:
        text = specification["utf8_text"]
        if not isinstance(text, str):
            raise RuntimeError("selected fixture utf8_text is not a string")
        return text.encode("utf-8")

    recipe = specification.get("recipe")
    if not isinstance(recipe, dict) or recipe.get("type") != "ustar_single_utf8_file_v1":
        raise RuntimeError("unsupported selected fixture payload recipe")
    member_name = recipe.get("member_path")
    member_text = recipe.get("utf8_text")
    if not isinstance(member_name, str) or not isinstance(member_text, str):
        raise RuntimeError("USTAR fixture recipe requires string member_path/utf8_text")
    logical = PurePosixPath(member_name)
    if (
        not member_name
        or logical.is_absolute()
        or any(part in {"", ".", ".."} for part in logical.parts)
        or "\\" in member_name
        or "\x00" in member_name
    ):
        raise RuntimeError("unsafe USTAR fixture member path")
    raw = member_text.encode("utf-8")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo(member_name)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.mode = 0o644
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def _strict_json(path: Path, *, max_bytes: int = 1024 * 1024) -> tuple[dict[str, Any], bytes]:
    raw = bounded_regular_file_read(path, max_bytes, check="bounded_input")
    value = parse_json_bytes(
        raw,
        max_depth=64,
        reject_duplicate_keys=True,
        failure_check="bounded_input",
        invalid_reason="JSON_INVALID",
        duplicate_reason="DUPLICATE_JSON_KEY",
    )
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON contract is not an object: {path}")
    return value, raw


def _assert_contract_hash(relative: str, expected: str) -> None:
    path = STUDY_ROOT / relative
    if _sha256(path.read_bytes()) != expected:
        raise RuntimeError(f"selected-fixture contract hash differs: {relative}")


def selected_fixture_policy(
    overlay_path: Path = DEFAULT_OVERLAY_PATH,
) -> dict[str, Any]:
    overlay, _ = _strict_json(overlay_path)
    extension = overlay.get("extends") or {}
    base_relative = extension.get("path")
    if not isinstance(base_relative, str):
        raise RuntimeError("selected-fixture overlay has no base-policy path")
    base_path = STUDY_ROOT / base_relative
    base, base_raw = _strict_json(base_path)
    if _sha256(base_raw) != extension.get("sha256"):
        raise RuntimeError("selected-fixture base-policy hash differs")

    contracts = overlay.get("contracts") or {}
    for path_key, hash_key in (
        ("manifest_schema_path", "manifest_schema_sha256"),
        ("production_reason_extension_path", "production_reason_extension_sha256"),
    ):
        relative = contracts.get(path_key)
        expected = contracts.get(hash_key)
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RuntimeError(f"selected-fixture overlay lacks {path_key}/{hash_key}")
        _assert_contract_hash(relative, expected)

    policy = copy.deepcopy(base)
    policy["status"] = overlay["status"]
    policy["fixture_overlay"] = {
        "schema_version": overlay["schema_version"],
        "selected_profile": overlay["selected_profile"],
        "cryptographic_boundary": overlay["cryptographic_boundary"],
        "forbidden_claims": overlay["forbidden_claims"],
    }
    policy["identity"].update(copy.deepcopy(overlay["identity"]))
    policy["statement"]["payload_type"] = PAYLOAD_TYPE
    policy["bundle"] = {
        "allowed_media_types": [],
        "schema_or_tool_version": "",
        "public_transparency_required": True,
        "accepted_log_ids": [],
        "inclusion_proof_required": True,
        "signed_entry_timestamp_or_rfc3161_required": True,
        "offline_verification_material_archived": True,
    }
    policy["algorithms"] = {
        "artifact_digest": ["sha256"],
        "approved_signature_algorithms": [],
        "explicit_downgrade_rejection": True,
    }

    provenance_overlay = overlay["provenance"]
    identity_overlay = overlay["identity"]
    payload_fixtures = overlay["payload_fixtures"]
    source_snapshot = payload_fixtures["source_snapshot"]
    dependency_lock = payload_fixtures["dependency_lock"]
    if source_snapshot["path"] == dependency_lock["path"]:
        raise RuntimeError("selected fixture payload paths collide")
    for fixture_name, fixture in payload_fixtures.items():
        raw = render_selected_fixture_payload(fixture)
        if len(raw) != fixture.get("bytes") or _sha256(raw) != fixture.get("sha256"):
            raise RuntimeError(
                f"selected fixture payload declaration differs from recipe: {fixture_name}"
            )
    repository = identity_overlay["repository_uri"]
    source_ref = provenance_overlay["source_ref"]
    selected_provenance = {
        "build_type": "https://actions.github.io/buildtypes/workflow/v1",
        "source_repository_uri": repository,
        "source_revision": provenance_overlay["source_revision"],
        "source_ref": source_ref,
        "workflow_path": provenance_overlay["workflow_path"],
        "builder_id": identity_overlay["certificate_identity"],
        "resolved_source_dependency_uri": f"git+{repository}@{source_ref}",
        "manifest_assertions": {
            "source": {
                "repository_uri": repository,
                "revision": provenance_overlay["source_revision"],
                "ref": source_ref,
                "git_object_format": "sha1",
                "tree": provenance_overlay["source_tree"],
                "dirty": False,
                "snapshot": {
                    "path": source_snapshot["path"],
                    "sha256": source_snapshot["sha256"],
                    "format": source_snapshot["media_type"],
                    "assurance": source_snapshot["assurance"],
                    "required_payload_role": source_snapshot["role"],
                },
            },
            "dependency_lock": {
                "path": dependency_lock["path"],
                "sha256": dependency_lock["sha256"],
                "required_payload_role": dependency_lock["role"],
            },
            "execution_image": {
                "reference": provenance_overlay["execution_image_reference"],
                "digest": provenance_overlay["execution_image_digest"],
            },
        },
    }
    policy["provenance"] = selected_provenance

    # Reuse only the public deterministic fixture PKI/transparency mechanics.
    fixture_policy = fixture_trust_policy(policy)
    fixture_policy["provenance"] = selected_provenance
    fixture_policy["identity"].update(copy.deepcopy(identity_overlay))
    fixture_policy["identity"]["authorized_identity_uri"] = AUTHORIZED_SAN
    fixture_policy["statement"]["payload_type"] = PAYLOAD_TYPE
    fixture_policy["trust"]["trusted_root_sha256"] = fixture_policy["pilot_fixture"][
        "root_certificate_sha256"
    ]
    fixture_policy["fixture_payloads"] = copy.deepcopy(payload_fixtures)

    unresolved = [
        value
        for value in _walk_strings(fixture_policy)
        if "TBD-BEFORE-REGISTRATION" in value
    ]
    if unresolved:
        raise RuntimeError("selected fixture policy retains production TBD markers")
    return fixture_policy


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)


def _payload_entry(path: str, raw: bytes, media_type: str, role: str) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "media_type": media_type,
        "role": role,
    }


def _selected_build_metadata(policy: dict[str, Any]) -> dict[str, Any]:
    assertions = policy["provenance"]["manifest_assertions"]
    expected_source = assertions["source"]
    expected_snapshot = expected_source["snapshot"]
    return {
        "schema_version": policy["manifest"]["build_metadata_schema_version"],
        "assertion_scope": policy["manifest"]["assertion_scope"],
        "source": {
            "repository_uri": expected_source["repository_uri"],
            "revision": expected_source["revision"],
            "ref": expected_source["ref"],
            "git_object_format": expected_source["git_object_format"],
            "tree": expected_source["tree"],
            "dirty": expected_source["dirty"],
            "snapshot": {
                "path": expected_snapshot["path"],
                "sha256": expected_snapshot["sha256"],
                "format": expected_snapshot["format"],
                "assurance": expected_snapshot["assurance"],
            },
        },
        "dependency_lock": {
            "path": assertions["dependency_lock"]["path"],
            "sha256": assertions["dependency_lock"]["sha256"],
        },
        "execution_image": dict(assertions["execution_image"]),
    }


def _write_selected_release(
    root: Path,
    *,
    release: dict[str, Any],
    files: dict[str, tuple[bytes, str, str]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError(f"selected release destination is not empty: {root}")
    payloads: list[dict[str, Any]] = []
    for relative, (raw, media_type, role) in sorted(
        files.items(), key=lambda item: item[0].encode("utf-8")
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        payloads.append(_payload_entry(relative, raw, media_type, role))
    manifest = {
        "schema_version": policy["manifest"]["schema_version"],
        "release": dict(release),
        "build_metadata": _selected_build_metadata(policy),
        "payloads": payloads,
    }
    (root / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))
    return manifest


def _selected_fixture_files(
    policy: dict[str, Any],
) -> dict[str, tuple[bytes, str, str]]:
    files: dict[str, tuple[bytes, str, str]] = {}
    for fixture in policy["fixture_payloads"].values():
        path = fixture["path"]
        if path in files:
            raise RuntimeError(f"duplicate selected fixture payload path: {path}")
        files[path] = (
            render_selected_fixture_payload(fixture),
            fixture["media_type"],
            fixture["role"],
        )
    return files


def build_clean_selected_release(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    files = {
        "payload/analysis.py": (b"print('selected fixture')\n", "text/x-python", "analysis_code"),
        "payload/data-copy.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/data.csv": (b"x,y\n1,2\n", "text/csv", "raw_data"),
        "payload/results/result.json": (
            b'{"sum":3}\n',
            "application/json",
            "analysis_output",
        ),
        **_selected_fixture_files(policy),
    }
    return _write_selected_release(
        root,
        release={
            "id": "selected-profile-clean",
            "version": "0.4.0",
            "kind": "benchmark_case",
        },
        files=files,
        policy=policy,
    )


def build_selected_release_from_base(
    root: Path,
    base: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Preserve every base recipe and add only reserved provenance fixtures."""

    files: dict[str, tuple[bytes, str, str]] = {}
    for entry in base["payloads"]:
        path = entry["path"]
        if path in files:
            raise ValueError(f"{base['id']}: duplicate blueprint path: {path}")
        files[path] = (
            render_recipe(entry["recipe"]),
            entry["media_type"],
            entry["role"],
        )
    for path, fixture in _selected_fixture_files(policy).items():
        if path in files:
            raise ValueError(
                f"{base['id']}: selected fixture path collides with blueprint: {path}"
            )
        files[path] = fixture
    return _write_selected_release(
        root,
        release=base["release"],
        files=files,
        policy=policy,
    )


def make_selected_statement(
    manifest_raw: bytes,
    policy: dict[str, Any],
    *,
    predicate_type: str | None = None,
    source_revision: str | None = None,
    workflow_path: str | None = None,
    builder_id: str | None = None,
) -> dict[str, Any]:
    provenance = policy["provenance"]
    revision = source_revision or provenance["source_revision"]
    return {
        "_type": policy["statement"]["type"],
        "subject": [
            {
                "name": policy["subject"]["name"],
                "digest": {"sha256": _sha256(manifest_raw)},
            }
        ],
        "predicateType": predicate_type or policy["statement"]["p3_predicate_type"],
        "predicate": {
            "buildDefinition": {
                "buildType": provenance["build_type"],
                "externalParameters": {
                    "workflow": {
                        "repository": provenance["source_repository_uri"],
                        "path": workflow_path or provenance["workflow_path"],
                        "ref": provenance["source_ref"],
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": provenance["resolved_source_dependency_uri"],
                        "digest": {"gitCommit": revision},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": builder_id or provenance["builder_id"]},
                "metadata": {"invocationId": "urn:amy:selected-fixture:0001"},
            },
        },
    }


def attest_selected_manifest(
    root: Path,
    policy: dict[str, Any],
    *,
    statement: dict[str, Any] | bytes | None = None,
    statement_options: dict[str, Any] | None = None,
    bundle_options: dict[str, Any] | None = None,
) -> None:
    manifest_raw = (root / "MANIFEST.jcs.json").read_bytes()
    if statement is None:
        statement = make_selected_statement(
            manifest_raw,
            policy,
            **(statement_options or {}),
        )
    statement_raw = statement if isinstance(statement, bytes) else rfc8785.dumps(statement)
    (root / "attestation.sigstore.json").write_bytes(
        make_fixture_bundle(statement_raw, **(bundle_options or {}))
    )


def _load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "MANIFEST.jcs.json").read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    (root / "MANIFEST.jcs.json").write_bytes(rfc8785.dumps(manifest))


def apply_selected_profile_mutation(
    case_id: str,
    root: Path,
    policy: dict[str, Any],
    *,
    base: dict[str, Any] | None = None,
    mutation_plan: Any | None = None,
) -> None:
    """Backward-compatible entry point; generator code is a separate module."""

    from .selected_profile_mutations import apply_selected_profile_mutation as apply

    apply(case_id, root, policy, base=base, mutation_plan=mutation_plan)


def _common_preflight(root: Path, policy: dict[str, Any]) -> None:
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise VerificationReject("INPUT_MISSING", "bounded_input", "release root is missing") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise VerificationReject("INPUT_MISSING", "bounded_input", "release root is not a directory")
    if (root / "payload").exists():
        observe_payload_tree(
            root,
            max_count=policy["limits"]["payload_file_max_count"],
            max_total_bytes=policy["limits"]["payload_total_max_bytes"],
        )


def verify_selected_fixture_release(
    root: Path,
    *,
    profile_id: str,
    policy: dict[str, Any],
    manifest_schema_path: Path | None = None,
) -> dict[str, Any]:
    if profile_id not in PROFILE_CHECKS:
        raise ValueError(f"unknown profile: {profile_id}")
    schema_path = manifest_schema_path or (
        STUDY_ROOT / policy["manifest"]["schema_path"]
    )
    checks = initial_check_states(profile_id)
    manifest_raw: bytes | None = None
    attestation_raw: bytes | None = None
    decision = "ERROR"
    reason = "INTERNAL_ERROR"
    details: dict[str, Any] = {}
    try:
        _common_preflight(root, policy)
        manifest_raw = bounded_regular_file_read(
            root / "MANIFEST.jcs.json",
            policy["limits"]["manifest_max_bytes"],
            check="bounded_input",
        )
        checks["bounded_input"] = "PASS"
        if profile_id == "P0":
            parse_p0_manifest(manifest_raw, policy)
            checks["manifest_json_syntax"] = "PASS"
        elif profile_id == "P1":
            validate_p1_manifest(
                manifest_raw,
                root=root,
                policy=policy,
                schema=load_schema(schema_path),
                checks=checks,
            )
        else:
            try:
                (root / "attestation.sigstore.json").lstat()
            except FileNotFoundError as exc:
                raise VerificationReject(
                    "ATTESTATION_MISSING",
                    "attestation_structure",
                    "required fixture attestation is missing",
                ) from exc
            attestation_raw = bounded_regular_file_read(
                root / "attestation.sigstore.json",
                policy["limits"]["attestation_max_bytes"],
                check="bounded_input",
            )
            evidence = verify_pilot_attestation(
                attestation_raw,
                manifest_raw,
                policy,
                checks,
            )
            if profile_id == "P3":
                try:
                    _enforce_p3(evidence.statement, policy, manifest_raw)
                except GitHubGateRejected as exc:
                    raise VerificationReject(
                        exc.code,
                        "provenance_policy",
                        exc.message,
                        exc.details,
                    ) from exc
                checks["provenance_policy"] = "PASS"
                validate_p1_manifest(
                    manifest_raw,
                    root=root,
                    policy=policy,
                    schema=load_schema(schema_path),
                    checks=checks,
                )
        incomplete = sorted(
            name for name in PROFILE_CHECKS[profile_id] if checks[name] != "PASS"
        )
        if incomplete:
            raise RuntimeError(f"required checks did not terminate: {incomplete}")
        decision = "ACCEPT"
        reason = "OK"
    except VerificationReject as exc:
        checks[exc.check] = "FAIL"
        decision = "REJECT"
        reason = exc.reason
        details = {"message": exc.message, **exc.details}
    except Exception as exc:
        details = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "schema_version": "amy.selected-profile-fixture-result.v1-draft",
        "profile_id": profile_id,
        "decision": decision,
        "primary_reason": reason,
        "checks": checks,
        "input": {
            "manifest_sha256": _sha256(manifest_raw) if manifest_raw is not None else None,
            "attestation_sha256": (
                _sha256(attestation_raw) if attestation_raw is not None else None
            ),
        },
        "details": details,
        "boundary": "controlled_fixture_not_production_sigstore_not_confirmatory",
    }
