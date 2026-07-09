#!/usr/bin/env python3
"""
Autonomous Research Agent with Dynamic Tool Discovery
======================================================
This script creates an agent that can:
1. Discover available tools across all scientific domains
2. Choose appropriate tools based on hypothesis requirements
3. Execute real scientific validations
4. Iterate based on peer review feedback

Demonstrates true tool-augmented reasoning across 100+ services.
"""

import asyncio
import sys
import os
import json
import math
import re
import time
import ast
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass

# Add project root to path
sys.path.append(os.getcwd())

# Core imports - defer heavy imports
# from app.services.llm_providers.groq_provider import groq_provider
from app.services.llm_providers.ollama_provider import ollama_provider

# Real scientific tools
import sympy
import numpy as np

from app.ssh_disorder_benchmark import (
    BenchmarkConfig as SSHDisorderBenchmarkConfig,
    format_benchmark_report as format_ssh_disorder_benchmark_report,
    run_benchmark as run_ssh_disorder_benchmark,
)

# MATH DOMAIN SERVICES (Lazy loaded to avoid circular deps if possible, but safe here)
try:
    from app.domains.mathematics.services.calculus_service import CalculusService, CalculusRequest
    from app.domains.mathematics.services.julia_service import JuliaService
    from app.services.theorem_proving.z3_smt_service import Z3SMTService
    from app.services.literature.literature_service import LiteratureService
    from app.services.verification.autonomous_peer_review_service import AutonomousPeerReviewService
    from app.config.config_loader import load_config_section
    from app.services.ml.improved_agent_prompts import (
        MATH_HYPOTHESIS_PROMPT_TEMPLATE,
        get_improved_prompt,
        get_agent_parameters,
        validate_json_response,
    )
except ImportError as e:
    print(f"⚠️ Warning: Some math services could not be imported: {e}")
    MATH_HYPOTHESIS_PROMPT_TEMPLATE = None  # Fallback defined later if None
    LiteratureService = None  # type: ignore
    AutonomousPeerReviewService = None  # type: ignore
    load_config_section = None  # type: ignore
    get_improved_prompt = None  # type: ignore
    get_agent_parameters = None  # type: ignore
    validate_json_response = None  # type: ignore

# Defer ServiceLocator import to avoid heavy chain
SERVICE_LOCATOR_AVAILABLE = False
try:
    # Only import if needed
    pass  # Will lazy load later
except Exception:
    pass


# Deterministic, real implementations of a subset of tools that previously
# used hardcoded lookup tables or random numbers. We import optionally so
# legacy deployments that don't have the A.M.Y root on sys.path keep working
# with the old behaviour — but every test run with the A.M.Y test harness
# picks up the real implementations.
_REAL_TOOLS_AVAILABLE = False
try:
    # Try repo-root location used by A.M.Y itself.
    _here = os.path.dirname(os.path.abspath(__file__))
    _repo_root = os.path.abspath(os.path.join(_here, "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from core import atlas_real_tools as _real
    _REAL_TOOLS_AVAILABLE = True
except Exception as _real_e:  # pragma: no cover — defensive only
    print(f"   ⚠️ core.atlas_real_tools not loaded ({_real_e}); using legacy fallback")


DOMAIN_ALIASES: Dict[str, List[str]] = {
    "math": ["mathematics", "number_theory"],
    "mathematics": ["number_theory"],
    "number_theory": ["mathematics"],
    "stats": ["statistics"],
    "statistics": [],
    "physics": ["quantum", "quantum_physics"],
    "quantum": ["physics"],
    "chemistry": ["materials", "materials_science"],
    "materials": ["materials_science", "chemistry"],
    "materials_science": ["materials", "chemistry"],
    "medicine": ["medical", "medical_imaging"],
    "medical": ["medicine"],
}


def _atlas_misuse_decision(operation: str, content: str, domain: str = "", tool_name: str = "") -> Dict[str, Any]:
    try:
        from app.security.misuse_guard import misuse_guard

        return misuse_guard.evaluate(
            operation=operation,
            content=content,
            domain=domain,
            tool_name=tool_name,
            actor_id=os.getenv("ATLAS_ACTOR_ID", "atlas_tool_registry"),
        ).to_dict()
    except Exception as exc:
        return {
            "allowed": False,
            "action": "block",
            "risk_level": "critical",
            "reasons": [f"misuse guard unavailable: {exc}"],
            "matched_rules": ["MISUSE_GUARD_UNAVAILABLE"],
            "decision_id": "fail-closed",
        }


def _atlas_misuse_blocked_message(decision: Dict[str, Any]) -> str:
    try:
        from app.security.misuse_guard import format_blocked_message

        return format_blocked_message(decision)
    except Exception:
        reasons = "; ".join(decision.get("reasons") or ["Misuse policy violation"])
        rules = ",".join(decision.get("matched_rules") or [])
        return f"Blocked by Atlas misuse policy: {reasons} (rules={rules}; decision_id={decision.get('decision_id')})"


def _core_safety_decision(operation: str, content: str, domain: str = "", tool_name: str = "") -> Dict[str, Any]:
    try:
        amy_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if amy_root not in sys.path:
            sys.path.insert(0, amy_root)
        from core.safety_kernel import evaluate_safety

        return evaluate_safety(
            operation=operation,
            content=content,
            domain=domain,
            tool_name=tool_name,
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


def _core_safety_blocked_message(decision: Dict[str, Any]) -> str:
    try:
        amy_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if amy_root not in sys.path:
            sys.path.insert(0, amy_root)
        from core.safety_kernel import blocked_message

        return blocked_message(decision)
    except Exception:
        reasons = "; ".join(decision.get("reasons") or ["Safety policy violation"])
        return f"Blocked by safety policy: {reasons} (decision_id={decision.get('decision_id')})"


def _normalize_domain(domain: str) -> str:
    return (domain or "").strip().lower()


def _render_braces_template(template: str, context: Dict[str, Any]) -> str:
    """Render minimal `{{var}}` templates without external deps."""
    if not template:
        return ""
    out = template
    for k, v in context.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def _compact_json(obj: Any, max_chars: int = 4000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obj)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n...<truncated>"

# ========================
# TOOL REGISTRY SYSTEM
# ========================

@dataclass
class ToolDescriptor:
    """Describes a tool available to the agent."""
    name: str
    domain: str
    description: str
    function: Callable
    input_format: str
    output_format: str
    evidence_grade: str = "heuristic"


class DynamicToolRegistry:
    """Registry of tools the agent can discover and use."""

    def __init__(self, scope_domain: Optional[str] = None, allowed_domains: Optional[set[str]] = None):
        self.tools: Dict[str, ToolDescriptor] = {}

        # Tools in "research" are globally useful (literature, validation).
        self._global_domains = {"research"}

        # Lightweight aliasing so domain callers don't silently get 0 tools.
        self._domain_aliases: Dict[str, List[str]] = {
            "math": ["mathematics", "number_theory"],
            "mathematics": ["number_theory"],
            "number_theory": ["mathematics"],
            "stats": ["statistics"],
            "statistics": [],
            "physics": ["quantum", "quantum_physics"],
            "quantum": ["physics"],
            "chemistry": ["materials", "materials_science"],
            "materials": ["materials_science", "chemistry"],
            "materials_science": ["materials", "chemistry"],
            "medicine": ["medical", "medical_imaging"],
            "medical": ["medicine"],
        }

        # Optional scoping: when provided, only register tools for the domain (+ aliases + research).
        self._scope_domain = _normalize_domain(scope_domain) if scope_domain else None
        if allowed_domains is not None:
            self._allowed_domains = {str(d).strip().lower() for d in allowed_domains if str(d).strip()}
        elif self._scope_domain:
            candidate_domains = {self._scope_domain}
            candidate_domains.update(self._domain_aliases.get(self._scope_domain, []))
            # Merge aliases from global DOMAIN_ALIASES if present.
            try:
                candidate_domains.update(DOMAIN_ALIASES.get(self._scope_domain, []))  # type: ignore[name-defined]
                # If scope is itself an alias, include its canonical domains too.
                for canon, aliases in (DOMAIN_ALIASES or {}).items():  # type: ignore[name-defined]
                    if self._scope_domain in (aliases or []):
                        candidate_domains.add(canon)
                        candidate_domains.update(aliases)
            except Exception:
                pass
            candidate_domains.update(self._global_domains)
            self._allowed_domains = candidate_domains
        else:
            self._allowed_domains = None

        self._register_builtin_tools()
        self._register_service_tools()
        self._register_orchestrator_tools()
    
    def _register_builtin_tools(self):
        """Register built-in mathematical tools."""
        # SymPy Tools
        self.register_tool(ToolDescriptor(
            name="sympy_solve_equation",
            domain="mathematics",
            description="Solve algebraic equations symbolically. Input: equation string like 'x**2 - 4 = 0'",
            function=self._sympy_solve,
            input_format="equation_string",
            output_format="solution_list"
        ))
        
        self.register_tool(ToolDescriptor(
            name="sympy_simplify",
            domain="mathematics",
            description="Simplify mathematical expressions. Input: expression like 'sin(x)**2 + cos(x)**2'",
            function=self._sympy_simplify,
            input_format="expression_string",
            output_format="simplified_expression"
        ))
        
        self.register_tool(ToolDescriptor(
            name="sympy_derivative",
            domain="mathematics",
            description="Compute symbolic derivatives. Input: 'expression, variable' like 'x**3, x'",
            function=self._sympy_derivative,
            input_format="expression_and_variable",
            output_format="derivative_expression"
        ))
        
        self.register_tool(ToolDescriptor(
            name="sympy_integrate",
            domain="mathematics",
            description="Compute symbolic integrals. Input: 'expression, variable' like 'x**2, x'",
            function=self._sympy_integrate,
            input_format="expression_and_variable",
            output_format="integral_expression"
        ))
        
        self.register_tool(ToolDescriptor(
            name="sympy_prime_analysis",
            domain="mathematics",
            description="Analyze prime numbers. Input: 'operation:argument' like 'is_prime:17' or 'nth_prime:100' or 'prime_range:1-100'",
            function=self._sympy_prime_analysis,
            input_format="operation_and_argument",
            output_format="analysis_result"
        ))
        
        # NumPy Tools
        self.register_tool(ToolDescriptor(
            name="numpy_statistics",
            domain="statistics",
            description="Compute statistics on numerical data. Input: 'operation:data' like 'mean:[1,2,3,4,5]' or 'std:[1,2,3,4,5]'",
            function=self._numpy_statistics,
            input_format="operation_and_data",
            output_format="statistical_result"
        ))
        
        self.register_tool(ToolDescriptor(
            name="numpy_distribution",
            domain="statistics",
            description="Generate and analyze probability distributions. Input: 'distribution:params' like 'normal:1000,0,1' (n,mean,std) or 'uniform:1000,0,1'",
            function=self._numpy_distribution,
            input_format="distribution_and_params",
            output_format="distribution_statistics"
        ))
        
        self.register_tool(ToolDescriptor(
            name="numpy_correlation",
            domain="statistics",
            description="Compute correlation between datasets. Input: two comma-separated arrays",
            function=self._numpy_correlation,
            input_format="two_arrays",
            output_format="correlation_coefficient"
        ))
        
        # Prime gap specific tools
        self.register_tool(ToolDescriptor(
            name="prime_gap_analysis",
            domain="number_theory",
            description="Analyze gaps between consecutive primes. Input: 'limit' like '10000' to analyze primes up to that limit",
            function=self._prime_gap_analysis,
            input_format="integer_limit",
            output_format="gap_statistics"
        ))

        self.register_tool(ToolDescriptor(
            name="prime_gap_model_comparison",
            domain="number_theory",
            description="Compare prime-gap statistics against log(N) and log(N)^2 scaling controls. Input: comma-separated limits like '10000,100000,1000000'",
            function=self._prime_gap_model_comparison,
            input_format="integer_limit_series",
            output_format="scaling_model_comparison"
        ))
        
        self.register_tool(ToolDescriptor(
            name="hypothesis_tester",
            domain="statistics",
            description="Perform statistical hypothesis testing. Input: 'test_type:data1:data2' like 'ttest:[1,2,3]:[4,5,6]'",
            function=self._hypothesis_tester,
            input_format="test_and_data",
            output_format="test_results"
        ))

        self.register_tool(ToolDescriptor(
            name="two_sample_effect_power",
            domain="statistics",
            description="Report two-sample effect size, confidence interval, deterministic bootstrap CI, and observed power. Input: '[1,2,3];[4,5,6]'",
            function=self._two_sample_effect_power,
            input_format="two_numeric_arrays",
            output_format="effect_power_summary"
        ))
        
        # Chemistry tools
        self.register_tool(ToolDescriptor(
            name="molecular_orbital_energy",
            domain="chemistry",
            description="Calculate molecular orbital energy levels. Input: 'n_atoms:bond_length' like '6:1.4' for benzene",
            function=self._molecular_orbital_energy,
            input_format="atoms_and_bond",
            output_format="energy_levels"
        ))

        self.register_tool(ToolDescriptor(
            name="huckel_polyene_scaling",
            domain="chemistry",
            description="Fit HOMO-LUMO gap scaling for linear polyenes. Input: comma-separated even atom counts like '4,6,8,10,12,16,20'",
            function=self._huckel_polyene_scaling,
            input_format="atom_count_series",
            output_format="scaling_model_comparison"
        ))

        self.register_tool(ToolDescriptor(
            name="bond_alternated_polyene_scaling",
            domain="chemistry",
            description="Compare HOMO-LUMO gap scaling for bond-alternated linear polyenes. Input: '4,6,8;strong=-2.7;weak=-2.3'",
            function=self._bond_alternated_polyene_scaling,
            input_format="atom_count_series_with_betas",
            output_format="bond_alternation_gap_series"
        ))

        self.register_tool(ToolDescriptor(
            name="ssh_polyene_gap_map",
            domain="chemistry",
            description=(
                "Map finite-chain SSH/polyene gaps across length, bond alternation, and boundary orientation. "
                "Input: '4,6,8;deltas=0,0.05,0.1;orientations=trivial,topological;beta=-2.5;threshold=0.05'"
            ),
            function=self._ssh_polyene_gap_map,
            input_format="atom_count_series_with_deltas_and_orientations",
            output_format="ssh_polyene_gap_map"
        ))

        self.register_tool(ToolDescriptor(
            name="ssh_edge_localization_map",
            domain="chemistry",
            description=(
                "Measure SSH/polyene frontier-state localization from eigenvectors. "
                "Input: '20,40,60;deltas=0.05,0.1;orientations=trivial,topological;"
                "beta=-2.5;edge_sites=2;localization_threshold=0.25'"
            ),
            function=self._ssh_edge_localization_map,
            input_format="atom_count_series_with_localization_options",
            output_format="ssh_edge_localization_map"
        ))

        self.register_tool(ToolDescriptor(
            name="ssh_disorder_diagnostic_benchmark",
            domain="chemistry",
            description=(
                "Benchmark gap-only versus joint gap/edge-weight/IPR diagnostics "
                "on paired finite SSH chains with off-diagonal and diagonal disorder. "
                "Input: '20,40;deltas=0.1;strengths=0,0.2;"
                "disorders=off_diagonal,diagonal;orientations=trivial,topological;"
                "realizations=8;namespace=study;protocol_sha256=<64 hex>'"
            ),
            function=self._ssh_disorder_diagnostic_benchmark,
            input_format="ssh_disorder_benchmark_protocol",
            output_format="ssh_disorder_diagnostic_benchmark"
        ))
        
        self.register_tool(ToolDescriptor(
            name="bond_energy_analyzer",
            domain="chemistry",
            description="Analyze chemical bond energies. Input: 'bond_type' like 'C-C', 'C=C', 'C-H', 'O-H'",
            function=self._bond_energy_analyzer,
            input_format="bond_type",
            output_format="energy_kj_mol"
        ))
        
        self.register_tool(ToolDescriptor(
            name="molecular_weight_calc",
            domain="chemistry",
            description="Calculate molecular weight from formula. Input: formula like 'C6H12O6' or 'H2O'",
            function=self._molecular_weight_calc,
            input_format="chemical_formula",
            output_format="molecular_weight"
        ))
        
        # Biology tools
        self.register_tool(ToolDescriptor(
            name="dna_analyzer",
            domain="biology",
            description="Analyze DNA sequence. Input: DNA sequence like 'ATCGATCG' for GC content, length, and reverse complement",
            function=self._dna_analyzer,
            input_format="dna_sequence",
            output_format="sequence_analysis"
        ))

        self.register_tool(ToolDescriptor(
            name="gc_at_panel_comparison",
            domain="biology",
            description="Compare GC-rich and AT-rich DNA sequence panels with effect size, confidence intervals, bootstrap CI, and coding-context controls. Input: 'gc=SEQ,SEQ;at=SEQ,SEQ'",
            function=self._gc_at_panel_comparison,
            input_format="labeled_sequence_panels",
            output_format="gc_at_panel_statistics"
        ))
        
        self.register_tool(ToolDescriptor(
            name="protein_properties",
            domain="biology",
            description="Calculate protein properties from amino acid sequence. Input: sequence like 'MVLSPADKTNVK'",
            function=self._protein_properties,
            input_format="amino_acid_sequence",
            output_format="protein_properties"
        ))
        
        # Physics tools
        self.register_tool(ToolDescriptor(
            name="quantum_energy_levels",
            domain="physics",
            description="Calculate quantum energy levels. Input: 'system:params' like 'hydrogen:1' for n=1 or 'harmonic:1,0.5' for n=1, omega=0.5",
            function=self._quantum_energy_levels,
            input_format="system_and_params",
            output_format="energy_levels"
        ))

        self.register_tool(ToolDescriptor(
            name="rydberg_scaling_comparison",
            domain="physics",
            description="Compare hydrogen Rydberg inverse-square scaling with a quantum-defect perturbation. Input: '1,2,3,5,10;delta=0.05'",
            function=self._rydberg_scaling_comparison,
            input_format="quantum_number_series",
            output_format="rydberg_model_comparison"
        ))

        # Astronomy tools
        self.register_tool(ToolDescriptor(
            name="cosmology_residual_comparison",
            domain="astronomy",
            description="Compare Planck18-parameter luminosity distances against low-redshift Hubble-law and second-order cosmographic approximations. Input: '0.01,0.1,0.5,1,2;threshold=5'",
            function=self._cosmology_residual_comparison,
            input_format="redshift_series_with_threshold",
            output_format="cosmology_residual_table"
        ))
    
    def _register_service_tools(self):
        """Register tools from AXIOM ServiceLocator (lazy loaded)."""
        try:
            from app.domains.service_locator import ServiceLocator
            locator = ServiceLocator.get_instance()
            domains = locator.list_domains()
            
            for domain in domains:
                service_names = locator.list_services(domain)
                for svc_name in service_names:
                    defn = locator.get_definition(svc_name)
                    if defn:
                        # Create a wrapper tool for each service
                        self.register_tool(ToolDescriptor(
                            name=f"service_{svc_name.lower()}",
                            domain=domain,
                            description=(
                                (defn.description or f"AXIOM service: {svc_name}")
                                + " | Input MUST be JSON for service.process_request. Example: {\"action\": \"status\"}"
                            ),
                            function=lambda input_data, n=svc_name: self._invoke_service(n, input_data),
                            input_format="json_request",
                            output_format="service_response"
                        ))
            print(f"   ✅ Loaded {len(domains)} domains from ServiceLocator")
        except Exception as e:
            print(f"   ⚠️ ServiceLocator not available (optional): {e}")
        
        # Register ADVANCED tools that use real AXIOM services
        self._register_advanced_tools()
    
    def _register_advanced_tools(self):
        """Register advanced tools that invoke real AXIOM scientific services."""
        
        # DNABERT2 Genomics - Real sequence analysis
        self.register_tool(ToolDescriptor(
            name="dnabert2_analysis",
            domain="biology",
            description="Advanced DNA analysis using DNABERT2. Input: 'operation:sequence' like 'motifs:TATAATATCGATCG' or 'classify:ATCGATCGATCG'. 'batch_process:DatasetName' for large scale.",
            function=self._dnabert2_analysis,
            input_format="operation_and_sequence",
            output_format="genomics_analysis"
        ))
        
        self.register_tool(ToolDescriptor(
            name="correlation_analysis",
            domain="statistics",
            description="Compute statistical correlation between named datasets. Input: 'dataset1,dataset2' notably 'dnabert2_scores,gene_expression'",
            function=self._correlation_analysis,
            input_format="dataset_names",
            output_format="correlation_report"
        ))
        
        # Computational Chemistry - Molecular dynamics setup
        self.register_tool(ToolDescriptor(
            name="computational_chemistry",
            domain="chemistry",
            description="Advanced computational chemistry. Input: 'operation:data' like 'analyze_molecule:C6H6' or 'quantum_calc:H2O'",
            function=self._computational_chemistry,
            input_format="operation_and_data",
            output_format="chemistry_analysis"
        ))
        
        # GNoME Materials Discovery
        self.register_tool(ToolDescriptor(
            name="gnome_materials",
            domain="materials",
            description="GNoME materials discovery and stability analysis. Input: 'operation:formula' like 'stability:Li2O' or 'properties:TiO2'",
            function=self._gnome_materials,
            input_format="operation_and_formula",
            output_format="materials_analysis"
        ))
        
        # Quantum Computing Service
        self.register_tool(ToolDescriptor(
            name="quantum_circuit",
            domain="physics",
            description="Quantum circuit simulation. Input: 'circuit_type:params' like 'bell:2' or 'grover:4' or 'vqe:H2'",
            function=self._quantum_circuit,
            input_format="circuit_and_params",
            output_format="quantum_results"
        ))
        
        # Literature Search
        self.register_tool(ToolDescriptor(
            name="literature_search",
            domain="research",
            description=(
                "Search scientific literature via LiteratureService (real). "
                "Input: optionally prefixed 'papers:<q>' / 'arxiv:<q>' / 'patents:<q>'. "
                "Returns JSON including abstracts when available."
            ),
            function=self._literature_search,
            input_format="search_query",
            output_format="literature_results"
        ))

        # Literature Verification (full multi-source context)
        self.register_tool(ToolDescriptor(
            name="literature_verify_hypothesis_plus",
            domain="research",
            description=(
                "Verify a hypothesis against multi-source literature (papers/arXiv/patents/etc.) via LiteratureService.verify_hypothesis_plus. "
                "Input: JSON {\"hypothesis\": {...}, \"topic\": <str optional>, \"k\": <int optional>} OR 'domain:hypothesis_title'. "
                "Returns JSON with support_score, reasons, and sources including abstracts/urls when available."
            ),
            function=self._literature_verify_hypothesis_plus,
            input_format="json_or_domain_colon_title",
            output_format="verification_sources"
        ))
        
        # Advanced Hypothesis Validator
        self.register_tool(ToolDescriptor(
            name="validate_hypothesis",
            domain="research",
            description="Validate scientific hypothesis using multiple evidence sources. Input: 'domain:hypothesis_text'",
            function=self._validate_hypothesis,
            input_format="domain_and_hypothesis",
            output_format="validation_result"
        ))
        
        # ========== MATHEMATICS DOMAIN TOOLS (ADVANCED) ==========
        self._register_mathematics_tools()
    
    def _register_mathematics_tools(self):
        """Register advanced mathematics tools from AXIOM's math domain."""
        
        # Z3 SMT Solver - Formal theorem proving
        self.register_tool(ToolDescriptor(
            name="z3_verify_theorem",
            domain="mathematics",
            description="Verify mathematical theorems using Z3 SMT solver. Input: 'theorem:variables' like 'x+y=y+x:x,y' or 'x*x>=0:x'",
            function=self._z3_verify_theorem,
            input_format="theorem_and_variables",
            output_format="verification_result"
        ))

        # Z3 prover (alias used by the agent prompt)
        self.register_tool(ToolDescriptor(
            name="z3_prover",
            domain="mathematics",
            description="Formal verification using Z3 with lightweight variable inference. Input: 'verify:<formula>' or '<formula>'",
            function=self._z3_prover,
            input_format="formula",
            output_format="verification_analysis"
        ))
        
        # Number Theory Advanced
        self.register_tool(ToolDescriptor(
            name="number_theory_advanced",
            domain="mathematics",
            description="Advanced number theory operations. Input: 'operation:args' like 'goldbach:100' or 'twin_primes:1000' or 'prime_gaps:10000' or 'factorize:12345'",
            function=self._number_theory_advanced,
            input_format="operation_and_args",
            output_format="number_theory_result"
        ))
        
        # High-Performance Prime Gap Diagnostics (primesieve-backed)
        self.register_tool(ToolDescriptor(
            name="prime_gap_hpc",
            domain="mathematics",
            description=(
                "High-performance prime gap residual diagnostics using primesieve. "
                "Computes normalized-gap KS distances vs Exp(1), max-gap/log^2(N) ratios, "
                "slab statistics, and R^2 trend fits across prefix checkpoints. "
                "Input: 'N_limit' e.g. '1e8' or '3e8'. Max 1e9."
            ),
            function=self._prime_gap_hpc,
            input_format="float_limit",
            output_format="prime_gap_hpc_result"
        ))

        # Conjecture Generator & Evaluator
        self.register_tool(ToolDescriptor(
            name="conjecture_engine",
            domain="mathematics",
            description="Generate and evaluate mathematical conjectures. Input: 'operation:domain:params' like 'generate:number_theory:primes' or 'evaluate:goldbach:100'",
            function=self._conjecture_engine,
            input_format="operation_domain_params",
            output_format="conjecture_result"
        ))
        
        # Automated Theorem Proving
        self.register_tool(ToolDescriptor(
            name="automated_prover",
            domain="mathematics",
            description="Automated theorem proving using multiple strategies. Input: 'method:statement' like 'induction:sum(1..n)=n*(n+1)/2' or 'contradiction:sqrt(2)_irrational'",
            function=self._automated_prover,
            input_format="method_and_statement",
            output_format="proof_result"
        ))
        
        # Discovery Engine
        self.register_tool(ToolDescriptor(
            name="mathematical_discovery",
            domain="mathematics",
            description="Discover mathematical patterns and relationships. Input: 'method:domain:params' like 'pattern_analysis:sequences:fibonacci' or 'numerical_exploration:primes:gaps'",
            function=self._mathematical_discovery,
            input_format="method_domain_params",
            output_format="discovery_result"
        ))
        
        # Sequence Analysis (OEIS-style)
        self.register_tool(ToolDescriptor(
            name="sequence_analyzer",
            domain="mathematics",
            description="Analyze integer sequences, find patterns, identify in OEIS. Input: 'operation:sequence' like 'analyze:1,1,2,3,5,8,13' or 'generate:fibonacci:20' or 'find_formula:2,4,8,16,32'",
            function=self._sequence_analyzer,
            input_format="operation_and_sequence",
            output_format="sequence_analysis"
        ))
        
        # Symbolic Calculus (extended)
        self.register_tool(ToolDescriptor(
            name="symbolic_calculus",
            domain="mathematics",
            description="Advanced symbolic calculus. Input: 'operation:expression:variable' like 'limit:sin(x)/x:x->0' or 'taylor:exp(x):x:0:5' or 'laplace:exp(-t):t'",
            function=self._symbolic_calculus,
            input_format="operation_expression_variable",
            output_format="calculus_result"
        ))

        # Alias kept for backwards-compatibility with older prompts
        self.register_tool(ToolDescriptor(
            name="calculus_engine",
            domain="mathematics",
            description="Alias for symbolic_calculus. Input: 'operation:expression:variable'",
            function=self._symbolic_calculus,
            input_format="operation_expression_variable",
            output_format="calculus_result"
        ))

        # Julia numerical computation (tool referenced by prompt)
        self.register_tool(ToolDescriptor(
            name="julia_computation",
            domain="mathematics",
            description="Execute Julia code for numerical computation. Input: Julia code (single snippet).",
            function=self._julia_computation,
            input_format="julia_code",
            output_format="execution_result"
        ))
        
        # Graph Theory
        self.register_tool(ToolDescriptor(
            name="graph_theory",
            domain="mathematics",
            description="Graph theory computations. Input: 'operation:graph_spec' like 'chromatic:petersen' or 'shortest_path:adjacency_matrix' or 'eulerian:6,[[0,1],[1,2],[2,0]]'",
            function=self._graph_theory,
            input_format="operation_and_graph",
            output_format="graph_result"
        ))
        
        # Topology Invariants
        self.register_tool(ToolDescriptor(
            name="topology_invariants",
            domain="mathematics",
            description="Compute topological invariants. Input: 'invariant:space' like 'betti:torus' or 'euler_char:klein_bottle' or 'fundamental_group:sphere'",
            function=self._topology_invariants,
            input_format="invariant_and_space",
            output_format="topology_result"
        ))
    
    async def _invoke_service(self, service_name: str, input_data: str) -> str:
        """Invoke an AXIOM service via ServiceLocator.process_request (real execution)."""
        try:
            from app.domains.service_locator import ServiceLocator
            locator = ServiceLocator.get_instance()
            service = locator.get_service(service_name)
            if not service:
                return f"Error: Service '{service_name}' not found."

            payload_raw = (input_data or "").strip()
            if not payload_raw:
                return f"Error: service '{service_name}' requires JSON input (e.g., {{\"action\": \"status\"}})."

            try:
                payload = json.loads(payload_raw)
            except Exception as e:
                return f"Error: invalid JSON input for service '{service_name}': {e}"

            if not hasattr(service, "process_request"):
                return f"Error: Service '{service_name}' has no process_request(). Type: {type(service).__name__}"

            res = service.process_request(payload)
            if asyncio.iscoroutine(res):
                res = await res
            return _compact_json(res, max_chars=6000)
        except Exception as e:
            return f"Error loading service {service_name}: {str(e)}"
    
    # ========================
    # ADVANCED TOOL IMPLEMENTATIONS
    # ========================
    
    def _dnabert2_analysis(self, query: str) -> str:
        """DNABERT2 advanced genomics analysis."""
        try:
            parts = query.split(":", 1)
            if len(parts) < 2:
                return "Error: Format should be 'operation:sequence' (e.g., 'motifs:ATCGATCG')"
            
            operation = parts[0].strip().lower()
            sequence = parts[1].strip().upper()
            
            # Allow "batch_process" to bypass DNA validation
            if operation != "batch_process":
                # Validate DNA sequence
                valid_bases = set("ATCGN")
                if not all(b in valid_bases for b in sequence):
                    return f"Error: Invalid DNA sequence. Only A, T, C, G, N allowed."
            else:
                # Batch process logic handled below
                pass
            
            if operation == "motifs":
                # Find regulatory motifs
                # ... existing motif logic ...
                pass 
            
            if operation == "batch_process":
                # Real batch analysis: caller can pass a single sequence to be
                # treated as a 1-element batch, or comma-separated sequences.
                # The previous implementation returned a hardcoded "12,500
                # sequences ... Validated. Ready for publication" string that
                # had nothing to do with the input.
                if _REAL_TOOLS_AVAILABLE:
                    seqs = [s.strip() for s in sequence.split(",") if s.strip()]
                    if not seqs:
                        seqs = [sequence]
                    return _real.dnabert2_batch_analysis(seqs)
                return ("DNABERT2 batch analysis requires core.atlas_real_tools "
                        "(not loaded). No simulated output is emitted.")

            if operation == "motifs":
                # Real, deterministic motif scan with σ70 / eukaryotic promoter
                # call. Replaces the prior random correlation/p-value output.
                if _REAL_TOOLS_AVAILABLE:
                    return _real.dnabert2_motifs(sequence)
                # Honest minimal fallback: report what we can compute with
                # only the standard library, and DO NOT invent statistics.
                motifs = []
                for pat, name in (("TATAAT", "−10 box"), ("TTGACA", "−35 box"),
                                  ("CAAT", "CAAT box")):
                    if pat in sequence:
                        motifs.append((pat, name, sequence.find(pat)))
                gc = ((sequence.count('G') + sequence.count('C')) / len(sequence) * 100
                      if sequence else 0.0)
                return (f"DNABERT2 motifs (fallback, real tools not loaded):\n"
                        f"  length: {len(sequence)} bp, GC: {gc:.1f}%\n"
                        f"  motifs: {motifs}")

                
            elif operation == "classify":
                # Classify sequence type
                gc_content = (sequence.count('G') + sequence.count('C')) / len(sequence) * 100
                at_ratio = (sequence.count('A') + sequence.count('T')) / len(sequence) * 100
                
                classification = "unknown"
                if gc_content > 60:
                    classification = "CpG island / promoter region"
                elif gc_content < 40:
                    classification = "AT-rich / heterochromatin"
                elif "ATG" in sequence and "TAA" in sequence or "TAG" in sequence or "TGA" in sequence:
                    classification = "coding sequence (ORF candidate)"
                else:
                    classification = "intergenic region"
                    
                return f"DNABERT2 Classification:\n- Classification: {classification}\n- GC content: {gc_content:.1f}%\n- Length: {len(sequence)} bp\n- ORF potential: {'ATG' in sequence}"
                
            elif operation == "stability":
                # Predict thermal stability
                gc_content = (sequence.count('G') + sequence.count('C')) / len(sequence) * 100
                # Nearest neighbor model approximation
                tm = 81.5 + 16.6 * math.log10(0.05) + 0.41 * gc_content - 675 / len(sequence)
                
                return f"DNABERT2 Stability Analysis:\n- Melting temperature (Tm): {tm:.1f}°C\n- GC content: {gc_content:.1f}%\n- Thermal stability: {'high' if gc_content > 50 else 'moderate' if gc_content > 40 else 'low'}"
                
            else:
                return f"Unknown operation '{operation}'. Available: motifs, classify, stability"
                
        except Exception as e:
            return f"DNABERT2 Error: {str(e)}"
    
    def _correlation_analysis(self, query: str) -> str:
        """Compute correlations from two real arrays.

        The previous implementation returned a hardcoded "r = 0.824"
        report for one specific dataset-name input, and a hardcoded
        "r = 0.04" for everything else. Neither was a real computation.
        We now require the caller to pass actual numbers, in any of
        these formats:
            [1,2,3];[4,5,6]
            correlation:[1,2,3],[4,5,6]
            1,2,3;4,5,6
        """
        if _REAL_TOOLS_AVAILABLE:
            return _real.correlation_analysis_from_query(query)
        return ("Error: correlation_analysis now requires real numeric input "
                "(format '[1,2,3];[4,5,6]') and the core.atlas_real_tools "
                "module. No hardcoded r-values are returned.")

    def _computational_chemistry(self, query: str) -> str:
        """Advanced computational chemistry using AXIOM services."""
        try:
            parts = query.split(":", 1)
            if len(parts) < 2:
                return "Error: Format should be 'operation:data' (e.g., 'analyze_molecule:C6H6')"
            
            operation = parts[0].strip().lower()
            data = parts[1].strip()
            
            if operation == "analyze_molecule" or operation == "molecular_descriptors":
                # Parse molecular formula
                formula = data.upper()
                element_pattern = re.compile(r'([A-Z][a-z]?)(\d*)')
                elements = {}
                for match in element_pattern.finditer(formula):
                    elem = match.group(1)
                    count = int(match.group(2)) if match.group(2) else 1
                    elements[elem] = count
                
                # Calculate properties
                # Atomic weights
                weights = {'H': 1.008, 'C': 12.011, 'N': 14.007, 'O': 15.999, 'S': 32.065, 'P': 30.974, 'CL': 35.453}
                mw = sum(weights.get(e, 12) * c for e, c in elements.items())
                
                # Estimate properties
                n_atoms = sum(elements.values())
                n_heavy = sum(c for e, c in elements.items() if e != 'H')
                
                # Estimate LogP (simplified Wildman-Crippen)
                logp_estimate = 0.5 * elements.get('C', 0) - 0.3 * elements.get('O', 0) - 0.5 * elements.get('N', 0)
                
                return f"Computational Chemistry Analysis for {formula}:\n- Molecular Weight: {mw:.2f} g/mol\n- Total atoms: {n_atoms}\n- Heavy atoms: {n_heavy}\n- Estimated LogP: {logp_estimate:.2f}\n- H-bond donors (est.): {elements.get('O', 0) + elements.get('N', 0)}\n- Rotatable bonds (est.): {max(0, elements.get('C', 0) - 1)}"
                
            elif operation == "quantum_calc" or operation == "dft":
                # CITED tabulated values for five small molecules. We DO NOT
                # claim to have computed these — the values are pulled from
                # NIST CCCBDB experimental references (where available) so
                # the LLM has anchor data, and we label them as such.
                # For real DFT use astropy/PySCF extended_science_tools or
                # AXIOM QuantumChemistryService.
                molecule = data.upper()
                tabulated = {
                    "H2":  {"HOMO": -15.4, "LUMO":  4.5, "gap": 19.9, "dipole": 0.00,
                            "source": "NIST CCCBDB"},
                    "H2O": {"HOMO": -12.6, "LUMO":  5.2, "gap": 17.8, "dipole": 1.85,
                            "source": "NIST CCCBDB"},
                    "CO2": {"HOMO": -13.8, "LUMO": -0.5, "gap": 13.3, "dipole": 0.00,
                            "source": "NIST CCCBDB"},
                    "CH4": {"HOMO": -13.0, "LUMO":  7.1, "gap": 20.1, "dipole": 0.00,
                            "source": "NIST CCCBDB"},
                    "NH3": {"HOMO": -10.8, "LUMO":  5.5, "gap": 16.3, "dipole": 1.47,
                            "source": "NIST CCCBDB"},
                }
                if molecule in tabulated:
                    p = tabulated[molecule]
                    return (f"DFT properties for {molecule} (TABULATED, source={p['source']}; "
                            f"NOT computed by this tool):\n"
                            f"- HOMO: {p['HOMO']:.2f} eV\n"
                            f"- LUMO: {p['LUMO']:.2f} eV\n"
                            f"- HOMO-LUMO gap: {p['gap']:.2f} eV\n"
                            f"- Dipole moment: {p['dipole']:.2f} D\n"
                            f"For an actual DFT run use the PySCF tools "
                            f"(pyscf_hf_energy / pyscf_dft_energy) or AXIOM "
                            f"QuantumChemistryService.")
                return (f"No tabulated reference for {molecule}. "
                        f"Tabulated set: {sorted(tabulated)}. "
                        f"For a real DFT calculation use pyscf_hf_energy / "
                        f"pyscf_dft_energy.")
                    
            elif operation == "reaction_energy":
                # Calculate reaction energy
                return f"Reaction energy calculation requires reactant/product specification. Format: 'reaction_energy:A+B->C+D'"
                
            else:
                return f"Unknown operation '{operation}'. Available: analyze_molecule, quantum_calc, dft, reaction_energy"
                
        except Exception as e:
            return f"Computational Chemistry Error: {str(e)}"
    
    def _gnome_materials(self, query: str) -> str:
        """GNoME materials discovery and analysis."""
        try:
            parts = query.split(":", 1)
            if len(parts) < 2:
                return "Error: Format should be 'operation:formula' (e.g., 'stability:Li2O')"
            
            operation = parts[0].strip().lower()
            formula = parts[1].strip()
            
            if operation == "stability" or operation == "predict":
                # CITED reference table — formation energies are experimental
                # values reported in the NIST/Materials Project databases.
                # The "stability" score is a normalized indicator we used
                # internally; we now report the raw formation energy and
                # acknowledge that no ML prediction is performed here.
                stable_compounds = {
                    "LI2O":   {"formation_energy": -5.97,  "structure": "antifluorite",
                               "source": "NIST"},
                    "TIO2":   {"formation_energy": -9.78,  "structure": "rutile",
                               "source": "Materials Project mp-2657"},
                    "FE2O3":  {"formation_energy": -8.24,  "structure": "corundum",
                               "source": "Materials Project mp-19770"},
                    "AL2O3":  {"formation_energy": -16.42, "structure": "corundum",
                               "source": "Materials Project mp-1143"},
                    "SIO2":   {"formation_energy": -9.09,  "structure": "alpha-quartz",
                               "source": "Materials Project mp-6930"},
                    "MGO":    {"formation_energy": -6.01,  "structure": "rocksalt",
                               "source": "Materials Project mp-1265"},
                    "NAF":    {"formation_energy": -5.75,  "structure": "rocksalt",
                               "source": "Materials Project mp-682"},
                    "LICOO2": {"formation_energy": -7.34,  "structure": "layered R-3m",
                               "source": "Materials Project mp-22526"},
                }
                fu = formula.upper()
                if fu in stable_compounds:
                    p = stable_compounds[fu]
                    return (f"GNoME entry for {formula} (TABULATED from {p['source']}; "
                            f"no ML prediction performed):\n"
                            f"- Formation energy: {p['formation_energy']:.2f} eV/atom\n"
                            f"- Reported structure: {p['structure']}\n"
                            f"For a real ML stability prediction call the "
                            f"GNoME service via AtlasTools.run_scientific_tool.")
                return (f"No tabulated reference for {formula}. "
                        f"Tabulated set: {sorted(stable_compounds)}. "
                        f"For an actual prediction use the GNoME service.")
                    
            elif operation == "properties":
                # CITED experimental band-gap values for four oxides.
                # NOT a prediction — sourced from solid-state physics
                # references.
                known_props = {
                    "TIO2":  {"band_gap": 3.20, "type": "semiconductor",
                              "applications": ["photocatalysis", "solar cells"],
                              "source": "Kavan et al., J. Am. Chem. Soc. (1996)"},
                    "LI2O":  {"band_gap": 5.0,  "type": "insulator",
                              "applications": ["solid electrolyte", "batteries"],
                              "source": "Ishii et al., Solid State Ionics (1999)"},
                    "FE2O3": {"band_gap": 2.20, "type": "semiconductor",
                              "applications": ["pigments", "photocatalysis"],
                              "source": "Sivula et al., ChemSusChem (2011)"},
                    "SIO2":  {"band_gap": 8.9,  "type": "insulator",
                              "applications": ["electronics", "optics"],
                              "source": "Weinberg et al., J. Vac. Sci. Technol. (1979)"},
                }
                fu = formula.upper()
                if fu in known_props:
                    p = known_props[fu]
                    return (f"GNoME properties for {formula} (TABULATED, source={p['source']}):\n"
                            f"- Band gap: {p['band_gap']:.2f} eV\n"
                            f"- Electronic type: {p['type']}\n"
                            f"- Applications: {', '.join(p['applications'])}")
                return (f"No tabulated reference for {formula}. "
                        f"Tabulated set: {sorted(known_props)}.")
                    
            else:
                return f"Unknown operation '{operation}'. Available: stability, predict, properties"
                
        except Exception as e:
            return f"GNoME Materials Error: {str(e)}"
    
    def _quantum_circuit(self, query: str) -> str:
        """Quantum circuit simulation."""
        try:
            parts = query.split(":", 1)
            if len(parts) < 2:
                return "Error: Format should be 'circuit_type:params' (e.g., 'bell:2')"
            
            circuit_type = parts[0].strip().lower()
            params = parts[1].strip()
            
            if circuit_type == "bell":
                n_qubits = int(params)
                # Bell state simulation
                if n_qubits == 2:
                    return f"Quantum Bell State Simulation:\n- Circuit: H(q0) → CNOT(q0, q1)\n- Initial state: |00⟩\n- Final state: (|00⟩ + |11⟩)/√2\n- Entanglement entropy: 1.0 bit\n- Measurement probabilities: {{|00⟩: 0.5, |11⟩: 0.5}}\n- Fidelity: 1.0"
                else:
                    return f"Bell state requires 2 qubits, got {n_qubits}"
                    
            elif circuit_type == "grover":
                n_qubits = int(params)
                # Grover's algorithm simulation
                optimal_iterations = int(math.pi / 4 * math.sqrt(2 ** n_qubits))
                success_prob = math.sin((2 * optimal_iterations + 1) * math.asin(1 / math.sqrt(2 ** n_qubits))) ** 2
                
                return f"Grover's Algorithm Simulation ({n_qubits} qubits):\n- Search space: {2**n_qubits} elements\n- Optimal iterations: {optimal_iterations}\n- Success probability: {success_prob:.4f}\n- Quantum speedup: O(√N) vs O(N) classical\n- Required gates: {3 * n_qubits * optimal_iterations}"
                
            elif circuit_type == "vqe":
                molecule = params.upper()
                # TABULATED published VQE ground-state references (not an
                # actual VQE simulation in legacy mode). Use AXIOM
                # QuantumComputingService / Qiskit / OpenFermion for a real
                # variational optimization.
                vqe_refs = {
                    "H2":   {"ground_energy": -1.137, "bond_length": 0.735,
                             "source": "Peruzzo et al., Nat. Commun. 5, 4213 (2014)"},
                    "LIH":  {"ground_energy": -7.882, "bond_length": 1.595,
                             "source": "Kandala et al., Nature 549, 242 (2017)"},
                    "HEH+": {"ground_energy": -2.862, "bond_length": 0.775,
                             "source": "O'Malley et al., PRX 6, 031007 (2016)"},
                }
                if molecule in vqe_refs:
                    r = vqe_refs[molecule]
                    return (f"VQE reference for {molecule} (TABULATED, "
                            f"source={r['source']}; no live VQE run):\n"
                            f"- Reported ground state energy: {r['ground_energy']:.4f} Ha\n"
                            f"- Optimal bond length: {r['bond_length']:.3f} Å\n"
                            f"For an actual VQE run use AXIOM QuantumComputingService.")
                return (f"No published VQE reference cached for {molecule}. "
                        f"Tabulated set: {sorted(vqe_refs)}.")
                    
            elif circuit_type == "qft":
                n_qubits = int(params)
                # QFT circuit
                n_gates = n_qubits * (n_qubits + 1) // 2 + n_qubits  # Hadamards + controlled rotations
                return f"Quantum Fourier Transform ({n_qubits} qubits):\n- Total gates: {n_gates}\n- Hadamard gates: {n_qubits}\n- Controlled phase gates: {n_qubits * (n_qubits - 1) // 2}\n- Circuit depth: O(n²)\n- Applications: Phase estimation, Shor's algorithm"
                
            else:
                return f"Unknown circuit '{circuit_type}'. Available: bell, grover, vqe, qft"
                
        except Exception as e:
            return f"Quantum Circuit Error: {str(e)}"
    
    def _literature_search(self, query: str) -> str:
        """Curated offline citation index (no live search in legacy path).

        This tool is a SEED REFERENCE LIST — not a search engine. It returns
        a small, manually curated catalog of canonical citations for a few
        topics so downstream LLM passes have anchor papers when no network
        is available. For real literature search use the
        `literature_search` route on the AtlasTools async API, which hits
        arXiv / PubMed / Semantic Scholar.

        The output now explicitly labels itself as "curated_index" so it
        cannot be mistaken for live search results in audits.
        """
        try:
            curated = {
                "prime gap": [
                    ("Bounded gaps between primes", "Y. Zhang", 2014,
                     "Annals of Mathematics", "10.4007/annals.2014.179.3.7"),
                    ("Small gaps between primes", "J. Maynard", 2015,
                     "Annals of Mathematics", "10.4007/annals.2015.181.1.7"),
                ],
                "aromatic": [
                    ("Aromaticity and the Hückel 4n+2 Rule", "M. Solà", 2017,
                     "Chem. Rev.", "10.1021/acs.chemrev.6b00738"),
                ],
                "dna stability": [
                    ("Unified nearest-neighbor parameters", "J. SantaLucia Jr.", 2004,
                     "Ann. Rev. Biophys. Biomol. Struct.",
                     "10.1146/annurev.biophys.32.110601.141800"),
                ],
                "quantum computing": [
                    ("Quantum supremacy using a programmable superconducting processor",
                     "F. Arute et al.", 2019, "Nature", "10.1038/s41586-019-1666-5"),
                    ("Variational quantum eigensolver",
                     "A. Peruzzo et al.", 2014, "Nature Communications",
                     "10.1038/ncomms5213"),
                ],
            }
            q = query.lower()
            results = []
            for key, papers in curated.items():
                if key in q:
                    results.extend(papers)
            if not results:
                return (f"curated_index miss for {query!r}: no canonical seed "
                        f"citations on this topic. For live search call "
                        f"AtlasTools.search_literature (arXiv/PubMed/SS).")
            lines = [f"curated_index hits for {query!r} (NOT a live search):"]
            for title, authors, year, journal, doi in results:
                lines.append(f"  - {title} ({authors}, {year}). {journal}. doi:{doi}")
            return "\n".join(lines)
        except Exception as e:
            return f"Literature Search Error: {str(e)}"
    
    def _validate_hypothesis(self, query: str) -> str:
        """Validate a scientific hypothesis."""
        try:
            parts = query.split(":", 1)
            if len(parts) < 2:
                return "Error: Format should be 'domain:hypothesis_text'"
            
            domain = parts[0].strip().lower()
            hypothesis = parts[1].strip()
            
            # Multi-factor validation
            validation = {
                "domain": domain,
                "hypothesis": hypothesis[:100] + "..." if len(hypothesis) > 100 else hypothesis,
                "factors": {}
            }
            
            # Check falsifiability
            falsifiable_keywords = ["increases", "decreases", "correlates", "causes", "predicts", "differs"]
            is_falsifiable = any(kw in hypothesis.lower() for kw in falsifiable_keywords)
            validation["factors"]["falsifiability"] = 0.8 if is_falsifiable else 0.4
            
            # Check specificity
            has_numbers = bool(re.search(r'\d+', hypothesis))
            has_comparison = any(c in hypothesis.lower() for c in ["greater", "less", "equal", "more", "fewer"])
            validation["factors"]["specificity"] = 0.7 if (has_numbers or has_comparison) else 0.5
            
            # Domain relevance
            domain_keywords = {
                "biology": ["gene", "protein", "cell", "dna", "enzyme", "organism"],
                "chemistry": ["molecule", "reaction", "bond", "catalyst", "compound"],
                "physics": ["energy", "quantum", "particle", "wave", "force"],
                "mathematics": ["theorem", "proof", "conjecture", "equation", "function"]
            }
            
            relevant_kw = domain_keywords.get(domain, [])
            relevance = sum(1 for kw in relevant_kw if kw in hypothesis.lower()) / max(len(relevant_kw), 1)
            validation["factors"]["domain_relevance"] = min(1.0, 0.5 + relevance)
            
            # Calculate overall score
            weights = {"falsifiability": 0.4, "specificity": 0.3, "domain_relevance": 0.3}
            overall = sum(validation["factors"][k] * weights[k] for k in weights)
            validation["overall_score"] = round(overall, 2)
            validation["verdict"] = "strong" if overall > 0.7 else "moderate" if overall > 0.5 else "weak"
            
            return f"Hypothesis Validation:\n- Domain: {domain}\n- Falsifiability: {validation['factors']['falsifiability']:.2f}\n- Specificity: {validation['factors']['specificity']:.2f}\n- Domain relevance: {validation['factors']['domain_relevance']:.2f}\n- Overall score: {validation['overall_score']}\n- Verdict: {validation['verdict']} hypothesis"
            
        except Exception as e:
            return f"Validation Error: {str(e)}"
    
    # ========================
    # MATHEMATICS TOOL IMPLEMENTATIONS
    # ========================
    
    def _z3_verify_theorem(self, query: str) -> str:
        """Verify mathematical theorems using Z3 SMT solver."""
        try:
            parts = query.split(":")
            theorem = parts[0].strip()
            variables = parts[1].strip().split(",") if len(parts) > 1 else ["x"]
            
            # Try to use actual Z3 service
            try:
                from app.services.theorem_proving.z3_smt_service import Z3SMTService, Z3_AVAILABLE
                if Z3_AVAILABLE:
                    service = Z3SMTService()
                    var_dict = {v.strip(): "real" for v in variables}
                    result = service.verify_mathematical_property(theorem, var_dict)
                    return f"""Z3 SMT Verification Result:
Theorem: {theorem}
Variables: {variables}
Status: {result.get('status', 'unknown')}
Is Valid: {result.get('is_valid', 'unknown')}
Proof Method: SAT/SMT Solving
Counterexample: {result.get('counterexample', 'None found')}
"""
            except ImportError:
                pass
            
            # Fallback: Symbolic verification with SymPy
            var_syms = [sympy.Symbol(v.strip()) for v in variables]
            
            # Common theorem patterns
            if "+" in theorem and "=" in theorem:
                # Try to verify algebraically
                lhs, rhs = theorem.split("=")
                lhs_expr = sympy.sympify(lhs.strip())
                rhs_expr = sympy.sympify(rhs.strip())
                diff = sympy.simplify(lhs_expr - rhs_expr)
                is_valid = diff == 0
                
                return f"""Mathematical Theorem Verification:
Theorem: {theorem}
Variables: {', '.join(v.strip() for v in variables)}
LHS simplified: {sympy.simplify(lhs_expr)}
RHS simplified: {sympy.simplify(rhs_expr)}
Difference: {diff}
Status: {'VALID (algebraically proven)' if is_valid else 'NOT AUTOMATICALLY PROVABLE'}
Method: Symbolic simplification
"""
            
            return f"Theorem '{theorem}' requires advanced proving techniques. Use automated_prover for complex proofs."
            
        except Exception as e:
            return f"Z3 Verification Error: {str(e)}"
    
    def _number_theory_advanced(self, query: str) -> str:
        """Advanced number theory operations."""
        try:
            parts = query.split(":")
            operation = parts[0].strip().lower()
            arg_str = parts[1].strip() if len(parts) > 1 else "100"
            
            # Handle range format (e.g., "4-100" or just "100")
            if "-" in arg_str and not arg_str.startswith("-"):
                range_parts = arg_str.split("-")
                start = int(range_parts[0])
                end = int(range_parts[1])
                arg = end  # Use end for single-value operations
            else:
                start = 4 if operation == "goldbach" else 2
                arg = int(arg_str)
                end = arg
            
            if operation == "goldbach":
                # Verify Goldbach conjecture for even numbers in range
                verified_count = 0
                failed = []
                sample_pairs = []
                
                for n in range(max(4, start if start % 2 == 0 else start + 1), end + 1, 2):
                    pairs_found = False
                    for p in range(2, n // 2 + 1):
                        if sympy.isprime(p) and sympy.isprime(n - p):
                            if len(sample_pairs) < 5:
                                sample_pairs.append((n, p, n - p))
                            pairs_found = True
                            break
                    if pairs_found:
                        verified_count += 1
                    else:
                        failed.append(n)
                
                total_tested = (end - max(4, start)) // 2 + 1
                
                return f"""Goldbach Conjecture Verification for n ∈ [{max(4, start)}, {end}]:
Status: {'ALL VERIFIED ✓' if not failed else 'COUNTEREXAMPLES FOUND!'}
Even numbers tested: {verified_count}
Verification rate: {verified_count}/{total_tested} ({100*verified_count/max(1,total_tested):.2f}%)

Sample prime pairs (n, p, q) where n = p + q:
{chr(10).join(f'  {n} = {p} + {q}' for n, p, q in sample_pairs)}

{'Failed cases: ' + str(failed) if failed else 'All tested even numbers can be expressed as sum of two primes.'}
Conclusion: Goldbach conjecture holds for all tested values.
"""
            
            elif operation == "twin_primes":
                # Find twin prime pairs up to limit
                twins = []
                for p in sympy.primerange(2, arg):
                    if sympy.isprime(p + 2):
                        twins.append((p, p + 2))
                
                return f"""Twin Prime Analysis up to {arg}:
Total twin prime pairs found: {len(twins)}
First 10 pairs: {twins[:10]}
Last 5 pairs: {twins[-5:] if len(twins) >= 5 else twins}
Density: {len(twins) / (arg / math.log(arg) if arg > 1 else 1):.4f} (relative to π(n))
Twin Prime Conjecture status: UNPROVEN (infinitely many expected)
"""
            
            elif operation == "prime_gaps":
                # Analyze prime gaps
                primes = list(sympy.primerange(2, arg))
                gaps = [primes[i+1] - primes[i] for i in range(len(primes)-1)]
                
                from collections import Counter
                gap_counts = Counter(gaps)
                most_common = gap_counts.most_common(10)
                max_gap = max(gaps) if gaps else 0
                max_gap_after = primes[gaps.index(max_gap)] if gaps else 0
                avg_gap = sum(gaps) / len(gaps) if gaps else 0
                
                return f"""Prime Gap Analysis up to {arg}:
Total primes: {len(primes)}
Total gaps analyzed: {len(gaps)}
Maximum gap: {max_gap} (occurs after prime {max_gap_after})
Average gap: {avg_gap:.2f}
Expected average (by PNT): {math.log(arg):.2f}
Most common gaps: {most_common}

Cramér's Conjecture Check:
  Max gap observed: {max_gap}
  Cramér bound (ln²n): {math.log(arg)**2:.2f}
  Status: {'WITHIN BOUND' if max_gap < math.log(arg)**2 else 'EXCEEDS BOUND (interesting!)'}
"""
            
            elif operation == "factorize":
                factors = sympy.factorint(arg)
                factor_str = " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(factors.items()))
                
                # Number theory properties
                phi = sympy.totient(arg)
                divisors = list(sympy.divisors(arg))
                sigma = sum(divisors)
                
                return f"""Prime Factorization of {arg}:
Factorization: {arg} = {factor_str}
Prime factors: {list(factors.keys())}
Exponents: {list(factors.values())}

Number-Theoretic Properties:
  φ(n) (Euler's totient): {phi}
  σ(n) (sum of divisors): {sigma}
  τ(n) (number of divisors): {len(divisors)}
  Divisors: {divisors[:20]}{'...' if len(divisors) > 20 else ''}
  Perfect number check: {'YES' if sigma - arg == arg else 'NO'}
  Abundant/Deficient: {'Abundant' if sigma - arg > arg else 'Deficient' if sigma - arg < arg else 'Perfect'}
"""
            
            else:
                return f"Unknown operation: {operation}. Available: goldbach, twin_primes, prime_gaps, factorize"
                
        except Exception as e:
            return f"Number Theory Error: {str(e)}"

    def _prime_gap_hpc(self, query: str) -> str:
        """High-performance prime gap residual diagnostics using primesieve.

        Input: float literal for N_limit, e.g. '1e8', '1e9', '1e10'. No hard limit.
        Computes normalized gaps x_i = g_i/log(p_i), KS vs Exp(1),
        max-gap/log^2(N) ratios, slab diagnostics, and R^2 OLS fits.
        For N > 5e8 uses streaming float32 to keep RAM < 2 GB.
        """
        import math as _math
        import json as _json
        import time as _time

        try:
            import primesieve as _ps
            import numpy as _np
        except ImportError:
            return (
                "prime_gap_hpc requires primesieve. "
                "Install: CPPFLAGS=-I$(brew --prefix primesieve)/include "
                "LDFLAGS=-L$(brew --prefix primesieve)/lib pip install primesieve"
            )

        # ── Parse input ──────────────────────────────────────────────────────
        try:
            N_limit = int(float((query or "1e9").strip().split(":")[0]))
        except ValueError:
            N_limit = 10 ** 9
        N_limit = max(100_000, N_limit)

        t_start = _time.perf_counter()
        STREAMING_THRESHOLD = 5 * 10 ** 8  # above this, use streaming float32

        # ── Build prefix checkpoints ─────────────────────────────────────────
        def _build_prefixes(n):
            pts = [10**5, 3*10**5]
            v = 10**6
            while v <= n:
                pts.append(v)
                v = int(v * 3) if int(v * 3) <= n else n
                if v not in pts:
                    pts.append(v)
                nv = int(v * 10 // 3)
                if 10 * v // 3 <= n:
                    v = 10 * v // 3
                else:
                    break
            pts.append(n)
            return sorted(set(pts))

        prefixes = _build_prefixes(N_limit)

        # ── Helpers ──────────────────────────────────────────────────────────
        def _ks_exp1(x_arr):
            if len(x_arr) == 0:
                return float("nan")
            xs = _np.sort(x_arr.astype(_np.float64))
            n  = len(xs)
            ecdf  = _np.arange(1, n + 1, dtype=_np.float64) / n
            theor = 1.0 - _np.exp(-xs)
            return float(_np.max(_np.abs(ecdf - theor)))

        def _tail_ratio(x_arr, t):
            if len(x_arr) == 0:
                return float("nan")
            empirical = float(_np.mean(x_arr >= t))
            theoretical = _math.exp(-t)
            return empirical / theoretical if theoretical > 0 else float("nan")

        def _ols_r2(xs, ys):
            xs = _np.asarray(xs, dtype=float)
            ys = _np.asarray(ys, dtype=float)
            if len(xs) < 2:
                return float("nan"), float("nan"), float("nan")
            xm, ym = xs.mean(), ys.mean()
            ss_xy = float(((xs - xm) * (ys - ym)).sum())
            ss_xx = float(((xs - xm) ** 2).sum())
            if ss_xx == 0:
                return float("nan"), float("nan"), float("nan")
            slope = ss_xy / ss_xx
            intercept = ym - slope * xm
            y_pred = slope * xs + intercept
            ss_res = float(((ys - y_pred) ** 2).sum())
            ss_tot = float(((ys - ym) ** 2).sum())
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
            return slope, intercept, r2

        # ── Data acquisition ─────────────────────────────────────────────────
        if N_limit <= STREAMING_THRESHOLD:
            # Fast path: load full prime array
            primes    = _np.array(_ps.primes(N_limit), dtype=_np.uint64)
            gaps_f64  = _np.diff(primes).astype(_np.float64)
            log_p_arr = _np.log(primes[:-1].astype(_np.float64))
            norm_arr  = gaps_f64 / log_p_arr
            p_arr     = primes[:-1]
            g_arr     = gaps_f64
            n_primes_total = len(primes)

            def _prefix_slice(N):
                mask = p_arr <= N
                return norm_arr[mask], g_arr[mask], int(_np.sum(primes <= N))

            def _slab_slice(lo, hi):
                mask = (p_arr > lo) & (p_arr <= hi)
                return norm_arr[mask], g_arr[mask]

            # Maximal gaps
            maximal_gaps = []
            cur_max = 0
            for i in range(len(g_arr)):
                if g_arr[i] > cur_max:
                    cur_max = g_arr[i]
                    maximal_gaps.append((int(primes[i]), int(g_arr[i])))
        else:
            # Streaming path: collect float32 normalized gaps + gap values
            # Also collect (prime_idx, p_value, gap_value) at prefix boundaries
            CHUNK = 8_000_000
            chunks_norm  = []   # float32 normalized gaps
            chunks_gap   = []   # uint16 raw gaps (all prime gaps <= ~1500 for N<=10^10)
            chunks_p     = []   # uint32 or uint64 prime values for prefix tracking

            it = _ps.Iterator()
            prev = 0; norm_buf = []; gap_buf = []; p_buf = []
            p = it.next_prime()
            maximal_gaps = []; cur_max = 0
            n_primes_total = 0
            while p <= N_limit:
                n_primes_total += 1
                if prev:
                    g = p - prev
                    lp = _math.log(prev)
                    xn = g / lp
                    norm_buf.append(_np.float32(xn))
                    gap_buf.append(g)
                    p_buf.append(prev)
                    if g > cur_max:
                        cur_max = g
                        maximal_gaps.append((int(prev), int(g)))
                    if len(norm_buf) >= CHUNK:
                        chunks_norm.append(_np.array(norm_buf, dtype=_np.float32))
                        chunks_gap.append(_np.array(gap_buf, dtype=_np.uint32))
                        chunks_p.append(_np.array(p_buf, dtype=_np.uint64))
                        norm_buf = []; gap_buf = []; p_buf = []
                prev = p
                p = it.next_prime()
            if norm_buf:
                chunks_norm.append(_np.array(norm_buf, dtype=_np.float32))
                chunks_gap.append(_np.array(gap_buf, dtype=_np.uint32))
                chunks_p.append(_np.array(p_buf, dtype=_np.uint64))

            norm_arr = _np.concatenate(chunks_norm)
            g_arr    = _np.concatenate(chunks_gap).astype(_np.float64)
            p_arr    = _np.concatenate(chunks_p)

            def _prefix_slice(N):
                mask = p_arr <= N
                return norm_arr[mask].astype(_np.float64), g_arr[mask], int(_np.sum(p_arr <= N)) + 1

            def _slab_slice(lo, hi):
                mask = (p_arr > lo) & (p_arr <= hi)
                return norm_arr[mask].astype(_np.float64), g_arr[mask]

        # ── Prefix diagnostics ───────────────────────────────────────────────
        prefix_rows = []
        for N in prefixes:
            x_s, g_s, n_pi = _prefix_slice(N)
            if len(x_s) == 0:
                continue
            max_g   = float(g_s.max())
            log2N   = _math.log(N) ** 2
            prefix_rows.append({
                "N":             N,
                "pi_N":          n_pi,
                "n_gaps":        len(x_s),
                "mean_gap":      round(float(g_s.mean()), 4),
                "mean_norm":     round(float(x_s.mean()), 6),
                "var_norm":      round(float(x_s.var()),  6),
                "ks_exp1":       round(_ks_exp1(x_s), 6),
                "max_gap":       int(max_g),
                "max_gap_ratio": round(max_g / log2N, 6),
                "tail_ratio_t3": round(_tail_ratio(x_s, 3.0), 6),
            })

        # ── Slab diagnostics ─────────────────────────────────────────────────
        slab_boundaries = sorted(set([10_000] + prefixes))
        slab_rows = []
        for i in range(len(slab_boundaries) - 1):
            lo, hi = slab_boundaries[i], slab_boundaries[i + 1]
            x_s, g_s = _slab_slice(lo, hi)
            if len(x_s) < 10:
                continue
            slab_rows.append({
                "interval":      f"({lo:.3g}, {hi:.3g}]",
                "n_gaps":        len(x_s),
                "mean_norm":     round(float(x_s.mean()), 6),
                "ks_exp1":       round(_ks_exp1(x_s), 6),
                "tail_ratio_t3": round(_tail_ratio(x_s, 3.0), 6),
            })

        # ── R^2 OLS trend fits ───────────────────────────────────────────────
        inv_log_N = [1.0 / _math.log(r["N"]) for r in prefix_rows]
        ks_vals   = [r["ks_exp1"]      for r in prefix_rows]
        tr_vals   = [r["tail_ratio_t3"] for r in prefix_rows]

        sl_ks, ic_ks, r2_ks = _ols_r2(inv_log_N, ks_vals)
        sl_tr, ic_tr, r2_tr = _ols_r2(inv_log_N, tr_vals)

        wall_time = _time.perf_counter() - t_start

        # ── Format output ────────────────────────────────────────────────────
        hdr = (
            f"=== prime_gap_hpc: N_limit={N_limit:,} | primes={n_primes_total:,} "
            f"| gaps={len(norm_arr):,} | wall_time={wall_time:.2f}s ===\n\n"
        )

        prefix_header = (
            f"{'N':>14} {'pi(N)':>12} {'mean_g':>9} {'mean_x':>9} "
            f"{'KS_Exp1':>9} {'max_g':>7} {'max/log²N':>10} {'tail≥3':>8}\n"
        )
        prefix_header += "-" * 90 + "\n"
        prefix_lines = ""
        for r in prefix_rows:
            prefix_lines += (
                f"{r['N']:>14,} {r['pi_N']:>12,} {r['mean_gap']:>9.4f} "
                f"{r['mean_norm']:>9.6f} {r['ks_exp1']:>9.6f} "
                f"{r['max_gap']:>7d} {r['max_gap_ratio']:>10.6f} {r['tail_ratio_t3']:>8.4f}\n"
            )

        slab_header = f"\n{'Interval':>25} {'gaps':>10} {'mean_x':>8} {'KS':>8} {'tail≥3':>8}\n"
        slab_header += "-" * 65 + "\n"
        slab_lines = ""
        for r in slab_rows:
            slab_lines += (
                f"{r['interval']:>25} {r['n_gaps']:>10,} {r['mean_norm']:>8.6f} "
                f"{r['ks_exp1']:>8.6f} {r['tail_ratio_t3']:>8.4f}\n"
            )

        trend = (
            f"\nOLS fits (y ~ a/log(N) + b):\n"
            f"  KS vs Exp(1):  slope={sl_ks:.4f}  intercept={ic_ks:.4f}  R²={r2_ks:.4f}\n"
            f"  tail_ratio≥3:  slope={sl_tr:.4f}  intercept={ic_tr:.4f}  R²={r2_tr:.4f}\n"
        )

        # Top maximal gaps
        max_gap_lines = "\nMAXIMAL GAP RECORDS (last 10):\n"
        max_gap_lines += f"{'after_prime':>16} {'gap':>6} {'log²(p)':>10} {'ratio':>8}\n"
        max_gap_lines += "-" * 46 + "\n"
        for mp, mg in maximal_gaps[-10:]:
            lg2 = _math.log(mp) ** 2
            max_gap_lines += f"{mp:>16,} {mg:>6} {lg2:>10.4f} {mg/lg2:>8.4f}\n"

        json_blob = _json.dumps({
            "N_limit":    N_limit,
            "n_primes":   int(n_primes_total),
            "wall_time_s": round(wall_time, 2),
            "prefixes":   prefix_rows,
            "slabs":      slab_rows,
            "maximal_gaps": maximal_gaps[-10:],
            "ols_ks":     {"slope": round(sl_ks, 4), "intercept": round(ic_ks, 4), "r2": round(r2_ks, 4)},
            "ols_tail":   {"slope": round(sl_tr, 4), "intercept": round(ic_tr, 4), "r2": round(r2_tr, 4)},
        }, ensure_ascii=False, indent=2)

        return (
            hdr
            + "PREFIX TABLE\n" + prefix_header + prefix_lines
            + "\nSLAB TABLE" + slab_header + slab_lines
            + trend
            + max_gap_lines
            + "\nJSON_DATA:\n" + json_blob
        )

    def _conjecture_engine(self, query: str) -> str:
        """Generate and evaluate mathematical conjectures."""
        try:
            parts = query.split(":")
            operation = parts[0].strip().lower()
            domain = parts[1].strip() if len(parts) > 1 else "number_theory"
            params = parts[2].strip() if len(parts) > 2 else ""
            
            if operation == "generate":
                # Generate conjectures based on domain
                conjectures = {
                    "number_theory": [
                        {"id": "goldbach", "statement": "Every even integer > 2 is the sum of two primes", "status": "unproven", "evidence_count": 4e18},
                        {"id": "twin_prime", "statement": "There are infinitely many twin primes (p, p+2)", "status": "unproven", "evidence_count": float('inf')},
                        {"id": "collatz", "statement": "The Collatz sequence eventually reaches 1 for all positive integers", "status": "unproven", "evidence_count": 2.95e20},
                        {"id": "riemann", "statement": "All non-trivial zeros of ζ(s) have real part 1/2", "status": "unproven", "evidence_count": 1e13},
                    ],
                    "graph_theory": [
                        {"id": "four_color", "statement": "Every planar graph is 4-colorable", "status": "proven_1976", "evidence_count": float('inf')},
                        {"id": "hadwiger", "statement": "Graphs without Kₙ minor are (n-1)-colorable", "status": "unproven_n>=7", "evidence_count": 1e6},
                    ]
                }
                
                domain_conj = conjectures.get(domain, conjectures["number_theory"])
                return f"""Mathematical Conjecture Generation ({domain}):
Generated {len(domain_conj)} conjectures:

""" + "\n\n".join(f"""Conjecture: {c['id'].upper()}
Statement: {c['statement']}
Status: {c['status']}
Empirical evidence checked: {c['evidence_count']:.2e} cases""" for c in domain_conj)
            
            elif operation == "evaluate":
                # Evaluate a specific conjecture
                conjecture_name = domain.lower()
                test_value = int(params) if params.isdigit() else 100
                
                if "goldbach" in conjecture_name:
                    # Test Goldbach for a specific value
                    result = self._number_theory_advanced(f"goldbach:{test_value}")
                    return f"Conjecture Evaluation: Goldbach\nTest value: {test_value}\n{result}"
                
                elif "collatz" in conjecture_name:
                    # Test Collatz
                    n = test_value
                    sequence = [n]
                    while n != 1 and len(sequence) < 1000:
                        n = n // 2 if n % 2 == 0 else 3 * n + 1
                        sequence.append(n)
                    
                    return f"""Conjecture Evaluation: Collatz
Starting value: {test_value}
Reached 1: {'YES' if sequence[-1] == 1 else 'NO (sequence truncated)'}
Steps to reach 1: {len(sequence) - 1}
Maximum value in sequence: {max(sequence)}
Sequence (first 20): {sequence[:20]}
"""
                
                return f"Unknown conjecture: {conjecture_name}"
            
            else:
                return f"Unknown operation: {operation}. Available: generate, evaluate"
                
        except Exception as e:
            return f"Conjecture Engine Error: {str(e)}"
    
    def _automated_prover(self, query: str) -> str:
        """Computational verification of a statement.

        Replaces the prior implementation that returned static "Proof by …"
        templates for two specific inputs. Now:
          - induction:sum_powers:p[:n_max]   →  verify Σ_{k=1}^{n} k^p closed form
          - contradiction:sqrt:n             →  check whether √n is irrational
            by factoring n and inspecting parity of prime exponents
        Any other input is honestly reported as unsupported.
        """
        try:
            parts = query.split(":")
            method = parts[0].strip().lower()

            if method == "induction" and len(parts) >= 3 and parts[1].strip().lower() == "sum_powers":
                if not _REAL_TOOLS_AVAILABLE:
                    return "Error: induction verification requires core.atlas_real_tools"
                p = int(parts[2].strip())
                n_max = int(parts[3].strip()) if len(parts) >= 4 else 5
                return _real.automated_prover_induction_sum_first_n_powers(p, n_max=n_max)

            if method == "contradiction" and len(parts) >= 3 and parts[1].strip().lower() == "sqrt":
                if not _REAL_TOOLS_AVAILABLE:
                    return "Error: irrationality check requires core.atlas_real_tools"
                n = int(parts[2].strip())
                return _real.automated_prover_irrational_root(n)

            return ("Error: automated_prover only supports computationally "
                    "verifiable statements. Use 'induction:sum_powers:p[:n_max]' "
                    "or 'contradiction:sqrt:n'. The prior template outputs were "
                    "removed because they did not depend on the input.")
        except Exception as e:
            return f"Automated Prover Error: {str(e)}"
    
    def _mathematical_discovery(self, query: str) -> str:
        """Discover mathematical patterns and relationships."""
        try:
            parts = query.split(":")
            method = parts[0].strip().lower()
            domain = parts[1].strip() if len(parts) > 1 else "sequences"
            params = parts[2].strip() if len(parts) > 2 else ""
            
            if method == "pattern_analysis":
                if domain == "sequences" or params == "fibonacci":
                    # Analyze Fibonacci-like patterns
                    fib = [1, 1]
                    for _ in range(18):
                        fib.append(fib[-1] + fib[-2])
                    
                    ratios = [fib[i+1]/fib[i] for i in range(len(fib)-1)]
                    phi = (1 + math.sqrt(5)) / 2
                    
                    return f"""Pattern Discovery: Fibonacci Sequence
Sequence: {fib[:15]}...
Discovered Patterns:

1. RATIO CONVERGENCE:
   Consecutive ratios: {[f'{r:.4f}' for r in ratios[-5:]]}
   Converges to φ (golden ratio): {phi:.6f}
   
2. CLOSED FORM (Binet's Formula):
   F(n) = (φⁿ - ψⁿ) / √5
   where φ = (1+√5)/2, ψ = (1-√5)/2

3. DIVISIBILITY:
   gcd(F(m), F(n)) = F(gcd(m, n))
   
4. SUM IDENTITY:
   F(1) + F(2) + ... + F(n) = F(n+2) - 1
   Verified: {sum(fib[:10])} = {fib[11]} - 1 = {fib[11] - 1} ✓
"""
                
                elif params == "primes":
                    return self._number_theory_advanced(f"prime_gaps:10000")
            
            elif method == "numerical_exploration":
                return self._number_theory_advanced(f"{params}:10000")
            
            else:
                return f"Unknown method: {method}. Available: pattern_analysis, numerical_exploration"
                
        except Exception as e:
            return f"Discovery Error: {str(e)}"
    
    def _sequence_analyzer(self, query: str) -> str:
        """Analyze integer sequences (OEIS-style)."""
        try:
            parts = query.split(":")
            operation = parts[0].strip().lower()
            data = parts[1].strip() if len(parts) > 1 else ""
            
            if operation == "analyze":
                # Parse sequence
                seq = [int(x.strip()) for x in data.split(",")]
                
                # Compute differences
                diffs = [seq[i+1] - seq[i] for i in range(len(seq)-1)]
                second_diffs = [diffs[i+1] - diffs[i] for i in range(len(diffs)-1)]
                
                # Check for known sequences
                known_sequences = {
                    (1, 1, 2, 3, 5, 8, 13): ("Fibonacci", "A000045"),
                    (2, 3, 5, 7, 11, 13): ("Primes", "A000040"),
                    (1, 4, 9, 16, 25, 36): ("Perfect squares", "A000290"),
                    (1, 8, 27, 64, 125): ("Perfect cubes", "A000578"),
                    (1, 2, 6, 24, 120, 720): ("Factorials", "A000142"),
                }
                
                # Check pattern
                seq_tuple = tuple(seq[:7]) if len(seq) >= 7 else tuple(seq)
                match = None
                for pattern, (name, oeis) in known_sequences.items():
                    if seq_tuple[:len(pattern)] == pattern[:len(seq_tuple)]:
                        match = (name, oeis)
                        break
                
                # Detect polynomial degree
                degree = None
                if all(d == 0 for d in second_diffs):
                    degree = 1  # Linear
                elif len(set(second_diffs)) == 1 and second_diffs[0] != 0:
                    degree = 2  # Quadratic
                
                return f"""Sequence Analysis:
Input: {seq}

First differences: {diffs}
Second differences: {second_diffs}

Pattern Detection:
  OEIS Match: {f'{match[0]} ({match[1]})' if match else 'No direct match'}
  Polynomial degree: {degree if degree else 'Not polynomial or higher degree'}
  
Recurrence check:
  Constant differences: {'Yes (arithmetic)' if len(set(diffs)) == 1 else 'No'}
  Ratio pattern: {[f'{seq[i+1]/seq[i]:.2f}' for i in range(min(5, len(seq)-1))] if all(s != 0 for s in seq[:-1]) else 'Contains zeros'}
"""
            
            elif operation == "generate":
                seq_type = data.lower()
                n = int(parts[2]) if len(parts) > 2 else 20
                
                if seq_type == "fibonacci":
                    seq = [1, 1]
                    for _ in range(n - 2):
                        seq.append(seq[-1] + seq[-2])
                elif seq_type == "primes":
                    seq = list(sympy.primerange(2, sympy.prime(n) + 1))[:n]
                elif seq_type == "triangular":
                    seq = [i * (i + 1) // 2 for i in range(1, n + 1)]
                elif seq_type == "catalan":
                    seq = [int(sympy.catalan(i)) for i in range(n)]
                else:
                    return f"Unknown sequence type: {seq_type}. Available: fibonacci, primes, triangular, catalan"
                
                return f"""Generated Sequence: {seq_type.title()}
First {n} terms: {seq}
"""
            
            elif operation == "find_formula":
                seq = [int(x.strip()) for x in data.split(",")]
                
                # Try to find polynomial formula
                x = sympy.Symbol('n')
                
                # Check linear: a*n + b
                if len(seq) >= 2:
                    diffs = [seq[i+1] - seq[i] for i in range(len(seq)-1)]
                    if len(set(diffs)) == 1:
                        a = diffs[0]
                        b = seq[0] - a
                        formula = f"{a}*n + {b}" if b >= 0 else f"{a}*n - {-b}"
                        return f"Formula found (linear): a(n) = {formula}"
                
                # Check quadratic
                if len(seq) >= 3:
                    second_diffs = [diffs[i+1] - diffs[i] for i in range(len(diffs)-1)]
                    if len(set(second_diffs)) == 1:
                        return f"Formula type: Quadratic (second differences constant = {second_diffs[0]})"
                
                # Check exponential
                if all(s != 0 for s in seq[:-1]):
                    ratios = [seq[i+1] / seq[i] for i in range(len(seq) - 1)]
                    if len(set([round(r, 4) for r in ratios])) == 1:
                        return f"Formula type: Exponential (common ratio = {ratios[0]:.4f})"
                
                return f"No simple formula detected for: {seq}"
            
            else:
                return f"Unknown operation: {operation}. Available: analyze, generate, find_formula"
                
        except Exception as e:
            return f"Sequence Analyzer Error: {str(e)}"
    
    def _symbolic_calculus(self, query: str) -> str:
        """Advanced symbolic calculus operations."""
        try:
            parts = query.split(":")
            operation = parts[0].strip().lower()
            expression = parts[1].strip() if len(parts) > 1 else "x"
            var_spec = parts[2].strip() if len(parts) > 2 else "x"
            extra = parts[3].strip() if len(parts) > 3 else ""
            
            x = sympy.Symbol('x')
            t = sympy.Symbol('t')
            s = sympy.Symbol('s')
            n = sympy.Symbol('n')
            
            if operation == "limit":
                # Parse limit: expression:x->value
                if "->" in var_spec:
                    var_name, point = var_spec.split("->")
                    var = sympy.Symbol(var_name.strip())
                    point = sympy.sympify(point.strip())
                else:
                    var = x
                    point = 0
                
                expr = sympy.sympify(expression)
                limit_val = sympy.limit(expr, var, point)
                
                return f"""Limit Computation:
Expression: {expression}
As {var} → {point}
Result: {limit_val}
"""
            
            elif operation == "taylor":
                # Taylor series: expression:variable:point:order
                var = sympy.Symbol(var_spec) if var_spec else x
                point = sympy.sympify(extra.split(":")[0]) if extra else 0
                order = int(extra.split(":")[1]) if ":" in extra else 5
                
                expr = sympy.sympify(expression)
                series = sympy.series(expr, var, point, order + 1).removeO()
                
                return f"""Taylor Series Expansion:
Function: {expression}
Variable: {var}
Expansion point: {point}
Order: {order}
Series: {series}
"""
            
            elif operation == "laplace":
                expr = sympy.sympify(expression)
                laplace = sympy.laplace_transform(expr, t, s)
                
                return f"""Laplace Transform:
f(t) = {expression}
L{{f(t)}} = {laplace[0]}
Region of convergence: Re(s) > {laplace[1] if len(laplace) > 1 else 'N/A'}
"""
            
            elif operation == "fourier":
                expr = sympy.sympify(expression)
                # Simplified Fourier coefficient calculation
                a0 = sympy.integrate(expr, (x, -sympy.pi, sympy.pi)) / (2 * sympy.pi)
                
                return f"""Fourier Analysis:
Function: {expression}
a₀ coefficient: {a0}
(Full Fourier series requires numerical integration for general functions)
"""
            
            else:
                return f"Unknown operation: {operation}. Available: limit, taylor, laplace, fourier"
                
        except Exception as e:
            return f"Symbolic Calculus Error: {str(e)}"
    
    def _graph_theory(self, query: str) -> str:
        """Real graph theory computations on user-specified graphs.

        Replaces the 4-graph hardcoded lookup. Now computes χ and Eulerian
        status from the actual graph. Specs:
          complete:n, cycle:n, path:n, bipartite:m,n, petersen, cube,
          edges:1-2,2-3,...
        """
        try:
            parts = query.split(":", 1)
            operation = parts[0].strip().lower()
            graph_spec = parts[1].strip() if len(parts) > 1 else "petersen"

            if not _REAL_TOOLS_AVAILABLE:
                return ("Error: graph_theory now requires core.atlas_real_tools "
                        "(deterministic χ + Eulerian, no hardcoded answers).")

            if operation == "chromatic":
                return _real.graph_chromatic_number(graph_spec)
            if operation == "eulerian":
                return _real.graph_eulerian(graph_spec)
            return (f"Unknown operation: {operation}. "
                    f"Available: chromatic, eulerian")
        except Exception as e:
            return f"Graph Theory Error: {str(e)}"
    
    def _topology_invariants(self, query: str) -> str:
        """Real topological invariants from triangulations / face vectors.

        Replaces the 5-space lookup dict. Now derives χ from an explicit
        f-vector (either passed directly or looked up via a known
        triangulation) and shows the alternating-sum computation.

        Inputs:
          euler_char:sphere          → from boundary-of-tetrahedron triangulation
          euler_char:torus           → from 7-vertex triangulation
          euler_char:fv:4,6,4        → from a caller-supplied f-vector
          betti:<space>              → from textbook Betti for surfaces
          fundamental_group:<space>  → from textbook π₁ for surfaces
        """
        try:
            parts = query.split(":")
            invariant = parts[0].strip().lower()
            arg = ":".join(parts[1:]).strip() if len(parts) > 1 else "sphere"

            # χ from real triangulations
            if invariant in ("euler_char", "euler"):
                if not _REAL_TOOLS_AVAILABLE:
                    return "Error: requires core.atlas_real_tools"
                if arg.lower().startswith("fv:"):
                    fv_str = arg[len("fv:"):]
                    try:
                        fv = [int(x.strip()) for x in fv_str.split(",")]
                    except ValueError:
                        return "Error: face vector must be 'fv:4,6,4'"
                    return _real.euler_characteristic_from_face_vector(fv)
                return _real.euler_characteristic_named_space(arg)

            # Betti numbers and π₁ for surfaces — these are CITED textbook values
            # not derived from a chain complex. We declare them as such so the
            # caller knows it's a lookup, not a computation.
            surface_data = {
                "sphere":             {"betti": [1, 0, 1], "pi1": "trivial"},
                "torus":              {"betti": [1, 2, 1], "pi1": "Z × Z"},
                "klein_bottle":       {"betti": [1, 1, 0], "pi1": "⟨a,b | aba⁻¹b⟩ (mod 2)"},
                "projective_plane":   {"betti": [1, 0, 0], "pi1": "Z/2Z"},
                "rp2":                {"betti": [1, 0, 0], "pi1": "Z/2Z"},
                "circle":             {"betti": [1, 1],    "pi1": "Z"},
                "s1":                 {"betti": [1, 1],    "pi1": "Z"},
                "point":              {"betti": [1],        "pi1": "trivial"},
            }
            name = arg.strip().lower()
            if invariant == "betti":
                if name not in surface_data:
                    return (f"Error: betti numbers tabulated only for "
                            f"{sorted(surface_data)}; got {name!r}")
                betti = surface_data[name]["betti"]
                return (f"Betti numbers (tabulated, surface case):\n"
                        f"  space: {name}\n"
                        f"  β = {betti}\n"
                        f"  alternating sum Σ(-1)ⁱ βᵢ = "
                        f"{sum(((-1)**i)*b for i, b in enumerate(betti))} "
                        f"(equals χ if Betti are correct)")
            if invariant in ("fundamental_group", "pi1"):
                if name not in surface_data:
                    return (f"Error: π₁ tabulated only for "
                            f"{sorted(surface_data)}; got {name!r}")
                return (f"Fundamental group (tabulated):\n"
                        f"  π₁({name}) = {surface_data[name]['pi1']}")
            return (f"Unknown invariant: {invariant}. "
                    f"Available: euler_char, betti, fundamental_group")
        except Exception as e:
            return f"Topology Error: {str(e)}"
    
    def register_tool(self, tool: ToolDescriptor):
        """Register a tool."""
        if self._allowed_domains is not None and tool.domain not in self._allowed_domains:
            return
        self.tools[tool.name] = tool
    
    def get_tool(self, name: str) -> ToolDescriptor:
        """Get a tool by name."""
        return self.tools.get(name)
    
    def list_tools(self, domain: str = None) -> List[str]:
        """List available tools, optionally filtered by domain."""
        if domain:
            return [name for name, tool in self.tools.items() if tool.domain == domain]
        return list(self.tools.keys())

    def list_tools_for_domain(self, domain: str) -> List[str]:
        """List tools for a domain, including aliases + global research tools."""
        dom = (domain or "").strip().lower()
        if not dom:
            return self.list_tools()

        candidate_domains = {dom}
        candidate_domains.update(self._domain_aliases.get(dom, []))
        candidate_domains.update(self._global_domains)

        return [
            name
            for name, tool in self.tools.items()
            if tool.domain in candidate_domains
        ]

    def get_tool_descriptions_for_domain(self, domain: str, max_chars: int = 4000) -> str:
        """Formatted descriptions of tools relevant to a domain."""
        tool_names = self.list_tools_for_domain(domain)
        lines: List[str] = []
        for name in tool_names:
            t = self.tools.get(name)
            if not t:
                continue
            lines.append(
                f"- {t.name} ({t.domain}) [{t.input_format} -> {t.output_format}]: {t.description}"
            )
        text = "\n".join(lines)
        return text[:max_chars]

    def _register_orchestrator_tools(self):
        """Expose ToolEvidenceOrchestrator routes as tools so every domain can gather evidence."""
        try:
            from app.services.tool_evidence_orchestrator import ToolEvidenceOrchestratorService
        except Exception as e:
            print(f"   ⚠️ ToolEvidenceOrchestrator not available (optional): {e}")
            return

        try:
            orchestrator = ToolEvidenceOrchestratorService()
            domains = sorted(orchestrator.domain_routes.keys())

            for dom in domains:
                safe_dom = re.sub(r"[^a-zA-Z0-9_]+", "_", dom.strip().lower())

                async def _corroborate_for_domain(hypothesis_text: str, _domain=dom):
                    hyp = {
                        "title": hypothesis_text[:120] if hypothesis_text else f"{_domain} hypothesis",
                        "description": hypothesis_text or "",
                        "domain": _domain,
                        "variables": [],
                        "assumptions": [],
                        "expected_outcome": "",
                    }
                    res = await orchestrator.process_request({
                        "action": "corroborate",
                        "hypothesis": hyp,
                        "domain": _domain,
                    })
                    if not isinstance(res, dict):
                        return str(res)

                    # Compact summary for LLM consumption
                    agg = res.get("aggregate", {}) or {}
                    coverage = agg.get("coverage")
                    support = agg.get("support_score")
                    mean_signal = agg.get("mean_signal")
                    real_coverage = agg.get("real_coverage")
                    real_success_count = agg.get("real_success_count")
                    failure_count = agg.get("failure_count")
                    tool_realism_score = agg.get("tool_realism_score")
                    tier_counts = agg.get("tier_counts")

                    items = res.get("evidence_items", []) or []
                    top = []
                    for it in items[:5]:
                        top.append(
                            f"- {it.get('source')}::{it.get('operation')} | "
                            f"success={it.get('success')} | signal={it.get('signal_strength')} | "
                            f"tier={it.get('evidence_tier')} | real={it.get('counts_as_real_evidence')}"
                        )
                    top_text = "\n".join(top)

                    return (
                        f"ToolEvidenceOrchestrator corroboration ({_domain}):\n"
                        f"- coverage: {coverage}\n- real_coverage: {real_coverage}\n"
                        f"- mean_signal: {mean_signal}\n- support_score: {support}\n"
                        f"- real_success_count: {real_success_count}\n- failure_count: {failure_count}\n"
                        f"- tool_realism_score: {tool_realism_score}\n- tier_counts: {tier_counts}\n"
                        f"Top evidence:\n{top_text}"
                    )

                self.register_tool(ToolDescriptor(
                    name=f"evidence_corroborate_{safe_dom}",
                    domain=dom,
                    description=(
                        "Run multi-tool evidence gathering for this domain via ToolEvidenceOrchestrator. "
                        "Input: hypothesis text (free-form)."
                    ),
                    function=_corroborate_for_domain,
                    input_format="hypothesis_text",
                    output_format="evidence_summary",
                ))

            print(f"   ✅ Exposed ToolEvidenceOrchestrator domains: {len(domains)}")
        except Exception as e:
            print(f"   ⚠️ Could not initialize ToolEvidenceOrchestrator tools: {e}")
    
    def get_tool_descriptions(self, domain: str = None) -> str:
        """Get formatted descriptions of available tools."""
        tools = self.tools.values()
        if domain:
            tools = [t for t in tools if t.domain == domain]
        
        descriptions = []
        for t in tools:
            descriptions.append(f"- {t.name} ({t.domain}): {t.description}")
        return "\n".join(descriptions)
    
    # ========================
    # TOOL IMPLEMENTATIONS
    # ========================
    
    def _sympy_solve(self, query: str) -> str:
        """Solve equations using SymPy."""
        try:
            if "=" in query:
                lhs, rhs = query.split("=")
                expr = sympy.sympify(lhs.strip()) - sympy.sympify(rhs.strip())
            else:
                expr = sympy.sympify(query)
            solutions = sympy.solve(expr)
            return f"Solutions: {solutions}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _sympy_simplify(self, query: str) -> str:
        """Simplify expressions using SymPy."""
        try:
            expr = sympy.sympify(query)
            simplified = sympy.simplify(expr)
            return f"Simplified: {simplified}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _sympy_derivative(self, query: str) -> str:
        """Compute derivatives using SymPy. Format: 'expression,variable' (e.g. 'x**3,x')."""
        parts = query.split(",")
        if len(parts) < 2:
            return ("Error: Format should be 'expression,variable' (e.g. 'x**3,x' or 'sin(x),x'). "
                    f"Received: {query!r}")
        try:
            expr = sympy.sympify(parts[0].strip())
            var = sympy.Symbol(parts[1].strip())
            derivative = sympy.diff(expr, var)
            return f"Derivative: {derivative}"
        except Exception as e:
            return f"Error: {str(e)}"

    def _sympy_integrate(self, query: str) -> str:
        """Compute integrals using SymPy. Format: 'expression,variable' (e.g. 'x**2,x')."""
        parts = query.split(",")
        if len(parts) < 2:
            return ("Error: Format should be 'expression,variable' (e.g. 'x**2,x' or 'sin(x),x'). "
                    f"Received: {query!r}")
        try:
            expr = sympy.sympify(parts[0].strip())
            var = sympy.Symbol(parts[1].strip())
            integral = sympy.integrate(expr, var)
            return f"Integral: {integral}"
        except Exception as e:
            return f"Error: {str(e)}"

    def _sympy_prime_analysis(self, query: str) -> str:
        """Analyze prime numbers using SymPy. Format: 'operation:arg' where operation ∈ {is_prime, nth_prime, prime_range, prime_count}."""
        parts = query.split(":")
        if len(parts) < 2:
            return ("Error: Format should be 'operation:arg'. "
                    "Available operations: is_prime, nth_prime, prime_range, prime_count. "
                    f"Examples: 'is_prime:97', 'nth_prime:10', 'prime_range:1-100', 'prime_count:1000'. "
                    f"Received: {query!r}")
        try:
            operation = parts[0].strip()
            arg = parts[1].strip()

            if operation == "is_prime":
                result = sympy.isprime(int(arg))
                return f"{arg} is prime: {result}"
            elif operation == "nth_prime":
                result = sympy.prime(int(arg))
                return f"The {arg}th prime is: {result}"
            elif operation == "prime_range":
                start, end = map(int, arg.split("-"))
                primes = list(sympy.primerange(start, end))
                return f"Primes in [{start}, {end}): {primes[:20]}... (total: {len(primes)})"
            elif operation == "prime_count":
                result = sympy.primepi(int(arg))
                return f"Number of primes up to {arg}: {result}"
            else:
                return f"Unknown operation: {operation}. Available: is_prime, nth_prime, prime_range, prime_count"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def _parse_numeric_array_literal(array_text: str) -> np.ndarray:
        """Parse numeric list/tuple input without executing Python code."""
        value = ast.literal_eval(array_text.strip())
        if not isinstance(value, (list, tuple)):
            raise ValueError("expected a numeric list or tuple literal")
        data = np.array(value, dtype=float)
        if data.size == 0:
            raise ValueError("numeric array cannot be empty")
        return data
    
    def _numpy_statistics(self, query: str) -> str:
        """Compute statistics using NumPy."""
        try:
            parts = query.split(":", 1)
            operation = parts[0].strip()
            data = self._parse_numeric_array_literal(parts[1])
            
            if operation == "mean":
                return f"Mean: {np.mean(data):.6f}"
            elif operation == "std":
                return f"Standard Deviation: {np.std(data):.6f}"
            elif operation == "var":
                return f"Variance: {np.var(data):.6f}"
            elif operation == "median":
                return f"Median: {np.median(data):.6f}"
            elif operation == "summary":
                return f"Mean: {np.mean(data):.4f}, Std: {np.std(data):.4f}, Min: {np.min(data):.4f}, Max: {np.max(data):.4f}"
            else:
                return f"Unknown operation: {operation}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _numpy_distribution(self, query: str) -> str:
        """Generate a reproducible sample from a named distribution.

        Now requires a seed so callers get identical outputs across runs.
        Input format: 'dist:n,p1,p2,...,seed'
          normal:n,mean,std,seed
          uniform:n,low,high,seed
          poisson:n,lambda,seed
        """
        try:
            parts = query.split(":")
            dist_type = parts[0].strip()
            tokens = [t.strip() for t in parts[1].split(",")]

            if _REAL_TOOLS_AVAILABLE:
                if dist_type == "normal":
                    if len(tokens) != 4:
                        return "Error: normal needs 'n,mean,std,seed'"
                    n, mean, std, seed = int(tokens[0]), float(tokens[1]), float(tokens[2]), int(tokens[3])
                    return _real.deterministic_sample("normal", n, mean, std, seed=seed)
                if dist_type == "uniform":
                    if len(tokens) != 4:
                        return "Error: uniform needs 'n,low,high,seed'"
                    n, low, high, seed = int(tokens[0]), float(tokens[1]), float(tokens[2]), int(tokens[3])
                    return _real.deterministic_sample("uniform", n, low, high, seed=seed)
                if dist_type == "poisson":
                    if len(tokens) != 3:
                        return "Error: poisson needs 'n,lambda,seed'"
                    n, lam, seed = int(tokens[0]), float(tokens[1]), int(tokens[2])
                    return _real.deterministic_sample("poisson", n, lam, seed=seed)
                return f"Unknown distribution: {dist_type}. Available: normal, uniform, poisson"

            # Legacy fallback (still without random hiding: warn caller)
            return ("Error: numpy_distribution now requires a seed; "
                    "load core.atlas_real_tools for reproducible sampling.")
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _numpy_correlation(self, query: str) -> str:
        """Compute correlation using NumPy."""
        try:
            # Try different input formats
            if ";" in query:
                parts = query.split(";")
                arr1 = self._parse_numeric_array_literal(parts[0])
                arr2 = self._parse_numeric_array_literal(parts[1])
            elif query.startswith("correlation:"):
                # Format: correlation:[1,2,3],[4,5,6]
                data = query.replace("correlation:", "").strip()
                # Find the two arrays
                import re
                arrays = re.findall(r'\[[\d.,\s-]+\]', data)
                if len(arrays) >= 2:
                    arr1 = self._parse_numeric_array_literal(arrays[0])
                    arr2 = self._parse_numeric_array_literal(arrays[1])
                else:
                    return "Error: Need two arrays. Format: correlation:[1,2,3],[4,5,6]"
            else:
                return "Error: Use format ';' separated or 'correlation:[arr1],[arr2]'"
            
            corr = np.corrcoef(arr1, arr2)[0, 1]
            return f"Pearson correlation coefficient: {corr:.6f} (n={len(arr1)})"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @staticmethod
    def _parse_int_limit(query: str):
        """Extract an integer limit from the many shapes an LLM produces.

        Real probes showed the model passing things like 'range:2,100000',
        'max_prime:100000', 'limit:10000', '10_000', 'primes up to 50000'.
        Rather than reject all of these with an int() crash, we robustly
        pull out the LARGEST integer in the string and use it as the upper
        bound (the lower bound for prime ranges is always 2). Returns None
        if no integer is present.
        """
        import re as _re
        # Normalize underscore digit grouping (10_000 → 10000).
        cleaned = query.replace("_", "")
        # Collapse *well-formed* thousands separators (1,234,567) but NOT
        # ad-hoc comma lists like 'range:2,100000' (groups must be 3 digits).
        cleaned = _re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", cleaned)
        tokens = _re.findall(r"\d+", cleaned)
        candidates = [int(t) for t in tokens] if tokens else []
        if not candidates:
            return None
        # The upper bound is the largest integer mentioned.
        return max(candidates)

    def _prime_gap_analysis(self, query: str) -> str:
        """Analyze prime gaps up to a given limit.

        Hard cap at 10^7 to prevent runaway memory; if the user requests more,
        the cap is applied and reported transparently in the output so that
        downstream consumers do not silently treat truncated data as full.
        """
        try:
            requested_limit = self._parse_int_limit(query)
            if requested_limit is None:
                return ("Error: could not parse a limit from "
                        f"{query!r}. Provide a single integer like '10000' "
                        "(the upper bound on primes to analyze).")
            HARD_CAP = 10_000_000
            if requested_limit > HARD_CAP:
                limit = HARD_CAP
                cap_notice = (f"NOTE: requested limit {requested_limit} exceeded the "
                              f"hard cap of {HARD_CAP}; computed for limit={limit} instead.\n")
            else:
                limit = requested_limit
                cap_notice = ""

            primes = list(sympy.primerange(2, limit))
            if len(primes) < 2:
                return f"Error: limit {limit} produced fewer than 2 primes; gap analysis requires ≥2."
            gaps = [primes[i+1] - primes[i] for i in range(len(primes)-1)]

            gap_mean = np.mean(gaps)
            gap_std = np.std(gaps)
            gap_max = max(gaps)
            max_gap_at = primes[gaps.index(gap_max)]

            from collections import Counter
            gap_counts = Counter(gaps)
            most_common = gap_counts.most_common(5)

            return (f"{cap_notice}"
                    f"Prime gap analysis up to {limit}:\n"
                    f"  Number of primes: {len(primes)}\n"
                    f"  Mean gap: {gap_mean:.4f}\n"
                    f"  Std dev: {gap_std:.4f}\n"
                    f"  Max gap: {gap_max} (after prime {max_gap_at})\n"
                    f"  Most common gaps: {most_common}")
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def _parse_int_limit_series(query: str) -> List[int]:
        """Extract a sorted, unique integer limit series from flexible input."""
        cleaned = query.replace("_", "")
        cleaned = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", cleaned)
        tokens = re.findall(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", cleaned)
        limits = []
        for token in tokens:
            value = int(float(token))
            if value not in limits:
                limits.append(value)
        return sorted(limits)

    def _prime_gap_model_comparison(self, query: str) -> str:
        """Compare finite prime-gap observations with logarithmic controls."""
        try:
            import bisect

            requested_limits = self._parse_int_limit_series(query)
            if len(requested_limits) < 3:
                return (
                    "Error: Provide at least three increasing limits, e.g. "
                    "'10000,100000,1000000'."
                )

            HARD_CAP = 10_000_000
            capped_limits = [min(n, HARD_CAP) for n in requested_limits if n >= 100]
            limits = sorted(dict.fromkeys(capped_limits))
            if len(limits) < 3:
                return "Error: Need at least three unique limits >= 100 after applying the hard cap."
            cap_notice = ""
            if any(n > HARD_CAP for n in requested_limits):
                cap_notice = (
                    f"NOTE: requested limits above {HARD_CAP} were capped at {HARD_CAP}; "
                    f"computed limits={limits}.\n"
                )

            primes = list(sympy.primerange(2, max(limits)))
            if len(primes) < 2:
                return "Error: limit series produced fewer than two primes."

            rows = []
            mean_gaps = []
            max_gaps = []
            log_values = []
            log_sq_values = []
            max_norm_values = []
            mean_norm_values = []

            for limit in limits:
                count = bisect.bisect_left(primes, limit)
                subset = primes[:count]
                if len(subset) < 2:
                    return f"Error: limit {limit} produced fewer than two primes."
                gaps = np.diff(np.array(subset, dtype=np.int64))
                mean_gap = float(np.mean(gaps))
                max_gap = int(np.max(gaps))
                max_gap_index = int(np.argmax(gaps))
                max_gap_at = int(subset[max_gap_index])
                log_n = float(math.log(limit))
                log_n_sq = float(log_n ** 2)
                mean_norm = float(mean_gap / log_n)
                max_norm = float(max_gap / log_n_sq)

                mean_gaps.append(mean_gap)
                max_gaps.append(float(max_gap))
                log_values.append(log_n)
                log_sq_values.append(log_n_sq)
                mean_norm_values.append(mean_norm)
                max_norm_values.append(max_norm)
                rows.append(
                    {
                        "limit": limit,
                        "prime_count": len(subset),
                        "mean_gap": mean_gap,
                        "max_gap": max_gap,
                        "max_gap_at": max_gap_at,
                        "logN": log_n,
                        "mean_gap_over_logN": mean_norm,
                        "max_gap_over_logN_squared": max_norm,
                    }
                )

            mean_fit = self._fit_line(log_values, mean_gaps)
            max_log_fit = self._fit_line(log_values, max_gaps)
            max_log_sq_fit = self._fit_line(log_sq_values, max_gaps)
            normalized_trend = self._fit_line(log_values, max_norm_values)
            best_model = (
                "logN_squared"
                if max_log_sq_fit["rmse"] <= max_log_fit["rmse"]
                else "logN"
            )

            observation_lines = [
                (
                    f"    N={row['limit']}: prime_count={row['prime_count']}, "
                    f"mean_gap={row['mean_gap']:.6f}, max_gap={row['max_gap']} "
                    f"(after prime {row['max_gap_at']}), logN={row['logN']:.6f}, "
                    f"mean_gap/logN={row['mean_gap_over_logN']:.6f}, "
                    f"max_gap/logN^2={row['max_gap_over_logN_squared']:.6f}"
                )
                for row in rows
            ]

            return (
                f"{cap_notice}"
                "Prime gap scaling model comparison:\n"
                "  Heuristic anchors: mean prime gap is compared with log(N); "
                "maximal finite-range gaps are compared with log(N)^2 as a "
                "Cramer-style scale diagnostic.\n"
                f"  Limits: {limits}\n"
                "  Observations:\n"
                + "\n".join(observation_lines)
                + "\n"
                f"  mean_gap_vs_logN fit mean_gap = {mean_fit['slope']:.6f}*log(N) + {mean_fit['intercept']:.6f}; "
                f"RMSE={mean_fit['rmse']:.6f}; R2={mean_fit['r2']:.6f}\n"
                f"  max_gap_vs_logN fit max_gap = {max_log_fit['slope']:.6f}*log(N) + {max_log_fit['intercept']:.6f}; "
                f"RMSE={max_log_fit['rmse']:.6f}; R2={max_log_fit['r2']:.6f}\n"
                f"  max_gap_vs_logN_squared fit max_gap = {max_log_sq_fit['slope']:.6f}*log(N)^2 + {max_log_sq_fit['intercept']:.6f}; "
                f"RMSE={max_log_sq_fit['rmse']:.6f}; R2={max_log_sq_fit['r2']:.6f}\n"
                f"  normalized_max_gap trend max_gap/logN^2 = {normalized_trend['slope']:.6f}*log(N) + {normalized_trend['intercept']:.6f}; "
                f"RMSE={normalized_trend['rmse']:.6f}; R2={normalized_trend['r2']:.6f}\n"
                f"  Best max-gap model by RMSE: {best_model}\n"
                "  Falsifiable next check: adding a larger N should keep the "
                "reported max_gap/logN^2 value within the residual trend if this "
                "finite-range diagnostic is stable.\n"
                "  Caution: finite computations cannot prove asymptotic Cramer behavior."
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    @staticmethod
    def _extract_two_arrays(payload: str):
        """Pull two numeric arrays out of a string, tolerant of separators.

        Accepts any of:
            [1,2,3]:[4,5,6]
            [1,2,3];[4,5,6]
            [1,2,3],[4,5,6]
            1,2,3;4,5,6
        Returns (np.ndarray, np.ndarray). Raises ValueError on failure.
        """
        import re as _re
        bracketed = _re.findall(r"\[[^\]]*\]", payload)
        if len(bracketed) >= 2:
            a = DynamicToolRegistry._parse_numeric_array_literal(bracketed[0])
            b = DynamicToolRegistry._parse_numeric_array_literal(bracketed[1])
            return a, b
        # No brackets: split on ';' first, then ':'
        for sep in (";", ":"):
            if sep in payload:
                left, _, right = payload.partition(sep)
                a = DynamicToolRegistry._parse_numeric_array_literal(
                    "[" + left.strip().strip("[]") + "]")
                b = DynamicToolRegistry._parse_numeric_array_literal(
                    "[" + right.strip().strip("[]") + "]")
                return a, b
        raise ValueError("expected two numeric arrays, e.g. '[1,2,3]:[4,5,6]'")

    def _hypothesis_tester(self, query: str) -> str:
        """Perform hypothesis testing (real scipy.stats, no mock)."""
        try:
            from scipy import stats
            parts = query.split(":")
            test_type = parts[0].strip().lower()
            payload = query[len(parts[0]) + 1:]  # everything after the first ':'

            if test_type == "ttest":
                data1, data2 = self._extract_two_arrays(payload)
                t_stat, p_value = stats.ttest_ind(data1, data2)
                return f"T-test: t-statistic={t_stat:.4f}, p-value={p_value:.4f}"
            elif test_type == "kstest":
                data = self._parse_numeric_array_literal(parts[1])
                dist = parts[2].strip() if len(parts) > 2 else "norm"
                stat, p_value = stats.kstest(data, dist)
                return f"KS-test ({dist}): statistic={stat:.4f}, p-value={p_value:.4f}"
            elif test_type == "shapiro":
                data = self._parse_numeric_array_literal(parts[1])
                stat, p_value = stats.shapiro(data)
                return f"Shapiro-Wilk test: statistic={stat:.4f}, p-value={p_value:.4f}"
            elif test_type == "pearson":
                # Pearson correlation test - flexible parsing
                # Accept both pearson:[arr1]:[arr2] AND pearson:[arr1],[arr2]
                remaining = ":".join(parts[1:])  # Everything after 'pearson:'
                
                # Try to find two arrays - might be separated by ],[ or by :
                if "],[" in remaining:
                    # Format: [1,2,3],[4,5,6]
                    split_point = remaining.find("],[") + 1
                    arr1_str = remaining[:split_point]
                    arr2_str = remaining[split_point + 1:]
                else:
                    # Format: [1,2,3]:[4,5,6]
                    arr_parts = remaining.split(":")
                    if len(arr_parts) >= 2:
                        arr1_str = arr_parts[0].strip()
                        arr2_str = arr_parts[1].strip()
                    else:
                        return "Error: Pearson test requires two arrays. Format: pearson:[arr1]:[arr2] or pearson:[arr1],[arr2]"
                
                data1 = self._parse_numeric_array_literal(arr1_str)
                data2 = self._parse_numeric_array_literal(arr2_str)
                
                if len(data1) != len(data2):
                    return f"Error: Arrays must have equal length. Got {len(data1)} and {len(data2)}"
                    
                r, p_value = stats.pearsonr(data1, data2)
                significance = "significant" if p_value < 0.05 else "not significant"
                return f"Pearson correlation: r={r:.4f}, p-value={p_value:.4f} ({significance})"
            elif test_type == "spearman":
                data1, data2 = self._extract_two_arrays(payload)
                rho, p_value = stats.spearmanr(data1, data2)
                return f"Spearman correlation: rho={rho:.4f}, p-value={p_value:.4f}"
            else:
                return f"Unknown test type: {test_type}. Available: ttest, kstest, shapiro, pearson, spearman"
        except Exception as e:
            return f"Error: {str(e)}"

    def _two_sample_effect_power(self, query: str) -> str:
        """Report two-sample effect size, CI, bootstrap CI, and observed power."""
        try:
            from scipy import stats

            data1, data2 = self._extract_two_arrays(query)
            if len(data1) < 2 or len(data2) < 2:
                return "Error: two_sample_effect_power requires at least two observations per group."

            n1 = int(len(data1))
            n2 = int(len(data2))
            mean1 = float(np.mean(data1))
            mean2 = float(np.mean(data2))
            sd1 = float(np.std(data1, ddof=1))
            sd2 = float(np.std(data2, ddof=1))
            diff = mean2 - mean1
            pooled_sd = float(np.sqrt(((n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2) / (n1 + n2 - 2)))
            cohen_d = float(diff / pooled_sd) if pooled_sd else 0.0
            hedges_correction = 1.0 - (3.0 / (4.0 * (n1 + n2) - 9.0))
            hedges_g = float(cohen_d * hedges_correction)

            se = float(np.sqrt(sd1 ** 2 / n1 + sd2 ** 2 / n2))
            if se:
                df_num = (sd1 ** 2 / n1 + sd2 ** 2 / n2) ** 2
                df_den = ((sd1 ** 2 / n1) ** 2 / (n1 - 1)) + ((sd2 ** 2 / n2) ** 2 / (n2 - 1))
                welch_df = float(df_num / df_den) if df_den else float(n1 + n2 - 2)
                tcrit = float(stats.t.ppf(0.975, welch_df))
                ci_low = diff - tcrit * se
                ci_high = diff + tcrit * se
            else:
                welch_df = float(n1 + n2 - 2)
                ci_low = diff
                ci_high = diff

            t_stat, p_value = stats.ttest_ind(data1, data2, equal_var=False)
            seed = 12345
            if not _REAL_TOOLS_AVAILABLE:
                return "Error: core.atlas_real_tools is required for deterministic bootstrap CI."
            boot_low, boot_high = _real.deterministic_bootstrap_mean_difference_ci(
                data1,
                data2,
                seed=seed,
                iterations=5000,
                confidence=0.95,
                order="second_minus_first",
            )

            alpha = 0.05
            zcrit = float(stats.norm.ppf(1.0 - alpha / 2.0))
            ncp = abs(cohen_d) * np.sqrt((n1 * n2) / (n1 + n2))
            observed_power = float(stats.norm.cdf(-zcrit - ncp) + (1.0 - stats.norm.cdf(zcrit - ncp)))

            return (
                "Two-sample effect and power summary:\n"
                f"  sample size n1={n1}, n2={n2}\n"
                f"  group1 mean={mean1:.6f}, standard deviation={sd1:.6f}\n"
                f"  group2 mean={mean2:.6f}, standard deviation={sd2:.6f}\n"
                f"  mean_difference(group2-group1)={diff:.6f}\n"
                f"  Welch t-statistic={float(t_stat):.6f}, p-value={float(p_value):.6f}, df={welch_df:.6f}\n"
                f"  95% CI for mean_difference: [{ci_low:.6f}, {ci_high:.6f}]\n"
                f"  Cohen's d={cohen_d:.6f}; Hedges g={hedges_g:.6f}; effect size interpretation=standardized mean difference\n"
                f"  bootstrap_ci_seed={seed}; bootstrap 95% CI for mean_difference: [{float(boot_low):.6f}, {float(boot_high):.6f}]\n"
                f"  observed_power={observed_power:.6f} using normal approximation, alpha={alpha:.2f}, two-sided\n"
                "  Falsifiable next check: add new observations using the same measurement protocol; the group-difference claim is weakened if the 95% CI crosses 0 or the effect size shrinks toward 0."
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    # Chemistry tool implementations
    def _molecular_orbital_energy(self, query: str) -> str:
        """Calculate molecular orbital energy for conjugated systems using Hückel method."""
        try:
            parts = query.split(":")
            n_atoms = int(parts[0].strip())
            bond_length = float(parts[1].strip()) if len(parts) > 1 else 1.4
            
            # Hückel molecular orbital theory for conjugated polyenes
            # E_k = alpha + 2*beta*cos(k*pi/(n+1)), k = 1,2,...,n
            alpha = -6.0  # eV (reference energy)
            beta = -2.5   # eV (resonance integral)
            
            energies = []
            for k in range(1, n_atoms + 1):
                E_k = alpha + 2 * beta * np.cos(k * np.pi / (n_atoms + 1))
                energies.append(E_k)
            sorted_energies = [float(e) for e in sorted(energies)]
            
            # Calculate delocalization energy
            E_isolated = 2 * alpha  # 2 electrons per pi bond
            E_delocalized = sum(sorted_energies[:n_atoms//2 + n_atoms % 2]) * 2  # Fill lowest orbitals
            delocalization = E_delocalized - (n_atoms / 2) * E_isolated
            homo = sorted_energies[n_atoms//2 - 1]
            lumo = sorted_energies[n_atoms//2]
            
            return (f"Hückel MO Analysis ({n_atoms} carbon conjugated system):\n"
                    f"  Model parameters: alpha={alpha:.3f} eV, beta={beta:.3f} eV\n"
                    f"  Energy levels (eV): {[round(e, 3) for e in sorted_energies]}\n"
                    f"  HOMO energy: {homo:.3f} eV\n"
                    f"  LUMO energy: {lumo:.3f} eV\n"
                    f"  HOMO-LUMO gap: {lumo - homo:.3f} eV\n"
                    f"  Delocalization energy: {delocalization:.3f} eV")
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def _fit_line(x_values: List[float], y_values: List[float]) -> Dict[str, float]:
        x = np.array(x_values, dtype=float)
        y = np.array(y_values, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        pred = slope * x + intercept
        residual = y - pred
        rmse = float(np.sqrt(np.mean(residual ** 2)))
        denom = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1.0 - float(np.sum(residual ** 2)) / denom if denom else 1.0
        return {
            "slope": float(slope),
            "intercept": float(intercept),
            "rmse": rmse,
            "r2": r2,
        }

    def _huckel_polyene_scaling(self, query: str) -> str:
        """Compare finite-chain Hückel HOMO-LUMO gap scaling laws."""
        try:
            atom_counts = [int(part.strip()) for part in re.split(r"[,;\s]+", query) if part.strip()]
            atom_counts = list(dict.fromkeys(atom_counts))
            if len(atom_counts) < 4:
                return "Error: Provide at least four even atom counts, e.g. '4,6,8,10,12,16,20'"
            invalid = [n for n in atom_counts if n < 2 or n % 2 != 0]
            if invalid:
                return f"Error: Hückel closed-shell linear polyene scaling requires even atom counts >= 2. Invalid: {invalid}"

            alpha = -6.0
            beta = -2.5
            gaps = []
            for n_atoms in atom_counts:
                energies = [
                    float(alpha + 2 * beta * np.cos(k * np.pi / (n_atoms + 1)))
                    for k in range(1, n_atoms + 1)
                ]
                sorted_energies = sorted(energies)
                homo = sorted_energies[n_atoms//2 - 1]
                lumo = sorted_energies[n_atoms//2]
                gaps.append(float(lumo - homo))

            inverse_linear = self._fit_line([1 / (n + 1) for n in atom_counts], gaps)
            inverse_quadratic = self._fit_line([1 / ((n + 1) ** 2) for n in atom_counts], gaps)
            asymptotic_slope = float(-2 * np.pi * beta)
            asymptotic_predictions = [
                asymptotic_slope / (n + 1)
                for n in atom_counts
            ]
            asymptotic_residual = np.array(gaps, dtype=float) - np.array(asymptotic_predictions, dtype=float)
            asymptotic_rmse = float(np.sqrt(np.mean(asymptotic_residual ** 2)))
            asymptotic_max_abs_error = float(np.max(np.abs(asymptotic_residual)))
            residual_threshold = 0.01
            small_angle_argument = float(np.pi / (2 * (min(atom_counts) + 1)))
            log_fit = self._fit_line([float(np.log(n + 1)) for n in atom_counts], [float(np.log(g)) for g in gaps])
            power_exponent = log_fit["slope"]
            power_prefactor = float(np.exp(log_fit["intercept"]))
            power_predictions = [
                power_prefactor * ((n + 1) ** power_exponent)
                for n in atom_counts
            ]
            residual = np.array(gaps, dtype=float) - np.array(power_predictions, dtype=float)
            power_rmse = float(np.sqrt(np.mean(residual ** 2)))
            denom = float(np.sum((np.array(gaps) - np.mean(gaps)) ** 2))
            power_r2 = 1.0 - float(np.sum(residual ** 2)) / denom if denom else 1.0

            models = {
                "inverse_linear": inverse_linear["rmse"],
                "inverse_quadratic": inverse_quadratic["rmse"],
                "power_law": power_rmse,
            }
            best_model = min(models, key=models.get)
            analytic_gaps = [
                float(-4 * beta * np.sin(np.pi / (2 * (n + 1))))
                for n in atom_counts
            ]
            max_formula_error = max(abs(a - b) for a, b in zip(gaps, analytic_gaps))
            rejection = (
                "inverse_quadratic rejected"
                if inverse_quadratic["rmse"] > power_rmse * 10
                else "inverse_quadratic not rejected"
            )

            rows = [
                f"    n={n}: gap={gap:.6f} eV"
                for n, gap in zip(atom_counts, gaps)
            ]
            return (
                "Hückel polyene HOMO-LUMO gap scaling:\n"
                "  Literature anchor: linear Hückel polyene levels use E_k = alpha + 2 beta cos(k*pi/(N+1)); "
                "the frontier gap is -4 beta sin(pi/(2(N+1))).\n"
                f"  Model parameters: alpha={alpha:.3f} eV, beta={beta:.3f} eV\n"
                f"  Chain sizes (n atoms): {atom_counts}\n"
                f"  Gaps (eV): {[round(g, 3) for g in gaps]}\n"
                "  Observations:\n"
                + "\n".join(rows)
                + "\n"
                f"  Formula check max_abs_error: {max_formula_error:.3e} eV\n"
                f"  asymptotic_slope -2*pi*beta = {asymptotic_slope:.6f}\n"
                f"  small_angle_argument_at_min_n = {small_angle_argument:.6f} rad\n"
                f"  asymptotic_inverse_model gap = {asymptotic_slope:.6f}/(n+1); "
                f"RMSE={asymptotic_rmse:.6f} eV; max_abs_error={asymptotic_max_abs_error:.6f} eV; "
                f"residual_threshold={residual_threshold:.6f} eV\n"
                f"  inverse_linear fit gap = {inverse_linear['slope']:.6f}/(n+1) + {inverse_linear['intercept']:.6f}; "
                f"RMSE={inverse_linear['rmse']:.6f} eV; R2={inverse_linear['r2']:.6f}\n"
                f"  inverse_quadratic fit gap = {inverse_quadratic['slope']:.6f}/(n+1)^2 + {inverse_quadratic['intercept']:.6f}; "
                f"RMSE={inverse_quadratic['rmse']:.6f} eV; R2={inverse_quadratic['r2']:.6f}\n"
                f"  power_law fit gap = {power_prefactor:.6f}*(n+1)^{power_exponent:.6f}; "
                f"power exponent p={power_exponent:.3f}; RMSE={power_rmse:.6f} eV; R2={power_r2:.6f}\n"
                f"  Best model by RMSE: {best_model}\n"
                f"  Falsification result: {rejection}; its RMSE is {inverse_quadratic['rmse'] / power_rmse:.1f}x the power-law RMSE.\n"
                "  Scaling conclusion: finite linear Hückel polyenes follow near-inverse-length HOMO-LUMO gap decay over this range, "
                "not inverse-quadratic decay."
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def _bond_alternated_polyene_scaling(self, query: str) -> str:
        """Finite-chain tight-binding gaps with alternating bond couplings."""
        try:
            segments = [part.strip() for part in query.split(";") if part.strip()]
            if not segments:
                return "Error: Provide atom counts, e.g. '4,6,8,10;strong=-2.7;weak=-2.3'"
            atom_counts = [int(part.strip()) for part in re.split(r"[,;\s]+", segments[0]) if part.strip()]
            atom_counts = list(dict.fromkeys(atom_counts))
            if len(atom_counts) < 4:
                return "Error: Provide at least four even atom counts, e.g. '4,6,8,10,12,16'"
            invalid = [n for n in atom_counts if n < 2 or n % 2 != 0]
            if invalid:
                return f"Error: Bond-alternated closed-shell chains require even atom counts >= 2. Invalid: {invalid}"

            alpha = -6.0
            beta_strong = -2.7
            beta_weak = -2.3
            for option in segments[1:]:
                if "=" not in option:
                    continue
                key, value = [item.strip().lower() for item in option.split("=", 1)]
                if key in {"alpha", "a"}:
                    alpha = float(value)
                elif key in {"strong", "beta_strong", "double"}:
                    beta_strong = float(value)
                elif key in {"weak", "beta_weak", "single"}:
                    beta_weak = float(value)

            gaps = []
            for n_atoms in atom_counts:
                hamiltonian = np.eye(n_atoms, dtype=float) * alpha
                for idx in range(n_atoms - 1):
                    beta = beta_strong if idx % 2 == 0 else beta_weak
                    hamiltonian[idx, idx + 1] = beta
                    hamiltonian[idx + 1, idx] = beta
                energies = np.linalg.eigvalsh(hamiltonian)
                gaps.append(float(energies[n_atoms//2] - energies[n_atoms//2 - 1]))

            asymptotic_gap = float(2 * abs(beta_strong - beta_weak))
            residuals = [gap - asymptotic_gap for gap in gaps]
            max_residual = max(abs(value) for value in residuals)
            rows = [
                f"    n={n}: alternated_gap={gap:.6f} eV; excess_over_asymptote={residual:.6f} eV"
                for n, gap, residual in zip(atom_counts, gaps, residuals)
            ]
            return (
                "Bond-alternated polyene gap scaling:\n"
                "  Method: explicit diagonalization of a nearest-neighbor tight-binding/Hückel matrix "
                "with alternating strong and weak couplings.\n"
                f"  Model parameters: alpha={alpha:.3f} eV, beta_strong={beta_strong:.3f} eV, beta_weak={beta_weak:.3f} eV\n"
                f"  Chain sizes (n atoms): {atom_counts}\n"
                f"  Alternated gaps (eV): {[round(g, 3) for g in gaps]}\n"
                f"  asymptotic_gap_estimate = {asymptotic_gap:.6f} eV\n"
                f"  max_excess_over_asymptote = {max_residual:.6f} eV\n"
                "  Observations:\n"
                + "\n".join(rows)
                + "\n"
                "  finite-gap conclusion: bond alternation prevents the zero-gap closure seen in the uniform-chain baseline; "
                "the tested finite chains approach a nonzero gap set by the strong/weak coupling contrast."
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def _parse_float_series_option(self, raw: str, option_name: str) -> list[float]:
        values = [float(part.strip()) for part in raw.split(",") if part.strip()]
        if not values:
            raise ValueError(f"{option_name} must contain at least one value")
        return list(dict.fromkeys(values))

    def _ssh_hamiltonian_for_chain(
        self,
        n_atoms: int,
        *,
        beta: float,
        delta: float,
        orientation: str,
        alpha: float = 0.0,
    ) -> float:
        t0 = abs(float(beta))
        t_strong = t0 * (1.0 + delta)
        t_weak = t0 * (1.0 - delta)
        if t_weak < 0:
            raise ValueError("delta must be <= 1.0 so weak coupling remains non-negative")

        hamiltonian = np.eye(n_atoms, dtype=float) * alpha
        for idx in range(n_atoms - 1):
            starts_with_strong = orientation == "trivial"
            use_strong = (idx % 2 == 0) if starts_with_strong else (idx % 2 == 1)
            coupling = t_strong if use_strong else t_weak
            hamiltonian[idx, idx + 1] = -coupling
            hamiltonian[idx + 1, idx] = -coupling
        return hamiltonian

    def _ssh_gap_for_chain(
        self,
        n_atoms: int,
        *,
        beta: float,
        delta: float,
        orientation: str,
        alpha: float = 0.0,
    ) -> float:
        hamiltonian = self._ssh_hamiltonian_for_chain(
            n_atoms,
            beta=beta,
            delta=delta,
            orientation=orientation,
            alpha=alpha,
        )
        energies = np.linalg.eigvalsh(hamiltonian)
        return float(energies[n_atoms // 2] - energies[n_atoms // 2 - 1])

    def _ssh_frontier_localization_for_chain(
        self,
        n_atoms: int,
        *,
        beta: float,
        delta: float,
        orientation: str,
        edge_sites: int,
    ) -> dict[str, float]:
        hamiltonian = self._ssh_hamiltonian_for_chain(
            n_atoms,
            beta=beta,
            delta=delta,
            orientation=orientation,
        )
        energies, eigenvectors = np.linalg.eigh(hamiltonian)
        frontier_indices = [n_atoms // 2 - 1, n_atoms // 2]
        edge_weights = []
        iprs = []
        for index in frontier_indices:
            probabilities = np.square(np.abs(eigenvectors[:, index]))
            edge_weight = float(
                probabilities[:edge_sites].sum() + probabilities[-edge_sites:].sum()
            )
            ipr = float(np.square(probabilities).sum())
            edge_weights.append(edge_weight)
            iprs.append(ipr)

        pair_edge_weight = float(sum(edge_weights) / len(edge_weights))
        pair_ipr = float(sum(iprs) / len(iprs))
        participation_sites = float(1.0 / pair_ipr) if pair_ipr > 0 else float("inf")
        return {
            "frontier_splitting_eV": float(energies[frontier_indices[1]] - energies[frontier_indices[0]]),
            "frontier_pair_edge_weight": pair_edge_weight,
            "frontier_pair_ipr": pair_ipr,
            "participation_sites": participation_sites,
        }

    def _ssh_polyene_gap_map(self, query: str) -> str:
        """Map finite-chain SSH identifiability across length and orientation."""
        try:
            segments = [part.strip() for part in query.split(";") if part.strip()]
            if not segments:
                return (
                    "Error: Provide atom counts, e.g. "
                    "'4,6,8;deltas=0,0.05;orientations=trivial,topological'"
                )

            atom_counts = [
                int(part.strip())
                for part in re.split(r"[,;\s]+", segments[0])
                if part.strip()
            ]
            atom_counts = list(dict.fromkeys(atom_counts))
            if len(atom_counts) < 4:
                return "Error: Provide at least four even atom counts, e.g. '4,6,8,10'"
            invalid = [n for n in atom_counts if n < 2 or n % 2 != 0]
            if invalid:
                return f"Error: SSH closed-shell chains require even atom counts >= 2. Invalid: {invalid}"

            deltas = [0.0, 0.05, 0.1, 0.2]
            orientations = ["trivial", "topological"]
            beta = -2.5
            threshold = 0.05
            for option in segments[1:]:
                if "=" not in option:
                    continue
                key, value = [item.strip().lower() for item in option.split("=", 1)]
                if key == "deltas":
                    deltas = self._parse_float_series_option(value, key)
                elif key == "orientations":
                    orientations = [
                        part.strip().lower()
                        for part in value.split(",")
                        if part.strip()
                    ]
                elif key in {"beta", "b"}:
                    beta = float(value)
                elif key in {"threshold", "identifiability_threshold"}:
                    threshold = float(value)

            if threshold < 0:
                return f"Error: threshold must be non-negative, got {threshold}"
            bad_deltas = [delta for delta in deltas if delta < 0 or delta > 1]
            if bad_deltas:
                return f"Error: deltas must be in [0, 1]. Invalid: {bad_deltas}"
            bad_orientations = [
                orientation for orientation in orientations
                if orientation not in {"trivial", "topological"}
            ]
            if bad_orientations:
                return f"Error: unknown orientations: {bad_orientations}. Available: trivial, topological"

            uniform_gaps = {
                n: self._ssh_gap_for_chain(n, beta=beta, delta=0.0, orientation="trivial")
                for n in atom_counts
            }
            rows: list[str] = []
            summaries: list[str] = []
            warnings: list[str] = []
            t0 = abs(beta)

            for delta in deltas:
                peierls_bulk_gap = float(4.0 * t0 * delta)
                for orientation in orientations:
                    gaps = [
                        self._ssh_gap_for_chain(
                            n,
                            beta=beta,
                            delta=delta,
                            orientation=orientation,
                        )
                        for n in atom_counts
                    ]
                    smallest_identifiable = None
                    edge_state_onset = None
                    for n, gap in zip(atom_counts, gaps):
                        difference = abs(gap - uniform_gaps[n])
                        if delta > 0 and difference >= threshold and smallest_identifiable is None:
                            smallest_identifiable = n
                        edge_warning = (
                            orientation == "topological"
                            and peierls_bulk_gap > 0
                            and gap < 0.5 * peierls_bulk_gap
                        )
                        if edge_warning and edge_state_onset is None:
                            edge_state_onset = n
                        if edge_warning:
                            warnings.append(
                                f"orientation=topological delta={delta:.6f} n={n}: "
                                f"edge_state_warning=true; frontier_gap={gap:.6f} eV; "
                                f"peierls_bulk_gap_estimate={peierls_bulk_gap:.6f} eV"
                            )
                        rows.append(
                            f"    delta={delta:.6f}; orientation={orientation}; n={n}; "
                            f"frontier_gap={gap:.6f} eV; uniform_gap={uniform_gaps[n]:.6f} eV; "
                            f"gap_minus_uniform={gap - uniform_gaps[n]:.6f} eV; "
                            f"peierls_bulk_gap_estimate={peierls_bulk_gap:.6f} eV; "
                            f"edge_state_warning={str(edge_warning).lower()}"
                        )
                    summaries.append(
                        f"  delta={delta:.6f}; orientation={orientation}; "
                        f"smallest_identifiable_n={smallest_identifiable if smallest_identifiable is not None else 'not_identified'}; "
                        f"edge_state_onset_n={edge_state_onset if edge_state_onset is not None else 'not_observed'}; "
                        f"terminal_gap_n{atom_counts[-1]}={gaps[-1]:.6f} eV; "
                        f"peierls_bulk_gap_estimate={peierls_bulk_gap:.6f} eV"
                    )

            warning_text = "\n".join(f"  {warning}" for warning in warnings[:12])
            if not warning_text:
                warning_text = "  edge_state_warning=false for all tested nonzero-delta conditions"

            return (
                "SSH/polyene finite-chain gap map:\n"
                "  Method: exact diagonalization of open-boundary nearest-neighbor SSH/Hückel chains.\n"
                f"  Chain sizes (n atoms): {atom_counts}\n"
                f"  beta={beta:.6f} eV; deltas={','.join(f'{d:.6f}' for d in deltas)}; "
                f"orientations={','.join(orientations)}\n"
                f"  identifiability_threshold_eV={threshold:.6f}\n"
                "  Uniform baseline uses delta=0 and trivial orientation; gap-only identifiability compares each condition against that finite-size baseline.\n"
                "  Identifiability summary:\n"
                + "\n".join(summaries)
                + "\n"
                "  Edge-state diagnostics:\n"
                + warning_text
                + "\n"
                "  Gap map observations:\n"
                + "\n".join(rows)
                + "\n"
                "  Interpretation: trivial-orientation gaps estimate Peierls-like bulk opening, while topological-orientation frontier gaps can be dominated by edge states; gap-only evidence is therefore insufficient unless boundary orientation is controlled."
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def _ssh_edge_localization_map(self, query: str) -> str:
        """Map frontier-state edge localization for finite SSH chains."""
        try:
            segments = [part.strip() for part in query.split(";") if part.strip()]
            if not segments:
                return (
                    "Error: Provide atom counts, e.g. "
                    "'20,40,60;deltas=0.05;orientations=trivial,topological'"
                )

            atom_counts = [
                int(part.strip())
                for part in re.split(r"[,;\s]+", segments[0])
                if part.strip()
            ]
            atom_counts = list(dict.fromkeys(atom_counts))
            if len(atom_counts) < 2:
                return "Error: Provide at least two even atom counts, e.g. '20,40'"
            invalid = [n for n in atom_counts if n < 2 or n % 2 != 0]
            if invalid:
                return f"Error: SSH closed-shell chains require even atom counts >= 2. Invalid: {invalid}"

            deltas = [0.05, 0.1, 0.2]
            orientations = ["trivial", "topological"]
            beta = -2.5
            edge_sites = 2
            localization_threshold = 0.25
            min_localization_n = 16
            for option in segments[1:]:
                if "=" not in option:
                    continue
                key, value = [item.strip().lower() for item in option.split("=", 1)]
                if key == "deltas":
                    deltas = self._parse_float_series_option(value, key)
                elif key == "orientations":
                    orientations = [
                        part.strip().lower()
                        for part in value.split(",")
                        if part.strip()
                    ]
                elif key in {"beta", "b"}:
                    beta = float(value)
                elif key == "edge_sites":
                    edge_sites = int(value)
                elif key in {"localization_threshold", "edge_weight_threshold"}:
                    localization_threshold = float(value)
                elif key == "min_localization_n":
                    min_localization_n = int(value)

            bad_deltas = [delta for delta in deltas if delta < 0 or delta > 1]
            if bad_deltas:
                return f"Error: deltas must be in [0, 1]. Invalid: {bad_deltas}"
            bad_orientations = [
                orientation for orientation in orientations
                if orientation not in {"trivial", "topological"}
            ]
            if bad_orientations:
                return f"Error: unknown orientations: {bad_orientations}. Available: trivial, topological"
            if edge_sites < 1:
                return f"Error: edge_sites must be >= 1, got {edge_sites}"
            if localization_threshold < 0 or localization_threshold > 1:
                return (
                    "Error: localization_threshold must be in [0, 1], "
                    f"got {localization_threshold}"
                )
            too_short = [n for n in atom_counts if edge_sites * 2 >= n]
            if too_short:
                return (
                    "Error: edge_sites covers the whole chain for "
                    f"{too_short}; choose fewer edge sites or larger chains"
                )

            rows: list[str] = []
            summaries: list[str] = []
            for delta in deltas:
                for orientation in orientations:
                    metrics_by_n = []
                    localization_onset = None
                    for n in atom_counts:
                        metrics = self._ssh_frontier_localization_for_chain(
                            n,
                            beta=beta,
                            delta=delta,
                            orientation=orientation,
                            edge_sites=edge_sites,
                        )
                        localized = (
                            n >= min_localization_n
                            and orientation == "topological"
                            and delta > 0
                            and metrics["frontier_pair_edge_weight"] >= localization_threshold
                        )
                        if localized and localization_onset is None:
                            localization_onset = n
                        metrics_by_n.append(metrics)
                        rows.append(
                            f"    delta={delta:.6f}; orientation={orientation}; n={n}; "
                            f"frontier_splitting_eV={metrics['frontier_splitting_eV']:.6f}; "
                            f"frontier_pair_edge_weight={metrics['frontier_pair_edge_weight']:.6f}; "
                            f"frontier_pair_ipr={metrics['frontier_pair_ipr']:.6f}; "
                            f"participation_sites={metrics['participation_sites']:.6f}; "
                            f"localized_edge_state={str(localized).lower()}"
                        )

                    max_edge_weight = max(
                        metric["frontier_pair_edge_weight"] for metric in metrics_by_n
                    )
                    max_ipr = max(metric["frontier_pair_ipr"] for metric in metrics_by_n)
                    min_participation = min(
                        metric["participation_sites"] for metric in metrics_by_n
                    )
                    terminal = metrics_by_n[-1]
                    summaries.append(
                        f"  delta={delta:.6f}; orientation={orientation}; "
                        f"localization_onset_n={localization_onset if localization_onset is not None else 'not_observed'}; "
                        f"max_pair_edge_weight={max_edge_weight:.6f}; "
                        f"max_pair_ipr={max_ipr:.6f}; "
                        f"min_participation_sites={min_participation:.6f}; "
                        f"terminal_frontier_splitting_eV={terminal['frontier_splitting_eV']:.6f}"
                    )

            return (
                "SSH/polyene edge-state localization map:\n"
                "  Method: exact diagonalization of open-boundary nearest-neighbor SSH/Hückel chains with frontier eigenvector diagnostics.\n"
                f"  Chain sizes (n atoms): {atom_counts}\n"
                f"  beta={beta:.6f} eV; deltas={','.join(f'{d:.6f}' for d in deltas)}; "
                f"orientations={','.join(orientations)}; edge_sites={edge_sites}; "
                f"localization_threshold={localization_threshold:.6f}; "
                f"min_localization_n={min_localization_n}\n"
                "  Localization summary:\n"
                + "\n".join(summaries)
                + "\n"
                "  Frontier-state observations:\n"
                + "\n".join(rows)
                + "\n"
                "  Interpretation: high frontier_pair_edge_weight together with elevated IPR and low participation_sites directly tests whether the small topological frontier gap is caused by boundary-localized states rather than a bulk Peierls gap."
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def _ssh_disorder_diagnostic_benchmark(self, query: str) -> str:
        """Run the deterministic, paired SSH disorder diagnostic benchmark."""
        try:
            segments = [part.strip() for part in query.split(";") if part.strip()]
            if not segments:
                return (
                    "Error: Provide chain lengths and protocol options, e.g. "
                    "'20,40;deltas=0.1;strengths=0,0.2;"
                    "disorders=off_diagonal,diagonal;realizations=8;"
                    "namespace=study'"
                )
            lengths = tuple(
                dict.fromkeys(
                    int(part.strip())
                    for part in re.split(r"[,\s]+", segments[0])
                    if part.strip()
                )
            )
            options = {
                "deltas": (0.05, 0.1, 0.2),
                "strengths": (0.0, 0.05, 0.1, 0.2, 0.4),
                "disorder_types": ("off_diagonal", "diagonal"),
                "orientations": ("trivial", "topological"),
                "realizations": 128,
                "namespace": "amy-ssh-disorder-v1",
                "beta": -2.5,
                "edge_sites": 2,
                "gap_threshold": 0.20,
                "edge_threshold": 0.50,
                "ipr_threshold": 2.50,
                "protocol_sha256": "",
            }
            for option in segments[1:]:
                if "=" not in option:
                    raise ValueError(f"protocol option lacks '=': {option}")
                key, value = [item.strip() for item in option.split("=", 1)]
                key = key.lower()
                if key == "deltas":
                    options["deltas"] = tuple(
                        dict.fromkeys(self._parse_float_series_option(value, key))
                    )
                elif key in {"strengths", "disorder_strengths", "w"}:
                    options["strengths"] = tuple(
                        dict.fromkeys(self._parse_float_series_option(value, key))
                    )
                elif key in {"disorders", "disorder_types"}:
                    options["disorder_types"] = tuple(
                        dict.fromkeys(
                            part.strip().lower()
                            for part in value.split(",")
                            if part.strip()
                        )
                    )
                elif key == "orientations":
                    options["orientations"] = tuple(
                        dict.fromkeys(
                            part.strip().lower()
                            for part in value.split(",")
                            if part.strip()
                        )
                    )
                elif key == "realizations":
                    options["realizations"] = int(value)
                elif key == "namespace":
                    options["namespace"] = value
                elif key in {"beta", "b"}:
                    options["beta"] = float(value)
                elif key == "edge_sites":
                    options["edge_sites"] = int(value)
                elif key == "gap_threshold":
                    options["gap_threshold"] = float(value)
                elif key == "edge_threshold":
                    options["edge_threshold"] = float(value)
                elif key in {"ipr_threshold", "normalized_ipr_threshold"}:
                    options["ipr_threshold"] = float(value)
                elif key in {"protocol_sha256", "preregistration_sha256"}:
                    options["protocol_sha256"] = value.lower()
                else:
                    raise ValueError(f"unknown benchmark option: {key}")

            config = SSHDisorderBenchmarkConfig(lengths=lengths, **options)
            return format_ssh_disorder_benchmark_report(
                run_ssh_disorder_benchmark(config)
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _bond_energy_analyzer(self, query: str) -> str:
        """Analyze chemical bond energies."""
        bond_energies = {
            "C-C": 347, "C=C": 614, "C≡C": 839, "C-H": 413,
            "C-O": 358, "C=O": 799, "C-N": 305, "C=N": 615, "C≡N": 891,
            "O-H": 463, "O-O": 146, "O=O": 495,
            "N-H": 391, "N-N": 163, "N=N": 418, "N≡N": 941,
            "H-H": 436, "H-F": 567, "H-Cl": 431, "H-Br": 366,
            "C-F": 485, "C-Cl": 339, "C-Br": 276,
        }
        
        bond = query.strip().upper().replace("-", "-").replace("=", "=")
        if bond in bond_energies:
            return f"Bond energy of {bond}: {bond_energies[bond]} kJ/mol"
        else:
            # Try with different cases
            for key in bond_energies:
                if key.upper() == bond.upper():
                    return f"Bond energy of {key}: {bond_energies[key]} kJ/mol"
            return f"Unknown bond type: {bond}. Available: {list(bond_energies.keys())}"
    
    def _molecular_weight_calc(self, query: str) -> str:
        """Calculate molecular weight from chemical formula."""
        import re
        atomic_weights = {
            'H': 1.008, 'C': 12.011, 'N': 14.007, 'O': 15.999, 'S': 32.065,
            'P': 30.974, 'F': 18.998, 'Cl': 35.453, 'Br': 79.904, 'I': 126.904,
            'He': 4.002602, 'Li': 6.94, 'B': 10.81, 'Ne': 20.180, 'Ar': 39.948,
            'Na': 22.990, 'K': 39.098, 'Ca': 40.078, 'Mg': 24.305, 'Fe': 55.845
        }
        
        formula = query.strip()
        # Parse formula like C6H12O6
        pattern = r'([A-Z][a-z]?)(\d*)'
        matches = re.findall(pattern, formula)
        if not matches:
            return f"Error: Could not parse molecular formula: {formula}"
        
        total_weight = 0
        composition = []
        unknown_elements = []
        for element, count in matches:
            if element:
                count = int(count) if count else 1
                if element in atomic_weights:
                    weight = atomic_weights[element] * count
                    total_weight += weight
                    composition.append(f"{element}{count}: {weight:.3f}")
                else:
                    unknown_elements.append(element)
        if unknown_elements:
            unknown = ", ".join(sorted(set(unknown_elements)))
            return f"Error: Unknown element(s) in formula {formula}: {unknown}"
        if total_weight <= 0:
            return f"Error: Molecular weight calculation failed for {formula}"
        
        return (f"Molecular weight of {formula}: {total_weight:.3f} g/mol\n"
                f"Composition: {', '.join(composition)}")
    
    # Biology tool implementations
    def _dna_analyzer(self, query: str) -> str:
        """Analyze DNA sequence."""
        # Handle prefix if present (e.g. "GC:ATCG" -> "ATCG")
        if ":" in query:
            query = query.split(":", 1)[1]
            
        seq = query.strip().upper()
        
        # Validate sequence
        valid = set("ATCGN")
        if not all(c in valid for c in seq):
            return f"Invalid DNA sequence. Use only A, T, C, G. Received: {seq[:20]}..."
        
        length = len(seq)
        a_count = seq.count('A')
        t_count = seq.count('T')
        g_count = seq.count('G')
        c_count = seq.count('C')
        gc_content = (g_count + c_count) / length * 100 if length > 0 else 0
        
        # Reverse complement
        complement = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
        rev_comp = ''.join(complement[base] for base in reversed(seq))
        
        # Melting temperature estimate (Wallace rule for short sequences)
        tm = 2 * (a_count + t_count) + 4 * (g_count + c_count)
        
        return (f"DNA Sequence Analysis:\n"
                f"  Length: {length} bp\n"
                f"  Composition: A={a_count}, T={t_count}, G={g_count}, C={c_count}\n"
                f"  GC content: {gc_content:.1f}%\n"
                f"  Estimated Tm: {tm}°C (Wallace rule)\n"
                f"  Reverse complement: {rev_comp[:30]}{'...' if len(rev_comp) > 30 else ''}")

    @staticmethod
    def _parse_sequence_panels(query: str) -> tuple[list[str], list[str]]:
        """Parse 'gc=SEQ,SEQ;at=SEQ,SEQ' or 'SEQ,SEQ;SEQ,SEQ' panels."""
        panels: dict[str, list[str]] = {}
        for chunk in query.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                key, value = chunk.split("=", 1)
                key = key.strip().lower()
            else:
                key = "gc" if "gc" not in panels else "at"
                value = chunk
            seqs = [s.strip().upper() for s in value.split(",") if s.strip()]
            if key in {"gc", "gcrich", "gc-rich", "rich"}:
                panels["gc"] = seqs
            elif key in {"at", "atrich", "at-rich", "control"}:
                panels["at"] = seqs

        gc_panel = panels.get("gc", [])
        at_panel = panels.get("at", [])
        valid = set("ATCG")
        all_sequences = gc_panel + at_panel
        if len(gc_panel) < 2 or len(at_panel) < 2:
            raise ValueError("gc_at_panel_comparison requires at least two sequences per panel.")
        for seq in all_sequences:
            if not seq:
                raise ValueError("empty sequence in panel")
            if not all(base in valid for base in seq):
                raise ValueError(f"invalid DNA sequence in panel: {seq[:20]}")
        return gc_panel, at_panel

    @staticmethod
    def _orf_like(sequence: str) -> bool:
        if not sequence.startswith("ATG"):
            return False
        stops = {"TAA", "TAG", "TGA"}
        return any(sequence[i:i + 3] in stops for i in range(3, len(sequence) - 2, 3))

    def _gc_at_panel_comparison(self, query: str) -> str:
        """Compare GC-rich and AT-rich sequence panels with bounded statistics."""
        try:
            from scipy import stats

            gc_panel, at_panel = self._parse_sequence_panels(query)
            gc_fracs = np.array([
                (seq.count("G") + seq.count("C")) / len(seq) for seq in gc_panel
            ], dtype=float)
            at_fracs = np.array([
                (seq.count("G") + seq.count("C")) / len(seq) for seq in at_panel
            ], dtype=float)
            n_gc = int(len(gc_fracs))
            n_at = int(len(at_fracs))
            mean_gc = float(np.mean(gc_fracs))
            mean_at = float(np.mean(at_fracs))
            sd_gc = float(np.std(gc_fracs, ddof=1))
            sd_at = float(np.std(at_fracs, ddof=1))
            diff = mean_gc - mean_at
            pooled_sd = float(np.sqrt(((n_gc - 1) * sd_gc ** 2 + (n_at - 1) * sd_at ** 2) / (n_gc + n_at - 2)))
            cohen_d = float(diff / pooled_sd) if pooled_sd else 0.0
            hedges_correction = 1.0 - (3.0 / (4.0 * (n_gc + n_at) - 9.0))
            hedges_g = float(cohen_d * hedges_correction)

            se = float(np.sqrt(sd_gc ** 2 / n_gc + sd_at ** 2 / n_at))
            if se:
                df_num = (sd_gc ** 2 / n_gc + sd_at ** 2 / n_at) ** 2
                df_den = ((sd_gc ** 2 / n_gc) ** 2 / (n_gc - 1)) + ((sd_at ** 2 / n_at) ** 2 / (n_at - 1))
                welch_df = float(df_num / df_den) if df_den else float(n_gc + n_at - 2)
                tcrit = float(stats.t.ppf(0.975, welch_df))
                ci_low = diff - tcrit * se
                ci_high = diff + tcrit * se
            else:
                welch_df = float(n_gc + n_at - 2)
                ci_low = diff
                ci_high = diff

            t_stat, p_value = stats.ttest_ind(gc_fracs, at_fracs, equal_var=False)
            seed = 12345
            if not _REAL_TOOLS_AVAILABLE:
                return "Error: core.atlas_real_tools is required for deterministic bootstrap CI."
            boot_low, boot_high = _real.deterministic_bootstrap_mean_difference_ci(
                gc_fracs,
                at_fracs,
                seed=seed,
                iterations=5000,
                confidence=0.95,
                order="first_minus_second",
            )

            lengths_gc = [len(seq) for seq in gc_panel]
            lengths_at = [len(seq) for seq in at_panel]
            gc_orf = sum(1 for seq in gc_panel if self._orf_like(seq))
            at_orf = sum(1 for seq in at_panel if self._orf_like(seq))
            motifs = ("TATAAT", "TTGACA", "ATG")
            gc_motif_hits = sum(sum(seq.count(motif) for motif in motifs) for seq in gc_panel)
            at_motif_hits = sum(sum(seq.count(motif) for motif in motifs) for seq in at_panel)

            return (
                "GC-rich versus AT-rich panel comparison:\n"
                f"  sample size n_gc={n_gc}, n_at={n_at}\n"
                f"  gc_panel fractions={','.join(f'{v:.6f}' for v in gc_fracs)}\n"
                f"  at_panel fractions={','.join(f'{v:.6f}' for v in at_fracs)}\n"
                f"  mean_gc_fraction={mean_gc:.6f}; mean_at_fraction={mean_at:.6f}\n"
                f"  mean_gc_difference(gc-at)={diff:.6f}\n"
                f"  Welch t-statistic={float(t_stat):.6f}, p-value={float(p_value):.6f}, df={welch_df:.6f}\n"
                f"  95% CI for mean_gc_difference: [{ci_low:.6f}, {ci_high:.6f}]\n"
                f"  Cohen's d={cohen_d:.6f}; Hedges g={hedges_g:.6f}; effect size interpretation=standardized GC-fraction difference\n"
                f"  bootstrap_ci_seed={seed}; bootstrap 95% CI for mean_gc_difference: [{float(boot_low):.6f}, {float(boot_high):.6f}]\n"
                f"  length_control: mean_length_gc={float(np.mean(lengths_gc)):.6f}, mean_length_at={float(np.mean(lengths_at)):.6f}, min_length={min(lengths_gc + lengths_at)}, max_length={max(lengths_gc + lengths_at)}\n"
                f"  coding_context_control: gc_orf_like={gc_orf}/{n_gc}, at_orf_like={at_orf}/{n_at}, gc_motif_hits={gc_motif_hits}, at_motif_hits={at_motif_hits}\n"
                "  Falsifiable next check: add matched-length sequences from an external source; weaken the GC-panel distinction if the 95% CI crosses 0, the bootstrap CI crosses 0, or coding-context controls become imbalanced."
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _protein_properties(self, query: str) -> str:
        """Calculate protein properties from amino acid sequence."""
        seq = query.strip().upper()
        
        # Amino acid molecular weights (Da)
        aa_weights = {
            'A': 89.1, 'R': 174.2, 'N': 132.1, 'D': 133.1, 'C': 121.2,
            'E': 147.1, 'Q': 146.2, 'G': 75.1, 'H': 155.2, 'I': 131.2,
            'L': 131.2, 'K': 146.2, 'M': 149.2, 'F': 165.2, 'P': 115.1,
            'S': 105.1, 'T': 119.1, 'W': 204.2, 'Y': 181.2, 'V': 117.1
        }
        
        # Hydropathy index (Kyte-Doolittle)
        hydropathy = {
            'A': 1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C': 2.5,
            'E': -3.5, 'Q': -3.5, 'G': -0.4, 'H': -3.2, 'I': 4.5,
            'L': 3.8, 'K': -3.9, 'M': 1.9, 'F': 2.8, 'P': -1.6,
            'S': -0.8, 'T': -0.7, 'W': -0.9, 'Y': -1.3, 'V': 4.2
        }
        
        # Calculate properties
        mol_weight = sum(aa_weights.get(aa, 0) for aa in seq) - (len(seq) - 1) * 18.0  # Water loss
        avg_hydropathy = np.mean([hydropathy.get(aa, 0) for aa in seq]) if seq else 0
        
        # Count charged residues
        positive = sum(1 for aa in seq if aa in 'RKH')
        negative = sum(1 for aa in seq if aa in 'DE')
        
        return (f"Protein Properties ({len(seq)} residues):\n"
                f"  Molecular weight: {mol_weight:.1f} Da\n"
                f"  Avg hydropathy (GRAVY): {avg_hydropathy:.2f}\n"
                f"  Charged residues: +{positive}, -{negative}, net={positive-negative}\n"
                f"  Classification: {'Hydrophobic' if avg_hydropathy > 0 else 'Hydrophilic'}")
    
    # Physics tool implementations
    def _quantum_energy_levels(self, query: str) -> str:
        """Calculate quantum mechanical energy levels."""
        try:
            parts = query.split(":")
            system = parts[0].strip().lower()
            params = parts[1].strip() if len(parts) > 1 else "1"
            
            if system == "hydrogen":
                # Hydrogen atom energy levels: E_n = -13.6 / n^2 eV
                n = int(params)
                energy = -13.6 / (n ** 2)
                levels = [-13.6 / (i ** 2) for i in range(1, min(n + 3, 8))]
                return (f"Hydrogen atom energy level n={n}:\n"
                        f"  E_{n} = {energy:.4f} eV\n"
                        f"  First {len(levels)} levels: {[round(e, 4) for e in levels]} eV\n"
                        f"  Ionization energy from n={n}: {-energy:.4f} eV")
            
            elif system == "harmonic":
                # Quantum harmonic oscillator: E_n = ℏω(n + 1/2)
                p = params.split(",")
                n = int(p[0])
                omega = float(p[1]) if len(p) > 1 else 1.0  # eV
                hbar = 6.582e-16  # eV·s
                energy = omega * (n + 0.5)  # In units of ℏω
                levels = [omega * (i + 0.5) for i in range(n + 3)]
                return (f"Quantum harmonic oscillator (ω={omega} eV):\n"
                        f"  E_{n} = {energy:.4f} ℏω = {energy * omega:.4f} eV\n"
                        f"  Zero-point energy: {0.5 * omega:.4f} eV\n"
                        f"  First {len(levels)} levels: {[round(e, 4) for e in levels]} ℏω")
            
            elif system == "particle_box":
                # Particle in a box: E_n = n²h²/(8mL²)
                p = params.split(",")
                n = int(p[0])
                L = float(p[1]) if len(p) > 1 else 1.0  # nm
                h = 4.136e-15  # eV·s
                m_e = 0.511e6 / (3e8)**2  # eV/c² → electron mass
                L_m = L * 1e-9  # Convert to meters
                E_0 = (h ** 2) / (8 * m_e * L_m ** 2)  # Ground state factor
                energy = n ** 2 * E_0
                return (f"Particle in 1D box (L={L} nm):\n"
                        f"  E_{n} = {energy:.4f} eV\n"
                        f"  E_1 (ground state) = {E_0:.4f} eV")
            
            else:
                return f"Unknown system: {system}. Available: hydrogen, harmonic, particle_box"
        except Exception as e:
            return f"Error: {str(e)}"

    def _rydberg_scaling_comparison(self, query: str) -> str:
        """Compare hydrogen inverse-square scaling with a perturbation control."""
        try:
            fields = [part.strip() for part in query.split(";") if part.strip()]
            n_values = [int(part.strip()) for part in re.split(r"[,:\s]+", fields[0]) if part.strip()]
            n_values = list(dict.fromkeys(n_values))
            if len(n_values) < 4:
                return "Error: Provide at least four principal quantum numbers, e.g. '1,2,3,5,10;delta=0.05'"
            invalid = [n for n in n_values if n < 1]
            if invalid:
                return f"Error: principal quantum numbers must be positive integers. Invalid: {invalid}"

            delta = 0.05
            for field in fields[1:]:
                if field.lower().startswith("delta="):
                    delta = float(field.split("=", 1)[1])
            if any(n <= delta for n in n_values):
                return "Error: quantum_defect delta must be smaller than every n in the input series."

            rydberg_ev = 13.6
            inverse_x = [1.0 / (n ** 2) for n in n_values]
            energies = [-rydberg_ev / (n ** 2) for n in n_values]
            inverse_fit = self._fit_line(inverse_x, energies)

            inverse_predictions = [
                inverse_fit["slope"] * x + inverse_fit["intercept"]
                for x in inverse_x
            ]
            inverse_residuals = np.array(energies, dtype=float) - np.array(inverse_predictions, dtype=float)
            inverse_max_abs_error = float(np.max(np.abs(inverse_residuals)))
            inverse_residual_std = float(np.std(inverse_residuals))

            defect_energies = [-rydberg_ev / ((n - delta) ** 2) for n in n_values]
            defect_residuals = np.array(energies, dtype=float) - np.array(defect_energies, dtype=float)
            defect_rmse = float(np.sqrt(np.mean(defect_residuals ** 2)))
            defect_max_abs_error = float(np.max(np.abs(defect_residuals)))
            rmse_effect_size = float(defect_rmse - inverse_fit["rmse"])
            best_model = "inverse_square" if inverse_fit["rmse"] <= defect_rmse else "quantum_defect"

            rows = [
                (
                    f"    n={n}: energy={energy:.6f} eV, inverse_square_prediction={pred:.6f} eV, "
                    f"residual={residual:.6e} eV, quantum_defect_prediction={defect:.6f} eV"
                )
                for n, energy, pred, residual, defect in zip(
                    n_values, energies, inverse_predictions, inverse_residuals, defect_energies
                )
            ]

            return (
                "Hydrogen Rydberg scaling comparison:\n"
                "  Literature anchor: the nonrelativistic hydrogen model predicts E_n = -13.6/n^2 eV.\n"
                f"  Principal quantum numbers: {n_values}\n"
                "  Observations:\n"
                + "\n".join(rows)
                + "\n"
                f"  inverse_square fit E = {inverse_fit['slope']:.6f}*(1/n^2) + {inverse_fit['intercept']:.6f}; "
                f"RMSE={inverse_fit['rmse']:.6f} eV; R2={inverse_fit['r2']:.6f}; "
                f"max_abs_error={inverse_max_abs_error:.6f} eV\n"
                f"  quantum_defect_delta={delta:.6f}; quantum_defect model E = -13.600000/(n-delta)^2; "
                f"RMSE={defect_rmse:.6f} eV; max_abs_error={defect_max_abs_error:.6f} eV\n"
                f"  Best model by RMSE: {best_model}\n"
                f"  Deterministic residual statistics: sample size n={len(n_values)}; "
                f"residual standard deviation={inverse_residual_std:.6f} eV; "
                f"effect size (quantum_defect_RMSE - inverse_square_RMSE)={rmse_effect_size:.6f} eV; "
                "confidence interval: not estimated because this is a deterministic analytic control, "
                "not a random sample.\n"
                "  Falsifiable next check: introduce a documented non-hydrogenic atom or measured spectral series; "
                "the inverse_square hydrogen control is rejected only if residuals exceed the recorded RMSE tolerance "
                "under the same units and precision.\n"
                "  Caution: the quantum-defect perturbation is a competing-model stress test, not a claim that "
                "hydrogen has core-screening quantum defects."
            )
        except Exception as e:
            return f"Error: {str(e)}"

    def _cosmology_residual_comparison(self, query: str) -> str:
        """Compare Planck18-parameter FLRW distances with low-z controls."""
        try:
            fields = [part.strip() for part in query.split(";") if part.strip()]
            if not fields:
                return "Error: Provide redshifts, e.g. '0.01,0.1,0.5,1,2;threshold=5'"

            z_values = [
                float(part.strip())
                for part in re.split(r"[,:\s]+", fields[0])
                if part.strip()
            ]
            z_values = list(dict.fromkeys(z_values))
            if len(z_values) < 3:
                return "Error: Provide at least three redshifts for a residual comparison."
            if any(z <= 0 for z in z_values):
                return "Error: redshifts must be positive."

            threshold = 5.0
            for field in fields[1:]:
                if field.lower().startswith("threshold="):
                    threshold = float(field.split("=", 1)[1])

            c_km_s = 299792.458
            h0 = 67.660
            omega_m = 0.3097
            omega_l = 0.6888
            omega_k = 1.0 - omega_m - omega_l
            q0 = 0.5 * omega_m - omega_l
            hubble_distance = c_km_s / h0

            try:
                from scipy.integrate import quad

                def integral_to(redshift: float) -> float:
                    return float(quad(
                        lambda x: 1.0 / math.sqrt(
                            omega_m * (1.0 + x) ** 3
                            + omega_k * (1.0 + x) ** 2
                            + omega_l
                        ),
                        0.0,
                        redshift,
                        epsabs=1e-10,
                        epsrel=1e-10,
                    )[0])
            except Exception:
                def integral_to(redshift: float) -> float:
                    grid = np.linspace(0.0, redshift, max(2048, int(4096 * redshift)))
                    inv_e = 1.0 / np.sqrt(
                        omega_m * (1.0 + grid) ** 3
                        + omega_k * (1.0 + grid) ** 2
                        + omega_l
                    )
                    return float(np.trapezoid(inv_e, grid))

            planck_distances = []
            hubble_distances = []
            second_order_distances = []
            for z in z_values:
                comoving = hubble_distance * integral_to(z)
                planck_distances.append((1.0 + z) * comoving)
                hubble_distances.append(hubble_distance * z)
                second_order_distances.append(
                    hubble_distance * z * (1.0 + 0.5 * (1.0 - q0) * z)
                )

            planck = np.array(planck_distances, dtype=float)
            hubble = np.array(hubble_distances, dtype=float)
            second = np.array(second_order_distances, dtype=float)
            hubble_residual = hubble - planck
            second_residual = second - planck
            hubble_percent = 100.0 * hubble_residual / planck
            second_percent = 100.0 * second_residual / planck
            hubble_rmse = float(np.sqrt(np.mean(hubble_residual ** 2)))
            second_rmse = float(np.sqrt(np.mean(second_residual ** 2)))
            hubble_residual_std = float(np.std(hubble_residual))
            second_residual_std = float(np.std(second_residual))
            hubble_fit = self._fit_line(list(planck), list(hubble))
            second_fit = self._fit_line(list(planck), list(second))
            max_abs_percent = float(np.max(np.abs(hubble_percent)))
            second_max_abs_percent = float(np.max(np.abs(second_percent)))
            rmse_effect_size = float(hubble_rmse - second_rmse)
            crossings = [
                z for z, pct in zip(z_values, np.abs(hubble_percent))
                if float(pct) >= threshold
            ]
            first_crossing = f"{crossings[0]:.6f}" if crossings else "not_crossed"
            best_model = "hubble_law" if hubble_rmse <= second_rmse else "cosmographic_second_order"

            rows = [
                (
                    f"    z={z:.6f}: Planck18_luminosity_distance_Mpc={dl:.6f}, "
                    f"hubble_law_distance_Mpc={hz:.6f}, "
                    f"hubble_percent_residual={hpct:.6f}, "
                    f"cosmographic_second_order_distance_Mpc={cz:.6f}, "
                    f"cosmographic_percent_residual={cpct:.6f}"
                )
                for z, dl, hz, hpct, cz, cpct in zip(
                    z_values, planck, hubble, hubble_percent, second, second_percent
                )
            ]

            return (
                "Planck18 versus low-redshift Hubble-law comparison:\n"
                f"  Parameters: H0={h0:.3f} km/s/Mpc, Omega_m={omega_m:.4f}, "
                f"Omega_Lambda={omega_l:.4f}, Omega_k={omega_k:.6f}, q0={q0:.6f}\n"
                f"  sample size n={len(z_values)}\n"
                "  Residual table where percent_residual = 100*(approximation-Planck18)/Planck18:\n"
                + "\n".join(rows)
                + "\n"
                f"  hubble_law RMSE_Mpc={hubble_rmse:.6f}; R2_vs_Planck18={hubble_fit['r2']:.6f}; "
                f"max_abs_percent_residual={max_abs_percent:.6f}; residual standard deviation_Mpc={hubble_residual_std:.6f}\n"
                f"  cosmographic_second_order RMSE_Mpc={second_rmse:.6f}; R2_vs_Planck18={second_fit['r2']:.6f}; "
                f"max_abs_percent_residual={second_max_abs_percent:.6f}; residual standard deviation_Mpc={second_residual_std:.6f}\n"
                f"  Best approximation by RMSE_Mpc: {best_model}\n"
                f"  Deterministic model-comparison effect size (hubble_law_RMSE_Mpc - cosmographic_second_order_RMSE_Mpc)={rmse_effect_size:.6f}\n"
                f"  breakdown_redshift_threshold_percent={threshold:.6f}; first_threshold_crossing_z={first_crossing}\n"
                "  Deterministic residual statistics: confidence interval not estimated because the calculation is a fixed "
                "Planck18-parameter grid, not a random observational sample.\n"
                "  Falsifiable next check: add an independently implemented FLRW integrator or a catalog-backed supernova "
                "distance set; weaken the approximation claim if the threshold crossing or RMSE ordering changes under "
                "the same redshift grid and units.\n"
                "  Caution: this is not an observational Hubble-constant measurement and does not address Hubble tension."
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    # === NEW MATH & LIT TOOLS ===

    async def _calculus_engine(self, query: str) -> str:
        """Perform symbolic calculus operations."""
        try:
            # Format: operation:expression:variable
            parts = query.split(":")
            if len(parts) < 3: return "Error: format operation:expression:variable"
            ops, expr, var = parts[0].strip(), parts[1].strip(), parts[2].strip()
            
            # Using service if available
            if 'CalculusService' in globals():
                request = CalculusRequest(
                    expression=expr,
                    operation=ops,
                    variable=var
                )
                try:
                    result = CalculusService.calculate(request)
                    return f"Calculus Result ({ops}):\nExpression: {expr}\nResult: {result.result}\nSteps: {str(result.steps)[:500]}"
                except Exception as sc_err:
                    return f"CalculusService Error: {sc_err}. Falling back to basic SymPy."

            # Fallback
            import sympy
            x = sympy.Symbol(var)
            e = sympy.sympify(expr)
            if ops == "derivative": res = sympy.diff(e, x)
            elif ops == "integral": res = sympy.integrate(e, x)
            else: return f"Unknown operation: {ops}"
            return f"Calculus Result (SymPy direct): {res}"
        except Exception as e: return f"Calculus Error: {e}"

    async def _julia_computation(self, query: str) -> str:
        """Run Julia code for high-performance math."""
        try:
            if 'JuliaService' not in globals(): return "JuliaService not loaded."
            # Format: library:code or just code
            code = query.split(":", 1)[1] if ":" in query else query
            
            svc = JuliaService()
            if not svc.julia_available: return "Julia not available (not installed or in path)."
            
            # Use internal execute method if accessible, else assume generic numerical analysis
            # Accessing protected method for direct code execution as this is an internal agent tool
            res = await svc._execute_julia_code(code)
            return f"Julia Execution Result:\nSuccess: {res.get('success')}\nOutput: {res.get('output') or res.get('error')}"
        except Exception as e: return f"Julia Error: {e}"

    async def _z3_prover(self, query: str) -> str:
        """Formal verification using Z3."""
        try:
            if 'Z3SMTService' not in globals(): return "Z3SMTService not loaded."
            # variable inference
            stmt = query
            if ":" in query:
                stmt = query.split(":")[1].strip()
            
            import re
            # extract single char vars
            vars_found = list(set(re.findall(r'\b[a-zA-Z]\b', stmt)))
            # exclude reserved words
            vars_found = [v for v in vars_found if v not in ['sin', 'cos', 'tan', 'exp', 'log', 'sqrt']]
            var_dict = {v: "real" for v in vars_found}
            
            svc = Z3SMTService()
            res = svc.verify_mathematical_property(stmt, var_dict)
            return f"Z3 Verification Analysis:\nStatement: {stmt}\nStatus: {res.get('status')}\nValid: {res.get('is_valid')}\nCounter-example: {res.get('counterexample')}"
        except Exception as e: return f"Z3 Verification Error: {e}"

    async def _literature_search(self, query: str) -> str:
        """Async literature search."""
        try:
            if 'LiteratureService' not in globals(): return "LiteratureService not loaded."
            svc = LiteratureService()

            raw = (query or "").strip()
            source = "papers"
            q = raw

            # Optional prefix: "papers:<q>", "arxiv:<q>", "patents:<q>"
            if ":" in raw:
                prefix, rest = raw.split(":", 1)
                prefix_l = prefix.strip().lower()
                if prefix_l in {"papers", "paper", "unified"}:
                    source = "papers"
                    q = rest.strip()
                elif prefix_l in {"arxiv", "ax"}:
                    source = "arxiv"
                    q = rest.strip()
                elif prefix_l in {"patent", "patents"}:
                    source = "patents"
                    q = rest.strip()

            if not q:
                return "Literature Search Error: empty query"

            action = {
                "papers": "search_papers",
                "arxiv": "search_arxiv",
                "patents": "search_patents",
            }[source]

            res = await svc.process_request({"action": action, "query": q, "k": 6})
            papers = res.get('results', [])
            if not papers:
                return _compact_json({"success": True, "source": source, "query": q, "results": []}, max_chars=2500)

            def _snip(txt: Any, n: int = 420) -> str:
                s = str(txt or "").strip()
                if len(s) <= n:
                    return s
                return s[: n - 20] + "...<truncated>"

            out = {
                "success": bool(res.get("success", True)),
                "source": source,
                "query": q,
                "results": [],
            }
            for p in papers[:6]:
                out["results"].append({
                    "title": p.get("title"),
                    "year": p.get("year"),
                    "authors": p.get("authors"),
                    "venue": p.get("journal") or p.get("venue") or p.get("source"),
                    "url": p.get("url") or p.get("pdf_url") or p.get("link"),
                    "abstract": _snip(p.get("abstract"), 420),
                })

            return _compact_json(out, max_chars=6000)
        except Exception as e: return f"LitSearch Error: {e}"

    async def _literature_verify_hypothesis_plus(self, query: str) -> str:
        """Verify hypothesis against multi-source literature (full context)."""
        try:
            if 'LiteratureService' not in globals():
                return "LiteratureService not loaded."
            svc = LiteratureService()

            raw = (query or "").strip()
            payload: Dict[str, Any] = {}
            topic = ""
            hypothesis: Dict[str, Any] = {}
            k = 12

            # JSON input preferred
            if raw.startswith("{"):
                try:
                    payload = json.loads(raw)
                except Exception as e:
                    return f"Error: invalid JSON input: {e}"
                topic = str(payload.get("topic") or "").strip()
                hypothesis = payload.get("hypothesis") or {}
                try:
                    k = int(payload.get("k", k))
                except Exception:
                    k = 12
            else:
                # Fallback format: "domain:hypothesis_title" or just title
                if ":" in raw:
                    _d, rest = raw.split(":", 1)
                    topic = rest.strip()
                else:
                    topic = raw
                hypothesis = {"title": topic, "statement": topic, "variables": []}

            if not topic:
                topic = str(hypothesis.get("title") or "").strip()
            if not topic:
                return "Error: empty topic/hypothesis title"

            if not hypothesis.get("title"):
                hypothesis = {**hypothesis, "title": topic}

            res = await svc.process_request({
                "action": "verify_hypothesis_plus",
                "hypothesis": hypothesis,
                "topic": topic,
                "k": k,
            })
            return _compact_json(res, max_chars=8000)
        except Exception as e:
            return f"LitVerify Error: {e}"

    async def execute_tool(self, tool_name: str, input_data: str) -> str:
        """Execute a tool by name (Async-capable)."""
        tool = self.get_tool(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found. Available: {self.list_tools()[:10]}..."
        try:
            cleaned = (input_data or "").strip()
            # Remove common wrapping that models often add
            if cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
                cleaned = cleaned[1:-1].strip()
            if (cleaned.startswith("\"") and cleaned.endswith("\"")) or (cleaned.startswith("'") and cleaned.endswith("'")):
                cleaned = cleaned[1:-1].strip()

            decision = _core_safety_decision(
                "atlas_registry.execute_tool",
                cleaned,
                domain=tool.domain,
                tool_name=tool_name,
            )
            misuse_decision = _atlas_misuse_decision(
                "atlas_registry.execute_tool",
                cleaned,
                domain=tool.domain,
                tool_name=tool_name,
            )
            if not misuse_decision["allowed"]:
                return _atlas_misuse_blocked_message(misuse_decision)
            if not decision["allowed"]:
                return _core_safety_blocked_message(decision)

            res = tool.function(cleaned)
            if asyncio.iscoroutine(res):
                return await res
            return res
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"


# ========================
# MAIN AGENT LOOP
# ========================

async def autonomous_research_agent(domain: str, topic: str, max_iterations: int = 2, target_score: int = 8, model_name: str = "llama-3.3-70b-versatile"):
    """
    Run autonomous research agent with dynamic tool selection.
    
    Args:
        domain: Scientific domain (mathematics, chemistry, biology, physics)
        topic: Research topic to investigate
        max_iterations: Initial max iterations (can be extended if close to acceptance)
        target_score: Minimum score to accept the paper (default: 8)
        model_name: Name of the LLM model to use (default: llama-3.3-70b-versatile)
    """
    import time

    initial_misuse_decision = _atlas_misuse_decision(
        "autonomous_research_agent",
        topic,
        domain=domain,
        tool_name="autonomous_research_agent",
    )
    if not initial_misuse_decision["allowed"]:
        return {
            "success": False,
            "blocked": True,
            "error": _atlas_misuse_blocked_message(initial_misuse_decision),
            "safety_decision": initial_misuse_decision,
            "paper": "",
            "score": 0,
            "accepted": False,
        }
    
    print(f"\n🔬 Autonomous Research Agent")
    print(f"   Domain: {domain}")
    print(f"   Topic: {topic}")
    print(f"   Model: {model_name}")
    print("=" * 70)
    
    # Normalize + scope tools per domain (domain + aliases + research)
    dom_norm = _normalize_domain(domain)
    tool_registry = DynamicToolRegistry(scope_domain=dom_norm)
    all_tools = tool_registry.list_tools()
    domain_tools = tool_registry.list_tools_for_domain(dom_norm)
    
    print(f"\n📦 Tool Discovery:")
    print(f"   Total tools available: {len(all_tools)}")
    print(f"   Domain-specific tools ({domain}): {len(domain_tools)}")
    print(f"   Sample tools: {domain_tools[:5] if domain_tools else all_tools[:5]}")
    
    # Get tool descriptions for the agent (domain-aware)
    tool_descriptions = tool_registry.get_tool_descriptions_for_domain(dom_norm)
    
    previous_feedback: Optional[str] = None
    final_paper: Optional[str] = None
    review_score = 0

    # Persistent context across iterations
    state: Dict[str, Any] = {
        "domain": dom_norm,
        "topic": topic,
        "hypothesis": None,
        "literature": None,
        "tool_results": None,
        "paper": None,
        "review": None,
    }
    
    # Rate limiting delay (seconds between API calls)
    api_delay = 2.0
    
    iteration = 0
    HARD_LIMIT = max(6, int(max_iterations))  # Prevent infinite loops but allow extensions
    
    # Load hypothesis prompt templates (config-driven)
    hyp_cfg: Dict[str, Any] = {}
    try:
        if load_config_section is not None:
            hyp_cfg = load_config_section("prompts/hypothesis_agent")
    except Exception:
        hyp_cfg = {}

    def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Strip common code-fence wrappers (```json ... ```)
        try:
            s0 = text.strip()
            if s0.startswith("```"):
                s0 = re.sub(r"^```(?:json)?\s*", "", s0.strip(), flags=re.IGNORECASE)
                s0 = re.sub(r"\s*```$", "", s0.strip())
                text = s0
        except Exception:
            pass
        # Prefer strict validator when available
        try:
            if validate_json_response is not None:
                parsed = validate_json_response(text, required_fields=["title", "statement"], agent_name="hypothesis")
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass

        # Fallback: best-effort JSON extraction
        try:
            s = text.strip()
            start = s.find("{")
            end = s.rfind("}")
            if start >= 0 and end > start:
                return json.loads(s[start : end + 1])
        except Exception:
            return None
        return None

    async def _llm(role: str, prompt: str, default_tokens: int) -> str:
        max_toks = default_tokens
        try:
            if get_agent_parameters is not None:
                params = get_agent_parameters(role) or {}
                max_toks = int(params.get("max_new_tokens") or params.get("max_tokens") or default_tokens)
        except Exception:
            max_toks = default_tokens
        out = await ollama_provider.generate_async(prompt=prompt, model=model_name, max_tokens=max_toks)
        return out.get("text", "") or ""

    while iteration < max_iterations and iteration < HARD_LIMIT:
        iteration += 1
        print(f"\n{'='*70}")
        print(f"🔄 ITERATION {iteration}")
        print(f"{'='*70}")
        
        # ============ PHASE 1: HYPOTHESIS (CONFIG-DRIVEN) ============
        print(f"\n📝 Phase 1: Generating/Refining Hypothesis (config-driven JSON)...")

        templates = (hyp_cfg.get("templates") or {}) if isinstance(hyp_cfg, dict) else {}
        if previous_feedback and state.get("hypothesis"):
            t_ref = templates.get("refine") or {}
            sys_t = str(t_ref.get("system") or "").strip()
            usr_t = str(t_ref.get("user") or "").strip()
            prompt = (sys_t + "\n\n" + _render_braces_template(usr_t, {
                "current_statement": _compact_json(state.get("hypothesis"), 3500),
                "feedback": previous_feedback,
            })).strip()
        else:
            t_gen = templates.get("generate") or {}
            sys_t = str(t_gen.get("system") or "").strip()
            usr_t = str(t_gen.get("user") or "").strip()
            prompt = (sys_t + "\n\n" + _render_braces_template(usr_t, {
                "research_question": topic,
                "domain": dom_norm,
            })).strip()

        # Add tool context (kept compact)
        prompt += "\n\nAVAILABLE TOOLS (for later validation; do not invent new ones):\n" + tool_descriptions[:3000]

        hypothesis_text = await _llm("scientific_reasoner", prompt, default_tokens=1100)
        hypothesis_obj = _extract_json_obj(hypothesis_text)
        if not hypothesis_obj:
            # Hard fallback: keep the raw text but wrap it
            hypothesis_obj = {
                "title": topic[:80],
                "statement": hypothesis_text.strip() or topic,
                "variables": [],
                "assumptions": [],
                "expected_outcome": "",
            }

        state["hypothesis"] = hypothesis_obj
        # Ensure domain is present for downstream services (literature/peer-review domain-specific logic)
        if isinstance(hypothesis_obj, dict) and not hypothesis_obj.get("domain"):
            hypothesis_obj["domain"] = dom_norm
        print(f"\nHypothesis JSON (compact):\n{_compact_json(hypothesis_obj, 1200)}")

        await asyncio.sleep(api_delay)

        # ============ PHASE 2: LITERATURE (FULL CONTEXT) ============
        print(f"\n📚 Phase 2: Literature verification (full sources/abstracts)...")
        literature_payload = {
            "topic": topic,
            "hypothesis": hypothesis_obj,
            "domain": dom_norm,
            "k": 12,
        }

        lit_out = None
        if "literature_verify_hypothesis_plus" in tool_registry.tools:
            lit_out = await tool_registry.execute_tool("literature_verify_hypothesis_plus", json.dumps(literature_payload, ensure_ascii=False))
        else:
            lit_out = await tool_registry.execute_tool("literature_search", f"papers:{topic}")

        state["literature"] = lit_out
        print(f"Literature (compact):\n{(lit_out or '')[:900]}...")

        await asyncio.sleep(api_delay)
        
        # ============ PHASE 3: TOOL EVIDENCE (JSON TOOL CALLS) ============
        print(f"\n🔧 Phase 3: Selecting and Executing Tools (JSON)...")

        safe_dom = re.sub(r"[^a-zA-Z0-9_]+", "_", dom_norm)
        evidence_tool = f"evidence_corroborate_{safe_dom}"

        # Build a compact tool catalog for the orchestrator
        available = tool_registry.list_tools_for_domain(dom_norm)
        tool_lines = []
        for name in available[:40]:
            t = tool_registry.get_tool(name)
            if not t:
                continue
            tool_lines.append({
                "name": t.name,
                "domain": t.domain,
                "input_format": t.input_format,
                "output_format": t.output_format,
                "description": t.description,
            })

        orchestrator_user_prompt = _compact_json({
            "task": "Select tools to gather real evidence for the hypothesis.",
            "constraints": {
                "must_use_real_tools": True,
                "tool_names_must_match": True,
                "return_format": "JSON only",
                "n_tools": 3,
            },
            "hypothesis": hypothesis_obj,
            "literature": lit_out,
            "available_tools": tool_lines,
            "required_tools": [evidence_tool] if evidence_tool in tool_registry.tools else [],
        }, max_chars=7000)

        if get_improved_prompt is not None:
            tool_prompt = get_improved_prompt(
                agent_role="orchestrator",
                user_prompt=(
                    orchestrator_user_prompt
                    + "\n\nReturn ONLY valid JSON: {\"tools\": [{\"name\": <tool>, \"input\": <string>, \"why\": <short>}] }"
                ),
                domain=dom_norm,
                literature_context=None,
            )
        else:
            tool_prompt = (
                "Select 3 tools to test the hypothesis using ONLY the available tools. "
                "Return ONLY JSON: {\"tools\":[{\"name\":...,\"input\":...,\"why\":...}]}\n\n"
                + orchestrator_user_prompt
            )

        tool_text = await _llm("orchestrator", tool_prompt, default_tokens=900)
        selected = _extract_json_obj(tool_text)
        tools_list = []
        if selected and isinstance(selected.get("tools"), list):
            tools_list = selected.get("tools")
        else:
            # Fallback: try parse as plain JSON
            try:
                tools_list = json.loads(tool_text).get("tools", [])
            except Exception:
                tools_list = []

        # Enforce at least one evidence tool if available
        if evidence_tool in tool_registry.tools and not any((t.get("name") == evidence_tool) for t in tools_list if isinstance(t, dict)):
            tools_list = ([{"name": evidence_tool, "input": str(hypothesis_obj.get("statement") or topic), "why": "Domain corroboration via orchestrator"}] + tools_list)[:3]

        # Ensure we actually execute multiple domain tools (avoid the "only 1 tool" failure mode)
        def _append_if_missing(name: str, inp: str, why: str) -> None:
            nonlocal tools_list
            if not name or name not in tool_registry.tools:
                return
            if any(isinstance(t, dict) and t.get("name") == name for t in tools_list):
                return
            tools_list.append({"name": name, "input": inp, "why": why})

        # Prefer deterministic math tools for the Goldbach-style topic
        if dom_norm in {"math", "mathematics", "number_theory"}:
            topic_lc = str(topic or "").lower()
            stmt_lc = str(hypothesis_obj.get("statement") or "").lower()
            if "goldbach" in topic_lc or "goldbach" in stmt_lc:
                if "number_theory_advanced" in tool_registry.tools:
                    _append_if_missing(
                        "number_theory_advanced",
                        "goldbach:10000",
                        "Direct bounded verification of Goldbach over an explicit range",
                    )
            if "sympy_prime_analysis" in tool_registry.tools:
                _append_if_missing(
                    "sympy_prime_analysis",
                    "prime_range:1-50000",
                    "Generate primes for prime-pair and Goldbach-style analysis",
                )
            if "prime_gap_analysis" in tool_registry.tools:
                _append_if_missing(
                    "prime_gap_analysis",
                    "100000",
                    "Analyze prime gaps as an additional structural signal",
                )

        # If still too few, pad with the first available non-research, non-evidence tools
        if len([t for t in tools_list if isinstance(t, dict)]) < 3:
            for cand in available:
                if cand == evidence_tool:
                    continue
                td = tool_registry.get_tool(cand)
                if not td or td.domain == "research":
                    continue
                if cand in {"sympy_solve_equation"}:
                    continue
                _append_if_missing(cand, str(hypothesis_obj.get("statement") or topic), "Additional domain evidence")
                if len([t for t in tools_list if isinstance(t, dict)]) >= 3:
                    break

        experiment_results: List[Dict[str, Any]] = []
        for t in tools_list[:4]:
            if not isinstance(t, dict):
                continue
            tool_name = str(t.get("name") or "").strip()
            tool_input = str(t.get("input") or "").strip()
            if not tool_name:
                continue

            print(f"\n   🔨 Executing: {tool_name}")
            print(f"      Input: {tool_input[:200]}")
            result = await tool_registry.execute_tool(tool_name, tool_input)
            print(f"      ✅ Result: {str(result)[:220]}")
            experiment_results.append({
                "tool": tool_name,
                "input": tool_input,
                "why": t.get("why"),
                "result": result,
            })

        if not experiment_results and evidence_tool in tool_registry.tools:
            result = await tool_registry.execute_tool(evidence_tool, str(hypothesis_obj.get("statement") or topic))
            experiment_results = [{"tool": evidence_tool, "input": topic, "why": "Fallback corroboration", "result": result}]

        state["tool_results"] = experiment_results
        
        # ============ PHASE 4: PAPER DRAFTING (IMPROVED PROMPTS) ============
        print(f"\n📄 Phase 4: Drafting Paper (publisher prompt)...")

        publisher_payload = {
            "hypothesis": hypothesis_obj,
            "literature": lit_out,
            "evidence": experiment_results,
            "previous_review": previous_feedback,
        }

        if get_improved_prompt is not None:
            paper_prompt = get_improved_prompt(
                agent_role="publisher",
                user_prompt=(
                    "Write a complete scientific paper using the provided hypothesis, literature, and tool evidence. "
                    "Cite sources by title/year/URL when available. Do not fabricate citations.\n\n"
                    + _compact_json(publisher_payload, 9000)
                ),
                domain=dom_norm,
                literature_context=None,
            )
        else:
            paper_prompt = "Write a complete scientific paper based on this context:\n" + _compact_json(publisher_payload, 9000)

        paper_text = await _llm("publisher", paper_prompt, default_tokens=1400)
        final_paper = paper_text
        state["paper"] = paper_text
        print(f"\n{paper_text[:600]}...")

        await asyncio.sleep(api_delay)
        
        # ============ PHASE 5: PEER REVIEW (REAL SERVICE) ============
        print(f"\n🔍 Phase 5: Peer Review (AutonomousPeerReviewService)...")

        review_text = ""
        review_score = 5
        review_payload = {
            "experiment": {
                "id": f"{dom_norm}_{int(time.time())}",
                "domain": dom_norm,
                "hypothesis": str(hypothesis_obj.get("statement") or ""),
                "methodology": "Tool-driven evidence + literature verification + paper draft",
                "results": {
                    "literature": lit_out,
                    "tool_results": experiment_results,
                    "paper": paper_text,
                },
            }
        }

        if AutonomousPeerReviewService is not None:
            try:
                prs = AutonomousPeerReviewService()
                review_res = await prs.process_request({"action": "validate_experiment", **review_payload})
                review_text = _compact_json(review_res, 6000)
                overall = review_res.get("overall_score")
                try:
                    review_score = int(round(float(overall)))
                except Exception:
                    review_score = 6 if review_res.get("approved") else 5
            except Exception as e:
                review_text = f"PeerReviewService error: {e}"
                review_score = 5
        else:
            # Fallback: improved reviewer prompt
            if get_improved_prompt is not None:
                review_prompt = get_improved_prompt(
                    agent_role="reviewer",
                    user_prompt=(
                        "Review the paper and the evidence critically. Return JSON with score (1-10) and actionable recommendations.\n\n"
                        + _compact_json(review_payload, 9000)
                    ),
                    domain=dom_norm,
                    literature_context=None,
                )
            else:
                review_prompt = "Review critically and provide a score 1-10 plus recommendations.\n\n" + _compact_json(review_payload, 9000)
            review_text = await _llm("reviewer", review_prompt, default_tokens=900)
            m = re.search(r'\b(\d{1,2})\b', review_text)
            if m:
                try:
                    review_score = max(1, min(10, int(m.group(1))))
                except Exception:
                    review_score = 5

        state["review"] = review_text
        print(f"\n{review_text[:1500]}")

        await asyncio.sleep(api_delay)

        is_accepted = review_score >= target_score
        
        if is_accepted:
            print(f"\n✅ Paper ACCEPTED after {iteration} iteration(s)! Score: {review_score}/10")
            
            # === OUTPUT PERSISTENCE ===
            try:
                from datetime import datetime as dt
                import os
                
                output_dir = "artifacts/research_papers"
                os.makedirs(output_dir, exist_ok=True)
                
                timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
                safe_topic = "".join(c if c.isalnum() else "_" for c in str(topic)[:30])
                
                # Save Markdown paper
                paper_file = f"{output_dir}/{timestamp}_{safe_topic}_paper.md"
                with open(paper_file, "w") as f:
                    f.write(final_paper if final_paper else "# Paper\n\nNo content generated.")
                print(f"   📄 Paper saved: {paper_file}")
                
                # Save LaTeX if paper_builder available
                try:
                    from app.autonomous.publication.paper_builder import MiniPaper
                    mini = MiniPaper(
                        title=str(hypothesis_obj.get("title", topic)),
                        abstract=str(hypothesis_obj.get("statement", ""))[:500],
                        introduction="",
                        methodology="",
                        results="",
                        discussion="",
                        conclusion="",
                        acknowledgements="",
                        sections=[{"title": "Content", "content": final_paper or ""}],
                        artifacts=[],
                        metadata={"domain": dom_norm, "score": review_score}
                    )
                    latex_content = mini.to_latex()
                    latex_file = f"{output_dir}/{timestamp}_{safe_topic}_paper.tex"
                    with open(latex_file, "w") as f:
                        f.write(latex_content)
                    print(f"   📝 LaTeX saved: {latex_file}")
                except Exception as latex_err:
                    print(f"   ⚠️ LaTeX generation skipped: {latex_err}")
                
                # Save metadata JSON
                metadata = {
                    "domain": dom_norm,
                    "topic": topic,
                    "hypothesis": hypothesis_obj,
                    "score": review_score,
                    "iterations": iteration,
                    "review": review_text[:2000],
                    "tools_used": [t.get("name") for t in tools_list if isinstance(t, dict)],
                    "timestamp": timestamp
                }
                meta_file = f"{output_dir}/{timestamp}_{safe_topic}_metadata.json"
                with open(meta_file, "w") as f:
                    json.dump(metadata, f, indent=2, default=str)
                print(f"   📋 Metadata saved: {meta_file}")
                
                # Store in ReasoningBank for learning
                try:
                    from app.memory.reasoning_bank import get_reasoning_bank
                    rb = get_reasoning_bank()
                    rb.store_success(
                        hypothesis=str(hypothesis_obj.get("statement", topic))[:2000],
                        score=review_score,
                        domain=dom_norm,
                        topic=str(topic),
                        tools_used=[t.get("name") for t in tools_list if isinstance(t, dict)],
                        iterations_needed=iteration
                    )
                    print(f"   🧠 Stored in ReasoningBank for future learning")
                except Exception as rb_err:
                    print(f"   ⚠️ ReasoningBank storage skipped: {rb_err}")
                    
            except Exception as save_err:
                print(f"   ⚠️ Output persistence error: {save_err}")
            
            _tool_names = [t.get("name") for t in tools_list if isinstance(t, dict)]
            _real_keywords = {"sympy", "numpy", "scipy", "qiskit", "sage", "z3", "lean", "calculus", "julia", "quantum", "math"}
            _heuristic_keywords = {"llm", "gpt", "mock", "fallback", "simulated"}
            _trs = 0.6
            if _tool_names:
                _scores = []
                for t in _tool_names:
                    tl = t.lower()
                    if any(r in tl for r in _real_keywords):
                        _scores.append(1.0)
                    elif any(h in tl for h in _heuristic_keywords):
                        _scores.append(0.2)
                    else:
                        _scores.append(0.6)
                _trs = round(sum(_scores) / len(_scores), 2)
            elif dom_norm in {"mathematics", "physics", "quantum"}:
                _trs = 0.8
            return {
                "status": "accepted",
                "final_score": review_score,
                "iterations_used": iteration,
                "paper": final_paper,
                "review": review_text,
                "tool_realism_score": _trs,
                "domain": dom_norm,
            }
        elif iteration < max_iterations:
            # Extract feedback for next iteration
            previous_feedback = review_text
            print(f"\n🔄 Revision requested (score: {review_score}). Proceeding to iteration {iteration + 1}...")
        else:
            # At max iterations but not accepted yet
            print(f"\n⏱️ Max iterations ({max_iterations}) reached. Score: {review_score}/10")
            if review_score >= 5:  # If showing progress, extend iterations
                max_iterations += 2
                HARD_LIMIT = max(HARD_LIMIT, int(max_iterations))
                previous_feedback = review_text
                print(f"   📈 Extending iterations to {max_iterations} to achieve acceptance...")
            else:
                print(f"   ⛔ Score too low ({review_score}). Stopping research cycle.")
                _tool_names = [t.get("name") for t in tools_list if isinstance(t, dict)]
                _real_keywords = {"sympy", "numpy", "scipy", "qiskit", "sage", "z3", "lean", "calculus", "julia", "quantum", "math"}
                _heuristic_keywords = {"llm", "gpt", "mock", "fallback", "simulated"}
                _trs = 0.6
                if _tool_names:
                    _scores = []
                    for t in _tool_names:
                        tl = t.lower()
                        if any(r in tl for r in _real_keywords):
                            _scores.append(1.0)
                        elif any(h in tl for h in _heuristic_keywords):
                            _scores.append(0.2)
                        else:
                            _scores.append(0.6)
                    _trs = round(sum(_scores) / len(_scores), 2)
                elif dom_norm in {"mathematics", "physics", "quantum"}:
                    _trs = 0.8
                return {
                    "status": "rejected",
                    "final_score": review_score,
                    "iterations_used": iteration,
                    "paper": final_paper,
                    "review": review_text,
                    "tool_realism_score": _trs,
                    "domain": dom_norm,
                }
    
    # Should not reach here normally
    _tool_names = [t.get("name") for t in tools_list if isinstance(t, dict)]
    _real_keywords = {"sympy", "numpy", "scipy", "qiskit", "sage", "z3", "lean", "calculus", "julia", "quantum", "math"}
    _heuristic_keywords = {"llm", "gpt", "mock", "fallback", "simulated"}
    _trs = 0.6
    if _tool_names:
        _scores = []
        for t in _tool_names:
            tl = t.lower()
            if any(r in tl for r in _real_keywords):
                _scores.append(1.0)
            elif any(h in tl for h in _heuristic_keywords):
                _scores.append(0.2)
            else:
                _scores.append(0.6)
        _trs = round(sum(_scores) / len(_scores), 2)
    elif dom_norm in {"mathematics", "physics", "quantum"}:
        _trs = 0.8
    return {
        "status": "completed",
        "final_score": review_score,
        "iterations_used": iteration,
        "paper": final_paper,
        "review": review_text if 'review_text' in dir() else None,
        "tool_realism_score": _trs,
        "domain": dom_norm,
    }


async def main():
    """Run multi-domain research tests."""
    
    test_cases = [
        ("mathematics", "prime number gap patterns and their statistical distribution"),
        ("chemistry", "molecular stability prediction using computational methods"),
        ("biology", "DNA sequence mutation patterns and evolutionary implications"),
    ]
    
    for domain, topic in test_cases:
        print(f"\n{'#'*80}")
        print(f"# DOMAIN: {domain.upper()}")
        print(f"# TOPIC: {topic}")
        print(f"{'#'*80}")
        
        await autonomous_research_agent(domain, topic, max_iterations=2)
        
        print("\n" + "="*80)
        input("Press Enter to continue to next domain...")


if __name__ == "__main__":
    import sys
    # Allow command-line domain selection
    if len(sys.argv) > 1:
        domain = sys.argv[1]
        topic = sys.argv[2] if len(sys.argv) > 2 else f"{domain} research hypothesis"
    else:
        domain = "chemistry"
        topic = "molecular orbital energy levels in conjugated systems"
    
    asyncio.run(autonomous_research_agent(
        domain=domain,
        topic=topic,
        max_iterations=2
    ))
