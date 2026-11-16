"""张量积曲面 oracle：Bézier 片闭式、双线性片、偏导有限差分、曲线-曲面一致性。"""

import random
from math import comb

import pytest

from operators.curve_eval.impl import curve_point
from operators.surface_eval.impl import surface_derivatives, surface_point
from primitives.bspline import DomainError

from helpers import random_clamped_knots


def bernstein(p, t):
    return [comb(p, i) * t**i * (1.0 - t) ** (p - i) for i in range(p + 1)]


def bezier_net(rng, pu, pv):
    return [
        [tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(pv + 1)]
        for _ in range(pu + 1)
    ]


@pytest.mark.parametrize("pu,pv", [(1, 1), (2, 2), (2, 3), (3, 2)])
def test_bezier_patch_closed_forms(pu, pv):
    rng = random.Random(15000 + pu * 10 + pv)
    U = [0.0] * (pu + 1) + [1.0] * (pu + 1)
    V = [0.0] * (pv + 1) + [1.0] * (pv + 1)
    net = bezier_net(rng, pu, pv)
    for uu in [0.0, 0.13, 0.4, 0.77, 1.0]:
        for vv in [0.0, 0.21, 0.5, 0.88, 1.0]:
            S = surface_point(U, V, pu, pv, net, uu, vv)
            Bu, Bv = bernstein(pu, uu), bernstein(pv, vv)
            expect = [0.0, 0.0, 0.0]
            for i in range(pu + 1):
                for j in range(pv + 1):
                    w = Bu[i] * Bv[j]
                    for d in range(3):
                        expect[d] += w * net[i][j][d]
            assert S == pytest.approx(expect, abs=1e-11), (uu, vv)
    # 角点插值
    assert surface_point(U, V, pu, pv, net, 0.0, 0.0) == pytest.approx(net[0][0], abs=1e-12)
    assert surface_point(U, V, pu, pv, net, 1.0, 1.0) == pytest.approx(net[pu][pv], abs=1e-12)


def test_bilinear_patch_exact():
    P00, P10, P01, P11 = (0.0, 0.0, 0.0), (2.0, 0.0, 1.0), (0.0, 3.0, -1.0), (2.0, 3.0, 0.5)
    net = [[P00, P01], [P10, P11]]
    U = V = [0.0, 0.0, 1.0, 1.0]
    for uu in [0.1, 0.35, 0.6, 0.9]:
        for vv in [0.2, 0.45, 0.8]:
            S = surface_point(U, V, 1, 1, net, uu, vv)
            expect = [
                (1 - uu) * (1 - vv) * P00[d] + uu * (1 - vv) * P10[d]
                + (1 - uu) * vv * P01[d] + uu * vv * P11[d]
                for d in range(3)
            ]
            assert S == pytest.approx(expect, abs=1e-12)
    # 双线性片的二阶混合偏导 = 常向量（有限差分校验过的解析结构）
    ders = surface_derivatives(U, V, 1, 1, net, 0.3, 0.7, 1, 1)
    expect_uv = [P11[d] - P10[d] - P01[d] + P00[d] for d in range(3)]
    assert ders[1][1] == pytest.approx(expect_uv, abs=1e-12)


@pytest.mark.parametrize("pu,pv", [(2, 3), (3, 2)])
def test_surface_derivatives_vs_finite_difference(pu, pv):
    rng = random.Random(16000 + pu * 10 + pv)
    U = random_clamped_knots(rng, pu, 4, 40)
    V = random_clamped_knots(rng, pv, 3, 40)
    nu, nv = pu + 4, pv + 3
    net = [
        [tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(nv + 1)]
        for _ in range(nu + 1)
    ]
    for _ in range(12):
        u = rng.uniform(U[pu] + 0.03, U[nu + 1] - 0.03)
        v = rng.uniform(V[pv] + 0.03, V[nv + 1] - 0.03)
        ders = surface_derivatives(U, V, pu, pv, net, u, v, 1, 1)
        h = 1e-6
        Su_p = surface_point(U, V, pu, pv, net, u + h, v)
        Su_m = surface_point(U, V, pu, pv, net, u - h, v)
        Sv_p = surface_point(U, V, pu, pv, net, u, v + h)
        Sv_m = surface_point(U, V, pu, pv, net, u, v - h)
        for d in range(3):
            fdu = (Su_p[d] - Su_m[d]) / (2 * h)
            fdv = (Sv_p[d] - Sv_m[d]) / (2 * h)
            assert abs(ders[1][0][d] - fdu) < 3e-4 * (1.0 + abs(ders[1][0][d])), (u, v, d)
            assert abs(ders[0][1][d] - fdv) < 3e-4 * (1.0 + abs(ders[0][1][d])), (u, v, d)
        # 混合偏导 S_uv 用二维差分
        h2 = 1e-4
        a = surface_point(U, V, pu, pv, net, u + h2, v + h2)
        b = surface_point(U, V, pu, pv, net, u + h2, v - h2)
        c = surface_point(U, V, pu, pv, net, u - h2, v + h2)
        e = surface_point(U, V, pu, pv, net, u - h2, v - h2)
        for d in range(3):
            fduv = (a[d] - b[d] - c[d] + e[d]) / (4 * h2 * h2)
            assert abs(ders[1][1][d] - fduv) < 5e-2 * (1.0 + abs(ders[1][1][d])), (u, v, d)


def test_surface_curve_consistency():
    """固定 v0，u ↦ S(u, v0) 应等于以 Σ_j N_j(v0)P_{i,j} 为控制点的 B 样条曲线。"""
    from primitives.bspline import basis_functions, find_span

    rng = random.Random(17000)
    pu, pv = 3, 2
    U = random_clamped_knots(rng, pu, 4, 40)
    V = random_clamped_knots(rng, pv, 3, 40)
    nu, nv = pu + 4, pv + 3
    net = [
        [tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(nv + 1)]
        for _ in range(nu + 1)
    ]
    v0 = 0.44
    sv = find_span(nv, pv, v0, V)
    Nv = basis_functions(sv, v0, pv, V)
    ctrl = [
        tuple(sum(Nv[b] * net[i][sv - pv + b][d] for b in range(pv + 1)) for d in range(3))
        for i in range(nu + 1)
    ]
    for u in [0.05, 0.23, 0.51, 0.84]:
        u = U[pu] + u * (U[nu + 1] - U[pu])
        S = surface_point(U, V, pu, pv, net, u, v0)
        C = curve_point(U, pu, ctrl, u)
        assert S == pytest.approx(C, abs=1e-10)


def test_invalid_net_rejected():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]  # p=2 → nu=3（4 行）
    V = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]  # p=2 → nv=2（3 列）
    net = [[(0.0, 0.0, 0.0)] * 4 for _ in range(4)]  # 4x4：列数不符 → 拒绝
    with pytest.raises(DomainError):
        surface_point(U, V, 2, 2, net, 0.3, 0.3)
