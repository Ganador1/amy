"""
Atlas Worker — Proceso persistente para ejecutar herramientas de Atlas.

Mantiene DynamicToolRegistry en memoria para evitar el overhead
de ~15s de inicialización en cada llamada.

Se comunica con A.M.Y via stdin/stdout con JSON:
  → {"id": 1, "action": "list_tools", "domain": null}
  ← {"id": 1, "result": ["tool1", "tool2", ...]}
  
  → {"id": 2, "action": "run_tool", "tool_name": "...", "tool_input": "..."}
  ← {"id": 2, "result": "output string"}
"""
import io
import json
import logging
import os
import sys
from pathlib import Path

# Redirigir stdout a un buffer durante init para que los logs de startup
# de DynamicToolRegistry no contaminen la comunicación JSON
_real_stdout = sys.stdout
sys.stdout = io.StringIO()

logging.disable(logging.CRITICAL)
os.environ["ENABLE_REDIS_CACHE"] = "false"
os.environ["MPLBACKEND"] = "Agg"

ATLAS_ROOT = Path(__file__).parent.parent / "atlas"
AMY_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AMY_ROOT))
sys.path.insert(0, str(ATLAS_ROOT))
os.chdir(str(ATLAS_ROOT))

from run_agent_with_tools import DynamicToolRegistry
import asyncio


class AtlasWorker:
    """Worker persistente que mantiene DynamicToolRegistry en memoria."""

    def __init__(self):
        # Inicializar con stdout redirigido para evitar contaminación
        self.registry = DynamicToolRegistry()
        # Register extended scientific tools (AstroPy / PySCF / ASE / PyMatGen)
        try:
            from app.extended_science_tools import register_extended_tools
            register_extended_tools(self.registry)
        except Exception:
            # Extended tools are optional — fall back silently if unavailable
            pass
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # Restaurar stdout real para la comunicación
        sys.stdout = _real_stdout

    def list_tools(self, domain: str | None = None) -> list[str]:
        if domain:
            return self.registry.list_tools_for_domain(domain)
        return self.registry.list_tools()

    def describe_tools(self, domain: str | None = None) -> list[dict]:
        """Return name+domain+description+input_format for each tool.

        A.M.Y uses this so it can pick the right tool and format inputs
        correctly. Without it the LLM has to guess.
        """
        tools = self.registry.tools.values()
        if domain:
            tools = [t for t in tools if t.domain == domain]
        return [
            {
                "name": t.name,
                "domain": t.domain,
                "description": t.description,
                "input_format": getattr(t, "input_format", ""),
            }
            for t in tools
        ]

    def run_tool(self, tool_name: str, tool_input: str) -> str:
        try:
            from core.safety_kernel import blocked_message, evaluate_safety

            decision = evaluate_safety(
                operation="atlas_worker.run_tool",
                content=tool_input,
                tool_name=tool_name,
            )
            if not decision.allowed:
                return blocked_message(decision)
        except Exception as exc:
            return f"Blocked by safety policy: safety kernel unavailable: {exc} (decision_id=fail-closed)"

        saved_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            return self.loop.run_until_complete(
                self.registry.execute_tool(tool_name, tool_input)
            )
        finally:
            sys.stdout = saved_stdout

    def handle_request(self, request: dict) -> dict:
        req_id = request.get("id", 0)
        action = request.get("action", "")

        try:
            if action == "list_tools":
                result = self.list_tools(request.get("domain"))
                return {"id": req_id, "result": result}
            elif action == "describe_tools":
                result = self.describe_tools(request.get("domain"))
                return {"id": req_id, "result": result}
            elif action == "run_tool":
                # Validate and preserve the exact tool name before execution.
                from core.security_hardening_v2 import require_valid_tool_name
                tool_name = require_valid_tool_name(request["tool_name"])
                tool_input = request["tool_input"]
                if not isinstance(tool_input, str):
                    raise ValueError("invalid tool_input")
                result = self.run_tool(
                    tool_name,
                    tool_input,
                )
                return {"id": req_id, "result": result}
            elif action == "ping":
                return {"id": req_id, "result": "pong"}
            else:
                return {"id": req_id, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"id": req_id, "error": str(e), "result": None}

    def run(self):
        """Lee requests de stdin, escribe responses a stdout."""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
            except json.JSONDecodeError as e:
                response = {"id": 0, "error": f"Invalid JSON: {e}"}
            _real_stdout.write(json.dumps(response, default=str) + "\n")
            _real_stdout.flush()


if __name__ == "__main__":
    worker = AtlasWorker()
    worker.run()
