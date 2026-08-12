#!/usr/bin/env python3
"""Build compatibility metadata only; never generate or execute mutation cases."""

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


DEFAULT_BASE_REGISTRY = STUDY_ROOT / "corpus/BASE_REGISTRY_DRAFT.json"
DEFAULT_PREREQUISITES = STUDY_ROOT / "protocol/PREREQUISITE_REGISTRY_DRAFT.json"
DEFAULT_CATALOG = STUDY_ROOT / "protocol/ATTACK_CATALOG.json"
DEFAULT_BASE_RUN = STUDY_ROOT / "base_pilot_runs/r0_bases_20260713T065228Z"
COMPATIBILITY_STATES = {"COMPATIBLE", "NOT_COMPATIBLE", "PENDING"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def derive_base_capabilities(
    base: dict[str, Any], base_run: Path, run_validation: dict[str, Any]
) -> dict[str, bool]:
    rendered = {
        payload["path"]: render_recipe(payload["recipe"])
        for payload in base["payloads"]
    }
    targets = base["mutation_targets"]
    required_roles_by_kind = {
        "benchmark_case": {"analysis_code", "analysis_output", "raw_data"},
        "scientific_paper": {
            "analysis_code",
            "analysis_output",
            "environment_lock",
            "evidence_ledger",
            "manuscript_render",
            "manuscript_source",
        },
        "model_artifact": {"model", "model_metadata"},
        "model_exchange": {
            "model_exchange_request",
            "model_exchange_response",
            "model_metadata",
        },
        "software_release": {"environment_lock", "source_code"},
        "mixed_research_release": {
            "analysis_code",
            "analysis_output",
            "environment_lock",
            "evidence_ledger",
        },
    }
    roles = [payload["role"] for payload in base["payloads"]]
    role_by_path = {payload["path"]: payload["role"] for payload in base["payloads"]}
    sole_path = targets["sole_required_role_payload"]
    sole_role = role_by_path[sole_path]
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
    release_root = base_run / "bases" / base["id"] / "release"
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
            sole_role in required_roles_by_kind[base["release"]["kind"]]
            and roles.count(sole_role) == 1
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
        return ("TRUE" if value else "FALSE", "base_blueprint_and_retained_clean_validation")
    if draft_state in {"TRUE", "FALSE", "PENDING"}:
        return draft_state, prerequisite["source"]
    raise ValueError(f"unsupported prerequisite state: {draft_state!r}")


def build_matrix(
    base_registry_path: Path,
    prerequisite_path: Path,
    catalog_path: Path,
    base_run: Path,
) -> dict[str, Any]:
    base_registry = load_json(base_registry_path)
    prerequisite_registry = load_json(prerequisite_path)
    catalog = load_json(catalog_path)
    run_validation = load_json(base_run / "validation.json")
    if run_validation.get("valid") is not True:
        raise ValueError("retained clean-base run is not independently valid")

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
    for base in sorted(base_registry["bases"], key=lambda item: item["id"].encode("ascii")):
        base_capabilities = derive_base_capabilities(base, base_run, run_validation)
        for case in sorted(catalog["cases"], key=lambda item: item["id"].encode("ascii")):
            evaluations = []
            states = []
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
            if "FALSE" in states:
                compatibility = "NOT_COMPATIBLE"
            elif "PENDING" in states:
                compatibility = "PENDING"
            else:
                compatibility = "COMPATIBLE"
            rows.append(
                {
                    "unit_id": f"{base['id']}--{case['id']}",
                    "stratum": "S1-CONFORMANCE",
                    "base_id": base["id"],
                    "base_release_kind": base["release"]["kind"],
                    "operator_id": case["id"],
                    "operator_family": case["family"],
                    "operator_kind": case["kind"],
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

    counts = Counter(row["compatibility"] for row in rows)
    if set(counts) - COMPATIBILITY_STATES:
        raise AssertionError("unknown compatibility state")
    return {
        "schema_version": "amy.compatibility-matrix.v1-draft",
        "status": "draft_with_pending_prerequisites_not_frozen",
        "classification": "R0_metadata_only_no_case_generation_or_execution",
        "stratum": "S1-CONFORMANCE",
        "atomic_unit": "base_release_id × mutation_operator_id",
        "uses_profile_expectations": False,
        "uses_observed_decisions": False,
        "uses_target_decisions": False,
        "catalog_fields_used": ["cases[].id", "cases[].family", "cases[].kind", "cases[].prerequisites"],
        "input_sha256": {
            "base_registry": sha256_file(base_registry_path),
            "prerequisite_registry": sha256_file(prerequisite_path),
            "attack_catalog": sha256_file(catalog_path),
            "base_run_validation": sha256_file(base_run / "validation.json"),
        },
        "candidate_unit_count": len(rows),
        "compatibility_counts": {
            state: counts.get(state, 0)
            for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
        },
        "planned_if_all_pending_resolve_true": (
            counts.get("COMPATIBLE", 0) + counts.get("PENDING", 0)
        ),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-registry", type=Path, default=DEFAULT_BASE_REGISTRY)
    parser.add_argument("--prerequisites", type=Path, default=DEFAULT_PREREQUISITES)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--base-run", type=Path, default=DEFAULT_BASE_RUN)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_matrix(
        args.base_registry, args.prerequisites, args.catalog, args.base_run
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
