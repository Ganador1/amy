from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import rfc8785
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey
from cryptography.x509.oid import ExtensionOID

from .fixture_crypto import dsse_pae
from .json_tools import parse_json_bytes
from .model import VerificationReject


@dataclass(frozen=True)
class AttestationEvidence:
    statement: dict[str, Any]
    signer_identity: str
    integrated_time: int
    signature_algorithm: str


def _b64decode(value: Any, field: str) -> bytes:
    if not isinstance(value, str):
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", f"{field} is not a base64 string"
        )
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", f"{field} is not valid base64"
        ) from exc


def _require_exact_keys(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", f"{label} is not an object"
        )
    keys = set(value)
    if not required <= keys or keys - required - optional:
        raise VerificationReject(
            "ATTESTATION_INVALID",
            "attestation_structure",
            f"{label} has missing or unexpected fields",
            {"missing": sorted(required - keys), "unexpected": sorted(keys - required - optional)},
        )
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_pilot_attestation(
    bundle_raw: bytes,
    manifest_raw: bytes,
    policy: dict[str, Any],
    checks: dict[str, str],
) -> AttestationEvidence:
    bundle = parse_json_bytes(
        bundle_raw,
        max_depth=policy["limits"]["json_max_depth"],
        reject_duplicate_keys=True,
        failure_check="attestation_structure",
        invalid_reason="ATTESTATION_INVALID",
        duplicate_reason="ATTESTATION_INVALID",
    )
    bundle = _require_exact_keys(
        bundle,
        {"mediaType", "verificationMaterial", "dsseEnvelope"},
        set(),
        "bundle",
    )
    if bundle["mediaType"] not in policy["bundle"]["allowed_media_types"]:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "bundle media type is not allowed"
        )
    material = _require_exact_keys(
        bundle["verificationMaterial"],
        {"certificateDer", "signatureAlgorithm"},
        {"transparency"},
        "verificationMaterial",
    )
    envelope = _require_exact_keys(
        bundle["dsseEnvelope"],
        {"payload", "payloadType", "signatures"},
        set(),
        "dsseEnvelope",
    )
    if envelope["payloadType"] != policy["statement"]["payload_type"]:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "DSSE payload type is not allowed"
        )
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "fixture DSSE requires one signature"
        )
    signature_entry = _require_exact_keys(signatures[0], {"keyid", "sig"}, set(), "signature")
    payload = _b64decode(envelope["payload"], "dsseEnvelope.payload")
    if len(payload) > policy["limits"]["dsse_statement_max_bytes"]:
        raise VerificationReject(
            "RESOURCE_LIMIT", "bounded_input", "DSSE Statement exceeds its byte limit"
        )
    signature = _b64decode(signature_entry["sig"], "dsseEnvelope.signatures[0].sig")
    certificate_der = _b64decode(material["certificateDer"], "certificateDer")
    try:
        certificate = x509.load_der_x509_certificate(certificate_der)
        root_der = _b64decode(
            policy["pilot_fixture"]["root_certificate_der_base64"],
            "pilot_fixture.root_certificate_der_base64",
        )
        root_certificate = x509.load_der_x509_certificate(root_der)
    except Exception as exc:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "certificate material is invalid"
        ) from exc
    if _sha256(root_der) != policy["pilot_fixture"]["root_certificate_sha256"]:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "fixture trust root digest mismatch"
        )
    try:
        root_certificate.public_key().verify(
            root_certificate.signature, root_certificate.tbs_certificate_bytes
        )
        root_certificate.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "certificate chain verification failed"
        ) from exc
    if certificate.issuer != root_certificate.subject:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "leaf certificate issuer mismatch"
        )
    checks["attestation_structure"] = "PASS"

    public_key = certificate.public_key()
    if isinstance(public_key, Ed25519PublicKey):
        derived_algorithm = "ed25519"
    elif isinstance(public_key, Ed448PublicKey):
        derived_algorithm = "ed448"
    else:
        raise VerificationReject(
            "ALGORITHM_UNAPPROVED", "algorithm_policy", "fixture public-key type is unsupported"
        )
    if material["signatureAlgorithm"] != derived_algorithm:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "algorithm label/key type mismatch"
        )
    if derived_algorithm not in policy["algorithms"]["approved_signature_algorithms"]:
        raise VerificationReject(
            "ALGORITHM_UNAPPROVED", "algorithm_policy", "signature algorithm is not approved"
        )
    public_key_der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if signature_entry["keyid"] != _sha256(public_key_der):
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "DSSE key identifier mismatch"
        )
    checks["algorithm_policy"] = "PASS"
    try:
        public_key.verify(
            signature,
            dsse_pae(policy["statement"]["payload_type"].encode("ascii"), payload),
        )
    except InvalidSignature as exc:
        raise VerificationReject(
            "SIGNATURE_INVALID", "signature_crypto", "DSSE signature verification failed"
        ) from exc
    checks["signature_crypto"] = "PASS"

    transparency = material.get("transparency")
    if not isinstance(transparency, dict):
        raise VerificationReject(
            "TRANSPARENCY_INVALID", "transparency", "required transparency evidence is missing"
        )
    transparency = _require_exact_keys(
        transparency,
        {"envelopeSha256", "integratedTime", "logId", "signature"},
        set(),
        "transparency",
    )
    log_public_raw = _b64decode(
        policy["pilot_fixture"]["transparency_log_public_key_raw_base64"],
        "pilot_fixture.transparency_log_public_key_raw_base64",
    )
    if transparency["logId"] != policy["pilot_fixture"]["transparency_log_id"]:
        raise VerificationReject(
            "TRANSPARENCY_INVALID", "transparency", "transparency log identity is not trusted"
        )
    if transparency["envelopeSha256"] != _sha256(rfc8785.dumps(envelope)):
        raise VerificationReject(
            "TRANSPARENCY_INVALID", "transparency", "transparency evidence names another envelope"
        )
    if not isinstance(transparency["integratedTime"], int) or isinstance(
        transparency["integratedTime"], bool
    ):
        raise VerificationReject(
            "TRANSPARENCY_INVALID", "transparency", "integrated time is not an integer"
        )
    transparency_core = {
        "envelopeSha256": transparency["envelopeSha256"],
        "integratedTime": transparency["integratedTime"],
        "logId": transparency["logId"],
    }
    log_message = (
        policy["pilot_fixture"]["transparency_signature_domain"].encode("ascii")
        + b"\x00"
        + rfc8785.dumps(transparency_core)
    )
    try:
        Ed25519PublicKey.from_public_bytes(log_public_raw).verify(
            _b64decode(transparency["signature"], "transparency.signature"), log_message
        )
    except (InvalidSignature, ValueError) as exc:
        raise VerificationReject(
            "TRANSPARENCY_INVALID", "transparency", "transparency signature verification failed"
        ) from exc
    checks["transparency"] = "PASS"

    witnessed_at = datetime.fromtimestamp(transparency["integratedTime"], tz=timezone.utc)
    if not (certificate.not_valid_before_utc <= witnessed_at <= certificate.not_valid_after_utc):
        raise VerificationReject(
            "CERTIFICATE_TIME_INVALID",
            "certificate_time",
            "certificate was not valid at the authenticated signing time",
        )
    checks["certificate_time"] = "PASS"

    try:
        identities = certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value.get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound as exc:
        raise VerificationReject(
            "SIGNER_UNAUTHORIZED", "signer_policy", "certificate has no URI identity"
        ) from exc
    if len(identities) != 1:
        raise VerificationReject(
            "SIGNER_UNAUTHORIZED", "signer_policy", "certificate identity is ambiguous"
        )
    identity = identities[0]
    expected_identity = policy["identity"]["authorized_identity_uri"]
    if identity != expected_identity:
        repository_prefix = policy["identity"]["repository_uri"] + "/"
        reason = "BUILDER_UNAUTHORIZED" if identity.startswith(repository_prefix) else "SIGNER_UNAUTHORIZED"
        raise VerificationReject(reason, "signer_policy", "certificate identity is not authorized")
    checks["signer_policy"] = "PASS"

    statement = parse_json_bytes(
        payload,
        max_depth=policy["limits"]["json_max_depth"],
        reject_duplicate_keys=True,
        failure_check="attestation_structure",
        invalid_reason="ATTESTATION_INVALID",
        duplicate_reason="ATTESTATION_INVALID",
    )
    if not isinstance(statement, dict) or statement.get("_type") != policy["statement"]["type"]:
        raise VerificationReject(
            "ATTESTATION_INVALID", "attestation_structure", "authenticated payload is not Statement v1"
        )
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1 or not isinstance(subjects[0], dict):
        raise VerificationReject(
            "SUBJECT_MISMATCH", "subject_binding", "Statement subject cardinality is not one"
        )
    subject = subjects[0]
    digest = subject.get("digest")
    if (
        subject.get("name") != policy["subject"]["name"]
        or not isinstance(digest, dict)
        or digest.get("sha256") != _sha256(manifest_raw)
        or set(digest) != {"sha256"}
    ):
        raise VerificationReject(
            "SUBJECT_MISMATCH", "subject_binding", "Statement does not bind exact manifest bytes"
        )
    checks["subject_binding"] = "PASS"
    return AttestationEvidence(statement, identity, transparency["integratedTime"], derived_algorithm)


def enforce_p3_provenance(
    statement: dict[str, Any], policy: dict[str, Any], checks: dict[str, str]
) -> None:
    if statement.get("predicateType") != policy["statement"]["p3_predicate_type"]:
        raise VerificationReject(
            "PREDICATE_TYPE_UNSUPPORTED",
            "provenance_policy",
            "authenticated predicate type is not the frozen SLSA provenance type",
        )
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise VerificationReject(
            "ATTESTATION_INVALID", "provenance_policy", "Statement predicate is not an object"
        )
    build_definition = predicate.get("buildDefinition")
    run_details = predicate.get("runDetails")
    if not isinstance(build_definition, dict) or not isinstance(run_details, dict):
        raise VerificationReject(
            "ATTESTATION_INVALID", "provenance_policy", "SLSA provenance structure is incomplete"
        )
    external = build_definition.get("externalParameters")
    source = external.get("source") if isinstance(external, dict) else None
    provenance = policy["provenance"]
    if (
        not isinstance(source, dict)
        or source.get("repository") != provenance["source_repository_uri"]
        or source.get("revision") != provenance["source_revision"]
    ):
        raise VerificationReject(
            "SOURCE_MISMATCH", "provenance_policy", "authenticated source policy mismatch"
        )
    dependencies = build_definition.get("resolvedDependencies")
    if not isinstance(dependencies, list):
        raise VerificationReject(
            "SOURCE_MISMATCH", "provenance_policy", "resolved dependency list is missing"
        )
    source_matches = [
        item
        for item in dependencies
        if isinstance(item, dict) and item.get("uri") == provenance["source_dependency_uri"]
    ]
    if len(source_matches) != 1 or (source_matches[0].get("digest") or {}).get(
        "gitCommit"
    ) != provenance["source_revision"]:
        raise VerificationReject(
            "SOURCE_MISMATCH", "provenance_policy", "source dependency revision mismatch"
        )
    if source.get("dirty") is not False:
        raise VerificationReject(
            "DIRTY_BUILD", "provenance_policy", "official provenance declares a dirty source"
        )
    builder = run_details.get("builder")
    if not isinstance(builder, dict) or builder.get("id") != provenance["builder_id"]:
        raise VerificationReject(
            "BUILDER_UNAUTHORIZED", "provenance_policy", "provenance builder is not authorized"
        )
    for required in provenance["materials"]:
        matches = [
            item
            for item in dependencies
            if isinstance(item, dict) and item.get("uri") == required["uri"]
        ]
        if len(matches) != 1 or (matches[0].get("digest") or {}).get(
            required["algorithm"]
        ) != required["digest"]:
            raise VerificationReject(
                "MATERIAL_MISMATCH",
                "provenance_policy",
                f"required material mismatch: {required['name']}",
            )
    checks["provenance_policy"] = "PASS"
