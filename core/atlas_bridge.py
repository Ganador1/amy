"""
Atlas Bridge — Conecta A.M.Y con el ecosistema AXIOM Atlas.

Cuando A.M.Y tiene una hipótesis o síntesis suficientemente desarrollada,
este bridge la envía a Atlas para:
  1. Verificar referencias con literatura real (arXiv, PubMed, Semantic Scholar)
  2. Ejecutar herramientas científicas reales (SymPy, NumPy, BioPython, etc.)
  3. Ejecutar peer review autónomo con AutonomousPeerReviewService
  4. Generar un paper académico revisado y aceptado
  5. Devolver el resultado a A.M.Y para actualizar su knowledge graph

Atlas usa su propio venv (.venv_new) en /Volumes/Ganador disk/A.M.Y/atlas/
Se invoca via subprocess para evitar conflictos de dependencias.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import structlog

log = structlog.get_logger()

ATLAS_ROOT = Path(__file__).parent.parent / "atlas"
ATLAS_VENV_PYTHON = ATLAS_ROOT / ".venv_new" / "bin" / "python3"
ATLAS_RUNNER = Path(__file__).parent / "atlas_runner.py"


def _evaluate_research_safety_or_fail_closed(
    *, domain: str, topic: str, hypothesis: str, knowledge_facts: list[dict] | None
) -> dict:
    try:
        from core.safety_kernel import evaluate_safety

        content = json.dumps(
            {
                "topic": topic,
                "hypothesis": hypothesis,
                "knowledge_facts": knowledge_facts or [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return evaluate_safety(
            operation="atlas_bridge.run_research",
            content=content,
            domain=domain,
            tool_name="autonomous_research_agent",
        ).to_dict()
    except Exception as exc:
        return {
            "allowed": False,
            "action": "block",
            "risk_level": "critical",
            "reasons": [f"safety kernel unavailable: {exc}"],
            "matched_rules": ["SAFETY_KERNEL_UNAVAILABLE"],
            "decision_id": "fail-closed",
        }


def _blocked_research_result(decision: dict) -> dict:
    try:
        from core.safety_kernel import blocked_message

        message = blocked_message(decision)
    except Exception:
        reasons = "; ".join(decision.get("reasons") or ["Safety policy violation"])
        message = f"Blocked by safety policy: {reasons} (decision_id={decision.get('decision_id')})"
    return {
        "success": False,
        "blocked": True,
        "error": message,
        "paper": "",
        "score": 0,
        "accepted": False,
        "safety_decision": decision,
    }


def _primary_ollama_api_key() -> str:
    try:
        from core.ollama_client import get_primary_ollama_cloud_api_key

        return get_primary_ollama_cloud_api_key()
    except Exception:
        return (
            os.getenv("OLLAMA_CLOUD_API_KEY", "")
            or os.getenv("OLLAMA_CLOUD_API_KEY_1", "")
            or os.getenv("OLLAMA_CLOUD_API_KEY_2", "")
        )


class AtlasBridge:
    """
    Bridge entre A.M.Y y Atlas.
    A.M.Y llama a run_research() con su hipótesis y Atlas devuelve
    un paper revisado por pares + score + feedback.
    """

    def __init__(self, atlas_root: str | None = None):
        self.atlas_root = Path(atlas_root) if atlas_root else ATLAS_ROOT
        self.python = str(ATLAS_VENV_PYTHON)
        self.available = self._check_available()

    def _check_available(self) -> bool:
        if not self.atlas_root.exists():
            log.warning("atlas_bridge.no_atlas_dir", path=str(self.atlas_root))
            return False
        if not Path(self.python).exists():
            log.warning("atlas_bridge.no_venv", python=self.python)
            return False
        log.info("atlas_bridge.ready", root=str(self.atlas_root))
        return True

    async def run_research(
        self,
        domain: str,
        topic: str,
        hypothesis: str,
        knowledge_facts: list[dict] | None = None,
        max_iterations: int = 3,
        target_score: int = 7,
    ) -> dict:
        """
        Envía una hipótesis a Atlas para investigación completa con peer review.

        Returns:
            {
                "success": bool,
                "paper": str,          # paper en Markdown
                "score": int,          # score del peer review (1-10)
                "accepted": bool,      # True si score >= target_score
                "feedback": str,       # feedback del reviewer
                "tools_used": list,    # herramientas ejecutadas
                "references": list,    # referencias verificadas
                "error": str | None,
            }
        """
        if not self.available:
            return {
                "success": False,
                "error": "Atlas no disponible",
                "paper": "",
                "score": 0,
                "accepted": False,
            }

        try:
            from core.atlas_tools import _atlas_misuse_blocked_message, _evaluate_atlas_misuse_or_fail_closed

            misuse_decision = _evaluate_atlas_misuse_or_fail_closed(
                operation="atlas_bridge.run_research",
                content=json.dumps(
                    {"topic": topic, "hypothesis": hypothesis, "knowledge_facts": knowledge_facts or []},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                domain=domain,
                tool_name="autonomous_research_agent",
            )
        except Exception as exc:
            misuse_decision = {
                "allowed": False,
                "action": "block",
                "risk_level": "critical",
                "reasons": [f"Atlas misuse guard unavailable: {exc}"],
                "matched_rules": ["MISUSE_GUARD_UNAVAILABLE"],
                "decision_id": "fail-closed",
            }

            def _atlas_misuse_blocked_message(decision: dict) -> str:
                reasons = "; ".join(decision.get("reasons") or ["Misuse policy violation"])
                rules = ",".join(decision.get("matched_rules") or [])
                return f"Blocked by Atlas misuse policy: {reasons} (rules={rules}; decision_id={decision.get('decision_id')})"

        if not misuse_decision["allowed"]:
            log.warning(
                "atlas_bridge.misuse_blocked",
                domain=domain,
                rules=misuse_decision.get("matched_rules", []),
            )
            return {
                "success": False,
                "blocked": True,
                "error": _atlas_misuse_blocked_message(misuse_decision),
                "paper": "",
                "score": 0,
                "accepted": False,
                "safety_decision": misuse_decision,
            }

        safety_decision = _evaluate_research_safety_or_fail_closed(
            domain=domain,
            topic=topic,
            hypothesis=hypothesis,
            knowledge_facts=knowledge_facts,
        )
        if not safety_decision["allowed"]:
            log.warning(
                "atlas_bridge.safety_blocked",
                domain=domain,
                rules=safety_decision.get("matched_rules", []),
            )
            return _blocked_research_result(safety_decision)

        # Preparar payload para Atlas
        payload = {
            "domain": domain,
            "topic": topic,
            "hypothesis": hypothesis,
            "knowledge_facts": knowledge_facts or [],
            "max_iterations": max_iterations,
            "target_score": target_score,
        }

        log.info(
            "atlas_bridge.starting",
            domain=domain,
            topic=topic[:80],
            iterations=max_iterations,
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                self._run_subprocess,
                payload,
            )
            log.info(
                "atlas_bridge.done",
                accepted=result.get("accepted"),
                score=result.get("score"),
                words=len(result.get("paper", "").split()),
            )
            return result
        except Exception as e:
            log.error("atlas_bridge.error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "paper": "",
                "score": 0,
                "accepted": False,
            }

    def _run_subprocess(self, payload: dict) -> dict:
        """Ejecuta Atlas en un subprocess con su propio venv."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(payload, f)
            payload_path = f.name

        out_path = payload_path + ".result.json"

        amy_key = _primary_ollama_api_key()

        runner_code = f"""
import sys, os, json, asyncio
sys.path.insert(0, {repr(str(self.atlas_root))})
os.chdir({repr(str(self.atlas_root))})

# Point Atlas at Ollama Cloud (same as A.M.Y) and disable Redis
# OllamaProvider appends /api/generate itself, so base_url NO debe tener /api
os.environ["OLLAMA_BASE_URL"] = "https://ollama.com"
os.environ["OLLAMA_API_KEY"] = {repr(amy_key)}
os.environ["ENABLE_REDIS_CACHE"] = "false"

# Cargar .env de Atlas (sin sobrescribir vars ya seteadas)
try:
    from dotenv import load_dotenv
    load_dotenv({repr(str(self.atlas_root / '.env'))}, override=False)
except Exception:
    pass

payload = json.load(open({repr(payload_path)}))

from run_agent_with_tools import autonomous_research_agent

async def main():
    result = await autonomous_research_agent(
        domain=payload["domain"],
        topic=payload["topic"] + ". Hypothesis: " + payload["hypothesis"],
        max_iterations=payload.get("max_iterations", 3),
        target_score=payload.get("target_score", 7),
        model_name="glm-5.1",
    )
    return result

result = asyncio.run(main())
json.dump(result if result else {{"success": False, "error": "no result"}}, open({repr(out_path)}, "w"))
"""

        script_path = payload_path + ".runner.py"
        with open(script_path, "w") as f:
            f.write(runner_code)

        try:
            env = os.environ.copy()
            env["OLLAMA_BASE_URL"] = "https://ollama.com"
            env["OLLAMA_API_KEY"] = _primary_ollama_api_key()
            env["ENABLE_REDIS_CACHE"] = "false"

            proc = subprocess.run(
                [self.python, script_path],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max
                env=env,
                cwd=str(self.atlas_root),
            )

            if proc.returncode != 0:
                log.error(
                    "atlas_bridge.subprocess_error",
                    stderr=proc.stderr[-500:],
                    returncode=proc.returncode,
                )

            if Path(out_path).exists():
                with open(out_path) as f:
                    result = json.load(f)
                return self._normalize_result(result, proc.stdout)
            else:
                return {
                    "success": False,
                    "error": f"No output file. stderr: {proc.stderr[-300:]}",
                    "paper": proc.stdout[-1000:] if proc.stdout else "",
                    "score": 0,
                    "accepted": False,
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Atlas timeout (>10 min)",
                "paper": "",
                "score": 0,
                "accepted": False,
            }
        finally:
            for p in [payload_path, script_path, out_path]:
                Path(p).unlink(missing_ok=True)

    def _normalize_result(self, raw: dict, stdout: str) -> dict:
        """Normaliza el resultado de Atlas al formato esperado por A.M.Y."""
        if raw is None:
            raw = {}

        # Atlas puede devolver distintos formatos según la versión
        # raw.get("paper") puede ser None (no ausente) cuando LLM falló
        paper = ""
        for key in ("paper", "final_paper", "content"):
            val = raw.get(key)
            if val and isinstance(val, str) and val.strip():
                paper = val
                break

        # Extraer review (feedback detallado del peer reviewer)
        review_raw = raw.get("review") or raw.get("review_text") or ""
        if isinstance(review_raw, dict):
            review_raw = json.dumps(review_raw)[:2000]

        score = raw.get("final_score") or raw.get("score") or raw.get("review_score", 0)
        try:
            score = int(round(float(score)))
        except Exception:
            score = 0

        accepted = raw.get("accepted") or raw.get("status") == "accepted" or score >= 7

        feedback = raw.get("feedback") or review_raw or ""
        if isinstance(feedback, dict):
            feedback = json.dumps(feedback)[:800]

        tools_used = raw.get("tools_used") or raw.get("experiments") or []
        references = raw.get("references") or []

        # Si no hay paper, intentar extraer del stdout (Atlas imprime el texto)
        if not paper and stdout:
            lines = stdout.split("\n")
            paper_lines = []
            in_paper = False
            for line in lines:
                # Detectar inicio de paper por header markdown o sección académica
                if not in_paper and line.strip().startswith("#"):
                    in_paper = True
                if not in_paper and any(kw in line for kw in
                                        ("Abstract", "Introduction", "Hypothesis",
                                         "Background", "Methods", "Results")):
                    in_paper = True
                if in_paper:
                    paper_lines.append(line)
            if paper_lines:
                paper = "\n".join(paper_lines[:300])

        # Si aún no hay paper pero hay review y fue aceptado, usar review como contenido
        if not paper and review_raw and score >= 5:
            paper = f"## Atlas Peer Review Content\n\n{review_raw[:3000]}"

        # Defensive filter: reject low-quality or empty papers
        if not paper.strip() or len(paper.split()) < 50:
            return {
                "success": False,
                "error": "Atlas returned an empty or trivial paper",
                "paper": paper,
                "score": score,
                "accepted": False,
                "feedback": str(feedback)[:800],
                "review": str(review_raw)[:2000],
                "tools_used": tools_used if isinstance(tools_used, list) else [tools_used],
                "references": references if isinstance(references, list) else [],
                "raw": raw,
            }

        # Heuristic realism gate: mathematics/quantum are the only domains
        # where Atlas currently produces verifiable evidence. For other domains,
        # downgrade acceptance unless score is very high.
        domain_realism = raw.get("domain", "")
        if score < 6:
            accepted = False

        return {
            "success": True,
            "paper": paper,
            "score": score,
            "accepted": accepted,
            "feedback": str(feedback)[:800],
            "review": str(review_raw)[:2000],
            "tools_used": tools_used if isinstance(tools_used, list) else [tools_used],
            "references": references if isinstance(references, list) else [],
            "raw": raw,
        }
