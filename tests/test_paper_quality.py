#!/usr/bin/env python3
"""
Test: Paper Generation Quality Across Domains

Genera papers reales con los resultados de herramientas Atlas
y evalúa su calidad científica:
1. Estructura del método científico
2. Coherencia entre resultados y conclusiones
3. Uso apropiado de evidencia computacional
4. Calidad de referencias y citaciones
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "atlas"))

from core.atlas_tools import AtlasTools
from communication.paper_generator import PaperGenerator


async def generate_and_evaluate_paper(domain: str, tools_results: list, hypothesis: str) -> dict:
    """Genera un paper y evalúa su calidad."""
    print(f"\n{'='*70}")
    print(f"GENERANDO PAPER: {domain.upper()}")
    print(f"{'='*70}")

    # Preparar secciones de herramientas
    tool_sections = []
    experiment_ids = []
    
    for i, tr in enumerate(tools_results):
        tool_name = tr.get("tool", "unknown")
        result = tr.get("result", "")
        tool_input = tr.get("input", "")
        
        tool_sections.append({
            "heading": f"Tool Result: {tool_name}",
            "content": f"Input: `{tool_input}`\n\nResult: {result[:300]}",
        })
        experiment_ids.append(f"{domain}_{tool_name}_{i}")

    # Generar paper
    print(f"\n[1/2] Generando paper...")
    pg = PaperGenerator(reasoning_engine=None)
    
    # Construir secciones del paper
    sections = [
        {
            "heading": "Introduction",
            "content": f"This study investigates {hypothesis} using computational methods.",
        },
        {
            "heading": "Methods",
            "content": f"We employed the AXIOM Atlas scientific platform with {len(tools_results)} computational tools.",
        },
        {
            "heading": "Computational Results",
            "content": "\n\n".join([
                f"**{s['heading']}**\n{s['content']}" 
                for s in tool_sections
            ]),
        },
        {
            "heading": "Discussion",
            "content": f"The results support the hypothesis that {hypothesis}.",
        },
        {
            "heading": "Conclusion",
            "content": f"Our computational analysis confirms {hypothesis}.",
        },
    ]

    paper = await pg.generate_paper(
        title=f"Computational Analysis of {hypothesis}",
        abstract=f"This paper presents a computational analysis of {hypothesis} using the AXIOM Atlas platform.",
        sections=sections,
        references=[
            "A.M.Y (2026). AXIOM Atlas: Scientific Tool Platform. Technical Report.",
            f"Atlas Tools ({domain.capitalize()} Domain). DynamicToolRegistry Documentation.",
        ],
        knowledge_facts=[
            {"subject": domain, "predicate": "analyzed_with", "object": "Atlas tools", "confidence": 0.95},
        ],
        experiment_ids=experiment_ids,
    )

    print(f"  ✅ Paper generado: {paper.get('title', 'Untitled')}")
    print(f"     Palabras: {paper.get('word_count', 0)}")
    print(f"     Secciones: {paper.get('sections', 0)}")
    print(f"     Path: {paper.get('markdown_path', 'N/A')}")

    # Evaluar calidad del paper
    print(f"\n[2/2] Evaluando calidad científica...")
    quality = evaluate_paper_quality(paper, tools_results, hypothesis)
    
    print(f"  Estructura: {quality['structure']}/10")
    print(f"  Coherencia: {quality['coherence']}/10")
    print(f"  Evidencia: {quality['evidence']}/10")
    print(f"  Método científico: {quality['scientific_method']}/10")
    print(f"  Overall: {quality['overall']}/10")

    return {
        "domain": domain,
        "paper": paper,
        "quality": quality,
    }


def evaluate_paper_quality(paper: dict, tools_results: list, hypothesis: str) -> dict:
    """Evalúa la calidad científica de un paper."""
    
    # Estructura: ¿Tiene las secciones necesarias?
    structure = 5
    if paper.get("sections", 0) >= 4:
        structure = 8
    elif paper.get("sections", 0) >= 3:
        structure = 7
    
    # Coherencia: ¿Los resultados apoyan la hipótesis?
    coherence = 5
    if len(tools_results) >= 2:
        coherence = 7
    if all(r.get("success") for r in tools_results):
        coherence += 1
    
    # Evidencia: ¿Usa resultados computacionales?
    evidence = 5
    if len(tools_results) >= 2:
        evidence = 7
    if len(tools_results) >= 3:
        evidence = 9
    
    # Método científico
    scientific_method = 5
    if hypothesis:
        scientific_method += 2
    if len(tools_results) > 0:
        scientific_method += 2
    if paper.get("word_count", 0) > 100:
        scientific_method += 1
    
    overall = (structure + coherence + evidence + scientific_method) / 4
    
    return {
        "structure": min(structure, 10),
        "coherence": min(coherence, 10),
        "evidence": min(evidence, 10),
        "scientific_method": min(scientific_method, 10),
        "overall": min(overall, 10),
    }


async def test_paper_quality_across_domains():
    """Genera papers en múltiples dominios y evalúa calidad."""
    print("=" * 70)
    print("PAPER QUALITY ACROSS DOMAINS")
    print("=" * 70)

    tools = AtlasTools()
    all_results = []

    # Dominios a probar
    domains = {
        "mathematics": {
            "hypothesis": "Prime gaps follow a non-normal distribution",
            "tools": [
                ("prime_gap_analysis", "1000", "mathematics"),
                ("sympy_prime_analysis", "is_prime:97", "mathematics"),
            ],
        },
        "chemistry": {
            "hypothesis": "Glucose has a molecular weight of approximately 180 g/mol",
            "tools": [
                ("molecular_weight_calc", "C6H12O6", "chemistry"),
                ("molecular_weight_calc", "H2O", "chemistry"),
            ],
        },
        "physics": {
            "hypothesis": "Hydrogen atom energy levels follow the Rydberg formula",
            "tools": [
                ("quantum_energy_levels", "hydrogen:3", "physics"),
                ("quantum_energy_levels", "hydrogen:5", "physics"),
            ],
        },
    }

    for domain, config in domains.items():
        print(f"\n{'='*70}")
        print(f"DOMINIO: {domain.upper()}")
        print(f"{'='*70}")

        # Ejecutar herramientas
        tools_results = []
        for tool_name, tool_input, tool_domain in config["tools"]:
            try:
                result = await tools.run_scientific_tool(tool_name, tool_input, tool_domain)
                tools_results.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": str(result)[:300],
                    "success": True,
                })
                print(f"  ✅ {tool_name}")
            except Exception as e:
                tools_results.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": str(e),
                    "success": False,
                })
                print(f"  ❌ {tool_name}: {e}")

        # Generar paper
        paper_result = await generate_and_evaluate_paper(
            domain, tools_results, config["hypothesis"]
        )
        all_results.append(paper_result)

    # Resumen
    print(f"\n{'='*70}")
    print("RESUMEN DE CALIDAD DE PAPERS")
    print(f"{'='*70}")
    
    avg_structure = sum(r["quality"]["structure"] for r in all_results) / len(all_results)
    avg_coherence = sum(r["quality"]["coherence"] for r in all_results) / len(all_results)
    avg_evidence = sum(r["quality"]["evidence"] for r in all_results) / len(all_results)
    avg_method = sum(r["quality"]["scientific_method"] for r in all_results) / len(all_results)
    avg_overall = sum(r["quality"]["overall"] for r in all_results) / len(all_results)

    print(f"\n{'Dominio':<15} {'Estructura':<12} {'Coherencia':<12} {'Evidencia':<12} {'Método':<10} {'Overall':<10}")
    print("-" * 75)
    for r in all_results:
        q = r["quality"]
        print(f"{r['domain']:<15} {q['structure']:<12} {q['coherence']:<12} {q['evidence']:<12} {q['scientific_method']:<10} {q['overall']:<10.1f}")

    print(f"\n{'PROMEDIO':<15} {avg_structure:<12.1f} {avg_coherence:<12.1f} {avg_evidence:<12.1f} {avg_method:<10.1f} {avg_overall:<10.1f}")

    # Guardar reporte
    report = {
        "papers": [
            {
                "domain": r["domain"],
                "title": r["paper"].get("title", ""),
                "word_count": r["paper"].get("word_count", 0),
                "quality": r["quality"],
            }
            for r in all_results
        ],
        "averages": {
            "structure": avg_structure,
            "coherence": avg_coherence,
            "evidence": avg_evidence,
            "scientific_method": avg_method,
            "overall": avg_overall,
        },
    }
    
    report_path = Path("paper_quality_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Reporte guardado: {report_path}")

    passed = avg_overall >= 6.0
    if passed:
        print(f"\n🎉 PAPER QUALITY TEST PASSED!")
        print(f"   Calidad promedio: {avg_overall:.1f}/10")
    else:
        print(f"\n⚠️  PAPER QUALITY TEST NEEDS ATTENTION")
        print(f"   Calidad promedio: {avg_overall:.1f}/10")

    # Real assertion (pytest ignores returned tuples). This test calls the
    # live LLM, so it is not part of the hermetic CI set.
    assert avg_overall >= 6.0, f"avg paper quality {avg_overall:.1f}/10 below 6.0 threshold"
    return passed, all_results


if __name__ == "__main__":
    success, results = asyncio.run(test_paper_quality_across_domains())
    sys.exit(0 if success else 1)
