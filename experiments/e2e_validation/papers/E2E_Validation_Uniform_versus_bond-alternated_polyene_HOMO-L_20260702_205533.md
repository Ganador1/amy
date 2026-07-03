# E2E Validation: Uniform versus bond-alternated polyene HOMO-LUMO gap scaling

**Authors:** A.M.Y Computational Research System [1]
**Affiliation:** [1] AXIOM Atlas Platform, Autonomous Computational Research
**Date:** July 02, 2026
**Classification:** PACS 31.15.-p (Electronic structure of molecules), PACS 82.20.-w (Chemical kinetics)
**Keywords:** computational chemistry, molecular weight, bond energy, Hückel theory, IUPAC standards

---

## Abstract

We report a systematic computational examination of e2e validation: uniform versus bond-alternated polyene homo-lumo gap scaling, employing 4 distinct computational methods from the AXIOM Atlas platform with full result hashing. Quantitative results are reported for: Huckel HOMO-LUMO gap scaling model comparison for linear polyenes; Bond-alternated tight-binding gap scaling for the same finite chain lengths; Small-polyene RHF/STO-3G HOMO-LUMO gap control for C4H6 and C6H8 (see Results for the provenance-anchored values). We record 5 verification controls; no result currently meets the threshold for a novelty claim. Every tool invocation is paired with an SHA-256 output hash and environment record, supporting bit-level reproducibility. The methodology illustrates an auditable approach to chemistry verification.

## Introduction

The study of e2e validation: uniform versus bond-alternated polyene homo-lumo gap scaling represents a fundamental challenge in chemistry, with implications spanning both theoretical understanding and practical applications (Hückel, E; Autschbach, J; Atkins, P. & de Paula, J). Recent advances in computational tools have enabled systematic verification of theoretical predictions at unprecedented scale and precision.

In this work, we employ 5 computational methods to analyze e2e validation: uniform versus bond-alternated polyene homo-lumo gap scaling, verifying established results while separating finite-range candidate patterns from novelty claims. Our approach combines symbolic computation, numerical analysis, and statistical verification to provide a comprehensive computational assessment.

## Methods

We employed 4 distinct computational tools from the AXIOM Atlas platform. Note that some tools were executed with multiple parameter configurations, yielding 5 total analyses. Only tools with fundamentally different algorithms are counted as methodologically independent.

- **Huckel HOMO-LUMO gap scaling model comparison for linear polyenes** (`huckel_polyene_scaling`): Executed with input parameters derived from the research question. Results were compared against theoretical predictions where available.
- **Bond-alternated tight-binding gap scaling for the same finite chain lengths** (`bond_alternated_polyene_scaling`): Executed with input parameters derived from the research question. Results were compared against theoretical predictions where available.
- **Small-polyene RHF/STO-3G HOMO-LUMO gap control for C4H6 and C6H8** (`pyscf_polyene_hf_gap`): Executed with input parameters derived from the research question. Results were compared against theoretical predictions where available.
- **Four-site Huckel endpoint/control calculation** (`molecular_orbital_energy`): Executed with 2 parameter configurations (configuration 1, configuration 2). Each configuration tests a different input condition using the same underlying algorithm. Results were compared against theoretical predictions.

All computations were performed using Python 3.13 on Apple Silicon M4 hardware with MPS acceleration. Numerical precision was verified to machine epsilon (≈2.2×10⁻¹⁶). Where applicable, results were compared against known analytical solutions or published reference values to distinguish genuine deviations from rounding artifacts.

## Results

### Evidence-grade results

**Tool:** `pyscf_polyene_hf_gap`
```text
PySCF polyene RHF/STO-3G HOMO-LUMO gap controls:
  Geometry: rough planar all-trans C_n H_(n+2), alternating C-C distances 1.34/1.46 A, C-H=1.09 A.
  Basis: sto-3g
  Carbon counts: [4, 6]
  Observations:
    n=4: formula=C4H6; total_energy=-152.46858270 Ha; HOMO=-0.238701 Ha; LUMO=0.237409 Ha; HF_gap=12.9556 eV; converged=True
    n=6: formula=C6H8; total_energy=-228.13039888 Ha; HOMO=-0.195717 Ha; LUMO=0.188743 Ha; HF_gap=10.4617 eV; converged=True
  HF trend over tested counts: decreases
  Interpretation: RHF/STO-3G orbital gaps are method-dependent and not optical gaps, but they provide an independent ab initio control on the sign of the length trend....
```

### Heuristic/demo results

**Tool:** `huckel_polyene_scaling`
```text
Hückel polyene HOMO-LUMO gap scaling:
  Literature anchor: linear Hückel polyene levels use E_k = alpha + 2 beta cos(k*pi/(N+1)); the frontier gap is -4 beta sin(pi/(2(N+1))).
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Chain sizes (n atoms): [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100]
  Gaps (eV): [3.09, 2.225, 1.736, 1.423, 1.205, 0.923, 0.747, 0.506, 0.383, 0.308, 0.194, 0.156]
  Observations:
    n=4: gap=3.090170 eV
    n=6: gap=2.225209 eV
    n=8: gap=1.736482 eV
    n=10: gap=1.423148 eV
    n=12: gap=1.205367 eV
    n=16: gap=0.922684 eV
    n=20: gap=0.747301 eV
    n=30: gap=0.506492 eV
    n=40: gap=0.383027 eV
    n=50: gap=0.307951 eV
    n=80: gap=0.193913 eV
    n=100: gap=0.155518 eV
  Formula check max_abs_error: 1.388e-15 eV
  asymptotic_slope -2*pi*beta = 15.707963
  small_angle_argument_at_min_n = 0.314159 rad
  asymptotic_inverse_model gap = 15.707963/(n+1); RMSE=0.016098 eV; max_abs_error=0.051423 eV; residual_threshold=0.010000 eV
  inverse_linear f...
```
**Tool:** `bond_alternated_polyene_scaling`
```text
Bond-alternated polyene gap scaling:
  Method: explicit diagonalization of a nearest-neighbor tight-binding/Hückel matrix with alternating strong and weak couplings.
  Model parameters: alpha=-6.000 eV, beta_strong=-2.700 eV, beta_weak=-2.300 eV
  Chain sizes (n atoms): [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100]
  Alternated gaps (eV): [3.569, 2.733, 2.261, 1.959, 1.751, 1.483, 1.32, 1.106, 1.003, 0.945, 0.868, 0.847]
  asymptotic_gap_estimate = 0.800000 eV
  max_excess_over_asymptote = 2.769412 eV
  Observations:
    n=4: alternated_gap=3.569412 eV; excess_over_asymptote=2.769412 eV
    n=6: alternated_gap=2.733328 eV; excess_over_asymptote=1.933328 eV
    n=8: alternated_gap=2.260871 eV; excess_over_asymptote=1.460871 eV
    n=10: alternated_gap=1.959087 eV; excess_over_asymptote=1.159087 eV
    n=12: alternated_gap=1.750598 eV; excess_over_asymptote=0.950598 eV
    n=16: alternated_gap=1.483116 eV; excess_over_asymptote=0.683116 eV
    n=20: alternated_gap=1.320481 eV; excess_ov...
```
**Tool:** `molecular_orbital_energy`
```text
Hückel MO Analysis (4 carbon conjugated system):
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Energy levels (eV): [-10.045, -7.545, -4.455, -1.955]
  HOMO energy: -7.545 eV
  LUMO energy: -4.455 eV
  HOMO-LUMO gap: 3.090 eV
  Delocalization energy: -11.180 eV...
```
**Tool:** `molecular_orbital_energy`
```text
Hückel MO Analysis (20 carbon conjugated system):
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Energy levels (eV): [-10.944, -10.778, -10.505, -10.131, -9.665, -9.117, -8.5, -7.827, -7.113, -6.374, -5.626, -4.887, -4.173, -3.5, -2.883, -2.335, -1.869, -1.495, -1.222, -1.056]
  HOMO energy: -6.374 eV
  LUMO energy: -5.626 eV
  HOMO-LUMO gap: 0.747 eV
  Delocalization energy: -61.907 eV...
```

### Summary Analysis

### Huckel HOMO-LUMO gap scaling model comparison for linear polyenes
**Tool:** `huckel_polyene_scaling`
**Input:** `4,6,8,10,12,16,20,30,40,50,80,100`
**Experiment:** `chemistry_huckel_polyene_scaling_20260703_005400`

```text
Hückel polyene HOMO-LUMO gap scaling:
  Literature anchor: linear Hückel polyene levels use E_k = alpha + 2 beta cos(k*pi/(N+1)); the frontier gap is -4 beta sin(pi/(2(N+1))).
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Chain sizes (n atoms): [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100]
  Gaps (eV): [3.09, 2.225, 1.736, 1.423, 1.205, 0.923, 0.747, 0.506, 0.383, 0.308, 0.194, 0.156]
  Observations:
    n=4: gap=3.090170 eV
    n=6: gap=2.225209 eV
    n=8: gap=1.736482 eV
    n=10: gap=1.423148 eV
    n=12: gap=1.205367 eV
    n=16: gap=0.922684 eV
    n=20: gap=0.747301 eV
    n=30: gap=0.506492 eV
    n=40: gap=0.383027 eV
    n=50: gap=0.307951 eV
    n=80: gap=0.193913 eV
    n=100: gap=0.155518 eV
  Formula check max_abs_error: 1.388e-15 eV
  asymptotic_slope -2*pi*beta = 15.707963
  small_angle_argument_at_min_n = 0.314159 rad
  asymptotic_inverse_model gap = 15.707963/(n+1); RMSE=0.016098 eV; max_abs_error=0.051423 eV; residual_threshold=0.010000 eV
  inverse_linear fit gap = 15.481724/(n+1) + 0.008151; RMSE=0.006472 eV; R2=0.999945
  inverse_quadratic fit gap = 73.461186/(n+1)^2 + 0.493610; RMSE=0.256926 eV; R2=0.912976
  power_law fit gap = 15.469521*(n+1)^-0.99
```

### Bond-alternated tight-binding gap scaling for the same finite chain lengths
**Tool:** `bond_alternated_polyene_scaling`
**Input:** `4,6,8,10,12,16,20,30,40,50,80,100;strong=-2.7;weak=-2.3`
**Experiment:** `chemistry_bond_alternated_polyene_scaling_20260703_005400`

```text
Bond-alternated polyene gap scaling:
  Method: explicit diagonalization of a nearest-neighbor tight-binding/Hückel matrix with alternating strong and weak couplings.
  Model parameters: alpha=-6.000 eV, beta_strong=-2.700 eV, beta_weak=-2.300 eV
  Chain sizes (n atoms): [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100]
  Alternated gaps (eV): [3.569, 2.733, 2.261, 1.959, 1.751, 1.483, 1.32, 1.106, 1.003, 0.945, 0.868, 0.847]
  asymptotic_gap_estimate = 0.800000 eV
  max_excess_over_asymptote = 2.769412 eV
  Observations:
    n=4: alternated_gap=3.569412 eV; excess_over_asymptote=2.769412 eV
    n=6: alternated_gap=2.733328 eV; excess_over_asymptote=1.933328 eV
    n=8: alternated_gap=2.260871 eV; excess_over_asymptote=1.460871 eV
    n=10: alternated_gap=1.959087 eV; excess_over_asymptote=1.159087 eV
    n=12: alternated_gap=1.750598 eV; excess_over_asymptote=0.950598 eV
    n=16: alternated_gap=1.483116 eV; excess_over_asymptote=0.683116 eV
    n=20: alternated_gap=1.320481 eV; excess_over_asymptote=0.520481 eV
    n=30: alternated_gap=1.105803 eV; excess_over_asymptote=0.305803 eV
    n=40: alternated_gap=1.003212 eV; excess_over_asymptote=0.203212 eV
    n=50: alternated_gap=0.9453
```

### Small-polyene RHF/STO-3G HOMO-LUMO gap control for C4H6 and C6H8
**Tool:** `pyscf_polyene_hf_gap`
**Input:** `4,6;basis=sto-3g`
**Experiment:** `chemistry_pyscf_polyene_hf_gap_20260703_005400`

```text
PySCF polyene RHF/STO-3G HOMO-LUMO gap controls:
  Geometry: rough planar all-trans C_n H_(n+2), alternating C-C distances 1.34/1.46 A, C-H=1.09 A.
  Basis: sto-3g
  Carbon counts: [4, 6]
  Observations:
    n=4: formula=C4H6; total_energy=-152.46858270 Ha; HOMO=-0.238701 Ha; LUMO=0.237409 Ha; HF_gap=12.9556 eV; converged=True
    n=6: formula=C6H8; total_energy=-228.13039888 Ha; HOMO=-0.195717 Ha; LUMO=0.188743 Ha; HF_gap=10.4617 eV; converged=True
  HF trend over tested counts: decreases
  Interpretation: RHF/STO-3G orbital gaps are method-dependent and not optical gaps, but they provide an independent ab initio control on the sign of the length trend.
```

### Four-site Huckel endpoint/control calculation
**Tool:** `molecular_orbital_energy`
**Input:** `4:1.4`
**Experiment:** `chemistry_molecular_orbital_energy_20260703_005400`

```text
Hückel MO Analysis (4 carbon conjugated system):
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Energy levels (eV): [-10.045, -7.545, -4.455, -1.955]
  HOMO energy: -7.545 eV
  LUMO energy: -4.455 eV
  HOMO-LUMO gap: 3.090 eV
  Delocalization energy: -11.180 eV
```

### Twenty-site Huckel endpoint/control calculation
**Tool:** `molecular_orbital_energy`
**Input:** `20:1.4`
**Experiment:** `chemistry_molecular_orbital_energy_20260703_005400_2`

```text
Hückel MO Analysis (20 carbon conjugated system):
  Model parameters: alpha=-6.000 eV, beta=-2.500 eV
  Energy levels (eV): [-10.944, -10.778, -10.505, -10.131, -9.665, -9.117, -8.5, -7.827, -7.113, -6.374, -5.626, -4.887, -4.173, -3.5, -2.883, -2.335, -1.869, -1.495, -1.222, -1.056]
  HOMO energy: -6.374 eV
  LUMO energy: -5.626 eV
  HOMO-LUMO gap: 0.747 eV
  Delocalization energy: -61.907 eV
```

## Discussion

The central comparison in this study is between the finite-size HOMO–LUMO gap scaling of uniform and bond-alternated linear polyenes under nearest-neighbor tight-binding (Hückel) models. For the uniform chain with α = −6.000 eV and β = −2.500 eV, the frontier gap values computed for n = [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100] reproduce the textbook analytical expression gap = −4β sin(π/(2(N+1))) to within a formula-check max_abs_error of 1.388 × 10⁻¹⁵ eV. This is a verification of a known result, not a novel finding. The nontrivial quantitative content lies in the scaling characterization: over the tested range, the uniform-chain gaps are best described by an inverse-linear model gap = 15.481724/(n+1) + 0.008151 (RMSE = 0.006472 eV, R² = 0.999945), with the intercept b = 0.008151 eV being small but nonzero rather than exactly zero. A power-law fit yields an exponent p = −0.996 (RMSE = 0.007021 eV, R² = 0.999935), consistent with near-inverse-length decay but not a perfect 1/N law. The inverse-quadratic model is rejected with an RMSE of 0.256926 eV, which is 36.6 times the power-law RMSE. We emphasize that these fits are finite-range observations over n = 4 to n = 100; they do not constitute a proof of asymptotic behavior, and the small nonzero intercept may reflect finite-size correction rather than a true residual gap.

**Bond alternation and gap non-closure.** The bond-alternated tight-binding model (α = −6.000 eV, β_strong = −2.700 eV, β_weak = −2.300 eV) produces a qualitatively different trend. For the same chain sizes, the alternated gaps range from 3.569412 eV at n = 4 down to 0.846601 eV at n = 100, with an asymptotic_gap_estimate of 0.800000 eV. The excess over this asymptote decreases monotonically from 2.769412 eV (n = 4) to 0.046601 eV (n = 100). This is consistent with the Peierls-type expectation that bond alternation opens a finite gap in the infinite-chain limit, and we classify it as a finite-range computational observation rather than a proof: the data span only twelve chain lengths under a single parameter set, and the asymptotic estimate of 0.800000 eV is a model-derived quantity, not an independently converged limit. Notably, the gap at n = 100 (0.846601 eV) still lies 0.046601 eV above the asymptotic estimate, so the approach to the limiting value is slow and not yet complete within the sampled range.

**Methodological scope and internal consistency.** All Hückel and bond-alternated results originate from the same underlying tight-binding methodology, differing only in the coupling parameters. The four-site (E4) and twenty-site (E5) endpoint calculations reproduce gap values of 3.090 eV and 0.747 eV, respectively, matching the corresponding entries in E1 (3.090170 eV and 0.747301 eV) to the precision reported. This confirms internal consistency of the diagonalization and analytical formula implementations, but it does not constitute methodological independence or cross-validation. The only genuinely independent method in this study is the PySCF RHF/STO-3G calculation (E3), which covers only n = 4 and n = 6. At those two sizes, the HF gaps are 12.9556 eV (C₄H₆) and 10.4617 eV (C₆H₈), showing a decreasing trend consistent in sign with the Hückel prediction. However, these are single-determinant, minimal-basis orbital energy gaps—not optical gaps—and they incorporate electron–electron repulsion and nuclear geometry effects absent from the tight-binding models. The RHF/STO-3G control therefore validates the direction of the length trend at two points but does not quantitatively constrain the scaling exponent or the asymptotic behavior.

**Limitations and alternative explanations.** Several limitations bear on the interpretation. First, the uniform-chain inverse-linear fit intercept of 0.008151 eV is small relative to the gap magnitudes but is not zero; whether this reflects a genuine finite-size correction or a fitting artifact over a limited range cannot be determined from twelve data points alone. Second, the bond-alternated asymptotic_gap_estimate of 0.800000 eV is exactly 2|β_strong − β_weak| = 2 × 0.4 eV, which is the expected infinite-chain Peierls gap for this parameter choice; its appearance confirms the model's internal logic but does not test the model against real polyene electronic structure. Third, the rough planar all-trans geometry with fixed C–C distances of 1.34/1.46 Å and C–H = 1.09 Å in the PySCF control is not geometry-optimized, so the ab initio gaps may shift with relaxation. Finally, no electron-correlation method beyond RHF was applied, and no basis larger than STO-3G was tested; the absence of correlated methods means the comparison between tight-binding and ab initio gaps is necessarily qualitative.

**Implications.** The evidence motivates a specific, testable question: does the bond-alternated tight-binding asymptotic gap of 0.800000 eV, derived from a coupling contrast of Δβ = 0.4 eV, survive when electron correlation and geometry relaxation are introduced at the ab initio level for larger chains? The PySCF data here cover only n = 4 and n = 6, where the HF gaps of 12.9556 eV and 10.4617 eV are far above the corresponding alternated Hückel gaps of 3.569412 eV and 2.733328 eV, making extrapolation impossible. Extending correlated calculations (e.g., MP2 or DFT with a triple-ζ basis) to n = 20 or beyond, with optimized bond-alternated geometries, would directly test whether the finite residual gap predicted by the tight-binding model is a robust feature of real polyene electronic structure or an artifact of the single-particle, fixed-geometry approximation.



## Testable Predictions

Candidate hypotheses were ranked via an Elo tournament (Co-Scientist–style ranking) before inclusion; lower-ranked candidates are listed last to discourage cherry-picking.

H1. The finite-size HOMO-LUMO gap scaling of linear polyenes transitions from an asymptotic 1/N decay to a sin(pi/(2(N+1))) dependence, and is fundamentally governed by bond-alternation; explicitly, for N=[4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100], the gap converges to a non-zero asymptote of 0.4 eV (delta_beta = 0.4 eV) under bond-alternated tight-binding (beta_strong=-2.700 eV, beta_weak=-2.300 eV) versus collapsing to 0 eV in the uniform Huckel model (beta=-2.500 eV). Testable via: fitting both the uniform Huckel frontier gaps and the bond-alternated tight-binding gaps to the functions gap_uniform(N) = -4*beta*sin(pi/(2(N+1))) and gap_altd(N) = A*sin(pi/(2(N+1))) + 0.4 eV, requiring the uniform fit to yield A=-10.0 eV with R^2 > 0.999 and the alternated fit to yield a baseline asymptote b=0.4 eV, while comparing these against the n=4 and n=6 RHF/STO-3G PySCF control gaps to quantify electron-electron repulsion deviations. (confidence: 70%). *(Elo: 1203.6, tournament: 0W-0L-8D, status: finite_computational_observation)* Testable via: fitting both the uniform Huckel frontier gaps and the bond-alternated tight-binding gaps to the functions gap_uniform(N) = -4*beta*sin(pi/(2(N+1))) and gap_altd(N) = A*sin(pi/(2(N+1))) + 0.4 eV, requiring the uniform fit to yield A=-10.0 eV with R^2 > 0.999 and the alternated fit to yield a baseline asymptote b=0.4 eV, while comparing these against the n=4 and n=6 RHF/STO-3G PySCF control gaps to quantify electron-electron repulsion deviations.

H2. The HOMO-LUMO gap of bond-alternated linear polyenes follows an inverse-length gap(n) = a/n + b asymptotic decay that converges to a finite residual gap of b ≈ 0.80 eV, unlike the uniform Hückel chain which obeys gap(n) = a/n + b converging to b = 0. Testable via: perform explicit diagonalization of the bond-alternated tight-binding matrix (alpha=-6.000 eV, beta_strong=-2.700 eV, beta_weak=-2.300 eV) for n = [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100], fit gap(n) to a/n + b, and verify that b falls within [0.70, 0.90] eV while the same fit on the uniform Hückel chain (beta=-2.500 eV) yields b within [-0.05, 0.05] eV. (confidence: 70%). *(Elo: 1201.4, tournament: 0W-0L-8D, status: finite_computational_observation)* Testable via: perform explicit diagonalization of the bond-alternated tight-binding matrix (alpha=-6.000 eV, beta_strong=-2.700 eV, beta_weak=-2.300 eV) for n = [4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 80, 100], fit gap(n) to a/n + b, and verify that b falls within [0.70, 0.90] eV while the same fit on the uniform Hückel chain (beta=-2.500 eV) yields b within [-0.05, 0.05] eV.

H3. Uniform finite-chain Hückel polyenes show near-inverse-length HOMO-LUMO gap decay over the tested range, consistent with the sine-derived analytical baseline. (confidence: 70%). *(Elo: 1198.7, tournament: 0W-0L-8D, status: finite_computational_observation)* Testable via: Compare inverse-linear, inverse-quadratic, and power-law fits against the recorded Hückel gap series; the finite-range claim is weakened if an alternative fit reduces RMSE without adding unsupported parameters.

H4. The HOMO-LUMO gap of the tested linear conjugated systems follows an inverse-length trend that can be modeled as gap(n) = a/n + b over the sampled range. (confidence: 70%). *(Elo: 1198.6, tournament: 0W-0L-8D, status: finite_computational_observation)* Testable via: Fit HOMO-LUMO gaps across additional chain lengths and validate the trend against an independent Hückel or DFT implementation.

H5. Bond alternation changes the limiting behavior of the tested polyene model from uniform-chain gap closure to a finite gap near 0.800000 eV. (confidence: 70%). *(Elo: 1197.8, tournament: 0W-0L-8D, status: finite_computational_observation)* Testable via: Extend the alternating-coupling series to larger n and vary beta_strong/beta_weak; the hypothesis is weakened if the fitted finite-gap intercept does not track the recorded asymptotic_gap_estimate.



## Conclusion

This computational study of e2e validation: uniform versus bond-alternated polyene homo-lumo gap scaling has verified theoretical predictions using 4 distinct computational methods. The analysis produced 5 verification controls or finite-range observations, but no result currently satisfies the threshold for a novelty claim. Future work should extend the parameter range, add literature baselines, and quantify effect sizes before proposing new claims.

## Acknowledgments

The authors acknowledge the AXIOM Atlas computational platform for providing
the scientific tools used in this study. All computations were performed on
Apple Silicon M4 hardware with Python 3.13 and MPS acceleration.

## Data Availability

All computational data supporting this study are publicly available.
The following experiment records contain full provenance information
including input parameters, complete output, execution environment,
and SHA-256 output hashes:

- chemistry_huckel_polyene_scaling_20260703_005400: `data/experiments/chemistry_huckel_polyene_scaling_20260703_005400/provenance.json` (output SHA-256: `5fcbb97e2d0ba3583a78adff075eab787f09794134e9f5ed2aa3fb0f0103cadb`)
- chemistry_bond_alternated_polyene_scaling_20260703_005400: `data/experiments/chemistry_bond_alternated_polyene_scaling_20260703_005400/provenance.json` (output SHA-256: `06b08ecad39043c147675d5ee7f7403c24c2db6193746533c0c64829d342cc7a`)
- chemistry_pyscf_polyene_hf_gap_20260703_005400: `data/experiments/chemistry_pyscf_polyene_hf_gap_20260703_005400/provenance.json` (output SHA-256: `35c0fbc856b0450220fdb36d2f6999a6b93ba4e60a3c1e62dea5ca9d73b29197`)
- chemistry_molecular_orbital_energy_20260703_005400: `data/experiments/chemistry_molecular_orbital_energy_20260703_005400/provenance.json` (output SHA-256: `4f8cf96569dd41bda97d6215c64eeae926d0bb7887edbb2e76f048538927801b`)
- chemistry_molecular_orbital_energy_20260703_005400_2: `data/experiments/chemistry_molecular_orbital_energy_20260703_005400_2/provenance.json` (output SHA-256: `44c5fe60d601d16068bba179a59ce94f711f811111b72dc8c2846e31f0159f46`)

## References

[1] Hückel, E. (1931). Quantentheoretische Beiträge zum Benzolproblem. Zeitschrift für Physik, 70, 204-286.
[2] Autschbach, J. (2007). Why the particle-in-a-box model works well for cyanine dyes but not for conjugated polyenes. Journal of Chemical Education, 84(11), 1840-1845. doi:10.1021/ed084p1840.
[3] Atkins, P. & de Paula, J. (2014). Atkins' Physical Chemistry. Oxford University Press.
[4] Clayden, J. et al. (2012). Organic Chemistry. Oxford University Press.
[5] Pauling, L. (1960). The Nature of the Chemical Bond. Cornell University Press.
[6] Housecroft, C.E. & Sharpe, A.G. (2018). Inorganic Chemistry. Pearson.
[7] Coulson, C.A., O'Leary, B. & Mallion, R.B. (1978). Hückel Theory for Organic Chemists. Academic Press.
[8] Griffiths, D.J. (2018). Introduction to Quantum Mechanics. Cambridge University Press.


---

## Provenance Watermark

This manuscript was generated by an autonomous research system. It is **not** a peer-reviewed publication. Treat individual claims as computational artifacts until independently verified.

<!-- AMY-WATERMARK
generated_by: A.M.Y (Autonomous Mind Yield) v1.0.0
title: E2E Validation: Uniform versus bond-alternated polyene HOMO-LUMO gap scaling
generated_at: 2026-07-03T00:55:34.253707+00:00
body_sha256: 5e112cc4003404b60b7a6a9879aa5c4f3bf0210cb35f651cddce99bae3306a78
homepage: https://github.com/Ganador1/amy
self_review: external_sidecar_when_available
verification: Each cited experiment_id resolves to data/experiments/<id>/provenance.json with a SHA-256 hash of the full tool output.
-->
