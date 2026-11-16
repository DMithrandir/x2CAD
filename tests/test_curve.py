"""曲线求值/求导 oracle：Bézier 闭式、端点差分闭式、双实现对拍、有限差分、
线性精度、常数不变量。"""

import math
import random
from math import comb

import pytest

from operators.curve_eval.impl import (
    curve_derivatives,
    curve_derivatives_by_differencing,
    curve_point,
)
from primitives.bspline import DomainError, find_span, greville_abscissae

from helpers import knot_grid, random_clamped_knots, random_points


def bezier_knots(p):
    return [0.0] * (p + 1) + [1.0] * (p + 1)


def bernstein(p, t):
    return [comb(p, i) * t**i * (1.0 - t) ** (p - i) for i in range(p + 1)]


def forward_diff(ctrl, k, start):
    """Δ^k P_start = Σ_j (-1)^{k-j} C(k,j) P_{start+j}（按维展开）。"""
    dim = len(ctrl[0])
    out = [0.0] * dim
    for j in range(k + 1):
        coef = (-1) ** (k - j) * comb(k, j)
        for d in range(dim):
            out[d] += coef * ctrl[start + j][d]
    return out


@pytest.mark.parametrize("p", [1, 2, 3, 4, 5])
def test_bezier_closed_forms(p):
    rng = random.Random(7000 + p)
    P = random_points(rng, p + 1, 3)
    U = bezier_knots(p)
    lam = lambda u: curve_point(U, p, P, u)

    # 端点插值（clamped 性质）
    assert lam(0.0) == pytest.approx(P[0], abs=1e-12)
    assert lam(1.0) == pytest.approx(P[p], abs=1e-12)

    # Bernstein 求值对拍
    for u in [0.03, 0.17, 0.31, 0.5, 0.68, 0.83, 0.97]:
        B = bernstein(p, u)
        expect = [sum(B[i] * P[i][d] for i in range(p + 1)) for d in range(3)]
        assert lam(u) == pytest.approx(expect, abs=1e-11)

    # 端点导数闭式：C^{(k)}(0) = p(p-1)...(p-k+1) · Δ^k P_0
    #             C^{(k)}(1) = (-1)^k · p(p-1)...(p-k+1) · Δ^k P_rev|_0
    ders0 = curve_derivatives(U, p, P, 0.0, p)
    ders0b = curve_derivatives_by_differencing(U, p, P, 0.0, p)
    ders1 = curve_derivatives(U, p, P, 1.0, p)
    Prev = P[::-1]
    falling = 1.0
    for k in range(1, p + 1):
        falling *= p - k + 1
        tol = 1e-7 * max(1.0, falling * 2**k)
        expect0 = [falling * c for c in forward_diff(P, k, 0)]
        assert ders0[k] == pytest.approx(expect0, abs=tol), (p, k)
        assert ders0b[k] == pytest.approx(ders0[k], abs=tol), (p, k)
        expect1 = [(-1) ** k * falling * c for c in forward_diff(Prev, k, 0)]
        assert ders1[k] == pytest.approx(expect1, abs=tol), (p, k)


@pytest.mark.parametrize("p,n_int", [(2, 5), (3, 6), (4, 4)])
def test_two_methods_agree(p, n_int):
    rng = random.Random(8000 + p * 10 + n_int)
    U = random_clamped_knots(rng, p, n_int, 40)
    P = random_points(rng, p + n_int + 1, 3)
    n = p + n_int
    for u in knot_grid(U, p, n, 120, 2e-3):
        A = curve_derivatives(U, p, P, u, p - 1)
        B = curve_derivatives_by_differencing(U, p, P, u, p - 1)
        for k in range(len(A)):
            scale = 1.0 + max(abs(c) for c in A[k])
            assert A[k] == pytest.approx(B[k], abs=2e-8 * scale), (u, k, A[k], B[k])


@pytest.mark.parametrize("p,n_int", [(3, 5), (4, 4)])
def test_derivatives_vs_finite_difference(p, n_int):
    rng = random.Random(9000 + p * 10 + n_int)
    U = random_clamped_knots(rng, p, n_int, 40)
    P = random_points(rng, p + n_int + 1, 3)
    n = p + n_int
    lam = lambda u: curve_point(U, p, P, u)
    for u in knot_grid(U, p, n, 80, 5e-3):
        ders = curve_derivatives(U, p, P, u, min(2, p))
        d1 = ders[1]
        fd1 = tuple((a - b) / 2e-6 for a, b in zip(lam(u + 1e-6), lam(u - 1e-6)))
        for dim in range(3):
            assert abs(d1[dim] - fd1[dim]) < 2e-4 * (1.0 + abs(d1[dim])), (u, dim)
        if p >= 3:
            d2 = ders[2]
            h = 1e-5
            pp, p0, pm = lam(u + h), lam(u), lam(u - h)
            fd2 = tuple((a - 2.0 * b + c) / (h * h) for a, b, c in zip(pp, p0, pm))
            for dim in range(3):
                assert abs(d2[dim] - fd2[dim]) < 5e-2 * (1.0 + abs(d2[dim])), (u, dim)


def test_clamped_endpoint_derivative_formula():
    # 一般 clamped 向量：C'(U[p]) = p(P_1-P_0)/(U[p+1]-U[p])，右端同理
    rng = random.Random(9500)
    p, n_int = 3, 5
    U = random_clamped_knots(rng, p, n_int, 40)
    P = random_points(rng, p + n_int + 1, 2)
    n = p + n_int
    d0 = curve_derivatives(U, p, P, U[p], 1)[1]
    expect0 = [p * (P[1][d] - P[0][d]) / (U[p + 1] - U[p]) for d in range(2)]
    assert d0 == pytest.approx(expect0, abs=1e-9)
    d1 = curve_derivatives(U, p, P, U[n + 1], 1)[1]
    expect1 = [p * (P[n][d] - P[n - 1][d]) / (U[n + 1] - U[n]) for d in range(2)]
    assert d1 == pytest.approx(expect1, abs=1e-9)


def test_constant_curve_invariant():
    rng = random.Random(9600)
    U = random_clamped_knots(rng, 3, 4, 40)
    Q = (0.3, -1.2, 2.0)
    P = [Q] * (3 + 4 + 1)
    n = len(P) - 1
    for u in knot_grid(U, 3, n, 40, 1e-3):
        ders = curve_derivatives(U, 3, P, u, 3)
        assert ders[0] == pytest.approx(Q, abs=1e-12)
        for k in (1, 2, 3):
            assert ders[k] == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_linear_precision():
    # 控制点取 Greville 横坐标处线性函数值 → 曲线精确重现该线性函数
    rng = random.Random(9700)
    for p, n_int in [(1, 4), (2, 6), (3, 5)]:
        U = random_clamped_knots(rng, p, n_int, 40)
        n = p + n_int
        xi = greville_abscissae(U, p, n)
        a, b = (0.7, -2.0, 1.5), (-1.3, 0.4, 0.9)
        P = [tuple(a[d] + b[d] * xi[i] for d in range(3)) for i in range(n + 1)]
        for u in knot_grid(U, p, n, 50, 1e-6):
            val = curve_point(U, p, P, u)
            expect = tuple(a[d] + b[d] * u for d in range(3))
            assert val == pytest.approx(expect, abs=1e-9), (p, u)
            d1 = curve_derivatives(U, p, P, u, 1)[1]
            assert d1 == pytest.approx(b, abs=1e-7), (p, u)


def test_differencing_smoothness_precondition():
    # 内部重数 2、p=3（C^1 曲线）：一阶导方法 B 可用且与方法 A 一致；二阶导被前置拒绝
    U = [0.0, 0.0, 0.0, 0.0, 0.3, 0.3, 1.0, 1.0, 1.0, 1.0]
    p, n = 3, 5
    P = [(-1.0, 0.0), (0.0, 1.0), (0.5, 1.0), (1.0, 0.5), (1.5, -0.2), (2.0, -0.5)]
    ders1 = curve_derivatives_by_differencing(U, p, P, 0.5, 1)
    ders1a = curve_derivatives(U, p, P, 0.5, 1)
    assert ders1[1] == pytest.approx(ders1a[1], abs=1e-10)
    with pytest.raises(DomainError):
        curve_derivatives_by_differencing(U, p, P, 0.5, 2)
