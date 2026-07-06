"""Publication artifact generation for A.M.Y papers.

This module turns raw tool outputs into inspectable paper artifacts: clean
tables, figures, and a manifest. It is intentionally conservative; if no
structured numeric rows are found, it returns an empty artifact set.
"""
from __future__ import annotations

import csv
import inspect
import json
import re
from pathlib import Path
from typing import Any


_PAIR_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
_STOPWORDS = {
    "with", "from", "into", "using", "versus", "finite", "chain", "model",
    "study", "analysis", "computational", "paper", "result", "results",
    "identifiability", "the", "and", "for", "that", "this",
}
_PLOT_METADATA_COLUMNS = {
    "row_index",
    "n",
    "beta",
    "alpha",
    "deltas",
    "edge_sites",
    "threshold",
    "localization_threshold",
    "min_localization_n",
    "residual_threshold",
}


def _safe_slug(text: str) -> str:
    return re.sub(r"[^\w\s-]", "", text).strip().replace(" ", "_")[:80] or "artifact"


def _portable_path(path: Path, output_dir: Path) -> str:
    try:
        return path.relative_to(output_dir).as_posix()
    except ValueError:
        return path.name


def _portable_manifest_table(table: dict[str, Any]) -> dict[str, Any]:
    item = dict(table)
    if item.get("csv_display_path"):
        item["csv_path"] = item["csv_display_path"]
    if item.get("json_display_path"):
        item["json_path"] = item["json_display_path"]
    item.pop("csv_display_path", None)
    item.pop("json_display_path", None)
    return item


def _portable_manifest_figure(figure: dict[str, Any]) -> dict[str, Any]:
    item = dict(figure)
    if item.get("display_path"):
        item["path"] = item["display_path"]
    item.pop("display_path", None)
    return item


def _numeric_rows(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in tool_results:
        tool_name = str(result.get("tool", "unknown_tool"))
        output = str(result.get("result", ""))
        for idx, line in enumerate(output.splitlines()):
            pairs = _PAIR_RE.findall(line)
            if len(pairs) < 2:
                continue
            row: dict[str, Any] = {"tool": tool_name, "row_index": idx}
            for key, value in pairs:
                try:
                    row[key] = float(value)
                except ValueError:
                    continue
            if len(row) > 3:
                rows.append(row)
    return rows


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for preferred in ("tool", "row_index", "delta", "n", "time", "parameter"):
        if any(preferred in row for row in rows):
            columns.append(preferred)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


class PublicationArtifactBuilder:
    """Build tables and figures from structured tool output."""

    async def build_async(
        self,
        *,
        title: str,
        tool_results: list[dict[str, Any]] | None,
        output_dir: Path,
        literature_search: Any | None = None,
        include_literature_audit: bool = True,
    ) -> dict[str, Any]:
        artifacts = self.build(
            title=title,
            tool_results=tool_results,
            output_dir=output_dir,
        )

        if not include_literature_audit:
            return artifacts

        audit = await self._build_literature_audit(
            title=title,
            output_dir=output_dir,
            literature_search=literature_search,
        )
        artifacts["literature_audit"] = audit["audit"]
        artifacts["literature_audit_path"] = audit["path"]
        artifacts["literature_audit_display_path"] = audit["display_path"]
        manifest_path = artifacts.get("manifest_path")
        if not manifest_path:
            artifact_dir = output_dir / "artifacts" / _safe_slug(title)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = str(artifact_dir / "manifest.json")
            artifacts["manifest_path"] = manifest_path
            artifacts["manifest_display_path"] = _portable_path(Path(manifest_path), output_dir)

        manifest = {
            "title": title,
            "tables": [_portable_manifest_table(table) for table in artifacts.get("tables", [])],
            "figures": [_portable_manifest_figure(figure) for figure in artifacts.get("figures", [])],
            "literature_audit_path": audit["display_path"],
        }
        Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        artifacts["section"] = self._markdown_section(
            artifacts.get("tables", []),
            artifacts.get("figures", []),
            artifacts.get("manifest_display_path") or _portable_path(Path(manifest_path), output_dir),
            literature_audit=audit["audit"],
            literature_audit_path=audit["display_path"],
        )
        return artifacts

    def build(
        self,
        *,
        title: str,
        tool_results: list[dict[str, Any]] | None,
        output_dir: Path,
    ) -> dict[str, Any]:
        if not tool_results:
            return {"tables": [], "figures": []}

        rows = _numeric_rows(tool_results)
        if not rows:
            return {"tables": [], "figures": []}

        artifact_dir = output_dir / "artifacts" / _safe_slug(title)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        columns = _ordered_columns(rows)
        csv_path = artifact_dir / "numeric_tool_results.csv"
        json_path = artifact_dir / "numeric_tool_results.json"
        manifest_path = artifact_dir / "manifest.json"

        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in columns})

        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

        figures = self._build_figures(rows, columns, artifact_dir, output_dir)
        tables = [
            {
                "id": "table_1",
                "csv_path": str(csv_path),
                "json_path": str(json_path),
                "csv_display_path": _portable_path(csv_path, output_dir),
                "json_display_path": _portable_path(json_path, output_dir),
                "row_count": len(rows),
                "columns": columns,
                "caption": "Machine-readable numeric values extracted from evidence-grade tool output.",
            }
        ]

        manifest = {
            "title": title,
            "tables": [_portable_manifest_table(table) for table in tables],
            "figures": [_portable_manifest_figure(figure) for figure in figures],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "tables": tables,
            "figures": figures,
            "manifest_path": str(manifest_path),
            "manifest_display_path": _portable_path(manifest_path, output_dir),
            "section": self._markdown_section(tables, figures, _portable_path(manifest_path, output_dir)),
        }

    async def _build_literature_audit(
        self,
        *,
        title: str,
        output_dir: Path,
        literature_search: Any | None,
    ) -> dict[str, Any]:
        artifact_dir = output_dir / "artifacts" / _safe_slug(title)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        audit_path = artifact_dir / "literature_novelty_audit.json"

        search = literature_search or _default_literature_search
        try:
            result = search(title, max_results=8)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            result = {
                "papers": [],
                "sources_succeeded": [],
                "support_score": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            }

        papers = result.get("papers", []) if isinstance(result, dict) else []
        normalized_papers = [_normalize_paper(paper) for paper in papers[:8]]
        verdict = _literature_verdict(title, normalized_papers)
        audit = {
            "query": title,
            "verdict": verdict,
            "interpretation": _verdict_interpretation(verdict),
            "support_score": result.get("support_score", 0.0) if isinstance(result, dict) else 0.0,
            "sources_succeeded": result.get("sources_succeeded", []) if isinstance(result, dict) else [],
            "papers": normalized_papers,
        }
        if isinstance(result, dict) and result.get("error"):
            audit["search_error"] = result["error"]

        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return {"path": str(audit_path), "display_path": _portable_path(audit_path, output_dir), "audit": audit}

    def _build_figures(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        artifact_dir: Path,
        output_dir: Path,
    ) -> list[dict[str, Any]]:
        numeric_columns = [
            col for col in columns
            if col not in {"tool"} and all(isinstance(row.get(col), (int, float)) for row in rows if col in row)
        ]
        if len(numeric_columns) < 2:
            return []

        x_col = next((col for col in ("delta", "n", "time", "parameter") if col in numeric_columns), numeric_columns[0])
        is_ssh_finite_chain = {
            "terminal_gap_n100",
            "peierls_bulk_gap_estimate",
            "edge_state_onset_n",
        }.issubset(set(columns))
        is_dna_base_composition = {"A", "T", "G", "C"}.issubset(set(columns))
        y_cols = []
        for col in numeric_columns:
            if col == x_col or col in _PLOT_METADATA_COLUMNS:
                continue
            values = [row[col] for row in rows if col in row]
            if len(values) < 2:
                continue
            if len({round(float(value), 12) for value in values}) < 2:
                continue
            y_cols.append(col)
        if is_ssh_finite_chain:
            priority = [
                "terminal_gap_n100",
                "peierls_bulk_gap_estimate",
                "edge_state_onset_n",
                "max_edge_weight",
                "left_edge_weight",
                "right_edge_weight",
            ]
            prioritized = [col for col in priority if col in y_cols]
            y_cols = prioritized or y_cols
        if not is_dna_base_composition:
            y_cols = y_cols[:3]
        if not y_cols and not is_dna_base_composition:
            return []

        try:
            import matplotlib

            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt
        except Exception:
            return []

        x_values = [row[x_col] for row in rows if x_col in row]
        if not x_values:
            return []

        if is_dna_base_composition:
            base_rows = [
                row for row in rows
                if all(isinstance(row.get(base), (int, float)) for base in ("A", "T", "G", "C"))
            ]
            if not base_rows:
                return []

            fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=160)
            labels = [f"{row.get('tool', 'sequence')} #{idx + 1}" for idx, row in enumerate(base_rows)]
            bottom = [0.0 for _ in base_rows]
            colors = {"A": "#4c78a8", "T": "#f58518", "G": "#54a24b", "C": "#b279a2"}
            for base in ("A", "T", "G", "C"):
                values = [float(row.get(base, 0.0)) for row in base_rows]
                ax.bar(labels, values, bottom=bottom, label=base, color=colors[base])
                bottom = [prev + value for prev, value in zip(bottom, values)]
            ax.set_ylabel("base count")
            ax.set_title("DNA base composition")
            ax.grid(True, axis="y", alpha=0.25)
            ax.legend(frameon=False, ncols=4)
            ax.tick_params(axis="x", labelrotation=20)
            figure_path = artifact_dir / "figure_1_dna_base_composition.png"
            caption = (
                "Figure 1. DNA base-composition control: A/T/G/C counts are plotted "
                "directly from evidence-grade sequence analyzer output."
            )
        elif is_ssh_finite_chain and "edge_state_onset_n" in y_cols and len(y_cols) > 1:
            def _points_for(col: str) -> list[tuple[float, float]]:
                points = []
                for row in rows:
                    if x_col not in row or col not in row:
                        continue
                    try:
                        points.append((float(row[x_col]), float(row[col])))
                    except (TypeError, ValueError):
                        continue
                return sorted(points, key=lambda point: point[0])

            def _unique_x(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
                unique = {}
                for x_val, y_val in points:
                    unique.setdefault(round(x_val, 12), (x_val, y_val))
                return [unique[key] for key in sorted(unique)]

            fig, (ax_gap, ax_edge) = plt.subplots(
                2,
                1,
                figsize=(6.4, 5.2),
                dpi=160,
                sharex=True,
                gridspec_kw={"height_ratios": [2, 1]},
            )
            peierls_points = _unique_x(_points_for("peierls_bulk_gap_estimate"))
            terminal_points = _points_for("terminal_gap_n100")
            edge_points = _unique_x(_points_for("edge_state_onset_n"))
            if peierls_points:
                ax_gap.plot(
                    [x for x, _ in peierls_points],
                    [y for _, y in peierls_points],
                    marker="o",
                    linewidth=1.8,
                    label="Peierls bulk-gap estimate",
                )
            if terminal_points:
                ax_gap.scatter(
                    [x for x, _ in terminal_points],
                    [y for _, y in terminal_points],
                    s=36,
                    alpha=0.78,
                    color="#1f77b4",
                    label="terminal gap n=100 by boundary orientation",
                )
            if edge_points:
                ax_edge.plot(
                    [x for x, _ in edge_points],
                    [y for _, y in edge_points],
                    marker="s",
                    linewidth=1.6,
                    color="#7f3c8d",
                    label="edge-state onset n",
                )
            ax_gap.set_ylabel("gap estimate")
            ax_gap.set_title("SSH finite-chain gap and edge-state diagnostics")
            ax_gap.grid(True, alpha=0.25)
            ax_gap.legend(frameon=False)
            ax_edge.set_xlabel(x_col.replace("_", " "))
            ax_edge.set_ylabel("onset n")
            ax_edge.grid(True, alpha=0.25)
            ax_edge.legend(frameon=False)
            figure_path = artifact_dir / "figure_1_ssh_finite_chain_diagnostic.png"
            caption = (
                "Figure 1. SSH finite-chain diagnostic sweep: Peierls bulk-gap estimates, "
                f"terminal gap values, and edge-state onset are plotted versus `{x_col}` "
                "from evidence-grade tool output."
            )
        else:
            fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=160)
            for y_col in y_cols:
                y_values = [row[y_col] for row in rows if x_col in row and y_col in row]
                x_for_y = [row[x_col] for row in rows if x_col in row and y_col in row]
                if len(x_for_y) == len(y_values) and y_values:
                    ax.plot(x_for_y, y_values, marker="o", linewidth=1.6, label=y_col.replace("_", " "))

            ax.set_xlabel(x_col.replace("_", " "))
            ax.set_ylabel("observed value")
            ax.set_title("Numeric tool sweep")
            ax.grid(True, alpha=0.25)
            ax.legend(frameon=False)
            figure_path = artifact_dir / "figure_1_numeric_sweep.png"
            caption = (
                "Figure 1. Numeric sweep extracted directly from tool output; "
                f"x-axis is `{x_col}` and plotted observables are {', '.join(y_cols)}."
            )

        fig.tight_layout()
        fig.savefig(figure_path, dpi=220, bbox_inches="tight")
        plt.close(fig)

        return [
            {
                "id": "figure_1",
                "path": str(figure_path),
                "display_path": _portable_path(figure_path, output_dir),
                "caption": caption,
            }
        ]

    @staticmethod
    def _markdown_section(
        tables: list[dict[str, Any]],
        figures: list[dict[str, Any]],
        manifest_path: str,
        literature_audit: dict[str, Any] | None = None,
        literature_audit_path: str | None = None,
    ) -> dict[str, str]:
        lines = [
            "The paper pipeline generated machine-readable publication artifacts from the raw tool outputs.",
            "",
            f"Artifact manifest: `{manifest_path}`",
            "",
        ]
        for idx, table in enumerate(tables, 1):
            csv_ref = table.get("csv_display_path") or table["csv_path"]
            json_ref = table.get("json_display_path") or table["json_path"]
            lines.append(
                f"Table {idx}. {table['caption']} CSV: `{csv_ref}`; JSON: `{json_ref}`."
            )
        if tables:
            lines.append("")
        for idx, figure in enumerate(figures, 1):
            figure_ref = figure.get("display_path") or figure["path"]
            lines.append(f"![Figure {idx}: {figure['caption']}]({figure_ref})")
            lines.append("")
            lines.append(figure["caption"])
            lines.append("")
        if literature_audit and literature_audit_path:
            lines.append(f"Literature novelty audit: `{literature_audit_path}`")
            lines.append("")
            lines.append(
                "Audit verdict: "
                f"`{literature_audit['verdict']}` — {literature_audit['interpretation']}"
            )
            papers = literature_audit.get("papers", [])
            if papers:
                lines.append("")
                lines.append("Closest literature signals:")
                for paper in papers[:3]:
                    year = paper.get("year") or "n.d."
                    source = paper.get("source") or "unknown source"
                    lines.append(f"- {paper.get('title', 'Untitled')} ({year}, {source})")
        return {
            "heading": "Publication Artifacts",
            "content": "\n".join(lines).strip(),
        }


async def _default_literature_search(query: str, max_results: int = 8) -> dict[str, Any]:
    from core.literature_search import search_literature_async

    return await search_literature_async(query, max_results=max_results)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4 and token not in _STOPWORDS
    }


def _normalize_paper(paper: Any) -> dict[str, Any]:
    if not isinstance(paper, dict):
        return {"title": str(paper), "year": None, "doi": "", "url": "", "source": ""}
    return {
        "title": str(paper.get("title", "")),
        "year": paper.get("year"),
        "doi": str(paper.get("doi", "")),
        "url": str(paper.get("url", "")),
        "source": str(paper.get("source", "")),
        "citations": paper.get("citations"),
    }


def _literature_verdict(query: str, papers: list[dict[str, Any]]) -> str:
    if not papers:
        return "no_direct_match_found"

    query_tokens = _tokens(query)
    if not query_tokens:
        return "related_literature_found"

    best_overlap = 0.0
    best_shared = 0
    for paper in papers:
        paper_tokens = _tokens(paper.get("title", ""))
        shared = query_tokens & paper_tokens
        overlap = len(shared) / max(len(query_tokens), 1)
        if overlap > best_overlap:
            best_overlap = overlap
            best_shared = len(shared)

    if best_overlap >= 0.35 and best_shared >= 2:
        return "needs_manual_review"
    return "related_literature_found"


def _verdict_interpretation(verdict: str) -> str:
    if verdict == "needs_manual_review":
        return "nearby published work was found; do not claim novelty without a human literature review."
    if verdict == "related_literature_found":
        return "related work exists, but title overlap did not indicate a direct match."
    return "the open literature search returned no direct match; this is not proof of novelty."
