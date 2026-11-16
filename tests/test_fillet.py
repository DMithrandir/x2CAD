"""2D 圆角的 oracle：直角手算例 + 相切性/等距性 + 解析弧长 + 退化拒绝。

圆角是 Pointer-CAD 文档 §4.5 说的「表示能力的酸测试」：选边 + 半径 → 相切圆弧。
这里的 oracle 全部是解析的（距离、正交、弧长），不依赖任何参考实现。
"""

import math
import random

import pytest

from operators.fillet_2d.impl import fillet_corner
from primitives.bspline import DomainError


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


def test_right_angle_hand_example():
    f = fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), 1.0)
    assert f.center == pytest.approx((1.0, 1.0))
    assert f.tangent1 == pytest.approx((1.0, 0.0))
    assert f.tangent2 == pytest.approx((0.0, 1.0))
    assert f.angle == pytest.approx(math.pi / 2)
    assert f.sweep == pytest.approx(-math.pi / 2)
    assert f.length == pytest.approx(math.pi / 2)
    assert f.point(0.0) == pytest.approx(f.tangent1)
    assert f.point(1.0) == pytest.approx(f.tangent2)


@pytest.mark.parametrize("theta_deg", [30, 45, 60, 90, 120, 150])
def test_tangency_and_distance_properties(theta_deg):
    theta = math.radians(theta_deg)
    L = 5.0
    r = 0.2 * L
    p2 = (0.0, 0.0)
    p1 = (L, 0.0)
    p3 = (L * math.cos(theta), L * math.sin(theta))
    f = fillet_corner(p1, p2, p3, r)

    u = _unit(_sub(p1, p2))
    v = _unit(_sub(p3, p2))
    # 1) 等距
    assert math.dist(f.center, f.tangent1) == pytest.approx(r, rel=1e-12)
    assert math.dist(f.center, f.tangent2) == pytest.approx(r, rel=1e-12)
    # 2) 正交（半径 ⟂ 边）—— 相切的等价条件
    assert _dot(_sub(f.tangent1, f.center), u) == pytest.approx(0.0, abs=1e-12)
    assert _dot(_sub(f.tangent2, f.center), v) == pytest.approx(0.0, abs=1e-12)
    # 3) 圆心到两条边所在直线的距离 = r
    def point_line_distance(c, a, d):
        w = _sub(c, a)
        return abs(w[0] * d[1] - w[1] * d[0])

    assert point_line_distance(f.center, p2, u) == pytest.approx(r, rel=1e-12)
    assert point_line_distance(f.center, p2, v) == pytest.approx(r, rel=1e-12)
    # 4) 弧长与中点
    assert f.length == pytest.approx(r * (math.pi - theta), rel=1e-12)
    d = r / math.sin(theta / 2.0)
    assert math.dist(f.corner, f.center) == pytest.approx(d, rel=1e-12)
    mid = f.point(0.5)
    assert math.dist(mid, p2) == pytest.approx(d - r, rel=1e-12)
    # 5) 切点在边上（距离角点 t）
    t = r / math.tan(theta / 2.0)
    assert math.dist(f.tangent1, p2) == pytest.approx(t, rel=1e-12)
    assert math.dist(f.tangent2, p2) == pytest.approx(t, rel=1e-12)


def test_arc_points_lie_on_circle():
    f = fillet_corner((2.0, 0.0), (0.0, 0.0), (0.0, 3.0), 0.5)
    for j in range(11):
        p = f.point(j / 10)
        assert math.dist(p, f.center) == pytest.approx(0.5, rel=1e-12)


def test_arc_parameter_bounds():
    f = fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), 0.5)
    with pytest.raises(DomainError):
        f.point(-0.1)
    with pytest.raises(DomainError):
        f.point(1.1)


def test_small_radius_matches_numeric_arc():
    # 半径很小时弧长仍精确等于 r(π−θ)（避免"按折线近似"的常见错误）
    theta = math.radians(70)
    f = fillet_corner((1.0, 0.0), (0.0, 0.0), (math.cos(theta), math.sin(theta)), 1e-6)
    assert f.length == pytest.approx(1e-6 * (math.pi - theta), rel=1e-12)


def test_radius_too_large_is_rejected():
    with pytest.raises(DomainError, match="过大"):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), 2.0)


def test_collinear_edges_are_rejected():
    with pytest.raises(DomainError, match="共线"):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (-1.0, 0.0), 0.1)
    with pytest.raises(DomainError, match="共线"):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (2.0, 0.0), 0.1)


def test_zero_length_edges_are_rejected():
    with pytest.raises(DomainError):
        fillet_corner((0.0, 0.0), (0.0, 0.0), (0.0, 1.0), 0.1)
    with pytest.raises(DomainError):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 0.0), 0.1)


def test_bad_radius_and_dimensionality_are_rejected():
    with pytest.raises(DomainError):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), 0.0)
    with pytest.raises(DomainError):
        fillet_corner((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), -1.0)
    with pytest.raises(DomainError):
        fillet_corner((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.1)


def test_random_corners_invariant_scan():
    rng = random.Random(8100)
    for _ in range(50):
        theta = rng.uniform(0.2, math.pi - 0.2)
        L = rng.uniform(1.0, 10.0)
        # 保证切点距离 t = r/tan(θ/2) 不超过边长 L
        r = rng.uniform(0.05, 0.5) * L * math.tan(theta / 2.0)
        p1 = (L, 0.0)
        p3 = (L * math.cos(theta), L * math.sin(theta))
        f = fillet_corner(p1, (0.0, 0.0), p3, r)
        assert f.length == pytest.approx(r * (math.pi - theta), rel=1e-11)
        for tp in (f.tangent1, f.tangent2):
            assert math.dist(tp, f.center) == pytest.approx(r, rel=1e-11)
