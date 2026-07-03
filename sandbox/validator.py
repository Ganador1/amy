"""
Sandbox validation helpers.

The sandbox's policy gate (static pattern checks + Python syntax validation)
is implemented as methods on :class:`sandbox.executor.SandboxExecutor`
(``_static_sandbox_policy_violation`` and ``_validate_python_syntax``), because
they depend on per-instance policy flags (allow_network, allow_subprocess,
allow_sensitive_env).

This module exposes a thin, instance-free wrapper so callers that only need a
quick "is this code obviously unsafe?" check can use it without building an
executor. It is the single import point for sandbox validation.
"""
from __future__ import annotations


def validate_python_syntax(code: str) -> str | None:
    """Return an error string if *code* is not valid Python, else ``None``."""
    try:
        compile(code, "<sandbox_validate>", "exec")
        return None
    except SyntaxError as exc:
        text = exc.text.strip() if exc.text else ""
        return f"Line {exc.lineno}: {exc.msg} — {text}"
    except Exception as exc:  # pragma: no cover - defensive
        return str(exc)


def static_policy_violation(
    code: str,
    language: str = "python",
    *,
    allow_network: bool = False,
    allow_subprocess: bool = False,
    allow_sensitive_env: bool = False,
) -> str | None:
    """Return a reason string if *code* violates the default sandbox policy.

    Delegates to :class:`sandbox.executor.SandboxExecutor` so the policy lives
    in exactly one place. Returns ``None`` when the code passes the static gate.
    """
    from sandbox.executor import SandboxExecutor

    checker = SandboxExecutor(
        {
            "allow_network": allow_network,
            "allow_subprocess": allow_subprocess,
            "allow_sensitive_env": allow_sensitive_env,
        }
    )
    return checker._static_sandbox_policy_violation(code, language)
