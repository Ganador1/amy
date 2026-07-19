from __future__ import annotations

import base64
import copy
import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

import rfc8785
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


FIXTURE_MEDIA_TYPE = "application/vnd.amy.pilot-fixture.dsse.v1+json"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
AUTHORIZED_SAN = (
    "https://github.com/Ganador1/amy/.github/workflows/"
    "attest-verifiable-release.yml@refs/tags/paper-v0.1.0"
)
WRONG_WORKFLOW_SAN = (
    "https://github.com/Ganador1/amy/.github/workflows/"
    "untrusted.yml@refs/heads/feature"
)
UNAUTHORIZED_SAN = (
    "https://github.com/ExampleAttacker/other/.github/workflows/"
    "release.yml@refs/tags/v1.0.0"
)
INTEGRATED_TIME = int(datetime(2026, 7, 13, 12, tzinfo=timezone.utc).timestamp())


def _seed(label: str, length: int) -> bytes:
    return hashlib.shake_256(f"A.M.Y PILOT FIXTURE ONLY::{label}".encode()).digest(length)


def _ed25519(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_seed(label, 32))


def _ed448(label: str) -> Ed448PrivateKey:
    return Ed448PrivateKey.from_private_bytes(_seed(label, 57))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dsse_pae(payload_type: bytes, payload: bytes) -> bytes:
    return b" ".join(
        (
            b"DSSEv1",
            str(len(payload_type)).encode("ascii"),
            payload_type,
            str(len(payload)).encode("ascii"),
            payload,
        )
    )


def _serial(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:19], "big") or 1


def _root_certificate() -> tuple[Ed25519PrivateKey, x509.Certificate]:
    key = _ed25519("root-ca")
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "A.M.Y PILOT ROOT - DO NOT TRUST")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(_serial("root-ca"))
        .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
        .not_valid_after(datetime(2035, 1, 1, tzinfo=timezone.utc))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, algorithm=None)
    )
    return key, certificate


def _leaf_certificate(
    *,
    identity: str,
    algorithm: Literal["ed25519", "ed448"],
    certificate_time_valid: bool,
) -> tuple[Ed25519PrivateKey | Ed448PrivateKey, x509.Certificate]:
    root_key, root_certificate = _root_certificate()
    key = _ed25519(f"leaf::{identity}") if algorithm == "ed25519" else _ed448(f"leaf::{identity}")
    if certificate_time_valid:
        not_before = datetime(2026, 7, 12, tzinfo=timezone.utc)
        not_after = datetime(2026, 7, 14, tzinfo=timezone.utc)
    else:
        not_before = datetime(2026, 6, 1, tzinfo=timezone.utc)
        not_after = datetime(2026, 6, 2, tzinfo=timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "A.M.Y PILOT SIGNER")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_certificate.subject)
        .public_key(key.public_key())
        .serial_number(_serial(f"{algorithm}::{identity}::{certificate_time_valid}"))
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(identity)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(root_key, algorithm=None)
    )
    return key, certificate


def fixture_trust_policy(base_policy: dict[str, Any]) -> dict[str, Any]:
    policy = copy.deepcopy(base_policy)
    _, root_certificate = _root_certificate()
    root_der = root_certificate.public_bytes(serialization.Encoding.DER)
    log_public = _ed25519("transparency-log").public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    log_id = _sha256(log_public)
    policy["status"] = "pilot_fixture_only_not_valid_for_production_or_confirmatory_release"
    policy["identity"].update(
        {
            "profile": "pilot_fixture_pki_not_production",
            "issuer": root_certificate.subject.rfc4514_string(),
            "workflow_path": ".github/workflows/attest-verifiable-release.yml",
            "allowed_ref_patterns": ["refs/tags/paper-v0.1.0"],
            "allowed_event_names": ["pilot_fixture"],
            "authorized_identity_uri": AUTHORIZED_SAN,
        }
    )
    policy["bundle"].update(
        {
            "allowed_media_types": [FIXTURE_MEDIA_TYPE],
            "schema_or_tool_version": "amy-pilot-fixture-dsse-v1",
            "accepted_log_ids": [log_id],
        }
    )
    policy["algorithms"]["approved_signature_algorithms"] = ["ed25519"]
    policy["provenance"].update(
        {
            "source_revision": "a" * 40,
            "builder_id": "https://github.com/actions/runner/github-hosted",
            "materials": [
                {
                    "name": "source_snapshot_sha256",
                    "uri": "amy:source-snapshot",
                    "algorithm": "sha256",
                    "digest": "b" * 64,
                },
                {
                    "name": "dependency_lock_sha256",
                    "uri": "amy:dependency-lock",
                    "algorithm": "sha256",
                    "digest": "c" * 64,
                },
                {
                    "name": "execution_image_digest",
                    "uri": "oci:amy-execution-image",
                    "algorithm": "sha256",
                    "digest": "d" * 64,
                },
            ],
        }
    )
    policy["pilot_fixture"] = {
        "warning": "PUBLIC TEST MATERIAL; NEVER AUTHORIZE FOR PRODUCTION",
        "root_certificate_der_base64": _b64(root_der),
        "root_certificate_sha256": _sha256(root_der),
        "transparency_log_public_key_raw_base64": _b64(log_public),
        "transparency_log_id": log_id,
        "transparency_signature_domain": "AMY-PILOT-LOG-V1",
    }
    return policy


def make_statement(
    manifest_bytes: bytes,
    policy: dict[str, Any],
    *,
    predicate_type: str | None = None,
    source_revision: str | None = None,
    source_repository_uri: str | None = None,
    dirty: bool = False,
    builder_id: str | None = None,
    material_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    provenance = policy["provenance"]
    revision = source_revision or provenance["source_revision"]
    repository = source_repository_uri or provenance["source_repository_uri"]
    material_overrides = material_overrides or {}
    dependencies = [
        {
            "uri": provenance["source_dependency_uri"],
            "digest": {"gitCommit": revision},
        }
    ]
    for material in provenance["materials"]:
        dependencies.append(
            {
                "uri": material["uri"],
                "digest": {
                    material["algorithm"]: material_overrides.get(
                        material["name"], material["digest"]
                    )
                },
            }
        )
    return {
        "_type": policy["statement"]["type"],
        "subject": [
            {
                "name": policy["subject"]["name"],
                "digest": {"sha256": _sha256(manifest_bytes)},
            }
        ],
        "predicateType": predicate_type or policy["statement"]["p3_predicate_type"],
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/Attestations/GitHubActionsWorkflow@v1",
                "externalParameters": {
                    "source": {
                        "repository": repository,
                        "revision": revision,
                        "dirty": dirty,
                    }
                },
                "internalParameters": {"fixture": True},
                "resolvedDependencies": dependencies,
            },
            "runDetails": {
                "builder": {"id": builder_id or provenance["builder_id"]},
                "metadata": {"invocationId": "urn:amy:pilot:invocation:0001"},
            },
        },
    }


def make_fixture_bundle(
    statement_bytes: bytes,
    *,
    signer: Literal["authorized", "unauthorized", "wrong_workflow"] = "authorized",
    algorithm: Literal["ed25519", "ed448"] = "ed25519",
    certificate_time_valid: bool = True,
    include_transparency: bool = True,
    corrupt_signature: bool = False,
    corrupt_transparency_signature: bool = False,
) -> bytes:
    identity = {
        "authorized": AUTHORIZED_SAN,
        "unauthorized": UNAUTHORIZED_SAN,
        "wrong_workflow": WRONG_WORKFLOW_SAN,
    }[signer]
    leaf_key, leaf_certificate = _leaf_certificate(
        identity=identity,
        algorithm=algorithm,
        certificate_time_valid=certificate_time_valid,
    )
    public_key_der = leaf_certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = leaf_key.sign(dsse_pae(PAYLOAD_TYPE.encode("ascii"), statement_bytes))
    if corrupt_signature:
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    envelope = {
        "payload": _b64(statement_bytes),
        "payloadType": PAYLOAD_TYPE,
        "signatures": [{"keyid": _sha256(public_key_der), "sig": _b64(signature)}],
    }
    envelope_bytes = rfc8785.dumps(envelope)
    verification_material: dict[str, Any] = {
        "certificateDer": _b64(leaf_certificate.public_bytes(serialization.Encoding.DER)),
        "signatureAlgorithm": algorithm,
    }
    if include_transparency:
        log_public = _ed25519("transparency-log").public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        core = {
            "envelopeSha256": _sha256(envelope_bytes),
            "integratedTime": INTEGRATED_TIME,
            "logId": _sha256(log_public),
        }
        log_message = b"AMY-PILOT-LOG-V1\x00" + rfc8785.dumps(core)
        log_signature = _ed25519("transparency-log").sign(log_message)
        if corrupt_transparency_signature:
            log_signature = bytes([log_signature[0] ^ 1]) + log_signature[1:]
        verification_material["transparency"] = {
            **core,
            "signature": _b64(log_signature),
        }
    return rfc8785.dumps(
        {
            "mediaType": FIXTURE_MEDIA_TYPE,
            "verificationMaterial": verification_material,
            "dsseEnvelope": envelope,
        }
    )
