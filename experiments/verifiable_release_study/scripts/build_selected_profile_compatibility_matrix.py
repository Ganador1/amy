#!/usr/bin/env python3
"""Build selected-profile compatibility metadata without generating cases."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


STUDY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY_ROOT))

from amy_verifier.base_corpus import render_recipe, sha256_file
from amy_verifier.selected_profile_mutations import (
    MutationPlanUnavailable,
    resolve_mutation_plan,
)


DEFAULT_BASE_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
DEFAULT_PREREQUISITES = (
    STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_SELECTED_PROFILE_DRAFT.json"
)
DEFAULT_CATALOG = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
DEFAULT_BASE_RUN = (
    STUDY_ROOT
    / "selected_profile_base_runs/r0_selected_bases_20260713T101851Z"
)
COMPATIBILITY_STATES = {"COMPATIBLE", "NOT_COMPATIBLE", "PENDING"}
MUTATION_GENERATOR_PATH = STUDY_ROOT / "amy_verifier/selected_profile_mutations.py"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def derive_base_capabilities(
    base: dict[str, Any],
    base_run: Path,
    run_validation: dict[str, Any],
    effective_policy: dict[str, Any],
) -> dict[str, bool]:
    rendered = {
        payload["path"]: render_recipe(payload["recipe"])
        for payload in base["payloads"]
    }
    targets = base["mutation_targets"]
    release_root = base_run / "bases" / base["id"] / "release"
    manifest = load_json(release_root / "MANIFEST.jcs.json")
    manifest_payloads = manifest.get("payloads") or []
    roles = [payload["role"] for payload in manifest_payloads]
    role_by_path = {
        payload["path"]: payload["role"] for payload in manifest_payloads
    }
    sole_path = targets["sole_required_role_payload"]
    sole_role = role_by_path[sole_path]
    required_roles = set(
        effective_policy["manifest"]["required_roles_by_release_kind"][
            base["release"]["kind"]
        ]
    )
    valid_record = next(
        (
            record
            for record in run_validation.get("validated_bases", [])
            if record.get("base_id") == base["id"]
        ),
        None,
    )
    all_clean_accept = bool(
        valid_record
        and all(
            valid_record.get("clean_profile_results", {}).get(profile)
            == {"decision": "ACCEPT", "primary_reason": "OK"}
            for profile in ("P0", "P1", "P2", "P3")
        )
    )
    manifest_exists = (release_root / "MANIFEST.jcs.json").is_file()
    attestation_exists = (release_root / "attestation.sigstore.json").is_file()
    return {
        "base_release_valid_for_all_profiles": all_clean_accept,
        "listed_nested_regular_payload_exists": bool(
            targets["nested_payload"] in rendered
            and "/" in targets["nested_payload"].removeprefix("payload/")
            and rendered[targets["nested_payload"]]
        ),
        "listed_regular_payload_exists": bool(rendered),
        "listed_regular_payload_size_at_least_1": bool(
            rendered.get(targets["primary_nonempty_payload"], b"")
        ),
        "payload_directory_exists": (release_root / "payload").is_dir(),
        "required_role_has_exactly_one_payload": bool(
            sole_role in required_roles and roles.count(sole_role) == 1
        ),
        "valid_attestation_exists": attestation_exists and all_clean_accept,
        "valid_authorized_attestation_exists": attestation_exists and all_clean_accept,
        "valid_manifest_exists": manifest_exists and all_clean_accept,
        "valid_signature_exists": attestation_exists and all_clean_accept,
    }


def resolve_state(
    prerequisite: dict[str, Any], base_capabilities: dict[str, bool]
) -> tuple[str, str]:
    draft_state = prerequisite["draft_state"]
    if draft_state == "BASE_DERIVED":
        value = base_capabilities.get(prerequisite["id"])
        if value is None:
            raise ValueError(f"no base derivation for {prerequisite['id']}")
        return (
            "TRUE" if value else "FALSE",
            "selected_profile_clean_base_and_separate_same_worktree_validation",
        )
    if draft_state in {"TRUE", "FALSE", "PENDING"}:
        return draft_state, prerequisite["source"]
    raise ValueError(f"unsupported prerequisite state: {draft_state!r}")


def derive_rows(
    base_registry: dict[str, Any],
    prerequisite_registry: dict[str, Any],
    catalog: dict[str, Any],
    base_run: Path,
    run_validation: dict[str, Any],
    effective_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    if run_validation.get("valid") is not True:
        raise ValueError("selected-profile clean-base validation is not valid")
    if run_validation.get("confirmatory_cases_generated") is not False:
        raise ValueError("selected-profile base evidence is not R0-only")
    if run_validation.get("confirmatory_outcomes_read") is not False:
        raise ValueError("selected-profile base evidence accessed confirmatory outcomes")
    prerequisites = {
        entry["id"]: entry for entry in prerequisite_registry["prerequisites"]
    }
    catalog_prerequisites = {
        prerequisite
        for case in catalog["cases"]
        for prerequisite in case["prerequisites"]
    }
    if set(prerequisites) != catalog_prerequisites:
        raise ValueError(
            "prerequisite registry/catalog mismatch: "
            f"missing={sorted(catalog_prerequisites - set(prerequisites))}, "
            f"extra={sorted(set(prerequisites) - catalog_prerequisites)}"
        )

    rows: list[dict[str, Any]] = []
    bases = sorted(base_registry["bases"], key=lambda item: item["id"].encode("ascii"))
    cases = sorted(catalog["cases"], key=lambda item: item["id"].encode("ascii"))
    for base in bases:
        base_capabilities = derive_base_capabilities(
            base, base_run, run_validation, effective_policy
        )
        for case in cases:
            try:
                plan = resolve_mutation_plan(
                    case["id"], base=base, policy=effective_policy
                )
                plan_record = {
                    "status": "RESOLVED",
                    "reason_code": None,
                    "plan_sha256": plan.sha256(),
                    "plan": plan.record(),
                }
            except MutationPlanUnavailable as exc:
                plan_record = {
                    "status": "UNAVAILABLE",
                    "reason_code": exc.reason_code,
                    "plan_sha256": None,
                    "plan": None,
                }
            evaluations: list[dict[str, str]] = []
            states: list[str] = []
            for prerequisite_id in case["prerequisites"]:
                state, evidence_source = resolve_state(
                    prerequisites[prerequisite_id], base_capabilities
                )
                states.append(state)
                evaluations.append(
                    {
                        "id": prerequisite_id,
                        "state": state,
                        "evidence_source": evidence_source,
                    }
                )
            compatibility = (
                "NOT_COMPATIBLE"
                if "FALSE" in states or plan_record["status"] == "UNAVAILABLE"
                else "PENDING"
                if "PENDING" in states
                else "COMPATIBLE"
            )
            rows.append(
                {
                    "unit_id": f"{base['id']}--{case['id']}",
                    "stratum": "S1-CONFORMANCE",
                    "base_id": base["id"],
                    "base_release_kind": base["release"]["kind"],
                    "operator_id": case["id"],
                    "operator_family": case["family"],
                    "operator_kind": case["kind"],
                    "mutation_plan": plan_record,
                    "generator_blocking_reason": plan_record["reason_code"],
                    "compatibility": compatibility,
                    "prerequisites": evaluations,
                    "blocking_false": sorted(
                        evaluation["id"]
                        for evaluation in evaluations
                        if evaluation["state"] == "FALSE"
                    ),
                    "blocking_pending": sorted(
                        evaluation["id"]
                        for evaluation in evaluations
                        if evaluation["state"] == "PENDING"
                    ),
                }
            )
    return rows


def build_matrix(
    base_registry_path: Path = DEFAULT_BASE_REGISTRY,
    prerequisite_path: Path = DEFAULT_PREREQUISITES,
    catalog_path: Path = DEFAULT_CATALOG,
    base_run: Path = DEFAULT_BASE_RUN,
) -> dict[str, Any]:
    base_registry = load_json(base_registry_path)
    prerequisite_registry = load_json(prerequisite_path)
    catalog = load_json(catalog_path)
    validation_path = base_run / "validation.json"
    summary_path = base_run / "summary.json"
    policy_path = base_run / "effective_fixture_policy.jcs.json"
    run_validation = load_json(validation_path)
    effective_policy = load_json(policy_path)
    rows = derive_rows(
        base_registry,
        prerequisite_registry,
        catalog,
        base_run,
        run_validation,
        effective_policy,
    )
    counts = Counter(row["compatibility"] for row in rows)
    plan_counts = Counter(row["mutation_plan"]["status"] for row in rows)
    if set(counts) - COMPATIBILITY_STATES:
        raise AssertionError("unknown compatibility state")
    return {
        "schema_version": "amy.selected-profile-compatibility-matrix.v1-draft",
        "status": "selected_profile_draft_with_pending_prerequisites_not_frozen",
        "classification": "R0_metadata_only_no_case_generation_or_execution",
        "selected_profile": (
            "standard_provenance_plus_authenticated_manifest_metadata"
        ),
        "stratum": "S1-CONFORMANCE",
        "atomic_unit": "base_release_id × mutation_operator_id",
        "uses_profile_expectations": False,
        "uses_target_decisions": False,
        "uses_confirmatory_mutation_outcomes": False,
        "uses_observed_clean_base_validation": True,
        "uses_base_aware_mutation_plan_resolution": True,
        "mutation_plan_resolution_uses_outcomes": False,
        "catalog_fields_used": [
            "cases[].id",
            "cases[].family",
            "cases[].kind",
            "cases[].prerequisites",
        ],
        "clean_base_evidence_boundary": (
            "Only clean-base ACCEPT/OK establishes structural fixture availability; no "
            "mutated-case result is present or read."
        ),
        "input_sha256": {
            "base_registry": sha256_file(base_registry_path),
            "prerequisite_registry": sha256_file(prerequisite_path),
            "attack_catalog": sha256_file(catalog_path),
            "selected_base_run_summary": sha256_file(summary_path),
            "selected_base_run_validation": sha256_file(validation_path),
            "selected_effective_fixture_policy": sha256_file(policy_path),
            "selected_profile_mutation_generator": sha256_file(
                MUTATION_GENERATOR_PATH
            ),
        },
        "candidate_unit_count": len(rows),
        "compatibility_counts": {
            state: counts.get(state, 0)
            for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
        },
        "mutation_plan_counts": {
            state: plan_counts.get(state, 0) for state in ("RESOLVED", "UNAVAILABLE")
        },
        "planned_if_all_pending_resolve_true": (
            counts.get("COMPATIBLE", 0) + counts.get("PENDING", 0)
        ),
        "rows": rows,
        "limitations": [
            "Compatibility is a structural precondition classification, not a verifier outcome.",
            "PENDING rows cannot enter a frozen confirmatory corpus until their named prerequisites resolve.",
            "The clean-base cryptographic fixture is controlled public test PKI, not production Sigstore.",
            "The matrix does not establish that a mutation implementation changes only its declared factor."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-registry", type=Path, default=DEFAULT_BASE_REGISTRY)
    parser.add_argument("--prerequisites", type=Path, default=DEFAULT_PREREQUISITES)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--base-run", type=Path, default=DEFAULT_BASE_RUN)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_matrix(
        args.base_registry.resolve(),
        args.prerequisites.resolve(),
        args.catalog.resolve(),
        args.base_run.resolve(),
    )
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
