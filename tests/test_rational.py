"""NURBS（有理）曲线 oracle：单位圆不变量（|C|=1、位置·切矢=0）、端点切向闭式、
有限差分。圆是解析真值级预言机：任何有理求值/求导的错误都会破坏 |C(u)|=1。"""

import math
import random

import pytest

from operators.curve_eval.impl import nurbs_curve_derivatives, nurbs_curve_point
from primitives.bspline import DomainError

SQRH = math.sqrt(0.5)


def quarter_circle():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    W = [1.0, SQRH, 1.0]
    return U, 2, P, W


def nine_point_circle():
    U = [0.0, 0.0, 0.0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1.0, 1.0, 1.0]
    P = [
        (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (-1.0, 1.0), (-1.0, 0.0),
        (-1.0, -1.0), (0.0, -1.0), (1.0, -1.0), (1.0, 0.0),
    ]
    W = [1.0, SQRH, 1.0, SQRH, 1.0, SQRH, 1.0, SQRH, 1.0]
    return U, 2, P, W


@pytest.mark.parametrize("mk", [quarter_circle, nine_point_circle])
def test_circle_radius_invariant(mk):
    U, p, P, W = mk()
    for i in range(501):
        u = i / 500
        C = nurbs_curve_point(U, p, P, W, u)
        r = math.hypot(C[0], C[1])
        assert abs(r - 1.0) < 5e-12, (u, r)
        D = nurbs_curve_derivatives(U, p, P, W, u, 1)[1]
        dot = C[0] * D[0] + C[1] * D[1]
        assert abs(dot) < 1e-8, (u, dot)


def test_quarter_circle_endpoints_and_tangents():
    U, p, P, W = quarter_circle()
    assert nurbs_curve_point(U, p, P, W, 0.0) == pytest.approx((1.0, 0.0), abs=1e-12)
    assert nurbs_curve_point(U, p, P, W, 1.0) == pytest.approx((0.0, 1.0), abs=1e-12)
    # 有理 Bézier 端点导矢闭式：C'(0) = p·(w_1/w_0)·(P_1-P_0) = √2·(0,1)
    D0 = nurbs_curve_derivatives(U, p, P, W, 0.0, 1)[1]
    assert D0 == pytest.approx((0.0, math.sqrt(2.0)), abs=1e-10)
    D1 = nurbs_curve_derivatives(U, p, P, W, 1.0, 1)[1]
    assert D1 == pytest.approx((-math.sqrt(2.0), 0.0), abs=1e-10)


def test_nine_point_circle_hits_cardinals():
    U, p, P, W = nine_point_circle()
    assert nurbs_curve_point(U, p, P, W, 0.25) == pytest.approx((0.0, 1.0), abs=1e-10)
    assert nurbs_curve_point(U, p, P, W, 0.5) == pytest.approx((-1.0, 0.0), abs=1e-10)
    assert nurbs_curve_point(U, p, P, W, 0.75) == pytest.approx((0.0, -1.0), abs=1e-10)
    assert nurbs_curve_point(U, p, P, W, 1.0) == pytest.approx((1.0, 0.0), abs=1e-10)


def test_nurbs_derivatives_vs_finite_difference():
    rng = random.Random(11000)
    for trial in range(6):
        p = rng.choice([2, 3, 4])
        n_int = rng.choice([3, 5])
        from helpers import random_clamped_knots, random_points

        U = random_clamped_knots(rng, p, n_int, 40)
        P = random_points(rng, p + n_int + 1, 3)
        W = [rng.uniform(0.2, 3.0) for _ in range(len(P))]
        for u in [rng.uniform(U[p] + 0.02, U[-p - 1] - 0.02) for _ in range(12)]:
            ders = nurbs_curve_derivatives(U, p, P, W, u, min(2, p))
            h = 1e-6
            pp = nurbs_curve_point(U, p, P, W, u + h)
            pm = nurbs_curve_point(U, p, P, W, u - h)
            fd1 = [(a - b) / (2 * h) for a, b in zip(pp, pm)]
            for d in range(3):
                assert abs(ders[1][d] - fd1[d]) < 3e-4 * (1.0 + abs(ders[1][d])), (trial, u, d)
            if p >= 3:
                h = 1e-5
                pp = nurbs_curve_point(U, p, P, W, u + h)
                p0 = nurbs_curve_point(U, p, P, W, u)
                pm = nurbs_curve_point(U, p, P, W, u - h)
                fd2 = [(a - 2 * b + c) / (h * h) for a, b, c in zip(pp, p0, pm)]
                for d in range(3):
                    assert abs(ders[2][d] - fd2[d]) < 8e-2 * (1.0 + abs(ders[2][d])), (trial, u, d)


def test_weight_validation():
    U, p, P, W = quarter_circle()
    with pytest.raises(DomainError):
        nurbs_curve_point(U, p, P, [1.0, -SQRH, 1.0], 0.5)
    with pytest.raises(DomainError):
        nurbs_curve_point(U, p, P, [1.0, SQRH], 0.5)
