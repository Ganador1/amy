from __future__ import annotations

import json
from pathlib import Path


def test_branch_quality_flags_repair_and_score_bottlenecks():
    from scripts.run.branch_quality import analyze_run

    summary = analyze_run(
        {
            "domain": "mathematics",
            "model": "glm-5.2",
            "tool_results": [{"tool": "prime_gap_analysis"}] * 3,
            "failed_results": [],
            "paper": {
                "publication_status": "published",
                "grounding_repair": {"repairs": 2},
            },
            "reflection": {"pass_overall": True},
            "rubric": {
                "total": 88.0,
                "per_dim": {
                    "tool_diversity": 7.0,
                    "falsifiability": 8.0,
                    "statistical_rigor": 6.5,
                },
            },
            "discussion": {"total": 85.0},
        },
        path=Path("experiments/e2e_validation/e2e_mathematics_20260702_225316.json"),
    )

    keys = {item.key for item in summary.bottlenecks}
    assert "grounding_repair" in keys
    assert "rubric_total" in keys
    assert "rubric_tool_diversity" in keys
    assert summary.meets_targets is False
    assert any("independent control" in action for action in summary.next_actions)
    assert any("missing numeric metrics" in action for action in summary.next_actions)


def test_branch_playbooks_cover_e2e_domains_with_single_objective_contracts():
    from scripts.run.branch_quality import DOMAIN_BRANCH_PLAYBOOKS
    from scripts.run.run_e2e_validation import DOMAIN_PLANS

    for domain in DOMAIN_PLANS:
        playbook = DOMAIN_BRANCH_PLAYBOOKS[domain]
        roles = {step["role"] for step in playbook["experiment_contract"]}

        assert playbook["objective"]
        assert "baseline" in roles
        assert "alternative_or_perturbation" in roles
        assert "independent_control" in roles
        assert playbook["stop_rule"]["rubric_total"] >= 90.0


def test_select_latest_per_domain_uses_timestamped_json_paths(tmp_path):
    from scripts.run.branch_quality import select_latest_per_domain

    older = tmp_path / "e2e_mathematics_20260702_170115.json"
    newer = tmp_path / "e2e_mathematics_20260702_225316.json"
    biology = tmp_path / "e2e_biology_20260702_172300.json"
    for path, domain in [(older, "mathematics"), (newer, "mathematics"), (biology, "biology")]:
        path.write_text(json.dumps({"domain": domain}), encoding="utf-8")

    selected = select_latest_per_domain([older, newer, biology])

    assert selected["mathematics"] == newer
    assert selected["biology"] == biology
