# Exact audit of the Alpöge-Fable Jacobian counterexample

**Run date:** 2026-08-11<br>
**Provenance ID:** `mathematics_jacobian_counterexample_audit_v1`<br>
**Canonical result SHA-256:** `5033cd69a655fa2f2ee010505efc9c5d5b56c630cc3e5fd35c8ba0280626bbe0`<br>
**Status:** published result independently reproduced; no novelty claim

## Result

A.M.Y expanded the published polynomial map in exact symbolic arithmetic and
obtained `det(JF) = -2`. It also verified two
disjoint rational three-point fibers:

- Published fiber image: `('-1/4', '0', '0')`.
- Independent certificate image: `('-1', '1', '-1')`.

The inputs in each fiber are distinct and all substitutions are exact. A
nonzero constant Jacobian together with either collision proves that this
specific map is a Keller map that is not injective.

## Why two collision certificates

The determinant identity and the published collision suffice mathematically.
The second fiber is retained as an adversarial implementation check: a typo
that accidentally preserves one hand-picked equality is less likely to
preserve a disjoint equality with a different target. This improves audit
resilience, not the underlying theorem.

## Claim boundary

- This reproduces the explicit dimension-three counterexample.
- It does not claim A.M.Y discovered the map or a new family.
- It does not resolve the remaining two-dimensional Jacobian conjecture.
- SymPy is the computational oracle; the result is not a Lean formalization.

## Primary sources

1. Gao, [Counterexamples to the Jacobian conjecture in dimensions greater than two](https://arxiv.org/abs/2608.00222), 2026.
2. Fong and Fable, [The State of the Jacobian Conjectures](https://jacobianconjectures.com/jacobian/note/), 2026.

## Reproduce

```bash
uv run python experiments/jacobian_counterexample/run_audit.py
```
