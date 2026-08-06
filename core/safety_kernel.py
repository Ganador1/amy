"""Shared anti-abuse safety kernel for A.M.Y and Atlas.

This module intentionally lives in ``core/`` instead of ``atlas/app/security``.
Atlas imports it independently, so deleting Atlas's security package does not
remove the safety gate from A.M.Y's tool path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import logging
import re
import threading
import uuid

try:  # POSIX process-level lock; A.M.Y currently targets macOS/Linux.
    import fcntl
except ImportError:  # pragma: no cover - defensive fallback for other platforms
    fcntl = None

# Use the stdlib logger (not structlog) so this kernel stays dependency-free
# and importable from Atlas's separate venv. See module docstring.
_log = logging.getLogger("amy.safety_kernel")
_EVENT_LOG_LOCK = threading.Lock()


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    action: str
    risk_level: str
    reasons: list[str]
    matched_rules: list[str] = field(default_factory=list)
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SafetyRule:
    rule_id: str
    reason: str
    patterns: tuple[str, ...]
    risk_level: str = "critical"
    action: str = "block"

    def matches(self, text: str) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in self.patterns)


SAFETY_RULES: tuple[SafetyRule, ...] = (
    SafetyRule(
        rule_id="CHEMICAL_WEAPONIZATION",
        reason="Chemical weapon or explosive operational assistance",
        patterns=(
            r"\bchemical weapon\b",
            r"\bnerve agent\b",
            r"\b(sarin|vx|tabun|soman|mustard gas)\b",
            r"\b(optimi[sz]e|increase|improve).{0,80}\b(yield|potency|purity).{0,80}\b(sarin|vx|nerve agent|toxin)\b",
            r"\b(synthesi[sz]e|manufacture|produce).{0,80}\b(sarin|vx|tabun|soman|ricin|explosive)\b",
            r"\b(tatp|anfo)\b.{0,80}\b(synthesi[sz]e|manufacture|detonate|yield)\b",
        ),
    ),
    SafetyRule(
        rule_id="BIO_WEAPONIZATION",
        reason="Biological weaponization or pathogen enhancement",
        patterns=(
            r"\bbioweapon\b",
            r"\bweaponi[sz]e(d)?\b.{0,80}\b(pathogen|virus|bacteria|anthrax|smallpox)\b",
            r"\bgain[- ]of[- ]function\b.{0,80}\b(pathogen|virus|influenza|coronavirus)\b",
            r"\b(increase|enhance|improve).{0,80}\b(virulence|transmissibility|contagiousness)\b",
            r"\b(aerosoli[sz]e|evade biosafety|bypass biosafety)\b.{0,80}\b(pathogen|virus|anthrax)\b",
        ),
    ),
    SafetyRule(
        rule_id="CYBER_ABUSE",
        reason="Cyber abuse, malware, credential theft, or unauthorized access",
        patterns=(
            r"\b(write|build|create|deploy).{0,80}\b(malware|ransomware|stealer|keylogger)\b",
            r"\b(steal|exfiltrate|dump).{0,80}\b(api keys?|passwords?|tokens?|credentials?)\b",
            r"\b(print|dump|exfiltrate|upload|send|post).{0,120}\b(os\.environ|api[_-]?keys?|passwords?|tokens?|credentials?|secrets?)\b",
            r"\b(bypass|disable).{0,80}\b(auth|authentication|authorization|guardrails?|safety checks?)\b",
            r"\b(phishing kit|credential harvester|botnet)\b",
        ),
    ),
    SafetyRule(
        rule_id="SECRET_EXFILTRATION",
        reason="Attempt to read or expose local secrets",
        patterns=(
            r"\b(os\.environ|os\.getenv)\b.{0,120}\b(api[_-]?keys?|passwords?|tokens?|credentials?|secrets?)\b",
            r"\b(\.env|\.secrets|secrets?[_\-.]|private\.key|id_rsa|ed25519_private)\b.{0,120}\b(read_text|read_bytes|open|cat|print)\b",
            r"\b(read_text|read_bytes|open|cat|print)\b.{0,120}\b(\.env|\.secrets|secrets?[_\-.]|private\.key|id_rsa|ed25519_private)\b",
        ),
    ),
    SafetyRule(
        rule_id="DESTRUCTIVE_LOCAL_EXECUTION",
        reason="Destructive local filesystem or system operation",
        patterns=(
            r"\brm\s+-rf\s+(/|~|\$HOME|\.)",
            r"\bshutil\.rmtree\b.{0,120}\b(/|~|security|core|atlas|\.env|\.secrets)\b",
            r"\b(os\.remove|Path\([^)]*\)\.unlink)\b.{0,120}\b(\.env|\.secrets|security|core|atlas)\b",
            r"\b(chmod\s+777|mkfs|shutdown|reboot)\b",
        ),
    ),
    SafetyRule(
        rule_id="UNAUTHORIZED_HUMAN_EXPERIMENTATION",
        reason="Unauthorized human experimentation or unsafe clinical deployment",
        patterns=(
            r"\bunauthori[sz]ed human experimentation\b",
            r"\b(run|start|perform).{0,80}\b(clinical trial|human trial)\b.{0,80}\b(without|no).{0,40}\b(consent|approval|irb|ethics)\b",
        ),
    ),
    SafetyRule(
        rule_id="GUARDRAIL_TAMPERING",
        reason="Attempt to remove or bypass safety controls",
        patterns=(
            r"\b(delete|remove|disable|bypass).{0,80}\b(safety|guardrails?|security gate|ethics gate)\b",
            r"\bmake.{0,80}\b(safety|guardrails?).{0,80}\bnot run\b",
        ),
    ),
)


def _normalize_text(*parts: object) -> str:
    return "\n".join(str(part or "") for part in parts).lower()


def evaluate_safety(
    *,
    operation: str,
    content: str,
    domain: str = "",
    tool_name: str = "",
) -> SafetyDecision:
    """Evaluate an operation before it reaches Atlas tools or literature APIs."""
    text = _normalize_text(operation, domain, tool_name, content)
    matched_rules: list[str] = []
    reasons: list[str] = []

    for rule in SAFETY_RULES:
        if rule.matches(text):
            matched_rules.append(rule.rule_id)
            reasons.append(rule.reason)

    if matched_rules:
        decision = SafetyDecision(
            allowed=False,
            action="block",
            risk_level="critical",
            reasons=reasons,
            matched_rules=matched_rules,
        )
    else:
        decision = SafetyDecision(
            allowed=True,
            action="allow",
            risk_level="low",
            reasons=[],
            matched_rules=[],
        )

    record_safety_event(decision, operation=operation, domain=domain, tool_name=tool_name, content=content)
    return decision


def blocked_message(decision: SafetyDecision | dict) -> str:
    data = decision if isinstance(decision, dict) else decision.to_dict()
    reasons = "; ".join(data.get("reasons") or ["Safety policy violation"])
    return f"Blocked by safety policy: {reasons} (decision_id={data.get('decision_id')})"


def _last_log_record(fh, *, chunk_size: int = 8192) -> bytes:
    """Return only the final JSONL record, including its trailing newline.

    Safety evaluation is a hot path.  Reading the complete audit file before
    every append made the cost grow linearly with runtime.  This backward scan
    keeps both memory and I/O bounded by the size of one record.
    """
    fh.seek(0, 2)
    end = fh.tell()
    if end == 0:
        return b""

    cursor = end
    fh.seek(end - 1)
    if fh.read(1) == b"\n":
        cursor -= 1

    while cursor > 0:
        read_size = min(chunk_size, cursor)
        cursor -= read_size
        fh.seek(cursor)
        block = fh.read(read_size)
        delimiter = block.rfind(b"\n")
        if delimiter >= 0:
            start = cursor + delimiter + 1
            fh.seek(start)
            return fh.read(end - start)

    fh.seek(0)
    return fh.read(end)


def record_safety_event(
    decision: SafetyDecision,
    *,
    operation: str,
    domain: str,
    tool_name: str,
    content: str,
) -> None:
    """Append a hash-chained safety event without storing full dangerous prompts."""
    try:
        log_path = Path(__file__).resolve().parent.parent / "logs" / "safety_events.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with _EVENT_LOG_LOCK, log_path.open("a+b") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                previous_record = _last_log_record(fh)
                previous_hash = (
                    hashlib.sha256(previous_record).hexdigest()
                    if previous_record
                    else ""
                )
                event = {
                    "decision": decision.to_dict(),
                    "operation": operation,
                    "domain": domain,
                    "tool_name": tool_name,
                    "content_sha256": hashlib.sha256(
                        str(content or "").encode("utf-8")
                    ).hexdigest(),
                    "content_length": len(str(content or "")),
                    "previous_event_hash": previous_hash,
                }
                serialized = json.dumps(
                    event,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                event["event_hash"] = hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest()
                record = (
                    json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                fh.seek(0, 2)
                fh.write(record)
                fh.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        # Safety decisions must never fail open because logging failed.
        # But we do surface the failure so it is not completely silent.
        _log.error("safety_kernel.log_failed: %s", exc)
        return


def fail_closed_decision(reason: str) -> SafetyDecision:
    return SafetyDecision(
        allowed=False,
        action="block",
        risk_level="critical",
        reasons=[reason],
        matched_rules=["SAFETY_KERNEL_UNAVAILABLE"],
    )
