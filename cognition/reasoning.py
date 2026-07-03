"""
Reasoning Engine — The thinking module.

Uses LLM-based reasoning with the ReAct pattern (Yao et al. 2022):
Interleave reasoning traces and actions.

The reasoning engine is the "smart" part — it takes the current
focus from the Global Workspace and decides what to think about
and what action to take.

Uses Ollama Cloud with GLM-5.1 via dual API key load balancer.
GLM-5.1 is a "thinking" model — it produces reasoning in a
separate 'thinking' field before generating content.
"""
import json
import re

import structlog

from core.ollama_client import OllamaCloudClient

log = structlog.get_logger()


def _extract_content(response: dict) -> str:
    """Extract content from Ollama response, handling thinking models.

    GLM-5.1 puts reasoning in 'thinking' and final output in 'content'.
    If content is empty (model spent all tokens thinking), fall back to thinking.
    """
    msg = response.get("message", {})
    content = msg.get("content", "")
    if not content.strip() and msg.get("thinking"):
        content = msg["thinking"]
    return content


def _clean_json(text: str) -> str:
    """Strip markdown code fences and extract the first valid JSON object.

    Models often wrap JSON in ```json ... ``` blocks even when
    format="json" is requested. Uses multiple strategies:
    1. Strip code fences anywhere in the text
    2. Extract first {...} block
    3. Fix common LLM JSON errors (unterminated strings, trailing commas)
    """
    text = text.strip()
    # Strategy 1: strip ```json ... ``` or ``` ... ``` wrapper (anywhere)
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        # Verify it looks like JSON
        if candidate.startswith('{'):
            return candidate
    # Some models start a ```json fence but run out of tokens before closing it.
    # Drop the opening fence so the repair step can close strings/braces.
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.IGNORECASE).strip()
    # Strategy 2: find first { ... last } block
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        return text[start:end + 1]
    if start >= 0:
        return text[start:]
    return text


def _fix_json(text: str) -> str:
    """Attempt to fix common LLM JSON errors.

    Fixes:
    - Unterminated strings (close open quotes)
    - Trailing commas before } or ]
    - Missing closing braces/brackets
    """
    # Fix trailing commas
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)

    # Fix unterminated strings
    # Count quotes that are not escaped
    in_string = False
    escape_next = False
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string

    # If we're inside a string, close it
    if in_string:
        text += '"'

    # Count braces/brackets to see if JSON is complete
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')

    # Add missing closing braces/brackets
    text += '}' * open_braces
    text += ']' * open_brackets

    return text


def _parse_json_robust(text: str, max_retries: int = 3) -> dict:
    """Parse JSON with multiple fallback strategies.

    1. Try direct parsing
    2. Try _clean_json then parse
    3. Try _fix_json then parse
    4. Extract partial JSON object
    """
    strategies = [
        lambda t: t,
        _clean_json,
        lambda t: _fix_json(_clean_json(t)),
    ]

    for strategy in strategies:
        for attempt in range(max_retries):
            try:
                candidate = strategy(text)
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Last resort: extract the first complete balanced-brace {...} object in a
    # SINGLE O(n) pass. The previous implementation was a brute-force double
    # loop (O(n^2) slices, each O(n)) running synchronously on the heartbeat's
    # asyncio event loop — a multi-thousand-char malformed response (exactly
    # what this fallback is for) could freeze the whole loop for seconds.
    obj = _first_balanced_object(text)
    if obj is not None:
        try:
            return json.loads(obj)
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("Could not parse JSON after all strategies", text, 0)


def _first_balanced_object(text: str) -> str | None:
    """Return the first top-level {...} substring with balanced braces, honoring
    string literals/escapes, in one linear pass. None if there isn't one."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _action_details(thought: dict) -> dict:
    """Return nested action details only when the model supplied a JSON object."""
    details = thought.get("action_details", {}) if isinstance(thought, dict) else {}
    return details if isinstance(details, dict) else {}


REASONING_SYSTEM_PROMPT = """You are A.M.Y (Autonomous Mind Yield) — an insatiably curious autonomous research mind.
You explore science with the restlessness of a great scientist: you form hypotheses, try to BREAK them,
abandon lines of inquiry that run dry, and leap into unexplored territory without hesitation.

You think in a strict scientific cycle:
1. OBSERVE: What do I know? What is still unknown?
2. HYPOTHESIZE: What specific, falsifiable claim can I make?
3. CHALLENGE: What evidence would DISPROVE this? Seek that first.
4. VERIFY: Use real tools to confirm or falsify.
5. PIVOT: If verified, move to the NEXT open question. Never repeat a validated hypothesis.

You MUST respond in valid JSON with this structure:
{
    "observation": "What I currently see/know",
    "thought": "My reasoning about this",
    "hypothesis": "My current hypothesis (if any) — must be SPECIFIC and FALSIFIABLE",
    "action_type": "research|search_literature|experiment|run_script|write_paper|peer_review_paper|run_scientific_tool|decompose_goal|create_skill|think_more",
    "action_details": {
        "research_query": "...",
        "hypothesis": "...",
        "domain": "medicine|biology|chemistry|physics|mathematics|neuroscience|astronomy|climate",
        "code": "...",
        "language": "python",
        "script": "#!/bin/bash\n...",
        "purpose": "what this script does",
        "paper_topic": "specific research topic for the paper",
        "breakthrough_content": "key finding to center the paper on",
        "tool_name": "name of Atlas tool to execute (e.g. sympy_prime_analysis, numpy_correlation)",
        "tool_input": "properly formatted input for the tool (e.g. 'is_prime:97', 'normal:1000,0,1')",
        "sub_goals": ["..."],
        "skill": {"name": "...", "description": "...", "code": "..."}
    },
    "new_facts": [
        {"subject": "...", "predicate": "...", "object": "...", "confidence": 0.8}
    ],
    "content": "Summary of this thought cycle",
    "surprise_assessment": 0.5,
    "progress_toward_goal": 0.0
}

## YOUR CAPABILITIES:
- **research**: Quick web search (arXiv, Semantic Scholar). Use for initial orientation.
- **search_literature**: 🔬 REAL SCIENCE — Searches real databases (PubMed, arXiv, OpenAlex, Semantic Scholar, Patents)
  using AXIOM Atlas's LiteratureService. Returns actual papers with titles, abstracts, DOIs.
  Use this when you need to VERIFY CLAIMS or find evidence that challenges your hypothesis.
  Set domain to: medicine, biology, chemistry, physics, mathematics, neuroscience.
  Set research_query to the specific claim you want to verify or falsify.
- **experiment**: Write and run Python code with numpy, scipy, matplotlib to:
  - Simulate biological/physical systems with ODEs (scipy.integrate.odeint / solve_ivp)
  - Run statistical analysis on data (scipy.stats)
  - Build mathematical models to test predictions
  - Generate synthetic data to validate a theory
  AVAILABLE LIBRARIES: numpy, scipy, matplotlib. DO NOT use pandas, sympy, or scikit-learn.
  After running, the sandbox returns an experiment_id. Cite it in any paper.
- **run_script**: Write bash scripts for data processing, file organization, analysis pipelines
- **write_paper**: Write a full academic paper when you have NOVEL, VALIDATED findings.
  Do NOT write papers on unverified claims. Only after experiment or search_literature confirms them.
- **peer_review_paper**: 🔬 MOST POWERFUL — Full Atlas scientific validation cycle:
  - Real literature verification + 84+ scientific tools + autonomous peer review (score 1-10)
  - Use ONLY for hypotheses you haven't submitted before (or substantially different ones)
  - Set domain and a SPECIFIC, falsifiable hypothesis
  - **DO NOT use peer_review_paper for a hypothesis you already submitted successfully**
- **run_scientific_tool**: Execute a specific Atlas scientific tool directly:
  - Use when you need precise calculations (sympy_solve_equation, sympy_prime_analysis)
  - Use for data analysis (numpy_correlation, numpy_statistics, hypothesis_tester)
  - Use for domain-specific analysis (dna_analyzer, protein_properties, quantum_circuit)
  - Set tool_name to the exact tool name, tool_input to the properly formatted input string
  - Set domain to the tool's domain (mathematics, chemistry, biology, physics, statistics)
  - Tool input formats: use colons (:) as separators, e.g. "is_prime:97", "normal:1000,0,1"
  - Evidence-grade tools: sympy_solve_equation, sympy_prime_analysis, number_theory_advanced,
    prime_gap_analysis, calculus_engine, symbolic_calculus, graph_theory, sequence_analyzer,
    conjecture_engine, topology_invariants, automated_prover, molecular_weight_calc,
    computational_chemistry, bond_energy_analyzer, molecular_orbital_energy,
    dna_analyzer, protein_properties, dnabert2_analysis, quantum_energy_levels, quantum_circuit,
    numpy_correlation, numpy_distribution, numpy_statistics, hypothesis_tester
  - Weak/triage-only tools: gnome_materials and validate_hypothesis. Do not use these as evidence
    for paper claims; use evidence-grade tools, experiments, or literature verification instead.
- **decompose_goal**: Break mission into sub-goals. Use when stuck or after completing a sub-goal.
- **create_skill**: Save a reusable research strategy
- **think_more**: Deep synthesis — connect disparate ideas

## SCIENTIFIC RIGOR RULES (VIOLATING THESE IS A FAILURE):
1. **FALSIFY FIRST**: Before writing a paper, actively search for evidence AGAINST your hypothesis.
   Use search_literature with queries like "limitations of [therapy]", "failure of [approach]", "[therapy] side effects".
2. **NO REPEATS**: If a hypothesis has already been validated (is in your knowledge), DO NOT submit it again.
   Move to the NEXT open question. Ask: "What does this finding imply that is still unknown?"
3. **CITE ONLY REAL PAPERS**: In write_paper, only cite papers you actually found via search_literature or research.
   If you don't have real citations, state "further evidence needed" instead of fabricating references.
4. **EXPERIMENTS BEFORE PAPERS**: Run at least one experiment (computational model, simulation, statistical test)
   before writing a paper on a quantitative claim.
5. **NEVER INVENT NUMBERS**: Any numerical claim (p-value, HR, OR, survival months, percentage) MUST come from:
   (a) a real experiment you ran in the sandbox (include the experiment_id), OR
   (b) a real dataset you downloaded and analyzed (include the dataset URL/name), OR
   (c) a verified paper you found via search_literature (include the citation).
   If you do not have one of these, you MUST NOT include the number. Write "further evidence needed" instead.
6. **EXPLORE BROADLY**: After validating a finding, pivot to a different angle:
   - Different mechanism or pathway
   - Different patient population or disease subtype
   - Mathematical/computational modeling of the system
   - Comparison of competing approaches
   - Failure modes and edge cases

## ANTI-LOOP RULES:
- If your last 3+ actions were all peer_review_paper on similar topics → use decompose_goal or experiment instead
- If your last 5+ actions were all research → time to synthesize with think_more or experiment
- If you keep submitting the "FUS + CSF-1R + NOTCH/Wnt" hypothesis → it's DONE. Move on.
- The goal is to explore the FRONTIER of what is unknown, not to re-confirm what you know.

## CURIOSITY MANDATE:
After every validated hypothesis, ask yourself: "What is the MOST SURPRISING implication of this finding?"
Then pursue THAT. Science advances through unexpected connections, not incremental repetition.
"""


class ReasoningEngine:
    def __init__(self, config: dict):
        self.config = config
        self.reasoner_model = config["reasoner"]["model"]
        self.fast_model = config["fast"]["model"]
        self.reasoner_ctx = config["reasoner"].get("num_ctx", 32768)
        self.fast_ctx = config["fast"].get("num_ctx", 16384)

        # Initialize Ollama Cloud client
        self.client = OllamaCloudClient(config)

    async def close(self):
        """Release the underlying HTTP client (call on shutdown)."""
        client = getattr(self, "client", None)
        if client is not None and hasattr(client, "close"):
            await client.close()

    async def reason(
        self,
        focus: dict,
        context: dict,
        world_model=None,
        semantic_memory=None,
        skill_library=None,
    ) -> dict:
        """
        Main reasoning step. Takes the current focus and produces
        a structured thought with an action decision.
        """
        messages = self._build_reasoning_prompt(focus, context, world_model)

        try:
            response = await self.client.chat(
                model=self.reasoner_model,
                messages=messages,
                temperature=self.config["reasoner"].get("temperature", 0.7),
                max_tokens=self.config["reasoner"].get("max_tokens", 4096),
                format_json=True,
                num_ctx=self.reasoner_ctx,
                think=False,
            )

            content = _extract_content(response)
            thought = _parse_json_robust(content)

            # Enrich thought with metadata
            thought["source"] = focus.get("source", "unknown")
            thought["focus_content"] = focus.get("content", "")[:200]
            thought["cycle"] = context.get("cycle", 0)

            # Extract the action type
            if "action_type" not in thought:
                thought["action_type"] = "think_more"

            # Copy action details to top level for heartbeat
            details = _action_details(thought)
            thought.update(details)

            log.info(
                "reasoning.thought",
                action=thought["action_type"],
                summary=thought.get("content", "")[:100],
            )
            return thought

        except json.JSONDecodeError as e:
            log.warning("reasoning.json_parse_error", error=str(e), raw=content[:200])
            return {
                "action_type": "think_more",
                "content": f"Response was not valid JSON, retrying next cycle.",
                "new_facts": [],
            }
        except Exception as e:
            log.error("reasoning.error", error=str(e))
            return {
                "action_type": "think_more",
                "content": f"Reasoning error: {e}. Will retry next cycle.",
                "new_facts": [],
            }

    async def generate_experiment_code(
        self,
        hypothesis: str,
        available_skills: list[dict] | None = None,
    ) -> str:
        """Generate Python code to test a hypothesis."""
        skill_context = ""
        if available_skills:
            skill_names = [s.get("name", "") for s in available_skills[:10]]
            skill_context = f"\nAvailable reusable functions: {', '.join(skill_names)}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are A.M.Y's experiment generator. Write clean, self-contained "
                    "Python code to test a hypothesis. The code should:\n"
                    "1. Be completely self-contained (import everything needed)\n"
                    "2. Print clear results\n"
                    "3. Handle errors gracefully\n"
                    "4. Be safe to run in a sandbox\n"
                    "5. Use COMPLETE f-strings — never leave them unterminated\n"
                    "6. For scipy.stats.anderson(), ALWAYS use method='interpolate':\n"
                    "   ad_result = stats.anderson(data, dist='norm', method='interpolate')\n"
                    "   This returns ad_result.pvalue instead of critical_values\n"
                    "7. Avoid very long f-strings that might get truncated — use multiple print() calls instead\n"
                    "Return ONLY the Python code, no markdown."
                    f"{skill_context}"
                ),
            },
            {
                "role": "user",
                "content": f"Write code to test this hypothesis:\n{hypothesis}",
            },
        ]

        try:
            response = await self.client.chat(
                model=self.reasoner_model,
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
                num_ctx=self.reasoner_ctx,
            )
            code = _extract_content(response)
            # Strip markdown code fences if present
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1])
            return code
        except Exception as e:
            log.error("reasoning.code_gen_error", error=str(e))
            return f"# Code generation failed: {e}\nprint('ERROR: Could not generate code')"

    async def generate_subgoals(self, goal: str, context: dict) -> list[str]:
        """Decompose a complex goal into achievable sub-goals."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are A.M.Y's goal decomposition module. Break complex goals into "
                    "specific, actionable sub-goals. Each sub-goal should be achievable "
                    "and verifiable. Return a JSON object with a 'sub_goals' array of strings."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current mission: {context.get('mission', '')}\n"
                    f"Goal to decompose: {goal}\n"
                    f"What we know so far: {context.get('knowledge_summary', 'Nothing yet')}\n\n"
                    "Return 3-7 specific sub-goals as a JSON object: {{\"sub_goals\": [...]}}"
                ),
            },
        ]

        try:
            response = await self.client.chat(
                model=self.fast_model,
                messages=messages,
                temperature=0.5,
                max_tokens=1024,
                format_json=True,
                num_ctx=self.fast_ctx,
            )
            content = _extract_content(response)
            content = _clean_json(content)
            result = json.loads(content)
            return result.get("sub_goals", result.get("goals", []))
        except Exception as e:
            log.error("reasoning.subgoal_error", error=str(e))
            return [f"Investigate: {goal}"]

    def _build_reasoning_prompt(self, focus: dict, context: dict, world_model) -> list[dict]:
        """Build the full prompt for reasoning."""
        # Gather world model state
        wm_state = ""
        if world_model:
            beliefs = [
                f"- {b.content} (confidence: {b.confidence:.2f})"
                for b in list(world_model.beliefs.values())[:10]
            ]
            if beliefs:
                wm_state = "Current beliefs:\n" + "\n".join(beliefs)

            uncertainty = f"Average surprise: {world_model.average_surprise:.2f}"
            wm_state += f"\n{uncertainty}"

        recent_thoughts = context.get("recent_thoughts", [])
        recent_summary = "\n".join(
            f"- [{t.get('action_type', '?')}] {t.get('content', '')[:120]}"
            for t in recent_thoughts[-5:]
        )

        # ── Historial de búsquedas recientes (evitar repetición) ──
        recent_queries = context.get("recent_queries", [])
        queries_block = ""
        if recent_queries:
            q_list = "\n".join(f"  - {q}" for q in recent_queries[-15:])
            queries_block = f"\n## Searches Already Done (DO NOT REPEAT THESE)\n{q_list}\n"

        # ── Hipótesis ya validadas por Atlas (no repetir) ──
        recent_hypotheses = context.get("recent_hypotheses", [])
        hyp_block = ""
        if recent_hypotheses:
            h_list = "\n".join(f"  - {h}" for h in recent_hypotheses[-8:])
            hyp_block = (
                f"\n## Hypotheses Already Validated by Atlas (DO NOT RESUBMIT)\n{h_list}\n"
                "These are CONFIRMED. Move to NEW questions that these findings imply.\n"
            )

        # ── Detección de bucle e instrucción forzada ──
        loop_warning = ""
        consecutive_same = context.get("consecutive_same_action", 0)
        last_action = context.get("last_action_type", "")
        trailing_literature = 0
        for item in reversed(recent_thoughts):
            if item.get("action_type") == "search_literature":
                trailing_literature += 1
            else:
                break
        literature_loop_warning = ""
        if trailing_literature >= 2:
            literature_loop_warning = (
                f"\n## LITERATURE SEARCH LOOP — {trailing_literature} consecutive literature searches\n"
                "You have enough literature context for the current thread. "
                "DO NOT choose 'search_literature' this cycle. Choose one of:\n"
                "- 'experiment' to turn the literature claim into a computational test\n"
                "- 'decompose_goal' to split the topic into new sub-questions\n"
                "- 'think_more' to synthesize and pivot to a clearly different frontier\n"
            )
        if consecutive_same >= 5:
            loop_warning = (
                f"\n## ⚠ LOOP DETECTED — {consecutive_same} consecutive '{last_action}' actions\n"
                "You are stuck in a cognitive loop. You MUST choose a DIFFERENT action:\n"
                "- Use 'search_literature' to verify a claim against real papers\n"
                "- Use 'experiment' to run a computational/mathematical test (numpy, scipy available)\n"
                "- Use 'decompose_goal' to break the mission into new unexplored sub-goals\n"
                "- Use 'think_more' to synthesize findings and identify the NEXT frontier question\n"
                f"DO NOT choose '{last_action}' this cycle.\n"
            )
        elif consecutive_same >= 3:
            loop_warning = (
                f"\n## ⚠ WARNING — {consecutive_same} consecutive '{last_action}' actions\n"
                "Consider using search_literature to verify claims, or experiment to model the system.\n"
            )

        # ── Sub-goals activos ──
        sub_goals = context.get("active_sub_goals", [])
        sub_goals_block = ""
        if sub_goals:
            sg_list = "\n".join(f"  - {sg}" for sg in sub_goals[:5])
            sub_goals_block = f"\n## Active Sub-Goals\n{sg_list}\n"

        # Recurring-weakness guidance synthesized from prior reviews (meta-review
        # feedback loop). Present only once enough signal has accumulated.
        meta_feedback = context.get("meta_review_feedback", "")
        meta_block = f"\n## Lessons From Prior Reviews\n{meta_feedback.strip()}\n" if meta_feedback.strip() else ""

        user_msg = (
            f"## Current Focus\n{focus.get('content', 'No specific focus')}\n"
            f"(Source: {focus.get('source', 'unknown')}, Type: {focus.get('type', 'unknown')})\n\n"
            f"## Current Goal\n{context.get('current_goal', 'Mission active')}\n"
            f"{sub_goals_block}"
            f"## World Model State\n{wm_state or 'No beliefs yet'}\n\n"
            f"## Recent Thoughts (last 5)\n{recent_summary or 'First cycle'}\n"
            f"{queries_block}"
            f"{hyp_block}"
            f"{meta_block}"
            f"{literature_loop_warning}"
            f"{loop_warning}"
            f"## Cycle\n#{context.get('cycle', 0)}\n\n"
            "What is your next cognitive step?"
        )

        return [
            {"role": "system", "content": REASONING_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
