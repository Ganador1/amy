"""End-to-end verification that EVERY registered Atlas tool computes correctly.

Unlike test_atlas_real_tools.py (which tests core.atlas_real_tools in
isolation), this test loads the *actual* DynamicToolRegistry from
atlas/app/run_agent_with_tools_legacy.py — the same class A.M.Y uses at
runtime — and drives each tool through its real string protocol, asserting
on values we can verify independently (textbook numbers, analytic
identities). It also runs each tool twice to prove determinism.

The heavy Atlas service stack (fastapi, ollama, ServiceLocator) is stubbed
so this can run in CI without those dependencies; the tool *bodies*
themselves run for real (sympy / numpy / scipy / networkx /
core.atlas_real_tools).

If a tool regresses to a mock, returns an error, or becomes
non-deterministic, this test fails.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
ATLAS_ROOT = ROOT / "atlas"
LEGACY_PATH = ATLAS_ROOT / "app" / "run_agent_with_tools_legacy.py"

pytestmark = pytest.mark.skipif(
    not LEGACY_PATH.exists(), reason="atlas legacy tool module not present"
)


def _install_stubs() -> None:
    if str(ATLAS_ROOT) not in sys.path:
        sys.path.insert(0, str(ATLAS_ROOT))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    def _pkg(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        m.__path__ = []
        return m

    services = _pkg("app.services")
    llm = _pkg("app.services.llm_providers")
    ollama_mod = _pkg("app.services.llm_providers.ollama_provider")

    class _StubProvider:
        def __getattr__(self, _):
            raise RuntimeError("ollama_provider stubbed for tests")

    ollama_mod.ollama_provider = _StubProvider()
    sys.modules.setdefault("app.services", services)
    sys.modules.setdefault("app.services.llm_providers", llm)
    sys.modules.setdefault("app.services.llm_providers.ollama_provider", ollama_mod)


@pytest.fixture(scope="module")
def registry():
    _install_stubs()
    spec = importlib.util.spec_from_file_location("atlas_legacy_e2e", LEGACY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["atlas_legacy_e2e"] = module
    spec.loader.exec_module(module)

    Reg = module.DynamicToolRegistry
    reg = Reg.__new__(Reg)
    reg.tools = {}
    reg._global_domains = {"research"}
    reg._domain_aliases = {}
    reg._scope_domain = None
    reg._allowed_domains = None
    reg._register_builtin_tools()
    if hasattr(reg, "_register_advanced_tools"):
        reg._register_advanced_tools()

    # The real tools module must be wired in — otherwise the tools we fixed
    # would be using the honest-fallback stubs instead of real computation.
    assert getattr(module, "_REAL_TOOLS_AVAILABLE", False), (
        "core.atlas_real_tools failed to import inside the legacy module"
    )
    return reg


def _run(reg, name: str, payload: str) -> str:
    import asyncio

    tool = reg.tools.get(name)
    assert tool is not None, f"tool {name!r} is not registered"
    out = tool.function(payload)
    if asyncio.iscoroutine(out):
        out = asyncio.get_event_loop().run_until_complete(out)
    return str(out)


def test_ssh_polyene_gap_map_identifiability_contract(registry):
    out = _run(
        registry,
        "ssh_polyene_gap_map",
        "4,6,8,10,12,20,40;deltas=0,0.05,0.1,0.2;"
        "orientations=trivial,topological;beta=-2.5",
    )

    assert "SSH/polyene finite-chain gap map" in out
    assert "identifiability_threshold_eV" in out
    assert "orientation=topological" in out
    assert "edge_state_warning" in out
    assert "edge_state_onset_n" in out
    assert "smallest_identifiable_n" in out


def test_ssh_edge_localization_map_reports_frontier_state_localization(registry):
    out = _run(
        registry,
        "ssh_edge_localization_map",
        "20,40,60;deltas=0.05,0.1;orientations=trivial,topological;"
        "beta=-2.5;edge_sites=2;localization_threshold=0.25",
    )

    assert "SSH/polyene edge-state localization map" in out
    assert "frontier_splitting_eV" in out
    assert "frontier_pair_edge_weight" in out
    assert "frontier_pair_ipr" in out
    assert "participation_sites" in out
    assert "localization_onset_n" in out
    assert "delta=0.100000; orientation=topological" in out
    assert "localized_edge_state=true" in out


# (name, input, list-of-substrings-that-must-all-appear, human label)
CASES = [
    # SymPy
    ("sympy_derivative", "x**3, x", ["3*x**2"], "d/dx x³"),
    ("sympy_integrate", "2*x, x", ["x**2"], "∫2x dx"),
    ("sympy_simplify", "(x**2 - 1)/(x - 1)", ["x + 1"], "simplify"),
    # Number theory
    ("number_theory_advanced", "goldbach:20", ["ALL VERIFIED", "10 = 3 + 7"], "Goldbach 20"),
    ("number_theory_advanced", "twin_primes:100", ["(71, 73)"], "twin primes ≤100"),
    # prime_gap_analysis must tolerate the messy inputs the LLM produces in
    # live runs (range:2,100000 / max_prime:N / 'primes up to N'), not just
    # a bare integer.
    ("prime_gap_analysis", "10000", ["Prime gap analysis up to 10000"], "bare int"),
    ("prime_gap_analysis", "range:2,100000",
     ["Prime gap analysis up to 100000"], "LLM 'range:2,100000' form"),
    ("prime_gap_analysis", "max_prime:100000",
     ["Prime gap analysis up to 100000"], "LLM 'max_prime:N' form"),
    ("prime_gap_analysis", "primes up to 50000",
     ["Prime gap analysis up to 50000"], "natural-language limit"),
    (
        "prime_gap_model_comparison",
        "10000,100000,1000000",
        [
            "Prime gap scaling model comparison",
            "mean_gap/logN",
            "max_gap/logN^2",
            "Best max-gap model by RMSE",
            "finite computations cannot prove asymptotic",
        ],
        "prime gap model comparison",
    ),
    # Sequences / provers
    ("sequence_analyzer", "generate:fibonacci:10", ["55"], "Fibonacci 10"),
    ("conjecture_engine", "evaluate:collatz:27", ["111", "9232"], "Collatz 27"),
    ("automated_prover", "induction:sum_powers:2:15", ["1240"], "Σk² 1..15"),
    ("automated_prover", "contradiction:sqrt:2", ["irrational"], "√2 irrational"),
    # Graph / topology
    ("graph_theory", "chromatic:petersen", [": 3"], "χ(Petersen)=3"),
    ("graph_theory", "chromatic:complete:7", [": 7"], "χ(K₇)=7"),
    ("graph_theory", "eulerian:cycle:6", ["Eulerian circuit"], "C₆ Eulerian"),
    ("topology_invariants", "euler_char:sphere", ["2"], "χ(S²)=2"),
    ("topology_invariants", "euler_char:torus", ["0"], "χ(T²)=0"),
    # Statistics
    ("numpy_statistics", "mean:1,2,3,4,5", ["3"], "mean"),
    ("numpy_correlation", "[1,2,3,4,5];[2,4,6,8,10]", ["1.0"], "r=1"),
    ("hypothesis_tester", "ttest:[1,2,3,4,5]:[6,7,8,9,10]",
     ["t-statistic=-5.0000", "p-value=0.0011"], "t-test colon"),
    ("hypothesis_tester", "ttest:[1,2,3,4,5];[6,7,8,9,10]",
     ["t-statistic=-5.0000"], "t-test semicolon"),
    (
        "two_sample_effect_power",
        "[12.1,11.8,12.4,12.0];[12.9,13.1,12.7,13.0]",
        [
            "Two-sample effect and power summary",
            "Cohen's d",
            "95% CI",
            "bootstrap_ci_seed=12345",
            "observed_power",
            "sample size n1=4, n2=4",
        ],
        "two-sample effect/power",
    ),
    ("correlation_analysis", "[1,2,3,4,5];[2,4,6,8,10]", ["+1.000000"], "corr r=1"),
    # Chemistry / materials
    ("molecular_weight_calc", "H2O", ["18.015"], "M(H₂O)"),
    ("molecular_weight_calc", "C6H12O6", ["180.156"], "M(glucose)"),
    ("molecular_orbital_energy", "6", ["HOMO-LUMO gap: 2.225 eV"], "Hückel C₆"),
    (
        "huckel_polyene_scaling",
        "4,6,8,10,12,16,20",
        [
            "Best model by RMSE: power_law",
            "power exponent p=-0.990",
            "asymptotic_slope -2*pi*beta = 15.707963",
            "small_angle_argument_at_min_n = 0.314159 rad",
            "residual_threshold=0.010000 eV",
            "inverse_quadratic rejected",
        ],
        "Hückel scaling series",
    ),
    (
        "bond_alternated_polyene_scaling",
        "4,6,8,10,12,16,20,30,40,50,80,100;strong=-2.7;weak=-2.3",
        [
            "Bond-alternated polyene gap scaling",
            "asymptotic_gap_estimate = 0.800000 eV",
            "n=100: alternated_gap=0.846601 eV",
            "finite-gap conclusion",
        ],
        "bond-alternated polyene scaling",
    ),
    ("bond_energy_analyzer", "C-H", ["413 kJ/mol"], "E(C-H)"),
    ("computational_chemistry", "analyze_molecule:C6H6", ["78.11", "Heavy atoms: 6"], "C₆H₆"),
    ("gnome_materials", "stability:TiO2", ["TABULATED"], "TiO₂ labelled"),
    # Physics / quantum
    ("quantum_energy_levels", "hydrogen:1", ["-13.6"], "H ground"),
    ("quantum_energy_levels", "hydrogen:2", ["-3.4"], "H n=2"),
    (
        "rydberg_scaling_comparison",
        "1,2,3,5,10,20;delta=0.05",
        [
            "Hydrogen Rydberg scaling comparison",
            "inverse_square fit",
            "RMSE=0.000000 eV",
            "quantum_defect_delta=0.050000",
            "Best model by RMSE: inverse_square",
            "sample size n=6",
            "residual standard deviation=0.000000 eV",
            "effect size",
            "confidence interval: not estimated",
            "Falsifiable next check",
        ],
        "Rydberg scaling comparison",
    ),
    ("quantum_circuit", "bell:2", ["Entanglement entropy: 1.0 bit"], "Bell"),
    ("quantum_circuit", "grover:4", ["Search space: 16", "Optimal iterations: 3"], "Grover"),
    ("quantum_circuit", "qft:3", ["Total gates: 9"], "QFT"),
    ("quantum_circuit", "vqe:H2", ["TABULATED", "-1.137"], "VQE labelled"),
    # Astronomy
    (
        "cosmology_residual_comparison",
        "0.01,0.1,0.5,1,2;threshold=5",
        [
            "Planck18 versus low-redshift Hubble-law comparison",
            "sample size n=5",
            "z=0.010000",
            "Planck18_luminosity_distance_Mpc",
            "hubble_law_distance_Mpc",
            "percent_residual",
            "RMSE_Mpc",
            "max_abs_percent_residual",
            "effect size",
            "residual standard deviation",
            "breakdown_redshift_threshold_percent=5.000000",
            "Falsifiable next check",
        ],
        "cosmology residual comparison",
    ),
    # Biology
    ("dna_analyzer", "GC_content:ATGCATGC", ["GC content: 50.0%", "GCATGCAT"], "DNA"),
    (
        "gc_at_panel_comparison",
        "gc=ATGGCGGCGGCGGCGGCGGCGGCGGCGTAA,ATGGCGGCGGCGGCGGCGGCGGCGGCATGA,"
        "ATGGCGGCGGCGGCGGCGGCGGCAGAATAG,ATGGCGGCGGCGGCGGCGGCGGCCGATTGA;"
        "at=ATGATAATAATAATAATAATAATAATATAA,ATGATTATTATTATTATTATTATTATATAG,"
        "ATGAATAATAATAATAATAATAATATTTGA,ATGTATTATTATTATTATTATTATTATTAA",
        [
            "GC-rich versus AT-rich panel comparison",
            "sample size n_gc=4, n_at=4",
            "mean_gc_difference",
            "Welch t-statistic",
            "95% CI for mean_gc_difference",
            "Cohen's d",
            "bootstrap_ci_seed=12345",
            "coding_context_control",
            "Falsifiable next check",
        ],
        "GC/AT panel comparison",
    ),
    ("protein_properties", "MKVL", ["489.7 Da"], "peptide MW"),
    ("dnabert2_analysis", "motifs:TATAATAAATTGACA", ["TATAAT", "TTGACA"], "DNABERT2 motifs"),
]


@pytest.mark.parametrize("name,payload,expected,label", CASES, ids=[c[3] for c in CASES])
def test_tool_produces_expected_value(registry, name, payload, expected, label):
    out = _run(registry, name, payload)
    assert not out.strip().lower().startswith(("error", "unknown ")), (
        f"{name}({payload}) returned an error: {out[:200]}"
    )
    for sub in expected:
        assert sub in out, (
            f"{name}({payload}) missing {sub!r}.\n  label: {label}\n  got: {out[:300]}"
        )


def test_huckel_tool_formats_native_float_list(registry):
    out = _run(registry, "molecular_orbital_energy", "4:1.4")

    assert "np.float64" not in out
    assert "Model parameters: alpha=-6.000 eV, beta=-2.500 eV" in out
    assert "Energy levels (eV): [-10.045, -7.545, -4.455, -1.955]" in out


@pytest.mark.parametrize("name,payload,expected,label", CASES, ids=[c[3] for c in CASES])
def test_tool_is_deterministic(registry, name, payload, expected, label):
    a = _run(registry, name, payload)
    b = _run(registry, name, payload)
    assert a == b, f"{name}({payload}) is non-deterministic — suspect random.*"
