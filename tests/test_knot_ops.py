"""N2 节点操作 oracle：Boehm 节点插入（几何不变性 + 解析反例 + 退化拒绝）。

核心判据：节点插入**不改变曲线几何**。这是强 oracle——它不依赖实现内部的任何中间量，
只比较插前/插后两条曲线在参数域内的逐点值。

另设解析手工例（p=1 的线性情形）钉死公式细节：分母若误用 U[i+p+1]-U[i]，
该例给出 1.25 而非正确答案 1.5。
"""

import math
import random

import pytest

from operators.curve_eval.impl import curve_point, nurbs_curve_point
from operators.curve_split.impl import split_curve, split_curve_nurbs
from operators.degree_elevation.impl import (
    elevate_bezier,
    elevate_bezier_nurbs,
    elevate_bezier_to,
)
from operators.knot_insertion.impl import insert_knot, insert_knot_nurbs, knot_multiplicity
from primitives.bspline import DomainError

from helpers import random_clamped_knots, random_points


def _random_curve(rng, p, n_interior):
    U = random_clamped_knots(rng, p, n_interior)
    n = len(U) - p - 2
    P = random_points(rng, n + 1, 2)
    return U, p, P


def _max_deviation(U0, P0, U1, P1, p, samples=25):
    lo, hi = U0[p], U0[len(P0) - 1 + 1]
    worst = 0.0
    for j in range(samples + 1):
        u = lo + (hi - lo) * j / samples
        a = curve_point(U0, p, P0, u)
        b = curve_point(U1, p, P1, u)
        worst = max(worst, max(abs(x - y) for x, y in zip(a, b)))
    return worst


@pytest.mark.parametrize("p", [1, 2, 3, 4])
def test_geometry_invariance_random(p):
    rng = random.Random(4100 + p)
    for _ in range(25):
        U, p_, P = _random_curve(rng, p, rng.randint(1, 4))
        lo, hi = U[p], U[len(P)]
        u = lo + (hi - lo) * rng.uniform(0.05, 0.95)
        U2, P2 = insert_knot(U, p_, P, u)
        assert _max_deviation(U, P, U2, P2, p_) < 1e-12
        assert knot_multiplicity(U2, u) == knot_multiplicity(U, u) + 1


def test_geometry_invariance_at_existing_knot():
    rng = random.Random(4200)
    U, p, P = _random_curve(rng, 3, 3)
    interior = sorted(set(U[4:7]))
    assert interior, "需要至少一个内部节点"
    u = interior[0]
    s = knot_multiplicity(U, u)
    U2, P2 = insert_knot(U, p, P, u, r=p - s)
    assert knot_multiplicity(U2, u) == p
    assert _max_deviation(U, P, U2, P2, p) < 1e-12


def test_hand_example_p1_exact():
    """p=1：插入 1.5 后新旧控制点必须把折线原样表示（解析值，无容差）。"""
    U = [0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 4.0]
    P = [(0.0,), (1.0,), (2.0,), (3.0,), (4.0,)]
    U2, P2 = insert_knot(U, 1, P, 1.5)
    assert U2 == [0.0, 0.0, 1.0, 1.5, 2.0, 3.0, 4.0, 4.0]
    assert [q[0] for q in P2] == [0.0, 1.0, 1.5, 2.0, 3.0, 4.0]


def test_length_and_count_invariants():
    rng = random.Random(4300)
    U, p, P = _random_curve(rng, 3, 2)
    for r in (0, 1, 2):
        U2, P2 = insert_knot(U, p, P, 0.37, r=r)
        assert len(U2) == len(U) + r
        assert len(P2) == len(P) + r
        U3, P3 = insert_knot(U2, p, P2, 0.37, r=0)
        assert U3 == U2 and P3 == P2


def test_repeat_to_multiplicity_p_is_still_same_curve():
    rng = random.Random(4400)
    U, p, P = _random_curve(rng, 4, 2)
    u = 0.43
    s = knot_multiplicity(U, u)
    U2, P2 = insert_knot(U, p, P, u, r=p - s)
    assert knot_multiplicity(U2, u) == p
    assert _max_deviation(U, P, U2, P2, p) < 1e-11


def test_nurbs_circle_invariance():
    # 标准四分之一圆（有理二次）
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    W = [1.0, 0.7071067811865476, 1.0]
    U2, P2, W2 = insert_knot_nurbs(U, 2, P, W, 0.5)
    for j in range(11):
        u = j / 10
        a = nurbs_curve_point(U, 2, P, W, u)
        b = nurbs_curve_point(U2, 2, P2, W2, u)
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-14
        assert abs(math.hypot(*b) - 1.0) < 5e-13
    assert all(w > 0 for w in W2)


def test_endpoint_insertion_is_rejected():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    with pytest.raises(DomainError, match="插入后重数"):
        insert_knot(U, 2, P, 0.0)
    with pytest.raises(DomainError, match="插入后重数"):
        insert_knot(U, 2, P, 1.0)


def test_exceeding_multiplicity_is_rejected():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    P = random_points(random.Random(1), 4, 2)
    with pytest.raises(DomainError, match="插入后重数"):
        insert_knot(U, 2, P, 0.5, r=2)


def test_bad_arguments_are_rejected():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    with pytest.raises(DomainError):
        insert_knot(U, 2, P, -0.1)
    with pytest.raises(DomainError):
        insert_knot(U, 2, P, 1.1)
    with pytest.raises(DomainError):
        insert_knot(U, 2, P, 0.5, r=-1)
    with pytest.raises(DomainError):
        insert_knot(U, 2, P, float("nan"))
    with pytest.raises(DomainError):
        insert_knot_nurbs(U, 2, P, [1.0, 0.0, 1.0], 0.5)
    with pytest.raises(DomainError):
        insert_knot_nurbs(U, 2, P, [1.0, 1.0], 0.5)


# ---------------------------------------------------------------- 曲线分割


def _curve_domain(U, P, p):
    return U[p], U[len(P)]


@pytest.mark.parametrize("p", [1, 2, 3])
def test_split_pieces_reproduce_original(p):
    rng = random.Random(5200 + p)
    for _ in range(15):
        U, p_, P = _random_curve(rng, p, rng.randint(1, 3))
        lo, hi = _curve_domain(U, P, p_)
        u = lo + (hi - lo) * rng.uniform(0.1, 0.9)
        (Ul, Pl), (Ur, Pr) = split_curve(U, p_, P, u)
        # 左段参数域 [lo, u]，右段 [u, hi]
        for j in range(11):
            t = u if j == 10 else lo + (u - lo) * j / 10
            a = curve_point(U, p_, P, t)
            b = curve_point(Ul, p_, Pl, t)
            assert max(abs(x - y) for x, y in zip(a, b)) < 1e-12
            t2 = u if j == 0 else u + (hi - u) * j / 10
            a2 = curve_point(U, p_, P, t2)
            b2 = curve_point(Ur, p_, Pr, t2)
            assert max(abs(x - y) for x, y in zip(a2, b2)) < 1e-12


def test_split_shared_endpoint():
    rng = random.Random(5300)
    U, p, P = _random_curve(rng, 3, 2)
    u = 0.4
    (Ul, Pl), (Ur, Pr) = split_curve(U, p, P, u)
    left_end = curve_point(Ul, p, Pl, u)
    right_start = curve_point(Ur, p, Pr, u)
    original = curve_point(U, p, P, u)
    assert max(abs(a - b) for a, b in zip(left_end, original)) < 1e-13
    assert max(abs(a - b) for a, b in zip(right_start, original)) < 1e-13


def test_split_at_existing_knot():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    P = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0)]
    (Ul, Pl), (Ur, Pr) = split_curve(U, 2, P, 0.5)
    for t in (0.0, 0.1, 0.25, 0.5):
        a = curve_point(U, 2, P, t)
        b = curve_point(Ul, 2, Pl, t)
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-13
    for t in (0.5, 0.75, 1.0):
        a = curve_point(U, 2, P, t)
        b = curve_point(Ur, 2, Pr, t)
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-13


def test_split_rejects_endpoints_and_outside():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    for u in (0.0, 1.0, -0.5, 1.5, float("inf")):
        with pytest.raises(DomainError):
            split_curve(U, 2, P, u)


def test_split_nurbs_circle():
    U = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    P = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    W = [1.0, 0.7071067811865476, 1.0]
    (Ul, Pl, Wl), (Ur, Pr, Wr) = split_curve_nurbs(U, 2, P, W, 0.5)
    for t in (0.0, 0.1, 0.2, 0.3, 0.5):
        a = nurbs_curve_point(U, 2, P, W, t)
        b = nurbs_curve_point(Ul, 2, Pl, Wl, t)
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-13
        assert abs(math.hypot(*b) - 1.0) < 1e-12
    assert Ul[-1] == pytest.approx(0.5) or Ul[-1] == 0.5


# ---------------------------------------------------------------- Bézier 升阶


def _bernstein_eval(ctrl, t):
    p = len(ctrl) - 1
    out = [0.0] * len(ctrl[0])
    for i, P in enumerate(ctrl):
        b = math.comb(p, i) * t**i * (1.0 - t) ** (p - i)
        for d in range(len(P)):
            out[d] += b * P[d]
    return out


def test_elevate_bezier_hand_example():
    """二次 → 三次的解析值。"""
    ctrl = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    out = elevate_bezier(ctrl)
    assert out[0] == (0.0, 0.0)
    assert out[-1] == (2.0, 0.0)
    assert out[1][0] == pytest.approx(2.0 / 3.0)
    assert out[1][1] == pytest.approx(2.0 / 3.0)
    assert out[2][0] == pytest.approx(4.0 / 3.0)
    assert out[2][1] == pytest.approx(2.0 / 3.0)


@pytest.mark.parametrize("p", [1, 2, 3, 4, 5])
def test_elevate_preserves_geometry(p):
    rng = random.Random(6100 + p)
    ctrl = random_points(rng, p + 1, 2)
    for target in (p + 1, p + 3):
        elevated = elevate_bezier_to(ctrl, target)
        assert len(elevated) == target + 1
        for j in range(21):
            t = j / 20
            a = _bernstein_eval(ctrl, t)
            b = _bernstein_eval(elevated, t)
            assert max(abs(x - y) for x, y in zip(a, b)) < 1e-12


def test_elevate_rejects_bad_requests():
    with pytest.raises(DomainError):
        elevate_bezier([(0.0, 0.0)])
    with pytest.raises(DomainError):
        elevate_bezier_to([(0.0, 0.0), (1.0, 0.0)], 0)
    with pytest.raises(DomainError):
        elevate_bezier_to([(0.0, 0.0), (1.0, 0.0)], 1.5)


def test_elevate_nurbs_quarter_circle_stays_exact():
    ctrl = [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    weights = [1.0, 0.7071067811865476, 1.0]
    P3, W3 = elevate_bezier_nurbs(ctrl, weights, 3)
    U2 = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    U3 = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    for j in range(11):
        t = j / 10
        a = nurbs_curve_point(U2, 2, ctrl, weights, t)
        b = nurbs_curve_point(U3, 3, P3, W3, t)
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-13
        assert abs(math.hypot(*b) - 1.0) < 1e-12
