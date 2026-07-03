from pathlib import Path

from cognition.reflection_agent import reflect
from communication.grounding_repair import repair_unsupported_decimal_claims


def _write_provenance(base: Path, experiment_id: str, output: str) -> None:
    exp_dir = base / experiment_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "provenance.json").write_text(
        '{"output_preview": ' + repr(output).replace("'", '"') + "}",
        encoding="utf-8",
    )
    (exp_dir / "output.txt").write_text(output, encoding="utf-8")


def test_grounding_repair_removes_only_unsupported_discussion_decimals(tmp_path):
    eid = "mathematics_prime_gap_analysis_20260702_010203"
    _write_provenance(tmp_path, eid, "Mean gap: 1.2345\nMax gap: 8.0000")
    md = f"""# Paper

## Abstract

This paper reports a grounded value of 1.234 and an unsupported value of 9.99.

## Discussion

The grounded mean is 1.234, but the invented comparison is 9.99.

## Data Availability

- {eid}: `data/experiments/{eid}/provenance.json`
"""

    repaired, report = repair_unsupported_decimal_claims(
        md,
        experiment_ids=[eid],
        experiments_dir=tmp_path,
    )

    assert "1.234" in repaired
    assert "9.99" not in repaired
    assert report["repairs"] == 2
    assert {item["section"] for item in report["items"]} == {"Abstract", "Discussion"}
    reflection = reflect(repaired, experiments_dir=tmp_path)
    assert not any("numerical claims" in issue["message"] for issue in reflection.issues)


def test_grounding_repair_keeps_unsupported_decimal_replacements_readable(tmp_path):
    eid = "chemistry_molecular_orbital_energy_20260702_010203"
    _write_provenance(tmp_path, eid, "HOMO-LUMO gap: 3.090 eV")
    md = f"""# Paper

## Discussion

The Hückel beta parameter is conventionally fixed near −2.5to −3.0 eV.

## Data Availability

- {eid}: `data/experiments/{eid}/provenance.json`
"""

    repaired, report = repair_unsupported_decimal_claims(
        md,
        experiment_ids=[eid],
        experiments_dir=tmp_path,
    )

    assert "−a provenance" not in repaired
    assert "numeric valueto" not in repaired
    assert "near a provenance-unverified numeric value to a provenance-unverified numeric value eV" in repaired
    assert report["repairs"] == 2
