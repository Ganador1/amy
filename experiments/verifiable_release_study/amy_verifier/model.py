from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CHECK_NAMES = (
    "bounded_input",
    "manifest_json_syntax",
    "manifest_schema",
    "manifest_canonicality",
    "path_safety",
    "closed_world_inventory",
    "payload_digests",
    "attestation_structure",
    "algorithm_policy",
    "signature_crypto",
    "certificate_time",
    "signer_policy",
    "transparency",
    "subject_binding",
    "provenance_policy",
)

PROFILE_CHECKS = {
    "P0": {"bounded_input", "manifest_json_syntax"},
    "P1": {
        "bounded_input",
        "manifest_json_syntax",
        "manifest_schema",
        "manifest_canonicality",
        "path_safety",
        "closed_world_inventory",
        "payload_digests",
    },
    "P2": {
        "bounded_input",
        "attestation_structure",
        "algorithm_policy",
        "signature_crypto",
        "certificate_time",
        "signer_policy",
        "transparency",
        "subject_binding",
    },
    "P3": set(CHECK_NAMES),
}


@dataclass
class VerificationReject(Exception):
    reason: str
    check: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def initial_check_states(profile_id: str) -> dict[str, str]:
    required = PROFILE_CHECKS[profile_id]
    return {
        name: "NOT_RUN" if name in required else "NOT_REQUIRED"
        for name in CHECK_NAMES
    }
