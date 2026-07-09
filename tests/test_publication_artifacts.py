import asyncio
import json
from pathlib import Path

from communication.paper_generator import PaperGenerator
from communication.publication_artifacts import PublicationArtifactBuilder


def _passing_reflection(md_content):
    return {
        "annotated_md": md_content,
        "score": 100.0,
        "pass_overall": True,
        "n_high": 0,
        "n_medium": 0,
        "n_low": 0,
        "issues": [],
    }


def test_paper_generator_creates_publication_artifacts_from_numeric_tool_results(tmp_path, monkeypatch):
    monkeypatch.setattr(PaperGenerator, "_run_reflection_gate", staticmethod(_passing_reflection))
    generator = PaperGenerator(enhance=False, output_dir=tmp_path)

    result = asyncio.run(
        generator.generate_paper(
            title="SSH Polyene Identifiability Artifact Test",
            abstract="Finite-chain SSH sweeps are summarized as publication artifacts.",
            sections=[
                {"heading": "Methods", "content": "We sweep bond alternation in a finite SSH chain."},
                {"heading": "Results", "content": "The sweep produced terminal gap and localization measurements."},
                {"heading": "Discussion", "content": "The result is a finite-chain diagnostic, not a proof of a new topological phase."},
                {"heading": "Conclusion", "content": "Publication artifacts should make the evidence inspectable."},
            ],
            references=["Su, W. P., Schrieffer, J. R. & Heeger, A. J. (1979). Solitons in polyacetylene."],
            domain="chemistry",
            tool_results=[
                {
                    "tool": "ssh_polyene_gap_map",
                    "result": "\n".join(
                        [
                            "delta=0.02 terminal_gap=0.094 bulk_gap=0.158225 localization=0.42",
                            "delta=0.04 terminal_gap=0.181 bulk_gap=0.237114 localization=0.51",
                            "delta=0.06 terminal_gap=0.263 bulk_gap=0.315882 localization=0.59",
                        ]
                    ),
                }
            ],
        )
    )

    artifacts = result["publication_artifacts"]

    assert artifacts["tables"], artifacts
    assert artifacts["figures"], artifacts
    assert "row_index" not in artifacts["figures"][0]["caption"]
    assert "terminal_gap" in artifacts["figures"][0]["caption"]
    table_csv = Path(artifacts["tables"][0]["csv_path"])
    table_json = Path(artifacts["tables"][0]["json_path"])
    figure = Path(artifacts["figures"][0]["path"])
    manifest = Path(artifacts["manifest_path"])

    assert table_csv.exists()
    assert table_json.exists()
    assert figure.exists()
    assert manifest.exists()

    rows = json.loads(table_json.read_text(encoding="utf-8"))
    assert rows[0]["delta"] == 0.02
    assert rows[2]["localization"] == 0.59

    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    latex = Path(result["latex_path"]).read_text(encoding="utf-8")

    assert "## Publication Artifacts" in markdown
    assert "Figure 1" in markdown
    assert "artifacts/SSH_Polyene_Identifiability_Artifact_Test/numeric_tool_results.csv" in markdown
    assert str(tmp_path) not in markdown
    assert "\\includegraphics" in latex
    assert str(tmp_path) not in latex


def test_publication_artifacts_builds_literature_novelty_audit_sidecar(tmp_path):
    async def fake_search(query, max_results=8):
        return {
            "papers": [
                {
                    "title": "Extended SSH Model: Non-Local Couplings and Non-Monotonous Edge States",
                    "year": 2025,
                    "doi": "10.0000/example",
                    "url": "https://example.org/ssh-edge-states",
                    "source": "OpenAlex",
                }
            ],
            "sources_succeeded": ["openalex"],
            "support_score": 0.44,
        }

    artifacts = asyncio.run(
        PublicationArtifactBuilder().build_async(
            title="SSH model polyacetylene finite chain edge states identifiability",
            tool_results=[],
            output_dir=tmp_path,
            literature_search=fake_search,
        )
    )

    audit_path = Path(artifacts["literature_audit_path"])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit_path.exists()
    assert audit["verdict"] == "needs_manual_review"
    assert audit["sources_succeeded"] == ["openalex"]
    assert audit["papers"][0]["title"].startswith("Extended SSH Model")
    assert "Literature novelty audit" in artifacts["section"]["content"]
    assert "artifacts/SSH_model_polyacetylene_finite_chain_edge_states_identifiability/literature_novelty_audit.json" in artifacts["section"]["content"]
    assert str(tmp_path) not in artifacts["section"]["content"]


def test_publication_figure_uses_n_as_axis_not_observable_when_delta_exists(tmp_path):
    artifacts = PublicationArtifactBuilder().build(
        title="SSH mixed axis artifact",
        output_dir=tmp_path,
        tool_results=[
            {
                "tool": "ssh_polyene_gap_map",
                "result": "\n".join(
                    [
                        "delta=0.02 n=40 terminal_gap_n100=0.094 peierls_bulk_gap_estimate=0.158 edge_weight=0.41",
                        "delta=0.04 n=60 terminal_gap_n100=0.181 peierls_bulk_gap_estimate=0.237 edge_weight=0.52",
                        "delta=0.06 n=80 terminal_gap_n100=0.263 peierls_bulk_gap_estimate=0.316 edge_weight=0.63",
                    ]
                ),
            }
        ],
    )

    caption = artifacts["figures"][0]["caption"]

    assert "x-axis is `delta`" in caption
    assert " n," not in caption
    assert "terminal_gap_n100" in caption


def test_ssh_publication_figure_uses_domain_specific_caption(tmp_path):
    artifacts = PublicationArtifactBuilder().build(
        title="SSH finite chain artifact",
        output_dir=tmp_path,
        tool_results=[
            {
                "tool": "ssh_polyene_gap_map",
                "result": "\n".join(
                    [
                        "delta=0.02 terminal_gap_n100=0.094 peierls_bulk_gap_estimate=0.158 edge_state_onset_n=60",
                        "delta=0.04 terminal_gap_n100=0.181 peierls_bulk_gap_estimate=0.237 edge_state_onset_n=30",
                        "delta=0.06 terminal_gap_n100=0.263 peierls_bulk_gap_estimate=0.316 edge_state_onset_n=16",
                    ]
                ),
            }
        ],
    )

    caption = artifacts["figures"][0]["caption"]

    assert "SSH finite-chain" in caption
    assert "Peierls" in caption
    assert "edge-state onset" in caption
    assert "Numeric sweep" not in caption


def test_dna_publication_figure_uses_base_composition_caption(tmp_path):
    artifacts = PublicationArtifactBuilder().build(
        title="DNA base composition artifact",
        output_dir=tmp_path,
        tool_results=[
            {
                "tool": "dna_analyzer",
                "result": "\n".join(
                    [
                        "Composition: A=0 T=0 G=10 C=10",
                        "Composition: A=5 T=5 G=5 C=5",
                    ]
                ),
            }
        ],
    )

    figure = artifacts["figures"][0]

    assert Path(figure["path"]).exists()
    assert "DNA base-composition" in figure["caption"]
    assert "A/T/G/C" in figure["caption"]
    assert "Numeric sweep" not in figure["caption"]
    assert figure["path"].endswith("figure_1_dna_base_composition.png")


def test_paper_generator_can_attach_literature_audit_with_search_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(PaperGenerator, "_run_reflection_gate", staticmethod(_passing_reflection))

    async def fake_search(query, max_results=8):
        return {
            "papers": [
                {
                    "title": "Extended SSH Model: Non-Local Couplings and Non-Monotonous Edge States",
                    "year": 2025,
                    "source": "OpenAlex",
                }
            ],
            "sources_succeeded": ["openalex"],
            "support_score": 0.44,
        }

    generator = PaperGenerator(
        enhance=False,
        output_dir=tmp_path,
        include_literature_audit=True,
        literature_search=fake_search,
    )

    result = asyncio.run(
        generator.generate_paper(
            title="SSH model polyacetylene finite chain edge states identifiability",
            abstract="The paper should carry a literature novelty audit.",
            sections=[
                {"heading": "Methods", "content": "We run a finite-chain SSH sweep."},
                {"heading": "Results", "content": "The sweep is compared with nearby literature."},
                {"heading": "Discussion", "content": "Novelty remains unclaimed until the literature audit is reviewed."},
            ],
            references=[],
            domain="chemistry",
            tool_results=[],
        )
    )

    audit_path = Path(result["publication_artifacts"]["literature_audit_path"])
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")

    assert audit_path.exists()
    assert "Literature novelty audit" in markdown
    assert "needs_manual_review" in markdown


def test_markdown_keeps_scientific_audit_sections(tmp_path):
    generator = PaperGenerator(enhance=False, output_dir=tmp_path)

    markdown = generator._build_markdown(
        "Audit Section Test",
        "A deterministic audit.",
        [
            {"heading": "Introduction", "content": "Context."},
            {"heading": "Methods", "content": "Method."},
            {"heading": "Results", "content": "Result."},
            {"heading": "Discussion", "content": "Discussion."},
            {
                "heading": "Testable Predictions",
                "content": "H1. Prediction. Testable via: rerun.",
            },
            {"heading": "Limitations and Scope", "content": "Limitation."},
            {
                "heading": "Reproducibility and Data Availability",
                "content": "Reproducibility.",
            },
            {
                "heading": "Declarations and AI Disclosure",
                "content": "Disclosure.",
            },
            {"heading": "Conclusion", "content": "Conclusion."},
        ],
        references=None,
        knowledge_facts=None,
        experiment_ids=None,
    )

    assert "## Testable Predictions" in markdown
    assert "## Limitations and Scope" in markdown
    assert "## Reproducibility and Data Availability" in markdown
    assert "## Declarations and AI Disclosure" in markdown
