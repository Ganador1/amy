#!/usr/bin/env python3
import asyncio
import sys
import os
import json
import traceback
import time

# Add project root to path
sys.path.insert(0, os.path.abspath("."))

from core.atlas_tools import AtlasTools, assess_tool_output

# Define representative/valid test inputs for all tools
INPUT_MAPPING = {
    # ── Mathematics ──
    "sympy_solve_equation": "x**2 - 4 = 0",
    "sympy_simplify": "(x**2 - 1)/(x - 1)",
    "sympy_derivative": "x**3, x",
    "sympy_integrate": "2*x, x",
    "sympy_prime_analysis": "is_prime:97",
    "prime_gap_analysis": "1000",
    "prime_gap_hpc": "1e6",
    "number_theory_advanced": "goldbach:20",
    "conjecture_engine": "evaluate:collatz:27",
    "automated_prover": "contradiction:sqrt:2",
    "mathematical_discovery": "pattern_analysis:sequences:fibonacci",
    "sequence_analyzer": "generate:fibonacci:10",
    "symbolic_calculus": "limit:sin(x)/x:x->0",
    "calculus_engine": "limit:sin(x)/x:x->0",
    "julia_computation": 'println("Hello from Julia")',
    "graph_theory": "chromatic:petersen",
    "topology_invariants": "euler_char:sphere",
    "z3_verify_theorem": "x+y=y+x:x,y",
    "z3_prover": "x*x>=0",

    # ── Statistics ──
    "numpy_statistics": "mean:[1,2,3,4,5]",
    "numpy_distribution": "normal:1000,0,1,42",
    "numpy_correlation": "[1,2,3,4,5];[2,4,6,8,10]",
    "correlation_analysis": "[1,2,3,4,5];[2,4,6,8,10]",
    "hypothesis_tester": "ttest:[1,2,3,4,5]:[6,7,8,9,10]",

    # ── Chemistry ──
    "molecular_orbital_energy": "6:1.4",
    "bond_energy_analyzer": "C-H",
    "molecular_weight_calc": "H2O",
    "computational_chemistry": "analyze_molecule:C6H6",
    "pyscf_hf_energy": "H 0 0 0; H 0 0 0.74",
    "pyscf_dft_energy": "H 0 0 0; H 0 0 0.74",
    "ase_optimize": "H2",
    "ase_thermochemistry": "H2:298",

    # ── Biology ──
    "dna_analyzer": "GC_content:ATGCATGC",
    "protein_properties": "MKVL",
    "dnabert2_analysis": "motifs:TATAATAAATTGACA",

    # ── Materials ──
    "gnome_materials": "stability:TiO2",
    "pymatgen_structure": "TiO2",

    # ── Physics ──
    "quantum_energy_levels": "hydrogen:1",
    "quantum_circuit": "bell:2",
    "astropy_constants": "G",
    "astropy_unit_convert": "1:pc:lyr",

    # ── Astronomy ──
    "astropy_cosmology": "luminosity_distance:1.0",
    "astropy_blackbody": "5778",

    # ── Research/Meta ──
    "literature_search": "prime gaps distribution",
    "literature_verify_hypothesis_plus": '{"hypothesis": "Global temperatures are rising", "k": 2}',
    "validate_hypothesis": "medicine:mRNA vaccines are effective",
}

# Add default status check for all service_ tools
# These tools wrap FastAPI microservices and expect a JSON request
SERVICE_PAYLOAD = '{"action": "status"}'

# Representative scientific hypothesis for corroboration tools
CORROBORATE_PAYLOAD = "Global average temperature has risen since the Industrial Revolution"

def classify_result(name, output):
    out_lower = output.lower()
    
    # 1. Blocked
    if "blocked by safety policy" in out_lower or "blocked by atlas misuse policy" in out_lower:
        return "BLOCKED", "Blocked by safety/misuse policy"
        
    # 2. Dependency issues
    dep_markers = ["modulenotfounderror", "not available in this environment", "pyscf not available", "ase not available", "not installed"]
    for marker in dep_markers:
        if marker in out_lower:
            return "FAIL (DEPENDENCY)", f"Missing library: {marker}"
            
    # 3. Code crash
    crash_markers = ["traceback (most recent call last)", "error executing", "unknown operation", "typeerror:", "valueerror:", "nameerror:", "syntaxerror:"]
    for marker in crash_markers:
        if marker in out_lower:
            return "FAIL (CRASH)", f"Code crashed: {marker}"
            
    # 4. Assessment using assess_tool_output
    assessment = assess_tool_output(output, tool_name=name)
    markers = assessment.get("markers", [])
    
    # Check if there are mock/placeholder markers
    mock_markers = ["mock", "placeholder", "dummy", "known weak evidence tool", "not implemented", "mock implementation", "mock output"]
    found_mocks = [m for m in markers if any(x in m for x in mock_markers)]
    if found_mocks or not assessment.get("usable", True):
        # Double check if it's actually a crash that was marked unusable
        if "error:" in out_lower or "failed" in out_lower:
            return "FAIL (CRASH)", f"Execution error: {output[:100]}"
        return "HEURISTIC/MOCK", f"Mock or placeholder: {', '.join(markers)}"
        
    # 5. Success
    return "PASS", "Fully functional"

async def kill_worker(atlas):
    if atlas._worker is not None:
        try:
            print("Terminating Atlas worker subprocess...")
            atlas._worker.kill()
            await atlas._worker.wait()
        except Exception as e:
            print(f"Error terminating worker: {e}")
        atlas._worker = None

async def test_tool(atlas, tool_info):
    name = tool_info["name"]
    domain = tool_info["domain"]
    
    # Determine the payload
    if name in INPUT_MAPPING:
        payload = INPUT_MAPPING[name]
    elif name.startswith("service_"):
        payload = SERVICE_PAYLOAD
    elif name.startswith("evidence_corroborate_"):
        payload = CORROBORATE_PAYLOAD
    else:
        payload = "test"
        
    # Dynamic timeout: 35s for heavy tools, 15s for fast tools
    is_heavy = (
        name.startswith("evidence_corroborate_") or 
        name.startswith("service_") or 
        "pyscf" in name or 
        "astropy" in name or 
        "ase" in name or
        name in ["julia_computation", "topology_invariants", "graph_theory"]
    )
    timeout_limit = 35.0 if is_heavy else 15.0
    
    # Pre-ensure worker is active before starting the timer to avoid counting startup time
    try:
        await atlas._ensure_worker()
    except Exception as e:
        print(f"Error ensuring worker for {name}: {e}")
        
    t0 = time.time()
    try:
        # Execute the tool with a timeout
        output = await asyncio.wait_for(
            atlas.run_scientific_tool(name, payload, domain=domain),
            timeout=timeout_limit
        )
        elapsed = time.time() - t0
        status, reason = classify_result(name, output)
        return {
            "name": name,
            "domain": domain,
            "payload": payload,
            "status": status,
            "reason": reason,
            "elapsed_seconds": round(elapsed, 3),
            "output_preview": output[:300] + ("..." if len(output) > 300 else "")
        }
    except asyncio.TimeoutError:
        elapsed = time.time() - t0
        print(f"⚠️ [TIMEOUT] {name} timed out after {timeout_limit}s. Restarting Atlas worker...")
        await kill_worker(atlas)
        return {
            "name": name,
            "domain": domain,
            "payload": payload,
            "status": "FAIL (TIMEOUT)",
            "reason": f"Execution timed out after {timeout_limit}s",
            "elapsed_seconds": round(elapsed, 3),
            "output_preview": ""
        }
    except Exception as e:
        elapsed = time.time() - t0
        print(f"⚠️ [CRASH] {name} raised exception: {e}. Restarting Atlas worker...")
        await kill_worker(atlas)
        return {
            "name": name,
            "domain": domain,
            "payload": payload,
            "status": "FAIL (CRASH)",
            "reason": f"Runner exception: {str(e)}",
            "elapsed_seconds": round(elapsed, 3),
            "output_preview": traceback.format_exc()
        }

async def main():
    print("=" * 80)
    print("      AXIOM/Atlas 94-Tool Diagnostics Runner (Sequential)")
    print("=" * 80)
    
    # Resolve a writable location for the tool registry snapshot. Prefer the
    # repo-local scratch dir (works for anyone who clones the repo); allow an
    # override via AMY_WORKER_TOOLS_PATH for custom setups.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    scratch_dir = os.path.join(repo_root, "data", "diagnostics")
    os.makedirs(scratch_dir, exist_ok=True)
    tools_path = os.environ.get(
        "AMY_WORKER_TOOLS_PATH", os.path.join(scratch_dir, "worker_tools.json")
    )

    atlas = AtlasTools()

    # Pre-initialize worker with a ping so the first tool doesn't pay startup overhead
    try:
        await atlas._ensure_worker()
        print("Atlas worker successfully initialized.")
    except Exception as e:
        print(f"Warning: worker initialization failed: {e}")

    # Self-generate the tool registry from the live worker. This makes the
    # diagnostic reproducible from a fresh clone — no pre-fetched author file.
    if os.path.exists(tools_path):
        with open(tools_path, "r") as f:
            tools = json.load(f)
        print(f"Loaded {len(tools)} tools from {tools_path}.")
    else:
        print("Fetching tool registry from the live Atlas worker (describe_tools)...")
        described = await atlas.describe_tools(domain=None)
        tools = [{"name": t["name"], "domain": t.get("domain", "")} for t in described]
        with open(tools_path, "w") as f:
            json.dump(tools, f, indent=2)
        print(f"Discovered {len(tools)} tools and cached them to {tools_path}.")
        
    print(f"Beginning sequential tests of {len(tools)} tools...")
    
    results = []
    completed = 0
    total = len(tools)
    
    for tool in tools:
        res = await test_tool(atlas, tool)
        results.append(res)
        completed += 1
        print(f"[{completed}/{total}] {res['status']:18} | {res['name']:35} | {res['elapsed_seconds']}s")
        sys.stdout.flush()
        
    # Sort results by name
    results.sort(key=lambda x: x["name"])
    
    # Save the raw results next to the registry snapshot (repo-local).
    out_path = os.environ.get(
        "AMY_TOOLS_TEST_RESULTS_PATH", os.path.join(scratch_dir, "tools_test_results.json")
    )
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
        
    print("=" * 80)
    print(f"Completed testing. Results saved to {out_path}")
    print("=" * 80)
    
    # Print a quick summary
    summary = {}
    for r in results:
        status = r["status"]
        summary[status] = summary.get(status, 0) + 1
        
    print("Summary:")
    for status, count in sorted(summary.items()):
        print(f"  {status:18}: {count}")
    print("=" * 80)
    
    # Clean up the worker at the end
    await kill_worker(atlas)

if __name__ == "__main__":
    asyncio.run(main())

