"""Tests for core.literature_search — the fast concurrent literature client.

Two layers:
  1. Offline/unit tests (always run in CI): parsing, dedup, scoring, deadline
     handling, schema — all with fake httpx responses, no network.
  2. Live tests (opt-in via RUN_LIVE_LITERATURE=1): hit the real open APIs.
     Skipped by default so CI stays hermetic and fast.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from core.literature_search import (
    Paper,
    _clean_abstract_from_inverted_index,
    _norm_title,
    search_literature_async,
)


# ─── Pure helpers ─────────────────────────────────────────────────────────────


def test_norm_title_strips_punctuation_and_case():
    assert _norm_title("The Riemann Hypothesis!") == "the riemann hypothesis"
    assert _norm_title("A  B—C") == "a b c"


def test_inverted_index_reconstructs_word_order():
    inv = {"Prime": [0], "gaps": [1], "are": [2], "interesting": [3]}
    assert _clean_abstract_from_inverted_index(inv) == "Prime gaps are interesting"


def test_inverted_index_empty_returns_empty():
    assert _clean_abstract_from_inverted_index(None) == ""
    assert _clean_abstract_from_inverted_index({}) == ""


def test_paper_to_dict_exposes_both_abstract_and_summary():
    p = Paper(title="T", abstract="A", source="X")
    d = p.to_dict()
    assert d["abstract"] == "A"
    assert d["summary"] == "A"  # heartbeat reads either key
    assert d["title"] == "T"


# ─── Merge / dedup / scoring with fake sources ────────────────────────────────


def _fake_source(papers):
    async def _fn(client, query, k):
        return papers
    return _fn


async def _search_with(sources, **kw):
    # Bypass the real httpx client by passing custom source coroutines that
    # ignore the client argument.
    return await search_literature_async("test query", sources=sources, **kw)


def test_empty_query_returns_zero_without_network():
    out = asyncio.run(search_literature_async("   "))
    assert out["papers"] == []
    assert out["support_score"] == 0.0
    assert out["error"] == "empty query"


def test_dedup_by_doi():
    p1 = Paper(title="Paper One", doi="10.1/x", source="A")
    p2 = Paper(title="Paper One (preprint)", doi="10.1/X", source="B")  # same DOI, diff case
    sources = {"a": _fake_source([p1]), "b": _fake_source([p2])}
    out = asyncio.run(_search_with(sources))
    assert len(out["papers"]) == 1


def test_dedup_by_title_when_no_doi():
    p1 = Paper(title="Quantum Entanglement Review", source="A")
    p2 = Paper(title="quantum entanglement review", source="B")
    sources = {"a": _fake_source([p1]), "b": _fake_source([p2])}
    out = asyncio.run(_search_with(sources))
    assert len(out["papers"]) == 1


def test_distinct_papers_all_kept():
    sources = {
        "a": _fake_source([Paper(title="Alpha", doi="10.1/a", source="A")]),
        "b": _fake_source([Paper(title="Beta", doi="10.1/b", source="B")]),
    }
    out = asyncio.run(_search_with(sources))
    assert len(out["papers"]) == 2
    assert {"A", "B"} == {p["source"] for p in out["papers"]}


def test_support_score_grows_with_more_sources():
    one = {"a": _fake_source([Paper(title="X", doi="10.1/a", source="A")])}
    three = {
        "a": _fake_source([Paper(title="X", doi="10.1/a", source="A")]),
        "b": _fake_source([Paper(title="Y", doi="10.1/b", source="B")]),
        "c": _fake_source([Paper(title="Z", doi="10.1/c", source="C")]),
    }
    s1 = asyncio.run(_search_with(one))["support_score"]
    s3 = asyncio.run(_search_with(three))["support_score"]
    assert s3 > s1
    assert 0.0 <= s1 <= 1.0 and 0.0 <= s3 <= 1.0


def test_failing_source_does_not_sink_the_query():
    async def _boom(client, query, k):
        raise RuntimeError("source down")

    sources = {
        "good": _fake_source([Paper(title="Good", doi="10.1/g", source="Good")]),
        "bad": _boom,
    }
    out = asyncio.run(_search_with(sources, per_source_timeout=2))
    assert len(out["papers"]) == 1
    assert "good" in out["sources_succeeded"]
    assert "bad" in out["source_errors"]


def test_slow_source_is_dropped_at_deadline():
    async def _slow(client, query, k):
        await asyncio.sleep(5)
        return [Paper(title="late", source="Slow")]

    sources = {
        "fast": _fake_source([Paper(title="Fast", doi="10.1/f", source="Fast")]),
        "slow": _slow,
    }
    # global deadline below the slow source's sleep
    out = asyncio.run(_search_with(sources, per_source_timeout=1, global_deadline=2))
    titles = [p["title"] for p in out["papers"]]
    assert "Fast" in titles
    assert "late" not in titles


def test_papers_without_title_are_dropped():
    sources = {"a": _fake_source([Paper(title="", source="A"),
                                  Paper(title="Real", doi="10.1/r", source="A")])}
    out = asyncio.run(_search_with(sources))
    assert len(out["papers"]) == 1
    assert out["papers"][0]["title"] == "Real"


def test_domain_filter_discards_popular_but_unrelated_papers():
    sources = {
        "mixed": _fake_source([
            Paper(
                title="Prime gap distributions and finite Cramer models",
                abstract="We enumerate consecutive prime numbers.",
                source="A",
                citations=12,
            ),
            Paper(
                title="Cancer survival after vaccine therapy",
                abstract="A clinical human-genome cohort study.",
                source="A",
                citations=50_000,
            ),
        ])
    }

    out = asyncio.run(search_literature_async(
        "prime gap distribution",
        domain="mathematics",
        sources=sources,
    ))

    assert [paper["title"] for paper in out["papers"]] == [
        "Prime gap distributions and finite Cramer models"
    ]
    assert out["papers_filtered_irrelevant"] == 1
    assert out["relevance_filter_applied"] is True
    assert "prime" in out["papers"][0]["relevance_matches"]


def test_domain_filter_is_not_applied_to_general_searches():
    sources = {
        "broad": _fake_source([
            Paper(title="Unrelated but intentionally retained", source="A")
        ])
    }

    out = asyncio.run(search_literature_async("prime gaps", sources=sources))

    assert len(out["papers"]) == 1
    assert out["relevance_filter_applied"] is False


# ─── Live tests (opt-in) ──────────────────────────────────────────────────────

_LIVE = os.getenv("RUN_LIVE_LITERATURE") == "1"


@pytest.mark.skipif(not _LIVE, reason="set RUN_LIVE_LITERATURE=1 to hit real APIs")
class TestLive:
    def test_real_query_returns_papers_fast(self):
        out = asyncio.run(search_literature_async(
            "CRISPR gene editing off-target", max_results=6))
        assert len(out["papers"]) >= 3
        assert out["elapsed"] < 20
        assert len(out["sources_succeeded"]) >= 2
        # Every paper has the schema the heartbeat expects.
        for p in out["papers"]:
            assert "title" in p and "abstract" in p and "summary" in p
