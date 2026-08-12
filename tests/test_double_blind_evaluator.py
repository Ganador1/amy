#!/usr/bin/env python3
"""Regression tests for the double-blind evaluator validity controls."""
import asyncio
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from double_blind_evaluator import (
    DoubleBlindEvaluator,
    REVIEWER_B_MODEL,
    RUBRIC_DIMENSIONS,
    anonymize_paper,
)
from run_double_blind_eval import analyze_results, generate_final_report


def _review(score: int = 5, recommendation: str = "REVISE") -> dict:
    return {
        "scores": {dim: score for dim in RUBRIC_DIMENSIONS},
        "concerns": [],
        "strengths": [],
        "recommendation": recommendation,
        "confidence": 5,
        "summary": "Synthetic test review.",
    }


def _weighted_kappa_fixed_scale(a_scores: list[int], b_scores: list[int]) -> float:
    categories = list(range(1, 8))
    cat_to_idx = {cat: i for i, cat in enumerate(categories)}
    matrix = [[0] * len(categories) for _ in categories]
    for a, b in zip(a_scores, b_scores):
        matrix[cat_to_idx[a]][cat_to_idx[b]] += 1

    weights = [[0.0] * len(categories) for _ in categories]
    for i, a in enumerate(categories):
        for j, b in enumerate(categories):
            weights[i][j] = 1.0 - ((abs(a - b) / 6.0) ** 2)

    row_sums = [sum(row) for row in matrix]
    col_sums = [sum(matrix[i][j] for i in range(len(categories))) for j in range(len(categories))]
    total = sum(row_sums)
    observed = sum(weights[i][j] * matrix[i][j] for i in range(len(categories)) for j in range(len(categories))) / total
    expected = sum(
        weights[i][j] * row_sums[i] * col_sums[j]
        for i in range(len(categories))
        for j in range(len(categories))
    ) / (total * total)
    return (observed - expected) / (1.0 - expected)


def test_anonymize_removes_internal_review_and_provenance_identifiers():
    raw = """
# Paper
**Authors:** A.M.Y Computational Research System [1]
**Affiliation:** AXIOM Atlas Platform
**Date:** April 26, 2026

## Results
Status: ALL VERIFIED [PASS]

## Data Availability
- mathematics_prime_gap_analysis_20260426_184158: `data/experiments/mathematics_prime_gap_analysis_20260426_184158/provenance.json`

## Supplementary Material

### Internal Peer Review

**Overall Score:** 8.3/10 -- **ACCEPT**
- [PASS] Strong methodology.
- [NOTE] Adequate references.
"""

    anon = anonymize_paper(raw, "abc12345")

    assert "A.M.Y" not in anon
    assert "AXIOM" not in anon
    assert "Atlas" not in anon
    assert "Internal Peer Review" not in anon
    assert "Overall Score" not in anon
    assert "ACCEPT" not in anon
    assert "[PASS]" not in anon
    assert "[NOTE]" not in anon
    assert "data/experiments" not in anon
    assert "mathematics_prime_gap_analysis" not in anon
    assert "[provenance_record_abc12345]" in anon


def test_evaluator_construction_is_offline_until_a_review_is_requested(
    monkeypatch, tmp_path
):
    for name in (
        "OLLAMA_CLOUD_API_KEY",
        "OLLAMA_CLOUD_API_KEY_1",
        "OLLAMA_CLOUD_API_KEY_2",
    ):
        monkeypatch.delenv(name, raising=False)

    evaluator = DoubleBlindEvaluator(
        papers_dir=tmp_path,
        output_dir=tmp_path / "out",
    )

    assert evaluator.client is None


def test_run_evaluation_uses_independent_reviewer_orders():
    async def _run():
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pairs = []
            for idx in range(2):
                pre = root / f"pre_{idx}.md"
                post = root / f"post_{idx}.md"
                pre.write_text(f"# Pre {idx}\n\n## Results\nText", encoding="utf-8")
                post.write_text(f"# Post {idx}\n\n## Results\nText", encoding="utf-8")
                pairs.append((pre, post, f"mission_{idx}"))

            evaluator = DoubleBlindEvaluator(papers_dir=root, output_dir=root / "out", review_delay_seconds=0)
            evaluator._find_paper_pairs = lambda: pairs
            seen: list[tuple[str, str]] = []

            async def fake_get_review(model, paper_id, paper_text, reviewer_label):
                seen.append((reviewer_label, paper_id))
                return _review()

            evaluator._get_review = fake_get_review
            try:
                result = await evaluator.run_evaluation()
            finally:
                await evaluator.close()

            assignments = result["assignments"]
            expected_a = [
                ("Reviewer_A", pid)
                for pid, _ in sorted(assignments.items(), key=lambda item: item[1]["reviewer_a"]["order"])
            ]
            expected_b = [
                ("Reviewer_B", pid)
                for pid, _ in sorted(assignments.items(), key=lambda item: item[1]["reviewer_b"]["order"])
            ]
            assert seen == expected_a + expected_b

    asyncio.run(_run())


def test_invalid_reviews_are_excluded_from_inter_rater_agreement():
    evaluator = DoubleBlindEvaluator()
    valid = _review(score=6)
    invalid = {
        "scores": {},
        "concerns": ["parse failed"],
        "strengths": [],
        "recommendation": "INVALID",
        "confidence": 0,
        "_parse_error": True,
    }

    agreement = evaluator._compute_inter_rater_agreement(
        [
            {"paper_id": "valid", "review_a": valid, "review_b": _review(score=5)},
            {"paper_id": "invalid", "review_a": valid, "review_b": invalid},
        ]
    )

    assert agreement["n_papers"] == 2
    assert agreement["n_valid_pairs"] == 1
    assert agreement["n_invalid_pairs"] == 1


def test_get_review_returns_invalid_without_fallback_scores_after_parse_failures():
    class InvalidJsonClient:
        async def chat(self, **kwargs):
            return {"message": {"content": "not json"}}

    async def _run():
        evaluator = DoubleBlindEvaluator(review_delay_seconds=0, retry_delay_seconds=0)
        evaluator.client = InvalidJsonClient()

        review = await evaluator._get_review(REVIEWER_B_MODEL, "paper1", "# Paper", "Reviewer_B")

        assert review["_parse_error"] is True
        assert review["_valid"] is False
        assert review["scores"] == {}
        assert review["recommendation"] == "INVALID"
        assert "_fallback_reviewer" not in review

    asyncio.run(_run())


def test_invalid_reviews_are_not_averaged_as_default_scores_in_cohort_comparison():
    evaluator = DoubleBlindEvaluator()
    pre = Path("pre.md")
    post = Path("post.md")
    pairs = [(pre, post, "mission")]
    paper_ids = {pre: "preid", post: "postid"}
    invalid = {
        "scores": {},
        "concerns": ["api failed"],
        "strengths": [],
        "recommendation": "INVALID",
        "confidence": 0,
        "_api_error": True,
    }

    comparison = evaluator._compare_cohorts(
        pairs,
        paper_ids,
        [
            {"paper_id": "preid", "review_a": _review(score=7), "review_b": invalid},
            {"paper_id": "postid", "review_a": _review(score=5), "review_b": invalid},
        ],
    )

    overall = comparison["dimension_comparison"]["overall_scientific_quality"]
    assert overall["pre_mean"] == 7
    assert overall["post_mean"] == 5
    assert overall["n_valid_pairs"] == 1
    assert overall["n_excluded_pairs"] == 0


def test_weighted_kappa_uses_fixed_likert_scale():
    a_scores = [5, 5, 6, 6]
    b_scores = [5, 6, 6, 7]
    expected = _weighted_kappa_fixed_scale(a_scores, b_scores)
    actual = DoubleBlindEvaluator._cohens_kappa(a_scores, b_scores)

    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def test_analysis_report_surfaces_invalid_review_counts():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "results.json"
        dim_comp = {
            dim: {
                "pre_mean": 3.0,
                "post_mean": 4.0,
                "mean_diff": 1.0,
                "cohens_d": 0.5,
                "direction": "improved",
                "n_valid_pairs": 1,
                "n_excluded_pairs": 0,
            }
            for dim in RUBRIC_DIMENSIONS
        }
        results = {
            "session_id": "test_session",
            "n_papers": 2,
            "n_pairs": 1,
            "reviewer_a_model": "model-a",
            "reviewer_b_model": "model-b",
            "inter_rater_agreement": {
                "cohens_kappa_by_dimension": {dim: 0.0 for dim in RUBRIC_DIMENSIONS},
                "pearson_r_by_dimension": {dim: 0.0 for dim in RUBRIC_DIMENSIONS},
                "overall_kappa": 0.0,
                "overall_pearson_r": 0.0,
                "recommendation_agreement": 0.5,
                "n_papers": 2,
                "n_valid_pairs": 1,
                "n_invalid_pairs": 1,
                "invalid_paper_ids": ["badpaper"],
            },
            "cohort_comparison": {
                "dimension_comparison": dim_comp,
                "overall": {
                    "pre_mean": 3.0,
                    "post_mean": 4.0,
                    "mean_diff": 1.0,
                    "direction": "improved",
                },
            },
        }
        path.write_text(json_dumps(results), encoding="utf-8")

        analysis = analyze_results(path)
        report = generate_final_report(analysis, path)

        assert analysis["agreement"]["n_valid_pairs"] == 1
        assert analysis["agreement"]["n_invalid_pairs"] == 1
        assert analysis["agreement"]["invalid_paper_ids"] == ["badpaper"]
        assert "Invalid/excluded pairs" in report
        assert "badpaper" in report


def json_dumps(data: dict) -> str:
    import json

    return json.dumps(data, indent=2)


def main():
    tests = [
        test_anonymize_removes_internal_review_and_provenance_identifiers,
        test_run_evaluation_uses_independent_reviewer_orders,
        test_invalid_reviews_are_excluded_from_inter_rater_agreement,
        test_get_review_returns_invalid_without_fallback_scores_after_parse_failures,
        test_invalid_reviews_are_not_averaged_as_default_scores_in_cohort_comparison,
        test_weighted_kappa_uses_fixed_likert_scale,
        test_analysis_report_surfaces_invalid_review_counts,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")


if __name__ == "__main__":
    main()
