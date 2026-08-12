"""
Tool Evidence Orchestrator Service
----------------------------------
Orquesta llamadas a múltiples servicios científicos para reunir evidencia
empírica/simulada que corrobore (o debilite) una hipótesis científica.

Acción principal:
  - action = "corroborate": recibe una hipótesis (dict) con campos
    {title, description, domain, variables, assumptions, expected_outcome}
    y retorna un reporte de evidencia estructurado.

Contrato de salida (simplificado):
{
  success: bool,
  hypothesis_title: str,
  domain: str,
  evidence_items: [
     {
       source: str,               # Nombre servicio/fuente
       operation: str,            # Acción ejecutada
       success: bool,
       signal_strength: float,    # 0-1 estimación heurística de soporte
       raw_result: {...},         # Resultado original (recortado si grande)
       reasoning: str,            # Explicación breve
       duration_seconds: float
     }, ...
  ],
  aggregate: {
     coverage: float,             # fracción de rutas ejecutadas con éxito
     mean_signal: float,          # media signal_strength exitosos
     support_score: float         # combinación final (coverage * mean_signal)
  }
}

Diseño:
  - Mapping dominio -> lista de "rutas" (call specs) con:
        { service: callable_factory, action: str, params: dict, weight: float }
  - Ejecución asíncrona secuencial (podría paralelizarse en futuro) con
    timeouts suaves y manejo robusto de excepciones.
  - Heurísticas simples para señal de soporte (signal_strength) basadas
    en presencia de claves o métricas dentro del resultado.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from typing import Dict, Any, List, Callable
from dataclasses import dataclass
from collections import Counter

from app.services.base_service import BaseService
from app.core.bootstrap_logging import logger
from pathlib import Path
import json
from app.exceptions.domain.biology import BiologyError
from app.types.tool_evidence_orchestrator_types import (
    ProcessRequestResult,
    CorroborateResult,
    ExecuteSpecResult,
    RunInternalActionResult,
    ResolveParamsResult,
    TruncateResult,
)

# Importaciones perezosas dentro de factorías para evitar costos iniciales


@dataclass
class CallSpec:
    service_factory: Callable[[], Any]
    action: str
    params: Dict[str, Any]
    weight: float = 1.0
    description: str = ""


class ToolEvidenceOrchestratorService(BaseService):
    def __init__(self):
        super().__init__("ToolEvidenceOrchestrator")
        self.domain_routes: Dict[str, List[CallSpec]] = self._build_domain_routes()
        logger.info("🧪 ToolEvidenceOrchestratorService inicializado")
        self.log_dir = Path("logs/tool_calls")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Parámetros de early stopping adaptativo
        self.early_min_coverage = 0.5  # si alcanzamos esta cobertura y soporte suficiente, detener
        self.early_support_threshold = 0.45
        self.enable_early_stopping = True
        self.max_parallel_specs = 4  # control de concurrencia para llamadas a herramientas

    REAL_EVIDENCE_TIERS = {"real_remote", "real_local"}
    REALISM_FACTORS = {
        "real_remote": 1.0,
        "real_local": 0.95,
        "heuristic": 0.25,
        "fallback": 0.1,
        "mock": 0.0,
        "auxiliary": 0.0,
        "unavailable": 0.0,
    }

    def _build_domain_routes(self) -> Dict[str, List[CallSpec]]:
        """Definir mapping dominio->lista de CallSpec.
        Factorías devuelven instancia de servicio cuando se invoca.
        """

        def _make_stub_service(name: str, reason: str):
            class _StubService:
                _is_stub_service = True
                _stub_name = name
                _stub_reason = reason

                def process_request(self, request_data):
                    return {
                        "success": False,
                        "error": reason,
                        "missing_dependency": name
                    }

            return _StubService()

        def materials_service_factory():
            from app.domains.chemistry.services.gnome_materials_service import GNOMEMaterialsService
            return GNOMEMaterialsService()

        def plasma_service_factory():
            from app.scientific.plasma_physics_service import PlasmaPhysicsService  # type: ignore
            try:
                return PlasmaPhysicsService()
            except BiologyError:  # fallback placeholder
                return None

        def medical_imaging_factory():
            # Dynamic import to avoid static import errors during analysis
            try:
                import importlib
                mod = importlib.import_module("app.domains.medicine.imaging.medical_imaging_service")
                svc_cls = getattr(mod, "MedicalImagingService", None)
                return svc_cls() if svc_cls else None
            except Exception:  # pragma: no cover - graceful degradation
                return None

        def numpy_factory():
            # Try legacy path first, then new advanced_ops path
            try:
                from app.advanced_numpy_operations import AdvancedNumPyOperations  # type: ignore
                return AdvancedNumPyOperations()
            except Exception:
                try:
                    from app.advanced_ops.advanced_numpy_operations import AdvancedNumPyOperations  # type: ignore
                    return AdvancedNumPyOperations()
                except Exception:
                    return _make_stub_service("AdvancedNumPyOperationsStub", "Advanced NumPy operations not available")

        def sympy_factory():
            from app.services.sympy_service import SymPyService
            return SymPyService()

        # Commented out - advanced_pandas_operations module not available
        # def pandas_factory():
        #     from app.advanced_pandas_operations import AdvancedPandasOperations
        #     return AdvancedPandasOperations()

        def scikit_factory():
            from app.services.scikit_learn_service import ScikitLearnService
            return ScikitLearnService()

        def torch_factory():
            from app.advanced_torch_operations import AdvancedTorchOperations
            return AdvancedTorchOperations()

        def scipy_factory():
            from app.services.scipy_service import SciPyService
            return SciPyService()

        def matplotlib_factory():
            from app.services.matplotlib_service import MatplotlibService
            return MatplotlibService()

        def plotly_factory():
            # Import real Plotly service
            try:
                from app.advanced_ops.advanced_plotly_operations import AdvancedPlotlyOperations
                return AdvancedPlotlyOperations()
            except ImportError as e:
                logger.warning(f"Plotly service not available: {e}")
                return _make_stub_service("PlotlyServiceStub", "Plotly backend not available")

        def transformers_factory():
            # Stub - module not available, returns mock service
            return _make_stub_service("TransformersServiceStub", "Transformers runtime not available")

        def langchain_factory():
            # Stub - module not available, returns mock service
            return _make_stub_service("LangchainServiceStub", "Langchain integration not available")

        def dnabert2_factory():
            from app.services.dnabert2_service import DNABERT2GenomicsService
            return DNABERT2GenomicsService()

        # Commented out - module not found
        # def biomechanical_factory():
        #     from app.biomechanical_models import BiomechanicalModelsService
        #     return BiomechanicalModelsService()

        # Commented out - module not found
        # def additive_manufacturing_factory():
        #     from app.additive_manufacturing_service import AdditiveManufacturingService
        #     return AdditiveManufacturingService()

        def physics_placeholder_factory():
            # Reutilizamos plasma para física si no hay otro servicio especializado
            return plasma_service_factory()

        def chemistry_placeholder_factory():
            # Placeholder: reutilizamos scipy para simulaciones químicas
            return scipy_factory()

        def biology_placeholder_factory():
            # Usar DNABERT2 o biomechanical models para biología
            return dnabert2_factory()

        def pubmed_factory():
            from app.services.pubmed_service import create_pubmed_service
            return create_pubmed_service()

        def literature_service_factory():
            from app.services.literature_service import LiteratureService
            return LiteratureService()

        def external_science_factory():
            from app.services.external_science_service import external_science_service
            return external_science_service

        def scientific_ai_factory():
            from app.services.scientific_ai import ScientificAIService
            return ScientificAIService()

        def molecular_dynamics_factory():
            from app.services.molecular_dynamics import MolecularDynamicsService
            return MolecularDynamicsService()

        def statistical_validation_factory():
            from app.services.statistical_validation_service import StatisticalValidationService
            return StatisticalValidationService()

        def formal_verification_factory():
            from app.services.formal_verification_service import FormalVerificationService
            return FormalVerificationService()

        def quantum_computing_factory():
            from app.domains.physics.services.quantum_computing import QuantumComputingService
            return QuantumComputingService()

        def climate_evidence_factory():
            from app.domains.climate.services.climate_evidence_service import ClimateEvidenceService
            return ClimateEvidenceService()

        # === ADVANCED MATHEMATICS SERVICES ===
        def advanced_number_theory_factory():
            """Factory for advanced number theory service (algebraic fields, elliptic curves)."""
            try:
                from app.domains.mathematics.services.advanced_number_theory_service import AdvancedNumberTheoryService
                return AdvancedNumberTheoryService()
            except ImportError as e:
                logger.warning(f"AdvancedNumberTheoryService not available: {e}")
                return _make_stub_service("AdvancedNumberTheoryService", "Number theory service not available")

        def z3_smt_factory():
            """Factory for Z3 SMT solver for formal verification."""
            try:
                from app.services.theorem_proving.z3_smt_service import Z3SMTService
                return Z3SMTService()
            except ImportError as e:
                logger.warning(f"Z3SMTService not available: {e}")
                return _make_stub_service("Z3SMTService", "Z3 SMT solver not available")

        def automated_theorem_proving_factory():
            """Factory for Lean4/Coq theorem prover integration."""
            try:
                from app.domains.mathematics.services.automated_theorem_proving_service import AutomatedTheoremProvingService
                return AutomatedTheoremProvingService()
            except ImportError as e:
                logger.warning(f"AutomatedTheoremProvingService not available: {e}")
                return _make_stub_service("AutomatedTheoremProvingService", "ATP service not available")

        def counterexample_fuzzer_factory():
            """Factory for counterexample search."""
            try:
                from app.services.verification.counterexample_fuzzer import IntelligentFuzzer
                return IntelligentFuzzer()
            except ImportError as e:
                logger.warning(f"IntelligentFuzzer not available: {e}")
                return _make_stub_service("IntelligentFuzzer", "Counterexample fuzzer not available")

        def hybrid_verification_factory():
            """Factory for hybrid verification combining multiple provers."""
            try:
                from app.services.verification.hybrid_verification_service import HybridVerificationService
                return HybridVerificationService()
            except ImportError as e:
                logger.warning(f"HybridVerificationService not available: {e}")
                return _make_stub_service("HybridVerificationService", "Hybrid verification not available")

        # === NEW ADVANCED MATH TOOLS ===
        def advanced_sympy_operations_factory():
            """Factory for advanced SymPy symbolic computation pipeline."""
            try:
                from app.advanced_ops.advanced_sympy_operations import AdvancedSymPyOperations
                return AdvancedSymPyOperations()
            except ImportError as e:
                logger.warning(f"AdvancedSymPyOperations not available: {e}")
                return _make_stub_service("AdvancedSymPyOperations", "Advanced SymPy operations not available")

        def complex_analysis_factory():
            """Factory for complex analysis service."""
            try:
                from app.services.math.complex_analysis_service import ComplexAnalysisService
                return ComplexAnalysisService()
            except ImportError as e:
                logger.warning(f"ComplexAnalysisService not available: {e}")
                return _make_stub_service("ComplexAnalysisService", "Complex analysis service not available")

        def pde_service_factory():
            """Factory for partial differential equations service."""
            try:
                from app.services.math.pde_service import PDEService
                return PDEService()
            except ImportError as e:
                logger.warning(f"PDEService not available: {e}")
                return _make_stub_service("PDEService", "PDE service not available")

        def statistical_validation_advanced_factory():
            """Factory for advanced statistical validation service."""
            try:
                from app.services.math.statistics_service_advanced import AdvancedStatisticsService
                return AdvancedStatisticsService()
            except ImportError as e:
                logger.warning(f"AdvancedStatisticsService not available: {e}")
                return _make_stub_service("AdvancedStatisticsService", "Advanced statistics not available")

        def topology_builder_factory():
            """Factory for Vietoris-Rips topology construction."""
            try:
                from app.mathlab.topology.topology_builder import VietorisRipsBuilder
                return VietorisRipsBuilder()
            except ImportError as e:
                logger.warning(f"VietorisRipsBuilder not available: {e}")
                return _make_stub_service("VietorisRipsBuilder", "Topology builder not available")

        def graph_invariants_factory():
            """Factory for graph theory invariants computation."""
            try:
                from app.mathlab.invariants.graph_invariants import GraphInvariants
                return GraphInvariants()
            except ImportError as e:
                logger.warning(f"GraphInvariants not available: {e}")
                return _make_stub_service("GraphInvariants", "Graph invariants not available")

        def uncertainty_quantification_factory():
            """Factory for uncertainty quantification in proofs."""
            try:
                from app.quality.uncertainty_quantification import FiducialInferenceQuantifier
                return FiducialInferenceQuantifier()
            except ImportError as e:
                logger.warning(f"FiducialInferenceQuantifier not available: {e}")
                return _make_stub_service("FiducialInferenceQuantifier", "Uncertainty quantification not available")

        def sequence_analyzer_factory():
            """Factory for sequence analysis (OEIS-style)."""
            try:
                from app.mathlab.sequences.sequence_analyzer import SequenceAnalyzer
                return SequenceAnalyzer()
            except ImportError as e:
                logger.warning(f"SequenceAnalyzer not available: {e}")
                return _make_stub_service("SequenceAnalyzer", "Sequence analyzer not available")


        routes: Dict[str, List[CallSpec]] = {
            "climate": [
                CallSpec(
                    service_factory=climate_evidence_factory,
                    action="climate_evidence",
                    params={},
                    weight=1.0,
                    description="Evaluación de soporte climático a partir de datos GISTEMP",
                ),
            ],
            "materials_science": [
                CallSpec(
                    service_factory=materials_service_factory,
                    action="suggest_candidates",
                    params={"target": "thermal conductivity"},
                    weight=1.0,
                    description="Buscar candidatos materiales relacionados a conductividad"
                ),
                CallSpec(
                    service_factory=materials_service_factory,
                    action="predict_properties",
                    params={"formula": "LiFePO4"},
                    weight=0.8,
                    description="Propiedades aproximadas de material base"
                ),
                CallSpec(
                    service_factory=numpy_factory,
                    action="matrix_operations",
                    params={"operation": "eigenvalues", "size": 5},
                    weight=0.7,
                    description="Análisis matricial para propiedades de cristal"
                ),
                CallSpec(
                    service_factory=scikit_factory,
                    action="clustering_analysis",
                    params={"algorithm": "kmeans", "data_type": "material_properties"},
                    weight=0.6,
                    description="Clustering de propiedades de materiales"
                ),
                CallSpec(
                    service_factory=pubmed_factory,
                    action="literature_search",
                    params={"domain": "materials_science", "keywords": ["materials", "nanomaterials", "biomaterials"]},
                    weight=0.95,
                    description="Literatura científica sobre ciencia de materiales"
                ),
            ],
            "drug_discovery": [
                CallSpec(
                    service_factory=dnabert2_factory,
                    action="analyze_sequence",
                    params={"sequence": "ATCGATCGATCG", "task": "classification"},
                    weight=1.0,
                    description="Análisis de secuencia genómica con DNABERT2"
                ),
                CallSpec(
                    service_factory=transformers_factory,
                    action="text_generation",
                    params={"prompt": "molecular structure analysis", "max_length": 100},
                    weight=0.8,
                    description="Generación de texto científico sobre estructuras moleculares"
                ),
                CallSpec(
                    service_factory=torch_factory,
                    action="neural_network_training",
                    params={"architecture": "mlp", "task": "classification"},
                    weight=0.9,
                    description="Entrenamiento de red neuronal para clasificación molecular"
                ),
                CallSpec(
                    service_factory=pubmed_factory,
                    action="literature_search",
                    params={"domain": "drug_discovery", "keywords": ["drug", "pharmaceutical", "therapeutic"]},
                    weight=0.95,
                    description="Literatura científica sobre descubrimiento de fármacos"
                ),
            ],
            "energy_storage": [
                CallSpec(
                    service_factory=materials_service_factory,
                    action="suggest_candidates",
                    params={"target": "energy_density"},
                    weight=1.0,
                    description="Candidatos para almacenamiento energético"
                ),
                CallSpec(
                    service_factory=scipy_factory,
                    action="optimization",
                    params={"method": "minimize", "objective": "energy_efficiency"},
                    weight=0.9,
                    description="Optimización de eficiencia energética"
                ),
                CallSpec(
                    service_factory=matplotlib_factory,
                    action="create_plot",
                    params={"plot_type": "energy_curves", "data_points": 50},
                    weight=0.6,
                    description="Visualización de curvas de energía"
                ),
            ],
            "quantum_computing": [
                CallSpec(
                    service_factory=numpy_factory,
                    action="quantum_simulation",
                    params={"qubits": 4, "gates": ["H", "CNOT"]},
                    weight=1.0,
                    description="Simulación cuántica básica con NumPy"
                ),
                CallSpec(
                    service_factory=sympy_factory,
                    action="quantum_operators",
                    params={"operator": "pauli_matrices", "dimension": 2},
                    weight=0.9,
                    description="Operadores cuánticos simbólicos"
                ),
                CallSpec(
                    service_factory=torch_factory,
                    action="quantum_ml",
                    params={"circuit_depth": 3, "parameters": 8},
                    weight=0.8,
                    description="Machine Learning cuántico con PyTorch"
                ),
                CallSpec(
                    service_factory=quantum_computing_factory,
                    action="process_request",
                    params={
                        "operation": "create_bell_state_qiskit",
                        "backend": "statevector_simulator"
                    },
                    weight=0.85,
                    description="Generación de estado Bell y análisis de probabilidades (Qiskit)"
                ),
                CallSpec(
                    service_factory=quantum_computing_factory,
                    action="process_request",
                    params={
                        "operation": "create_grover_search_qiskit",
                        "n_qubits": 2,
                        "target_state": "11"
                    },
                    weight=0.82,
                    description="Ejecución de Grover para estabilizadores topológicos"
                ),
            ],
            "biophysics": [
                # Commented out - biomechanical_factory not available
                # CallSpec(
                #     service_factory=biomechanical_factory,
                #     action="analyze_biomechanics",
                #     params={"motion_data": "walking", "subject": "human"},
                #     weight=1.0,
                #     description="Análisis biomecánico de movimiento molecular"
                # ),
                CallSpec(
                    service_factory=torch_factory,
                    action="distributed_training_setup",
                    params={"backend": "nccl", "world_size": 1},
                    weight=0.9,
                    description="Setup para modelado de proteínas distribuido"
                ),
                CallSpec(
                    service_factory=scipy_factory,
                    action="optimization",
                    params={"method": "minimize", "objective": "energy_minimization"},
                    weight=0.8,
                    description="Optimización energética de sistemas biofísicos"
                ),
            ],
            "genomics": [
                CallSpec(
                    service_factory=dnabert2_factory,
                    action="analyze_sequence",
                    params={"sequence": "ATCGATCGATCGATCGTAGCTACG", "task": "classification"},
                    weight=1.0,
                    description="Análisis de secuencia genómica con DNABERT2"
                ),
                CallSpec(
                    service_factory=scikit_factory,
                    action="clustering_analysis",
                    params={"algorithm": "pca", "data_type": "genomic_data"},
                    weight=0.9,
                    description="Análisis de genética poblacional"
                ),
                CallSpec(
                    service_factory=matplotlib_factory,
                    action="create_plot",
                    params={"plot_type": "heatmap", "data_points": 100},
                    weight=0.7,
                    description="Visualización de expresión génica"
                ),
            ],
            "biomedical_engineering": [
                CallSpec(
                    service_factory=materials_service_factory,
                    action="suggest_candidates",
                    params={"target": "biocompatibility"},
                    weight=1.0,
                    description="Búsqueda de materiales biocompatibles"
                ),
                CallSpec(
                    service_factory=medical_imaging_factory,
                    action="get_available_segmentation_methods",
                    params={},
                    weight=0.9,
                    description="Métodos de segmentación para ingeniería de tejidos"
                ),
                CallSpec(
                    service_factory=torch_factory,
                    action="compile_model",
                    params={"optimization": True},
                    weight=0.8,
                    description="Optimización de modelos para biomateriales"
                ),
            ],
            "neuroscience": [
                CallSpec(
                    service_factory=torch_factory,
                    action="advanced_optimization_loop",
                    params={"model_type": "neural", "epochs": 5},
                    weight=1.0,
                    description="Entrenamiento optimizado de modelos neuronales"
                ),
                CallSpec(
                    service_factory=medical_imaging_factory,
                    action="get_available_segmentation_methods",
                    params={},
                    weight=0.9,
                    description="Métodos disponibles para segmentación cerebral"
                ),
                CallSpec(
                    service_factory=scipy_factory,
                    action="numerical_integration",
                    params={"function": "sin(x)", "limits": [0, 3.14159]},
                    weight=0.8,
                    description="Integración numérica para análisis de señales"
                ),
                CallSpec(
                    service_factory=plotly_factory,
                    action="create_plot",
                    params={"plot_type": "line", "data_points": 50},
                    weight=0.7,
                    description="Visualización de datos neuronales"
                ),
                CallSpec(
                    service_factory=pubmed_factory,
                    action="literature_search",
                    params={"domain": "neuroscience", "keywords": ["neural", "brain", "neuron"]},
                    weight=0.95,
                    description="Búsqueda de literatura científica en neurociencia"
                ),
            ],
            "mathematics": [
                CallSpec(
                    service_factory=numpy_factory,
                    action="vectorized_demo",
                    params={"op": "vectorized", "arrays": [[1,2,3],[4,5,6]]},
                    weight=0.7,
                    description="Operaciones vectorizadas NumPy básicas"
                ),
                CallSpec(
                    service_factory=sympy_factory,
                    action="diff_polynomial",
                    params={"expr": "x**3 + 2*x**2 - x", "var": "x"},
                    weight=0.9,
                    description="Diferenciación simbólica de polinomio"
                ),
                CallSpec(
                    service_factory=scipy_factory,
                    action="process_request",
                    params={
                        "operation": "integrate",
                        "expression": "sin(x)",
                        "variable": "x",
                        "definite": True,
                        "lower": 0,
                        "upper": 3.14159
                    },
                    weight=0.8,
                    description="Integración numérica con SciPy"
                ),
                # === ADVANCED MATHEMATICS TOOLS ===
                CallSpec(
                    service_factory=z3_smt_factory,
                    action="verify_smt2",
                    params={
                        "statement": "{title}",
                        "context": "{description}",
                        "timeout_ms": 5000
                    },
                    weight=1.2,  # High weight - critical for verification
                    description="Verificación SMT con Z3 para validar conjeturas"
                ),
                CallSpec(
                    service_factory=automated_theorem_proving_factory,
                    action="check_proof",
                    params={
                        "conjecture": "{title}",
                        "context": "{description}",
                        "system": "lean4"
                    },
                    weight=1.1,
                    description="Verificación formal con Lean4/Coq"
                ),
                CallSpec(
                    service_factory=counterexample_fuzzer_factory,
                    action="find_counterexample",
                    params={
                        "statement": "{title}",
                        "domain": "mathematics",
                        "iterations": 1000
                    },
                    weight=1.0,
                    description="Búsqueda de contraejemplos mediante fuzzing"
                ),
                CallSpec(
                    service_factory=advanced_number_theory_factory,
                    action="analyze_conjecture",
                    params={
                        "conjecture": "{title}",
                        "check_primes": True,
                        "check_algebraic": True
                    },
                    weight=0.95,
                    description="Análisis con teoría de números avanzada"
                ),
                CallSpec(
                    service_factory=hybrid_verification_factory,
                    action="verify_with_multiple_backends",
                    params={
                        "statement": "{title}",
                        "backends": ["z3", "cvc5"],
                        "timeout": 10
                    },
                    weight=0.85,
                    description="Verificación híbrida con múltiples SMT solvers"
                ),
                # === NEW ADVANCED MATH TOOLS ===
                CallSpec(
                    service_factory=advanced_sympy_operations_factory,
                    action="symbolic_computation_pipeline",
                    params={
                        "problem": {
                            "type": "algebraic",
                            "expression": "{title}",
                            "operations": ["simplify", "expand", "factor"]
                        }
                    },
                    weight=1.0,
                    description="Pipeline simbólico completo SymPy"
                ),
                CallSpec(
                    service_factory=complex_analysis_factory,
                    action="analyze",
                    params={
                        "expression": "{title}",
                        "domain": "complex"
                    },
                    weight=0.8,
                    description="Análisis complejo de funciones"
                ),
                CallSpec(
                    service_factory=pde_service_factory,
                    action="solve_pde",
                    params={
                        "equation": "{title}",
                        "boundary_conditions": "natural"
                    },
                    weight=0.75,
                    description="Resolución de ecuaciones en derivadas parciales"
                ),
                CallSpec(
                    service_factory=statistical_validation_advanced_factory,
                    action="validate_statistically",
                    params={
                        "hypothesis": "{title}",
                        "sample_size": 10000,
                        "confidence_level": 0.95
                    },
                    weight=0.9,
                    description="Validación estadística avanzada de hipótesis"
                ),
                CallSpec(
                    service_factory=topology_builder_factory,
                    action="build_space",
                    params={
                        "type": "manifold",
                        "description": "{title}"
                    },
                    weight=0.7,
                    description="Construcción de espacios topológicos"
                ),
                CallSpec(
                    service_factory=graph_invariants_factory,
                    action="compute_invariants",
                    params={
                        "graph_spec": "{title}",
                        "invariants": ["chromatic_number", "clique_number", "connectivity"]
                    },
                    weight=0.85,
                    description="Cálculo de invariantes de grafos"
                ),
                CallSpec(
                    service_factory=uncertainty_quantification_factory,
                    action="quantify_uncertainty",
                    params={
                        "statement": "{title}",
                        "method": "bayesian"
                    },
                    weight=0.8,
                    description="Cuantificación de incertidumbre en resultados"
                ),
                CallSpec(
                    service_factory=sequence_analyzer_factory,
                    action="analyze_sequence",
                    params={
                        "sequence_spec": "{title}",
                        "check_oeis": True,
                        "max_terms": 100
                    },
                    weight=0.75,
                    description="Análisis de secuencias estilo OEIS"
                ),
            ],
            "number_theory": [
                CallSpec(
                    service_factory=sympy_factory,
                    action="diff_polynomial",
                    params={"expr": "{title}", "var": "x"},
                    weight=0.9,
                    description="Análisis simbólico de conjetura numérica"
                ),
                CallSpec(
                    service_factory=numpy_factory,
                    action="vectorized_demo",
                    params={"op": "vectorized", "arrays": [[1,2,3],[4,5,6]]},
                    weight=0.7,
                    description="Validación numérica de propiedades"
                ),
                CallSpec(
                    service_factory=literature_service_factory,
                    action="verify_hypothesis_plus",
                    params={"topic": "{title}"},
                    weight=0.85,
                    description="Búsqueda de literatura en teoría de números"
                ),
                CallSpec(
                    service_factory=sympy_factory,
                    action="process_request",
                    params={
                        "operation": "integrate",
                        "expression": "exp(-x**2)",
                        "variable": "x",
                        "definite": True,
                        "lower": 0,
                        "upper": 5
                    },
                    weight=0.78,
                    description="Integración gaussiana para estimaciones probabilísticas de gaps"
                ),
                CallSpec(
                    service_factory=statistical_validation_factory,
                    action="power_analysis",
                    params={
                        "operation": "power_analysis",
                        "effect_size": 0.3,
                        "sample_size": 120,
                        "alpha": 0.05
                    },
                    weight=0.72,
                    description="Análisis de potencia para experimentos numéricos sobre gaps primos"
                ),
                CallSpec(
                    service_factory=scientific_ai_factory,
                    action="scientific_reasoning_chain",
                    params={
                        "operation": "scientific_reasoning_chain",
                        "problem": "{title}",
                        "context": "{description}",
                        "steps": 5
                    },
                    weight=0.74,
                    description="Cadena de razonamiento para heurísticas de teoría analítica de números"
                ),
                # === ADVANCED NUMBER THEORY TOOLS ===
                CallSpec(
                    service_factory=z3_smt_factory,
                    action="verify_number_theory",
                    params={
                        "conjecture": "{title}",
                        "bounds": {"n_min": 1, "n_max": 1000},
                        "timeout_ms": 10000
                    },
                    weight=1.2,
                    description="Verificación SMT de conjeturas de teoría de números"
                ),
                CallSpec(
                    service_factory=automated_theorem_proving_factory,
                    action="verify_conjecture",
                    params={
                        "statement": "{title}",
                        "domain": "number_theory",
                        "system": "lean4"
                    },
                    weight=1.1,
                    description="Prueba formal de conjeturas con Lean4"
                ),
                CallSpec(
                    service_factory=counterexample_fuzzer_factory,
                    action="search_counterexample_number_theory",
                    params={
                        "conjecture": "{title}",
                        "search_range": {"start": 1, "end": 100000},
                        "iterations": 5000
                    },
                    weight=1.0,
                    description="Búsqueda exhaustiva de contraejemplos en teoría de números"
                ),
                CallSpec(
                    service_factory=advanced_number_theory_factory,
                    action="analyze_prime_gap",
                    params={
                        "conjecture": "{title}",
                        "prime_limit": 10000,
                        "check_cramer": True
                    },
                    weight=1.05,
                    description="Análisis de gaps entre primos y conjeturas relacionadas"
                ),
                CallSpec(
                    service_factory=advanced_number_theory_factory,
                    action="elliptic_curve_analysis",
                    params={
                        "conjecture": "{title}",
                        "check_bsd": True,
                        "modular_forms": True
                    },
                    weight=0.95,
                    description="Análisis con curvas elípticas y formas modulares"
                ),
                CallSpec(
                    service_factory=hybrid_verification_factory,
                    action="multi_solver_verify",
                    params={
                        "statement": "{title}",
                        "solvers": ["z3", "cvc5"],
                        "timeout_per_solver": 5
                    },
                    weight=0.90,
                    description="Verificación multi-solver para mayor confianza"
                ),
            ],
            "physics": [
                CallSpec(
                    service_factory=physics_placeholder_factory,
                    action="quick_sanity",
                    params={"dimension": 6},
                    weight=0.6,
                    description="Chequeo físico (plasma) reutilizado"
                ),
                CallSpec(
                    service_factory=sympy_factory,
                    action="symbolic_energy",
                    params={"expr": "1/2*m*v**2 + m*g*h", "vars": ["m","v","g","h"]},
                    weight=0.8,
                    description="Expresión simbólica de energía mecánica"
                ),
                CallSpec(
                    service_factory=plotly_factory,
                    action="physics_visualization",
                    params={"system": "harmonic_oscillator", "time_steps": 100},
                    weight=0.7,
                    description="Visualización interactiva de sistemas físicos"
                ),
            ],
            "chemistry": [
                CallSpec(
                    service_factory=chemistry_placeholder_factory,
                    action="stoichiometry_demo",
                    params={"reactants": {"H2":2, "O2":1}, "products": {"H2O":2}},
                    weight=0.7,
                    description="Balance sencillo de reacción (heurístico)"
                ),
                CallSpec(
                    service_factory=langchain_factory,
                    action="advanced_agent_pipeline",
                    params={"agent_type": "chemistry", "task": "molecular_analysis"},
                    weight=0.8,
                    description="Agente químico con LangChain"
                ),
            ],
            "biology": [
                CallSpec(
                    service_factory=biology_placeholder_factory,
                    action="analyze_sequence",
                    params={"sequence": "ATCGATCGATCG", "task": "classification"},
                    weight=0.9,
                    description="Análisis de secuencia con DNABERT2"
                ),
                # Commented out - biomechanical_factory not available
                # CallSpec(
                #     service_factory=biomechanical_factory,
                #     action="analyze_biomechanics",
                #     params={"motion_data": "walking", "subject": "human"},
                #     weight=0.8,
                #     description="Análisis biomecánico de movimiento"
                # ),
                # Commented out - pandas_factory not available
                # CallSpec(
                #     service_factory=pandas_factory,
                #     action="biological_data_analysis",
                #     params={"data_type": "gene_expression", "samples": 100},
                #     weight=0.7,
                #     description="Análisis de datos biológicos con Pandas"
                # ),
            ],
            "plasma_physics": [
                CallSpec(
                    service_factory=plasma_service_factory,
                    action="quick_sanity",
                    params={"dimension": 8},
                    weight=1.0,
                    description="Chequeo rápido de parámetros de plasma (heurístico)"
                )
            ],
            "medical_imaging": [
                CallSpec(
                    service_factory=medical_imaging_factory,
                    action="list_methods",
                    params={},
                    weight=0.6,
                    description="Listar métodos de segmentación disponibles"
                ),
                CallSpec(
                    service_factory=torch_factory,
                    action="medical_ai_analysis",
                    params={"modality": "MRI", "task": "segmentation"},
                    weight=0.9,
                    description="Análisis de imágenes médicas con IA"
                ),
            ],
            "manufacturing": [
                # Commented out - additive_manufacturing_factory not available
                # CallSpec(
                #     service_factory=additive_manufacturing_factory,
                #     action="optimize_printing",
                #     params={"material": "PLA", "geometry": "complex"},
                #     weight=0.9,
                #     description="Optimización de impresión 3D"
                # ),
                CallSpec(
                    service_factory=scikit_factory,
                    action="quality_prediction",
                    params={"features": ["temperature", "speed", "pressure"]},
                    weight=0.8,
                    description="Predicción de calidad en manufactura"
                ),
            ],
        }

        routes["materials_science"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"hypothesis": "__hypothesis__", "k": 12},
                weight=1.05,
                description="Corroborar hipótesis con literatura y bases científicas"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning",
                params={
                    "operation": "scientific_reasoning",
                    "problem": "{title}",
                    "context": "{description}",
                },
                weight=0.75,
                description="Razonamiento asistido por IA para materiales"
            ),
            CallSpec(
                service_factory=molecular_dynamics_factory,
                action="material_properties",
                params={
                    "material_structure": "{primary_structure}",
                    "property_type": "thermal",
                    "temperature_range": ["{primary_temperature_low}", "{primary_temperature_high}"]
                },
                weight=0.65,
                description="Configurar simulación MD para validar propiedades"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.35,
                    "sample_size": 40,
                    "alpha": 0.05,
                    "test_type": "ttest"
                },
                weight=0.55,
                description="Validación estadística de experimentos de materiales"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="paperqa2_verify_claim",
                params={
                    "claim": "{title}",
                    "domain": "materials_science",
                    "max_results": 8,
                },
                weight=0.72,
                description="Síntesis citada tipo PaperQA2 para hipótesis de materiales"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="mattergen_generate_candidates",
                params={
                    "chemical_system": "{primary_structure}",
                    "target_properties": {"goal": "{description}"},
                    "max_candidates": 6,
                },
                weight=0.7,
                description="Generación de candidatos de materiales vía MatterGen"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="mattersim_simulate_candidates",
                params={
                    "candidates": ["{primary_structure}", "{title}"],
                    "conditions": {
                        "temperature_low": "{primary_temperature_low}",
                        "temperature_high": "{primary_temperature_high}",
                    },
                    "requested_metrics": ["stability", "formation_energy", "elasticity"],
                },
                weight=0.7,
                description="Simulación de candidatos de materiales vía MatterSim"
            ),
            # === NUEVOS CallSpecs: Ronda 4 Scientific Services ===
            CallSpec(
                service_factory=scikit_factory,
                action="process_request",
                params={
                    "operation": "clustering",
                    "algorithm": "kmeans",
                    "n_clusters": 5,
                    "data_description": "material_properties"
                },
                weight=0.70,
                description="Clustering de materiales por propiedades similares (ScikitLearn)"
            ),
            CallSpec(
                service_factory=scipy_factory,
                action="process_request",
                params={
                    "operation": "optimize",
                    "method": "minimize",
                    "function_type": "material_properties_optimization"
                },
                weight=0.68,
                description="Optimización de propiedades de materiales (SciPy)"
            ),
            CallSpec(
                service_factory=matplotlib_factory,
                action="process_request",
                params={
                    "operation": "create_scatter_plot",
                    "title": "Material Properties Distribution",
                    "x_label": "Property A",
                    "y_label": "Property B"
                },
                weight=0.60,
                description="Visualización de distribución de propiedades (Matplotlib)"
            ),
        ])

        routes["drug_discovery"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_chembl",
                params={"query": "{primary_variable_fallback}", "k": 8},
                weight=0.9,
                description="Consulta compuestos relevantes en ChEMBL"
            ),
            CallSpec(
                service_factory=molecular_dynamics_factory,
                action="ligand_binding",
                params={
                    "protein_pdb": "PDB:1CRN",
                    "ligand_smiles": "{primary_variable_fallback}",
                    "binding_site": "active"
                },
                weight=0.7,
                description="Simulación aproximada de unión ligando-proteína"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_database_integration",
                params={
                    "operation": "scientific_database_integration",
                    "query": "{title}",
                    "databases": ["pubmed", "arxiv", "materials_project"]
                },
                weight=0.75,
                description="Integración de información científica multidominio"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.5,
                    "sample_size": 60,
                    "alpha": 0.05,
                    "test_type": "ttest"
                },
                weight=0.5,
                description="Evaluación del poder estadístico de ensayos"
            ),
        ])

        routes["energy_storage"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"hypothesis": "__hypothesis__", "k": 10},
                weight=0.95,
                description="Verificación multifuente para almacenamiento energético"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 6
                },
                weight=0.7,
                description="Cadena de razonamiento interdisciplinar"
            ),
            CallSpec(
                service_factory=molecular_dynamics_factory,
                action="material_properties",
                params={
                    "material_structure": "{primary_structure}",
                    "property_type": "electrical",
                    "temperature_range": ["{primary_temperature_low}", "{primary_temperature_high}"]
                },
                weight=0.6,
                description="Simulación de propiedades eléctricas"
            ),
        ])

        routes["quantum_computing"].extend([
            CallSpec(
                service_factory=quantum_computing_factory,
                action="service_info",
                params={"operation": "service_info"},
                weight=0.6,
                description="Inventario de capacidades cuánticas disponibles"
            ),
            CallSpec(
                service_factory=quantum_computing_factory,
                action="run_vqe",
                params={
                    "operation": "run_vqe",
                    "parameters": {"n_qubits": 2, "problem": "{title}"}
                },
                weight=0.85,
                description="Simulación cuántica VQE de la hipótesis"
            ),
            CallSpec(
                service_factory=quantum_computing_factory,
                action="process_request",
                params={
                    "operation": "run_qaoa",
                    "parameters": {
                        "n_qubits": 4,
                        "depth": 2,
                        "problem": "{title}"
                    }
                },
                weight=0.83,
                description="Optimización QAOA para códigos estabilizadores topológicos"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 5
                },
                weight=0.7,
                description="Razonamiento científico guiado para computación cuántica"
            ),
            CallSpec(
                service_factory=quantum_computing_factory,
                action="process_request",
                params={
                    "operation": "compare_quantum_vs_classical",
                    "problem_size": 4
                },
                weight=0.7,
                description="Comparativa de complejidad entre aproximaciones cuánticas y clásicas"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"topic": "{title}", "k": 12},
                weight=0.88,
                description="Corroboración bibliográfica sobre corrección de errores cuánticos topológicos"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="paperqa2_verify_claim",
                params={
                    "claim": "{title}",
                    "domain": "quantum_computing",
                    "max_results": 8,
                },
                weight=0.7,
                description="Síntesis citada tipo PaperQA2 para hipótesis cuánticas"
            ),
        ])

        routes["biophysics"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_proteins",
                params={"query": "{primary_variable_fallback}", "k": 8},
                weight=0.85,
                description="Búsqueda de evidencia proteica relacionada"
            ),
            CallSpec(
                service_factory=molecular_dynamics_factory,
                action="protein_folding",
                params={
                    "protein_sequence": "{primary_variable_value}",
                    "simulation_time": 20.0
                },
                weight=0.7,
                description="Simulación de plegamiento proteico"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_data_fusion",
                params={
                    "operation": "scientific_data_fusion",
                    "domains": ["biology", "physics"],
                    "focus": "{primary_variable_fallback}"
                },
                weight=0.6,
                description="Fusión de datos científicos biofísicos"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.45,
                    "sample_size": 50,
                    "alpha": 0.05
                },
                weight=0.5,
                description="Análisis de poder estadístico biofísico"
            ),
        ])

        routes["genomics"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_proteins",
                params={"query": "{primary_variable_fallback}", "k": 10},
                weight=0.8,
                description="Búsqueda de literatura de proteínas asociadas"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 6
                },
                weight=0.65,
                description="Cadena de razonamiento genómica"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.5,
                    "sample_size": 80,
                    "alpha": 0.05
                },
                weight=0.55,
                description="Validación estadística genómica"
            ),
        ])

        routes["biomedical_engineering"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_patents",
                params={"query": "{title}", "k": 5},
                weight=0.85,
                description="Revisión de patentes biomédicas"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_database_integration",
                params={
                    "operation": "scientific_database_integration",
                    "query": "{title}",
                    "databases": ["pubmed", "arxiv", "materials_project"]
                },
                weight=0.7,
                description="Integración de información de bases científicas"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.4,
                    "sample_size": 60,
                    "alpha": 0.05
                },
                weight=0.55,
                description="Evaluación estadística para ensayos clínicos"
            ),
        ])

        routes["neuroscience"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"hypothesis": "__hypothesis__", "k": 10},
                weight=0.9,
                description="Corroboración bibliográfica de hipótesis neurocientíficas"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 6
                },
                weight=0.7,
                description="Cadena de razonamiento neurocientífico"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.35,
                    "sample_size": 45,
                    "alpha": 0.05
                },
                weight=0.5,
                description="Análisis de poder de experimentos neuronales"
            ),
            CallSpec(
                service_factory=pubmed_factory,
                action="search",
                params={
                    "query": "{title}",
                    "max_results": 15
                },
                weight=0.85,
                description="Búsqueda PubMed de estudios neurocientíficos"
            ),
            CallSpec(
                service_factory=torch_factory,
                action="process_request",
                params={
                    "operation": "neural_network_optimization",
                    "model_type": "fmri_classifier",
                    "epochs": 50
                },
                weight=0.6,
                description="Optimización ML para análisis neuronal"
            ),
        ])

        routes["mathematics"].extend([
            CallSpec(
                service_factory=formal_verification_factory,
                action="verify_statement",
                params={
                    "type": "verify_theorem",
                    "statement": "{title}",
                    "method": "sympy"
                },
                weight=0.75,
                description="Intento de verificación formal del enunciado"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 5
                },
                weight=0.65,
                description="Cadena de razonamiento matemático"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="search_papers",
                params={"query": "{title}", "k": 8},
                weight=0.6,
                description="Búsqueda de literatura matemática"
            ),
            # === NUEVOS CallSpecs: Ronda 4 Scientific Services ===
            CallSpec(
                service_factory=scipy_factory,
                action="process_request",
                params={
                    "operation": "optimize",
                    "method": "minimize",
                    "function_type": "mathematical_optimization"
                },
                weight=0.72,
                description="Optimización de funciones matemáticas (SciPy)"
            ),
            CallSpec(
                service_factory=scipy_factory,
                action="process_request",
                params={
                    "operation": "stats",
                    "confidence": 0.95
                },
                weight=0.68,
                description="Análisis estadístico para validación matemática (SciPy)"
            ),
            CallSpec(
                service_factory=matplotlib_factory,
                action="process_request",
                params={
                    "operation": "create_line_plot",
                    "title": "Mathematical Function Visualization",
                    "x_label": "x",
                    "y_label": "f(x)"
                },
                weight=0.62,
                description="Visualización de funciones y resultados (Matplotlib)"
            ),
        ])

        routes["physics"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_papers",
                params={"query": "{title}", "k": 10},
                weight=0.85,
                description="Búsqueda de literatura física"
            ),
            CallSpec(
                service_factory=quantum_computing_factory,
                action="service_info",
                params={"operation": "service_info"},
                weight=0.55,
                description="Capacidades cuánticas aplicables"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 6
                },
                weight=0.65,
                description="Cadena de razonamiento físico"
            ),
        ])

        routes["chemistry"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_chembl",
                params={"query": "{primary_variable_fallback}", "k": 8},
                weight=0.85,
                description="Consulta de compuestos y dianas en ChEMBL"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_data_fusion",
                params={
                    "operation": "scientific_data_fusion",
                    "domains": ["chemistry", "physics"],
                    "focus": "{primary_variable_fallback}"
                },
                weight=0.65,
                description="Fusión de datos químicos"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.4,
                    "sample_size": 50,
                    "alpha": 0.05
                },
                weight=0.5,
                description="Evaluación estadística para experimentos químicos"
            ),
        ])

        routes["biology"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"hypothesis": "__hypothesis__", "k": 10},
                weight=0.9,
                description="Corroboración bibliográfica biológica"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="search_proteins",
                params={"query": "{primary_variable_fallback}", "k": 8},
                weight=0.8,
                description="Búsqueda de proteínas relacionadas (UniProt)"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="get_alphafold",
                params={"accession": "{primary_variable_value}"},
                weight=0.65,
                description="Predicciones estructurales AlphaFold para la diana"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="paperqa2_verify_claim",
                params={
                    "claim": "{title}",
                    "domain": "biology",
                    "max_results": 8,
                },
                weight=0.78,
                description="Síntesis citada tipo PaperQA2 para biología"
            ),
            CallSpec(
                service_factory=external_science_factory,
                action="alphagenome_predict_variant_effects",
                params={
                    "sequence": "{description}",
                    "variants": ["{primary_variable_value}"],
                    "assays": ["gene_expression", "chromatin_accessibility"],
                },
                weight=0.72,
                description="Predicción de efectos regulatorios vía AlphaGenome"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 6
                },
                weight=0.65,
                description="Cadena de razonamiento biológico"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.4,
                    "sample_size": 55,
                    "alpha": 0.05
                },
                weight=0.55,
                description="Validación estadística biológica"
            ),
        ])

        routes["medical_imaging"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_papers",
                params={"query": "{title} segmentation", "k": 8},
                weight=0.85,
                description="Literatura sobre técnicas de imagen médica"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                    "context": "{description}",
                    "steps": 5
                },
                weight=0.65,
                description="Cadena de razonamiento en imagen médica"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.3,
                    "sample_size": 40,
                    "alpha": 0.05
                },
                weight=0.5,
                description="Evaluación estadística de estudios de imagen"
            ),
        ])

        routes["manufacturing"].extend([
            CallSpec(
                service_factory=literature_service_factory,
                action="search_patents",
                params={"query": "{title}", "k": 5},
                weight=0.8,
                description="Patentes relevantes en manufactura"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_database_integration",
                params={
                    "operation": "scientific_database_integration",
                    "query": "{title}",
                    "databases": ["pubmed", "arxiv", "materials_project"]
                },
                weight=0.65,
                description="Integración de datos científicos para manufactura"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.35,
                    "sample_size": 45,
                    "alpha": 0.05
                },
                weight=0.45,
                description="Análisis de poder estadístico en manufactura"
            ),
        ])

        # Medicine domain routes
        routes["medicine"] = [
            CallSpec(
                service_factory=pubmed_factory,
                action="literature_search",
                params={"domain": "medicine", "keywords": ["clinical", "therapeutic", "drug"]},
                weight=0.95,
                description="Búsqueda de literatura médica en PubMed"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"topic": "{title}"},
                weight=0.85,
                description="Validación de hipótesis médica con literatura"
            ),
            CallSpec(
                service_factory=literature_service_factory,
                action="get_alphafold",
                params={"protein_id": "{target_protein}"},
                weight=0.80,
                description="Obtener estructura AlphaFold de proteína objetivo"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                },
                weight=0.70,
                description="Razonamiento científico para hipótesis médica"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.3,
                    "sample_size": 100,
                    "alpha": 0.05
                },
                weight=0.55,
                description="Análisis estadístico de validación clínica"
            ),
        ]

        # Astronomy domain routes
        routes["astronomy"] = [
            CallSpec(
                service_factory=literature_service_factory,
                action="verify_hypothesis_plus",
                params={"topic": "{title}"},
                weight=0.90,
                description="Búsqueda de literatura astronómica"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_reasoning_chain",
                params={
                    "operation": "scientific_reasoning_chain",
                    "problem": "{title}",
                },
                weight=0.75,
                description="Razonamiento científico astronómico"
            ),
            CallSpec(
                service_factory=torch_factory,
                action="advanced_optimization_loop",
                params={"model_type": "astronomical", "epochs": 5},
                weight=0.85,
                description="Optimización de modelos astronómicos con ML"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.4,
                    "sample_size": 50,
                    "alpha": 0.05
                },
                weight=0.50,
                description="Análisis estadístico de observaciones"
            ),
        ]

        # Engineering domain routes
        routes["engineering"] = [
            CallSpec(
                service_factory=literature_service_factory,
                action="search_patents",
                params={"query": "{title}", "k": 8},
                weight=0.85,
                description="Búsqueda de patentes en ingeniería"
            ),
            CallSpec(
                service_factory=scientific_ai_factory,
                action="scientific_database_integration",
                params={
                    "operation": "scientific_database_integration",
                    "query": "{title}",
                    "databases": ["pubmed", "arxiv", "materials_project"]
                },
                weight=0.75,
                description="Integración de bases de datos científicas"
            ),
            CallSpec(
                service_factory=torch_factory,
                action="advanced_optimization_loop",
                params={"model_type": "engineering", "epochs": 3},
                weight=0.80,
                description="Optimización de diseño con ML"
            ),
            CallSpec(
                service_factory=statistical_validation_factory,
                action="power_analysis",
                params={
                    "operation": "power_analysis",
                    "effect_size": 0.35,
                    "sample_size": 60,
                    "alpha": 0.05
                },
                weight=0.50,
                description="Validación estadística de experimentos"
            ),
        ]

        return routes

    async def process_request(self, request_data: ProcessRequestResult) -> ProcessRequestResult:  # type: ignore[override]
        global_timeout = 90.0
        try:
            action = request_data.get("action")
            if action == "corroborate":
                # Enforce a global deadline so callers (e.g. AtlasTools with
                # asyncio.wait_for) can actually time out. Without this, a
                # domain with 15 routes × 30s per-route timeout can run for
                # minutes, freezing the event loop.
                raw_timeout = os.environ.get("ORCHESTRATOR_GLOBAL_TIMEOUT", "90")
                try:
                    global_timeout = float(raw_timeout)
                except (TypeError, ValueError):
                    return {
                        "success": False,
                        "status": "configuration_error",
                        "error": "ORCHESTRATOR_GLOBAL_TIMEOUT must be a finite number between 0.1 and 600 seconds",
                    }
                if not math.isfinite(global_timeout) or not 0.1 <= global_timeout <= 600:
                    return {
                        "success": False,
                        "status": "configuration_error",
                        "error": "ORCHESTRATOR_GLOBAL_TIMEOUT must be a finite number between 0.1 and 600 seconds",
                    }
                return await asyncio.wait_for(
                    self._corroborate(request_data),
                    timeout=global_timeout,
                )
            return {"success": False, "error": f"Unknown action: {action}", "available_actions": ["corroborate"]}
        except asyncio.TimeoutError:
            return {
                "success": False,
                "status": "timed_out",
                "error": f"Orchestrator global timeout ({global_timeout}s) exceeded",
                "aggregate": {"coverage": 0, "support_score": 0, "real_success_count": 0},
                "evidence_items": [],
                "partial_evidence_retained": False,
                "background_sync_operations_may_continue": True,
            }
        except BiologyError as e:
            return self.handle_error(e, "process_request")

    async def _corroborate(self, request_data: CorroborateResult) -> CorroborateResult:
        hypothesis = request_data.get("hypothesis", {})
        domain = hypothesis.get("domain") or request_data.get("domain")
        if not domain:
            return {"success": False, "error": "domain requerido"}

        routes = self.domain_routes.get(domain, [])
        if not routes:
            return {"success": False, "error": f"No hay rutas configuradas para dominio {domain}"}

        # Paralelizar cada spec en tareas
        evidence_items: List[Dict[str, Any]] = []
        total_weight_available = 0.0
        available_specs = 0.0
        early_stop = False

        async def _execute_batch(batch: List[CallSpec]) -> List[Dict[str, Any]]:
            tasks = [asyncio.create_task(self._execute_spec(spec, hypothesis, domain)) for spec in batch]
            return await asyncio.gather(*tasks)

        # Ejecutar en lotes limitados por max_parallel_specs manteniendo opción de early stop
        idx = 0
        total_specs = len(routes)
        while idx < total_specs and not early_stop:
            batch = routes[idx: idx + self.max_parallel_specs]
            idx += len(batch)
            batch_results = await _execute_batch(batch)
            for item in batch_results:
                evidence_items.append(item)
                if item.get("_available", True):
                    total_weight_available += item.get("_weight", 0.0)
                    available_specs += 1.0
            success_items = [
                e for e in evidence_items if e.get("success") and e.get("_available", True)
            ]
            weight_success = sum(e.get("_weight", 0.0) for e in success_items)
            denom = total_weight_available or 1.0
            weighted_coverage = weight_success / denom
            mean_signal = sum(e.get("signal_strength", 0.0) for e in success_items) / max(len(success_items), 1)
            real_weight_success = sum(
                e.get("_weight", 0.0)
                for e in success_items
                if e.get("counts_as_real_evidence")
            )
            real_success_items = [e for e in success_items if e.get("counts_as_real_evidence")]
            real_weighted_coverage = real_weight_success / denom
            real_mean_signal = (
                sum(e.get("signal_strength", 0.0) for e in real_success_items) / max(len(real_success_items), 1)
                if real_success_items
                else 0.0
            )
            real_diversity = (
                len({e.get("source") for e in real_success_items}) / max(len(real_success_items), 1)
                if real_success_items
                else 0.0
            )
            provisional_support = real_weighted_coverage * real_mean_signal * (0.9 + 0.1 * real_diversity)
            if (
                self.enable_early_stopping
                and total_weight_available > 0
                and real_weighted_coverage >= self.early_min_coverage
                and provisional_support >= self.early_support_threshold
            ):
                early_stop = True
                break

        # Métricas agregadas refinadas
        usable_routes = [r for r in routes if r.weight > 0]
        success_items = [e for e in evidence_items if e.get("success") and e.get("_available", True)]
        weight_success = sum(e.get("_weight", 0.0) for e in success_items)
        total_weight = total_weight_available or sum(spec.weight for spec in usable_routes) or 1.0
        divisor = available_specs or len(usable_routes) or 1.0
        coverage = len(success_items) / divisor
        weighted_coverage = weight_success / total_weight
        mean_signal = sum(e.get("signal_strength", 0.0) for e in success_items) / max(len(success_items), 1)
        diversity = len({e.get("source") for e in success_items}) / max(len(success_items), 1) if success_items else 0.0
        failure_count = len([e for e in evidence_items if not e.get("success")])
        nominal_support_score = weighted_coverage * mean_signal * (0.9 + 0.1 * diversity)

        real_success_items = [e for e in success_items if e.get("counts_as_real_evidence")]
        real_weight_success = sum(e.get("_weight", 0.0) for e in real_success_items)
        real_coverage = len(real_success_items) / divisor
        real_weighted_coverage = real_weight_success / total_weight
        real_mean_signal = (
            sum(e.get("signal_strength", 0.0) for e in real_success_items) / max(len(real_success_items), 1)
            if real_success_items
            else 0.0
        )
        real_diversity = (
            len({e.get("source") for e in real_success_items}) / max(len(real_success_items), 1)
            if real_success_items
            else 0.0
        )
        support_score = real_weighted_coverage * real_mean_signal * (0.9 + 0.1 * real_diversity)
        realized_weight = sum(
            e.get("_weight", 0.0) * e.get("realism_factor", 0.0)
            for e in success_items
        )
        tool_realism_score = realized_weight / max(weight_success, 1e-9) if weight_success > 0 else 0.0
        tier_counts = dict(Counter(str(e.get("evidence_tier") or "unknown") for e in evidence_items))
        success_tier_counts = dict(Counter(str(e.get("evidence_tier") or "unknown") for e in success_items))

        # Limpiar campos internos
        for e in evidence_items:
            e.pop("_weight", None)
            e.pop("_available", None)

        return {
            "success": True,
            "hypothesis_title": hypothesis.get("title"),
            "domain": domain,
            "evidence_items": evidence_items,
            "aggregate": {
                "coverage": round(coverage, 3),
                "weighted_coverage": round(weighted_coverage, 3),
                "mean_signal": round(mean_signal, 3),
                "avg_signal": round(mean_signal, 3),  # Alias para compatibilidad
                "diversity": round(diversity, 3),
                "nominal_support_score": round(nominal_support_score, 3),
                "real_coverage": round(real_coverage, 3),
                "real_weighted_coverage": round(real_weighted_coverage, 3),
                "real_mean_signal": round(real_mean_signal, 3),
                "real_diversity": round(real_diversity, 3),
                "tool_realism_score": round(tool_realism_score, 3),
                "failure_count": failure_count,
                "support_score": round(support_score, 3),
                "tool_count": len(evidence_items),  # Total de herramientas ejecutadas
                "success_count": len(success_items),  # Herramientas exitosas
                "real_success_count": len(real_success_items),
                "nonreal_success_count": len(success_items) - len(real_success_items),
                "tier_counts": tier_counts,
                "success_tier_counts": success_tier_counts,
                "total_weight": round(total_weight, 3)  # Peso total disponible
            }
        }

    async def _execute_spec(self, spec: CallSpec, hypothesis: ExecuteSpecResult, domain: str) -> ExecuteSpecResult:
        start = time.time()
        service_instance = None
        try:
            service_instance = spec.service_factory()
            # Si la factoría no pudo construir el servicio, registrar un item fallido pero NO romper todo el flujo
            if service_instance is None:
                tier, realism_factor, class_reason = self._classify_evidence_tier(spec, None, {"error": "service_factory returned None"}, available=False)
                return {
                    "source": "UnavailableService",
                    "operation": spec.action,
                    "success": False,
                    "signal_strength": 0.0,
                    "raw_result": {"error": "service_factory returned None"},
                    "reasoning": "Instancia de servicio no disponible",
                    "duration_seconds": round(time.time() - start, 3),
                    "evidence_tier": tier,
                    "realism_factor": realism_factor,
                    "counts_as_real_evidence": False,
                    "classification_reason": class_reason,
                    "_weight": spec.weight,
                    "_available": False
                }
            if getattr(service_instance, "_is_stub_service", False):
                reason = getattr(service_instance, "_stub_reason", "Service not available")
                source = getattr(service_instance, "_stub_name", "UnavailableService")
                logger.warning(
                    "Skipping stubbed service %s for action %s in domain %s: %s",
                    source,
                    spec.action,
                    domain,
                    reason,
                )
                tier, realism_factor, class_reason = self._classify_evidence_tier(spec, service_instance, {"error": reason}, available=False)
                return {
                    "source": source,
                    "operation": spec.action,
                    "success": False,
                    "signal_strength": 0.0,
                    "raw_result": {"error": reason},
                    "reasoning": f"Dependencia ausente: {reason}",
                    "duration_seconds": round(time.time() - start, 3),
                    "evidence_tier": tier,
                    "realism_factor": realism_factor,
                    "counts_as_real_evidence": False,
                    "classification_reason": class_reason,
                    "_weight": spec.weight,
                    "_available": False
                }
            pr = getattr(service_instance, "process_request", None)
            resolved_params = self._resolve_params(spec.params, hypothesis)
            raw: Any
            # Acciones personalizadas (no expuestas por process_request)
            if not pr or spec.action in {"vectorized_demo", "diff_polynomial", "symbolic_energy", "symbolic_growth", "stoichiometry_demo", "quick_sanity", "numerical_integration"}:
                raw = await self._run_internal_action(spec, service_instance, resolved_params)
            else:
                call_payload = dict(resolved_params)
                call_payload["action"] = spec.action
                if asyncio.iscoroutinefunction(pr):
                    raw = await asyncio.wait_for(pr(call_payload), timeout=12)
                else:
                    loop = asyncio.get_running_loop()
                    raw = await loop.run_in_executor(None, lambda: pr(call_payload))  # type: ignore
            payload_valid, payload_reason = self._validate_evidence_payload(spec, raw)
            available = (
                isinstance(raw, dict)
                and not bool(raw.get("unavailable") or raw.get("missing_dependency"))
            )
            signal = self._compute_signal_strength(spec, raw) if payload_valid else 0.0
            tier, realism_factor, class_reason = self._classify_evidence_tier(spec, service_instance, raw, available=available)
            if not payload_valid:
                tier = "unavailable"
                realism_factor = self.REALISM_FACTORS["unavailable"]
                class_reason = payload_reason
            counts_as_real_evidence = payload_valid and tier in self.REAL_EVIDENCE_TIERS
            item = {
                "source": service_instance.__class__.__name__,
                "operation": spec.action,
                "success": payload_valid,
                "signal_strength": signal,
                "raw_result": self._truncate(raw),
                "reasoning": f"Resultado {spec.action} peso={spec.weight}",
                "duration_seconds": round(time.time() - start, 3),
                "evidence_tier": tier,
                "realism_factor": realism_factor,
                "counts_as_real_evidence": counts_as_real_evidence,
                "classification_reason": class_reason,
                "_weight": spec.weight,
                "_available": available
            }
            self._log_tool_call({
                "hypothesis_title": hypothesis.get("title"),
                "domain": domain,
                "source": service_instance.__class__.__name__,
                "operation": spec.action,
                "params": self._truncate(resolved_params),
                "raw_result": self._truncate(raw),
                "signal_strength": signal,
                "evidence_tier": tier,
                "realism_factor": realism_factor,
                "counts_as_real_evidence": counts_as_real_evidence,
                "timestamp": time.time()
            })
            return item
        except asyncio.TimeoutError:
            tier, realism_factor, class_reason = self._classify_evidence_tier(spec, service_instance, {"error": "timeout"}, available=False)
            return {
                "source": getattr(service_instance, "__class__", type("X", (), {})).__name__,
                "operation": spec.action,
                "success": False,
                "signal_strength": 0.0,
                "raw_result": {"error": "timeout"},
                "reasoning": "Timeout",
                "duration_seconds": round(time.time() - start, 3),
                "evidence_tier": tier,
                "realism_factor": realism_factor,
                "counts_as_real_evidence": False,
                "classification_reason": class_reason,
                "_weight": spec.weight,
                "_available": bool(service_instance)
            }
        except BiologyError as e:  # noqa
            tier, realism_factor, class_reason = self._classify_evidence_tier(spec, service_instance, {"error": str(e)}, available=bool(service_instance))
            return {
                "source": getattr(service_instance, "__class__", type("X", (), {})).__name__,
                "operation": spec.action,
                "success": False,
                "signal_strength": 0.0,
                "raw_result": {"error": str(e)},
                "reasoning": "Excepción",
                "duration_seconds": round(time.time() - start, 3),
                "evidence_tier": tier,
                "realism_factor": realism_factor,
                "counts_as_real_evidence": False,
                "classification_reason": class_reason,
                "_weight": spec.weight,
                "_available": bool(service_instance)
            }
        except Exception as e:
            # Captura de seguridad para evitar que una excepción no contemplada derribe el orquestador
            tier, realism_factor, class_reason = self._classify_evidence_tier(spec, service_instance, {"error": str(e), "type": type(e).__name__}, available=bool(service_instance))
            return {
                "source": getattr(service_instance, "__class__", type("X", (), {})).__name__ if service_instance else "UnavailableService",
                "operation": spec.action,
                "success": False,
                "signal_strength": 0.0,
                "raw_result": {"error": str(e), "type": type(e).__name__},
                "reasoning": "Excepción no controlada",
                "duration_seconds": round(time.time() - start, 3),
                "evidence_tier": tier,
                "realism_factor": realism_factor,
                "counts_as_real_evidence": False,
                "classification_reason": class_reason,
                "_weight": spec.weight,
                "_available": bool(service_instance)
            }

    async def _run_internal_action(self, spec: CallSpec, service_instance: Any, params: RunInternalActionResult) -> RunInternalActionResult:
        """Ejecuta acciones internas sin process_request estandar."""
        act = spec.action
        try:
            if act == "vectorized_demo":
                import numpy as np
                arrays = params.get("arrays", [])
                np_arrays = [np.array(a, dtype=float) for a in arrays[:2]]
                if len(np_arrays) < 2:
                    return {"success": False, "error": "faltan arrays"}
                add = (np_arrays[0] + np_arrays[1]).tolist()
                return {"success": True, "operation": act, "add_result": add, "size": len(add)}
            if act == "diff_polynomial":
                import sympy as sp
                expr_txt = params.get("expr", "x")
                var_txt = params.get("var", "x")
                x = sp.symbols(var_txt)
                expr = sp.sympify(expr_txt)
                deriv = sp.diff(expr, x)
                terms = len(sp.Add.make_args(sp.expand(expr)))
                return {"success": True, "expression": str(expr), "derivative": str(deriv), "terms": terms}
            if act == "symbolic_energy":
                import sympy as sp
                expr = sp.sympify(params.get("expr", "0"))
                vars_ = params.get("vars", [])
                simplified = sp.simplify(expr)
                return {"success": True, "expression": str(expr), "simplified": str(simplified), "vars": vars_}
            if act == "symbolic_growth":
                import sympy as sp
                expr = sp.sympify(params.get("expr", "K/(1+exp(-r*(t-t0)))"))
                t = sp.symbols('t')
                d = sp.diff(expr, t)
                return {"success": True, "expression": str(expr), "d_dt": str(d)}
            if act == "stoichiometry_demo":
                react = params.get("reactants", {})
                prod = params.get("products", {})
                balanced = bool(react and prod)
                return {"success": True, "reactants": react, "products": prod, "balanced": balanced}
            if act == "quick_sanity":
                if hasattr(service_instance, "calculate_plasma_parameters"):
                    plasma_params = service_instance.calculate_plasma_parameters(
                        temperature=float(params.get("temperature", 1e6)),
                        density=float(params.get("density", 1e20)),
                        magnetic_field=float(params.get("magnetic_field", 1.0)),
                    )
                    return {
                        "success": True,
                        "operation": act,
                        "debye_length": plasma_params.debye_length,
                        "plasma_frequency": plasma_params.plasma_frequency,
                        "larmor_radius": plasma_params.larmor_radius,
                        "cyclotron_frequency": plasma_params.cyclotron_frequency,
                    }
                return {"success": False, "error": "quick_sanity requires plasma parameter support"}
            if act == "advanced_optimization_loop":
                # Create a simplified optimization demo to avoid PyTorch compilation issues
                model_type = params.get("model_type", "neural")
                epochs = params.get("epochs", 5)

                # Simplified training simulation
                import torch
                loss_values = []
                for epoch in range(epochs):
                    # Simulate decreasing loss
                    loss = 1.0 - (epoch * 0.1) + torch.randn(1).item() * 0.05
                    loss_values.append(max(0.1, loss))

                return {
                    "success": True,
                    "optimization": "completed",
                    "epochs": epochs,
                    "model_type": model_type,
                    "final_loss": loss_values[-1],
                    "loss_trajectory": loss_values,
                    "convergence": "achieved" if loss_values[-1] < 0.5 else "partial"
                }
            if act == "analyze_sequence":
                # Call the actual method from DNABERT2GenomicsService
                if hasattr(service_instance, "analyze_sequence"):
                    result = service_instance.analyze_sequence(params)
                    return result
                else:
                    return {"success": False, "error": "analyze_sequence method not available"}
            if act == "get_available_segmentation_methods":
                # Call the actual method from MedicalImagingService
                if hasattr(service_instance, "get_available_segmentation_methods"):
                    methods = service_instance.get_available_segmentation_methods()
                    return {"success": True, "segmentation_methods": methods}
                else:
                    return {"success": False, "error": "get_available_segmentation_methods method not available"}
            if act == "numerical_integration":
                # Call the actual method from AdvancedSciPyOperations
                if hasattr(service_instance, "numerical_integration"):
                    function = params.get("function", "sin(x)")
                    limits = params.get("limits", [0, 3.14159])
                    if service_instance.__class__.__name__ == "SciPyService":
                        function_type = "sine" if str(function).strip() == "sin(x)" else str(function)
                        result = service_instance.numerical_integration({
                            "function": function_type,
                            "lower": limits[0],
                            "upper": limits[1],
                            "method": "quad",
                        })
                    else:
                        result = service_instance.numerical_integration(function, limits)
                    if asyncio.iscoroutine(result):
                        result = await result
                    return {"success": True, "integration_result": result, "function": function, "limits": limits}
                else:
                    # Fallback implementation using scipy
                    import scipy.integrate as integrate
                    import numpy as np
                    function_str = params.get("function", "sin(x)")
                    limits = params.get("limits", [0, 3.14159])

                    if function_str == "sin(x)":
                        result, error = integrate.quad(np.sin, limits[0], limits[1])
                        return {"success": True, "integration_result": result, "error": error, "function": function_str, "limits": limits}
                    else:
                        return {"success": True, "integration_result": 1.0, "function": function_str, "limits": limits, "note": "fallback"}
            if act == "create_plot":
                # Call the actual method from AdvancedPlotlyOperations
                if hasattr(service_instance, "create_plot"):
                    plot_params = params
                    result = service_instance.create_plot(plot_params)
                    return {"success": True, "plot_created": True, "params": plot_params, **result}
                else:
                    # Fallback - create a simple mock plot response
                    plot_params = params
                    mock_plot = {
                        "data": [{"type": "scatter", "x": [1, 2, 3], "y": [1, 4, 9]}],
                        "layout": {"title": "Mock Plot", "xaxis": {"title": "X"}, "yaxis": {"title": "Y"}}
                    }
                    return {"success": True, "plot_created": True, "plot_json": json.dumps(mock_plot), "params": plot_params}
            if act == "literature_search":
                # Call PubMed service for literature evidence
                if hasattr(service_instance, "get_domain_evidence"):
                    domain = params.get("domain", "general")
                    keywords = params.get("keywords", [])
                    result = await service_instance.get_domain_evidence(domain, keywords)
                    return {"success": True, "literature_search": "completed", **result}
                else:
                    return {"success": False, "error": "literature_search method not available"}
        except BiologyError as e:  # noqa
            return {"success": False, "error": str(e), "operation": act}
        return {"success": False, "error": "acción interna no reconocida", "operation": act}

    def _resolve_params(self, params: ResolveParamsResult, hypothesis: ResolveParamsResult) -> ResolveParamsResult:
        if not params:
            return {}

        context = self._build_context_map(hypothesis)

        def _resolve(value: Any) -> Any:
            if isinstance(value, str):
                if value == "__hypothesis__":
                    return hypothesis
                if value == "__variables__":
                    return hypothesis.get("variables") or {}
                if value == "__assumptions__":
                    return hypothesis.get("assumptions") or []
                if value.startswith("{") and value.endswith("}") and value.count("{") == 1 and value.count("}") == 1:
                    key = value[1:-1]
                    return context.get(key, value)
                try:
                    return value.format_map(context)
                except BiologyError:
                    return value
            if isinstance(value, list):
                return [_resolve(v) for v in value]
            if isinstance(value, dict):
                return {k: _resolve(v) for k, v in value.items()}
            return value

        return {k: _resolve(v) for k, v in params.items()}

    def _build_context_map(self, hypothesis: Dict[str, Any]) -> "_SafeDict":
        title = hypothesis.get("title") or ""
        description = hypothesis.get("description") or ""
        domain = hypothesis.get("domain") or ""
        variables = hypothesis.get("variables") or {}
        assumptions = hypothesis.get("assumptions") or []
        parameters = hypothesis.get("parameters") or {}

        variable_keys: List[str]
        variable_values: List[Any]
        if isinstance(variables, dict):
            variable_keys = list(variables.keys())
            variable_values = list(variables.values())
        elif isinstance(variables, list):
            variable_keys = [str(v) for v in variables]
            variable_values = variables
        else:
            variable_keys = []
            variable_values = []

        primary_variable = next((v for v in variable_keys if v), None) or title
        primary_value = next((v for v in variable_values if v), None) or primary_variable or title

        context_data = {
            "title": title,
            "description": description,
            "domain": domain,
            "assumptions": assumptions,
            "variables": variables,
            "parameters": parameters,
            "primary_variable": primary_variable,
            "primary_variable_value": primary_value,
            "primary_variable_fallback": primary_value or description or title,
            "primary_sequence": hypothesis.get("sequence") or primary_value or "ACDEFGHIKLMNPQRSTVWY",
            "primary_structure": hypothesis.get("structure") or title or "Unknown",
            "keywords": hypothesis.get("keywords") or list(variable_keys) or title.split(),
            "combined_text": f"{title}. {description}".strip(),
            "primary_problem": hypothesis.get("problem") or description or title,
            "primary_temperature_low": 280,
            "primary_temperature_high": 360,
        }

        return _SafeDict(context_data)

    def _validate_evidence_payload(self, spec: CallSpec, raw: Any) -> tuple[bool, str]:
        if not isinstance(raw, dict) or not raw:
            return False, "La herramienta no devolvió un payload de evidencia no vacío."

        if raw.get("success") is not True:
            return False, "La herramienta no declaró success=true de forma explícita."

        if raw.get("error") or raw.get("errors"):
            return False, "El payload declaró un error y no puede contarse como evidencia."

        if raw.get("unavailable") or raw.get("missing_dependency"):
            return False, "La herramienta o una dependencia no estuvo disponible."

        placeholder_flags = (
            "placeholder",
            "is_placeholder",
            "mock",
            "is_mock",
            "stub",
            "is_stub",
        )
        if any(raw.get(key) for key in placeholder_flags):
            return False, "El payload se identificó como placeholder, mock o stub."

        action = str(spec.action or "").strip().lower()
        returned_action = str(raw.get("action") or "").strip().lower()
        if returned_action and returned_action != action:
            return False, "El action devuelto entra en conflicto con la acción solicitada."

        returned_operation = str(raw.get("operation") or "").strip().lower()
        expected_operation = (
            str(spec.params.get("operation") or "").strip().lower()
            if action == "process_request"
            else action
        )
        if returned_operation and expected_operation and returned_operation != expected_operation:
            return False, "La operation devuelta entra en conflicto con la operación solicitada."

        metadata_keys = {
            "success",
            "status",
            "message",
            "detail",
            "error",
            "errors",
            "unavailable",
            "missing_dependency",
            "backend",
            "source",
            "service",
            "tool",
            "action",
            "operation",
            "metadata",
            "meta",
            "timestamp",
            "started_at",
            "completed_at",
            "duration",
            "duration_seconds",
            "request_id",
            "trace_id",
            "run_id",
            "placeholder",
            "is_placeholder",
            "mock",
            "is_mock",
            "stub",
            "is_stub",
            "note",
            "warning",
            "warnings",
            "version",
        }
        substantive_values = [
            value for key, value in raw.items() if str(key).lower() not in metadata_keys
        ]
        if not any(self._has_substantive_evidence_value(value) for value in substantive_values):
            return False, "El payload contiene sólo metadatos, errores o placeholders."

        return True, "El payload declaró éxito explícito y contiene evidencia sustantiva."

    def _has_substantive_evidence_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if not normalized:
                return False
            placeholder_values = {
                "placeholder",
                "mock",
                "stub",
                "todo",
                "tbd",
                "not implemented",
                "not available",
                "n/a",
                "unknown",
            }
            return normalized not in placeholder_values
        if isinstance(value, dict):
            return any(
                self._has_substantive_evidence_value(nested)
                for nested in value.values()
            )
        if isinstance(value, (list, tuple, set)):
            return any(self._has_substantive_evidence_value(nested) for nested in value)
        return True

    def _compute_signal_strength(self, spec: CallSpec, raw: Dict[str, Any]) -> float:
        if not isinstance(raw, dict):
            return 0.0
        if raw.get("success") is not True:
            return 0.0
        # Métricas reales (si están presentes) ajustan base
        metric_bonus = 0.0
        for key in ("loss", "final_loss", "accuracy", "dice", "f1", "support_score"):
            if key in raw and isinstance(raw.get(key), (int, float)):
                val = float(raw[key])
                if key == "loss" or key == "final_loss":
                    metric_bonus += max(0.0, min(0.2, 0.2 * (1.0 - min(1.0, val))))
                else:
                    metric_bonus += max(0.0, min(0.25, 0.25 * val))
        # Heurística base por acción
        if spec.action == "suggest_candidates":
            cands = raw.get("candidates", [])
            return min(1.0, (0.2 + 0.15 * len(cands) + metric_bonus)) * spec.weight
        if spec.action == "predict_properties":
            props = raw.get("predicted_properties") or raw.get("raw_result", {}).get("predicted_properties", {})
            if isinstance(props, dict):
                return min(1.0, (0.3 + 0.05 * len(props) + metric_bonus)) * spec.weight
        if spec.action in {"verify_hypothesis", "verify_hypothesis_plus"}:
            support = raw.get("support_score")
            if support is None:
                support = raw.get("analysis", {}).get("support_score") if isinstance(raw.get("analysis"), dict) else None
            support = float(support) if isinstance(support, (int, float)) else 0.4
            reasons = raw.get("reasons", [])
            base = 0.35 + 0.45 * min(1.0, support)
            base += min(0.15, 0.03 * len(reasons))
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action in {"search_papers", "search_patents", "search_chembl", "search_proteins", "literature_search"}:
            results = raw.get("results") or raw.get("papers") or []
            if isinstance(results, dict):
                results = results.get("results", [])
            count = len(results) if isinstance(results, list) else 0
            return min(1.0, (0.25 + 0.04 * count + metric_bonus)) * spec.weight
        if spec.action in {"paperqa2_verify_claim", "paperqa2_answer_question"}:
            citations = raw.get("citations") or []
            support = raw.get("support_score")
            support = float(support) if isinstance(support, (int, float)) else 0.4
            count = len(citations) if isinstance(citations, list) else 0
            base = 0.35 + 0.4 * min(1.0, support)
            base += min(0.18, 0.03 * count)
            if raw.get("backend") == "paperqa_package":
                base += 0.05
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "scientific_reasoning_chain":
            trace = raw.get("reasoning_trace", [])
            if isinstance(trace, list) and trace:
                confidences = [float(step.get("confidence", 0.6)) for step in trace if isinstance(step, dict)]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.6
                base = 0.35 + 0.4 * min(1.0, avg_conf)
                base += min(0.2, 0.02 * len(trace))
            else:
                base = 0.3
            if raw.get("final_conclusion"):
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "scientific_reasoning":
            steps = raw.get("steps", [])
            reasoning = raw.get("reasoning_trace", [])
            base = 0.3 + min(0.2, 0.03 * len(steps))
            if reasoning:
                base += 0.1
            if raw.get("conclusion"):
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "scientific_database_integration":
            databases = raw.get("databases_queried", [])
            results = raw.get("results", {})
            coverage = len(databases)
            richness = sum(len(v) if isinstance(v, dict) else 1 for v in results.values()) if isinstance(results, dict) else 0
            base = 0.3 + min(0.25, 0.05 * coverage) + min(0.2, 0.02 * richness)
            if raw.get("cross_references"):
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "scientific_data_fusion":
            sources = raw.get("data_sources", [])
            domain_data = raw.get("domain_data", {})
            base = 0.3 + min(0.25, 0.05 * len(sources))
            base += min(0.2, 0.02 * len(domain_data.keys())) if isinstance(domain_data, dict) else 0
            if raw.get("multidisciplinary_insights"):
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "list_methods":
            methods = raw.get("all_methods") or raw.get("basic_methods")
            if methods:
                return min(1.0, (0.25 + 0.05 * len(methods) + metric_bonus)) * spec.weight
        if spec.action == "quick_sanity":
            return min(1.0, 0.5 + metric_bonus) * spec.weight
        if spec.action == "climate_evidence":
            support = raw.get("support_score")
            mean_signal = raw.get("mean_signal")
            support_val = float(support) if isinstance(support, (int, float)) else 0.0
            signal_val = float(mean_signal) if isinstance(mean_signal, (int, float)) else 0.0
            return min(1.0, 0.25 + 0.45 * support_val + 0.20 * signal_val + metric_bonus) * spec.weight
        if spec.action in {"vectorized_demo", "diff_polynomial", "symbolic_energy", "symbolic_growth"}:
            return min(1.0, 0.45 + metric_bonus) * spec.weight
        if spec.action == "stoichiometry_demo":
            return min(1.0, 0.4 + metric_bonus) * spec.weight
        if spec.action in {"protein_folding", "ligand_binding", "material_properties"}:
            info = raw.get("protein_info") or raw.get("binding_info") or raw.get("material_info") or {}
            base = 0.35 + min(0.25, 0.05 * len(info.keys()))
            if raw.get("simulation_id"):
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "power_analysis":
            analysis = raw.get("analysis", {}) if isinstance(raw.get("analysis"), dict) else raw
            power = analysis.get("statistical_power") if isinstance(analysis, dict) else None
            if power is None and isinstance(analysis, dict):
                power = analysis.get("required_sample_size")
                if isinstance(power, (int, float)) and power > 0:
                    power = min(1.0, 1.0 / (1.0 + (power / 100.0)))
            power_val = float(power) if isinstance(power, (int, float)) else 0.5
            recs = analysis.get("recommendations") if isinstance(analysis, dict) else None
            base = 0.35 + 0.4 * min(1.0, power_val)
            if recs:
                base += min(0.15, 0.02 * len(recs))
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "verify_statement":
            if raw.get("is_valid") is True:
                confidence = raw.get("confidence", 0.6)
                base = 0.4 + 0.4 * min(1.0, float(confidence))
            else:
                base = 0.2
            steps = raw.get("proof_steps") or raw.get("steps") or []
            base += min(0.15, 0.03 * len(steps))
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action in {"service_info", "run_vqe"}:
            results = raw.get("results") or {}
            if spec.action == "run_vqe" and isinstance(results, dict):
                eigenvalue = results.get("eigenvalue")
                base = 0.35 + (0.4 if eigenvalue is not None else 0.2)
            else:
                base = 0.3 + 0.1 * len([k for k, v in raw.items() if v])
            return min(1.0, base + metric_bonus) * spec.weight
        if spec.action == "get_alphafold":
            entries = raw.get("results") or []
            count = len(entries) if isinstance(entries, list) else (1 if entries else 0)
            base = 0.35 + min(0.4, 0.1 * count)
            # bonus si hay url de modelo/cif
            try:
                has_model = any(
                    isinstance(e, dict) and (e.get("model_url") or e.get("cifUrl") or e.get("pdbUrl"))
                    for e in (entries if isinstance(entries, list) else [entries])
                )
            except Exception:
                has_model = False
            if has_model:
                base += 0.1
            return min(1.0, base + metric_bonus) * spec.weight
        # Ajuste adicional por tamaño / diversidad de claves
        base = 0.2 * spec.weight
        try:
            key_factor = min(0.3, 0.02 * len(raw.keys()))
            return min(1.0, base + key_factor + metric_bonus)
        except BiologyError:
            return base

    def _classify_evidence_tier(
        self,
        spec: CallSpec,
        service_instance: Any,
        raw: Any,
        *,
        available: bool,
    ) -> tuple[str, float, str]:
        if not available:
            return "unavailable", self.REALISM_FACTORS["unavailable"], "La herramienta o dependencia no estuvo disponible."

        payload_valid, payload_reason = self._validate_evidence_payload(spec, raw)
        if not payload_valid:
            return "unavailable", self.REALISM_FACTORS["unavailable"], payload_reason

        action = str(spec.action or "")
        source = service_instance.__class__.__name__ if service_instance is not None else "UnavailableService"
        backend = str(raw.get("backend") or "").strip().lower()

        if raw.get("note") == "fallback" or backend == "atlas_fallback":
            return "fallback", self.REALISM_FACTORS["fallback"], "La salida proviene de un fallback heurístico."
        if action in {"paperqa2_verify_claim", "paperqa2_answer_question"} and backend != "paperqa_package":
            return "fallback", self.REALISM_FACTORS["fallback"], "PaperQA2 no está ejecutándose con su backend real."

        if action in {"create_plot", "create_scatter_plot", "create_line_plot", "create_histogram", "create_bar_plot", "create_heatmap", "create_contour_plot", "create_3d_surface", "service_info", "list_methods", "get_available_segmentation_methods"}:
            return "auxiliary", self.REALISM_FACTORS["auxiliary"], "Herramienta auxiliar útil para visualización o inventario, no para evidencia."

        if action in {"advanced_optimization_loop", "vectorized_demo", "stoichiometry_demo"}:
            return "mock", self.REALISM_FACTORS["mock"], "La ruta ejecuta una simulación simplificada o demo."

        if action in {"scientific_reasoning", "scientific_reasoning_chain", "scientific_data_fusion", "scientific_database_integration"} or source == "ScientificAIService":
            return "heuristic", self.REALISM_FACTORS["heuristic"], "La salida es razonamiento asistido por LLM, no medición científica directa."

        if backend == "http":
            return "real_remote", self.REALISM_FACTORS["real_remote"], "La herramienta llamó un endpoint científico remoto real."
        if action in {"search_papers", "search_patents", "search_chembl", "search_proteins", "search_materials", "search_materials_by_chemsys", "get_alphafold", "verify_hypothesis", "verify_hypothesis_plus", "literature_search"}:
            return "real_remote", self.REALISM_FACTORS["real_remote"], "La evidencia proviene de búsqueda o recuperación sobre fuentes científicas reales."
        if action in {"run_vqe", "power_analysis", "diff_polynomial", "symbolic_energy", "symbolic_growth", "numerical_integration", "protein_folding", "ligand_binding", "material_properties"}:
            return "real_local", self.REALISM_FACTORS["real_local"], "La evidencia proviene de computación científica local."
        if action == "quick_sanity" and source == "PlasmaPhysicsService":
            return "real_local", self.REALISM_FACTORS["real_local"], "La evidencia proviene de parámetros físicos de plasma calculados localmente."
        if action == "climate_evidence" and source == "ClimateEvidenceService":
            return "real_local", self.REALISM_FACTORS["real_local"], "La evidencia proviene de análisis local del dataset climático configurado."
        if action == "process_request":
            operation = str(raw.get("operation") or "").strip().lower()
            if operation in {"run_qaoa", "compare_quantum_vs_classical"}:
                return "real_local", self.REALISM_FACTORS["real_local"], "La evidencia proviene de computación cuántica local."
        if source in {
            "QuantumComputingService",
            "StatisticalValidationService",
            "SciPyService",
            "SymPyService",
            "MolecularDynamicsService",
            "LiteratureService",
            "MatplotlibService",
        }:
            tier = "real_remote" if source == "LiteratureService" else "real_local"
            return tier, self.REALISM_FACTORS[tier], "La herramienta ejecutó una capacidad científica real del entorno."

        return "heuristic", self.REALISM_FACTORS["heuristic"], "No fue posible demostrar una fuente científica real para esta salida."

    def _truncate(self, raw: TruncateResult, limit: int = 1200) -> TruncateResult:
        try:
            safe_raw = self._json_safe(raw)
            s = json.dumps(safe_raw, ensure_ascii=False)
            if len(s) <= limit:
                return safe_raw
            return {"truncated": True, "preview": s[:limit]}
        except Exception:
            return {"note": "unserializable"}

    def _log_tool_call(self, record: Dict[str, Any]) -> None:
        """Log tool call synchronously (called from sync context)"""
        try:
            daily = self.log_dir / f"tool_calls_{int(time.time() // 86400)}.jsonl"
            # Sync write since this is called from sync context
            with open(daily, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(self._json_safe(record), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _json_safe(self, value: Any) -> Any:
        """Convert nested scientific results into JSON-safe structures."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, complex):
            return {"real": float(value.real), "imag": float(value.imag)}
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        if hasattr(value, "tolist"):
            try:
                return self._json_safe(value.tolist())
            except Exception:
                pass
        if hasattr(value, "__fspath__"):
            try:
                return str(value)
            except Exception:
                pass
        return str(value)


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
