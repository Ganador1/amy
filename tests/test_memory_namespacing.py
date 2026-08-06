"""Mission memory paths must be stable and isolated across unrelated goals."""

from pathlib import Path

import pytest

from amy import scoped_memory_config


def _config(goal, tmp_path, **memory_overrides):
    memory = {
        "namespace_by_mission": True,
        "mission_memory_root": str(tmp_path / "missions"),
    }
    memory.update(memory_overrides)
    return {
        "mission": {"goal": goal},
        "memory": memory,
    }


def test_same_mission_gets_stable_memory_paths(tmp_path):
    config = _config("Investigate prime gaps", tmp_path)

    first = scoped_memory_config(config)
    second = scoped_memory_config(config)

    assert first == second
    assert first["mission_namespace"].startswith("investigate-prime-gaps-")
    assert Path(first["knowledge_graph_path"]).parent == (
        tmp_path / "missions" / first["mission_namespace"]
    )


def test_unrelated_missions_do_not_share_persistent_state(tmp_path):
    prime = scoped_memory_config(_config("Investigate prime gaps", tmp_path))
    glioma = scoped_memory_config(
        _config("Investigate glioblastoma therapies", tmp_path)
    )

    for key in (
        "knowledge_graph_path",
        "episodic_log_path",
        "vector_db_path",
    ):
        assert prime[key] != glioma[key]


def test_explicit_namespace_supports_reproducible_campaigns(tmp_path):
    config = _config(
        "A goal whose wording may change",
        tmp_path,
        mission_namespace="Prime Gaps / Release 1",
    )

    scoped = scoped_memory_config(config)

    assert scoped["mission_namespace"] == "prime-gaps-release-1"


def test_namespacing_is_opt_in_for_library_consumers(tmp_path):
    memory = {
        "namespace_by_mission": False,
        "knowledge_graph_path": str(tmp_path / "legacy.json"),
    }
    scoped = scoped_memory_config(
        {"mission": {"goal": "anything"}, "memory": memory}
    )

    assert scoped == memory


def test_invalid_explicit_namespace_fails_closed(tmp_path):
    config = _config(
        "goal",
        tmp_path,
        mission_namespace="../",
    )

    with pytest.raises(ValueError, match="mission_namespace"):
        scoped_memory_config(config)
