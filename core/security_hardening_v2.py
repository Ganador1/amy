"""
Security Hardening v2 — Additional fixes from deep code audit.

Addresses vulnerabilities found in the second-pass review:

1. SUBPROCESS ENVIRONMENT LEAK
   - atlas_tools.py and atlas_bridge.py pass os.environ.copy() to subprocesses
   - This leaks ALL env vars (API keys, tokens) to child processes
   - Fix: minimal env with only needed vars

2. API KEY INJECTION IN GENERATED CODE
   - atlas_bridge.py embeds API key in generated Python code via repr()
   - If key contains special chars, code injection is possible
   - Fix: pass key via env var, not string interpolation

3. WATERMARK TAMPERING
   - body_sha256 is computed but never verified after generation
   - An attacker can modify the paper body without detection
   - Fix: verify_watermark function (already in security_hardening.py)

4. TOOL NAME VALIDATION
   - atlas_worker.py accepts any tool_name without validation
   - Fix: allowlist of known tool names

5. PROVENANCE DIRECTORY TRAVERSAL
   - experiment_id is used to construct file paths without validation
   - Fix: validate experiment_id format

6. LLM PROMPT INJECTION VIA FEEDBACK
   - meta_review_agent feedback is appended to LLM prompts
   - If feedback contains injection, it bypasses the tool-output shielding
   - Fix: scan feedback before injection
"""
from __future__ import annotations

import hmac
import os
import re
import structlog
from pathlib import Path
from typing import Any

log = structlog.get_logger()

# ─── 1. Subprocess Environment Sanitization ────────────────────

# Keys that are SAFE to pass to subprocesses (no secrets)
_SAFE_SUBPROCESS_ENV_KEYS = frozenset({
    "PATH",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "HOME",
    "TMPDIR",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    "MPLBACKEND",
    "PYTHONNOUSERSITE",
    "ENABLE_REDIS_CACHE",
    "OLLAMA_BASE_URL",
    "ORCHESTRATOR_GLOBAL_TIMEOUT",
    "AXIOM_DISABLE_NET",
    # OLLAMA_API_KEY is intentionally NOT here — it's set explicitly
    # per-call, not inherited from the parent environment.
})

# Patterns that indicate secret-like env vars
_SECRET_ENV_PATTERNS = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|credential|private[_-]?key|"
    r"access[_-]?key|auth[_-]?token|session[_-]?secret|jwt[_-]?secret)",
)


def sanitize_subprocess_env(
    *,
    extra: dict[str, str] | None = None,
    include_ollama_key: str = "",
) -> dict[str, str]:
    """Build a minimal, secret-free environment for subprocess execution.

    This replaces the dangerous pattern of ``os.environ.copy()`` which
    leaks ALL environment variables (including API keys, tokens, and
    other secrets) to child processes.

    Args:
        extra: Additional non-secret vars to include.
        include_ollama_key: The Ollama API key to pass (if needed).
            Passed explicitly so it's visible in the call site, not
            hidden in a copied environment.

    Returns:
        A clean environment dict with only safe variables.
    """
    clean: dict[str, str] = {}

    # Copy only safe keys from the current environment
    for key in _SAFE_SUBPROCESS_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            clean[key] = value

    # Add explicitly provided extra vars (caller is responsible for
    # ensuring these don't contain secrets)
    if extra:
        for key, value in extra.items():
            if _SECRET_ENV_PATTERNS.search(key):
                log.warning(
                    "subprocess_env.secret_key_in_extra",
                    key=key,
                    msg="Refusing to pass secret-like env var via extra; use include_ollama_key instead",
                )
                continue
            clean[key] = value

    # Add the Ollama key explicitly if provided
    if include_ollama_key:
        clean["OLLAMA_API_KEY"] = include_ollama_key

    return clean


# ─── 2. Safe Code Generation for Subprocess ───────────────────

def safe_subprocess_code(template: str, **kwargs: str) -> str:
    """Safely generate Python code for subprocess execution.

    This replaces the dangerous pattern of embedding secrets directly
    in generated code via repr() or f-strings. Instead, secrets are
    passed via environment variables, and the generated code reads them
    from os.environ.

    Args:
        template: Code template with {placeholder} markers.
        **kwargs: Values for placeholders. Values are escaped to
            prevent code injection — only alphanumeric, dots, slashes,
            and hyphens are allowed (no quotes, semicolons, parens, etc.).

    Returns:
        Safe Python code string.
    """
    # Strict allowlist: only alphanumeric + safe path chars
    # No quotes, semicolons, parens, brackets, or other code-breaking chars
    _SAFE_CODE_CHAR_RE = re.compile(r"[^a-zA-Z0-9./_\-]")

    safe_kwargs: dict[str, str] = {}
    for key, value in kwargs.items():
        # Strip all characters that could break out of a string context
        escaped = _SAFE_CODE_CHAR_RE.sub("", str(value))
        safe_kwargs[key] = escaped

    return template.format(**safe_kwargs)


# ─── 3. Experiment ID Validation ──────────────────────────────

# Filesystem-safe experiment identifiers. Historical A.M.Y callers also use
# stable names such as ``exp_fixed`` and append ``_2`` on collision, so the
# security boundary is one safe path component rather than one timestamp
# presentation format.
_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")

# Blocked substrings in experiment IDs
_BLOCKED_ID_SUBSTRINGS = ("..", "/", "\\", "\x00", " ", "\n", "\r", "\t")


def validate_experiment_id(experiment_id: str) -> bool:
    """Validate that an experiment ID is safe for filesystem use.

    This prevents path traversal via experiment_id in provenance paths
    like ``data/experiments/{experiment_id}/provenance.json``.

    Args:
        experiment_id: The experiment ID to validate.

    Returns:
        True if the ID is safe, False otherwise.
    """
    if not experiment_id or len(experiment_id) > 200:
        return False

    # Check for blocked substrings
    for blocked in _BLOCKED_ID_SUBSTRINGS:
        if blocked in experiment_id:
            return False

    # Check format
    if not _EXPERIMENT_ID_RE.match(experiment_id):
        return False

    return True


def require_valid_experiment_id(experiment_id: str) -> str:
    """Return *experiment_id* unchanged or fail closed."""
    if not isinstance(experiment_id, str) or not validate_experiment_id(experiment_id):
        raise ValueError("invalid experiment_id")
    return experiment_id


def safe_experiment_path(experiments_dir: Path, experiment_id: str) -> Path | None:
    """Build a safe path for an experiment directory.

    Returns None if the experiment_id is invalid.
    The returned path is guaranteed to be within experiments_dir.
    """
    if not validate_experiment_id(experiment_id):
        return None

    candidate = experiments_dir / experiment_id
    # Verify the resolved path is still within experiments_dir
    try:
        candidate.resolve().relative_to(experiments_dir.resolve())
    except ValueError:
        return None

    return candidate


# ─── 4. Tool Name Validation ───────────────────────────────────

# Pattern for valid tool names (alphanumeric + underscore, max 64 chars)
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Blocked tool names (meta/system tools that shouldn't be called externally)
_BLOCKED_TOOL_NAMES = frozenset({
    "__import__",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "type",
    "super",
    "object",
    "property",
    "staticmethod",
    "classmethod",
})


def validate_tool_name(tool_name: str) -> bool:
    """Validate that a tool name is safe to execute.

    Args:
        tool_name: The tool name to validate.

    Returns:
        True if the name is safe, False otherwise.
    """
    if not tool_name or len(tool_name) > 64:
        return False

    if not _TOOL_NAME_RE.match(tool_name):
        return False

    if tool_name in _BLOCKED_TOOL_NAMES:
        return False

    return True


def require_valid_tool_name(tool_name: str) -> str:
    """Return *tool_name* unchanged or fail closed."""
    if not isinstance(tool_name, str) or not validate_tool_name(tool_name):
        raise ValueError("invalid tool_name")
    return tool_name


# ─── 5. Feedback Sanitization ──────────────────────────────────

# Reuse injection patterns from security_hardening.py
try:
    from core.security_hardening import scan_for_injection, InjectionScanResult
except ImportError:
    # Fallback if security_hardening is not available
    _INJECTION_PATTERNS = [
        re.compile(r"(?i)\b(ignore|disregard|forget)\b.{0,50}\b(previous|system|above)\b.{0,30}\b(instructions?|rules?|prompts?)\b"),
        re.compile(r"(?i)\byou are now\b.{0,50}\b(DAN|developer mode|unrestricted|unbound|free)\b"),
        re.compile(r"(?i)\b(new rules|new instructions)\s*[:)]"),
        re.compile(r"(?i)\[SYSTEM\]|\[ASSISTANT\]|\[INSTRUCTION\]|\[OVERRIDE\]"),
    ]

    def scan_for_injection(text: str) -> Any:
        if not text:
            class _R:
                clean = True
                matches: list[str] = []
                sanitized = ""
            return _R()
        matches = []
        sanitized = text
        for pattern in _INJECTION_PATTERNS:
            for m in pattern.finditer(text):
                matches.append(m.group(0)[:100])
                sanitized = sanitized.replace(m.group(0), "[REDACTED_INJECTION_ATTEMPT]")
        class _R:
            clean = len(matches) == 0
            matches_list = matches
            sanitized = sanitized
        _R.matches = matches
        return _R()


def sanitize_feedback_text(feedback: str) -> str:
    """Sanitize meta-review feedback before appending to LLM prompts.

    The meta-review feedback is derived from accumulated reviews and
    appended to the next cycle's LLM prompts. If a review contained
    injection text (e.g., from a compromised tool output), the feedback
    could carry that injection into the LLM context, bypassing the
    tool-output shielding.

    This function scans and neutralizes injection patterns in feedback
    text before it reaches the LLM.

    Args:
        feedback: The feedback text to sanitize.

    Returns:
        Sanitized feedback text with injection patterns neutralized.
    """
    if not feedback or not feedback.strip():
        return feedback

    result = scan_for_injection(feedback)
    if not result.clean:
        log.warning(
            "security_hardening_v2.feedback_injection_detected",
            match_count=len(result.matches),
            examples=result.matches[:3],
        )
        return result.sanitized

    return feedback


# ─── 6. Watermark Verification Helper ─────────────────────────

def extract_watermark_hash(paper_md: str) -> str | None:
    """Extract the body_sha256 from a paper's AMY-WATERMARK.

    Args:
        paper_md: The full paper markdown including the watermark.

    Returns:
        The body_sha256 hex string, or None if not found.
    """
    marker = "\n\n---\n\n## Provenance Watermark"
    comment_marker = "<!-- AMY-WATERMARK\n"
    if paper_md.count(marker) != 1 or paper_md.count(comment_marker) != 1:
        return None
    if not paper_md.endswith("-->\n"):
        return None

    marker_index = paper_md.index(marker)
    comment_index = paper_md.index(comment_marker, marker_index)
    comment = paper_md[comment_index + len(comment_marker):-4]
    matches = re.findall(
        r"(?m)^body_sha256:\s*([a-fA-F0-9]{64})\s*$",
        comment,
    )
    return matches[0].lower() if len(matches) == 1 else None


def verify_paper_watermark(paper_md: str) -> bool:
    """Verify that a paper's watermark hash matches its body content.

    This detects tampering: if someone modifies the paper body after
    generation, the hash in the watermark will no longer match.

    Args:
        paper_md: The full paper markdown including the watermark.

    Returns:
        True if the watermark is valid, False otherwise.
    """
    import hashlib

    # Extract the declared hash from the watermark
    declared_hash = extract_watermark_hash(paper_md)
    if not declared_hash:
        return False

    # Extract the body (everything before the single terminal watermark
    # section). This is an unkeyed consistency digest, not an author signature.
    watermark_marker = "\n\n---\n\n## Provenance Watermark"
    body_end = paper_md.find(watermark_marker)
    if body_end == -1:
        return False

    body = paper_md[:body_end]
    actual_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    return hmac.compare_digest(actual_hash, declared_hash)
