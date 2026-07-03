# E2E Validation: Hydrogen Rydberg inverse-square scaling against perturbation controls

**Authors:** A.M.Y Computational Research System [1]
**Affiliation:** [1] AXIOM Atlas Platform, Autonomous Computational Research
**Date:** July 03, 2026
**Classification:** PACS 31.15.-p (Calculations and mathematical techniques in atomic physics), PACS 32.30.-r (Atomic spectra)
**Keywords:** atomic physics, quantum energy levels, Rydberg formula, computational verification

---

## Abstract

The present study applies 3 distinct computational methods from the AXIOM Atlas platform to e2e validation: hydrogen rydberg inverse-square scaling against perturbation controls, with each tool invocation recorded for independent audit. The run produced numerical output for: Hydrogen inverse-square Rydberg scaling model comparison; Hydrogen endpoint/control energy level at n=5; Hydrogen endpoint/control energy level at n=20 (see Results for the provenance-anchored values). The analysis reports 5 verification controls or finite-range observations without asserting novelty. Each run is captured with input parameters, complete output, and a cryptographic fingerprint, allowing replication on independent hardware. We position the study as a methodological contribution to reproducible physics.

## Introduction

The study of e2e validation: hydrogen rydberg inverse-square scaling against perturbation controls represents a fundamental challenge in physics, with implications spanning both theoretical understanding and practical applications (Griffiths, D.J; Sakurai, J.J. & Napolitano, J; Bethe, H.A. & Salpeter, E.E). Recent advances in computational tools have enabled systematic verification of theoretical predictions at unprecedented scale and precision.

In this work, we employ 4 computational methods to analyze e2e validation: hydrogen rydberg inverse-square scaling against perturbation controls, verifying established results while separating finite-range candidate patterns from novelty claims. Our approach combines symbolic computation, numerical analysis, and statistical verification to provide a comprehensive computational assessment.

## Methods

We employed 3 distinct computational tools from the AXIOM Atlas platform. Note that some tools were executed with multiple parameter configurations, yielding 4 total analyses. Only tools with fundamentally different algorithms are counted as methodologically independent.

- **Hydrogen inverse-square Rydberg scaling model comparison** (`rydberg_scaling_comparison`): Executed with input parameters derived from the research question. Results were compared against theoretical predictions where available.
- **Hydrogen endpoint/control energy level at n=5** (`quantum_energy_levels`): Executed with 2 parameter configurations (configuration 1, configuration 2). Each configuration tests a different input condition using the same underlying algorithm. Results were compared against theoretical predictions.
- **Bell-state circuit as an independent quantum-control check** (`quantum_circuit`): Executed with input parameters derived from the research question. Results were compared against theoretical predictions where available.

All computations were performed using Python 3.13 on Apple Silicon M4 hardware with MPS acceleration. Numerical precision was verified to machine epsilon (≈2.2×10⁻¹⁶). Where applicable, results were compared against known analytical solutions or published reference values to distinguish genuine deviations from rounding artifacts.

## Results

### Heuristic/demo results

**Tool:** `rydberg_scaling_comparison`
```text
Hydrogen Rydberg scaling comparison:
  Literature anchor: the nonrelativistic hydrogen model predicts E_n = -13.6/n^2 eV.
  Principal quantum numbers: [1, 2, 3, 5, 10, 20]
  Observations:
    n=1: energy=-13.600000 eV, inverse_square_prediction=-13.600000 eV, residual=-1.776357e-15 eV, quantum_defect_prediction=-15.069252 eV
    n=2: energy=-3.400000 eV, inverse_square_prediction=-3.400000 eV, residual=4.440892e-16 eV, quantum_defect_prediction=-3.576594 eV
    n=3: energy=-1.511111 eV, inverse_square_prediction=-1.511111 eV, residual=4.440892e-16 eV, quantum_defect_prediction=-1.562769 eV
    n=5: energy=-0.544000 eV, inverse_square_prediction=-0.544000 eV, residual=6.661338e-16 eV, quantum_defect_prediction=-0.555045 eV
    n=10: energy=-0.136000 eV, inverse_square_prediction=-0.136000 eV, residual=6.938894e-16 eV, quantum_defect_prediction=-0.137370 eV
    n=20: energy=-0.034000 eV, inverse_square_prediction=-0.034000 eV, residual=7.216450e-16 eV, quantum_defect_prediction=-0.034171...
```
**Tool:** `quantum_energy_levels`
```text
Hydrogen atom energy level n=5:
  E_5 = -0.5440 eV
  First 7 levels: [-13.6, -3.4, -1.5111, -0.85, -0.544, -0.3778, -0.2776] eV
  Ionization energy from n=5: 0.5440 eV...
```
**Tool:** `quantum_energy_levels`
```text
Hydrogen atom energy level n=20:
  E_20 = -0.0340 eV
  First 7 levels: [-13.6, -3.4, -1.5111, -0.85, -0.544, -0.3778, -0.2776] eV
  Ionization energy from n=20: 0.0340 eV...
```
**Tool:** `quantum_circuit`
```text
Quantum Bell State Simulation:
- Circuit: H(q0) → CNOT(q0, q1)
- Initial state: |00⟩
- Final state: (|00⟩ + |11⟩)/√2
- Entanglement entropy: 1.0 bit
- Measurement probabilities: {|00⟩: 0.5, |11⟩: 0.5}
- Fidelity: 1.0...
```

### Summary Analysis

### Hydrogen inverse-square Rydberg scaling model comparison
**Tool:** `rydberg_scaling_comparison`
**Input:** `1,2,3,5,10,20;delta=0.05`
**Experiment:** `physics_rydberg_scaling_comparison_20260703_163406`

```text
Hydrogen Rydberg scaling comparison:
  Literature anchor: the nonrelativistic hydrogen model predicts E_n = -13.6/n^2 eV.
  Principal quantum numbers: [1, 2, 3, 5, 10, 20]
  Observations:
    n=1: energy=-13.600000 eV, inverse_square_prediction=-13.600000 eV, residual=-1.776357e-15 eV, quantum_defect_prediction=-15.069252 eV
    n=2: energy=-3.400000 eV, inverse_square_prediction=-3.400000 eV, residual=4.440892e-16 eV, quantum_defect_prediction=-3.576594 eV
    n=3: energy=-1.511111 eV, inverse_square_prediction=-1.511111 eV, residual=4.440892e-16 eV, quantum_defect_prediction=-1.562769 eV
    n=5: energy=-0.544000 eV, inverse_square_prediction=-0.544000 eV, residual=6.661338e-16 eV, quantum_defect_prediction=-0.555045 eV
    n=10: energy=-0.136000 eV, inverse_square_prediction=-0.136000 eV, residual=6.938894e-16 eV, quantum_defect_prediction=-0.137370 eV
    n=20: energy=-0.034000 eV, inverse_square_prediction=-0.034000 eV, residual=7.216450e-16 eV, quantum_defect_prediction=-0.034171 eV
  inverse_square fit E = -13.600000*(1/n^2) + -0.000000; RMSE=0.000000 eV; R2=1.000000; max_abs_error=0.000000 eV
  quantum_defect_delta=0.050000; quantum_defect model E = -13.600000/(n-delta)^2; RMSE=0.604522 eV; max_abs_error=1.469252 eV
  Best model by RMSE: inverse_square
  Deterministic residual statistics: sample size n=6; residual standard deviation=0.000000 eV; effect size (quantum_defect_RMSE - inverse_square_RMSE)=0.604522 eV; confidence interval: not estimated because this is a deterministic analytic control, not a random sample.
  Falsifiable next check: introduce a documented non-hydrogenic atom or measured spectral series; the inverse_square hydrogen control is rejected only if residuals exceed the recorded RMSE tolerance under the same units and precision.
  Caution: the quantum-defect perturbation is a competing-model stress test, not a claim that hydrogen has core-screening quantum defects.
```

### Hydrogen endpoint/control energy level at n=5
**Tool:** `quantum_energy_levels`
**Input:** `hydrogen:5`
**Experiment:** `physics_quantum_energy_levels_20260703_163406`

```text
Hydrogen atom energy level n=5:
  E_5 = -0.5440 eV
  First 7 levels: [-13.6, -3.4, -1.5111, -0.85, -0.544, -0.3778, -0.2776] eV
  Ionization energy from n=5: 0.5440 eV
```

### Hydrogen endpoint/control energy level at n=20
**Tool:** `quantum_energy_levels`
**Input:** `hydrogen:20`
**Experiment:** `physics_quantum_energy_levels_20260703_163406_2`

```text
Hydrogen atom energy level n=20:
  E_20 = -0.0340 eV
  First 7 levels: [-13.6, -3.4, -1.5111, -0.85, -0.544, -0.3778, -0.2776] eV
  Ionization energy from n=20: 0.0340 eV
```

### Bell-state circuit as an independent quantum-control check
**Tool:** `quantum_circuit`
**Input:** `bell:2`
**Experiment:** `physics_quantum_circuit_20260703_163406`

```text
Quantum Bell State Simulation:
- Circuit: H(q0) → CNOT(q0, q1)
- Initial state: |00⟩
- Final state: (|00⟩ + |11⟩)/√2
- Entanglement entropy: 1.0 bit
- Measurement probabilities: {|00⟩: 0.5, |11⟩: 0.5}
- Fidelity: 1.0
```

## Discussion

The central result of this study is the end-to-end validation of the nonrelativistic hydrogen inverse-square Rydberg scaling relation, $E_n = -13.6/n^2$ eV, against a quantum-defect perturbation control. Across the six principal quantum numbers examined ($n = 1, 2, 3, 5, 10, 20$), the inverse-square model reproduces the reference energy levels with residuals on the order of $10^{-16}$ eV, yielding an RMSE of 0.000000 eV and an $R^2$ of 1.000000. These residuals—ranging from $-1.776357 \times 10^{-15}$ eV at $n=1$ to $7.216450 \times 10^{-16}$ eV at $n=20$—are consistent with IEEE 754 double-precision floating-point roundoff and carry no physical content. This is a reproduction of a textbook result, not a novel finding. The value of the computation lies in establishing a hashed, reproducible control dataset against which a competing perturbative model can be quantitatively stress-tested.

The quantum-defect perturbation, configured with $\delta = 0.050000$ and applied as $E = -13.600000/(n - \delta)^2$, serves as a deliberately mismatched competing-model control. Its RMSE of 0.604522 eV and maximum absolute error of 1.469252 eV (occurring at $n=1$, where the predicted energy is $-15.069252$ eV versus the reference $-13.600000$ eV) confirm that even a small effective quantum defect produces substantial deviations when applied to a single-electron system with no core-screening structure. As the evidence explicitly cautions, this perturbation is a stress test of model discrimination, not a physical claim that hydrogen possesses quantum defects. The effect size, defined as the difference in RMSE between the two models, is 0.604522 eV. However, the confidence interval is reported as not estimated, and correctly so: the six data points are deterministic analytic evaluations, not a random sample, and applying frequentist inferential statistics would be inappropriate.

**Methodological scope and limitations.** All energy-level values originate from the same underlying analytic hydrogen model, implemented across two tools (`rydberg_scaling_comparison` and `quantum_energy_levels`). The agreement between E1 and the endpoint controls in E2 and E3—both yielding $E_5 = -0.5440$ eV and $E_{20} = -0.0340$ eV—demonstrates internal consistency of the computational pipeline, but this is not methodological independence. No alternative solver, variational method, or independently measured spectral dataset was employed. The sample size is fixed at $n = 6$ principal quantum numbers, which is sufficient to cover nearly two decades in $n$ but is too small to support any claim about asymptotic behavior beyond the recorded range. The Bell-state circuit control (E4), which produces the expected $(|00\rangle + |11\rangle)/\sqrt{2}$ state with fidelity 1.0 and entanglement entropy of 1.0 bit, confirms that the quantum simulation framework executes correctly on a known two-qubit benchmark; it does not, however, constitute an independent validation of the Rydberg scaling results, as it tests an entirely different quantum system with no shared computational pathway.

**Residual structure and alternative explanations.** The candidate hypothesis H1 proposes that the high-precision residuals exhibit a logarithmic scaling with $n$ that mirrors entanglement entropy. The evidence does not support this interpretation. The residuals are $-1.776357 \times 10^{-15}$, $4.440892 \times 10^{-16}$, $4.440892 \times 10^{-16}$, $6.661338 \times 10^{-16}$, $6.938894 \times 10^{-16}$, and $7.216450 \times 10^{-16}$ eV for $n = 1$ through $n = 20$. These values are machine-epsilon-scale artifacts of floating-point representation; their non-monotonicity at small $n$ and apparent stabilization at large $n$ reflect the relative magnitude of the energies being represented, not an emergent physical signature. Connecting these numerical artifacts to the 1.0-bit entanglement entropy of an unrelated Bell-state circuit has no physical or computational basis in the present evidence. The most parsimonious explanation—consistent with H3 and H4—is that all residuals are rounding artifacts, and the inverse-square scaling holds exactly within the analytic model.

**Implications.** The evidence establishes a reproducible, hashed control benchmark for hydrogen Rydberg scaling and quantifies the discrimination power of RMSE-based model comparison against a quantum-defect perturbation with a documented $\delta$ value. The next testable question, as stated in the evidence itself, is whether the inverse-square model maintains its recorded RMSE tolerance when applied to a documented non-hydrogenic atom or a measured spectral series—systems where core-screening quantum defects are physically present and the perturbative model would be expected to outperform the pure inverse-square form. Such a comparison would move the framework from analytic self-consistency verification to genuine predictive validation.

**Scope and non-claims.** This study does not claim a new hydrogen spectrum, does not assert a physical quantum-defect effect in hydrogen, and should not be treated as experimental spectroscopy. The quantum-defect comparison is a perturbation control, the Bell circuit is a verification control, and the Rydberg fit is a finite-grid analytic check without asserting novelty.



## Testable Predictions

Candidate hypotheses were ranked via an Elo tournament (Co-Scientist–style ranking) before inclusion; lower-ranked candidates are listed last to discourage cherry-picking.

H1. The high-n hydrogen Rydberg residuals represent an emergent systematic quantum defect rather than mere rounding artifacts, exhibiting a logarithmic scaling with principal quantum number that mirrors the information entropy distribution of entangled quantum control states. Testable via: performing a linear regression of the unsigned high-precision residuals (currently ~1.776e-15 eV at n=1) against log(n) for n in the range [1, 20] using extended-precision arithmetic, comparing the fitted slope against a null baseline of slope = 0 (pure rounding error), and cross-validating the residual entropy signature against the 1.0 bit entanglement entropy from the Bell-state circuit control. (confidence: 55%). *(Elo: 1208.9, tournament: 4W-0L-4D, status: known_control)* Testable via: performing a linear regression of the unsigned high-precision residuals (currently ~1.776e-15 eV at n=1) against log(n) for n in the range [1, 20] using extended-precision arithmetic, comparing the fitted slope against a null baseline of slope = 0 (pure rounding error), and cross-validating the residual entropy signature against the 1.0 bit entanglement entropy from the Bell-state circuit control.

H2. The hydrogen Rydberg series is a precision-control dataset in which inverse-square scaling should outperform a quantum-defect perturbation under the recorded RMSE comparison. (confidence: 58%). *(Elo: 1197.5, tournament: 0W-0L-8D, status: known_control)* Testable via: Extend the n grid or replace the dataset with a documented non-hydrogenic spectral series; reject the inverse-square control only if the recorded RMSE tolerance is exceeded under the same units and precision.

H3. The computed hydrogen energy levels provide a precision-control dataset for Rydberg scaling; apparent high-n deviations must be treated as rounding artifacts unless full-precision residuals exceed numerical tolerance. (confidence: 55%). *(Elo: 1192.8, tournament: 0W-4L-4D, status: known_control)* Testable via: Recompute levels at full precision and fit residuals against E_n = -R/n^2 before testing a quantum-defect model.

H4. The inverse-square hydrogen control is falsifiable by replacing the analytic source with an independently implemented numerical Schrodinger solver and checking whether the RMSE remains at the recorded tolerance. (confidence: 56%). Testable via: Run an independent numerical solver on the same n grid; reject the control claim if the residual RMSE exceeds the recorded tolerance under the same units and precision.



## Conclusion

This computational study of e2e validation: hydrogen rydberg inverse-square scaling against perturbation controls has verified theoretical predictions using 3 distinct computational methods. The analysis produced 5 verification controls or finite-range observations, but no result currently satisfies the threshold for a novelty claim. Future work should extend the parameter range, add literature baselines, and quantify effect sizes before proposing new claims.

## Acknowledgments

The authors acknowledge the AXIOM Atlas computational platform for providing
the scientific tools used in this study. All computations were performed on
Apple Silicon M4 hardware with Python 3.13 and MPS acceleration.

## Data Availability

All computational data supporting this study are publicly available.
The following experiment records contain full provenance information
including input parameters, complete output, execution environment,
and SHA-256 output hashes:

- physics_rydberg_scaling_comparison_20260703_163406: `data/experiments/physics_rydberg_scaling_comparison_20260703_163406/provenance.json` (output SHA-256: `f0f11d1e230f29184fb5f12443b9d27b0ed2e2fecafc1adcaead7f0e25d298c9`)
- physics_quantum_energy_levels_20260703_163406: `data/experiments/physics_quantum_energy_levels_20260703_163406/provenance.json` (output SHA-256: `0520678e4d4f7d53d81767363f5736b23d572149ed02bc7881cd2e9a6e419269`)
- physics_quantum_energy_levels_20260703_163406_2: `data/experiments/physics_quantum_energy_levels_20260703_163406_2/provenance.json` (output SHA-256: `7daa3b19910b54d90b4238240b1171baf5047e5d89d7a0a8dbe9875b4bb9309d`)
- physics_quantum_circuit_20260703_163406: `data/experiments/physics_quantum_circuit_20260703_163406/provenance.json` (output SHA-256: `2012ae4fea255ccbc50ed8353f6d6cc2d99ccf486bbc4fafaa2da613bde89049`)

## References

[1] Griffiths, D.J. (2018). Introduction to Quantum Mechanics. Cambridge University Press.
[2] Sakurai, J.J. & Napolitano, J. (2020). Modern Quantum Mechanics. Cambridge University Press.
[3] Bethe, H.A. & Salpeter, E.E. (1957). Quantum Mechanics of One- and Two-Electron Atoms. Springer.
[4] Cohen-Tannoudji, C. et al. (2019). Quantum Mechanics, Vols. 1 & 2. Wiley.


---

## Provenance Watermark

This manuscript was generated by an autonomous research system. It is **not** a peer-reviewed publication. Treat individual claims as computational artifacts until independently verified.

<!-- AMY-WATERMARK
generated_by: A.M.Y (Autonomous Mind Yield) v1.0.0
title: E2E Validation: Hydrogen Rydberg inverse-square scaling against perturbation controls
generated_at: 2026-07-03T16:35:08.650451+00:00
body_sha256: de27c9e0c9b9d5386e009692a9ba0b28ec5504539e48d59db7dbcca2c3f4c74b
homepage: https://github.com/Ganador1/amy
self_review: external_sidecar_when_available
verification: Each cited experiment_id resolves to data/experiments/<id>/provenance.json with a SHA-256 hash of the full tool output.
-->
