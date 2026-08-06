#!/usr/bin/env python3
"""
Test: Full Mission Simulation — Multi-Cycle End-to-End

Simula una misión científica completa con múltiples ciclos cognitivos:
1. Ciclo 1-2: Ejecutar herramientas de recolección de datos
2. Ciclo 3-4: Analizar resultados y formar hipótesis
3. Ciclo 5: Escribir paper con resultados
4. Ciclo 6: Enviar a peer review autónomo
5. Verificar calidad del paper y feedback del reviewer

Dominio: Análisis de propiedades físico-químicas de moléculas
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "atlas"))

from core.heartbeat import Heartbeat
from core.global_workspace import GlobalWorkspace
from core.world_model import WorldModel
from memory.episodic import EpisodicMemory
from memory.semantic import SemanticMemory
from memory.procedural import ProceduralMemory
from cognition.goal_stack import GoalStack
from cognition.curiosity import CuriosityModule
from cognition.reflection import ReflectionModule
from skills.library import SkillLibrary
from senses.web_sensor import WebSensor
from senses.time_sensor import TimeSensor
from communication.breakthrough_detector import BreakthroughDetector
from communication.report_generator import ReportGenerator


TEST_CONFIG = {
    "heartbeat": {
        "base_interval_seconds": 1.0,
        "focused_interval_seconds": 0.5,
        "idle_interval_seconds": 5.0,
        "max_cycles_before_reflection": 10,
        "adaptive_interval": False,
        "atlas": {
            "peer_review_timeout_seconds": 20,
            "model": "glm-5.2",
        },
    },
    "mission": {
        "goal": "Investigate molecular properties of common compounds",
        "description": "Use Atlas tools to analyze molecular weight, energy levels, and statistical properties",
    },
    "memory": {
        "episodic_db": ":memory:",
        "semantic_db": ":memory:",
        "procedural_db": ":memory:",
    },
    "llm": {
        "provider": "ollama",
        "model": "gemini-3-flash-preview:cloud",
        "temperature": 0.7,
    },
    "curiosity": {
        "surprise_threshold": 0.7,
    },
    "communication": {
        "breakthrough_threshold": 0.9,
    },
    "skills": {
        "library_path": ":memory:",
    },
    "research": {},
}


class MockReasoningEngine:
    """Mock reasoning engine that simulates a full scientific mission."""
    
    def __init__(self):
        self.step = 0
        self.thoughts = [
            # Ciclo 1: Recolección de datos - Química
            {
                "observation": "Need to analyze molecular properties",
                "thought": "Start with molecular weight calculation",
                "hypothesis": "Glucose has MW ~180 g/mol",
                "action_type": "run_scientific_tool",
                "action_details": {
                    "tool_name": "molecular_weight_calc",
                    "tool_input": "C6H12O6",
                    "domain": "chemistry",
                },
                "new_facts": [],
                "content": "Calculating molecular weight of glucose",
                "surprise_assessment": 0.5,
                "progress_toward_goal": 0.2,
            },
            # Ciclo 2: Recolección de datos - Física
            {
                "observation": "Glucose MW is 180.156 g/mol",
                "thought": "Now analyze quantum energy levels",
                "hypothesis": "Hydrogen energy levels follow Rydberg formula",
                "action_type": "run_scientific_tool",
                "action_details": {
                    "tool_name": "quantum_energy_levels",
                    "tool_input": "hydrogen:3",
                    "domain": "physics",
                },
                "new_facts": [
                    {"subject": "glucose", "predicate": "molecular_weight", "object": "180.156", "confidence": 0.99}
                ],
                "content": "Analyzing hydrogen energy levels",
                "surprise_assessment": 0.6,
                "progress_toward_goal": 0.4,
            },
            # Ciclo 3: Análisis estadístico
            {
                "observation": "Hydrogen n=3 energy is -1.511 eV",
                "thought": "Run statistical analysis on molecular data",
                "hypothesis": "Molecular properties show predictable patterns",
                "action_type": "run_scientific_tool",
                "action_details": {
                    "tool_name": "numpy_statistics",
                    "tool_input": "summary:[180.156, 18.015, 44.01, 28.01, 32.00]",
                    "domain": "statistics",
                },
                "new_facts": [
                    {"subject": "hydrogen", "predicate": "energy_n3", "object": "-1.511", "confidence": 0.99}
                ],
                "content": "Running statistical analysis",
                "surprise_assessment": 0.4,
                "progress_toward_goal": 0.6,
            },
            # Ciclo 4: Validación de hipótesis
            {
                "observation": "Mean molecular weight is 60.44 g/mol",
                "thought": "Validate the hypothesis about molecular properties",
                "hypothesis": "Molecular properties follow predictable statistical patterns",
                "action_type": "run_scientific_tool",
                "action_details": {
                    "tool_name": "validate_hypothesis",
                    "tool_input": "chemistry:molecular weights follow predictable patterns",
                    "domain": "research",
                },
                "new_facts": [
                    {"subject": "molecules", "predicate": "mean_weight", "object": "60.44", "confidence": 0.95}
                ],
                "content": "Validating hypothesis",
                "surprise_assessment": 0.3,
                "progress_toward_goal": 0.8,
            },
            # Ciclo 5: Escribir paper
            {
                "observation": "All data collected and validated",
                "thought": "Synthesize findings into a paper",
                "hypothesis": "Molecular properties can be predicted computationally",
                "action_type": "write_paper",
                "action_details": {
                    "paper_topic": "Computational Analysis of Molecular Properties",
                },
                "new_facts": [
                    {"subject": "hypothesis", "predicate": "validated", "object": "True", "confidence": 0.85}
                ],
                "content": "Writing paper on molecular properties",
                "surprise_assessment": 0.2,
                "progress_toward_goal": 1.0,
            },
            # Ciclo 6: Peer review
            {
                "observation": "Paper written with computational evidence",
                "thought": "Submit for peer review",
                "hypothesis": "Molecular properties can be predicted computationally",
                "action_type": "peer_review_paper",
                "action_details": {},
                "new_facts": [],
                "content": "Submitting for peer review",
                "surprise_assessment": 0.1,
                "progress_toward_goal": 1.0,
            },
        ]
    
    async def reason(self, **kwargs):
        if self.step < len(self.thoughts):
            thought = self.thoughts[self.step]
            self.step += 1
            return thought
        return {"action_type": "think_more", "content": "Mission complete"}
    
    async def generate_experiment_code(self, **kwargs):
        return "print('mock experiment')"


async def _run_full_mission_simulation(tmp_path=None):
    """Simulate a complete multi-cycle scientific mission."""
    print("=" * 70)
    print("FULL MISSION SIMULATION — MULTI-CYCLE END-TO-END")
    print("=" * 70)
    print("\nMisión: Análisis computacional de propiedades moleculares")
    print("Ciclos: 6 (recolección → análisis → paper → peer review)")

    # Isolate persistent memory from the developer's real knowledge graph. The
    # old test used unused keys such as ``semantic_db`` and silently fell back
    # to ``data/knowledge_graph.json``.
    temporary_context = None
    if tmp_path is None:
        temporary_context = tempfile.TemporaryDirectory(
            prefix="amy-full-mission-"
        )
        tmp_path = Path(temporary_context.name)
    memory_config = {
        "episodic_log_path": str(tmp_path / "episodic_memory.jsonl"),
        "knowledge_graph_path": str(tmp_path / "knowledge_graph.json"),
        "vector_db_path": str(tmp_path / "vector_db"),
        "max_episodic_before_consolidation": 1000,
        "belief_confidence_threshold": 0.3,
    }

    # Initialize
    print("\n[1/7] Initializing A.M.Y cognitive architecture...")
    episodic = EpisodicMemory(memory_config)
    semantic = SemanticMemory(memory_config)
    procedural = ProceduralMemory(memory_config)
    world_model = WorldModel(semantic_memory=semantic, episodic_memory=episodic)
    goal_stack = GoalStack(TEST_CONFIG["mission"])
    curiosity = CuriosityModule(TEST_CONFIG["curiosity"])
    reflection = ReflectionModule(episodic_memory=episodic, semantic_memory=semantic)
    reasoning = MockReasoningEngine()
    reflection.reasoning_engine = reasoning
    workspace = GlobalWorkspace()
    skill_library = SkillLibrary(TEST_CONFIG["skills"])
    web_sensor = WebSensor(TEST_CONFIG["research"])
    time_sensor = TimeSensor()
    breakthrough = BreakthroughDetector(TEST_CONFIG["communication"])
    report_gen = ReportGenerator(TEST_CONFIG["communication"])

    heartbeat = Heartbeat(
        config=TEST_CONFIG["heartbeat"],
        world_model=world_model,
        goal_stack=goal_stack,
        curiosity=curiosity,
        reflection=reflection,
        reasoning=reasoning,
        workspace=workspace,
        episodic_memory=episodic,
        semantic_memory=semantic,
        procedural_memory=procedural,
        skill_library=skill_library,
        web_sensor=web_sensor,
        time_sensor=time_sensor,
        breakthrough_detector=breakthrough,
        report_generator=report_gen,
    )
    print("  ✅ Initialized")

    # Run 6 cycles
    print("\n[2/7] Running 6 cognitive cycles...")
    results = []
    for cycle in range(6):
        print(f"\n  --- Cycle {cycle + 1} ---")
        
        await heartbeat._perceive()
        focus = await heartbeat._attend([])
        thought = await heartbeat._think(focus)
        action_result = await heartbeat._act(thought)
        await heartbeat._learn(thought, action_result)
        
        action_type = action_result.get("type", "noop")
        success = action_result.get("success", True)
        
        if action_type == "run_scientific_tool":
            tool_name = action_result.get("tool_name", "unknown")
            result_preview = str(action_result.get("result", ""))[:60]
            icon = "✅" if success else "❌"
            print(f"  {icon} {tool_name}: {result_preview}")
        elif action_type == "write_paper":
            paper_result = action_result.get("result", {})
            if "error" not in paper_result:
                print(f"  ✅ Paper: {paper_result.get('title', 'Untitled')[:50]}")
                print(f"     Words: {paper_result.get('word_count', 0)}")
            else:
                print(f"  ⚠️  Paper error: {paper_result.get('error', 'Unknown')[:60]}")
        elif action_type == "peer_review_paper":
            score = action_result.get("score", 0)
            accepted = action_result.get("accepted", False)
            icon = "✅" if accepted else "⚠️"
            print(f"  {icon} Peer review: score={score}/10, accepted={accepted}")
        else:
            print(f"  ℹ️  {action_type}: {thought.get('content', '')[:50]}")
        
        results.append({
            "cycle": cycle + 1,
            "action_type": action_type,
            "success": success,
            "payload": action_result,
        })

    # Verify tool results
    print("\n[3/7] Verifying tool executions...")
    tool_results = [r for r in results if r["action_type"] == "run_scientific_tool"]
    print(f"  ✅ {len(tool_results)} tool executions")

    # Verify paper
    print("\n[4/7] Verifying paper generation...")
    paper_results = [r for r in results if r["action_type"] == "write_paper"]
    if paper_results:
        print(f"  ✅ Paper generation attempted")
    else:
        print(f"  ❌ No paper generation")

    # Verify peer review
    print("\n[5/7] Verifying peer review...")
    review_results = [r for r in results if r["action_type"] == "peer_review_paper"]
    if review_results:
        print(f"  ✅ Peer review attempted")
    else:
        print(f"  ❌ No peer review")

    # Verify memory
    print("\n[6/7] Verifying episodic memory...")
    recent_events = await heartbeat.episodic_memory.get_recent(n=20)
    tool_events = [e for e in recent_events if e.get("event_type") == "scientific_tool_execution"]
    paper_events = [e for e in recent_events if e.get("event_type") == "paper_written"]
    print(f"  ✅ {len(tool_events)} tool events in memory")
    print(f"  ✅ {len(paper_events)} paper events in memory")

    # Verify tool history
    print("\n[7/7] Verifying tool results history...")
    tool_history = getattr(heartbeat, "_tool_results_history", [])
    print(f"  ✅ {len(tool_history)} tool results in history")
    for tr in tool_history:
        print(f"     - {tr['tool_name']}: {str(tr['result'])[:40]}")

    # Summary
    print("\n" + "=" * 70)
    print("MISSION SUMMARY")
    print("=" * 70)
    
    checks = [
        (
            "Three usable tool executions",
            len([result for result in tool_results if result["success"]]) >= 3,
        ),
        (
            "Weak evidence was rejected",
            any(
                result["payload"].get("tool_name") == "validate_hypothesis"
                and result["payload"].get("error") == "unusable_tool_output"
                for result in tool_results
            ),
        ),
        (
            "Paper pipeline returned a substantive draft",
            any(
                result["payload"].get("result", {}).get("word_count", 0) >= 100
                for result in paper_results
            ),
        ),
        (
            "Peer review completed or failed explicitly within its deadline",
            any(
                result["success"]
                or bool(result["payload"].get("error"))
                for result in review_results
            ),
        ),
        ("Memory storage", len(tool_events) >= 3),
        ("Tool history", len(tool_history) >= 3),
    ]
    
    passed = 0
    for name, check in checks:
        if check:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name}")

    print(f"\nPassed: {passed}/{len(checks)}")
    await heartbeat.stop()
    if temporary_context is not None:
        temporary_context.cleanup()

    failed_checks = [name for name, check in checks if not check]
    assert not failed_checks, (
        "Full mission checks failed: " + ", ".join(failed_checks)
    )

    print("\n🎉 FULL MISSION SIMULATION PASSED!")
    print("\nPipeline verified:")
    print("  1. ✅ Data collection (chemistry + physics + statistics)")
    print("  2. ✅ Weak-evidence rejection")
    print("  3. ✅ Paper generation with tool results")
    print("  4. ✅ Bounded peer review submission")
    print("  5. ✅ Memory storage")
    return True


async def test_full_mission_simulation(tmp_path):
    await _run_full_mission_simulation(tmp_path)


if __name__ == "__main__":
    success = asyncio.run(_run_full_mission_simulation())
    sys.exit(0 if success else 1)
