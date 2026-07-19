#!/usr/bin/env python3
"""Build the outcome-blind v0.4 S1 catalog for the selected P3 profile."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_CATALOG = "protocol/ATTACK_CATALOG.json"
HISTORICAL_CATALOG_SHA256 = (
    "409213b0660263467947dc611933352cea145a03d536224181d94a3107c8c46d"
)
HISTORICAL_PREREQUISITES = "protocol/PREREQUISITE_REGISTRY_DRAFT.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load(relative: str) -> dict[str, Any]:
    return json.loads((STUDY_ROOT / relative).read_text(encoding="utf-8"))


def expectations(p3_reason: str, *, p1_reason: str | None = None) -> dict[str, Any]:
    p1 = (
        {"decision": "REJECT", "primary_reason": p1_reason}
        if p1_reason
        else {"decision": "ACCEPT", "primary_reason": "OK"}
    )
    return {
        "P0": {"decision": "ACCEPT", "primary_reason": "OK"},
        "P1": p1,
        "P2": {"decision": "ACCEPT", "primary_reason": "OK"},
        "P3": {"decision": "REJECT", "primary_reason": p3_reason},
    }


def mutation_contract(
    *,
    authenticated_object: str,
    json_pointer: str,
    isolation: str,
) -> dict[str, Any]:
    return {
        "authenticated_object": authenticated_object,
        "json_pointer": json_pointer,
        "reattest_after_mutation": True,
        "payload_bytes_changed": False,
        "isolation": isolation,
    }


def _replace_case(cases: list[dict[str, Any]], case_id: str, **updates: Any) -> None:
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise RuntimeError(f"historical case cardinality differs: {case_id}")
    matches[0].update(copy.deepcopy(updates))


def build_catalog() -> dict[str, Any]:
    historical_path = STUDY_ROOT / HISTORICAL_CATALOG
    if sha256(historical_path) != HISTORICAL_CATALOG_SHA256:
        raise RuntimeError("historical attack catalog hash differs")
    catalog = copy.deepcopy(load(HISTORICAL_CATALOG))
    catalog["catalog_version"] = "0.4.0-draft"
    catalog["status"] = "selected_profile_migration_not_frozen_not_executed"
    catalog["target_contract_id"] = "amy-verifiable-release-selected-profile-v0.4-draft"
    catalog["derived_from"] = {
        "path": HISTORICAL_CATALOG,
        "sha256": HISTORICAL_CATALOG_SHA256,
        "boundary": (
            "The v0.3 catalog and retained pilot archives remain immutable; this v0.4 "
            "draft has no confirmatory or production outcomes."
        ),
    }
    catalog["reason_code_registry"] = {
        "base_path": "protocol/REASON_CODES.json",
        "production_extension_path": "protocol/PRODUCTION_REASON_CODES_DRAFT.json",
    }
    catalog["manifest_contract"] = {
        "path": "schemas/manifest-production-v0.2.schema.json",
        "sha256": sha256(STUDY_ROOT / "schemas/manifest-production-v0.2.schema.json"),
        "build_metadata_pointer": "/build_metadata",
        "source_snapshot_assurance": (
            "exact-opaque-bytes-no-git-tree-equivalence-claim"
        ),
    }
    catalog["fixture_policy"] = {
        "path": "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json",
        "sha256": sha256(
            STUDY_ROOT / "protocol/SELECTED_PROFILE_FIXTURE_POLICY_DRAFT.json"
        ),
        "production_sigstore_conformance": False,
    }
    catalog["profile_selection"] = {
        "id": "standard_provenance_plus_authenticated_manifest_metadata",
        "decision_path": "protocol/ATTESTATION_PROFILE_DECISION_DRAFT.json",
        "standard_predicate": "https://slsa.dev/provenance/v1",
        "custom_slsa_materials": False,
    }
    catalog["rules"] = [
        *catalog["rules"],
        (
            "Selected-profile S1 cases authenticate changed manifest/Statement bytes with "
            "the controlled signer so the named semantic check is reachable."
        ),
        (
            "Workflow-authored manifest values are tested as policy assertions, not as "
            "facts independently certified by the fixture, GitHub, or Sigstore."
        ),
        (
            "Source-snapshot mutations test exact-byte metadata and role binding only; "
            "tree-to-tar equivalence is outside the target contract."
        ),
    ]

    cases = catalog["cases"]
    _replace_case(
        cases,
        "PREDICATE-WRONG-TYPE-001",
        operation=(
            "Authenticate the unchanged manifest under a Statement whose predicateType is "
            "not https://slsa.dev/provenance/v1."
        ),
        mutation_contract=mutation_contract(
            authenticated_object="in_toto_statement",
            json_pointer="/predicateType",
            isolation="Only predicateType changes; subject, signer, and manifest remain valid.",
        ),
    )
    _replace_case(
        cases,
        "SOURCE-WRONG-REVISION-001",
        operation=(
            "Authenticate the unchanged manifest under default-shape SLSA provenance whose "
            "sole resolved Git dependency carries the wrong full revision."
        ),
        mutation_contract=mutation_contract(
            authenticated_object="in_toto_statement",
            json_pointer="/predicate/buildDefinition/resolvedDependencies/0/digest/gitCommit",
            isolation=(
                "Only the resolved source digest changes; workflow, builder, subject, and "
                "manifest remain valid."
            ),
        ),
    )
    _replace_case(
        cases,
        "BUILD-DIRTY-001",
        operation=(
            "Set authenticated manifest /build_metadata/source/dirty to true, leave all "
            "payload bytes and standard provenance unchanged, and re-attest the new manifest."
        ),
        prerequisites=[
            "dirty_build_field_or_invariant_frozen",
            "authorized_fixture_signer_available",
        ],
        mutation_contract=mutation_contract(
            authenticated_object="manifest",
            json_pointer="/build_metadata/source/dirty",
            isolation="Only the workflow-authored clean-state assertion changes.",
        ),
    )
    _replace_case(
        cases,
        "MATERIAL-LOCK-MISMATCH-001",
        operation=(
            "Change authenticated manifest /build_metadata/dependency_lock/sha256 while the "
            "lock payload entry and bytes remain unchanged, then re-attest the manifest."
        ),
        prerequisites=[
            "required_material_policy_frozen",
            "authorized_fixture_signer_available",
        ],
        mutation_contract=mutation_contract(
            authenticated_object="manifest",
            json_pointer="/build_metadata/dependency_lock/sha256",
            isolation=(
                "Only workflow-authored lock metadata changes; the manifest payload entry "
                "still matches current lock bytes."
            ),
        ),
    )

    additions = [
        {
            "id": "WORKFLOW-PARAMETER-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Use an authorized fixture certificate and correct subject but change the "
                "standard provenance workflow path."
            ),
            "prerequisites": [
                "standard_default_provenance_fixture_available",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("BUILDER_UNAUTHORIZED"),
            "mutation_contract": mutation_contract(
                authenticated_object="in_toto_statement",
                json_pointer="/predicate/buildDefinition/externalParameters/workflow/path",
                isolation=(
                    "Certificate identity, source dependency, builder, subject, manifest, and "
                    "payload remain valid."
                ),
            ),
        },
        {
            "id": "BUILDER-PREDICATE-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Use an authorized fixture certificate and correct workflow/source but change "
                "the authenticated provenance builder id."
            ),
            "prerequisites": [
                "standard_default_provenance_fixture_available",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("BUILDER_UNAUTHORIZED"),
            "mutation_contract": mutation_contract(
                authenticated_object="in_toto_statement",
                json_pointer="/predicate/runDetails/builder/id",
                isolation=(
                    "Certificate identity, workflow, source dependency, subject, manifest, and "
                    "payload remain valid."
                ),
            ),
        },
        {
            "id": "SOURCE-TREE-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Change authenticated manifest /build_metadata/source/tree while all payload "
                "entries and standard provenance remain unchanged."
            ),
            "prerequisites": [
                "selected_manifest_metadata_policy_frozen",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("MATERIAL_MISMATCH"),
            "mutation_contract": mutation_contract(
                authenticated_object="manifest",
                json_pointer="/build_metadata/source/tree",
                isolation="Only the workflow-authored Git-tree assertion changes.",
            ),
        },
        {
            "id": "SNAPSHOT-DIGEST-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Change authenticated manifest source-snapshot metadata SHA-256 while the "
                "snapshot payload entry and exact bytes remain unchanged."
            ),
            "prerequisites": [
                "selected_manifest_metadata_policy_frozen",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("MATERIAL_MISMATCH"),
            "mutation_contract": mutation_contract(
                authenticated_object="manifest",
                json_pointer="/build_metadata/source/snapshot/sha256",
                isolation=(
                    "Only opaque snapshot metadata changes; no tar-member equivalence claim "
                    "is introduced."
                ),
            ),
        },
        {
            "id": "SNAPSHOT-ROLE-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Keep snapshot metadata and bytes unchanged but assign its manifest payload "
                "entry a role different from the frozen source_code role."
            ),
            "prerequisites": [
                "selected_manifest_metadata_policy_frozen",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("MATERIAL_MISMATCH"),
            "mutation_contract": mutation_contract(
                authenticated_object="manifest",
                json_pointer="/payloads/{snapshot-entry}/role",
                isolation=(
                    "Only the snapshot payload role changes; digest, size, path, and bytes "
                    "remain valid."
                ),
            ),
        },
        {
            "id": "EXECUTION-IMAGE-MISMATCH-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Change authenticated manifest /build_metadata/execution_image/digest while "
                "the standard provenance, subject, and payload tree remain valid."
            ),
            "prerequisites": [
                "selected_manifest_metadata_policy_frozen",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations("MATERIAL_MISMATCH"),
            "mutation_contract": mutation_contract(
                authenticated_object="manifest",
                json_pointer="/build_metadata/execution_image/digest",
                isolation="Only the workflow-authored execution-image assertion changes.",
            ),
        },
        {
            "id": "BUILD-METADATA-MISSING-001",
            "family": "provenance",
            "kind": "target_invalid",
            "operation": (
                "Remove /build_metadata from a canonical manifest, re-attest the exact new "
                "manifest, and leave every payload byte unchanged."
            ),
            "prerequisites": [
                "selected_manifest_metadata_policy_frozen",
                "authorized_fixture_signer_available",
            ],
            "target_decision": "REJECT",
            "profile_expectations": expectations(
                "PROVENANCE_INVALID", p1_reason="SCHEMA_INVALID"
            ),
            "mutation_contract": mutation_contract(
                authenticated_object="manifest",
                json_pointer="/build_metadata",
                isolation=(
                    "The complete workflow-authored metadata object is removed; release and "
                    "payload inventory remain unchanged."
                ),
            ),
        },
    ]
    existing_ids = {case["id"] for case in cases}
    if existing_ids & {case["id"] for case in additions}:
        raise RuntimeError("selected-profile additions collide with historical case IDs")
    cases.extend(additions)
    cases.sort(key=lambda case: case["id"])
    return catalog


def build_prerequisite_registry() -> dict[str, Any]:
    historical = copy.deepcopy(load(HISTORICAL_PREREQUISITES))
    historical["schema_version"] = "0.2.0-draft"
    historical["status"] = "selected_profile_migration_not_frozen"
    historical["derived_from"] = {
        "path": HISTORICAL_PREREQUISITES,
        "sha256": sha256(STUDY_ROOT / HISTORICAL_PREREQUISITES),
    }
    by_id = {entry["id"]: entry for entry in historical["prerequisites"]}
    by_id["dirty_build_field_or_invariant_frozen"]["evidence_rule"] = (
        "Resolve only when /build_metadata/source/dirty, its false-only official-release "
        "rule, generator, oracle, and verifier are independently reviewed and frozen."
    )
    by_id["required_material_policy_frozen"]["evidence_rule"] = (
        "Resolve only when the selected manifest pointers, expected digests/roles, opaque "
        "snapshot assurance, and mismatch reasons are independently reviewed and frozen."
    )
    by_id["source_revision_policy_frozen"]["evidence_rule"] = (
        "Resolve only when the exact default-provenance resolved dependency URI/digest, full "
        "source OID, object format, repository URI, source ref, and matching manifest fields "
        "are independently reviewed and frozen."
    )
    additions = [
        {
            "id": "selected_manifest_metadata_policy_frozen",
            "source": "normative_policy",
            "draft_state": "PENDING",
            "evidence_rule": (
                "Resolve only when every enforced /build_metadata pointer, expected value, "
                "cross-bound payload role, reason, and opaque-snapshot boundary is independently "
                "reviewed and frozen."
            ),
        },
        {
            "id": "standard_default_provenance_fixture_available",
            "source": "controlled_fixture_contract",
            "draft_state": "TRUE",
            "evidence_rule": (
                "The selected fixture emits the pinned default-shape workflow build type, one "
                "workflow external parameter, one resolved Git dependency, and builder id."
            ),
            "claim_boundary": (
                "This is controlled Statement-shape coverage under public test PKI, not "
                "production actions/attest or Sigstore conformance."
            ),
        },
    ]
    if set(by_id) & {entry["id"] for entry in additions}:
        raise RuntimeError("selected prerequisite additions collide with historical IDs")
    historical["prerequisites"].extend(additions)
    historical["prerequisites"].sort(key=lambda entry: entry["id"])
    return historical


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog-output",
        type=Path,
        default=STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json",
    )
    parser.add_argument(
        "--prerequisite-output",
        type=Path,
        default=(
            STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json"
        ),
    )
    args = parser.parse_args()
    for path, value in (
        (args.catalog_output, build_catalog()),
        (args.prerequisite_output, build_prerequisite_registry()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(value), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
