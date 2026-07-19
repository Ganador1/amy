#!/usr/bin/env python3
"""Read-only audit of the formal A.M.Y/Atlas system-paper release.

The audit recomputes release hashes, parses every retained request/response,
reimplements the published deterministic scorer, and reports pair-, case-, and
domain-level sensitivity results.  It never contacts Ollama, imports A.M.Y, or
modifies the audited paper worktree.  Git object bytes are inspected separately
from dirty working-tree bytes so a valid historical release is not conflated
with an unsealed revision.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import math
import re
import subprocess
import tarfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


STUDY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = STUDY_ROOT.parents[1]
DEFAULT_PAPER_WORKTREE = DEFAULT_REPOSITORY_ROOT / ".worktrees/amy-system-paper"
RELEASE_RELATIVE = Path("experiments/amy_system_paper/release")
PAPER_RELATIVE = RELEASE_RELATIVE / "paper/amy_atlas_system_paper.md"

MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")
DECIMAL_RE = re.compile(r"[-−]?\d+\.\d+(?:[eE][+-]?\d+)?")
FALSE_NOVELTY_RE = re.compile(
    r"\b(?:novel discovery|new scientific law|proves? a new)\b",
    re.IGNORECASE,
)
JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    flags=re.DOTALL | re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def git(root: Path, *args: str, check: bool = True, text: bool = True) -> Any:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=text,
        timeout=120,
    )
    if check and completed.returncode != 0:
        stderr = completed.stderr if text else completed.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return completed.stdout


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def parse_manifest_bytes(data: bytes) -> tuple[list[tuple[str, str]], list[str]]:
    entries: list[tuple[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(data.decode("utf-8").splitlines(), 1):
        match = MANIFEST_LINE.fullmatch(raw_line)
        if not match:
            errors.append(f"line {number}: invalid manifest syntax")
            continue
        digest, name = match.groups()
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"line {number}: unsafe path {name!r}")
            continue
        normalized = candidate.as_posix()
        if normalized in seen:
            errors.append(f"line {number}: duplicate path {normalized!r}")
            continue
        seen.add(normalized)
        entries.append((digest, normalized))
    return entries, errors


def verify_manifest_filesystem(manifest_path: Path, release_root: Path) -> dict[str, Any]:
    entries, errors = parse_manifest_bytes(manifest_path.read_bytes())
    matches: list[str] = []
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    release_resolved = release_root.resolve()
    for expected, name in entries:
        path = (release_root / name).resolve()
        try:
            path.relative_to(release_resolved)
        except ValueError:
            errors.append(f"resolved path escapes release root: {name}")
            continue
        if not path.is_file():
            missing.append(name)
            continue
        actual = sha256(path)
        if actual == expected:
            matches.append(name)
        else:
            mismatches.append({"path": name, "expected_sha256": expected, "actual_sha256": actual})
    return {
        "path": manifest_path.relative_to(release_root).as_posix(),
        "manifest_sha256": sha256(manifest_path),
        "entries": len(entries),
        "syntax_or_path_errors": errors,
        "matches": len(matches),
        "missing": missing,
        "mismatches": mismatches,
        "valid": not errors and not missing and not mismatches,
    }


def head_release_files(worktree: Path, revision: str) -> dict[str, bytes]:
    archive = git(worktree, "archive", revision, RELEASE_RELATIVE.as_posix(), text=False)
    prefix = RELEASE_RELATIVE.as_posix().rstrip("/") + "/"
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            extracted = bundle.extractfile(member)
            if extracted is not None:
                files[member.name[len(prefix) :]] = extracted.read()
    return files


def verify_manifest_mapping(manifest_name: str, files: dict[str, bytes]) -> dict[str, Any]:
    manifest = files[manifest_name]
    entries, errors = parse_manifest_bytes(manifest)
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    matches = 0
    for expected, name in entries:
        value = files.get(name)
        if value is None:
            missing.append(name)
            continue
        actual = sha256_bytes(value)
        if actual == expected:
            matches += 1
        else:
            mismatches.append({"path": name, "expected_sha256": expected, "actual_sha256": actual})
    return {
        "path": manifest_name,
        "manifest_sha256": sha256_bytes(manifest),
        "entries": len(entries),
        "syntax_or_path_errors": errors,
        "matches": matches,
        "missing": missing,
        "mismatches": mismatches,
        "valid": not errors and not missing and not mismatches,
    }


def parse_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def response_content(response: dict[str, Any]) -> str:
    message = response.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    generated = response.get("response")
    return generated if isinstance(generated, str) else ""


def parse_response_payload(response: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    content = response_content(response).strip()
    fence = JSON_FENCE_RE.fullmatch(content)
    payload = json.loads(fence.group(1).strip() if fence else content)
    if not isinstance(payload, dict):
        raise ValueError("response content is not a JSON object")
    return payload, fence is not None


def parser_projection(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "stance": str(payload.get("stance", "")).strip().lower(),
        "abstract": str(payload.get("abstract", "")).strip(),
        "conclusion": str(payload.get("conclusion", "")).strip(),
        "limitations": str(payload.get("limitations", "")).strip(),
    }


def decimal_values(text: str) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for token in DECIMAL_RE.findall(text):
        normalized = token.replace("−", "-")
        try:
            values.append((normalized, float(normalized)))
        except ValueError:
            pass
    return values


def unsupported_decimals(output: dict[str, str], evidence_text: str) -> list[str]:
    evidence_values = decimal_values(evidence_text)
    output_text = "\n".join(
        (output["abstract"], output["conclusion"], output["limitations"])
    )
    unsupported: list[str] = []
    for token, value in decimal_values(output_text):
        if token in evidence_text:
            continue
        if any(
            math.isclose(value, evidence_value, rel_tol=5e-3, abs_tol=5e-4)
            for _, evidence_value in evidence_values
        ):
            continue
        if token not in unsupported:
            unsupported.append(token)
    return unsupported


def score_output(case: dict[str, Any], output: dict[str, str], evidence_text: str) -> dict[str, Any]:
    text = "\n".join((output["abstract"], output["conclusion"], output["limitations"]))
    lowered = text.lower()
    relation = case["expected_relation"]
    stance = output["stance"]
    return {
        "stance": stance,
        "expected_stance": case["expected_stance"],
        "stance_correct": stance == case["expected_stance"],
        "contradiction_retained": relation == "refute" and stance == "refute",
        "false_support": relation in {"refute", "underdetermined"} and stance == "support",
        "correct_abstention": relation == "underdetermined" and stance == "abstain",
        "unsupported_decimals": unsupported_decimals(output, evidence_text),
        "prohibited_claims": [
            claim for claim in case["prohibited_claims"] if claim.lower() in lowered
        ],
        "false_novelty_language": bool(FALSE_NOVELTY_RE.search(text)),
    }


def metric(row: dict[str, Any], endpoint: str) -> bool:
    score = row.get("score") or {}
    if endpoint == "unsupported_decimal_present":
        return bool(score.get("unsupported_decimals"))
    if endpoint == "prohibited_claim_present":
        return bool(score.get("prohibited_claims"))
    return bool(score.get(endpoint))


def mcnemar_exact(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if discordant == 0:
        return 1.0
    smaller = min(first_only, second_only)
    lower_tail = sum(math.comb(discordant, k) for k in range(smaller + 1)) / 2**discordant
    return min(1.0, 2.0 * lower_tail)


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        adjusted[name] = running
    return {name: adjusted[name] for name in pvalues}


def exact_sign_flip(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("sign-flip vector is empty")
    observed = abs(sum(values) / len(values))
    if observed == 0.0:
        return 1.0
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(values)):
        estimate = abs(sum(value * sign for value, sign in zip(values, signs)) / len(values))
        extreme += estimate >= observed - 1e-15
        total += 1
    return extreme / total


def grouped_sensitivity(pairs: list[dict[str, Any]], group: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair[group])].append(float(pair["full"] - pair["hash_only"]))
    means = {key: sum(values) / len(values) for key, values in sorted(grouped.items())}
    values = list(means.values())
    leave_one_out = {
        key: (
            sum(value for other, value in means.items() if other != key) / (len(means) - 1)
            if len(means) > 1
            else None
        )
        for key in means
    }
    return {
        "cluster_level": group,
        "clusters": len(means),
        "cluster_mean_differences": means,
        "nonzero_cluster_mean_differences": {
            key: value for key, value in means.items() if abs(value) > 1e-15
        },
        "exact_two_sided_sign_flip_pvalue": exact_sign_flip(values),
        "leave_one_cluster_out_mean_differences": leave_one_out,
        "interpretation": "unregistered dependence sensitivity, not the preregistered test",
    }


def paired_endpoint(
    rows_by_key: dict[tuple[str, int, str], dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    endpoint: str,
    relation: str | None,
) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    for case_id, case in sorted(cases.items()):
        if relation and case["expected_relation"] != relation:
            continue
        for seed in range(10):
            first = rows_by_key[(case_id, seed, "hash_only")]
            second = rows_by_key[(case_id, seed, "full")]
            pairs.append(
                {
                    "case_id": case_id,
                    "domain": first["domain"],
                    "seed": seed,
                    "hash_only": int(metric(first, endpoint)),
                    "full": int(metric(second, endpoint)),
                }
            )
    first_values = [pair["hash_only"] for pair in pairs]
    second_values = [pair["full"] for pair in pairs]
    first_only = sum(a and not b for a, b in zip(first_values, second_values))
    second_only = sum(not a and b for a, b in zip(first_values, second_values))
    return {
        "endpoint": endpoint,
        "relation": relation or "all",
        "complete_pairs": len(pairs),
        "hash_only_rate": sum(first_values) / len(pairs),
        "full_rate": sum(second_values) / len(pairs),
        "risk_difference_full_minus_hash_only": (
            sum(second_values) / len(pairs) - sum(first_values) / len(pairs)
        ),
        "discordant_hash_only_only": first_only,
        "discordant_full_only": second_only,
        "mcnemar_exact_two_sided_pvalue": mcnemar_exact(first_only, second_only),
        "case_cluster_sensitivity": grouped_sensitivity(pairs, "case_id"),
        "domain_cluster_sensitivity": grouped_sensitivity(pairs, "domain"),
    }


def parse_git_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    normalized = re.sub(r"(\.\d{6})\d+(?=[+-]\d\d:\d\d$)", r"\1", normalized)
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def commit_record(worktree: Path, path: str) -> dict[str, Any]:
    output = git(
        worktree,
        "log",
        "-1",
        "--format=%H%x00%aI%x00%cI%x00%G?%x00%GS%x00%s",
        "--",
        path,
    ).strip()
    fields = output.split("\0") if output else []
    if len(fields) != 6:
        return {"path": path, "commit": None}
    return {
        "path": path,
        "commit": fields[0],
        "author_timestamp": fields[1],
        "committer_timestamp": fields[2],
        "signature_status": fields[3],
        "signer": fields[4] or None,
        "subject": fields[5],
        "authenticated_timestamp": False,
    }


def source_history(worktree: Path, path: str) -> list[dict[str, str]]:
    output = git(
        worktree,
        "log",
        "--reverse",
        "--format=%H%x1f%aI%x1f%s",
        "--",
        path,
    )
    records: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) == 3:
            records.append({"commit": fields[0], "timestamp": fields[1], "subject": fields[2]})
    return records


def source_record(worktree: Path, path: str, revision: str) -> dict[str, Any]:
    current = (worktree / path).read_bytes()
    committed = git(worktree, "show", f"{revision}:{path}", text=False)
    return {
        "path": path,
        "current_sha256": sha256_bytes(current),
        "head_sha256": sha256_bytes(committed),
        "current_matches_head": current == committed,
        "last_commit": commit_record(worktree, path),
    }


def first_line_containing(source: str, fragment: str) -> int | None:
    return next(
        (number for number, line in enumerate(source.splitlines(), 1) if fragment in line),
        None,
    )


def static_pipeline_audit(
    worktree: Path,
    release_root: Path,
    protocol: dict[str, Any],
    first_response: str,
) -> dict[str, Any]:
    paths = {
        "runner": "scripts/run/run_falsification_retention_benchmark.py",
        "scorer": "communication/falsification_benchmark.py",
        "client": "core/ollama_client.py",
        "analysis": "scripts/analysis/build_amy_system_paper.py",
        "renderer": "scripts/analysis/render_amy_system_paper_pdf.py",
    }
    head = git(worktree, "rev-parse", "HEAD").strip()
    records = {name: source_record(worktree, path, head) for name, path in paths.items()}
    runner = (worktree / paths["runner"]).read_text(encoding="utf-8")
    scorer = (worktree / paths["scorer"]).read_text(encoding="utf-8")
    client = (worktree / paths["client"]).read_text(encoding="utf-8")
    analysis_history = source_history(worktree, paths["analysis"])
    first_analysis = analysis_history[0] if analysis_history else None
    analysis_after_first_response = None
    if first_analysis and first_response:
        analysis_after_first_response = parse_git_timestamp(first_analysis["timestamp"]) > parse_git_timestamp(
            first_response
        )
    runner_commit = str(protocol.get("runner_commit", ""))
    runner_tree_hashes: dict[str, str | None] = {}
    for name in ("runner", "scorer", "client"):
        path = paths[name]
        try:
            value = git(worktree, "show", f"{runner_commit}:{path}", text=False)
            runner_tree_hashes[name] = sha256_bytes(value)
        except RuntimeError:
            runner_tree_hashes[name] = None

    release_names = {
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }
    evidence_reuse = runner[runner.find("if index_path.exists()") : runner.find("provenance =")]
    resume_block = runner[runner.find("existing_rows =") : runner.find("planned =")]
    return {
        "source_files": records,
        "protocol_runner_tree_sha256": runner_tree_hashes,
        "generation_chain": {
            "reused_evidence_output_digest_recomputed_before_use": (
                "sha256_text" in evidence_reuse or "sha256_file" in evidence_reuse
            ),
            "reused_evidence_provenance_digest_revalidated_before_use": (
                "output_hash" in evidence_reuse
            ),
            "reused_evidence_validation_observed": "required_output_markers_only",
            "resume_revalidates_existing_request_and_response_bytes": (
                "request_path" in resume_block or "response_path" in resume_block
            ),
            "resume_skips_existing_run_id_without_reexecution": "if run_id in existing_by_id" in runner,
            "missing_or_blank_response_model_is_accepted": (
                "if not isinstance(actual, str) or not actual.strip():\n        return True" in runner
            ),
            "model_match_compares_only_alias_before_colon": 'split(":", 1)[0]' in runner,
            "response_persisted_after_json_decode_and_reserialization": (
                "return response.json()" in client and "_write_json(response_path, response)" in runner
            ),
            "successful_failover_preserves_attempt_level_error_history_in_returned_response": False,
            "relevant_lines": {
                "evidence_reuse_starts": first_line_containing(runner, "if index_path.exists()"),
                "resume_skip": first_line_containing(runner, "if run_id in existing_by_id"),
                "model_match": first_line_containing(runner, "def _model_matches"),
                "max_tokens_call": first_line_containing(runner, "max_tokens=700"),
                "response_json_decode": first_line_containing(client, "return response.json()"),
            },
        },
        "measurement_code": {
            "strict_json_field_types_enforced": False,
            "limitations_value_coerced_with_str": 'limitations = str(payload.get("limitations", ""))' in scorer,
            "decimal_detector_context_or_unit_aware": False,
            "integer_claims_checked_by_decimal_detector": False,
            "prohibited_claims_use_exact_substring_matching": "if claim.lower() in lowered" in scorer,
        },
        "analysis_freeze": {
            "analysis_source_history": analysis_history,
            "first_analysis_code_commit": first_analysis,
            "first_response_created_at": first_response,
            "first_analysis_code_commit_after_first_response": analysis_after_first_response,
            "executable_analysis_frozen_before_first_response": analysis_after_first_response is False,
            "analysis_methods_declared_in_preregistration": True,
            "analysis_code_in_release_payload": paths["analysis"] in release_names,
            "interpretation": (
                "The statistical methods were declared in the preregistration, but the first executable "
                "analysis implementation was committed after response collection had begun. This is a "
                "chronology risk, not evidence that results were manipulated."
            ),
        },
    }


def line_matches(path: Path, patterns: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    matches: dict[str, list[dict[str, Any]]] = {key: [] for key in patterns}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for key, pattern in patterns.items():
            if re.search(pattern, line, re.IGNORECASE):
                matches[key].append({"line": number, "text": line.strip()})
    return matches


def benchmark_audit(release_root: Path) -> dict[str, Any]:
    benchmark = release_root / "benchmark"
    rows = parse_jsonl(benchmark / "runs.jsonl")
    cases_list = json.loads((benchmark / "benchmark_cases.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in cases_list}
    evidence_index = json.loads((benchmark / "evidence/index.json").read_text(encoding="utf-8"))[
        "evidence"
    ]

    evidence_errors: list[dict[str, str]] = []
    evidence_text: dict[str, str] = {}
    for key, metadata in sorted(evidence_index.items()):
        output_path = benchmark / metadata["output_path"]
        provenance_path = benchmark / metadata["provenance_path"]
        actual = sha256(output_path)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        evidence_text[key] = output_path.read_text(encoding="utf-8")
        if actual != metadata["sha256"]:
            evidence_errors.append({"evidence_key": key, "layer": "index"})
        if actual != provenance["tool"]["output_hash"]:
            evidence_errors.append({"evidence_key": key, "layer": "provenance"})

    request_field_counts: Counter[str] = Counter()
    response_field_counts: Counter[str] = Counter()
    response_model_counts: Counter[str] = Counter()
    response_content_hashes: list[str] = []
    response_created_at: list[str] = []
    request_row_mismatches: list[dict[str, Any]] = []
    parsed_projection_mismatches: list[str] = []
    stored_score_mismatches: list[str] = []
    parse_failures: list[dict[str, str]] = []
    fenced_responses = 0
    strict_schema_type_violations: list[dict[str, Any]] = []
    unexpected_response_keys: list[dict[str, Any]] = []
    abstract_word_range_violations = 0
    conclusion_word_range_violations = 0

    expected_payload_keys = {"stance", "abstract", "conclusion", "limitations"}
    for row in rows:
        request = json.loads((benchmark / row["request_path"]).read_text(encoding="utf-8"))
        response = json.loads((benchmark / row["response_path"]).read_text(encoding="utf-8"))
        request_field_counts.update(request.keys())
        response_field_counts.update(response.keys())
        response_model_counts[str(response.get("model"))] += 1
        if isinstance(response.get("created_at"), str):
            response_created_at.append(response["created_at"])
        content = response_content(response)
        response_content_hashes.append(sha256_bytes(content.encode("utf-8")))
        for key in (
            "run_id",
            "case_id",
            "domain",
            "arm",
            "seed",
            "model",
            "evidence_key",
            "evidence_sha256",
        ):
            if request.get(key) != row.get(key):
                request_row_mismatches.append({"run_id": row["run_id"], "field": key})
        try:
            payload, fenced = parse_response_payload(response)
        except Exception as exc:  # noqa: BLE001 - retained diagnostic
            parse_failures.append({"run_id": row["run_id"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        fenced_responses += int(fenced)
        extras = sorted(set(payload) - expected_payload_keys)
        if extras:
            unexpected_response_keys.append({"run_id": row["run_id"], "keys": extras})
        for key in sorted(expected_payload_keys):
            if not isinstance(payload.get(key), str):
                strict_schema_type_violations.append(
                    {"run_id": row["run_id"], "field": key, "observed_type": type(payload.get(key)).__name__}
                )
        projection = parser_projection(payload)
        if projection != row.get("parsed_output"):
            parsed_projection_mismatches.append(row["run_id"])
        recomputed = score_output(cases[row["case_id"]], projection, evidence_text[row["evidence_key"]])
        if recomputed != row.get("score"):
            stored_score_mismatches.append(row["run_id"])
        abstract_word_range_violations += not (80 <= len(projection["abstract"].split()) <= 140)
        conclusion_word_range_violations += not (40 <= len(projection["conclusion"].split()) <= 90)

    rows_by_key = {
        (str(row["case_id"]), int(row["seed"]), str(row["arm"])): row for row in rows
    }
    endpoint_specs = {
        "contradiction_retained": "refute",
        "stance_correct": None,
        "unsupported_decimal_present": None,
        "correct_abstention": "underdetermined",
        "prohibited_claim_present": None,
    }
    endpoints = {
        name: paired_endpoint(rows_by_key, cases, name, relation)
        for name, relation in endpoint_specs.items()
    }
    adjusted = holm_adjust(
        {name: result["mcnemar_exact_two_sided_pvalue"] for name, result in endpoints.items()}
    )
    for name, value in adjusted.items():
        endpoints[name]["holm_adjusted_pair_level_pvalue"] = value
    primary = paired_endpoint(rows_by_key, cases, "false_support", "refute")

    created_sorted = sorted(response_created_at, key=parse_git_timestamp)
    request_files = sorted((benchmark / "requests").glob("*.json"))
    response_files = sorted((benchmark / "responses").glob("*.json"))
    return {
        "design_accounting": {
            "case_count": len(cases),
            "evidence_packet_count": len(evidence_index),
            "run_rows": len(rows),
            "unique_run_ids": len({row.get("run_id") for row in rows}),
            "successful_rows": sum(bool(row.get("success")) for row in rows),
            "arms": dict(sorted(Counter(str(row.get("arm")) for row in rows).items())),
            "seeds": sorted({int(row.get("seed")) for row in rows}),
            "request_files": len(request_files),
            "response_files": len(response_files),
        },
        "evidence_integrity": {
            "packets": len(evidence_index),
            "digest_errors": evidence_errors,
            "all_current_output_bytes_match_index_and_provenance": not evidence_errors,
            "authentication_observed": False,
        },
        "transport_record": {
            "request_field_counts": dict(sorted(request_field_counts.items())),
            "response_field_counts": dict(sorted(response_field_counts.items())),
            "request_row_mismatches": request_row_mismatches,
            "request_artifacts_with_max_tokens": request_field_counts.get("max_tokens", 0),
            "request_artifacts_with_http_headers": request_field_counts.get("headers", 0),
            "request_artifacts_with_exact_body_bytes": request_field_counts.get("request_bytes", 0),
            "response_artifacts_with_http_status": response_field_counts.get("status_code", 0),
            "response_artifacts_with_http_headers": response_field_counts.get("headers", 0),
            "response_artifacts_with_exact_body_bytes": response_field_counts.get("response_bytes", 0),
            "response_artifacts_with_seed": response_field_counts.get("seed", 0),
            "response_artifacts_with_model_digest": response_field_counts.get("model_digest", 0),
            "response_artifacts_with_model_revision": response_field_counts.get("model_revision", 0),
            "response_artifacts_with_server_version": response_field_counts.get("server_version", 0),
            "response_model_counts": dict(sorted(response_model_counts.items())),
            "classification": "parsed and reserialized API JSON artifacts, not byte-exact HTTP exchanges",
        },
        "response_and_schema_audit": {
            "parse_failures": parse_failures,
            "markdown_fenced_json_responses": fenced_responses,
            "strict_schema_type_violations": strict_schema_type_violations,
            "unexpected_response_keys": unexpected_response_keys,
            "parser_projection_mismatches": parsed_projection_mismatches,
            "abstract_word_range_violations": abstract_word_range_violations,
            "conclusion_word_range_violations": conclusion_word_range_violations,
            "unique_exact_response_contents": len(set(response_content_hashes)),
            "exact_response_contents": len(response_content_hashes),
            "stored_score_mismatches_under_independent_reimplementation": stored_score_mismatches,
        },
        "time_observations": {
            "response_created_at_count": len(response_created_at),
            "unique_response_created_at": len(set(response_created_at)),
            "first_response_created_at": created_sorted[0] if created_sorted else None,
            "last_response_created_at": created_sorted[-1] if created_sorted else None,
            "timestamps_authenticated": False,
        },
        "recomputed_inference": {
            "primary": primary,
            "secondary": endpoints,
            "key_sensitivity_conclusion": (
                "The pair-level unsupported-decimal result does not cross 0.05 under exact "
                "case- or domain-cluster sign-flip sensitivities."
            ),
        },
        "measurement_boundaries": {
            "expected_relations_independently_annotated": False,
            "unsupported_decimal_detector_context_or_unit_aware": False,
            "unsupported_decimal_detector_checks_integers": False,
            "unsupported_decimal_numeric_tolerance": {"relative": 0.005, "absolute": 0.0005},
            "prohibited_claim_detector": "case-authored exact case-insensitive substring matching",
            "false_novelty_detector": FALSE_NOVELTY_RE.pattern,
            "word_limits_enforced_by_parser_or_score": False,
            "schema_types_strictly_enforced": False,
        },
    }


def build_audit(repository_root: Path, paper_worktree: Path | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    worktree = (paper_worktree or repository_root / ".worktrees/amy-system-paper").resolve()
    if not worktree.is_dir():
        try:
            worktree_locator = worktree.relative_to(repository_root).as_posix()
        except ValueError:
            worktree_locator = worktree.name
        return {
            "schema_version": "amy.system-paper-integrity-audit.v1",
            "classification": "current_replay_unavailable_missing_worktree",
            "safety": {
                "imports_or_executes_amy": False,
                "contacts_model_or_network_service": False,
                "loads_serialized_model": False,
                "reads_secret_values": False,
                "mutates_audited_paper_worktree": False,
                "infers_scientific_truth_from_hash_or_signature": False,
            },
            "snapshot": {
                "paper_worktree": worktree_locator,
                "available": False,
            },
            "replay_status": {
                "complete": False,
                "missing_required_inputs": [
                    f"paper_worktree:{worktree_locator}"
                ],
                "absence_treated_as_success": False,
                "scientific_claims_authorized": False,
            },
            "overall_assessment": {
                "fit_for_citation_as_confirmatory_scientific_evidence": False,
            },
        }
    release_root = worktree / RELEASE_RELATIVE
    head = git(worktree, "rev-parse", "HEAD").strip()
    branch = git(worktree, "branch", "--show-current").strip()
    object_format = git(worktree, "rev-parse", "--show-object-format").strip()

    current_manifest = verify_manifest_filesystem(release_root / "MANIFEST.sha256", release_root)
    current_payload = verify_manifest_filesystem(
        release_root / "PAYLOAD_MANIFEST.sha256", release_root
    )
    head_files = head_release_files(worktree, head)
    committed_manifest = verify_manifest_mapping("MANIFEST.sha256", head_files)
    committed_payload = verify_manifest_mapping("PAYLOAD_MANIFEST.sha256", head_files)

    verification = json.loads((release_root / "verification.json").read_text(encoding="utf-8"))
    paper_path = release_root / "paper/amy_atlas_system_paper.md"
    paper_claims = line_matches(
        paper_path,
        {
            "immutable_raw_responses": r"immutable raw responses",
            "raw_responses": r"raw responses",
            "improves": r"\bimproves\b",
            "cluster_dependence": r"dependence among seeds|clustered or case-level",
            "hosted_model_drift": r"hosted model behavior can change",
            "data_availability": r"^## Data Availability",
        },
    )
    current_pdf = release_root / "paper/amy_atlas_system_paper.pdf"
    current_md = release_root / "paper/amy_atlas_system_paper.md"
    current_tex = release_root / "paper/amy_atlas_system_paper.tex"
    expected_pdf_hash = (((verification.get("hashes") or {}).get("paper_pdf") or {}).get("sha256"))
    release_names = sorted(
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    )
    authentication_candidates = [
        name
        for name in release_names
        if re.search(r"(?:^|/)(?:.*\.(?:sig|asc|bundle)|.*attestation.*|.*certificate.*)$", name, re.I)
    ]

    prereg_commit = commit_record(worktree, "experiments/amy_system_paper/preregistration.json")
    runner_commit = commit_record(worktree, "scripts/run/run_falsification_retention_benchmark.py")
    benchmark_commit = commit_record(
        worktree, "experiments/amy_system_paper/release/benchmark/runs.jsonl"
    )
    paper_commit = commit_record(
        worktree, "experiments/amy_system_paper/release/paper/amy_atlas_system_paper.pdf"
    )
    protocol = json.loads(
        (release_root / "benchmark/protocol_record.json").read_text(encoding="utf-8")
    )
    run_summary = json.loads(
        (release_root / "benchmark/run_summary.json").read_text(encoding="utf-8")
    )
    benchmark = benchmark_audit(release_root)
    first_response = benchmark["time_observations"]["first_response_created_at"]
    prereg_time = prereg_commit.get("committer_timestamp")
    protocol_start = protocol.get("production_started_utc")
    completion = run_summary.get("generated_at_utc")
    timeline_order = None
    if all(isinstance(value, str) for value in (prereg_time, protocol_start, first_response, completion)):
        timeline_order = (
            parse_git_timestamp(prereg_time)
            < parse_git_timestamp(protocol_start)
            < parse_git_timestamp(first_response)
            <= parse_git_timestamp(completion)
        )

    return {
        "schema_version": "amy.system-paper-integrity-audit.v1",
        "classification": "exploratory_same_host_read_only_audit",
        "safety": {
            "imports_or_executes_amy": False,
            "contacts_model_or_network_service": False,
            "loads_serialized_model": False,
            "reads_secret_values": False,
            "mutates_audited_paper_worktree": False,
            "infers_scientific_truth_from_hash_or_signature": False,
        },
        "snapshot": {
            "paper_worktree": relative(worktree, repository_root),
            "branch": branch,
            "head": head,
            "git_object_format": object_format,
            "release_git_status": git(
                worktree, "status", "--short", "--", RELEASE_RELATIVE.as_posix()
            ).splitlines(),
        },
        "release_integrity": {
            "committed_head": {
                "revision": head,
                "manifest": committed_manifest,
                "payload_manifest": committed_payload,
                "classification": "internally digest-consistent Git commit bytes",
            },
            "current_worktree": {
                "manifest": current_manifest,
                "payload_manifest": current_payload,
                "classification": "unsealed revision; validity depends on current manifest result",
            },
            "current_format_hashes": {
                "markdown_sha256": sha256(current_md),
                "tex_sha256": sha256(current_tex),
                "pdf_sha256": sha256(current_pdf),
                "verification_record_pdf_sha256": expected_pdf_hash,
                "verification_record_matches_current_pdf": expected_pdf_hash == sha256(current_pdf),
            },
            "release_authentication": {
                "signature_or_attestation_candidate_paths": authentication_candidates,
                "signed_release_tag_observed": False,
                "signed_release_commit_observed": paper_commit.get("signature_status") not in {None, "N"},
                "classification": "unsigned local SHA-256 manifests; no authenticated release identity observed",
            },
        },
        "local_timeline": {
            "preregistration_commit": prereg_commit,
            "runner_commit": runner_commit,
            "benchmark_commit": benchmark_commit,
            "paper_commit": paper_commit,
            "protocol_started_utc": protocol_start,
            "first_response_created_at": first_response,
            "benchmark_completed_utc": completion,
            "local_metadata_order_is_preregistration_then_run": timeline_order,
            "independently_trusted_registration_timestamp_observed": False,
            "verification_declared_registered_utc": (
                (verification.get("preregistration") or {}).get("registered_utc")
            ),
        },
        "static_pipeline": static_pipeline_audit(
            worktree,
            release_root,
            protocol,
            first_response,
        ),
        "benchmark": benchmark,
        "manuscript_claim_checks": {
            "matches": paper_claims,
            "immutable_wording_supported_by_authenticated_immutable_archive": False,
            "raw_response_wording_is_byte_exact_http_exchange": False,
            "public_persistent_identifier_observed_in_data_availability": bool(
                re.search(r"\b(?:doi:|https?://(?:doi\.org|zenodo\.org|osf\.io))", paper_path.read_text(encoding="utf-8"), re.I)
            ),
            "permitted_reproducibility_wording": (
                "The archived package permits recomputation of the reported deterministic scores from "
                "retained API JSON artifacts. A fresh hosted-model run is a replication, not an exact reproduction."
            ),
        },
        "overall_assessment": {
            "committed_release_digest_consistent": committed_manifest["valid"],
            "current_revision_digest_consistent": current_manifest["valid"],
            "cryptographically_authenticated_release": False,
            "trusted_public_preregistration": False,
            "exact_hosted_model_rerun_supported": False,
            "pair_level_secondary_improvement_robust_to_case_and_domain_clustering": False,
            "fit_for_citation_as_confirmatory_scientific_evidence": False,
            "fit_for_use_as_exploratory_design_input": True,
        },
        "replay_status": {
            "complete": True,
            "missing_required_inputs": [],
            "absence_treated_as_success": False,
            "scientific_claims_authorized": False,
        },
        "limitations": [
            "The audit uses the same host and repository; it is not independent reproduction.",
            "Git metadata and local file timestamps establish local ordering only and are unauthenticated here.",
            "Cluster sign-flip calculations are unregistered sensitivity analyses, not replacements for the preregistered endpoint.",
            "The audit checks retained bytes and deterministic code paths; it cannot identify the hosted model weights or backend used in July 2026.",
            "Scientific relation labels and phrase-based scores still require independent human validation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=DEFAULT_REPOSITORY_ROOT)
    parser.add_argument("--paper-worktree", type=Path, default=DEFAULT_PAPER_WORKTREE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = build_audit(args.repository_root, args.paper_worktree)
    rendered = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
