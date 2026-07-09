"""
Paper Generator — A.M.Y's academic publication engine.

Converts A.M.Y's research findings, knowledge graph, and breakthrough reports
into structured academic papers (PDF + Markdown).

Format follows standard scientific paper structure:
Abstract → Introduction → Methods → Results → Discussion → Conclusion → References
"""
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

import structlog

from communication.citation_verifier import CitationVerifier
from communication.grounding_repair import repair_unsupported_decimal_claims
from communication.numeric_verifier import NumericVerifier
from communication.publication_artifacts import PublicationArtifactBuilder
from communication.paper_enhancer import PaperEnhancer

try:
    from core.atlas_tools import assess_tool_output
except ImportError:
    def assess_tool_output(output: object, tool_name: str | None = None) -> dict:
        return {"usable": bool(str(output or "").strip()), "markers": [], "warnings": []}

log = structlog.get_logger()

PAPERS_DIR = Path("papers")
PAPERS_DIR.mkdir(exist_ok=True)
REJECTED_PAPERS_DIR = PAPERS_DIR / "rejected"
EXPERIMENTS_DIR = Path("data/experiments")
MIN_PUBLICATION_PEER_REVIEW_SCORE = 7.0


def _sanitize_filename(title: str) -> str:
    return re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:60]


def _provenance_output_hash(experiment_id: str) -> str | None:
    """Return the real SHA-256 output hash recorded in provenance, if present."""
    prov_path = EXPERIMENTS_DIR / experiment_id / "provenance.json"
    try:
        record = json.loads(prov_path.read_text(encoding="utf-8"))
    except OSError as exc:
        log.warning("provenance.read_error", experiment_id=experiment_id, error=str(exc))
        return None
    except json.JSONDecodeError as exc:
        log.warning("provenance.json_error", experiment_id=experiment_id, error=str(exc))
        return None

    output_hash = record.get("tool", {}).get("output_hash")
    if isinstance(output_hash, str) and re.fullmatch(r"[a-fA-F0-9]{64}", output_hash):
        return output_hash.lower()
    return None


class PaperGenerator:
    def __init__(
        self,
        reasoning_engine=None,
        enhance: bool = True,
        include_internal_review: bool = False,
        include_literature_audit: bool | None = None,
        literature_search=None,
        output_dir: Path | str | None = None,
    ):
        self.reasoning = reasoning_engine
        self.enhance = enhance
        self.include_internal_review = include_internal_review
        self.include_literature_audit = (
            include_literature_audit
            if include_literature_audit is not None
            else os.getenv("AMY_PUBLICATION_LITERATURE_AUDIT", "0").lower() in {"1", "true", "yes", "on"}
        )
        self.literature_search = literature_search
        self._enhancer = PaperEnhancer()
        # Where generated papers (and their rejected counterparts) are written.
        # Defaults to the package-level PAPERS_DIR; pass output_dir to give a
        # run its own cohort folder (e.g. papers/e2e_v2/).
        self.papers_dir = Path(output_dir) if output_dir else PAPERS_DIR
        self.papers_dir.mkdir(parents=True, exist_ok=True)
        self.rejected_dir = self.papers_dir / "rejected"

    async def generate_paper(
        self,
        title: str,
        abstract: str,
        sections: list[dict],
        references: list[str] | None = None,
        knowledge_facts: list[dict] | None = None,
        experiment_ids: list[str] | None = None,
        domain: str | None = None,
        tool_results: list[dict] | None = None,
    ) -> dict:
        """
        Generate an academic paper from structured content.
        Returns paths to generated files.
        """
        enhanced_peer_review = None

        # Enhance paper if domain and tool_results are provided
        if self.enhance and domain and tool_results:
            try:
                enhanced = await self._enhancer.enhance_paper(
                    domain=domain,
                    topic=title.replace("Computational Analysis of ", ""),
                    results=tool_results,
                    sections=sections,
                    knowledge_facts=knowledge_facts,
                    experiment_ids=experiment_ids,
                )
                # Use enhanced content
                sections = enhanced["sections"]
                references = enhanced["references"]
                abstract = enhanced["abstract"]
                knowledge_facts = enhanced["knowledge_facts"]
                enhanced_peer_review = enhanced.get("peer_review") or {}
                log.info("paper_generator.enhanced",
                         hypotheses=len(enhanced.get("hypotheses", [])),
                         review_score=enhanced_peer_review.get("overall_score", 0))
            except Exception as e:
                log.warning("paper_generator.enhance_failed", error=str(e))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _sanitize_filename(title)
        md_path = self.papers_dir / f"{slug}_{timestamp}.md"
        pdf_path = self.papers_dir / f"{slug}_{timestamp}.pdf"
        tex_path = self.papers_dir / f"{slug}_{timestamp}.tex"

        publication_artifacts = {"tables": [], "figures": []}
        render_sections = list(sections)
        if tool_results or self.include_literature_audit:
            publication_artifacts = await PublicationArtifactBuilder().build_async(
                title=title,
                tool_results=tool_results,
                output_dir=self.papers_dir,
                literature_search=self.literature_search,
                include_literature_audit=self.include_literature_audit,
            )
            artifact_section = publication_artifacts.get("section")
            if artifact_section:
                render_sections.append(artifact_section)

        md_content = self._build_markdown(title, abstract, render_sections, references, knowledge_facts, experiment_ids, tool_results)
        grounding_repair = {"repairs": 0, "items": []}
        if experiment_ids:
            md_content, grounding_repair = repair_unsupported_decimal_claims(
                md_content,
                experiment_ids=experiment_ids,
            )
            if grounding_repair.get("repairs"):
                log.info("paper_generator.grounding_repaired", repairs=grounding_repair["repairs"])

        # Run factual verifiers before saving
        citation_v = CitationVerifier()
        numeric_v = NumericVerifier()
        cit_result = citation_v.verify_citations(md_content)
        num_result = numeric_v.verify_text(md_content, experiment_ids=experiment_ids or [])

        if cit_result.get("unverified"):
            md_content = citation_v.mark_unverified(md_content, cit_result["unverified"])
        if num_result.get("flagged"):
            md_content = numeric_v.mark_flagged(md_content, num_result["flagged"])

        gate = self._prepublication_gate(md_content, experiment_ids or [])
        if not gate["passed"]:
            return self._reject_draft(
                title=title,
                md_path=md_path,
                md_content=md_content,
                section_count=len(render_sections),
                reasons=gate["reasons"],
                grounding_repair=grounding_repair,
                publication_artifacts=publication_artifacts,
            )

        peer_review_gate = self._peer_review_gate(enhanced_peer_review)
        if not peer_review_gate["passed"]:
            return self._reject_draft(
                title=title,
                md_path=md_path,
                md_content=md_content,
                section_count=len(render_sections),
                reasons=peer_review_gate["reasons"],
                grounding_repair=grounding_repair,
                publication_artifacts=publication_artifacts,
            )

        reflection_summary = self._run_reflection_gate(md_content)
        if reflection_summary is not None:
            if self.include_internal_review:
                md_content = reflection_summary["annotated_md"]
            log.info("paper_generator.reflection_done",
                     score=reflection_summary["score"],
                     pass_overall=reflection_summary["pass_overall"],
                     n_high=reflection_summary["n_high"])
            if not reflection_summary["pass_overall"]:
                reasons = ["reflection gate failed"]
                if reflection_summary["n_high"] > 0:
                    reasons.append("reflection high-severity issues")
                return self._reject_draft(
                    title=title,
                    md_path=md_path,
                    md_content=reflection_summary["annotated_md"],
                    section_count=len(render_sections),
                    reasons=reasons,
                    grounding_repair=grounding_repair,
                    publication_artifacts=publication_artifacts,
                )

        md_content = self._append_watermark(
            md_content,
            title,
            includes_internal_review=self.include_internal_review,
        )

        pdf_ok = await self._render_pdf(md_content, pdf_path, title, abstract, render_sections, references)
        if not pdf_ok:
            return self._reject_draft(
                title=title,
                md_path=md_path,
                md_content=md_content,
                section_count=len(render_sections),
                reasons=["pdf render failed"],
                grounding_repair=grounding_repair,
                publication_artifacts=publication_artifacts,
            )

        tex_ok = await self._render_latex(
            tex_path,
            title,
            abstract,
            render_sections,
            references,
            publication_artifacts=publication_artifacts,
        )

        md_path.write_text(md_content, encoding="utf-8")
        log.info("paper_generator.markdown_written", path=str(md_path), chars=len(md_content))

        review_path = None
        if reflection_summary is not None and not self.include_internal_review:
            review_path = md_path.with_suffix(".review.json")
            review_path.write_text(
                json.dumps(
                    {
                        "score": reflection_summary["score"],
                        "pass_overall": reflection_summary["pass_overall"],
                        "n_high": reflection_summary["n_high"],
                        "n_medium": reflection_summary["n_medium"],
                        "n_low": reflection_summary["n_low"],
                        "issues": reflection_summary["issues"],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log.info("paper_generator.review_sidecar_written", path=str(review_path))

        result = {
            "title": title,
            "markdown_path": str(md_path),
            "pdf_path": str(pdf_path),
            "latex_path": str(tex_path) if tex_ok else None,
            "word_count": len(md_content.split()),
            "sections": len(render_sections),
            "publication_status": "published",
            "rejection_reasons": [],
            "internal_review_path": str(review_path) if review_path else None,
            "grounding_repair": grounding_repair,
            "publication_artifacts": publication_artifacts,
        }
        log.info("paper_generator.paper_complete", **result)
        return result

    def _prepublication_gate(self, md_content: str, experiment_ids: list[str]) -> dict:
        """Reject drafts that cite experiments without verifiable provenance."""
        reasons = []

        missing_hash_ids = [
            eid for eid in dict.fromkeys(experiment_ids)
            if not _provenance_output_hash(eid)
        ]
        if missing_hash_ids:
            reasons.append("missing provenance output hash")

        code_blocks = re.findall(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", md_content, flags=re.DOTALL)
        unusable_blocks = []
        for block in code_blocks:
            assessment = assess_tool_output(block)
            if not assessment.get("usable", False):
                unusable_blocks.append(assessment)
        full_text_assessment = assess_tool_output(md_content)
        if full_text_assessment.get("markers") and not any(
            set(full_text_assessment.get("markers", [])).issubset(set(block.get("markers", [])))
            for block in unusable_blocks
        ):
            unusable_blocks.append(full_text_assessment)
        if unusable_blocks:
            reasons.append("unusable tool output in manuscript")

        return {"passed": not reasons, "reasons": reasons}

    @staticmethod
    def _peer_review_gate(peer_review: dict | None) -> dict:
        """Reject enhanced drafts whose own reviewer score is below paper quality."""
        if not peer_review:
            return {"passed": True, "reasons": []}
        try:
            score = float(peer_review.get("overall_score"))
        except (TypeError, ValueError):
            return {"passed": False, "reasons": ["peer review score missing or invalid"]}
        if score < MIN_PUBLICATION_PEER_REVIEW_SCORE:
            return {
                "passed": False,
                "reasons": [
                    "peer review score below publication threshold "
                    f"({score:.1f} < {MIN_PUBLICATION_PEER_REVIEW_SCORE:.1f})"
                ],
            }
        return {"passed": True, "reasons": []}

    def _reject_draft(
        self,
        *,
        title: str,
        md_path: Path,
        md_content: str,
        section_count: int,
        reasons: list[str],
        grounding_repair: dict,
        publication_artifacts: dict,
    ) -> dict:
        self.rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = self.rejected_dir / md_path.name
        rejected_content = self._annotate_rejected_draft(md_content, reasons)
        rejected_path.write_text(rejected_content, encoding="utf-8")
        result = {
            "title": title,
            "markdown_path": str(rejected_path),
            "pdf_path": None,
            "word_count": len(rejected_content.split()),
            "sections": section_count,
            "publication_status": "rejected",
            "rejection_reasons": reasons,
            "grounding_repair": grounding_repair,
            "publication_artifacts": publication_artifacts,
        }
        log.warning("paper_generator.prepublication_rejected", **result)
        return result

    @staticmethod
    def _append_watermark(
        md_content: str,
        title: str,
        includes_internal_review: bool = False,
    ) -> str:
        """Append a machine-readable watermark identifying this paper as A.M.Y-generated.

        The watermark serves two purposes:
        1. Lets downstream consumers (journals, search engines, peer reviewers)
           detect and filter A.M.Y-generated content if they choose to.
        2. Carries the A.M.Y version and a content fingerprint so the manuscript
           can be linked back to the exact A.M.Y release that produced it.
        """
        import hashlib as _hashlib
        from datetime import datetime as _dt, timezone as _tz

        try:
            from amy import __version__ as amy_version  # type: ignore
        except Exception:
            amy_version = "1.0.0"

        body_hash = _hashlib.sha256(md_content.encode("utf-8")).hexdigest()
        ts = _dt.now(_tz.utc).isoformat()

        review_note = (
            "embedded_in_manuscript"
            if includes_internal_review
            else "external_sidecar_when_available"
        )

        watermark = (
            "\n\n---\n\n"
            "## Provenance Watermark\n\n"
            "This manuscript was generated by an autonomous research system. It is **not** a "
            "peer-reviewed publication. Treat individual claims as computational artifacts "
            "until independently verified.\n\n"
            "<!-- AMY-WATERMARK\n"
            f"generated_by: A.M.Y (Autonomous Mind Yield) v{amy_version}\n"
            f"title: {title}\n"
            f"generated_at: {ts}\n"
            f"body_sha256: {body_hash}\n"
            "homepage: https://github.com/Ganador1/amy\n"
            f"self_review: {review_note}\n"
            "verification: Each cited experiment_id resolves to data/experiments/<id>/provenance.json with a SHA-256 hash of the full tool output.\n"
            "-->\n"
        )
        return md_content + watermark

    @staticmethod
    def _run_reflection_gate(md_content: str) -> dict | None:
        """Run the Reflection Agent and annotate the draft with its findings.

        This is an *advisory* gate — it does not reject the draft, but it
        surfaces concrete weaknesses (missing limitations, ungrounded numbers,
        weak hypotheses) and embeds them in the manuscript as a Self-Review
        section so a downstream reviewer (or the author) can act on them.
        """
        try:
            from cognition.reflection_agent import reflect
        except Exception as exc:
            log.warning("paper_generator.reflection_unavailable", error=str(exc))
            return None

        try:
            result = reflect(md_content)
        except Exception as exc:
            log.warning("paper_generator.reflection_failed", error=str(exc))
            return None

        if not result.issues:
            block = "\n\n## Self-Review (Reflection Agent)\n\nInternal self-review passed (score: {:.1f}/100).\n".format(result.score)
        else:
            lines = [
                "\n\n## Self-Review (Reflection Agent)\n",
                f"Internal review score: **{result.score:.1f}/100** "
                f"({result.annotations['n_high']} high, "
                f"{result.annotations['n_medium']} medium, "
                f"{result.annotations['n_low']} low).\n",
                "\n**Action items raised by self-review:**\n",
            ]
            for iss in result.issues:
                lines.append(f"- *[{iss['severity']}]* **{iss['section']}**: {iss['message']} → *{iss['suggestion']}*")
            lines.append("")
            block = "\n".join(lines)

        return {
            "annotated_md": md_content + block,
            "score": result.score,
            "pass_overall": result.pass_overall,
            "n_high": result.annotations["n_high"],
            "n_medium": result.annotations["n_medium"],
            "n_low": result.annotations["n_low"],
            "issues": result.issues,
        }

    @staticmethod
    def _annotate_rejected_draft(md_content: str, reasons: list[str]) -> str:
        reason_lines = "\n".join(f"- {reason}" for reason in reasons)
        return (
            "<!-- PREPUBLICATION_REJECTED\n"
            f"{reason_lines}\n"
            "-->\n\n"
            + md_content
        )

    # ─── Domain-specific templates ────────────────────────────────────────
    DOMAIN_TEMPLATES = {
        "mathematics": {
            "classification": "MSC 11A41 (Prime numbers), MSC 11N05 (Distribution of primes), MSC 11Y11 (Primality)",
            "keywords": "computational number theory, prime distribution, automated verification, numerical methods",
            "intro_boilerplate": (
                "The Prime Number Theorem (PNT), independently proved by Hadamard and de la Vallée-Poussin in 1896, "
                "states that the prime-counting function π(n) ∼ n/ln(n). Recent computational advances have enabled "
                "systematic verification of number-theoretic conjectures at unprecedented scale (Oliveira e Silva et al., 2014). "
                "This study presents a reproducible computational verification using the AXIOM Atlas platform."
            ),
        },
        "physics": {
            "classification": "PACS 31.15.-p (Calculations and mathematical techniques in atomic physics), PACS 32.30.-r (Atomic spectra)",
            "keywords": "atomic physics, quantum energy levels, Rydberg formula, computational verification",
            "intro_boilerplate": (
                "The Rydberg formula E_n = -13.6/n² eV describes the energy levels of the hydrogen atom "
                "with remarkable precision. First empirically derived by Balmer (1885) and generalized by "
                "Rydberg (1888), it was later derived from first principles by Bohr (1913). "
                "This formula remains the foundation of atomic spectroscopy and is essential for "
                "stellar astrophysics, plasma physics, and quantum chemistry. "
                "This study verifies the AXIOM Atlas platform's reproduction of these fundamental quantum levels."
            ),
        },
        "chemistry": {
            "classification": "PACS 31.15.-p (Electronic structure of molecules), PACS 82.20.-w (Chemical kinetics)",
            "keywords": "computational chemistry, molecular weight, bond energy, Hückel theory, IUPAC standards",
            "intro_boilerplate": (
                "Accurate molecular weights and bond energies are fundamental to computational chemistry. "
                "The IUPAC atomic masses provide the standard reference for molecular weight calculations, "
                "while bond dissociation energies are critical for thermochemical modeling (Benson, 1965). "
                "Hückel molecular orbital theory provides a semi-empirical framework for understanding "
                "conjugated π-systems (Hückel, 1931). "
                "This study verifies the AXIOM Atlas platform's ability to reproduce these fundamental chemical quantities."
            ),
        },
        "biology": {
            "classification": "MSC 92D20 (DNA sequencing), MSC 92-05 (Computational biology)",
            "keywords": "bioinformatics, DNA analysis, protein properties, computational biology, sequence analysis",
            "intro_boilerplate": (
                "DNA sequence analysis and protein property prediction are foundational techniques in "
                "bioinformatics. The DNA double helix, first described by Watson and Crick (1953), "
                "encodes genetic information through the sequence of four nucleotides (A, T, G, C). "
                "Protein sequences, composed of 20 amino acids, determine three-dimensional structure "
                "and biological function (Anfinsen, 1973). "
                "This study verifies the AXIOM Atlas platform's ability to perform basic bioinformatics computations."
            ),
        },
        "statistics": {
            "classification": "MSC 62-05 (Statistical analysis), MSC 62E15 (Distribution theory)",
            "keywords": "computational statistics, normal distribution, correlation analysis, hypothesis testing",
            "intro_boilerplate": (
                "Statistical analysis is fundamental to all empirical sciences. The normal (Gaussian) "
                "distribution, first studied by Gauss (1809) and Laplace (1812), arises from the Central "
                "Limit Theorem and describes the distribution of sample means for large sample sizes. "
                "Pearson's correlation coefficient measures linear relationships between variables, "
                "while Student's t-test (Gosset, 1908) is the standard method for comparing group means. "
                "This study verifies the AXIOM Atlas platform's statistical computation capabilities."
            ),
        },
        "astronomy": {
            "classification": "MSC 85A04 (Astrophysics), MSC 81V45 (Atomic physics), MSC 85-05 (Computational astrophysics)",
            "keywords": "stellar astrophysics, hydrogen spectrum, Rydberg formula, computational verification, exoplanets",
            "intro_boilerplate": (
                "The hydrogen Balmer series is the primary diagnostic for stellar classification, "
                "effective temperature determination, and atmospheric modeling across the Hertzsprung-Russell diagram "
                "(Morgan & Keenan, 1973). Accurate computation of hydrogen energy levels is a prerequisite "
                "for any automated astrophysical reasoning system. "
                "This study presents a reproducible, provenance-gated verification of the Rydberg formula "
                "using the AXIOM Atlas computational platform."
            ),
        },
        "medicine": {
            "classification": "MSC 92C50 (Medical applications), MSC 92-05 (Computational biology)",
            "keywords": "computational medicine, protein structure, clinical evidence, automated verification",
            "intro_boilerplate": (
                "Computational methods are increasingly central to medical research, from protein structure "
                "prediction (Jumper et al., 2021) to evidence synthesis from clinical trials. "
                "Automated verification of biomedical claims against published literature is essential "
                "for maintaining scientific rigor in AI-assisted research. "
                "This study evaluates the AXIOM Atlas platform's ability to corroborate medical hypotheses "
                "against published evidence."
            ),
        },
        "neuroscience": {
            "classification": "MSC 92C20 (Neural biology), MSC 92-05 (Computational biology)",
            "keywords": "computational neuroscience, synaptic plasticity, neural activity, evidence synthesis",
            "intro_boilerplate": (
                "Neuroscience has been transformed by computational approaches that bridge molecular mechanisms "
                "and systems-level phenomena. Synaptic plasticity—the activity-dependent modification of "
                "synaptic strength—is widely considered the cellular basis of learning and memory "
                "(Bliss & Lømo, 1973; Martin et al., 2000). "
                "This study evaluates the AXIOM Atlas platform's ability to analyze neural data and "
                "corroborate neuroscience hypotheses against published literature."
            ),
        },
        "climate": {
            "classification": "MSC 86A10 (Meteorology and atmospheric physics), MSC 86-05 (Computational geophysics)",
            "keywords": "climate science, global temperature, evidence synthesis, computational verification",
            "intro_boilerplate": (
                "Climate science relies on the integration of observational data, theoretical models, "
                "and computational simulations. The global temperature record, compiled from thousands of "
                "weather stations, ocean buoys, and satellite measurements, provides the primary evidence "
                "for anthropogenic climate change (Hersbach et al., 2020). "
                "This study evaluates the AXIOM Atlas platform's ability to corroborate climate hypotheses "
                "against published scientific evidence."
            ),
        },
        "engineering": {
            "classification": "MSC 74S05 (Finite element methods), MSC 74-05 (Computational mechanics)",
            "keywords": "computational engineering, additive manufacturing, finite element analysis, evidence synthesis",
            "intro_boilerplate": (
                "Computational methods are essential in modern engineering, from finite element analysis "
                "of structural integrity to additive manufacturing process optimization. "
                "Automated verification of engineering claims against published literature supports "
                "evidence-based design and manufacturing decisions. "
                "This study evaluates the AXIOM Atlas platform's ability to corroborate engineering "
                "hypotheses against published evidence."
            ),
        },
        "machine-learning": {
            "classification": "ACM CCS: Computing methodologies > Machine learning; Information theory",
            "keywords": "machine learning, information bottleneck, representation learning, neural networks, reproducibility",
            "intro_boilerplate": (
                "Machine-learning research increasingly depends on reproducible experimental protocols, "
                "negative controls, and explicit uncertainty reporting. Information-theoretic analyses "
                "of neural representations are especially sensitive to estimator choice and benchmark "
                "design, so provenance-backed computational studies must distinguish diagnostic signals "
                "from broad theoretical claims."
            ),
        },
    }

    def _detect_domain(self, title: str, sections: list[dict], experiment_ids: list[str] | None) -> str:
        """Detect the scientific domain from paper content."""
        text = (title + " " + " ".join(s.get("content", "") for s in sections)).lower()
        
        # Check experiment_ids first
        if experiment_ids:
            for eid in dict.fromkeys(experiment_ids):
                for domain in self.DOMAIN_TEMPLATES:
                    if domain in eid.lower():
                        return domain
        
        # Keyword-based detection
        domain_keywords = {
            "mathematics": ["prime", "number theory", "goldbach", "theorem", "proof", "conjecture", "equation"],
            "physics": ["quantum", "rydberg", "energy level", "hydrogen", "atom", "spectrum", "bohr"],
            "chemistry": ["molecular weight", "bond energy", "hückel", "molecule", "organic", "iupac"],
            "biology": ["dna", "protein", "sequence", "amino acid", "bioinformatics", "genome"],
            "statistics": ["normal distribution", "correlation", "t-test", "statistical", "gaussian"],
            "astronomy": ["stellar", "astrophysics", "exoplanet", "spectral", "balmer", "rydberg"],
            "medicine": ["clinical", "medical", "protein structure", "drug", "therapy", "disease"],
            "neuroscience": ["neural", "synaptic", "brain", "neuron", "plasticity", "memory"],
            "climate": ["climate", "temperature", "global warming", "co2", "atmospheric"],
            "engineering": ["additive manufacturing", "3d printing", "finite element", "structural"],
            "machine-learning": ["information bottleneck", "relu", "neural network", "representation learning", "held-out", "label-shuffled"],
        }
        
        scores = {}
        for domain, keywords in domain_keywords.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[domain] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "mathematics"

    def _build_markdown(
        self,
        title: str,
        abstract: str,
        sections: list[dict],
        references: list[str] | None,
        knowledge_facts: list[dict] | None,
        experiment_ids: list[str] | None,
        tool_results: list[dict] | None = None,
    ) -> str:
        now = datetime.now().strftime("%B %d, %Y")
        
        domain = self._detect_domain(title, sections, experiment_ids)
        template = self.DOMAIN_TEMPLATES.get(domain, self.DOMAIN_TEMPLATES["mathematics"])
        
        # Build IMRaD-standard paper
        lines = [
            f"# {title}",
            "",
            f"**Authors:** A.M.Y Computational Research System [1]",
            f"**Affiliation:** [1] AXIOM Atlas Platform, Autonomous Computational Research",
            f"**Date:** {now}",
            f"**Classification:** {template['classification']}",
            f"**Keywords:** {template['keywords']}",
            "",
            "---",
            "",
            "## Abstract",
            "",
            abstract,
            "",
        ]
        
        # Standard IMRaD sections only
        standard_sections = [
            "introduction",
            "methods",
            "results",
            "discussion",
            "testable predictions",
            "limitations",
            "reproducibility",
            "data availability",
            "declarations",
            "ai disclosure",
            "conclusion",
            "publication artifacts",
        ]
        for sec in sections:
            heading = sec.get("heading", "Section")
            content = sec.get("content", "")
            heading_lower = heading.lower()
            
            # Only include standard academic sections in the main body
            is_standard = any(s in heading_lower for s in standard_sections)
            # Also include novelty analysis as part of Results/Discussion
            if "novelty" in heading_lower:
                is_standard = True
            
            if is_standard:
                # Strip emojis from content (not academic)
                clean_content = self._strip_emojis(content)
                lines.append(f"## {heading}")
                lines.append("")
                
                # If this is the Results section and we have tool_results, format evidence grades
                if "results" in heading_lower and tool_results:
                    evidence_grade_tools = []
                    heuristic_tools = []
                    
                    for r in tool_results:
                        tool_name = r.get("tool", "unknown")
                        # Real/local/evidence tools
                        if any(k in tool_name.lower() for k in ["pyscf", "sympy", "scipy", "astropy", "ase", "pymatgen"]):
                            evidence_grade_tools.append(r)
                        elif "search" in tool_name.lower() or "literature" in tool_name.lower():
                            evidence_grade_tools.append(r)
                        else:
                            heuristic_tools.append(r)
                    
                    if evidence_grade_tools:
                        lines.append("### Evidence-grade results")
                        lines.append("")
                        for r in evidence_grade_tools:
                            lines.append(f"**Tool:** `{r.get('tool', 'unknown')}`")
                            lines.append(f"```text\n{str(r.get('result', ''))[:1000]}...\n```")
                        lines.append("")
                    
                    if heuristic_tools:
                        lines.append("### Heuristic/demo results")
                        lines.append("")
                        for r in heuristic_tools:
                            lines.append(f"**Tool:** `{r.get('tool', 'unknown')}`")
                            lines.append(f"```text\n{str(r.get('result', ''))[:1000]}...\n```")
                        lines.append("")
                    
                    # Also include the original results text for narrative context
                    lines.append("### Summary Analysis")
                    lines.append("")
                    
                lines.append(clean_content)
                lines.append("")

        # Acknowledgments (standard academic section)
        lines += [
            "## Acknowledgments",
            "",
            "The authors acknowledge the AXIOM Atlas computational platform for providing ",
            "the scientific tools used in this study. All computations were performed on ",
            "Apple Silicon M4 hardware with Python 3.13 and MPS acceleration.",
            "",
        ]

        # Data Availability Statement (standard in modern science)
        if experiment_ids:
            lines += [
                "## Data Availability",
                "",
                "All computational data supporting this study are publicly available. ",
                "The following experiment records contain full provenance information ",
                "including input parameters, complete output, execution environment, ",
                "and SHA-256 output hashes:",
                "",
            ]
            for eid in experiment_ids:
                output_hash = _provenance_output_hash(eid)
                if output_hash:
                    lines.append(
                        f"- {eid}: `data/experiments/{eid}/provenance.json` "
                        f"(output SHA-256: `{output_hash}`)"
                    )
                else:
                    lines.append(
                        f"- {eid}: `data/experiments/{eid}/provenance.json` "
                        "(output SHA-256: unavailable; provenance file must be verified before release)"
                    )
            lines.append("")

        # References in academic format
        if references:
            lines += ["## References", ""]
            for i, ref in enumerate(references, 1):
                lines.append(f"[{i}] {ref}")
            lines.append("")

        # Supplementary Material (peer review, hypotheses go here — not in main body)
        has_hypotheses = any("hypothesis" in s.get("heading", "").lower() for s in sections)
        has_review = any("peer review" in s.get("heading", "").lower() or "review" in s.get("heading", "").lower() for s in sections)
        
        if has_hypotheses or has_review:
            lines += [
                "---",
                "",
                "## Supplementary Material",
                "",
            ]
            for sec in sections:
                heading = sec.get("heading", "Section")
                content = sec.get("content", "")
                heading_lower = heading.lower()
                
                # Non-standard sections go to supplementary
                is_supplementary = (
                    "hypothesis" in heading_lower 
                    or "peer review" in heading_lower 
                    or "review" in heading_lower
                    or "key facts" in heading_lower
                )
                if is_supplementary:
                    clean_content = self._strip_emojis(content)
                    lines.append(f"### {heading}")
                    lines.append("")
                    lines.append(clean_content)
                    lines.append("")

        return "\n".join(lines)
    
    @staticmethod
    def _strip_emojis(text: str) -> str:
        """Remove emojis and non-academic markers from text."""
        # Remove common emojis used in A.M.Y output
        emoji_map = {
            "🆕 **NOVEL**:": "[NOVEL]:",
            "📊:": "[DATA]:",
            "✅": "[PASS]",
            "❌": "[FAIL]",
            "⚠️": "[NOTE]",
            "✓": "[PASS]",
            "✗": "[FAIL]",
            "🆕": "[NOVEL]",
            "📊": "[DATA]",
            "🔬": "",
            "📄": "",
            "📋": "",
            "🔧": "",
            "🚀": "",
            "😴": "",
            "💥": "",
            "⏱️": "",
            "🧪": "",
        }
        result = text
        for emoji, replacement in emoji_map.items():
            result = result.replace(emoji, replacement)
        return result

    async def _render_pdf(
        self,
        md_content: str,
        pdf_path: Path,
        title: str,
        abstract: str,
        sections: list[dict],
        references: list[str] | None,
    ) -> bool:
        """Render PDF using reportlab."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                HRFlowable,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2.5 * cm,
                leftMargin=2.5 * cm,
                topMargin=2.5 * cm,
                bottomMargin=2.5 * cm,
            )

            styles = getSampleStyleSheet()
            style_title = ParagraphStyle(
                "Title",
                parent=styles["Title"],
                fontSize=18,
                spaceAfter=6,
                textColor=colors.HexColor("#1a1a2e"),
                alignment=TA_CENTER,
            )
            style_author = ParagraphStyle(
                "Author",
                parent=styles["Normal"],
                fontSize=10,
                spaceAfter=4,
                textColor=colors.HexColor("#555555"),
                alignment=TA_CENTER,
            )
            style_h2 = ParagraphStyle(
                "H2",
                parent=styles["Heading2"],
                fontSize=13,
                spaceBefore=14,
                spaceAfter=6,
                textColor=colors.HexColor("#16213e"),
                borderPad=4,
            )
            style_body = ParagraphStyle(
                "Body",
                parent=styles["Normal"],
                fontSize=10,
                leading=15,
                spaceAfter=8,
                alignment=TA_JUSTIFY,
            )
            style_abstract = ParagraphStyle(
                "Abstract",
                parent=styles["Normal"],
                fontSize=10,
                leading=14,
                leftIndent=30,
                rightIndent=30,
                spaceAfter=12,
                textColor=colors.HexColor("#333333"),
                alignment=TA_JUSTIFY,
            )

            now = datetime.now().strftime("%B %d, %Y")
            story = [
                Paragraph(title, style_title),
                Spacer(1, 0.3 * cm),
                Paragraph("A.M.Y Computational Research System [1]", style_author),
                Paragraph(f"AXIOM Atlas Platform, Autonomous Computational Research · {now}", style_author),
                Spacer(1, 0.5 * cm),
                HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a1a2e")),
                Spacer(1, 0.5 * cm),
                Paragraph("Abstract", style_h2),
            ]

            # Split abstract into safe paragraphs
            for para in abstract.split("\n\n"):
                para = para.strip()
                if para:
                    story.append(Paragraph(_safe_para(para), style_abstract))

            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))

            for sec in sections:
                story.append(Paragraph(sec.get("heading", ""), style_h2))
                content = sec.get("content", "")
                for para in content.split("\n\n"):
                    para = para.strip()
                    if not para:
                        continue
                    # Render bullet points
                    if para.startswith("- ") or para.startswith("* "):
                        for line in para.split("\n"):
                            line = line.lstrip("-* ").strip()
                            if line:
                                story.append(Paragraph(f"• {_safe_para(line)}", style_body))
                    else:
                        story.append(Paragraph(_safe_para(para), style_body))
                story.append(Spacer(1, 0.2 * cm))

            if references:
                story.append(Paragraph("References", style_h2))
                for i, ref in enumerate(references, 1):
                    story.append(Paragraph(f"{i}. {_safe_para(ref)}", style_body))

            story.append(Spacer(1, 1 * cm))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
            story.append(
                Paragraph(
                    "<i>Computational research report with provenance-linked results and cited references.</i>",
                    style_author,
                )
            )

            doc.build(story)
            log.info("paper_generator.pdf_written", path=str(pdf_path))
            return True

        except Exception as e:
            log.error("paper_generator.pdf_error", error=str(e))
            return False

    async def _render_latex(
        self,
        tex_path: Path,
        title: str,
        abstract: str,
        sections: list[dict],
        references: list[str] | None,
        publication_artifacts: dict | None = None,
    ) -> bool:
        """Render paper to LaTeX format."""
        try:
            lines = [
                "\\documentclass[11pt,a4paper]{article}",
                "\\usepackage[utf8]{inputenc}",
                "\\usepackage[T1]{fontenc}",
                "\\usepackage{amsmath,amssymb,amsfonts}",
                "\\usepackage{geometry}",
                "\\geometry{a4paper, margin=2.5cm}",
                "\\usepackage{hyperref}",
                "\\usepackage{graphicx}",
                "\\usepackage{authblk}",
                "\\usepackage{xcolor}",
                "",
                f"\\title{{{self._escape_latex(title)}}}",
                "\\author{A.M.Y Computational Research System\\\\",
                "\\small AXIOM Atlas Platform, Autonomous Computational Research}",
                "\\date{\\today}",
                "",
                "\\begin{document}",
                "\\maketitle",
                "",
                "\\begin{abstract}",
                self._escape_latex(abstract),
                "\\end{abstract}",
                "",
            ]

            for sec in sections:
                heading = sec.get("heading", "")
                content = sec.get("content", "")
                if heading:
                    lines.append(f"\\section{{{self._escape_latex(heading)}}}")
                
                in_list = False
                for para in content.split("\n\n"):
                    para = para.strip()
                    if not para:
                        continue
                    if para.startswith("- ") or para.startswith("* "):
                        if not in_list:
                            lines.append("\\begin{itemize}")
                            in_list = True
                        for item in para.split("\n"):
                            item = item.lstrip("-* ").strip()
                            if item:
                                lines.append(f"\\item {self._escape_latex(item)}")
                    else:
                        if in_list:
                            lines.append("\\end{itemize}")
                            in_list = False
                        lines.append(self._escape_latex(para))
                        lines.append("")
                
                if in_list:
                    lines.append("\\end{itemize}")
                    lines.append("")
                lines.append("")

            for figure in (publication_artifacts or {}).get("figures", []):
                figure_path = str(figure.get("display_path") or figure.get("path", ""))
                caption = str(figure.get("caption", ""))
                if figure_path:
                    lines += [
                        "\\begin{figure}[htbp]",
                        "\\centering",
                        f"\\includegraphics[width=0.95\\linewidth]{{\\detokenize{{{figure_path}}}}}",
                        f"\\caption{{{self._escape_latex(caption)}}}",
                        "\\end{figure}",
                        "",
                    ]

            if references:
                lines.append("\\begin{thebibliography}{99}")
                for i, ref in enumerate(references, 1):
                    lines.append(f"\\bibitem{{ref{i}}} {self._escape_latex(ref)}")
                lines.append("\\end{thebibliography}")

            lines.append("\\end{document}")
            
            tex_content = "\n".join(lines)
            tex_path.write_text(tex_content, encoding="utf-8")
            log.info("paper_generator.latex_written", path=str(tex_path))
            return True
        except Exception as e:
            log.error("paper_generator.latex_error", error=str(e))
            return False

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape LaTeX-special characters so the generated .tex compiles.

        Escapes the full special set, not just % & # — scientific prose routinely
        contains _ ^ ~ $ { } and \\ (subscripts E_n, powers n^2, set braces),
        and an unescaped one breaks compilation ("Missing $ inserted", undefined
        control sequence, etc.). Backslash is escaped FIRST so we don't mangle
        the replacements we introduce, and the markdown bold/italic substitution
        runs LAST so its own \\textbf{...} braces stay functional.
        """
        replacements = [
            ("\\", r"\textbackslash{}"),  # must be first
            ("{", r"\{"),
            ("}", r"\}"),
            ("$", r"\$"),
            ("&", r"\&"),
            ("%", r"\%"),
            ("#", r"\#"),
            ("_", r"\_"),
            ("^", r"\textasciicircum{}"),
            ("~", r"\textasciitilde{}"),
        ]
        for old, new in replacements:
            text = text.replace(old, new)

        # Replace Markdown bold/italic (after escaping, so these braces survive).
        text = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"\*([^*]+)\*", r"\\textit{\1}", text)
        return text

    async def generate_from_llm(
        self,
        topic: str,
        knowledge_facts: list[dict],
        recent_thoughts: list[str],
        breakthrough_content: str = "",
        tool_sections: list[dict] | None = None,
        experiment_ids: list[str] | None = None,
        literature_papers: list[dict] | None = None,
    ) -> dict:
        """
        Use the LLM to structure and write the paper content,
        then render it. Called by A.M.Y when she decides to write a paper.
        """
        if not self.reasoning:
            log.error("paper_generator.no_reasoning_engine")
            return {"error": "No reasoning engine attached"}

        facts_text = "\n".join(
            f"- {f.get('subject','')} {f.get('predicate','')} {f.get('object','')} (conf={float(f.get('confidence',0)):.0%})"
            for f in knowledge_facts[:30]
        )
        thoughts_text = "\n".join(f"- {t}" for t in recent_thoughts[-10:])

        # Include tool results in the prompt
        tools_text = ""
        if tool_sections:
            tools_text = "\n\nComputational Evidence:\n" + "\n\n".join(
                f"### {s['heading']}\n{s['content']}" for s in tool_sections
            )

        # Include real literature references in the prompt
        literature_text = ""
        if literature_papers:
            lit_lines = ["\n\nReal literature references found (use these as citations in the paper):"]
            for i, p in enumerate(literature_papers[:6], 1):
                title = p.get("title", "Unknown")
                authors = p.get("authors", "")
                year = p.get("year", "")
                venue = p.get("venue", "")
                if isinstance(authors, list):
                    authors = ", ".join(str(a) for a in authors[:3])
                lit_lines.append(f"  [{i}] {authors} ({year}). {title}. {venue}.")
            literature_text = "\n".join(lit_lines)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are A.M.Y's scientific writing engine. "
                    "Structure research findings into a rigorous academic paper. "
                    "Be specific, cite evidence, avoid vague claims. "
                    "Include computational verification results as evidence. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research topic: {topic}\n\n"
                    f"Established facts:\n{facts_text}\n\n"
                    f"Recent synthesis thoughts:\n{thoughts_text}\n\n"
                    f"Key breakthrough:\n{breakthrough_content[:600]}\n"
                    f"{tools_text}"
                    f"{literature_text}\n\n"
                    "Write a structured academic paper. Use the real literature references above as citations. "
                    "Return JSON:\n"
                    "{\n"
                    '  "title": "specific paper title",\n'
                    '  "abstract": "250-word abstract",\n'
                    '  "sections": [\n'
                    '    {"heading": "Introduction", "content": "..."},\n'
                    '    {"heading": "Methods", "content": "..."},\n'
                    '    {"heading": "Results", "content": "..."},\n'
                    '    {"heading": "Discussion", "content": "..."},\n'
                    '    {"heading": "Conclusion", "content": "..."}\n'
                    "  ],\n"
                    '  "references": ["Author et al. (year). Title. Journal.", ...]\n'
                    "}"
                ),
            },
        ]

        try:
            from cognition.reasoning import _clean_json, _extract_content

            if not getattr(self.reasoning, "client", None):
                return await self._generate_from_structured_fallback(
                    topic=topic,
                    knowledge_facts=knowledge_facts,
                    recent_thoughts=recent_thoughts,
                    breakthrough_content=breakthrough_content,
                    tool_sections=tool_sections,
                    experiment_ids=experiment_ids,
                    literature_papers=literature_papers,
                )

            response = await self.reasoning.client.chat(
                model=self.reasoning.reasoner_model,
                messages=messages,
                temperature=0.5,
                max_tokens=4096,
                format_json=True,
            )
            raw = _extract_content(response)
            raw = _clean_json(raw)
            data = json.loads(raw)

            # Inject tool sections into results if provided
            sections = data.get("sections", [])
            if tool_sections:
                # Find Results section or append
                results_idx = next((i for i, s in enumerate(sections) if "result" in s.get("heading", "").lower()), -1)
                if results_idx >= 0:
                    for ts in tool_sections:
                        sections.insert(results_idx + 1, ts)
                else:
                    sections.extend(tool_sections)

            return await self.generate_paper(
                title=data["title"],
                abstract=data["abstract"],
                sections=sections,
                references=data.get("references", []),
                knowledge_facts=knowledge_facts,
                experiment_ids=experiment_ids,
            )
        except Exception as e:
            log.error("paper_generator.llm_error", error=str(e))
            return {"error": str(e)}

    async def _generate_from_structured_fallback(
        self,
        topic: str,
        knowledge_facts: list[dict],
        recent_thoughts: list[str],
        breakthrough_content: str = "",
        tool_sections: list[dict] | None = None,
        experiment_ids: list[str] | None = None,
        literature_papers: list[dict] | None = None,
    ) -> dict:
        """Generate a deterministic paper when no model client is available."""
        title = topic.strip() or "A.M.Y Computational Research Report"
        facts = knowledge_facts or []
        tool_sections = tool_sections or []
        experiment_ids = experiment_ids or []
        literature_papers = literature_papers or []

        tool_count = len(tool_sections)
        experiment_count = len(experiment_ids)
        abstract = (
            f"This manuscript reports a deterministic computational verification study on {title}. "
            f"The workflow used {tool_count} computational evidence section(s) and cites "
            f"{experiment_count} provenance-tracked experiment record(s). Claims are limited to "
            "the recorded tool outputs and are intended as reproducible calibration evidence, "
            "not as a peer-reviewed discovery claim."
        )

        facts_text = "\n".join(
            f"- {fact.get('subject', '')} {fact.get('predicate', '')} {fact.get('object', '')} "
            f"(confidence={float(fact.get('confidence', 0.0)):.0%})"
            for fact in facts[:20]
        ) or "No additional semantic facts were available beyond the recorded tool outputs."
        thoughts_text = "\n".join(f"- {thought}" for thought in recent_thoughts[-8:])
        if not thoughts_text:
            thoughts_text = "- No recent synthesis thoughts were available."

        sections = [
            {
                "heading": "Introduction",
                "content": (
                    f"The study addresses {title}. A.M.Y generated this report from recorded "
                    "computational observations, preserving the distinction between calibration "
                    "results and novel scientific claims."
                ),
            },
            {
                "heading": "Methods",
                "content": (
                    "A.M.Y executed Atlas scientific tools, stored each successful output with "
                    "SHA-256 provenance, and then synthesized the resulting evidence into an "
                    "IMRaD manuscript. The synthesis used deterministic fallback writing because "
                    "no model-backed writing client was available in this runtime."
                ),
            },
            {
                "heading": "Results",
                "content": "\n\n".join(
                    section.get("content", "") for section in tool_sections
                ) or "No tool output was available for the Results section.",
            },
            {
                "heading": "Discussion",
                "content": (
                    f"Recent synthesis context:\n{thoughts_text}\n\n"
                    f"Recorded facts:\n{facts_text}\n\n"
                    f"Breakthrough or summary signal: {breakthrough_content or 'none recorded'}.\n\n"
                    "These results support only the narrow computational checks shown above. "
                    "Alternative explanations include tool implementation assumptions, finite "
                    "sample limitations, and environment-specific execution behavior."
                ),
            },
            {
                "heading": "Conclusion",
                "content": (
                    "A.M.Y produced a reproducible computational report with explicit provenance. "
                    "The result is suitable for audit and follow-up testing, but it should not be "
                    "treated as an independently peer-reviewed scientific result."
                ),
            },
        ]

        references = []
        for paper in literature_papers[:6]:
            title_part = paper.get("title", "Untitled")
            authors = paper.get("authors", "")
            year = paper.get("year", "")
            venue = paper.get("venue", "")
            if isinstance(authors, list):
                authors = ", ".join(str(author) for author in authors[:3])
            references.append(f"{authors} ({year}). {title_part}. {venue}.")

        return await self.generate_paper(
            title=title,
            abstract=abstract,
            sections=sections,
            references=references,
            knowledge_facts=knowledge_facts,
            experiment_ids=experiment_ids,
        )


def _safe_para(text: str) -> str:
    """Escape special chars for ReportLab paragraphs."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Keep Python/math operators such as 3*x**2 literal; ReportLab accepts a
    # small XML subset, so over-eager Markdown conversion can create crossed tags.
    text = re.sub(
        r"(?<![A-Za-z0-9])\*\*(\S(?:.*?\S)?)\*\*(?![A-Za-z0-9])",
        r"<b>\1</b>",
        text,
    )
    return text
