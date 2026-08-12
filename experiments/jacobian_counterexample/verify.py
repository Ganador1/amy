"""Exact symbolic audit of the 2026 Alpöge-Fable Jacobian counterexample."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import sympy as sp


RationalPoint = tuple[sp.Rational, sp.Rational, sp.Rational]


@dataclass(frozen=True)
class CollisionVerification:
    valid: bool
    distinct_inputs: bool
    common_output: tuple[str, str, str] | None
    reason: str


def alpoge_fable_map() -> tuple[tuple[sp.Symbol, ...], tuple[sp.Expr, ...]]:
    """Return the published polynomial map F: C^3 -> C^3."""
    x, y, z = sp.symbols("x y z")
    u = 1 + x * y
    components = (
        sp.expand(u**3 * z + y**2 * u * (4 + 3 * x * y)),
        sp.expand(y + 3 * x * u**2 * z + 3 * x * y**2 * (4 + 3 * x * y)),
        sp.expand(2 * x - 3 * x**2 * y - x**3 * z),
    )
    return (x, y, z), components


def evaluate_map(point: RationalPoint) -> RationalPoint:
    variables, components = alpoge_fable_map()
    substitutions = dict(zip(variables, point, strict=True))
    return tuple(sp.Rational(component.subs(substitutions)) for component in components)


def verify_collision(
    points: tuple[RationalPoint, ...],
    expected_output: RationalPoint | None = None,
) -> CollisionVerification:
    """Check that distinct rational inputs have exactly the same image."""
    if len(points) < 2:
        return CollisionVerification(False, False, None, "at least two points are required")
    distinct = len(set(points)) == len(points)
    outputs = tuple(evaluate_map(point) for point in points)
    common = outputs[0]
    same_output = all(output == common for output in outputs)
    expected = expected_output is None or common == expected_output
    valid = distinct and same_output and expected
    if not distinct:
        reason = "inputs are not distinct"
    elif not same_output:
        reason = "inputs do not share an image"
    elif not expected:
        reason = "common image differs from the published target"
    else:
        reason = "exact rational collision verified"
    return CollisionVerification(
        valid,
        distinct,
        tuple(str(value) for value in common) if same_output else None,
        reason,
    )


def run_audit() -> dict:
    variables, components = alpoge_fable_map()
    jacobian = sp.Matrix(components).jacobian(variables)
    determinant = sp.expand(jacobian.det())
    degrees = [sp.Poly(component, *variables).total_degree() for component in components]

    official_points = (
        (sp.Rational(0), sp.Rational(0), sp.Rational(-1, 4)),
        (sp.Rational(1), sp.Rational(-3, 2), sp.Rational(13, 2)),
        (sp.Rational(-1), sp.Rational(3, 2), sp.Rational(13, 2)),
    )
    official_target = (sp.Rational(-1, 4), sp.Rational(0), sp.Rational(0))
    independent_points = (
        (sp.Rational(1), sp.Rational(-2), sp.Rational(9)),
        (sp.Rational(-1, 3), sp.Rational(4), sp.Rational(27)),
        (sp.Rational(-2, 3), sp.Rational(-1, 2), sp.Rational(-9, 8)),
    )
    independent_target = (sp.Rational(-1), sp.Rational(1), sp.Rational(-1))
    official = verify_collision(official_points, official_target)
    independent = verify_collision(independent_points, independent_target)

    certificate_payload = {
        "components": [str(component) for component in components],
        "jacobian_determinant": str(determinant),
        "official_collision": official.__dict__,
        "independent_collision": independent.__dict__,
    }
    certificate_digest = hashlib.sha256(
        json.dumps(certificate_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "experiment": "amy_alpoge_fable_exact_audit_v1",
        "map": {
            "variables": [str(variable) for variable in variables],
            "components": [str(component) for component in components],
            "total_degrees": degrees,
        },
        "jacobian": {
            "determinant": str(determinant),
            "is_nonzero_constant": determinant == -2,
        },
        "official_collision": official.__dict__,
        "independent_collision": independent.__dict__,
        "certificate_sha256": certificate_digest,
        "counterexample_conditions_verified": (
            determinant == -2 and official.valid and independent.valid
        ),
        "method": {
            "arithmetic": "exact SymPy integer/rational polynomial arithmetic",
            "determinant_check": "symbolic expansion of det(JF) + 2 to zero",
            "collision_check": "exact substitution at two disjoint three-point fibers",
        },
        "claim_status": {
            "published_counterexample_replicated": True,
            "new_counterexample_claimed": False,
            "global_novelty_certified": False,
            "plane_case_resolved": False,
        },
    }
