"""Deterministic repair for ungrounded decimal claims in generated papers."""
from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

log = structlog.get_logger()

EXPERIMENTS_DIR = Path("data/experiments")
_EXPERIMENT_ID_RE = re.compile(r"([a-z][a-z0-9_-]+_\d{8}_\d{6}(?:_[a-z0-9]+)?)")
_DECIMAL_RE = re.compile(r"(?<![\w.])[-−]?\d+\.\d+(?:[eE][+-]?\d+)?\s*%?")


def _extract_experiment_ids(md: str) -> list[str]:
    return list(dict.fromkeys(_EXPERIMENT_ID_RE.findall(md)))


def _load_provenance_text(experiment_ids: list[str], experiments_dir: Path) -> str:
    chunks: list[str] = []
    for eid in dict.fromkeys(experiment_ids):
        exp_dir = experiments_dir / eid
        prov_path = exp_dir / "provenance.json"
        if prov_path.exists():
            try:
                record = json.loads(prov_path.read_text(encoding="utf-8"))
            except Exception:
                record = {}
            for key in ("output_preview", "stdout", "stderr"):
                value = record.get(key)
                if value:
                    chunks.append(str(value))
            tool = record.get("tool") if isinstance(record, dict) else None
            if isinstance(tool, dict):
                for key in ("output", "input"):
                    value = tool.get(key)
                    if value:
                        chunks.append(str(value))
        output_path = exp_dir / "output.txt"
        if output_path.exists():
            chunks.append(output_path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _provenance_numbers(provenance_text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"[-−]?\d+\.\d+(?:[eE][+-]?\d+)?", provenance_text):
        try:
            values.append(float(raw.replace("−", "-")))
        except ValueError:
            pass
    return values


def _numeric_part(token: str) -> str:
    return token.strip().rstrip("%").strip().replace("−", "-")


def _is_grounded_decimal(token: str, provenance_text: str, numbers: list[float]) -> bool:
    value_text = _numeric_part(token)
    if value_text in provenance_text:
        return True
    if re.search(re.escape(value_text) + r"\d*", provenance_text):
        return True
    try:
        value = float(value_text)
    except ValueError:
        return False
    tolerance = max(5e-4, abs(value) * 1e-3)
    return any(abs(value - recorded) <= tolerance for recorded in numbers)


def repair_unsupported_decimal_claims(
    md: str,
    *,
    experiment_ids: list[str] | None = None,
    experiments_dir: Path | str | None = None,
    section_names: tuple[str, ...] = ("Abstract", "Discussion"),
) -> tuple[str, dict]:
    """Remove decimal claims from key prose sections when they lack provenance.

    This is intentionally conservative: grounded numbers are left untouched;
    unsupported decimals in Abstract/Discussion are replaced with non-numeric
    wording so downstream reflection/scoring no longer treats them as claims.
    Results/code blocks and Data Availability are not modified.
    """
    exp_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    ids = list(dict.fromkeys(experiment_ids or _extract_experiment_ids(md)))
    provenance_text = _load_provenance_text(ids, exp_dir)
    numbers = _provenance_numbers(provenance_text)
    report = {
        "repairs": 0,
        "items": [],
        "experiment_ids": ids,
        "sections_checked": list(section_names),
    }
    if not ids or not provenance_text:
        return md, report

    section_alt = "|".join(re.escape(name) for name in section_names)
    section_re = re.compile(
        rf"(^##\s*(?P<section>{section_alt})\b[^\n]*\n)(?P<body>.*?)(?=^##\s|\Z)",
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    def repair_section(match: re.Match) -> str:
        header = match.group(1)
        section = match.group("section")
        body = match.group("body")

        def repair_number(num_match: re.Match) -> str:
            token = num_match.group(0)
            if _is_grounded_decimal(token, provenance_text, numbers):
                return token
            replacement = (
                "a provenance-unverified percentage"
                if token.strip().endswith("%")
                else "a provenance-unverified numeric value"
            )
            report["repairs"] += 1
            report["items"].append({"section": section, "number": _numeric_part(token)})
            if num_match.start() > 0 and body[num_match.start() - 1].isalnum():
                replacement = " " + replacement
            if num_match.end() < len(body) and body[num_match.end()].isalpha():
                replacement = replacement + " "
            return replacement

        return header + _DECIMAL_RE.sub(repair_number, body)

    repaired = section_re.sub(repair_section, md)
    if report["repairs"]:
        log.info("grounding_repair.applied", repairs=report["repairs"])
    return repaired, report
