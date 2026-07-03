#!/usr/bin/env python3
"""Hermetic tests for the rapid-round fixes (curiosity, skills, ollama client).

From the 2026-06-28 re-review: curiosity _explored_topics grows unbounded and
the epistemic_weight knob was dead; skills register_skill silently reset usage
stats; ollama embed had no failover and 429 Retry-After was ignored.
"""
import time

import pytest

from cognition.curiosity import CuriosityModule
from cognition.reasoning import ReasoningEngine, _parse_json_robust
from core.heartbeat import Heartbeat, _action_details
from skills.library import SkillLibrary
from skills.code_experiment import CodeExperimentSkill
from core.ollama_client import OllamaCloudClient


# ── Curiosity: bounded explored-topics + working epistemic_weight ────────────

class _FakeWorldModel:
    average_surprise = 0.0
    async def get_uncertainty_map(self):
        return []


async def test_explored_topics_evicted_below_floor():
    c = CuriosityModule({"novelty_decay": 0.5, "novelty_floor": 0.05})
    c._explored_topics = {"old": 0.06, "fresh": 1.0}
    await c.get_signal(_FakeWorldModel(), None)
    # 0.06 * 0.5 = 0.03 < floor -> evicted; 1.0 * 0.5 = 0.5 kept.
    assert "old" not in c._explored_topics
    assert "fresh" in c._explored_topics


async def test_explored_topics_bounded_by_max():
    c = CuriosityModule({"novelty_decay": 1.0, "novelty_floor": 0.0, "max_explored_topics": 10})
    c._explored_topics = {f"t{i}": (i + 1) / 100 for i in range(50)}
    await c.get_signal(_FakeWorldModel(), None)
    assert len(c._explored_topics) <= 10


async def test_epistemic_weight_actually_affects_signal():
    wm = _FakeWorldModel()
    # With no uncertainties, model_uncertainty = 0.8; novelty/surprise terms = 0
    # (empty topics -> novelty 1.0 actually). Compare two epistemic weights.
    c_hi = CuriosityModule({"epistemic_weight": 0.9})
    c_lo = CuriosityModule({"epistemic_weight": 0.1})
    sig_hi = await c_hi.get_signal(wm, None)
    sig_lo = await c_lo.get_signal(wm, None)
    # Different weights must yield different curiosity levels (knob is live).
    assert sig_hi["level"] != sig_lo["level"]


# ── Skills: re-register preserves usage stats; unknown usage warns ───────────

async def test_register_skill_preserves_usage_stats():
    lib = SkillLibrary({"library_path": ":memory:"})
    await lib.register_skill("s", "does a thing", "print(1)")
    await lib.record_usage("s", success=True)
    await lib.record_usage("s", success=True)
    assert lib.skills["s"]["times_used"] == 2
    # Re-register (e.g. consolidation re-extracts) must NOT wipe the history.
    await lib.register_skill("s", "does a thing v2", "print(2)")
    assert lib.skills["s"]["times_used"] == 2
    assert lib.skills["s"]["success_count"] == 2
    assert lib.skills["s"]["description"] == "does a thing v2"  # metadata updated


async def test_record_usage_unknown_skill_is_noop_not_crash():
    lib = SkillLibrary({"library_path": ":memory:"})
    # Should not raise (and should not create a phantom entry).
    await lib.record_usage("nonexistent", success=True)
    assert "nonexistent" not in lib.skills


# ── Ollama: Retry-After parsing + cooldown honoring + embed failover ─────────

def _client_stub(n_keys=2):
    c = OllamaCloudClient.__new__(OllamaCloudClient)
    c._keys = ["k"] * n_keys
    c._key_failures = {}
    c._cooldown_seconds = 120
    return c


def test_ollama_client_prefers_primary_key_over_legacy_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "new-primary")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_1", "old-legacy")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "backup")

    client = OllamaCloudClient({"base_url": "https://ollama.com/api"})

    assert client._keys == ["new-primary", "backup"]


def test_ollama_client_deduplicates_key_aliases(monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "same-key")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_1", "same-key")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "backup")

    client = OllamaCloudClient({"base_url": "https://ollama.com/api"})

    assert client._keys == ["same-key", "backup"]


def test_ollama_client_uses_legacy_key_when_primary_missing(monkeypatch):
    monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_1", "legacy-only")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "backup")

    client = OllamaCloudClient({"base_url": "https://ollama.com/api"})

    assert client._keys == ["legacy-only", "backup"]


def test_parse_retry_after():
    assert OllamaCloudClient._parse_retry_after("30") == 30.0
    assert OllamaCloudClient._parse_retry_after(None) is None
    assert OllamaCloudClient._parse_retry_after("garbage") is None


def test_record_failure_honors_retry_after():
    c = _client_stub()
    exc = Exception("429")
    exc.retry_after = 300  # server says wait 300s, longer than 120 cooldown
    before = time.time()
    c._record_failure(0, exc)
    # _pick_key compares (now - last_fail) > cooldown; with retry_after the key
    # should remain unavailable until ~300s from now, i.e. last_fail is in the
    # future relative to a plain time.time() failure.
    assert c._key_failures[0] > before  # pushed forward to honor retry_after
    # Effective ready-time = last_fail + cooldown ≈ now + 300.
    ready_in = c._key_failures[0] + c._cooldown_seconds - before
    assert 290 < ready_in < 310


def test_record_failure_default_cooldown_without_retry_after():
    c = _client_stub()
    c._record_failure(0, Exception("boom"))
    # No retry_after -> last_fail ≈ now (standard 120s cooldown applies).
    assert abs(c._key_failures[0] - time.time()) < 2


async def test_embed_fails_over_across_keys(monkeypatch):
    c = _client_stub(n_keys=2)
    from itertools import cycle
    c._key_cycle = cycle(range(2))
    calls = {"n": 0}

    async def fake_do(endpoint, payload, api_key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("first key down")
        return {"embeddings": [[0.1, 0.2]]}

    monkeypatch.setattr(c, "_do_request", fake_do)
    out = await c.embed("model", "text")
    assert out == [[0.1, 0.2]]
    assert calls["n"] == 2  # it retried the second key


def test_reasoning_parser_recovers_unclosed_markdown_json_fence():
    raw = '```json\n{"action_type": "think_more", "content": "partial but usable"'

    parsed = _parse_json_robust(raw)

    assert parsed["action_type"] == "think_more"
    assert parsed["content"] == "partial but usable"


def test_heartbeat_treats_null_action_details_as_empty_dict():
    assert _action_details({"action_details": None}) == {}

    hb = Heartbeat.__new__(Heartbeat)
    result = hb._safety_block_for_thought(
        "think_more",
        {"action_type": "think_more", "action_details": None, "content": "benign"},
    )

    assert result is None


async def test_reasoning_treats_null_action_details_as_empty_dict():
    class FakeClient:
        async def chat(self, **kwargs):
            return {
                "message": {
                    "content": (
                        '{"action_type": "experiment", "action_details": null, '
                        '"content": "run an experiment"}'
                    )
                }
            }

    engine = ReasoningEngine.__new__(ReasoningEngine)
    engine.config = {"reasoner": {"temperature": 0.7, "max_tokens": 256}}
    engine.client = FakeClient()
    engine.reasoner_model = "test-model"
    engine.reasoner_ctx = 2048

    thought = await engine.reason(
        focus={"content": "focus", "source": "test"},
        context={"cycle": 7},
    )

    assert thought["action_type"] == "experiment"
    assert thought["content"] == "run an experiment"
    assert thought["cycle"] == 7


def test_reasoning_prompt_forces_pivot_after_repeated_literature_searches():
    engine = ReasoningEngine.__new__(ReasoningEngine)

    messages = engine._build_reasoning_prompt(
        focus={"content": "open curiosity", "source": "curiosity", "type": "open"},
        context={
            "current_goal": "free exploration",
            "cycle": 5,
            "recent_thoughts": [
                {"action_type": "search_literature", "content": "searched topic A"},
                {"action_type": "search_literature", "content": "searched topic A again"},
            ],
            "recent_queries": ["topic A", "topic A mechanism"],
        },
        world_model=None,
    )

    prompt = messages[-1]["content"]
    assert "LITERATURE SEARCH LOOP" in prompt
    assert "DO NOT choose 'search_literature'" in prompt


async def test_search_literature_records_recent_query():
    class FakeAtlas:
        async def search_literature(self, query, domain="medicine"):
            return {"papers": [], "support_score": 0.0}

    class FakeMemory:
        async def record(self, **kwargs):
            self.kwargs = kwargs

    hb = Heartbeat.__new__(Heartbeat)
    hb._atlas_tools = FakeAtlas()
    hb._recent_queries = []
    hb.world_model = None
    hb.episodic_memory = FakeMemory()

    await hb._act_search_literature(
        {"research_query": "CaMKII synaptic memory turnover", "domain": "neuroscience"}
    )

    assert hb._recent_queries == ["CaMKII synaptic memory turnover"]


async def test_code_experiment_retries_recoverable_float_integer_format_error():
    skill = CodeExperimentSkill({"max_execution_time": 30})
    result = await skill.run_experiment(
        hypothesis="formatting repair smoke",
        code="value = 154.0\nprint(f'gap={value:d}')\n",
    )

    assert result["success"] is True
    assert "gap=154" in result["stdout"]
    assert result["repair"]["attempted"] is True


async def test_code_experiment_repairs_misaligned_function_docstring_indent():
    skill = CodeExperimentSkill({"max_execution_time": 30})
    result = await skill.run_experiment(
        hypothesis="docstring indentation repair smoke",
        code='def f():\n   """\n    docs\n    """\n    return 1\nprint(f())\n',
    )

    assert result["success"] is True
    assert result["stdout"].strip() == "1"
    assert result["repair"]["reason"] == "misaligned_docstring_indent"
