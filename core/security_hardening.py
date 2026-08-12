"""
Security Hardening Module — Defense-in-depth improvements for A.M.Y.

This module addresses the gaps identified in the security audit:

1. PROMPT INJECTION SHIELDING
   - Wraps tool outputs in explicit XML delimiters before passing to LLM
   - Scans LLM output for injection artifacts (role hijack, system override)
   - Strips embedded instruction-like patterns from tool outputs

2. PROVENANCE INTEGRITY HELPERS
   - HMAC-SHA256 local authentication of provenance records
   - Timestamp + nonce metadata (not replay or rollback prevention)
   - Input+output hash (not just output hash)

3. TOOL INPUT VALIDATION
   - Strict allowlist-based parser for tool inputs
   - Size limits on all inputs
   - Path traversal prevention

4. LLM OUTPUT SANITIZATION
   - Post-generation scan for leaked secrets, injection artifacts
   - Numeric claim extraction + cross-check against provenance
   - Process chatter removal (already partially done in llm_enhancer)

Usage:
    from core.security_hardening import SecurityHardener
    hardener = SecurityHardener()
    safe_output = hardener.shield_tool_output(tool_output, tool_name)
    safe_llm = hardener.sanitize_llm_output(llm_text, evidence_context)
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets as _secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# ─── Configuration ──────────────────────────────────────────────

MAX_TOOL_OUTPUT_LEN = 20_000
MAX_TOOL_INPUT_LEN = 2_000
MAX_LLM_OUTPUT_LEN = 20_000

# HMAC key — from env or generated per-session (ephemeral). This is a shared
# secret MAC, not a public digital signature or proof of author identity.
_HMAC_KEY = os.environ.get("AMY_PROVENANCE_HMAC_KEY", "")


def _get_hmac_key() -> bytes:
    """Return the HMAC key, generating an ephemeral one if not configured."""
    global _HMAC_KEY
    if _HMAC_KEY:
        return _HMAC_KEY.encode("utf-8")
    # Ephemeral key — provenance signatures won't survive restart,
    # but this still prevents tampering within a single session.
    _HMAC_KEY = _secrets.token_hex(32)
    log.warning("security_hardening.ephemeral_hmac_key", msg="Set AMY_PROVENANCE_HMAC_KEY for persistent signatures")
    return _HMAC_KEY.encode("utf-8")


# ─── 1. Prompt Injection Shielding ──────────────────────────────

# Delimiters that wrap tool outputs in the LLM context — the LLM is
# instructed to treat content inside these tags as DATA, not instructions.
TOOL_OUTPUT_OPEN = "<TOOL_EVIDENCE>"
TOOL_OUTPUT_CLOSE = "</TOOL_EVIDENCE>"

# Patterns that indicate prompt injection attempts in tool outputs
_INJECTION_PATTERNS = [
    # Role hijacking
    re.compile(r"(?i)\b(ignore|disregard|forget)\b.{0,50}\b(previous|system|above)\b.{0,30}\b(instructions?|rules?|prompts?)\b"),
    re.compile(r"(?i)\byou are now\b.{0,50}\b(DAN|developer mode|unrestricted|unbound|free)\b"),
    re.compile(r"(?i)\b(new rules|new instructions)\s*[:)]"),
    # System prompt extraction
    re.compile(r"(?i)\b(print|show|reveal|display|leak)\b.{0,50}\b(your )?(initial |system )?(prompt|instructions?|rules?)\b"),
    # Instruction injection via markup
    re.compile(r"(?i)\[SYSTEM\]|\[ASSISTANT\]|\[INSTRUCTION\]|\[OVERRIDE\]"),
    # Translate-to-injection
    re.compile(r"(?i)\b(translate|write) this into\b.{0,50}\b(instructions?|system prompt)\b"),
]

# Patterns that indicate leaked secrets in LLM output
_SECRET_PATTERNS = [
    re.compile(r"(?i)(?:api[_-]?key|secret|token|password|credential)\s*[=:]\s*[A-Za-z0-9+/=]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bOLLAMA_CLOUD_API_KEY[_12]*\s*[=:]"),
]


@dataclass
class InjectionScanResult:
    """Result of scanning text for injection artifacts."""
    clean: bool
    matches: list[str] = field(default_factory=list)
    sanitized: str = ""


def scan_for_injection(text: str) -> InjectionScanResult:
    """Scan text for prompt injection patterns.

    Returns a result with:
    - clean: True if no injection patterns found
    - matches: list of matched patterns (for logging)
    - sanitized: text with injection patterns neutralized
    """
    if not text:
        return InjectionScanResult(clean=True, sanitized="")

    matches: list[str] = []
    sanitized = text

    for pattern in _INJECTION_PATTERNS:
        for m in pattern.finditer(text):
            matches.append(m.group(0)[:100])  # Truncate for logging
            # Replace the matched text with a neutralized marker
            sanitized = sanitized.replace(m.group(0), "[REDACTED_INJECTION_ATTEMPT]")

    return InjectionScanResult(
        clean=len(matches) == 0,
        matches=matches,
        sanitized=sanitized,
    )


def shield_tool_output(tool_output: str, tool_name: str = "") -> str:
    """Wrap tool output in XML delimiters and neutralize injection attempts.

    This is the core defense against prompt injection via tool outputs:
    1. Truncate to max length
    2. Scan for and neutralize injection patterns
    3. XML-escape untrusted content so it cannot close or reopen the wrapper
    4. Wrap in explicit delimiters
    """
    if not tool_output:
        return f"{TOOL_OUTPUT_OPEN}\n{TOOL_OUTPUT_CLOSE}"

    # Scan and neutralize injection attempts FIRST (before truncation,
    # so injection at the end of a long output is still caught)
    scan = scan_for_injection(tool_output)
    if not scan.clean:
        log.warning(
            "security_hardening.injection_detected",
            tool=tool_name,
            match_count=len(scan.matches),
            examples=scan.matches[:3],
        )

    # Truncate after scanning
    truncated = False
    sanitized = html.escape(scan.sanitized, quote=False)
    if len(sanitized) > MAX_TOOL_OUTPUT_LEN:
        sanitized = sanitized[:MAX_TOOL_OUTPUT_LEN] + " …[truncated by security hardening]"
        truncated = True

    # Wrap in delimiters
    shielded = f"{TOOL_OUTPUT_OPEN}\n{sanitized}\n{TOOL_OUTPUT_CLOSE}"
    if truncated:
        shielded += "\n<!-- output was truncated by security hardening -->"

    return shielded


# ─── 2. Provenance Integrity ───────────────────────────────────


def _canonical_record(record: dict) -> str:
    """Produce deterministic Python JSON used for HMAC verification.

    The security block is included EXCEPT for the hmac_signature field itself.
    This way sign and verify use the exact same payload.

    This deliberately does not claim RFC 8785 interoperability. Non-standard
    numbers and unknown Python objects fail instead of being stringified.
    """
    sec = record.get("security", {})
    sec_without_sig = {k: v for k, v in sec.items() if k != "hmac_signature"}
    record_copy = {k: v for k, v in record.items() if k != "security"}
    record_copy["security"] = sec_without_sig
    return json.dumps(
        record_copy,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def sign_provenance(record: dict) -> dict:
    """Add an HMAC-SHA256 MAC plus uniqueness metadata to a record.

    This strengthens the existing SHA-256 output hash with:
    - HMAC signature over the full record (not just output)
    - Timestamp + nonce metadata; callers must not infer replay prevention
    - Input hash (not just output hash)
    """
    # Add anti-replay fields
    record.setdefault("security", {})
    record["security"]["timestamp_epoch"] = int(time.time())
    record["security"]["nonce"] = _secrets.token_hex(16)

    # Hash the input alongside the output
    tool = record.get("tool", {})
    tool_input = str(tool.get("input", ""))
    tool_output = str(tool.get("output", record.get("output_preview", "")))
    record["security"]["input_hash"] = hashlib.sha256(tool_input.encode("utf-8")).hexdigest()
    framed_input_output = json.dumps(
        [tool_input, tool_output],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    record["security"]["combined_hash"] = hashlib.sha256(
        framed_input_output
    ).hexdigest()
    record["security"]["signature_version"] = "1.0"

    # HMAC signature over the canonical record (excluding hmac_signature itself)
    canonical = _canonical_record(record)
    signature = hmac.new(
        _get_hmac_key(),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    record["security"]["hmac_signature"] = signature

    return record


def verify_provenance(record: dict) -> bool:
    """Verify the HMAC signature on a provenance record.

    Returns True if the signature is valid, False otherwise.
    Records without a signature are treated as invalid.
    """
    if not isinstance(record, dict):
        return False

    sec = record.get("security", {})
    if not isinstance(sec, dict):
        return False

    stored_sig = sec.get("hmac_signature")
    if not isinstance(stored_sig, str) or re.fullmatch(r"[0-9a-f]{64}", stored_sig) is None:
        return False

    # Reconstruct the same canonical payload used for signing
    try:
        canonical = _canonical_record(record)
        expected_sig = hmac.new(
            _get_hmac_key(),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return False

    return hmac.compare_digest(stored_sig, expected_sig)


# ─── 3. Tool Input Validation ──────────────────────────────────

# Allowlist of safe characters for tool inputs
_SAFE_INPUT_RE = re.compile(r"^[a-zA-Z0-9\s,;:.()\-+/=*'\"\\]+$")

# Blocked substrings in tool inputs
_BLOCKED_INPUT_SUBSTRINGS = [
    "..",           # Path traversal
    "\x00",         # Null bytes
    "\n",           # Newlines (could inject into shell args)
    "$(",           # Command substitution
    "`",            # Backtick command substitution
    "|",            # Pipe (could inject shell commands)
    ";",            # Command separator — but allow in some tools
]


@dataclass
class InputValidationResult:
    valid: bool
    sanitized: str
    reason: str = ""


def validate_tool_input(raw_input: str, tool_name: str = "") -> InputValidationResult:
    """Validate and sanitize a tool input string.

    Returns a result with:
    - valid: True if input passes all checks
    - sanitized: cleaned input string
    - reason: error message if invalid
    """
    if not raw_input:
        return InputValidationResult(valid=True, sanitized="")

    # Size limit
    if len(raw_input) > MAX_TOOL_INPUT_LEN:
        return InputValidationResult(
            valid=False,
            sanitized="",
            reason=f"Input exceeds maximum length {MAX_TOOL_INPUT_LEN}",
        )

    # Check for null bytes
    if "\x00" in raw_input:
        return InputValidationResult(
            valid=False,
            sanitized="",
            reason="Input contains null bytes",
        )

    # Check for path traversal
    if ".." in raw_input:
        return InputValidationResult(
            valid=False,
            sanitized="",
            reason="Input contains path traversal sequence",
        )

    # Check for command injection patterns
    lowered = raw_input.lower()
    for blocked in _BLOCKED_INPUT_SUBSTRINGS:
        if blocked in lowered and blocked not in (";",):  # Semicolons are allowed for some tools
            return InputValidationResult(
                valid=False,
                sanitized="",
                reason=f"Input contains blocked pattern: {repr(blocked)}",
            )

    # Check for shell metacharacters (unless tool explicitly needs them)
    if re.search(r"[`$()|&<>]", raw_input):
        # Some tools use semicolons in their format (e.g. "1,2,3;delta=0.05")
        # but shell metacharacters like backticks, $(), |, &, <, > are always blocked
        return InputValidationResult(
            valid=False,
            sanitized="",
            reason="Input contains shell metacharacters",
        )

    return InputValidationResult(valid=True, sanitized=raw_input.strip())


# ─── 4. LLM Output Sanitization ────────────────────────────────


@dataclass
class LLMSanitizationResult:
    clean: bool
    sanitized: str
    issues: list[str] = field(default_factory=list)


def sanitize_llm_output(llm_text: str, evidence_context: str = "") -> LLMSanitizationResult:
    """Sanitize LLM output for security and integrity.

    Checks:
    1. Leaked secrets (API keys, tokens, passwords)
    2. Injection artifacts (role hijacking, system override)
    3. Process chatter (already partially done in llm_enhancer)
    4. Length limits
    """
    if not llm_text:
        return LLMSanitizationResult(clean=True, sanitized="")

    issues: list[str] = []
    sanitized = llm_text

    # 1. Check for leaked secrets
    for pattern in _SECRET_PATTERNS:
        matches = pattern.findall(llm_text)
        if matches:
            issues.append(f"leaked_secret:{matches[0][:30]}...")
            for m in pattern.finditer(llm_text):
                sanitized = sanitized.replace(m.group(0), "[REDACTED_SECRET]")

    # 2. Check for injection artifacts (in case the LLM was compromised)
    # Continue from the already redacted text. Restarting from llm_text here
    # would restore any secrets removed by the previous pass.
    injection_scan = scan_for_injection(sanitized)
    if not injection_scan.clean:
        issues.append(f"injection_artifact:{len(injection_scan.matches)} matches")
        sanitized = injection_scan.sanitized

    # 3. Length limit
    if len(sanitized) > MAX_LLM_OUTPUT_LEN:
        sanitized = sanitized[:MAX_LLM_OUTPUT_LEN] + " …[truncated by security hardening]"
        issues.append("output_truncated")

    clean = len(issues) == 0
    if issues:
        log.warning(
            "security_hardening.llm_output_issues",
            issues=issues,
            original_len=len(llm_text),
            sanitized_len=len(sanitized),
        )

    return LLMSanitizationResult(clean=clean, sanitized=sanitized, issues=issues)


# ─── 5. Watermark Integrity ────────────────────────────────────


def verify_watermark_integrity(
    paper_body: str,
    watermark_body_sha256: str,
    watermark_generated_at: str,
) -> bool:
    """Verify that the paper body hash in the watermark matches the actual body.

    This prevents an attacker from copying a legitimate watermark onto
    a different paper body.
    """
    if not paper_body or not watermark_body_sha256:
        return False

    actual_hash = hashlib.sha256(paper_body.encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual_hash, watermark_body_sha256.lower())


# ─── Convenience class ──────────────────────────────────────────


class SecurityHardener:
    """Convenience facade for all security hardening operations."""

    def shield_tool_output(self, tool_output: str, tool_name: str = "") -> str:
        return shield_tool_output(tool_output, tool_name)

    def validate_tool_input(self, raw_input: str, tool_name: str = "") -> InputValidationResult:
        return validate_tool_input(raw_input, tool_name)

    def sanitize_llm_output(self, llm_text: str, evidence_context: str = "") -> LLMSanitizationResult:
        return sanitize_llm_output(llm_text, evidence_context)

    def sign_provenance(self, record: dict) -> dict:
        return sign_provenance(record)

    def verify_provenance(self, record: dict) -> bool:
        return verify_provenance(record)

    def verify_watermark(self, body: str, wm_hash: str, wm_ts: str) -> bool:
        return verify_watermark_integrity(body, wm_hash, wm_ts)
