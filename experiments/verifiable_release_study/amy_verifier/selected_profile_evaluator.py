"""Result-to-oracle join for selected-profile development and future runs.

The evaluator receives values from its caller and performs no file discovery.
It neither generates mutations nor derives expected labels.
"""

from __future__ import annotations

from typing import Any


def evaluate_selected_profile_result(
    case_id: str,
    observed: dict[str, Any],
    oracle_row: dict[str, Any],
) -> dict[str, Any]:
    required_oracle = {
        "case_id",
        "profile_id",
        "expected_decision",
        "expected_primary_reason",
        "catalog_json_pointer",
    }
    if set(oracle_row) != required_oracle:
        raise ValueError("oracle row shape differs from the closed evaluator input")
    if oracle_row["case_id"] != case_id:
        raise ValueError("case ID differs between caller and oracle row")
    if observed.get("profile_id") != oracle_row["profile_id"]:
        raise ValueError("profile ID differs between result and oracle row")
    observed_decision = observed.get("decision")
    observed_reason = observed.get("primary_reason")
    expected_decision = oracle_row["expected_decision"]
    expected_reason = oracle_row["expected_primary_reason"]
    conforms = (
        observed_decision == expected_decision and observed_reason == expected_reason
    )
    return {
        "case_id": case_id,
        "profile_id": oracle_row["profile_id"],
        "expected_decision": expected_decision,
        "expected_primary_reason": expected_reason,
        "observed_decision": observed_decision,
        "observed_primary_reason": observed_reason,
        "profile_conforms": conforms,
        "error_satisfies_expected_reject": False,
    }
