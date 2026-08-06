#!/usr/bin/env python3
"""
Double-Blind Peer Review Evaluator for A.M.Y Papers

Uses two independent LLM agents (GLM-5.1 and Kimi-K2.6) as simulated
peer reviewers in a double-blind protocol:

1. Papers are anonymized (author/affiliation stripped, random IDs assigned)
2. Assignment is randomized: each reviewer sees a random subset
3. Neither reviewer knows the other reviewer's identity or scores
4. Neither reviewer knows which papers are pre-gate vs post-gate
5. Reviewers evaluate on standardized rubrics
6. Inter-rater agreement (Cohen's κ) is computed post-hoc

This emulates a real double-blind peer review process as closely as possible
with LLM agents instead of human reviewers.

Usage:
    python double_blind_evaluator.py [--papers-dir papers] [--output-dir data/double_blind_eval]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# ─── Configuration ───────────────────────────────────────────────────────────

PAPERS_DIR = Path("papers")
OUTPUT_DIR = Path("data/double_blind_eval")
PROVENANCE_DIR = Path("data/experiments")

# Two independent reviewer models. Defaults preserve the historical protocol;
# env overrides allow controlled model-comparison runs without code edits.
REVIEWER_A_MODEL = os.environ.get("DBLIND_REVIEWER_A_MODEL", "glm-5.1")
REVIEWER_B_MODEL = os.environ.get("DBLIND_REVIEWER_B_MODEL", "kimi-k2.6")

# Review rubric dimensions (7-point Likert scale)
RUBRIC_DIMENSIONS = [
    "novelty_claims_justified",      # Are novelty claims supported by evidence?
    "known_facts_correctly_labeled", # Are known facts/conjectures identified as such?
    "methodology_rigor",             # Is the methodology sound and reproducible?
    "discussion_depth",              # Does discussion go beyond generic statements?
    "references_quality",           # Are references real, relevant, and sufficient?
    "provenance_verifiability",      # Can results be traced to real experiments?
    "domain_appropriateness",        # Are claims within the paper's domain of expertise?
    "overall_scientific_quality",    # Overall assessment of scientific quality
]

RUBRIC_SCALE = (1, 7)  # 1=Very Poor, 7=Excellent

# ─── Ollama Cloud Client (reuse existing) ────────────────────────────────────

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))
from core.ollama_client import OllamaCloudClient


def _load_config() -> dict:
    """Load LLM config from project config.yaml."""
    import yaml
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        llm = cfg.get("llm", {})
        return {
            "base_url": llm.get("base_url", "https://ollama.com/api"),
            "reasoner": llm.get("reasoner", {}),
            "fast": llm.get("fast", {}),
        }
    return {"base_url": "https://ollama.com/api"}


# ─── Paper Anonymization ─────────────────────────────────────────────────────

def anonymize_paper(text: str, paper_id: str) -> str:
    """Strip identifying information from a paper for double-blind review.
    
    Removes:
    - Author names and affiliations
    - "A.M.Y" / "Atlas" / "AXIOM" references
    - Timestamps that could identify the paper
    - Provenance paths (replaced with generic references)
    - Any "Generated autonomously" footers
    - Emojis and decorative markers
    """
    lines = text.split("\n")
    anonymized_lines = []
    skip_section_level: int | None = None
    
    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if skip_section_level is not None:
            if heading_match and len(heading_match.group(1)) <= skip_section_level:
                skip_section_level = None
            else:
                continue

        if heading_match:
            heading_text = heading_match.group(2).strip().lower()
            if heading_text in {
                "internal peer review",
                "automated peer review",
                "peer review",
            }:
                skip_section_level = len(heading_match.group(1))
                continue

        # Skip author/affiliation lines
        if re.match(r"^\s*\*\*Authors?:\*\*", line, re.IGNORECASE):
            anonymized_lines.append(f"**Authors:** Anonymous [Paper {paper_id}]")
            continue
        if re.match(r"^\s*\*\*Affiliation:\*\*", line, re.IGNORECASE):
            anonymized_lines.append(f"**Affiliation:** Independent Research Institution")
            continue
        if re.match(r"^\s*\*\*Date:\*\*", line, re.IGNORECASE):
            anonymized_lines.append("**Date:** 2026")
            continue
        
        # Replace identifying strings
        anon_line = line
        for pattern in [
            r"A\.M\.Y", r"AMY", r"Atlas", r"AXIOM",
            r"autonomous_science", r"novelty_gate",
        ]:
            anon_line = re.sub(pattern, "[SYSTEM]", anon_line, flags=re.IGNORECASE)
        
        # Replace provenance paths with generic references
        anon_line = re.sub(
            r"`?data/experiments/[^`\s)]+/provenance\.json`?",
            f"[provenance_record_{paper_id}]",
            anon_line,
        )
        anon_line = re.sub(
            rf"^(\s*[-*]\s+)[A-Za-z0-9_.-]+:\s+`?(\[provenance_record_{re.escape(paper_id)}\])`?",
            r"\1\2",
            anon_line,
        )
        anon_line = re.sub(
            r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+_\d{8}_\d{6}\b",
            "[experiment_id]",
            anon_line,
        )
        
        # Replace specific timestamps
        anon_line = re.sub(r"\d{8}_\d{6}", "[TIMESTAMP]", anon_line)
        anon_line = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "[DATETIME]", anon_line)
        
        # Remove "Generated autonomously" footer
        if "generated autonomously" in anon_line.lower():
            continue
        
        # Strip emojis
        anon_line = re.sub(r"[🆕📊✅❌⚠️✓🎯🔬📈💡🔍🧮⚛️🧪🧬]", "", anon_line)
        anon_line = re.sub(r"\[(?:PASS|FAIL|NOTE)\]\s*", "", anon_line)
        
        anonymized_lines.append(anon_line)
    
    return "\n".join(anonymized_lines)


# ─── Review Prompt Templates ─────────────────────────────────────────────────

REVIEWER_SYSTEM_PROMPT = """You are an expert peer reviewer for computational science papers. 
You are reviewing papers that claim to present scientific findings from autonomous computational experiments.

Your role is to evaluate each paper on its scientific merit, NOT on who wrote it or how it was produced.
You must be objective, thorough, and consistent.

IMPORTANT: You are one of two independent reviewers. You must NOT consult any other reviewer.
Your evaluation must be entirely your own expert judgment.

You will evaluate each paper on the following rubric dimensions, using a {scale_min}-{scale_max} Likert scale:

1. novelty_claims_justified: Are novelty claims supported by evidence? (1=Claims are unjustified, 7=All claims well-supported)
2. known_facts_correctly_labeled: Are known facts/conjectures identified as such rather than claimed as novel? (1=Known facts presented as novel, 7=All known facts correctly labeled)
3. methodology_rigor: Is the methodology sound and reproducible? (1=No methodology, 7=Fully rigorous and reproducible)
4. discussion_depth: Does the discussion go beyond generic statements? (1=Generic/vague, 7=Deep domain-specific analysis)
5. references_quality: Are references real, relevant, and sufficient? (1=No references or fake, 7=Comprehensive real references)
6. provenance_verifiability: Can results be traced to real experiments? (1=No traceability, 7=Full provenance chain)
7. domain_appropriateness: Are claims within the paper's domain of expertise? (1=Claims leak across domains, 7=All claims domain-appropriate)
8. overall_scientific_quality: Overall assessment (1=Not scientific, 7=Publishable quality)

For each dimension, provide:
- Score (1-7)
- Brief justification (1-2 sentences)

Then provide:
- A list of specific concerns (if any)
- A list of strengths (if any)
- Your recommendation: ACCEPT / REVISE / REJECT
- Confidence in your review (1-7)

CRITICAL: You MUST respond with ONLY valid JSON. No markdown, no code blocks, no extra text.
The response must start with {{ and end with }}. Use double quotes for all strings."""

REVIEWER_PAPER_PROMPT = """Please review the following scientific paper. The paper has been anonymized for double-blind review.

=== PAPER START ===
{paper_text}
=== PAPER END ===

Provide your review in the following JSON format:
{{
    "scores": {{
        "novelty_claims_justified": <1-7>,
        "known_facts_correctly_labeled": <1-7>,
        "methodology_rigor": <1-7>,
        "discussion_depth": <1-7>,
        "references_quality": <1-7>,
        "provenance_verifiability": <1-7>,
        "domain_appropriateness": <1-7>,
        "overall_scientific_quality": <1-7>
    }},
    "concerns": ["<concern1>", "<concern2>", ...],
    "strengths": ["<strength1>", "<strength2>", ...],
    "recommendation": "<ACCEPT|REVISE|REJECT>",
    "confidence": <1-7>,
    "summary": "<2-3 sentence summary of your assessment>"
}}"""


# ─── Double-Blind Evaluator ──────────────────────────────────────────────────

class DoubleBlindEvaluator:
    """Orchestrates double-blind peer review using two independent LLM agents."""
    
    def __init__(
        self,
        papers_dir: Path = PAPERS_DIR,
        output_dir: Path = OUTPUT_DIR,
        review_delay_seconds: float = 2.0,
        retry_delay_seconds: float = 5.0,
        client=None,
    ):
        self.papers_dir = papers_dir
        self.output_dir = output_dir
        self.review_delay_seconds = review_delay_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Creating an evaluator for assignment/statistical analysis must not
        # require network credentials.  Initialize the model client only when a
        # review is actually requested; callers may inject a hermetic client.
        self.client = client
        
        self.session_id = datetime.now().strftime("dblind_%Y%m%d_%H%M%S")
        self.assignments: dict[str, dict] = {}  # paper_id → reviewer assignments
        self.reviews: dict[str, dict] = {}      # review_key → review data
        
    async def close(self):
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if close is not None:
                await close()

    def _get_client(self):
        if self.client is None:
            config = _load_config()
            self.client = OllamaCloudClient({
                "base_url": config.get("base_url", "https://ollama.com/api"),
            })
        return self.client
    
    def _find_paper_pairs(self) -> list[tuple[Path, Path, str]]:
        """Find pre-gate and post-gate paper pairs.
        
        Returns list of (pre_path, post_path, mission_name) tuples.
        """
        mission_prefixes = {
            "prime_gaps": "Computational_Analysis_of_Prime_Gap_Scaling_Anomalies_Relati",
            "quantum": "Verification_of_Rydberg_Formula_Scaling_and_Deviation_Analys",
            "molecular_orbital": "Huckel_Molecular_Orbital_Analysis_of_Conjugated_Pi-Systems_H",
            "deep_prime": "Computational_Verification_of_Prime_Properties_and_Classical",
        }
        
        pairs = []
        for mission, prefix in mission_prefixes.items():
            # Find all papers matching this prefix, sorted by timestamp
            all_candidates = sorted(self.papers_dir.glob(f"{prefix}_*.md"))
            
            if len(all_candidates) >= 2:
                # Pre-gate = oldest, Post-gate = newest
                pairs.append((all_candidates[0], all_candidates[-1], mission))
            else:
                log.warning("dblind.missing_pair", mission=mission, 
                           found=len(all_candidates))
        
        return pairs
    
    def _generate_paper_ids(self, pairs: list[tuple[Path, Path, str]]) -> dict[Path, str]:
        """Generate random anonymized IDs for each paper.
        
        Uses a deterministic seed for reproducibility, but the mapping
        is random so reviewers cannot guess which paper is which.
        """
        all_papers = []
        for pre_path, post_path, mission in pairs:
            all_papers.append(pre_path)
            all_papers.append(post_path)
        
        # Generate random 8-char hex IDs
        random.seed(42)  # Reproducible randomization
        ids = [format(random.randint(0, 0xFFFFFFFF), '08x') for _ in all_papers]
        random.shuffle(ids)  # Shuffle so pre/post are not adjacent
        
        # Re-assign ensuring no pair has adjacent IDs
        paper_to_id = {}
        idx = 0
        for pre_path, post_path, mission in pairs:
            paper_to_id[pre_path] = ids[idx]
            idx += 1
            paper_to_id[post_path] = ids[idx]
            idx += 1
        
        return paper_to_id
    
    def _assign_reviewers(self, paper_ids: dict[Path, str]) -> dict[str, dict]:
        """Assign papers to reviewers in a balanced design.
        
        Each paper is reviewed by BOTH reviewers (for inter-rater agreement).
        But the order and presentation is randomized independently.
        """
        assignments = {}
        papers = list(paper_ids.items())
        
        # Randomize presentation order for each reviewer independently
        random.seed(123)  # Different seed for reviewer assignment
        order_a = list(range(len(papers)))
        random.shuffle(order_a)
        
        random.seed(456)  # Different seed for reviewer B
        order_b = list(range(len(papers)))
        random.shuffle(order_b)
        
        for path, paper_id in papers:
            assignments[paper_id] = {
                "path": str(path),
                "reviewer_a": {
                    "model": REVIEWER_A_MODEL,
                    "order": order_a.index(list(paper_ids.keys()).index(path)),
                },
                "reviewer_b": {
                    "model": REVIEWER_B_MODEL,
                    "order": order_b.index(list(paper_ids.keys()).index(path)),
                },
            }
        
        return assignments
    
    async def _get_review(self, model: str, paper_id: str, paper_text: str, 
                          reviewer_label: str) -> dict:
        """Get a single review from one LLM reviewer."""
        log.info("dblind.reviewing", reviewer=reviewer_label, model=model, paper=paper_id)
        
        messages = [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT.format(
                scale_min=RUBRIC_SCALE[0], scale_max=RUBRIC_SCALE[1]
            )},
            {"role": "user", "content": REVIEWER_PAPER_PROMPT.format(paper_text=paper_text)},
        ]
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = await self._get_client().chat(
                    model=model,
                    messages=messages,
                    temperature=0.3,  # Low temperature for consistent evaluation
                    max_tokens=4096,
                    format_json=True,
                )
                
                # Extract response content
                content = result.get("message", {}).get("content", "")
                if not content:
                    content = result.get("response", "")
                
                # Parse JSON response
                # Try multiple strategies to extract valid JSON
                review = None
                
                # Strategy 1: Try direct parse
                try:
                    review = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    pass
                
                # Strategy 2: Extract JSON from markdown code blocks
                if review is None:
                    code_block = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
                    if code_block:
                        try:
                            review = json.loads(code_block.group(1))
                        except (json.JSONDecodeError, ValueError):
                            pass
                
                # Strategy 3: Find outermost JSON object
                if review is None:
                    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                    if json_match:
                        try:
                            review = json.loads(json_match.group())
                        except (json.JSONDecodeError, ValueError):
                            pass
                
                # Strategy 4: More aggressive extraction - find any JSON-like structure
                if review is None:
                    # Remove any non-JSON prefix/suffix
                    start = content.find('{')
                    end = content.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        try:
                            review = json.loads(content[start:end+1])
                        except (json.JSONDecodeError, ValueError):
                            pass
                
                if review is None:
                    raise ValueError(f"Could not parse JSON from response: {content[:200]}")
                
                # Validate required fields
                if "scores" not in review:
                    raise ValueError(f"Missing 'scores' in review for {paper_id}")
                missing_dims = [dim for dim in RUBRIC_DIMENSIONS if dim not in review["scores"]]
                if missing_dims:
                    raise ValueError(f"Missing score dimensions for {paper_id}: {missing_dims}")
                
                # Validate score ranges
                for dim, score in review["scores"].items():
                    if not isinstance(score, (int, float)):
                        raise ValueError(f"Score for {dim} is not numeric: {score}")
                    review["scores"][dim] = max(RUBRIC_SCALE[0], min(RUBRIC_SCALE[1], int(score)))
                
                log.info("dblind.review_complete", reviewer=reviewer_label, 
                        paper=paper_id, recommendation=review.get("recommendation"))
                return review
                
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("dblind.parse_error", reviewer=reviewer_label, 
                           paper=paper_id, attempt=attempt+1, error=str(e))
                if attempt == max_retries - 1:
                    return {
                        "scores": {},
                        "concerns": [f"Review parsing failed after {max_retries} attempts: {str(e)[:200]}"],
                        "strengths": [],
                        "recommendation": "INVALID",
                        "confidence": 0,
                        "summary": f"Review parsing error. Original model {model} failed.",
                        "_valid": False,
                        "_parse_error": True,
                    }
                await asyncio.sleep(self.retry_delay_seconds)
                
            except Exception as e:
                log.warning("dblind.api_error", reviewer=reviewer_label,
                           paper=paper_id, attempt=attempt+1, error=str(e)[:200])
                if attempt == max_retries - 1:
                    return {
                        "scores": {},
                        "concerns": [f"API error: {str(e)[:200]}"],
                        "strengths": [],
                        "recommendation": "INVALID",
                        "confidence": 0,
                        "summary": f"API call failed after {max_retries} attempts.",
                        "_valid": False,
                        "_api_error": True,
                    }
                await asyncio.sleep(self.retry_delay_seconds)
    
    async def run_evaluation(self) -> dict:
        """Run the full double-blind evaluation.
        
        Steps:
        1. Find paper pairs (pre-gate and post-gate)
        2. Anonymize all papers
        3. Assign random IDs and reviewer order
        4. Get reviews from both LLM reviewers
        5. Compute inter-rater agreement (Cohen's κ)
        6. Compare pre-gate vs post-gate scores
        7. Generate report
        """
        start_time = time.time()
        
        # Step 1: Find paper pairs
        pairs = self._find_paper_pairs()
        if not pairs:
            raise FileNotFoundError("No pre/post paper pairs found!")
        
        log.info("dblind.found_pairs", count=len(pairs))
        
        # Step 2: Generate anonymized IDs
        paper_ids = self._generate_paper_ids(pairs)
        
        # Step 3: Assign reviewers
        self.assignments = self._assign_reviewers(paper_ids)
        
        # Step 4: Anonymize all papers
        anonymized_papers = {}
        for path, paper_id in paper_ids.items():
            log.info("dblind.processing", paper=paper_id, path=path.name)
            
            # Read and anonymize
            raw_text = Path(path).read_text(encoding="utf-8")
            anon_text = anonymize_paper(raw_text, paper_id)
            
            # Save anonymized version
            anon_path = self.output_dir / f"anon_{paper_id}.md"
            anon_path.write_text(anon_text, encoding="utf-8")
            anonymized_papers[paper_id] = {
                "path": str(path),
                "text": anon_text,
            }

        # Step 5: Review in independent reviewer-specific orders
        for paper_id, assignment in sorted(
            self.assignments.items(),
            key=lambda item: item[1]["reviewer_a"]["order"],
        ):
            review_a = await self._get_review(
                REVIEWER_A_MODEL, paper_id, anonymized_papers[paper_id]["text"], "Reviewer_A"
            )
            await asyncio.sleep(self.review_delay_seconds)  # Rate limit buffer
            review_key_a = f"{paper_id}_A"
            self.reviews[review_key_a] = {
                "paper_id": paper_id,
                "reviewer": "A",
                "model": REVIEWER_A_MODEL,
                "review": review_a,
                "timestamp": datetime.now().isoformat(),
            }

        for paper_id, assignment in sorted(
            self.assignments.items(),
            key=lambda item: item[1]["reviewer_b"]["order"],
        ):
            review_b = await self._get_review(
                REVIEWER_B_MODEL, paper_id, anonymized_papers[paper_id]["text"], "Reviewer_B"
            )
            await asyncio.sleep(self.review_delay_seconds)  # Rate limit buffer
            review_key_b = f"{paper_id}_B"
            self.reviews[review_key_b] = {
                "paper_id": paper_id,
                "reviewer": "B",
                "model": REVIEWER_B_MODEL,
                "review": review_b,
                "timestamp": datetime.now().isoformat(),
            }

        all_reviews = []
        for path, paper_id in paper_ids.items():
            all_reviews.append({
                "paper_id": paper_id,
                "original_path": str(path),
                "review_a": self.reviews.get(f"{paper_id}_A", {}).get("review", {}),
                "review_b": self.reviews.get(f"{paper_id}_B", {}).get("review", {}),
            })
        
        # Step 6: Compute inter-rater agreement
        agreement = self._compute_inter_rater_agreement(all_reviews)
        
        # Step 7: Compare pre-gate vs post-gate
        comparison = self._compare_cohorts(pairs, paper_ids, all_reviews)
        
        # Step 8: Generate report
        duration = time.time() - start_time
        
        result = {
            "experiment": "double_blind_peer_review",
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(duration, 1),
            "reviewer_a_model": REVIEWER_A_MODEL,
            "reviewer_b_model": REVIEWER_B_MODEL,
            "n_papers": len(paper_ids),
            "n_pairs": len(pairs),
            "rubric_dimensions": RUBRIC_DIMENSIONS,
            "rubric_scale": list(RUBRIC_SCALE),
            "assignments": self.assignments,
            "reviews": {k: v for k, v in self.reviews.items()},
            "inter_rater_agreement": agreement,
            "cohort_comparison": comparison,
        }
        
        # Save full results
        results_path = self.output_dir / f"{self.session_id}_results.json"
        results_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("dblind.saved_results", path=str(results_path))
        
        # Generate human-readable report
        report = self._generate_report(result)
        report_path = self.output_dir / f"{self.session_id}_report.md"
        report_path.write_text(report, encoding="utf-8")
        log.info("dblind.saved_report", path=str(report_path))
        
        return result
    
    @staticmethod
    def _is_valid_review(review: dict) -> bool:
        if not review or review.get("_parse_error") or review.get("_api_error") or review.get("_valid") is False:
            return False
        scores = review.get("scores", {})
        if not all(dim in scores for dim in RUBRIC_DIMENSIONS):
            return False
        return all(isinstance(scores.get(dim), (int, float)) for dim in RUBRIC_DIMENSIONS)

    def _compute_inter_rater_agreement(self, all_reviews: list[dict]) -> dict:
        """Compute Cohen's κ and Pearson correlation for inter-rater agreement."""
        
        # Collect paired scores for each dimension
        dimension_scores = {dim: {"a": [], "b": []} for dim in RUBRIC_DIMENSIONS}
        overall_a = []
        overall_b = []
        
        valid_review_pairs = []
        invalid_pairs = []
        for review_data in all_reviews:
            if self._is_valid_review(review_data.get("review_a", {})) and self._is_valid_review(review_data.get("review_b", {})):
                valid_review_pairs.append(review_data)
            else:
                invalid_pairs.append(review_data)

        for review_data in valid_review_pairs:
            scores_a = review_data["review_a"].get("scores", {})
            scores_b = review_data["review_b"].get("scores", {})
            
            for dim in RUBRIC_DIMENSIONS:
                sa = scores_a.get(dim, 4)
                sb = scores_b.get(dim, 4)
                dimension_scores[dim]["a"].append(sa)
                dimension_scores[dim]["b"].append(sb)
            
            overall_a.append(scores_a.get("overall_scientific_quality", 4))
            overall_b.append(scores_b.get("overall_scientific_quality", 4))
        
        # Compute Cohen's κ for each dimension
        kappas = {}
        pearson_rs = {}
        for dim in RUBRIC_DIMENSIONS:
            a_scores = dimension_scores[dim]["a"]
            b_scores = dimension_scores[dim]["b"]
            kappas[dim] = self._cohens_kappa(a_scores, b_scores)
            pearson_rs[dim] = self._pearson_r(a_scores, b_scores)
        
        # Overall agreement
        overall_kappa = self._cohens_kappa(overall_a, overall_b)
        overall_pearson = self._pearson_r(overall_a, overall_b)
        
        # Recommendation agreement
        rec_a = [review_data["review_a"].get("recommendation", "REVISE") for review_data in valid_review_pairs]
        rec_b = [review_data["review_b"].get("recommendation", "REVISE") for review_data in valid_review_pairs]
        rec_agreement = sum(1 for a, b in zip(rec_a, rec_b) if a == b) / len(rec_a) if rec_a else 0
        
        return {
            "cohens_kappa_by_dimension": kappas,
            "pearson_r_by_dimension": pearson_rs,
            "overall_kappa": overall_kappa,
            "overall_pearson_r": overall_pearson,
            "recommendation_agreement": rec_agreement,
            "n_papers": len(all_reviews),
            "n_valid_pairs": len(valid_review_pairs),
            "n_invalid_pairs": len(invalid_pairs),
            "invalid_paper_ids": [item.get("paper_id") for item in invalid_pairs],
        }
    
    @staticmethod
    def _cohens_kappa(rater_a: list[int], rater_b: list[int]) -> float:
        """Compute Cohen's κ for two raters on a Likert scale.
        
        Uses quadratic weights for ordinal data.
        """
        n = len(rater_a)
        if n == 0:
            return float("nan")
        
        # Build confusion matrix over the full fixed Likert scale.
        categories = list(range(RUBRIC_SCALE[0], RUBRIC_SCALE[1] + 1))
        n_cats = len(categories)
        cat_to_idx = {c: i for i, c in enumerate(categories)}
        
        matrix = [[0] * n_cats for _ in range(n_cats)]
        for a, b in zip(rater_a, rater_b):
            if a not in cat_to_idx or b not in cat_to_idx:
                continue
            matrix[cat_to_idx[a]][cat_to_idx[b]] += 1
        
        # Observed agreement (weighted)
        weights = [[0.0] * n_cats for _ in range(n_cats)]
        for i in range(n_cats):
            for j in range(n_cats):
                diff = abs(categories[i] - categories[j])
                max_diff = max(1, RUBRIC_SCALE[1] - RUBRIC_SCALE[0])
                weights[i][j] = 1.0 - (diff / max_diff) ** 2
        
        # Expected agreement
        row_sums = [sum(row) for row in matrix]
        col_sums = [sum(matrix[i][j] for i in range(n_cats)) for j in range(n_cats)]
        total = sum(row_sums)
        
        if total == 0:
            return float("nan")
        
        observed = sum(
            weights[i][j] * matrix[i][j]
            for i in range(n_cats) for j in range(n_cats)
        ) / total
        
        expected = sum(
            weights[i][j] * row_sums[i] * col_sums[j]
            for i in range(n_cats) for j in range(n_cats)
        ) / (total * total)
        
        if expected == 1.0:
            return 1.0
        
        return (observed - expected) / (1.0 - expected)
    
    @staticmethod
    def _pearson_r(x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation coefficient."""
        n = len(x)
        if n < 2:
            return float("nan")
        
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        
        if std_x == 0 or std_y == 0:
            return float("nan")
        
        return cov / (std_x * std_y)
    
    def _compare_cohorts(self, pairs: list[tuple[Path, Path, str]], 
                         paper_ids: dict[Path, str],
                         all_reviews: list[dict]) -> dict:
        """Compare pre-gate vs post-gate scores from the double-blind reviews."""
        
        # Map paper_id to review data
        review_map = {}
        for rd in all_reviews:
            review_map[rd["paper_id"]] = rd
        
        # Separate pre and post reviews
        pre_scores = {dim: [] for dim in RUBRIC_DIMENSIONS}
        post_scores = {dim: [] for dim in RUBRIC_DIMENSIONS}
        
        pre_recommendations = []
        post_recommendations = []

        def valid_scores(review_data: dict, dim: str) -> list[float]:
            scores = []
            for key in ("review_a", "review_b"):
                review = review_data.get(key, {})
                if self._is_valid_review(review):
                    scores.append(float(review["scores"][dim]))
            return scores

        def valid_recommendations(review_data: dict) -> tuple[str, ...]:
            recs = []
            for key in ("review_a", "review_b"):
                review = review_data.get(key, {})
                if self._is_valid_review(review):
                    recs.append(review.get("recommendation", "REVISE"))
            return tuple(recs)
        
        for pre_path, post_path, mission in pairs:
            pre_id = paper_ids[pre_path]
            post_id = paper_ids[post_path]
            
            pre_rd = review_map.get(pre_id, {})
            post_rd = review_map.get(post_id, {})
            
            # Average valid reviewer scores only; invalid parse/API reviews are excluded.
            for dim in RUBRIC_DIMENSIONS:
                pre_valid = valid_scores(pre_rd, dim)
                post_valid = valid_scores(post_rd, dim)
                if pre_valid and post_valid:
                    pre_scores[dim].append(sum(pre_valid) / len(pre_valid))
                    post_scores[dim].append(sum(post_valid) / len(post_valid))
            
            pre_recommendations.append(valid_recommendations(pre_rd))
            post_recommendations.append(valid_recommendations(post_rd))
        
        # Compute means and effect sizes
        dimension_comparison = {}
        for dim in RUBRIC_DIMENSIONS:
            pre_mean = sum(pre_scores[dim]) / len(pre_scores[dim]) if pre_scores[dim] else 0
            post_mean = sum(post_scores[dim]) / len(post_scores[dim]) if post_scores[dim] else 0
            
            # Paired t-test (approximate)
            diffs = [post_scores[dim][i] - pre_scores[dim][i] 
                     for i in range(len(pre_scores[dim]))]
            mean_diff = sum(diffs) / len(diffs) if diffs else 0
            std_diff = math.sqrt(sum((d - mean_diff)**2 for d in diffs) / max(1, len(diffs) - 1)) if len(diffs) > 1 else 0
            t_stat = mean_diff / (std_diff / math.sqrt(len(diffs))) if std_diff > 0 and diffs else 0
            
            # Cohen's d
            pooled_std = std_diff if std_diff > 0 else 0.01
            cohens_d = mean_diff / pooled_std if pooled_std > 0 else 0
            
            dimension_comparison[dim] = {
                "pre_mean": round(pre_mean, 2),
                "post_mean": round(post_mean, 2),
                "mean_diff": round(mean_diff, 2),
                "paired_t": round(t_stat, 3),
                "cohens_d": round(cohens_d, 2),
                "direction": "improved" if mean_diff > 0 else ("worsened" if mean_diff < 0 else "unchanged"),
                "n_valid_pairs": len(diffs),
                "n_excluded_pairs": len(pairs) - len(diffs),
            }
        
        # Overall comparison
        pre_overall = [s for s in pre_scores["overall_scientific_quality"]]
        post_overall = [s for s in post_scores["overall_scientific_quality"]]
        
        pre_mean_overall = sum(pre_overall) / len(pre_overall) if pre_overall else 0
        post_mean_overall = sum(post_overall) / len(post_overall) if post_overall else 0
        
        # Wilcoxon signed-rank test (approximate with paired t)
        overall_diffs = [post_overall[i] - pre_overall[i] for i in range(len(pre_overall))]
        mean_overall_diff = sum(overall_diffs) / len(overall_diffs) if overall_diffs else 0
        
        return {
            "n_pairs": len(pairs),
            "dimension_comparison": dimension_comparison,
            "overall": {
                "pre_mean": round(pre_mean_overall, 2),
                "post_mean": round(post_mean_overall, 2),
                "mean_diff": round(mean_overall_diff, 2),
                "direction": "improved" if mean_overall_diff > 0 else ("worsened" if mean_overall_diff < 0 else "unchanged"),
            },
            "pre_recommendations": pre_recommendations,
            "post_recommendations": post_recommendations,
        }
    
    def _generate_report(self, result: dict) -> str:
        """Generate a human-readable double-blind evaluation report."""
        
        agreement = result["inter_rater_agreement"]
        comparison = result["cohort_comparison"]
        dim_comp = comparison["dimension_comparison"]
        
        # Build dimension comparison table
        dim_rows = []
        for dim in RUBRIC_DIMENSIONS:
            dc = dim_comp[dim]
            dim_rows.append(
                f"| {dim.replace('_', ' ').title()} | {dc['pre_mean']} | {dc['post_mean']} | "
                f"{dc['mean_diff']:+.2f} | {dc['cohens_d']:+.2f} | {dc['direction']} |"
            )
        
        # Build per-paper review table
        review_rows = []
        for review_key, review_data in result["reviews"].items():
            paper_id = review_data["paper_id"]
            reviewer = review_data["reviewer"]
            model = review_data["model"]
            review = review_data["review"]
            scores = review.get("scores", {})
            rec = review.get("recommendation", "N/A")
            conf = review.get("confidence", "N/A")
            status = "VALID" if self._is_valid_review(review) else "INVALID"
            
            review_rows.append(
                f"| {paper_id} | {reviewer} ({model}) | "
                f"{scores.get('overall_scientific_quality', 'N/A')} | "
                f"{scores.get('novelty_claims_justified', 'N/A')} | "
                f"{scores.get('known_facts_correctly_labeled', 'N/A')} | "
                f"{rec} | {conf} | {status} |"
            )
        
        # Build agreement table
        agree_rows = []
        for dim in RUBRIC_DIMENSIONS:
            kappa = agreement["cohens_kappa_by_dimension"].get(dim, float("nan"))
            pr = agreement["pearson_r_by_dimension"].get(dim, float("nan"))
            kappa_str = f"{kappa:.3f}" if not math.isnan(kappa) else "N/A"
            pr_str = f"{pr:.3f}" if not math.isnan(pr) else "N/A"
            agree_rows.append(
                f"| {dim.replace('_', ' ').title()} | {kappa_str} | {pr_str} |"
            )
        
        overall_kappa = agreement["overall_kappa"]
        overall_pr = agreement["overall_pearson_r"]
        rec_agree = agreement["recommendation_agreement"]
        
        kappa_str = f"{overall_kappa:.3f}" if not math.isnan(overall_kappa) else "N/A"
        pr_str = f"{overall_pr:.3f}" if not math.isnan(overall_pr) else "N/A"
        invalid_ids = ", ".join(agreement.get("invalid_paper_ids", [])) or "None"
        
        # Interpret κ
        if not math.isnan(overall_kappa):
            if overall_kappa >= 0.81:
                interp = "Almost perfect agreement"
            elif overall_kappa >= 0.61:
                interp = "Substantial agreement"
            elif overall_kappa >= 0.41:
                interp = "Moderate agreement"
            elif overall_kappa >= 0.21:
                interp = "Fair agreement"
            else:
                interp = "Slight/poor agreement"
        else:
            interp = "Could not be computed"
        
        report = f"""# Double-Blind Peer Review Evaluation Report

**Session:** {result['session_id']}
**Date:** {result['timestamp']}
**Duration:** {result['duration_seconds']:.0f} seconds
**Reviewer A:** {result['reviewer_a_model']}
**Reviewer B:** {result['reviewer_b_model']}
**Papers Reviewed:** {result['n_papers']} ({result['n_pairs']} pre/post pairs)

---

## 1. Inter-Rater Agreement

### Overall Agreement

| Metric | Value | Interpretation |
|--------|-------|---------------|
| Cohen's κ (overall) | {kappa_str} | {interp} |
| Pearson r (overall) | {pr_str} | Linear correlation |
| Recommendation agreement | {rec_agree:.0%} | ACCEPT/REVISE/REJECT match |
| Valid review pairs | {agreement.get('n_valid_pairs', result['n_papers'])}/{result['n_papers']} | Used in agreement statistics |
| Invalid/excluded pairs | {agreement.get('n_invalid_pairs', 0)} | Parse/API/missing-rubric failures |

**Excluded paper IDs:** {invalid_ids}

### Agreement by Dimension

| Dimension | Cohen's κ | Pearson r |
|-----------|-----------|-----------|
{chr(10).join(agree_rows)}

**Interpretation:** κ > 0.61 = substantial agreement, κ > 0.41 = moderate agreement, κ > 0.21 = fair agreement (Landis & Koch, 1977).

---

## 2. Pre-Gate vs Post-Gate Comparison

### Overall Quality

| Metric | Pre-Gate | Post-Gate | Difference |
|--------|----------|-----------|------------|
| Mean Overall Quality | {comparison['overall']['pre_mean']} | {comparison['overall']['post_mean']} | {comparison['overall']['mean_diff']:+.2f} |
| Direction | — | — | {comparison['overall']['direction']} |

### Dimension-by-Dimension Comparison

| Dimension | Pre-Gate Mean | Post-Gate Mean | Diff | Cohen's d | Direction |
|-----------|--------------|----------------|------|-----------|-----------|
{chr(10).join(dim_rows)}

---

## 3. Individual Reviews

| Paper ID | Reviewer | Overall | Novelty | Known Facts | Rec. | Conf. | Status |
|----------|----------|---------|---------|-------------|------|-------|--------|
{chr(10).join(review_rows)}

---

## 4. Methodology Notes

### Double-Blind Protocol
1. **Anonymization:** All papers were stripped of author names, affiliations, system identifiers (A.M.Y, Atlas, AXIOM), timestamps, and provenance paths.
2. **Random Assignment:** Each paper received a random 8-character hex ID. Review order was independently randomized for each reviewer.
3. **Independent Review:** Reviewer A ({result['reviewer_a_model']}) and Reviewer B ({result['reviewer_b_model']}) evaluated papers independently with no communication.
4. **Standardized Rubric:** Both reviewers used the same 8-dimension, 7-point Likert scale rubric.
5. **JSON-Structured Output:** Reviews were forced into structured JSON to enable quantitative comparison.

### Limitations
- LLM reviewers may share training data biases
- Sample size is small (n={result['n_pairs']} pairs)
- Cohen's κ with small n should be interpreted cautiously
- LLM reviewers cannot truly verify experimental reproducibility
- Invalid parse/API reviews are excluded from aggregate statistics and reported separately
- The anonymization removes some context that human reviewers would have

---

## 5. Conclusion

This double-blind evaluation using two independent LLM agents ({result['reviewer_a_model']} and {result['reviewer_b_model']}) provides an automated proxy for human peer review. The inter-rater agreement (κ = {kappa_str}) indicates {interp.lower()}. The pre/post-gate comparison shows whether the novelty hardening gates produced measurable improvements in paper quality as perceived by independent reviewers.

## References

[1] Landis, J.R. & Koch, G.G. (1977). The measurement of observer agreement for categorical data. Biometrics, 33(1), 159-174.
[2] Cohen, J. (1960). A coefficient of agreement for nominal scales. Educational and Psychological Measurement, 20(1), 37-46.
[3] Sakai, Y. et al. (2024). The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery. arXiv:2408.06292.
"""
        return report


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    """Run the double-blind evaluation."""
    evaluator = DoubleBlindEvaluator()
    try:
        result = await evaluator.run_evaluation()
        print(f"\n✅ Double-blind evaluation complete!")
        print(f"   Session: {result['session_id']}")
        print(f"   Papers: {result['n_papers']}")
        print(f"   Pairs: {result['n_pairs']}")
        print(f"   Duration: {result['duration_seconds']:.0f}s")
        
        agreement = result["inter_rater_agreement"]
        kappa = agreement["overall_kappa"]
        if not math.isnan(kappa):
            print(f"   Overall Cohen's κ: {kappa:.3f}")
        print(f"   Recommendation agreement: {agreement['recommendation_agreement']:.0%}")
        
        comparison = result["cohort_comparison"]
        overall = comparison["overall"]
        print(f"\n   Pre-gate overall quality: {overall['pre_mean']:.2f}")
        print(f"   Post-gate overall quality: {overall['post_mean']:.2f}")
        print(f"   Difference: {overall['mean_diff']:+.2f} ({overall['direction']})")
        
    finally:
        await evaluator.close()


if __name__ == "__main__":
    asyncio.run(main())
