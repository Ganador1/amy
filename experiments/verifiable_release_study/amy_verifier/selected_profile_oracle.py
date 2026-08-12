"""Deterministic draft oracle derived only from the selected attack catalog.

The module does not import a verifier, generator, evaluator, pilot run, or
confirmatory result.  Human review of the resulting rows remains a separate
blocking registration gate.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .json_tools import bounded_regular_file_read, parse_json_bytes


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = STUDY_ROOT / "protocol/ATTACK_CATALOG_SELECTED_PROFILE_DRAFT.json"
DEFAULT_RESULT_SCHEMA_PATH = STUDY_ROOT / "schemas/selected-profile-fixture-result.schema.json"
PROFILES = ("P0", "P1", "P2", "P3")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: Path, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    raw = bounded_regular_file_read(path, max_bytes, check="bounded_input")
    value = parse_json_bytes(
        raw,
        max_depth=64,
        reject_duplicate_keys=True,
        failure_check="bounded_input",
    )
    if not isinstance(value, dict):
        raise RuntimeError(f"oracle source is not a JSON object: {path}")
    return value, raw


def build_selected_profile_oracle(
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    result_schema_path: Path = DEFAULT_RESULT_SCHEMA_PATH,
) -> dict[str, Any]:
    catalog, catalog_raw = _load_object(catalog_path, max_bytes=4 * 1024 * 1024)
    result_schema, result_schema_raw = _load_object(
        result_schema_path, max_bytes=1024 * 1024
    )
    if catalog.get("catalog_version") != "0.4.0-draft":
        raise RuntimeError("selected oracle requires catalog v0.4.0-draft")
    if catalog.get("status") != "selected_profile_migration_not_frozen_not_executed":
        raise RuntimeError("selected catalog status does not preserve the pre-execution boundary")

    catalog_profiles = tuple(profile.get("id") for profile in catalog.get("profiles") or [])
    if catalog_profiles != PROFILES:
        raise RuntimeError("selected catalog profile order differs from the oracle contract")
    cases = catalog.get("cases")
    if not isinstance(cases, list) or len(cases) != 41:
        raise RuntimeError("selected oracle requires exactly 41 catalog cases")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids):
        raise RuntimeError("selected catalog case IDs are malformed or duplicated")

    reason_vocabulary = set(
        result_schema.get("$defs", {}).get("reasonCode", {}).get("enum", [])
    )
    rows: list[dict[str, Any]] = []
    for case_index, case in sorted(
        enumerate(cases), key=lambda item: str(item[1].get("id")).encode("utf-8")
    ):
        expectations = case.get("profile_expectations")
        if not isinstance(expectations, dict) or set(expectations) != set(PROFILES):
            raise RuntimeError(f"{case.get('id')}: profile expectations are incomplete")
        for profile_id in PROFILES:
            expected = expectations[profile_id]
            if not isinstance(expected, dict) or set(expected) != {
                "decision",
                "primary_reason",
            }:
                raise RuntimeError(
                    f"{case.get('id')}/{profile_id}: expectation shape differs"
                )
            decision = expected["decision"]
            reason = expected["primary_reason"]
            if decision not in {"ACCEPT", "REJECT"} or reason not in reason_vocabulary:
                raise RuntimeError(
                    f"{case.get('id')}/{profile_id}: expectation vocabulary differs"
                )
            if (decision == "ACCEPT") != (reason == "OK"):
                raise RuntimeError(
                    f"{case.get('id')}/{profile_id}: decision/reason pair is inconsistent"
                )
            rows.append(
                {
                    "case_id": case["id"],
                    "profile_id": profile_id,
                    "expected_decision": decision,
                    "expected_primary_reason": reason,
                    "catalog_json_pointer": (
                        f"/cases/{case_index}/profile_expectations/{profile_id}"
                    ),
                }
            )

    return {
        "schema_version": "amy.selected-profile-oracle.v1-draft",
        "status": "draft_same_author_not_independently_reviewed_not_frozen",
        "source_catalog": {
            "path": catalog_path.relative_to(STUDY_ROOT).as_posix(),
            "sha256": _sha256(catalog_raw),
            "catalog_version": catalog["catalog_version"],
        },
        "result_contract": {
            "path": result_schema_path.relative_to(STUDY_ROOT).as_posix(),
            "sha256": _sha256(result_schema_raw),
        },
        "derivation_boundary": {
            "source_fields": ["cases[].id", "cases[].profile_expectations"],
            "observed_results_read": False,
            "confirmatory_cases_read": False,
            "confirmatory_cases_executed": False,
            "target_decisions_used_as_profile_expectations": False,
            "implementation_behavior_used_to_generate_rows": False,
            "independent_human_review_complete": False,
            "classification": "pre_registration_expected_implementation_behavior",
        },
        "profiles": list(PROFILES),
        "case_count": len(cases),
        "row_count": len(rows),
        "rows": rows,
    }
