#!/usr/bin/env python3
"""
A.M.Y Autonomous Mission Runner

Deja A.M.Y corriendo autónomamente ejecutando misiones científicas:
1. Selecciona un dominio aleatorio
2. Ejecuta 3-5 herramientas Atlas
3. Genera un paper con los resultados
4. Repite indefinidamente

Uso: python run_amy_autonomous.py --duration 3600 --domain mathematics
"""
import argparse
import asyncio
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "atlas"))

from core.atlas_tools import AtlasTools, assess_tool_output
from core.provenance import ProvenanceManager
from communication.paper_generator import PaperGenerator
from cognition.reasoning import ReasoningEngine

MIN_MISSION_START_BUDGET_SECONDS = 60.0


# Misiones por dominio — solo tools que funcionan (sin service_* ni service_* con JSON)
MISSIONS = {
    "mathematics": {
        "topic": "Mathematical Analysis",
        "tools": [
            ("prime_gap_analysis", "1000", "Prime gap distribution (up to 1000)"),
            ("sympy_prime_analysis", "is_prime:97", "Prime verification (97)"),
            ("number_theory_advanced", "goldbach:100", "Goldbach conjecture verification"),
            ("sympy_solve_equation", "x**2 - 4 = 0", "Polynomial equation solving"),
            ("sympy_derivative", "x**3, x", "Symbolic derivative"),
            ("sympy_integrate", "x**2, x", "Symbolic integral"),
            ("calculus_engine", "limit:sin(x)/x:x->0", "Limit computation"),
            ("graph_theory", "chromatic:petersen", "Petersen graph chromatic number"),
            ("graph_theory", "eulerian:K4", "K4 Eulerian path analysis"),
            ("topology_invariants", "euler_char:sphere", "Sphere Euler characteristic"),
            ("topology_invariants", "betti:torus", "Torus Betti numbers"),
            ("z3_prover", "x > 0 and x < 10 implies x*x < 100", "Z3 theorem verification"),
            ("number_theory_advanced", "prime_count:1000", "Prime counting function π(1000)"),
            ("sympy_simplify", "sin(x)**2 + cos(x)**2", "Trigonometric identity"),
        ],
    },
    "chemistry": {
        "topic": "Molecular Structure and Energetics",
        "tools": [
            ("molecular_weight_calc", "C6H12O6", "Glucose molecular weight"),
            ("molecular_weight_calc", "H2O", "Water molecular weight"),
            ("molecular_weight_calc", "CO2", "Carbon dioxide weight"),
            ("molecular_weight_calc", "C6H6", "Benzene molecular weight"),
            ("molecular_weight_calc", "NH3", "Ammonia molecular weight"),
            ("bond_energy_analyzer", "C-C", "C-C single bond energy"),
            ("bond_energy_analyzer", "O-H", "O-H bond energy"),
            ("bond_energy_analyzer", "N-H", "N-H bond energy"),
            ("bond_energy_analyzer", "C=O", "C=O double bond energy"),
            ("molecular_orbital_energy", "6", "Benzene HMO 6-carbon"),
            ("molecular_orbital_energy", "4", "Butadiene HMO 4-carbon"),
            ("computational_chemistry", "analyze_molecule:C6H6", "Benzene DFT analysis"),
            ("computational_chemistry", "analyze_molecule:H2O", "Water DFT analysis"),
            ("computational_chemistry", "analyze_molecule:CO2", "CO2 DFT analysis"),
        ],
    },
    "physics": {
        "topic": "Quantum Mechanics and Energy Levels",
        "tools": [
            ("quantum_energy_levels", "hydrogen:1", "Hydrogen ground state n=1"),
            ("quantum_energy_levels", "hydrogen:2", "Hydrogen n=2"),
            ("quantum_energy_levels", "hydrogen:3", "Hydrogen n=3"),
            ("quantum_energy_levels", "hydrogen:5", "Hydrogen n=5"),
            ("quantum_energy_levels", "hydrogen:7", "Hydrogen n=7"),
            ("calculus_engine", "derivative:E_n=-13.6/n**2:n", "Bohr energy derivative"),
            ("numpy_statistics", "summary:[-13.6,-3.4,-1.51,-0.85,-0.54,-0.38,-0.28]", "Hydrogen energy levels stats"),
            ("topology_invariants", "euler_char:sphere", "S² Euler characteristic (QM context)"),
            ("z3_prover", "E > -13.6 and E < 0", "Bound state energy constraint"),
            ("graph_theory", "chromatic:K5", "K5 chromatic number"),
        ],
    },
    "biology": {
        "topic": "DNA Sequence and Protein Analysis",
        "tools": [
            ("dna_analyzer", "ATCGATCGATCGATCGATCG", "20-mer DNA composition"),
            ("dna_analyzer", "GCGCGCGCGCGCGCGCGCGC", "GC-rich DNA analysis"),
            ("dna_analyzer", "AAAAATTTTTGGGGGCCCCC", "Mixed DNA analysis"),
            ("protein_properties", "MVLSPADKTNVKAAWGKVGA", "Hemoglobin alpha fragment"),
            ("protein_properties", "MKTAYIAKQRQISFVKSHFS", "20-residue test protein"),
            ("sequence_analyzer", "ATCGATCGATCG", "DNA repeat analysis"),
            ("numpy_statistics", "summary:[0.25,0.25,0.25,0.25]", "GC/AT base statistics"),
            ("hypothesis_tester", "ttest:[0.3,0.31,0.29,0.32,0.30]:[0.5,0.51,0.49,0.52,0.50]", "GC content t-test"),
        ],
    },
    "statistics": {
        "topic": "Statistical Analysis and Inference",
        "tools": [
            ("numpy_statistics", "summary:[1,2,3,4,5,6,7,8,9,10]", "Uniform distribution stats"),
            ("numpy_statistics", "summary:[2.1,2.3,1.9,2.4,2.0,2.2,2.1,2.3]", "Measurement series stats"),
            ("numpy_distribution", "normal:1000,0,1", "Standard normal sampling"),
            ("numpy_distribution", "normal:500,5,2", "Normal mu=5 sigma=2"),
            ("numpy_distribution", "uniform:1000,0,1", "Uniform distribution"),
            ("hypothesis_tester", "ttest:[1,2,3,4,5]:[3,4,5,6,7]", "Two-sample t-test"),
            ("hypothesis_tester", "ttest:[10,12,11,13,10]:[15,16,14,17,15]", "Treatment comparison"),
            ("numpy_correlation", "correlation:[1,2,3,4,5]:[2,4,6,8,10]", "Linear correlation"),
            ("numpy_correlation", "correlation:[1,4,9,16,25]:[1,2,3,4,5]", "Quadratic correlation"),
        ],
    },
    "engineering": {
        "topic": "Structural and Network Engineering Analysis",
        "tools": [
            ("graph_theory", "chromatic:petersen", "Petersen network chromatic number"),
            ("graph_theory", "eulerian:K4", "K4 complete graph Eulerian"),
            ("graph_theory", "shortest_path:grid", "Grid network shortest path"),
            ("topology_invariants", "euler_char:sphere", "Sphere Euler characteristic"),
            ("topology_invariants", "betti:torus", "Torus Betti numbers (mesh topology)"),
            ("topology_invariants", "fundamental_group:circle", "Circle fundamental group"),
            ("numpy_statistics", "summary:[245,251,248,253,247,250,249,252]", "Load measurement series"),
            ("numpy_correlation", "correlation:[1,2,3,4,5,6,7,8]:[2.1,4.0,6.2,7.9,10.1,12.0,14.2,15.8]", "Stress-strain correlation"),
            ("calculus_engine", "derivative:3*x**3+2*x**2-5*x:x", "Structural force derivative"),
            ("hypothesis_tester", "ttest:[245,251,248,253,247]:[260,265,258,262,261]", "Material strength t-test"),
            ("z3_prover", "stress > 0 and stress < 250 implies safety_factor > 1.5", "Safety constraint verification"),
            ("sympy_solve_equation", "3*x**2 - 12*x + 9 = 0", "Buckling load equation"),
        ],
    },
    "neuroscience": {
        "topic": "Neural Signal and Network Analysis",
        "tools": [
            ("numpy_statistics", "summary:[0.12,0.15,0.11,0.14,0.13,0.16,0.12,0.15]", "Neural firing rate stats"),
            ("numpy_statistics", "summary:[72,75,68,71,74,73,70,76,69,72]", "EEG amplitude series"),
            ("numpy_distribution", "normal:1000,0.13,0.02", "Firing rate distribution"),
            ("numpy_distribution", "normal:500,72,3", "EEG amplitude distribution"),
            ("numpy_correlation", "correlation:[0.12,0.15,0.11,0.14,0.13]:[0.24,0.30,0.22,0.28,0.26]", "Neuron pair correlation"),
            ("hypothesis_tester", "ttest:[72,75,68,71,74]:[85,88,82,86,84]", "Pre/post stimulation t-test"),
            ("hypothesis_tester", "ttest:[0.12,0.15,0.11,0.14,0.13]:[0.22,0.25,0.21,0.24,0.23]", "Firing rate comparison"),
            ("graph_theory", "chromatic:petersen", "Neural network graph coloring"),
            ("topology_invariants", "betti:torus", "Neural manifold topology"),
            ("calculus_engine", "derivative:-70+20*exp(-t/10):t", "Membrane potential dynamics"),
        ],
    },
    "astronomy": {
        "topic": "Stellar Physics and Cosmological Analysis",
        "tools": [
            ("quantum_energy_levels", "hydrogen:1", "Lyman alpha transition n=1"),
            ("quantum_energy_levels", "hydrogen:2", "Balmer series n=2"),
            ("quantum_energy_levels", "hydrogen:3", "Paschen series n=3"),
            ("numpy_statistics", "summary:[5778,3500,10000,25000,3000,6000,8000,4500]", "Stellar temperature survey"),
            ("numpy_statistics", "summary:[1.0,0.08,10.0,15.0,0.5,1.2,3.0,0.7]", "Stellar mass distribution"),
            ("calculus_engine", "derivative:L=4*pi*r**2*sigma*T**4:T", "Stefan-Boltzmann luminosity law"),
            ("calculus_engine", "limit:GM/r:r->inf", "Gravitational potential at infinity"),
            ("numpy_correlation", "correlation:[3000,5000,7000,10000,15000]:[0.04,0.5,2.0,10.0,30.0]", "Temperature-luminosity correlation"),
            ("hypothesis_tester", "ttest:[5778,5500,6000,5900,5800]:[3200,3500,3400,3300,3600]", "G-dwarf vs M-dwarf temps"),
            ("numpy_distribution", "normal:1000,5778,500", "Solar-type star temperature distribution"),
            ("molecular_weight_calc", "H2", "Hydrogen molecule (stellar fuel)"),
            ("molecular_weight_calc", "He", "Helium (stellar product)"),
        ],
    },
    "climate": {
        "topic": "Climate Dynamics and Environmental Analysis",
        "tools": [
            ("numpy_statistics", "summary:[280,285,290,295,300,305,310,315,320,325]", "CO2 concentration trend (ppm)"),
            ("numpy_statistics", "summary:[13.8,13.9,14.1,14.2,14.3,14.5,14.6,14.8,15.0,15.2]", "Global temperature anomaly"),
            ("numpy_correlation", "correlation:[280,295,310,325,340,355,370,385,400,415]:[13.8,13.9,14.0,14.2,14.3,14.5,14.6,14.8,15.0,15.2]", "CO2-temperature correlation"),
            ("numpy_distribution", "normal:1000,14.5,0.5", "Temperature anomaly distribution"),
            ("hypothesis_tester", "ttest:[13.8,13.9,14.0,14.1,14.2]:[14.8,14.9,15.0,15.1,15.2]", "Pre/post-1980 temperature t-test"),
            ("calculus_engine", "derivative:C=280*exp(0.006*t):t", "Exponential CO2 growth rate"),
            ("numpy_correlation", "correlation:[0,10,20,30,40,50,60,70,80,90]:[0.0,0.1,0.15,0.25,0.35,0.45,0.55,0.65,0.8,1.0]", "Warming trend correlation"),
            ("numpy_statistics", "summary:[3.1,3.3,3.5,3.6,3.8,3.9,4.1,4.2,4.3,4.5]", "Sea level rise (mm/yr)"),
            ("hypothesis_tester", "ttest:[3.1,3.2,3.3,3.4,3.5]:[4.0,4.1,4.2,4.3,4.4]", "Sea level rise rate comparison"),
            ("calculus_engine", "limit:delta_T=lambda*ln(C/C0):C->2*C0", "Climate sensitivity doubling"),
        ],
    },
}


class AutonomousAMY:
    """A.M.Y running autonomously."""
    
    def __init__(self, duration_seconds: int = 3600, fixed_domain: str = None, model: str = None):
        self.duration = duration_seconds
        self.fixed_domain = fixed_domain
        self.model = model
        self.tools = None  # Lazy init
        
        # Load config and optionally override model
        config = yaml.safe_load(open("config.yaml"))
        if model:
            config["llm"]["reasoner"]["model"] = model
            config["llm"]["fast"]["model"] = model
        
        reasoning = ReasoningEngine(config["llm"])
        self.pg = PaperGenerator(reasoning_engine=reasoning)
        self.provenance = ProvenanceManager()
        self.mission_count = 0
        self.tool_count = 0
        self.paper_count = 0
        self.start_time = time.time()
        
    def _init_tools(self):
        """Initialize Atlas tools (takes time on first call)."""
        if self.tools is None:
            self.log("🔧 Initializing Atlas tools (first time, may take 30-60s)...")
            self.tools = AtlasTools()
            self.log("✅ Atlas tools ready!")
        
    def should_continue(self) -> bool:
        """Check if we should continue running."""
        elapsed = time.time() - self.start_time
        return elapsed < self.duration

    def remaining_seconds(self) -> float:
        """Return the remaining autonomous run budget."""
        elapsed = time.time() - self.start_time
        return max(0.0, self.duration - elapsed)

    def mission_start_budget_seconds(self) -> float:
        """Minimum remaining time required before starting another mission."""
        return min(MIN_MISSION_START_BUDGET_SECONDS, float(self.duration))

    def has_mission_start_budget(self) -> bool:
        """Avoid launching a fresh mission when only a short tail remains."""
        if not self.should_continue():
            return False
        if self.mission_count == 0:
            return True
        return self.remaining_seconds() >= self.mission_start_budget_seconds()
    
    def log(self, message: str):
        """Log with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")
        
    async def run_mission(self) -> dict:
        """Run one complete mission."""
        self.mission_count += 1
        
        # Worker ya pre-calentado en run()
        self._init_tools()
        
        # Select domain
        if self.fixed_domain:
            domain = self.fixed_domain
        else:
            domain = random.choice(list(MISSIONS.keys()))
        
        mission = MISSIONS[domain]
        self.log(f"🚀 Mission #{self.mission_count}: {domain.upper()} - {mission['topic']}")
        
        # Select 3-5 tools (adaptado al tamaño del dominio)
        max_tools = len(mission['tools'])
        lo = min(3, max_tools)
        hi = min(5, max_tools)
        num_tools = random.randint(lo, hi)
        selected_tools = random.sample(mission['tools'], num_tools)
        
        # Execute tools
        results = []
        for tool_name, tool_input, description in selected_tools:
            started = time.time()
            try:
                result = await asyncio.wait_for(
                    self.tools.run_scientific_tool(tool_name, tool_input, domain),
                    timeout=180,
                )
                result_text = str(result)
                duration = time.time() - started
                assessment = assess_tool_output(result_text, tool_name)
                provenance = self.provenance.record_execution(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=result_text,
                    success=bool(assessment["usable"]),
                    duration_seconds=duration,
                    domain=domain,
                    extra={"description": description, "quality_assessment": assessment},
                )
                results.append({
                    "tool": tool_name,
                    "description": description,
                    "input": tool_input,
                    "result": result_text[:400],
                    "success": bool(assessment["usable"]),
                    "experiment_id": provenance["experiment_id"],
                    "quality_assessment": assessment,
                })
                self.tool_count += 1
                if assessment["usable"]:
                    self.log(f"  ✅ {description}: {result_text[:60]}")
                else:
                    markers = ", ".join(assessment.get("markers") or ["unusable output"])
                    self.log(f"  ❌ {description}: unusable output ({markers})")
            except asyncio.TimeoutError:
                duration = time.time() - started
                provenance = self.provenance.record_execution(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output="TIMEOUT",
                    success=False,
                    duration_seconds=duration,
                    domain=domain,
                    extra={"description": description, "failure_type": "timeout"},
                )
                results.append({
                    "tool": tool_name,
                    "description": description,
                    "input": tool_input,
                    "result": "TIMEOUT",
                    "success": False,
                    "experiment_id": provenance["experiment_id"],
                })
                self.log(f"  ⏱️  TIMEOUT {description}")
            except Exception as e:
                duration = time.time() - started
                provenance = self.provenance.record_execution(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=str(e),
                    success=False,
                    duration_seconds=duration,
                    domain=domain,
                    extra={"description": description, "failure_type": "exception"},
                )
                results.append({
                    "tool": tool_name,
                    "description": description,
                    "input": tool_input,
                    "result": str(e),
                    "success": False,
                    "experiment_id": provenance["experiment_id"],
                })
                self.log(f"  ❌ {description}: {e}")
        
        # Generate paper if we have results
        if len([r for r in results if r["success"]]) >= 2:
            try:
                paper = await self.generate_paper(domain, mission['topic'], results)
                self.paper_count += 1
                self.log(f"  📄 Paper: {paper.get('word_count', 0)} words")
            except Exception as e:
                self.log(f"  ⚠️  Paper generation failed: {e}")
        
        return {
            "domain": domain,
            "tools_executed": len([r for r in results if r["success"]]),
            "tools_failed": len([r for r in results if not r["success"]]),
        }
    
    async def generate_paper(self, domain: str, topic: str, results: list) -> dict:
        """Generate a paper with real experimental data and LLM synthesis."""
        tool_sections = []
        experiment_ids = []
        successful_results = [
            r for r in results
            if r.get("success")
            and assess_tool_output(r.get("result", ""), r.get("tool")).get("usable", False)
        ]
        failed_results = [r for r in results if r not in successful_results]

        # Build rich results section with full data
        results_text_parts = []
        for i, r in enumerate(successful_results):
            # Sanitize input to avoid markdown/XML parse errors in PDF generator
            safe_input = r['input'].replace('*', '×').replace('_', '-').replace('<', '').replace('>', '')
            safe_result = r['result'][:600].replace('<', '').replace('>', '')
            section_content = f"**Tool:** {r['tool']}\n**Input:** {safe_input}\n\n**Output:**\n{safe_result}"
            tool_sections.append({
                "heading": r["description"],
                "content": section_content,
            })
            experiment_ids.append(r["experiment_id"])
            results_text_parts.append(f"[{r['description']}]: {r['result'][:200]}")

        # Synthesize results with LLM for rich discussion
        results_summary = "\n".join(results_text_parts)
        
        intro = (
            f"This study presents a computational investigation of {topic} using {len(tool_sections)} "
            f"usable Atlas platform outputs after excluding {len(failed_results)} failed or unusable "
            f"tool executions. Each reported data point represents a real computational output from the {domain} "
            f"domain toolkit. The investigation covers: {', '.join(r['description'] for r in successful_results)}."
        )
        methods = (
            f"All computations were performed using the AXIOM Atlas tool platform on Apple Silicon M4. "
            f"The following {len(tool_sections)} tool outputs passed the operational quality gate:\n"
            + "\n".join(f"- **{r['tool']}**: {r['description']}" for r in successful_results)
        )
        if failed_results:
            methods += (
                f"\n\nThe quality gate excluded {len(failed_results)} failed or unusable tool outputs "
                f"before manuscript synthesis. Excluded runs remain available in provenance records "
                f"and are not treated as scientific evidence."
            )
        results_full = "\n\n".join(
            f"### {s['heading']}\n{s['content']}" for s in tool_sections
        )
        discussion = (
            f"{len(successful_results)} tool outputs passed the usability gate, producing computational "
            f"data for {topic}; {len(failed_results)} outputs were excluded. Key numerical findings:\n\n{results_summary}\n\n"
            f"These results collectively demonstrate reproducible computational verification "
            f"in the {domain} domain using Atlas tools."
        )
        conclusion = (
            f"This autonomous computational study of {topic} produced {len(successful_results)} "
            f"usable experimental results using Atlas tools after excluding {len(failed_results)} failed outputs. "
            f"Domain: {domain.upper()}. Computation: Apple Silicon M4, Python 3.13, AXIOM Atlas."
        )

        return await self.pg.generate_paper(
            title=f"Computational Analysis of {topic}",
            abstract=(
                f"A.M.Y. autonomous system retained {len(successful_results)} usable Atlas outputs "
                f"and excluded {len(failed_results)} failed or unusable outputs while computationally "
                f"investigating {topic}. Data spans: {results_summary[:300]}."
            ),
            sections=[
                {"heading": "Introduction", "content": intro},
                {"heading": "Methods", "content": methods},
                {"heading": "Results", "content": results_full},
                {"heading": "Discussion", "content": discussion},
                {"heading": "Conclusion", "content": conclusion},
            ],
            references=["A.M.Y (2026). AXIOM Atlas Platform, Apple Silicon M4."],
            knowledge_facts=[{"subject": domain, "predicate": "verified", "object": topic, "confidence": 0.99}],
            experiment_ids=experiment_ids,
            domain=domain,
            tool_results=successful_results,
        )
    
    async def run(self):
        """Main autonomous loop."""
        self.log("=" * 70)
        self.log("A.M.Y AUTONOMOUS MISSION STARTED")
        self.log(f"Duration: {self.duration} seconds ({self.duration/60:.0f} minutes)")
        self.log(f"Domain: {self.fixed_domain or 'ALL (random)'}")
        self.log(f"Model:  {self.model or 'config.yaml default'}")
        self.log("=" * 70)
        
        while self.should_continue():
            if not self.has_mission_start_budget():
                self.log(
                    "⏹️  Remaining time below mission start budget "
                    f"({self.remaining_seconds():.0f}s < {self.mission_start_budget_seconds():.0f}s); stopping."
                )
                break
            try:
                await self.run_mission()                
                # Stats
                remaining = self.remaining_seconds()
                self.log(f"📊 Stats: {self.mission_count} missions, {self.tool_count} tools, {self.paper_count} papers")
                self.log(f"⏱️  Remaining: {remaining/60:.0f} minutes")
                
                # Wait between missions
                if self.should_continue():
                    wait_time = random.randint(5, 15)
                    self.log(f"😴 Sleeping {wait_time}s before next mission...")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                self.log(f"💥 Error in mission: {e}")
                await asyncio.sleep(10)
        
        # Final report
        self.log("=" * 70)
        self.log("A.M.Y AUTONOMOUS MISSION COMPLETED")
        self.log("=" * 70)
        self.log(f"Total missions: {self.mission_count}")
        self.log(f"Total tools executed: {self.tool_count}")
        self.log(f"Total papers generated: {self.paper_count}")
        self.log(f"Duration: {(time.time() - self.start_time)/60:.1f} minutes")


def main():
    parser = argparse.ArgumentParser(description="Run A.M.Y autonomously")
    parser.add_argument("--duration", type=int, default=3600, help="Duration in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--domain", type=str, default=None, help="Fixed domain (default: random)")
    parser.add_argument("--model", type=str, default=None, help="Override LLM model (e.g. kimi-k2.6:cloud, glm-5.1:cloud)")
    args = parser.parse_args()
    
    amy = AutonomousAMY(duration_seconds=args.duration, fixed_domain=args.domain, model=args.model)
    asyncio.run(amy.run())


if __name__ == "__main__":
    main()
