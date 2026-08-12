from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import tarfile
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator

from .fixture_crypto import fixture_trust_policy
from .path_policy import validate_manifest_paths
from .pilot import attest_current_manifest


BASE_ID_PATTERN = re.compile(r"^B[0-9]{2}-[A-Z0-9-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RECIPE_VERSION = b"amy.base-recipes.v1\x00"
CC0_NOTICE = (
    "To the extent possible under law, the study authors have waived all "
    "copyright and related or neighboring rights to these generated fixture "
    "bytes under CC0 1.0. See https://creativecommons.org/publicdomain/zero/1.0/.\n"
).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_escape(value: str) -> bytes:
    raw = value.encode("ascii")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def minimal_pdf(title: str, body: str) -> bytes:
    title_bytes = _pdf_escape(title)
    body_bytes = _pdf_escape(body)
    content = (
        b"BT /F1 14 Tf 72 720 Td ("
        + title_bytes
        + b") Tj 0 -28 Td /F1 10 Tf ("
        + body_bytes
        + b") Tj ET\n"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
    ]
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode("ascii"))
        result.extend(obj)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(result)


def sha256_counter_stream(seed: str, byte_count: int) -> bytes:
    if byte_count < 0:
        raise ValueError("sha256_counter byte count cannot be negative")
    seed_bytes = seed.encode("utf-8")
    output = bytearray()
    counter = 0
    while len(output) < byte_count:
        output.extend(
            hashlib.sha256(
                RECIPE_VERSION + seed_bytes + b"\x00" + counter.to_bytes(8, "big")
            ).digest()
        )
        counter += 1
    return bytes(output[:byte_count])


def render_recipe(recipe: dict[str, Any]) -> bytes:
    recipe_type = recipe.get("type")
    if recipe_type == "empty":
        return b""
    if recipe_type == "utf8":
        text = recipe.get("text")
        if not isinstance(text, str):
            raise ValueError("utf8 recipe requires text")
        return text.encode("utf-8")
    if recipe_type == "jcs_json":
        return rfc8785.dumps(recipe.get("value"))
    if recipe_type == "sha256_counter":
        seed = recipe.get("seed")
        byte_count = recipe.get("bytes")
        if not isinstance(seed, str) or not isinstance(byte_count, int):
            raise ValueError("sha256_counter recipe requires string seed and integer bytes")
        return sha256_counter_stream(seed, byte_count)
    if recipe_type == "minimal_pdf":
        title = recipe.get("title")
        body = recipe.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("minimal_pdf recipe requires title and body")
        return minimal_pdf(title, body)
    raise ValueError(f"unknown base byte recipe: {recipe_type!r}")


def validate_registry(registry: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("classification") != "R0_inputs_only_no_confirmatory_cases":
        errors.append("base registry classification is not R0-only")
    if registry.get("generation", {}).get("byte_recipe_version") != RECIPE_VERSION[:-1].decode():
        errors.append("base registry byte-recipe version differs from implementation")
    base_entries = registry.get("bases")
    if not isinstance(base_entries, list) or not base_entries:
        return ["base registry contains no bases"]
    base_ids = [base.get("id") for base in base_entries if isinstance(base, dict)]
    if len(base_ids) != len(set(base_ids)):
        errors.append("duplicate base IDs")
    seeds = [base.get("seed") for base in base_entries if isinstance(base, dict)]
    if len(seeds) != len(set(seeds)):
        errors.append("duplicate base seeds")

    for base in base_entries:
        if not isinstance(base, dict):
            errors.append("base entry is not an object")
            continue
        base_id = str(base.get("id", "<missing-id>"))
        if not BASE_ID_PATTERN.fullmatch(base_id):
            errors.append(f"{base_id}: invalid base ID")
        if base.get("stratum") != "S1-CONFORMANCE":
            errors.append(f"{base_id}: draft generated bases must belong to S1-CONFORMANCE")
        if base.get("license_spdx") != "CC0-1.0" or base.get("third_party_bytes") is not False:
            errors.append(f"{base_id}: license/origin policy is not redistributable fixture-only")
        for hash_field in (
            "expected_base_archive_sha256",
            "expected_manifest_sha256",
            "expected_tree_sha256",
        ):
            value = base.get(hash_field)
            if value is not None and not SHA256_PATTERN.fullmatch(str(value)):
                errors.append(f"{base_id}: {hash_field} is neither null nor SHA-256")

        payload_specs = base.get("payloads")
        if not isinstance(payload_specs, list) or not payload_specs:
            errors.append(f"{base_id}: no payload blueprints")
            continue
        paths = [entry.get("path") for entry in payload_specs if isinstance(entry, dict)]
        if len(paths) != len(payload_specs) or any(not isinstance(path, str) for path in paths):
            errors.append(f"{base_id}: payload paths must be strings")
            continue
        try:
            validate_manifest_paths(
                paths,
                max_bytes=policy["limits"]["path_max_utf8_bytes"],
                max_components=policy["limits"]["path_max_components"],
            )
        except Exception as exc:
            errors.append(f"{base_id}: invalid payload paths: {type(exc).__name__}: {exc}")
        rendered: dict[str, bytes] = {}
        for entry in payload_specs:
            try:
                raw = render_recipe(entry["recipe"])
            except Exception as exc:
                errors.append(f"{base_id}/{entry.get('path')}: invalid recipe: {exc}")
                continue
            if len(raw) > policy["limits"]["single_payload_max_bytes"]:
                errors.append(f"{base_id}/{entry['path']}: payload exceeds policy")
            rendered[entry["path"]] = raw
        if len(rendered) > policy["limits"]["payload_file_max_count"]:
            errors.append(f"{base_id}: payload count exceeds policy")
        if sum(map(len, rendered.values())) > policy["limits"]["payload_total_max_bytes"]:
            errors.append(f"{base_id}: payload total exceeds policy")

        release = base.get("release") or {}
        release_kind = release.get("kind")
        roles = [entry.get("role") for entry in payload_specs]
        required_roles = policy["manifest"]["required_roles_by_release_kind"].get(
            release_kind
        )
        if required_roles is None:
            errors.append(f"{base_id}: unknown release kind {release_kind!r}")
        elif set(required_roles) - set(roles):
            errors.append(f"{base_id}: missing required roles {sorted(set(required_roles) - set(roles))}")

        targets = base.get("mutation_targets") or {}
        for target_name in (
            "primary_nonempty_payload",
            "same_bytes_source",
            "nested_payload",
            "sole_required_role_payload",
        ):
            if targets.get(target_name) not in rendered:
                errors.append(f"{base_id}: mutation target {target_name} is absent")
        primary = targets.get("primary_nonempty_payload")
        if primary in rendered and not rendered[primary]:
            errors.append(f"{base_id}: primary mutation target is empty")
        hardlink_target = targets.get("hardlink_target", primary)
        same_bytes_source = targets.get("same_bytes_source")
        if hardlink_target in rendered and same_bytes_source in rendered:
            if rendered[hardlink_target] != rendered[same_bytes_source]:
                errors.append(f"{base_id}: hardlink target/source fixture bytes differ")
        sole_path = targets.get("sole_required_role_payload")
        role_by_path = {entry["path"]: entry.get("role") for entry in payload_specs}
        sole_role = role_by_path.get(sole_path)
        if sole_role not in set(required_roles or []):
            errors.append(f"{base_id}: sole-role mutation target is not a required role")
        elif roles.count(sole_role) != 1:
            errors.append(f"{base_id}: sole-role mutation target role is not unique")
    return errors


def build_manifest(base: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    rendered = {
        entry["path"]: render_recipe(entry["recipe"])
        for entry in base["payloads"]
    }
    payloads = [
        {
            "path": entry["path"],
            "bytes": len(rendered[entry["path"]]),
            "sha256": sha256_bytes(rendered[entry["path"]]),
            "media_type": entry["media_type"],
            "role": entry["role"],
        }
        for entry in base["payloads"]
    ]
    payloads.sort(key=lambda entry: entry["path"].encode("utf-8"))
    manifest = {
        "schema_version": "0.1.0-draft",
        "release": dict(base["release"]),
        "payloads": payloads,
    }
    return manifest, rendered


def build_clean_base(
    destination: Path,
    base: dict[str, Any],
    policy: dict[str, Any],
    manifest_schema: dict[str, Any],
) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"base destination already exists: {destination}")
    manifest, rendered = build_manifest(base)
    destination.mkdir(parents=True)
    for path_string, raw in rendered.items():
        path = destination / path_string
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    manifest_raw = rfc8785.dumps(manifest)
    if len(manifest_raw) > policy["limits"]["manifest_max_bytes"]:
        raise ValueError(f"{base['id']}: clean manifest exceeds policy")
    errors = sorted(
        Draft202012Validator(manifest_schema).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(
            f"{base['id']}: manifest schema errors: "
            + "; ".join(error.message for error in errors)
        )
    (destination / "MANIFEST.jcs.json").write_bytes(manifest_raw)
    attest_current_manifest(destination, policy)
    return {
        "base_id": base["id"],
        "manifest_sha256": sha256_bytes(manifest_raw),
        "payload_count": len(rendered),
        "payload_bytes": sum(map(len, rendered.values())),
    }


def snapshot_tree(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode()):
        path_stat = path.lstat()
        logical_path = path.relative_to(root).as_posix()
        if stat.S_ISDIR(path_stat.st_mode):
            records.append({"path": logical_path, "kind": "directory"})
        elif stat.S_ISREG(path_stat.st_mode):
            records.append(
                {
                    "path": logical_path,
                    "kind": "regular",
                    "bytes": path_stat.st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            raise ValueError(f"clean base contains non-regular object: {logical_path}")
    return records


def write_deterministic_archive(root: Path, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(f"archive destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode())
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        for path in paths:
            logical_path = path.relative_to(root).as_posix()
            path_stat = path.lstat()
            info = tarfile.TarInfo(logical_path)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if stat.S_ISDIR(path_stat.st_mode):
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            elif stat.S_ISREG(path_stat.st_mode):
                raw = path.read_bytes()
                info.type = tarfile.REGTYPE
                info.mode = 0o644
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            else:
                raise ValueError(f"clean base archive contains unsupported object: {logical_path}")
    return sha256_file(destination)


def load_draft_inputs(
    registry_path: Path, trust_policy_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    base_policy = json.loads(trust_policy_path.read_text(encoding="utf-8"))
    return registry, fixture_trust_policy(base_policy)
