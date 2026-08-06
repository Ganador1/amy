"""
Heartbeat — The cognitive cycle that never stops.

Inspired by:
- Active Inference (continuous perception-action cycle)
- SOAR (propose → evaluate → select → apply operators)
- NELL (24/7 never-ending learning)

Each "beat" is one cycle of cognition:
1. PERCEIVE  — sample senses (time, web events, new data)
2. ATTEND    — global workspace selects what to focus on
3. THINK     — reason about the focused content (recursive)
4. ACT       — execute the chosen action (research, experiment, reflect)
5. LEARN     — update memory and world model
6. REPORT    — if breakthrough detected, communicate
"""
import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger()


def _action_details(thought: dict) -> dict:
    """Return nested action details only when the model supplied a JSON object."""
    details = thought.get("action_details", {}) if isinstance(thought, dict) else {}
    return details if isinstance(details, dict) else {}


def _belief_to_research_fact(belief) -> dict:
    """Preserve belief content and source when handing evidence to Atlas."""
    if all(hasattr(belief, attr) for attr in ("subject", "predicate", "obj")):
        return {
            "subject": belief.subject,
            "predicate": belief.predicate,
            "object": belief.obj,
            "confidence": getattr(belief, "confidence", 0.5),
            "source": getattr(belief, "source", "world_model"),
        }
    return {
        "subject": "WorldModelBelief",
        "predicate": "states",
        "object": getattr(belief, "content", str(belief)),
        "confidence": getattr(belief, "confidence", 0.5),
        "source": getattr(belief, "source", "world_model"),
    }


class CognitiveState(Enum):
    PERCEIVING = "perceiving"
    ATTENDING = "attending"
    THINKING = "thinking"
    ACTING = "acting"
    LEARNING = "learning"
    REFLECTING = "reflecting"
    DREAMING = "dreaming"  # consolidating memory when idle


@dataclass
class CognitiveContext:
    """The current state of mind — what A.M.Y is aware of right now."""
    cycle_number: int = 0
    state: CognitiveState = CognitiveState.PERCEIVING
    current_focus: str = ""
    current_goal: str = ""
    surprise_level: float = 0.0  # How unexpected was the last observation
    energy_level: float = 1.0    # Computational budget remaining
    cycles_since_reflection: int = 0
    last_breakthrough_time: float = 0.0
    thoughts: list = field(default_factory=list)


class Heartbeat:
    """
    The infinite cognitive loop.
    Like a heartbeat, it never stops. Each beat is a full cycle of cognition.
    The frequency adapts based on what's happening:
    - Deep focus on promising lead → faster beats
    - Idle reflection → slower beats
    - Breakthrough detected → rapid beats
    """

    def __init__(
        self,
        config: dict,
        world_model,
        goal_stack,
        curiosity,
        reflection,
        reasoning,
        workspace,
        episodic_memory,
        semantic_memory,
        procedural_memory,
        skill_library,
        web_sensor,
        time_sensor,
        breakthrough_detector,
        report_generator,
        self_retrain=None,
    ):
        self.config = config
        self.world_model = world_model
        self.goal_stack = goal_stack
        self.curiosity = curiosity
        self.reflection = reflection
        self.reasoning = reasoning
        self.workspace = workspace
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.procedural_memory = procedural_memory
        self.skill_library = skill_library
        self.web_sensor = web_sensor
        self.time_sensor = time_sensor
        self.breakthrough_detector = breakthrough_detector
        self.report_generator = report_generator
        # Self-improvement loop (optional): belief-weight recalibration +
        # meta-review feedback. Driven from _reflect(); guarded so a None (e.g.
        # in tests) is a safe no-op.
        self.self_retrain = self_retrain
        self._reflections_since_retrain = 0
        self._reflections_per_retrain = config.get("reflections_per_retrain", 3)

        self.ctx = CognitiveContext()
        self._running = False
        self._current_interval = config["base_interval_seconds"]
        # Loop detection: track consecutive same-action streaks
        self._last_action_type: str = ""
        self._consecutive_same_action: int = 0
        # Recent search query log (last 20)
        self._recent_queries: list[str] = []
        # Mission completion detection
        self._mission_complete_streak: int = 0
        # Atlas bridge (lazy init)
        self._atlas_bridge = None
        # Atlas tools (lazy init)
        self._atlas_tools = None
        # Hipótesis recientes enviadas a Atlas (para detectar bucle temático)
        self._recent_hypotheses: deque[str] = deque(maxlen=50)
        self._same_hypothesis_count: int = 0
        # Historial de resultados de herramientas científicas para papers
        self._tool_results_history: deque[dict] = deque(maxlen=20)
        # Memory consolidation (the "sleep on it" pass: episodic → semantic
        # patterns + procedural skills). Previously defined but never wired in,
        # so procedural memory stayed permanently empty. Run during reflection,
        # throttled by _reflections_per_consolidation.
        from memory.consolidation import MemoryConsolidation
        self._consolidator = MemoryConsolidation(
            episodic_memory, semantic_memory, procedural_memory
        )
        self._reflections_since_consolidation = 0
        self._reflections_per_consolidation = config.get("reflections_per_consolidation", 3)
        # Runtime metrics: a cheap, always-current observability surface so the
        # loop's health (cycles, errors, action mix, experiment success rate,
        # memory) is visible without grepping logs. See status_snapshot().
        from core.metrics import HeartbeatMetrics
        self.metrics = HeartbeatMetrics()

    def status_snapshot(self) -> dict:
        """Point-in-time view of what A.M.Y is doing and how it's holding up.

        Combines the live cognitive context (cycle, state, focus, goal) with the
        accumulated runtime metrics. JSON-serializable; safe to call anytime."""
        snap = self.metrics.snapshot()
        snap.update({
            "running": self._running,
            "state": self.ctx.state.value if hasattr(self.ctx.state, "value") else str(self.ctx.state),
            "cycle_number": self.ctx.cycle_number,
            "current_goal": self.ctx.current_goal[:200],
            "current_focus": self.ctx.current_focus[:200],
            "current_interval_seconds": self._current_interval,
        })
        return snap

    def _sandbox_config(self) -> dict:
        """Return the sandbox config visible to action executors."""
        sandbox = self.config.get("sandbox")
        if isinstance(sandbox, dict):
            return sandbox
        return {}

    async def run(self):
        """The infinite loop. Each iteration is one cognitive cycle."""
        self._running = True
        self.ctx.cycle_number = 0

        # Sync the cognitive context's goal from the goal stack's mission.
        # Without this, ctx.current_goal stays "" for the whole (default,
        # single-mission) run — the reasoner prompt's "## Current Goal" field,
        # the decompose parent, and the paper-topic fallback all saw an empty
        # string. The continuous-mission path sets it on rollover, but the
        # initial mission was never wired through.
        self._sync_current_goal_from_mission()

        log.info("heartbeat.started", interval=self._current_interval, goal=self.ctx.current_goal[:120])

        while self._running:
            cycle_start = time.monotonic()
            self.ctx.cycle_number += 1

            try:
                await self._beat()
            except Exception as e:
                self.metrics.record_error(str(e))
                log.error("heartbeat.cycle_error", error=str(e), cycle=self.ctx.cycle_number)
                # Don't crash — log and continue. A mind doesn't crash from one bad thought.
                await self.episodic_memory.record(
                    event_type="error",
                    content=f"Cycle {self.ctx.cycle_number} error: {e}",
                    metadata={"cycle": self.ctx.cycle_number},
                )

            # Adaptive timing
            elapsed = time.monotonic() - cycle_start
            self.metrics.record_cycle(elapsed)
            sleep_time = max(0, self._current_interval - elapsed)

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    async def stop(self):
        """Gracefully stop the heartbeat."""
        log.info("heartbeat.stopping", total_cycles=self.ctx.cycle_number)
        self._running = False
        # AtlasTools owns a subprocess and asyncio streams tied to this
        # heartbeat's event loop.  Reap it before the loop closes so a later
        # mission cannot inherit stale loop-bound futures or a zombie worker.
        atlas_tools = getattr(self, "_atlas_tools", None)
        self._atlas_tools = None
        close_atlas = getattr(atlas_tools, "close", None)
        if close_atlas is not None:
            try:
                await close_atlas()
            except Exception as exc:
                log.warning("heartbeat.atlas_tools_close_failed", error=str(exc))
        # Flush the debounced knowledge graph here too: the mission-complete
        # path reaches heartbeat.stop() but NOT amy.stop(), so without this the
        # final <save_interval window of facts would be silently dropped.
        flush = getattr(self.semantic_memory, "flush", None)
        if flush is not None:
            try:
                await flush()
            except Exception as exc:
                log.warning("heartbeat.semantic_flush_failed", error=str(exc))

    def _sync_current_goal_from_mission(self):
        """Set ctx.current_goal from the goal stack's active mission if it is
        currently empty. Safe no-op if there is no mission or it is already set."""
        if self.ctx.current_goal:
            return
        gs = getattr(self, "goal_stack", None)
        mission_id = getattr(gs, "mission_id", None) if gs else None
        if not mission_id:
            return
        mission = gs.goals.get(mission_id)
        if mission and getattr(mission, "description", ""):
            self.ctx.current_goal = mission.description

    async def _beat(self):
        """
        One full cognitive cycle.

        This is the "thought" of A.M.Y. Every beat she:
        1. Opens her senses
        2. Decides what to focus on
        3. Thinks about it recursively
        4. Takes action
        5. Learns from the result
        6. Checks if she found something worth reporting
        """
        log.debug("heartbeat.beat", cycle=self.ctx.cycle_number, state=self.ctx.state.value)

        # ──────────── 1. PERCEIVE ────────────
        self.ctx.state = CognitiveState.PERCEIVING
        perceptions = await self._perceive()

        # ──────────── 2. ATTEND (Global Workspace) ────────────
        self.ctx.state = CognitiveState.ATTENDING
        focus = await self._attend(perceptions)
        self.ctx.current_focus = focus.get("content", "")

        # ──────────── 3. THINK (Recursive Reasoning) ────────────
        self.ctx.state = CognitiveState.THINKING
        thought = await self._think(focus)

        # ──────────── 4. ACT ────────────
        self.ctx.state = CognitiveState.ACTING
        action_result = await self._act(thought)
        self.metrics.record_action(thought.get("action_type", "think_more"), action_result)

        # ──────────── LOOP DETECTION ────────────
        current_action = thought.get("action_type", "think_more")
        if current_action == self._last_action_type:
            self._consecutive_same_action += 1
        else:
            self._consecutive_same_action = 0
            self._last_action_type = current_action
        if self._consecutive_same_action >= 8:
            log.warning(
                "heartbeat.loop_detected",
                action=current_action,
                streak=self._consecutive_same_action,
            )
            # Force a reflection immediately
            self.ctx.cycles_since_reflection = self.config["max_cycles_before_reflection"]

        # ──────────── MISSION COMPLETION DETECTION ────────────
        content = thought.get("content", "")
        _mission_complete_phrases = (
            "MISSION COMPLETE", "MISSION STATUS: COMPLETE",
            "FINAL MISSION CLOSURE", "DEFINITIVE MISSION CLOSE",
            "FINAL MISSION ARCHIVE", "MISSION DEFINITIVELY COMPLETE",
            "SYNTHESIS COMPLETE", "DEFINITIVE SYNTHESIS",
            "FINAL SYNTHESIS", "DEFINITIVELY COMPLETE",
            "FINAL COMPREHENSIVE SYNTHESIS", "FINAL SYNTHESIS\n",
        )
        _content_lower = content.lower()
        _is_mission_complete_thought = (
            any(phrase in content for phrase in _mission_complete_phrases)
            or "research is complete" in _content_lower
            or "mission is complete" in _content_lower
            or "all sub-goals" in _content_lower and "complete" in _content_lower
        )
        if _is_mission_complete_thought:
            self._mission_complete_streak += 1
            log.info(
                "heartbeat.mission_complete_signal",
                streak=self._mission_complete_streak,
                action=current_action,
            )
            if self._mission_complete_streak >= 3:
                log.info(
                    "heartbeat.mission_complete_detected",
                    streak=self._mission_complete_streak,
                )
                await self._advance_to_next_mission(thought)
                self._mission_complete_streak = 0
                self._consecutive_same_action = 0
        elif current_action == "think_more":
            # Only reset streak on a think_more that does NOT signal completion
            self._mission_complete_streak = 0

        # ──────────── 5. LEARN ────────────
        self.ctx.state = CognitiveState.LEARNING
        await self._learn(thought, action_result)

        # ──────────── 6. CHECK FOR BREAKTHROUGH ────────────
        await self._check_breakthrough(thought, action_result)

        # ──────────── 7. MAYBE REFLECT ────────────
        self.ctx.cycles_since_reflection += 1
        if self.ctx.cycles_since_reflection >= self.config["max_cycles_before_reflection"]:
            self.ctx.state = CognitiveState.REFLECTING
            await self._reflect()
            self.ctx.cycles_since_reflection = 0

        # ──────────── ADAPT HEARTBEAT RATE ────────────
        self._adapt_interval()

    async def _perceive(self) -> list[dict]:
        """
        Sample all senses. What's happening in the world right now?
        Unlike a traditional AI that only perceives when prompted,
        A.M.Y continuously samples her environment.
        """
        perceptions = []

        # Time perception — always active
        time_data = await self.time_sensor.sense()
        perceptions.append({"source": "time", "data": time_data})

        # Current goal context
        current_goals = await self.goal_stack.get_active_goals()
        perceptions.append({"source": "goals", "data": current_goals})

        # World model predictions vs reality (surprise detection)
        surprise = await self.world_model.compute_surprise(perceptions)
        self.ctx.surprise_level = surprise
        perceptions.append({"source": "surprise", "data": {"level": surprise}})

        # Curiosity signal — what does A.M.Y *want* to know?
        curiosity_signal = await self.curiosity.get_signal(
            world_model=self.world_model,
            goal_stack=self.goal_stack,
        )
        perceptions.append({"source": "curiosity", "data": curiosity_signal})

        return perceptions

    async def _attend(self, perceptions: list[dict]) -> dict:
        """
        Global Workspace: multiple modules compete for the spotlight.
        Only one "thought" gets broadcast to all other modules.
        """
        candidates = []

        # Goal-directed attention: what does the current goal need?
        goal_candidate = await self.goal_stack.get_attention_candidate()
        if goal_candidate:
            candidates.append({
                "content": goal_candidate["description"],
                "source": "goal_stack",
                "priority": goal_candidate.get("priority", 0.5),
                "type": "goal_directed",
            })

        # Curiosity-driven attention: what is surprising/novel?
        if self.ctx.surprise_level > self.curiosity.config.get("surprise_threshold", 0.7):
            candidates.append({
                "content": f"High surprise detected: {self.ctx.surprise_level:.2f}",
                "source": "curiosity",
                "priority": self.ctx.surprise_level,
                "type": "curiosity_driven",
            })

        # Memory-driven: does something from the past connect to now?
        memory_candidate = await self.episodic_memory.get_recent_relevant(
            context=self.ctx.current_goal
        )
        if memory_candidate:
            candidates.append({
                "content": memory_candidate.get("content", ""),
                "source": "episodic_memory",
                "priority": memory_candidate.get("relevance", 0.3),
                "type": "memory_driven",
            })

        # Let the Global Workspace decide
        winner = await self.workspace.compete_and_broadcast(candidates)

        log.debug(
            "heartbeat.attention",
            focus=winner.get("content", "")[:100],
            source=winner.get("source", ""),
        )
        return winner

    async def _think(self, focus: dict) -> dict:
        """
        Recursive reasoning about the focused content.
        Can spawn sub-thoughts, like SOAR's universal subgoaling.
        """
        # Gather active sub-goals for context
        active_goals = await self.goal_stack.get_active_goals()
        sub_goals = [
            g.get("description", "") for g in active_goals
            if g.get("depth", 0) > 0
        ][:5]

        # Meta-review feedback: recurring weaknesses synthesized from prior
        # paper reviews, fed into the prompt so later cycles pre-empt repeated
        # mistakes (the Co-Scientist "learning without backprop" loop). Empty
        # until enough recurring signal has accumulated.
        meta_feedback = ""
        if self.self_retrain is not None:
            try:
                meta_feedback = self.self_retrain.feedback_prompt_suffix()
            except Exception as exc:
                log.warning("heartbeat.meta_feedback_failed", error=str(exc))

        thought = await self.reasoning.reason(
            focus=focus,
            context={
                "current_goal": self.ctx.current_goal,
                "cycle": self.ctx.cycle_number,
                "recent_thoughts": self.ctx.thoughts[-5:],
                "recent_queries": self._recent_queries[-15:],
                "recent_hypotheses": list(self._recent_hypotheses)[-8:],
                "consecutive_same_action": self._consecutive_same_action,
                "last_action_type": self._last_action_type,
                "active_sub_goals": sub_goals,
                "meta_review_feedback": meta_feedback,
            },
            world_model=self.world_model,
            semantic_memory=self.semantic_memory,
            skill_library=self.skill_library,
        )

        # Record the thought in the stream of consciousness
        self.ctx.thoughts.append(thought)
        if len(self.ctx.thoughts) > 100:
            self.ctx.thoughts = self.ctx.thoughts[-50:]

        return thought

    async def _act(self, thought: dict) -> dict:
        """
        Turn thought into action. This could be:
        - Research: search for papers, read articles
        - Experiment: write and run Python code in sandbox
        - Run script: write and run bash scripts for data processing, file ops
        - Write paper: synthesize findings into a structured academic PDF paper
        - Peer review paper: send hypothesis to Atlas for full scientific validation + peer review
        - Decompose: break a goal into sub-goals
        - Create: write a new skill/tool
        - Nothing: sometimes the best action is to keep thinking
        """
        action_type = thought.get("action_type", "think_more")
        blocked = self._safety_block_for_thought(action_type, thought)
        if blocked:
            return blocked

        if action_type == "research":
            return await self._act_research(thought)
        elif action_type == "search_literature":
            return await self._act_search_literature(thought)
        elif action_type == "experiment":
            return await self._act_experiment(thought)
        elif action_type == "run_script":
            return await self._act_run_script(thought)
        elif action_type == "write_paper":
            return await self._act_write_paper(thought)
        elif action_type == "peer_review_paper":
            return await self._act_peer_review_paper(thought)
        elif action_type == "run_scientific_tool":
            return await self._act_run_scientific_tool(thought)
        elif action_type == "decompose_goal":
            return await self._act_decompose(thought)
        elif action_type == "create_skill":
            return await self._act_create_skill(thought)
        elif action_type == "think_more":
            # Recursive thinking — go deeper
            return {"type": "think_more", "depth": thought.get("depth", 0) + 1}
        else:
            return {"type": "noop"}

    def _safety_block_for_thought(self, action_type: str, thought: dict) -> dict | None:
        """Fail-closed anti-abuse check before A.M.Y executes side-effecting actions."""
        try:
            from core.safety_kernel import blocked_message, evaluate_safety

            action_details = _action_details(thought)
            content = json.dumps(
                {
                    "content": thought.get("content", ""),
                    "hypothesis": thought.get("hypothesis", action_details.get("hypothesis", "")),
                    "research_query": thought.get("research_query", action_details.get("research_query", "")),
                    "script": thought.get("script", action_details.get("script", "")),
                    "code": thought.get("code", action_details.get("code", "")),
                    "purpose": thought.get("purpose", action_details.get("purpose", "")),
                    "paper_topic": thought.get("paper_topic", action_details.get("paper_topic", "")),
                    "tool_name": thought.get("tool_name", action_details.get("tool_name", "")),
                    "tool_input": thought.get("tool_input", action_details.get("tool_input", "")),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            decision = evaluate_safety(
                operation=f"heartbeat.{action_type}",
                content=content,
                domain=thought.get("domain", action_details.get("domain", "")),
                tool_name=thought.get("tool_name", action_details.get("tool_name", "")),
            )
        except Exception as exc:
            return {
                "type": action_type,
                "success": False,
                "error": "Blocked by safety policy",
                "reason": f"safety kernel unavailable: {exc}",
            }

        if decision.allowed:
            return None

        log.warning(
            "heartbeat.safety_blocked",
            action_type=action_type,
            rules=decision.matched_rules,
        )
        return {
            "type": action_type,
            "success": False,
            "error": "Blocked by safety policy",
            "message": blocked_message(decision),
            "safety_decision": decision.to_dict(),
        }

    async def _act_research(self, thought: dict) -> dict:
        """Search the web/papers for information related to the current thought."""
        query = thought.get("research_query", thought.get("content", ""))
        results = await self.web_sensor.search(query)

        # Log query to avoid repetition
        self._recent_queries.append(query[:100])
        if len(self._recent_queries) > 20:
            self._recent_queries = self._recent_queries[-20:]

        if results:
            await self.episodic_memory.record(
                event_type="research",
                content=f"Searched: {query}",
                metadata={"results_count": len(results), "query": query},
            )
            # Feed results into world model
            await self.world_model.update_with_observations(results)

        return {"type": "research", "query": query, "results": results}

    async def _act_search_literature(self, thought: dict) -> dict:
        """Búsqueda de literatura científica real usando Atlas (arXiv, PubMed, Semantic Scholar)."""
        from core.atlas_tools import get_atlas_tools
        if self._atlas_tools is None:
            self._atlas_tools = get_atlas_tools()

        query = str(thought.get("research_query", thought.get("hypothesis", thought.get("content", ""))))
        domain = thought.get("domain", "medicine")
        self._recent_queries.append(str(query)[:100])
        if len(self._recent_queries) > 20:
            self._recent_queries = self._recent_queries[-20:]

        log.info("heartbeat.atlas_literature_search", query=query[:80], domain=domain)
        result = await self._atlas_tools.search_literature(query, domain=domain)

        papers = result.get("papers", result.get("sources", {}).get("papers", []))
        support = result.get("support_score", 0)

        # Feed real papers into world model
        if papers:
            obs = [
                {
                    "title": p.get("title", "") if isinstance(p, dict) else str(p),
                    "content": p.get("abstract", p.get("summary", "")) if isinstance(p, dict) else "",
                }
                for p in papers[:6]
            ]
            await self.world_model.update_with_observations(obs)

        await self.episodic_memory.record(
            event_type="literature_search",
            content=f"Literature: {query[:80]} | support={support:.2f} | papers={len(papers)}",
            metadata={"query": query, "domain": domain, "support_score": support, "papers_found": len(papers)},
        )
        log.info("heartbeat.atlas_literature_done", papers=len(papers), support=round(support, 2))
        return {"type": "search_literature", "query": query, "papers": papers, "support_score": support}

    async def _act_experiment(self, thought: dict) -> dict:
        """Write and execute code to test a hypothesis."""
        blocked = self._safety_block_for_thought("experiment", thought)
        if blocked:
            return blocked
        hypothesis = thought.get("hypothesis", "")
        code = thought.get("code", "")

        if not code:
            # Ask reasoning engine to generate experimental code
            code = await self.reasoning.generate_experiment_code(
                hypothesis=hypothesis,
                available_skills=await self.skill_library.list_skills(),
            )

        # Execute in sandbox via CodeExperimentSkill for provenance tracking
        from skills.code_experiment import CodeExperimentSkill
        skill = CodeExperimentSkill(self._sandbox_config())
        result = await skill.run_experiment(hypothesis=hypothesis, code=code, language="python")

        await self.episodic_memory.record(
            event_type="experiment",
            content=f"Hypothesis: {hypothesis}",
            metadata={"code": code, "result": result},
        )

        return {"type": "experiment", "hypothesis": hypothesis, "result": result}

    async def _act_decompose(self, thought: dict) -> dict:
        """Break a complex goal into sub-goals."""
        sub_goals = thought.get("sub_goals", [])
        for sg in sub_goals:
            await self.goal_stack.push_subgoal(
                parent=self.ctx.current_goal,
                description=sg,
            )
        return {"type": "decompose", "sub_goals": sub_goals}

    async def _act_create_skill(self, thought: dict) -> dict:
        """Create a new reusable skill and save it to the library."""
        skill = thought.get("skill", {})
        await self.skill_library.register_skill(
            name=skill.get("name", "unnamed"),
            description=skill.get("description", ""),
            code=skill.get("code", ""),
        )
        return {"type": "create_skill", "skill_name": skill.get("name")}

    async def _act_run_script(self, thought: dict) -> dict:
        """Write and run a bash script for data processing or file operations."""
        blocked = self._safety_block_for_thought("run_script", thought)
        if blocked:
            return blocked
        script = thought.get("script", "")
        purpose = thought.get("purpose", "")
        language = thought.get("language", "bash")

        if not script:
            log.warning("heartbeat.run_script_empty")
            return {"type": "run_script", "success": False, "error": "no script provided"}

        from sandbox.executor import SandboxExecutor
        executor = SandboxExecutor(self._sandbox_config())
        result = await executor.execute(script, language=language)

        log.info(
            "heartbeat.script_executed",
            purpose=purpose[:80],
            success=result["success"],
            lines=len(result.get("stdout", "").splitlines()),
        )

        await self.episodic_memory.record(
            event_type="script_execution",
            content=f"Script: {purpose}",
            metadata={
                "script": script[:500],
                "success": result["success"],
                "stdout": result.get("stdout", "")[:500],
                "stderr": result.get("stderr", "")[:300],
            },
        )

        # Feed stdout into world model as an observation if successful
        if result["success"] and result.get("stdout"):
            await self.world_model.update_with_observations(
                [{"title": f"Script result: {purpose}", "content": result["stdout"][:2000]}]
            )

        return {"type": "run_script", "purpose": purpose, "result": result}

    async def _act_write_paper(self, thought: dict) -> dict:
        """Synthesize current findings into a structured academic paper (PDF + Markdown).
        
        Integrates Atlas scientific tool results as computational evidence sections.
        """
        blocked = self._safety_block_for_thought("write_paper", thought)
        if blocked:
            return blocked
        from communication.paper_generator import PaperGenerator

        action_details = _action_details(thought)
        topic = thought.get("paper_topic", action_details.get("paper_topic", self.ctx.current_goal))
        log.info("heartbeat.writing_paper", topic=topic[:80])

        # Gather knowledge context
        facts = [
            _belief_to_research_fact(b)
            for b in list(self.world_model.beliefs.values())[:30]
        ]

        recent_thoughts = [
            t.get("content", "")[:200]
            for t in self.ctx.thoughts[-10:]
            if isinstance(t, dict)
        ]

        breakthrough = thought.get("breakthrough_content", "")
        if not breakthrough and self.ctx.thoughts:
            last = self.ctx.thoughts[-1]
            if isinstance(last, dict):
                breakthrough = last.get("content", "")[:800]

        # ── INTEGRACIÓN: Resultados de herramientas Atlas ─────────────────────
        # Recuperar resultados de herramientas científicas ejecutadas recientemente
        tool_results = list(getattr(self, "_tool_results_history", []))
        tool_sections = []
        experiment_ids = []
        
        if tool_results:
            tool_content_lines = [
                "This study employed computational verification through the AXIOM Atlas scientific platform. "
                "The following tools were executed to validate mathematical and statistical claims:",
                "",
            ]
            for tr in tool_results[-10:]:  # Last 10 tool executions
                tool_name = tr.get("tool_name", "unknown")
                tool_input = tr.get("input", "")
                result = tr.get("result", "")
                domain = tr.get("domain", "")
                
                # Format result for paper
                result_str = str(result)[:300] if result else "No output"
                tool_content_lines.append(f"**{tool_name}** (domain: {domain}):")
                tool_content_lines.append(f"- Input: `{tool_input}`")
                tool_content_lines.append(f"- Result: {result_str}")
                tool_content_lines.append("")
                
                exp_id = tr.get("experiment_id")
                if exp_id:
                    experiment_ids.append(exp_id)
            
            tool_sections.append({
                "heading": "Computational Verification",
                "content": "\n".join(tool_content_lines),
            })
        # ─────────────────────────────────────────────────────────────────────

        # ── INTEGRACIÓN: Literatura real de Atlas ────────────────────────────
        # Buscar papers reales sobre el tema para usarlos como referencias
        literature_papers = []
        try:
            from core.atlas_tools import get_atlas_tools
            if self._atlas_tools is None:
                self._atlas_tools = get_atlas_tools()
            
            # Detectar dominio del topic
            domain_keywords = {
                "mathematics": ["prime", "number", "theorem", "conjecture", "equation", "algebra"],
                "physics": ["quantum", "energy", "rydberg", "hydrogen", "atom", "spectrum"],
                "chemistry": ["molecular", "bond", "weight", "organic", "compound", "hückel"],
                "biology": ["dna", "protein", "sequence", "gene", "amino", "bioinformatics"],
                "statistics": ["distribution", "correlation", "normal", "test", "variance"],
                "astronomy": ["star", "stellar", "exoplanet", "galaxy", "spectral", "cosm"],
                "medicine": ["clinical", "drug", "therapy", "disease", "protein", "vaccine"],
                "neuroscience": ["neural", "brain", "synaptic", "neuron", "plasticity"],
                "climate": ["climate", "temperature", "global", "co2", "atmospheric"],
                "engineering": ["manufacturing", "3d", "printing", "structural", "finite"],
            }
            topic_lower = topic.lower()
            domain = "mathematics"
            for d, kws in domain_keywords.items():
                if any(kw in topic_lower for kw in kws):
                    domain = d
                    break
            
            # Ejecutar búsqueda de literatura real
            lit_result = await self._atlas_tools.search_literature(topic, domain=domain)
            papers_raw = lit_result.get("papers", lit_result.get("sources", {}).get("papers", []))
            if not papers_raw:
                # Fallback: usar literature_search del worker
                pass
            
            if papers_raw:
                # ``search_literature`` already applies a conservative
                # domain/topic relevance gate.  Keep that audit metadata and
                # never refill the six slots with results it discarded.
                for p in papers_raw[:6]:
                    if isinstance(p, dict):
                        literature_papers.append(p)
                    elif isinstance(p, str):
                        literature_papers.append({"title": p, "authors": "", "year": ""})
        except Exception as e:
            log.warning("heartbeat.literature_search_for_paper_failed", error=str(e))
        # ─────────────────────────────────────────────────────────────────────

        generator = PaperGenerator(reasoning_engine=self.reasoning)
        result = await generator.generate_from_llm(
            topic=topic,
            knowledge_facts=facts,
            recent_thoughts=recent_thoughts,
            breakthrough_content=breakthrough,
            tool_sections=tool_sections,
            experiment_ids=experiment_ids,
            literature_papers=literature_papers,
        )

        if "error" not in result:
            log.info(
                "heartbeat.paper_written",
                title=result.get("title", ""),
                pdf=result.get("pdf_path", ""),
                words=result.get("word_count", 0),
            )
            await self.episodic_memory.record(
                event_type="paper_written",
                content=f"Paper: {result.get('title','')}",
                metadata={
                    "markdown_path": result.get("markdown_path"),
                    "pdf_path": result.get("pdf_path"),
                    "word_count": result.get("word_count", 0),
                    "tools_used": [t.get("tool_name") for t in tool_results[-10:]],
                    "publication_status": result.get("publication_status"),
                    "duplicate_draft": result.get("duplicate_draft", False),
                },
            )
            # Feed this paper's reviews into the meta-review feedback loop so the
            # recurring-weakness digest (used to sharpen later prompts) builds up
            # over the run. Best-effort; guarded.
            if self.self_retrain is not None:
                try:
                    self.self_retrain.record_review(
                        reflection_result=result.get("reflection") or result.get("self_review"),
                        peer_review=result.get("peer_review"),
                    )
                except Exception as exc:
                    log.warning("heartbeat.record_review_failed", error=str(exc))

        return {"type": "write_paper", "result": result}

    async def _act_run_scientific_tool(self, thought: dict) -> dict:
        """Execute a specific Atlas scientific tool (SymPy, NumPy, BioPython, etc.)."""
        blocked = self._safety_block_for_thought("run_scientific_tool", thought)
        if blocked:
            return blocked

        from core.atlas_tools import assess_tool_output, get_atlas_tools
        if self._atlas_tools is None:
            self._atlas_tools = get_atlas_tools()

        # Support both direct fields and nested action_details
        action_details = _action_details(thought)
        tool_name = thought.get("tool_name", action_details.get("tool_name", ""))
        tool_input = thought.get("tool_input", action_details.get("tool_input", ""))
        domain = thought.get("domain", action_details.get("domain", "mathematics"))

        if not tool_name:
            log.warning("heartbeat.run_scientific_tool.no_tool_name")
            return {"type": "run_scientific_tool", "success": False, "error": "no tool_name provided"}

        log.info("heartbeat.running_scientific_tool", tool=tool_name, domain=domain, input_preview=tool_input[:60])

        try:
            started = time.monotonic()
            result = await self._atlas_tools.run_scientific_tool(tool_name, tool_input, domain)
            duration_seconds = time.monotonic() - started
            worker_metrics_fn = getattr(self._atlas_tools, "worker_metrics", None)
            worker_metrics = worker_metrics_fn() if callable(worker_metrics_fn) else {}
            assessment = assess_tool_output(result, tool_name=tool_name)
            if not assessment["usable"]:
                log.warning(
                    "heartbeat.scientific_tool_unusable",
                    tool=tool_name,
                    markers=assessment["markers"],
                    result_preview=assessment["preview"][:120],
                )
                return {
                    "type": "run_scientific_tool",
                    "tool_name": tool_name,
                    "success": False,
                    "error": "unusable_tool_output",
                    "assessment": assessment,
                    "result": result,
                }
            log.info("heartbeat.scientific_tool_done", tool=tool_name, result_preview=str(result)[:80])

            from core.provenance import get_provenance_manager
            provenance_record = get_provenance_manager().record_execution(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=str(result),
                success=True,
                duration_seconds=duration_seconds,
                domain=domain,
            )
            experiment_id = provenance_record["experiment_id"]

            # Record in episodic memory
            await self.episodic_memory.record(
                event_type="scientific_tool_execution",
                content=f"Tool {tool_name}: {tool_input[:80]}",
                metadata={
                    "tool_name": tool_name,
                    "domain": domain,
                    "input": tool_input,
                    "result": str(result)[:500],
                    "experiment_id": experiment_id,
                    "provenance_path": f"data/experiments/{experiment_id}/provenance.json",
                    "duration_seconds": round(duration_seconds, 3),
                    "atlas_worker": worker_metrics,
                },
            )

            # Feed result into world model
            await self.world_model.update_with_observations(
                [{"title": f"Scientific tool result: {tool_name}", "content": str(result)[:2000]}]
            )

            # Store for paper writing integration
            self._tool_results_history.append({
                "tool_name": tool_name,
                "domain": domain,
                "input": tool_input,
                "result": result,
                "timestamp": time.time(),
                "experiment_id": experiment_id,
                "duration_seconds": duration_seconds,
                "atlas_worker": worker_metrics,
            })

            return {
                "type": "run_scientific_tool",
                "tool_name": tool_name,
                "success": True,
                "result": result,
                "experiment_id": experiment_id,
                "provenance_path": f"data/experiments/{experiment_id}/provenance.json",
                "duration_seconds": duration_seconds,
                "atlas_worker": worker_metrics,
            }
        except Exception as e:
            log.error("heartbeat.scientific_tool_error", tool=tool_name, error=str(e))
            return {"type": "run_scientific_tool", "tool_name": tool_name, "success": False, "error": str(e)}

    async def _act_peer_review_paper(self, thought: dict) -> dict:
        """
        Envía la hipótesis actual a AXIOM Atlas para:
        - Verificación de literatura real (arXiv, PubMed)
        - Ejecución de herramientas científicas (SymPy, NumPy, BioPython)
        - Peer review autónomo (AutonomousPeerReviewService)
        - Generación de paper académico validado
        """
        blocked = self._safety_block_for_thought("peer_review_paper", thought)
        if blocked:
            return blocked
        from core.atlas_bridge import AtlasBridge

        if self._atlas_bridge is None:
            atlas_config = self.config.get("atlas", {})
            if not isinstance(atlas_config, dict):
                atlas_config = {}
            self._atlas_bridge = AtlasBridge(
                timeout_seconds=atlas_config.get("peer_review_timeout_seconds"),
                model_name=atlas_config.get("model"),
            )

        if not self._atlas_bridge.available:
            log.warning("heartbeat.atlas_not_available")
            return {"type": "peer_review_paper", "success": False, "error": "Atlas no disponible"}

        hypothesis = thought.get("hypothesis", thought.get("content", ""))[:800]
        domain = thought.get("domain", "medicine")
        topic = thought.get("paper_topic", self.ctx.current_goal)

        # ── DETECTOR DE HIPÓTESIS REPETIDAS ──────────────────────────────────
        # Si A.M.Y envía variantes de la misma hipótesis ≥4 veces, forzar cambio de tema
        hyp_fingerprint = hypothesis[:120].lower().strip()
        similar_count = sum(
            1 for h in self._recent_hypotheses
            if len(set(hyp_fingerprint.split()) & set(h.split())) / max(len(hyp_fingerprint.split()), 1) > 0.5
        )
        self._recent_hypotheses.append(hyp_fingerprint)

        if similar_count >= 3:
            log.warning(
                "heartbeat.hypothesis_loop_detected",
                similar_count=similar_count,
                hypothesis_preview=hypothesis[:80],
            )
            # Forzar inmediatamente una reflexión profunda para cambiar de tema
            self.ctx.cycles_since_reflection = self.config["max_cycles_before_reflection"]
            await self.goal_stack.push_subgoal(
                parent=self.goal_stack.mission_id or "",
                description=(
                    "EXPLORAR NUEVO ÁNGULO: La hipótesis actual ya fue validada varias veces. "
                    "Investiga una pregunta claramente distinta dentro de la misión, o un método "
                    "complementario: un mecanismo no explorado, una técnica experimental diferente, "
                    "un modelo predictivo, o un análisis de los casos en que la hipótesis NO se cumple."
                ),
                priority=1.0,
            )
            return {
                "type": "peer_review_paper",
                "success": False,
                "error": "hypothesis_loop_detected — forzando cambio de tema",
            }
        # ─────────────────────────────────────────────────────────────────────

        # Gather key facts as context
        facts = [
            _belief_to_research_fact(b)
            for b in list(self.world_model.beliefs.values())[:15]
        ]

        # ── INTEGRACIÓN: Incluir resultados de herramientas en el peer review ──
        tool_results = list(getattr(self, "_tool_results_history", []))
        if tool_results:
            # Agregar resultados de herramientas como facts adicionales
            for tr in tool_results[-5:]:
                facts.append({
                    "subject": f"Tool:{tr.get('tool_name', 'unknown')}",
                    "predicate": "executed_with_result",
                    "object": str(tr.get("result", ""))[:500],
                    "confidence": 0.95,
                    "source": "atlas_tool_execution",
                    "experiment_id": tr.get("experiment_id", ""),
                })
        # ─────────────────────────────────────────────────────────────────────

        log.info(
            "heartbeat.sending_to_atlas",
            domain=domain,
            topic=topic[:80],
            hypothesis=hypothesis[:100],
        )

        result = await self._atlas_bridge.run_research(
            domain=domain,
            topic=topic,
            hypothesis=hypothesis,
            knowledge_facts=facts,
            max_iterations=3,
            target_score=7,
        )

        if result.get("success"):
            score = result.get("score", 0)
            accepted = result.get("accepted", False)
            paper = result.get("paper", "")
            feedback = result.get("feedback", "")

            log.info(
                "heartbeat.atlas_result",
                score=score,
                accepted=accepted,
                paper_words=len(paper.split()),
            )

            # Run AMY's local quality gate before treating Atlas output as accepted science.
            from communication.atlas_quality_gate import AtlasPaperQualityGate
            from communication.paper_generator import PAPERS_DIR
            from datetime import datetime
            import re

            review_text = result.get("review", "")
            content_body = paper if paper else (
                f"## Hypothesis\n\n{hypothesis}\n\n"
                f"## Peer Review\n\n{review_text or feedback or '(no review text)'}\n"
            )
            gate = AtlasPaperQualityGate(**self.config.get("atlas_quality_gate", {}))
            # Citation verification is network-bound and exposes a synchronous
            # compatibility API.  Keep it off the cognitive event loop.
            quality_decision = await asyncio.to_thread(
                gate.evaluate,
                paper_text=content_body,
                domain=domain,
                atlas_result=result,
            )
            original_accepted = accepted
            accepted = accepted and quality_decision.passed
            result["accepted"] = accepted
            result["quality_gate"] = quality_decision.to_dict()

            if original_accepted and not accepted:
                log.warning(
                    "heartbeat.atlas_acceptance_downgraded",
                    reasons=quality_decision.reasons,
                    score=score,
                )

            # Save accepted papers in papers/ and failed reviews in papers/quarantine/.
            if score >= 5 or original_accepted:
                target_dir = PAPERS_DIR if quality_decision.passed else PAPERS_DIR / "quarantine"
                target_dir.mkdir(parents=True, exist_ok=True)
                slug = re.sub(r"[^\w]", "_", topic[:50])
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                prefix = "ATLAS" if quality_decision.passed else "ATLAS_NEEDS_VALIDATION"
                atlas_md = target_dir / f"{prefix}_{slug}_{ts}.md"
                status_label = "ACCEPTED" if accepted else "NEEDS VALIDATION"
                quality_notes = "\n".join(f"- {reason}" for reason in quality_decision.reasons)
                if not quality_notes:
                    quality_notes = "- Passed AMY local quality gate"
                header = (
                    f"# [ATLAS {status_label}, score={score}/10]\n"
                    f"**Topic:** {topic}\n"
                    f"**Domain:** {domain}\n"
                    f"**Score:** {score}/10\n"
                    f"**AMY quality gate:** {quality_decision.status}\n\n"
                    "## AMY Quality Gate\n\n"
                    f"{quality_notes}\n\n"
                )
                atlas_md.write_text(header + quality_decision.marked_content, encoding="utf-8")
                log.info(
                    "heartbeat.atlas_paper_saved",
                    path=str(atlas_md),
                    score=score,
                    accepted=accepted,
                    quality_gate=quality_decision.status,
                )

            # Record to episodic memory
            await self.episodic_memory.record(
                event_type="atlas_peer_review",
                content=f"Atlas reviewed: {topic[:80]} | score={score}/10 accepted={accepted}",
                metadata={
                    "score": score,
                    "accepted": accepted,
                    "feedback": feedback[:400],
                    "tools_used": result.get("tools_used", []),
                    "references": result.get("references", []),
                    "quality_gate": result.get("quality_gate", {}),
                },
            )

            # Feed feedback back into world model
            if feedback:
                await self.world_model.update_with_observations(
                    [{"title": f"Peer review feedback (score {score}/10)", "content": feedback}]
                )

            # If not accepted, push improvement sub-goal
            if not accepted and (feedback or quality_decision.reasons):
                improvement = feedback[:150] if feedback else "; ".join(quality_decision.reasons)[:150]
                await self.goal_stack.push_subgoal(
                    parent=self.goal_stack.mission_id or "",
                    description=f"Address Atlas validation gap: {improvement}",
                    priority=0.9,
                )

        return {"type": "peer_review_paper", **result}

    async def _learn(self, thought: dict, action_result: dict):
        """
        Update all memory systems with what was learned.
        This is where A.M.Y actually grows.
        """
        # Record to episodic memory
        await self.episodic_memory.record(
            event_type="cognitive_cycle",
            content=thought.get("content", ""),
            metadata={
                "cycle": self.ctx.cycle_number,
                "action_type": action_result.get("type", ""),
                "focus_source": thought.get("source", ""),
            },
        )

        # Update semantic memory if new facts discovered
        new_facts = thought.get("new_facts", [])
        for fact in new_facts:
            await self.semantic_memory.add_fact(
                subject=fact.get("subject", ""),
                predicate=fact.get("predicate", ""),
                obj=fact.get("object", ""),
                confidence=fact.get("confidence", 0.5),
                source=f"cycle_{self.ctx.cycle_number}",
            )

        # Update world model
        await self.world_model.update_beliefs(thought, action_result)

        # Update curiosity (novelty decays for explored topics)
        await self.curiosity.update(thought, action_result)

    async def _check_breakthrough(self, thought: dict, action_result: dict):
        """Check if we discovered something worth reporting to the human."""
        is_breakthrough = await self.breakthrough_detector.evaluate(
            thought=thought,
            action_result=action_result,
            semantic_memory=self.semantic_memory,
        )

        if is_breakthrough:
            self.ctx.last_breakthrough_time = time.time()
            report = await self.report_generator.generate(
                thought=thought,
                action_result=action_result,
                context={
                    "cycle": self.ctx.cycle_number,
                    "goal": self.ctx.current_goal,
                },
            )
            log.info("heartbeat.breakthrough", report_preview=report[:200])

    async def _reflect(self):
        """
        Periodic reflection — like stepping back and thinking about your thinking.
        Consolidates episodic memories into semantic knowledge.
        Reviews and prunes beliefs with low confidence.
        Generates new research directions.
        """
        log.info("heartbeat.reflecting", cycles_since_last=self.ctx.cycles_since_reflection)
        self.metrics.record_reflection()
        # Emit a periodic status snapshot — reflection is a natural checkpoint,
        # so health is visible in the logs/monitoring without extra tooling.
        log.info("heartbeat.status", **self.metrics.snapshot())
        await self.reflection.reflect(
            world_model=self.world_model,
            goal_stack=self.goal_stack,
        )

        # Consolidation pass ("REM sleep"): extract recurring patterns and
        # successful-experiment skills from episodic memory. Throttled so it
        # doesn't run on every reflection.
        self._reflections_since_consolidation += 1
        if self._reflections_since_consolidation >= self._reflections_per_consolidation:
            self._reflections_since_consolidation = 0
            try:
                await self._consolidator.consolidate()
                self.metrics.record_consolidation()
                skills = await self.procedural_memory.list_skills()
                log.info("heartbeat.consolidated", skill_count=len(skills))
            except Exception as exc:
                log.warning("heartbeat.consolidation_failed", error=str(exc))

        # Self-retrain pass: recalibrate world-model belief confidences from
        # accumulated evidence (heuristic, persisted). Throttled. Previously
        # this module existed but was never run in the live loop — wiring it
        # here is what makes the "recalibrates belief confidences" claim true
        # at runtime. Guarded so a missing module is a safe no-op.
        if self.self_retrain is not None:
            self._reflections_since_retrain += 1
            if self._reflections_since_retrain >= self._reflections_per_retrain:
                self._reflections_since_retrain = 0
                try:
                    record = await self.self_retrain.retrain_world_model(
                        self.world_model, self.episodic_memory, self.semantic_memory
                    )
                    if record:
                        log.info("heartbeat.self_retrain", **(record if isinstance(record, dict) else {}))
                except Exception as exc:
                    log.warning("heartbeat.self_retrain_failed", error=str(exc))

    def _adapt_interval(self):
        """
        Adapt heartbeat frequency based on current state.
        High surprise / active experimentation → faster
        Idle / reflecting → slower
        """
        if self.ctx.surprise_level > 0.8:
            self._current_interval = self.config["focused_interval_seconds"]
        elif self.ctx.state == CognitiveState.REFLECTING:
            self._current_interval = self.config["idle_interval_seconds"]
        else:
            self._current_interval = self.config["base_interval_seconds"]

    async def _advance_to_next_mission(self, last_thought: dict):
        """
        Called when A.M.Y declares the current mission complete.

        Behaviour is governed by ``heartbeat.continuous_mission``:
          * False (Satisfaction Mode) — stop and hibernate to bound API usage.
          * True  — generate the next, deeper mission from what was learned
            and keep going (the autonomous "never sleeps" behaviour).
        """
        if not self.config.get("continuous_mission", False):
            log.info("heartbeat.mission_complete_hibernate", goal=self.ctx.current_goal[:120])
            await self.stop()
            return

        log.info("heartbeat.mission_complete_chaining", completed_goal=self.ctx.current_goal[:120])

        # Build context from what was learned
        known_facts = []
        for b in list(self.world_model.beliefs.values())[:15]:
            known_facts.append(f"- {b.content} (confidence {b.confidence:.0%})")
        facts_text = "\n".join(known_facts) if known_facts else "No beliefs yet"

        last_synthesis = last_thought.get("content", "")[:800]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are A.M.Y's mission generator. "
                    "The current research mission has been completed. "
                    "You must generate the NEXT, DEEPER research mission. "
                    "Be specific and scientifically ambitious. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Completed Mission\n{self.ctx.current_goal}\n\n"
                    f"## Key Knowledge Gained\n{facts_text}\n\n"
                    f"## Final Synthesis\n{last_synthesis}\n\n"
                    "Generate the NEXT deeper mission. It should:\n"
                    "- Go deeper into the most promising finding from the current mission\n"
                    "- Be specific and scientifically testable\n"
                    "- Build on what was learned, not repeat it\n\n"
                    "Return JSON:\n"
                    "{\n"
                    '  "next_mission": "specific deep research question",\n'
                    '  "rationale": "why this is the logical next step",\n'
                    '  "first_subgoals": ["subgoal 1", "subgoal 2", "subgoal 3"]\n'
                    "}"
                ),
            },
        ]

        try:
            import json as _json
            from cognition.reasoning import _extract_content, _clean_json

            response = await self.reasoning.client.chat(
                model=self.reasoning.fast_model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                format_json=True,
            )
            raw = _extract_content(response)
            raw = _clean_json(raw)
            result = _json.loads(raw)

            next_mission = result.get("next_mission", "")
            rationale = result.get("rationale", "")
            first_subgoals = result.get("first_subgoals", [])

            if not next_mission:
                # Valid JSON but no mission proposed. Without this, the method
                # would no-op while the caller already reset the completion
                # streak — so A.M.Y would sit on the finished mission, re-detect
                # "complete" ~3 cycles later, and loop with zero progress.
                # Route into the same fallback as a hard error.
                raise ValueError("LLM returned empty next_mission")

            if next_mission:
                log.info(
                    "heartbeat.next_mission_generated",
                    mission=next_mission[:120],
                    rationale=rationale[:80],
                )

                # Save completed mission to episodic memory
                await self.episodic_memory.record(
                    event_type="mission_completed",
                    content=f"COMPLETED: {self.ctx.current_goal}",
                    metadata={"synthesis": last_synthesis[:500]},
                )

                # Set the new mission
                await self.goal_stack.set_mission(
                    goal=next_mission,
                    description=rationale,
                )
                self.ctx.current_goal = next_mission
                self.ctx.thoughts = []
                self._recent_queries = []

                # Push first sub-goals
                for sg in first_subgoals[:4]:
                    if sg:
                        await self.goal_stack.push_subgoal(
                            parent=self.goal_stack.mission_id or "",
                            description=sg,
                            priority=0.8,
                        )

                log.info("heartbeat.new_mission_active", mission=next_mission[:100])

        except Exception as e:
            log.error("heartbeat.next_mission_error", error=str(e))
            # Fallback: push a meta-research goal
            await self.goal_stack.push_subgoal(
                parent=self.goal_stack.mission_id or "",
                description=(
                    "Design a computational experiment to validate the most promising "
                    "finding from the previous research phase"
                ),
                priority=0.9,
            )
