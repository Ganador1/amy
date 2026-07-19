#!/usr/bin/env python3
"""Validate selected-profile compatibility completeness and outcome blindness."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import posixpath
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785

STUDY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = STUDY_ROOT / "scripts"
sys.path.insert(0, str(STUDY_ROOT))
sys.path.insert(0, str(SCRIPTS))

from amy_verifier.base_corpus import render_recipe, sha256_file
from build_selected_profile_compatibility_matrix import (
    DEFAULT_BASE_REGISTRY,
    DEFAULT_BASE_RUN,
    DEFAULT_CATALOG,
    DEFAULT_PREREQUISITES,
    MUTATION_GENERATOR_PATH,
    build_matrix,
    derive_rows,
)
from validate_selected_profile_base_run import validate as validate_base_run


DEFAULT_MATRIX = (
    STUDY_ROOT / "corpus/COMPATIBILITY_MATRIX_SELECTED_PROFILE_DRAFT.json"
)
FORBIDDEN_ROW_KEYS = {
    "profile_expectations",
    "expected_decision",
    "expected_primary_reason",
    "observed_decision",
    "observed_result",
    "target_decision",
}
PRIMARY_PLAN_CASES = {
    "CONTENT-BITFLIP-001",
    "CONTENT-TRUNCATE-001",
    "CONTENT-SAME-SIZE-001",
    "PATH-DUPLICATE-NORMALIZED-001",
    "PATH-NONREGULAR-001",
    "PATH-SYMLINK-001",
    "SUBSTITUTION-COHERENT-001",
    "SUBSTITUTION-UNAUTHORIZED-001",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _separate_validator_base_capabilities(
    base: dict[str, Any],
    base_run: Path,
    separately_validated_run: dict[str, Any],
    effective_policy: dict[str, Any],
) -> dict[str, bool]:
    rendered = {
        entry["path"]: render_recipe(entry["recipe"])
        for entry in base["payloads"]
    }
    targets = base["mutation_targets"]
    release_root = base_run / "bases" / base["id"] / "release"
    manifest = load_json(release_root / "MANIFEST.jcs.json")
    manifest_payloads = manifest.get("payloads") or []
    role_by_path = {entry["path"]: entry["role"] for entry in manifest_payloads}
    sole_role = role_by_path[targets["sole_required_role_payload"]]
    roles = [entry["role"] for entry in manifest_payloads]
    required_roles = set(
        effective_policy["manifest"]["required_roles_by_release_kind"][
            base["release"]["kind"]
        ]
    )
    record = next(
        (
            item
            for item in separately_validated_run.get("validated_bases", [])
            if item.get("base_id") == base["id"]
        ),
        None,
    )
    all_clean_accept = bool(
        record
        and all(
            (record.get("clean_profile_results") or {}).get(profile)
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
        "required_role_has_exactly_one_payload": (
            sole_role in required_roles and roles.count(sole_role) == 1
        ),
        "valid_attestation_exists": attestation_exists and all_clean_accept,
        "valid_authorized_attestation_exists": attestation_exists and all_clean_accept,
        "valid_manifest_exists": manifest_exists and all_clean_accept,
        "valid_signature_exists": attestation_exists and all_clean_accept,
    }


def _independent_expected_mutation_plan(
    base: dict[str, Any], case_id: str, policy: dict[str, Any]
) -> dict[str, Any]:
    targets = dict(base["mutation_targets"])
    targets.setdefault("hardlink_target", targets["primary_nonempty_payload"])
    payload_by_path = {item["path"]: item for item in base["payloads"]}
    effective_payloads = list(base["payloads"]) + list(
        policy["fixture_payloads"].values()
    )
    target_path: str | None = None
    source_path: str | None = None
    target_role: str | None = None
    generated_path: str | None = None
    generated_strategy: str | None = None
    symlink_target: str | None = None

    if case_id in PRIMARY_PLAN_CASES:
        target_path = targets["primary_nonempty_payload"]
    elif case_id == "INVENTORY-MISSING-001":
        target_path = targets["nested_payload"]
    elif case_id == "INVENTORY-OMIT-ROLE-001":
        target_path = targets["sole_required_role_payload"]
        target_role = payload_by_path[target_path]["role"]
        if sum(item.get("role") == target_role for item in effective_payloads) != 1:
            return {
                "status": "UNAVAILABLE",
                "reason_code": "TARGET_REQUIRED_ROLE_NOT_UNIQUE",
                "plan_sha256": None,
                "plan": None,
            }
    elif case_id == "PATH-HARDLINK-001":
        target_path = targets["hardlink_target"]
        source_path = targets["same_bytes_source"]

    payload_paths = set(payload_by_path) | {
        item["path"] for item in policy["fixture_payloads"].values()
    }
    if case_id == "INVENTORY-EXTRA-001":
        generated_path = "payload/unlisted.txt"
        if generated_path in payload_paths:
            for counter in range(65_536):
                seed = hashlib.sha256(
                    f"{base['id']}\x00{case_id}\x00{counter}".encode("utf-8")
                ).hexdigest()[:16]
                candidate = f"payload/__amy_generated__/unlisted-{seed}.bin"
                if candidate not in payload_paths:
                    generated_path = candidate
                    break
            else:
                raise AssertionError(
                    "independent generator cannot find a collision-free path"
                )
        generated_strategy = "DETERMINISTIC_UNLISTED_PAYLOAD"
    elif case_id == "PATH-PARENT-001":
        generated_path = "payload/../amy-parent-escape.txt"
        generated_strategy = "INTENTIONAL_PARENT_SEGMENT_MANIFEST_ENTRY"
    elif case_id == "PATH-DUPLICATE-NORMALIZED-001":
        logical = PurePosixPath(target_path or "")
        candidate = logical.name.upper()
        if candidate == logical.name:
            candidate = logical.name.lower()
        generated_path = logical.with_name(candidate).as_posix()
        generated_strategy = "CASEFOLD_DUPLICATE_OF_TARGET"
    elif case_id == "PATH-SYMLINK-001":
        parent_depth = len(PurePosixPath(target_path or "").parent.parts)
        symlink_target = "../" * (parent_depth + 1) + "amy-outside-target.bin"
        joined = posixpath.normpath(
            posixpath.join(posixpath.dirname(target_path or ""), symlink_target)
        )
        if not joined.startswith("../"):
            raise AssertionError("independent symlink target is not outside the release")

    plan = {
        "schema_version": "amy.selected-profile-mutation-plan.v1-draft",
        "base_id": base["id"],
        "case_id": case_id,
        "mutation_targets_sha256": hashlib.sha256(rfc8785.dumps(targets)).hexdigest(),
        "target_path": target_path,
        "source_path": source_path,
        "target_role": target_role,
        "generated_path": generated_path,
        "generated_path_strategy": generated_strategy,
        "symlink_target": symlink_target,
        "contains_expected_or_observed_decisions": False,
        "confirmatory_evidence": False,
    }
    return {
        "status": "RESOLVED",
        "reason_code": None,
        "plan_sha256": hashlib.sha256(rfc8785.dumps(plan)).hexdigest(),
        "plan": plan,
    }


def _counterfactual_outcome_invariance(
    bases: dict[str, Any],
    prerequisites: dict[str, Any],
    catalog: dict[str, Any],
    base_run: Path,
    run_validation: dict[str, Any],
    policy: dict[str, Any],
    retained_rows: list[dict[str, Any]],
) -> bool:
    poisoned = copy.deepcopy(catalog)
    for index, case in enumerate(poisoned["cases"]):
        case["profile_expectations"] = {
            "COUNTERFACTUAL": {
                "decision": "ACCEPT" if index % 2 else "REJECT",
                "primary_reason": f"POISON-{index}",
            }
        }
        case["target_decision"] = "ACCEPT" if index % 2 else "REJECT"
        case["observed_decision"] = "COUNTERFACTUAL-NOT-AN-INPUT"
    counterfactual_rows = derive_rows(
        bases,
        prerequisites,
        poisoned,
        base_run,
        run_validation,
        policy,
    )
    return counterfactual_rows == retained_rows


def validate(matrix_path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    errors: list[str] = []
    matrix = load_json(matrix_path)
    bases = load_json(DEFAULT_BASE_REGISTRY)
    prerequisites = load_json(DEFAULT_PREREQUISITES)
    catalog = load_json(DEFAULT_CATALOG)
    run_validation_path = DEFAULT_BASE_RUN / "validation.json"
    run_summary_path = DEFAULT_BASE_RUN / "summary.json"
    policy_path = DEFAULT_BASE_RUN / "effective_fixture_policy.jcs.json"
    retained_run_validation = load_json(run_validation_path)
    policy = load_json(policy_path)
    separate_run_validation = validate_base_run(DEFAULT_BASE_RUN)

    if not separate_run_validation["valid"]:
        errors.append("selected-profile base run fails separate same-worktree replay")
    if separate_run_validation.get("confirmatory_cases_generated") is not False:
        errors.append("selected-profile base run is not clean R0 evidence")
    if separate_run_validation.get("confirmatory_outcomes_read") is not False:
        errors.append("selected-profile base replay accessed confirmatory outcomes")
    expected_hashes = {
        "base_registry": sha256_file(DEFAULT_BASE_REGISTRY),
        "prerequisite_registry": sha256_file(DEFAULT_PREREQUISITES),
        "attack_catalog": sha256_file(DEFAULT_CATALOG),
        "selected_base_run_summary": sha256_file(run_summary_path),
        "selected_base_run_validation": sha256_file(run_validation_path),
        "selected_effective_fixture_policy": sha256_file(policy_path),
        "selected_profile_mutation_generator": sha256_file(
            MUTATION_GENERATOR_PATH
        ),
    }
    if matrix.get("input_sha256") != expected_hashes:
        errors.append("matrix input hashes differ from current selected-profile inputs")
    if matrix.get("classification") != "R0_metadata_only_no_case_generation_or_execution":
        errors.append("matrix is not classified as R0 metadata only")
    expected_flags = {
        "uses_profile_expectations": False,
        "uses_target_decisions": False,
        "uses_confirmatory_mutation_outcomes": False,
        "uses_observed_clean_base_validation": True,
        "uses_base_aware_mutation_plan_resolution": True,
        "mutation_plan_resolution_uses_outcomes": False,
    }
    for flag, expected in expected_flags.items():
        if matrix.get(flag) is not expected:
            errors.append(f"matrix evidence-use flag differs: {flag}")
    if matrix.get("catalog_fields_used") != [
        "cases[].id",
        "cases[].family",
        "cases[].kind",
        "cases[].prerequisites",
    ]:
        errors.append("matrix catalog-field declaration differs")

    prerequisite_by_id = {
        entry["id"]: entry for entry in prerequisites["prerequisites"]
    }
    base_by_id = {base["id"]: base for base in bases["bases"]}
    case_by_id = {case["id"]: case for case in catalog["cases"]}
    expected_pairs = [
        (base_id, case_id)
        for base_id in sorted(base_by_id, key=lambda value: value.encode("ascii"))
        for case_id in sorted(case_by_id, key=lambda value: value.encode("ascii"))
    ]
    rows = matrix.get("rows") or []
    observed_pairs = [(row.get("base_id"), row.get("operator_id")) for row in rows]
    if observed_pairs != expected_pairs:
        errors.append("rows are not the complete sorted base × operator Cartesian product")
    if matrix.get("candidate_unit_count") != len(expected_pairs):
        errors.append("candidate unit count differs from Cartesian product")
    unit_ids = [row.get("unit_id") for row in rows]
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("duplicate compatibility unit IDs")

    capabilities = {
        base_id: _separate_validator_base_capabilities(
            base, DEFAULT_BASE_RUN, separate_run_validation, policy
        )
        for base_id, base in base_by_id.items()
    }
    state_counts: Counter[str] = Counter()
    plan_state_counts: Counter[str] = Counter()
    forbidden_rows = 0
    for row in rows:
        base_id = row.get("base_id")
        operator_id = row.get("operator_id")
        case = case_by_id.get(operator_id)
        base = base_by_id.get(base_id)
        if case is None or base is None:
            continue
        forbidden_present = FORBIDDEN_ROW_KEYS & set(row)
        if forbidden_present:
            forbidden_rows += 1
            errors.append(
                f"{row.get('unit_id')}: contains forbidden outcome fields "
                f"{sorted(forbidden_present)}"
            )
        expected_metadata = {
            "unit_id": f"{base_id}--{operator_id}",
            "stratum": "S1-CONFORMANCE",
            "base_release_kind": base["release"]["kind"],
            "operator_family": case["family"],
            "operator_kind": case["kind"],
        }
        for field, expected in expected_metadata.items():
            if row.get(field) != expected:
                errors.append(f"{row.get('unit_id')}: metadata mismatch for {field}")
        expected_plan = _independent_expected_mutation_plan(base, operator_id, policy)
        observed_plan = row.get("mutation_plan")
        if observed_plan != expected_plan:
            errors.append(f"{row.get('unit_id')}: mutation plan differs")
        plan_state_counts[(observed_plan or {}).get("status")] += 1
        if row.get("generator_blocking_reason") != expected_plan["reason_code"]:
            errors.append(f"{row.get('unit_id')}: generator blocking reason differs")
        if expected_plan["status"] == "RESOLVED":
            plan_payload = (observed_plan or {}).get("plan") or {}
            if plan_payload.get("contains_expected_or_observed_decisions") is not False:
                errors.append(
                    f"{row.get('unit_id')}: mutation plan crossed outcome boundary"
                )
            if plan_payload.get("confirmatory_evidence") is not False:
                errors.append(
                    f"{row.get('unit_id')}: mutation plan claims confirmatory evidence"
                )
        elif (observed_plan or {}).get("plan") is not None or (
            observed_plan or {}
        ).get("plan_sha256") is not None:
            errors.append(
                f"{row.get('unit_id')}: unavailable mutation plan contains a payload"
            )
        evaluations = row.get("prerequisites") or []
        if [entry.get("id") for entry in evaluations] != case["prerequisites"]:
            errors.append(f"{row.get('unit_id')}: prerequisite order/set mismatch")
        states: list[str] = []
        for evaluation in evaluations:
            prerequisite_id = evaluation.get("id")
            prerequisite = prerequisite_by_id.get(prerequisite_id)
            state = evaluation.get("state")
            states.append(state)
            if prerequisite is None:
                errors.append(f"{row.get('unit_id')}: unknown prerequisite")
                continue
            draft_state = prerequisite["draft_state"]
            if draft_state == "BASE_DERIVED":
                expected_state = (
                    "TRUE" if capabilities[base_id][prerequisite_id] else "FALSE"
                )
                expected_source = (
                    "selected_profile_clean_base_and_separate_same_worktree_validation"
                )
            else:
                expected_state = draft_state
                expected_source = prerequisite["source"]
            if state != expected_state:
                errors.append(
                    f"{row.get('unit_id')}: prerequisite {prerequisite_id} "
                    f"state {state!r} != {expected_state!r}"
                )
            if evaluation.get("evidence_source") != expected_source:
                errors.append(
                    f"{row.get('unit_id')}: prerequisite evidence source differs"
                )
        expected_compatibility = (
            "NOT_COMPATIBLE"
            if "FALSE" in states or expected_plan["status"] == "UNAVAILABLE"
            else "PENDING"
            if "PENDING" in states
            else "COMPATIBLE"
        )
        compatibility = row.get("compatibility")
        state_counts[compatibility] += 1
        if compatibility != expected_compatibility:
            errors.append(f"{row.get('unit_id')}: compatibility resolution mismatch")
        expected_false = sorted(
            entry["id"] for entry in evaluations if entry.get("state") == "FALSE"
        )
        expected_pending = sorted(
            entry["id"] for entry in evaluations if entry.get("state") == "PENDING"
        )
        if row.get("blocking_false") != expected_false:
            errors.append(f"{row.get('unit_id')}: false blocker list mismatch")
        if row.get("blocking_pending") != expected_pending:
            errors.append(f"{row.get('unit_id')}: pending blocker list mismatch")

    expected_counts = {
        state: state_counts.get(state, 0)
        for state in ("COMPATIBLE", "PENDING", "NOT_COMPATIBLE")
    }
    if matrix.get("compatibility_counts") != expected_counts:
        errors.append("compatibility summary counts differ from rows")
    expected_plan_counts = {
        state: plan_state_counts.get(state, 0)
        for state in ("RESOLVED", "UNAVAILABLE")
    }
    if matrix.get("mutation_plan_counts") != expected_plan_counts:
        errors.append("mutation-plan summary counts differ from rows")
    if matrix.get("planned_if_all_pending_resolve_true") != (
        expected_counts["COMPATIBLE"] + expected_counts["PENDING"]
    ):
        errors.append("conditional planned-unit count differs from rows")

    fresh = build_matrix()
    deterministic_replay = canonical_json(fresh) == canonical_json(matrix)
    if not deterministic_replay:
        errors.append("retained matrix differs from deterministic fresh builder output")
    counterfactual_invariant = _counterfactual_outcome_invariance(
        bases,
        prerequisites,
        catalog,
        DEFAULT_BASE_RUN,
        retained_run_validation,
        policy,
        rows,
    )
    if not counterfactual_invariant:
        errors.append("matrix rows change when target/expectation outcomes are poisoned")
    return {
        "schema_version": "amy.selected-profile-compatibility-validation.v1-draft",
        "valid": not errors,
        "classification": "R0_outcome_blind_structural_replay",
        "matrix_sha256": sha256_file(matrix_path),
        "matrix_canonical_sha256": hashlib.sha256(canonical_json(matrix)).hexdigest(),
        "fresh_matrix_canonical_sha256": hashlib.sha256(canonical_json(fresh)).hexdigest(),
        "candidate_unit_count": len(rows),
        "compatibility_counts": expected_counts,
        "mutation_plan_counts": expected_plan_counts,
        "outcome_blinded": forbidden_rows == 0 and counterfactual_invariant,
        "counterfactual_outcome_fields_invariant": counterfactual_invariant,
        "deterministic_replay_identical": deterministic_replay,
        "selected_base_run_separate_validator_valid": separate_run_validation["valid"],
        "confirmatory_cases_generated": False,
        "confirmatory_outcomes_read": False,
        "errors": errors,
        "limitations": [
            "Outcome blindness is demonstrated for declared target/expectation fields, not proven for every possible covert channel.",
            "Clean-base ACCEPT/OK is used only to establish fixture availability.",
            "No compatibility label is itself an empirical verifier result."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", nargs="?", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = validate(args.matrix.resolve())
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
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
