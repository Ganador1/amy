import sympy as sp

from experiments.jacobian_counterexample.verify import (
    alpoge_fable_map,
    evaluate_map,
    run_audit,
    verify_collision,
)


def test_published_map_has_constant_negative_two_jacobian():
    variables, components = alpoge_fable_map()
    determinant = sp.expand(sp.Matrix(components).jacobian(variables).det())
    assert determinant == -2


def test_published_three_point_collision_is_exact():
    points = (
        (sp.Rational(0), sp.Rational(0), sp.Rational(-1, 4)),
        (sp.Rational(1), sp.Rational(-3, 2), sp.Rational(13, 2)),
        (sp.Rational(-1), sp.Rational(3, 2), sp.Rational(13, 2)),
    )
    expected = (sp.Rational(-1, 4), sp.Rational(0), sp.Rational(0))
    result = verify_collision(points, expected)
    assert result.valid is True
    assert all(evaluate_map(point) == expected for point in points)


def test_audit_checks_second_disjoint_collision():
    audit = run_audit()
    assert audit["map"]["total_degrees"] == [7, 6, 4]
    assert audit["official_collision"]["valid"] is True
    assert audit["independent_collision"]["valid"] is True
    assert audit["counterexample_conditions_verified"] is True


def test_collision_verifier_rejects_repeated_inputs():
    point = (sp.Rational(0), sp.Rational(0), sp.Rational(-1, 4))
    result = verify_collision((point, point))
    assert result.valid is False
    assert result.distinct_inputs is False
