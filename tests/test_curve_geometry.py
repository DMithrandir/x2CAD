"""曲线微分几何量的 oracle：解析值 + 独立求积对拍 + 有限差分对拍。

- 弧长：直线/圆解析值；随机曲线用 Simpson 法则（独立于 Gauss–Legendre）对拍；
- 曲率：圆的 κ=1/r、抛物线顶点 κ=2 为解析真值；随机曲线用位置的中心差分重建导数再算 κ
  （与实现走的基函数导数路线不同源）。
"""

import math
import random

import pytest

from operators.curve_eval.impl import curve_point
from operators.curve_geometry.impl import (
    arc_length,
    curvature,
    nurbs_arc_length,
    nurbs_curvature,
    nurbs_unit_tangent,
    speed,
    unit_tangent,
)
from primitives.bspline import DomainError
from primitives.quadrature import gauss_legendre, integrate

from helpers import random_clamped_knots, random_points

QUARTER_CIRCLE = dict(
    U=[0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
    p=2,
    ctrl=[(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
    w=[1.0, 0.7071067811865476, 1.0],
)


# ---------------------------------------------------------------- 求积基元


def test_gauss_legendre_polynomial_exactness():
    for n in (1, 2, 4, 8):
        nodes, weights = gauss_legendre(n)
        assert len(nodes) == n and len(weights) == n
        assert sum(weights) == pytest.approx(2.0, abs=1e-14)
        # 2n-1 次以下多项式精确：∫_{-1}^{1} x^k = 0（k 奇）/ 2/(k+1)（k 偶）
        for k in range(0, 2 * n):
            value = sum(w * x**k for x, w in zip(nodes, weights))
            expected = 0.0 if k % 2 else 2.0 / (k + 1)
            assert value == pytest.approx(expected, abs=1e-12)


def test_integrate_direction_and_degenerate():
    assert integrate(lambda x: x * x, 0.0, 3.0) == pytest.approx(9.0, abs=1e-12)
    assert integrate(lambda x: 1.0, 2.0, 2.0) == 0.0
    assert integrate(lambda x: x, 1.0, 0.0) == pytest.approx(-0.5, rel=1e-14)
    with pytest.raises(DomainError):
        integrate(lambda x: x, 0.0, float("inf"))


# ---------------------------------------------------------------- 弧长


def test_line_arc_length_exact():
    # 二次 Bézier，控制点共线：曲线就是直线段，长度为 2
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    ctrl = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert arc_length(U, 2, ctrl) == pytest.approx(2.0, abs=1e-13)


def test_quarter_circle_arc_length_is_pi_over_two():
    c = QUARTER_CIRCLE
    # 用非有理求值会得到不同的长度；这里必须走 NURBS 版本
    length = nurbs_arc_length(c["U"], c["p"], c["ctrl"], c["w"])
    assert length == pytest.approx(math.pi / 2.0, rel=1e-12)


def test_arc_length_is_additive():
    rng = random.Random(7100)
    U = random_clamped_knots(rng, 3, 2)
    n = len(U) - 3 - 2
    ctrl = random_points(rng, n + 1, 2)
    total = arc_length(U, 3, ctrl)
    parts = arc_length(U, 3, ctrl, 0.0, 0.3) + arc_length(U, 3, ctrl, 0.3, 1.0)
    assert parts == pytest.approx(total, rel=1e-12)


def _simpson(f, a, b, n=4000):
    if n % 2:
        n += 1
    h = (b - a) / n
    s = f(a) + f(b)
    for i in range(1, n):
        s += (4.0 if i % 2 else 2.0) * f(a + i * h)
    return s * h / 3.0


def test_arc_length_matches_independent_simpson():
    rng = random.Random(7200)
    for _ in range(5):
        U = random_clamped_knots(rng, 3, 3)
        n = len(U) - 3 - 2
        ctrl = random_points(rng, n + 1, 2)
        got = arc_length(U, 3, ctrl)
        ref = _simpson(lambda t: speed(U, 3, ctrl, t), 0.0, 1.0)
        assert got == pytest.approx(ref, rel=1e-8)


def test_arc_length_rejects_bad_intervals():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    ctrl = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    with pytest.raises(DomainError):
        arc_length(U, 2, ctrl, 0.5, 0.5)
    with pytest.raises(DomainError):
        arc_length(U, 2, ctrl, 1.2)


# ---------------------------------------------------------------- 切矢/曲率


def test_unit_tangent_of_circle():
    c = QUARTER_CIRCLE
    # 起点处切矢 = (0,1)；中点处切矢 = (-1,1)/√2
    t0 = nurbs_unit_tangent(c["U"], c["p"], c["ctrl"], c["w"], 0.0)
    assert t0 == pytest.approx((0.0, 1.0), abs=1e-12)
    tm = nurbs_unit_tangent(c["U"], c["p"], c["ctrl"], c["w"], 0.5)
    r = 1.0 / math.sqrt(2.0)
    assert tm == pytest.approx((-r, r), abs=1e-12)
    assert math.hypot(*tm) == pytest.approx(1.0, abs=1e-14)


def test_circle_curvature_is_one():
    c = QUARTER_CIRCLE
    for u in (0.05, 0.25, 0.5, 0.75, 0.95):
        assert nurbs_curvature(c["U"], c["p"], c["ctrl"], c["w"], u) == pytest.approx(1.0, rel=1e-10)


def test_parabola_curvature_analytic():
    """Bézier (-1,1),(0,-1),(1,1) 精确表示 y=x²。κ(x)=2/(1+4x²)^{3/2}。"""
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    ctrl = [(-1.0, 1.0), (0.0, -1.0), (1.0, 1.0)]
    for t, x in ((0.0, -1.0), (0.3, -0.4), (0.5, 0.0), (0.7, 0.4), (1.0, 1.0)):
        expected = 2.0 / (1.0 + 4.0 * x * x) ** 1.5
        assert curvature(U, 2, ctrl, t) == pytest.approx(expected, rel=1e-12)


def test_straight_line_has_zero_curvature():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    ctrl = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    for u in (0.1, 0.5, 0.9):
        assert curvature(U, 2, ctrl, u) == pytest.approx(0.0, abs=1e-15)


def test_curvature_matches_finite_difference_reconstruction():
    rng = random.Random(7300)
    U = random_clamped_knots(rng, 4, 2)
    n = len(U) - 4 - 2
    ctrl = random_points(rng, n + 1, 2)
    h = 1e-4
    for u in (0.2, 0.45, 0.7):
        p0 = curve_point(U, 4, ctrl, u)
        pm = curve_point(U, 4, ctrl, u - h)
        pp = curve_point(U, 4, ctrl, u + h)
        d1 = [(pp[d] - pm[d]) / (2 * h) for d in range(2)]
        d2 = [(pp[d] - 2 * p0[d] + pm[d]) / (h * h) for d in range(2)]
        num = abs(d1[0] * d2[1] - d1[1] * d2[0])
        den = (math.hypot(*d1)) ** 3
        ref = num / den
        assert curvature(U, 4, ctrl, u) == pytest.approx(ref, rel=2e-5)


def test_curvature_requires_second_derivative():
    U = [0.0, 0.0, 1.0, 1.0]
    ctrl = [(0.0, 0.0), (1.0, 0.0)]
    with pytest.raises(DomainError, match="二阶导"):
        curvature(U, 1, ctrl, 0.5)


def test_singular_speed_is_rejected():
    # 重节点导致的尖点：两个控制点重合 → 在 u=0.5 处 |C'| 可能为零
    U = [0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0]
    ctrl = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    with pytest.raises(DomainError):
        unit_tangent(U, 2, ctrl, 0.5)


# ---------------------------------------------------------------- Tier 4 鲁棒性平面


def test_arc_length_robustness_plane():
    """四分之一圆弧长在 刚体变换 × 尺度 × 位错 × 容差 四维扰动下的通过率。"""
    from verify.robustness import random_rotation_2d, rigid_transform_2d, run_plane

    W = [1.0, 0.7071067811865476, 1.0]
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    base = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    def build(scale, offset, tol, rng):
        rot = random_rotation_2d(rng)
        moved = rigid_transform_2d(base, rot, (offset, -offset))
        ctrl = [(x * scale, y * scale) for x, y in moved]
        return {"U": U, "ctrl": ctrl, "scale": scale}

    result = run_plane(
        "nurbs_quarter_circle_arc_length",
        build,
        lambda o: nurbs_arc_length(o["U"], 2, o["ctrl"], W),
        lambda o: o["scale"] * math.pi / 2.0,
        threshold=1e-9,
    )
    assert result.default_domain_pass_rate() == 1.0
    assert result.worst_error() < 1e-9
    assert len(result.rows) == 3 * 5 * 5 * 3
