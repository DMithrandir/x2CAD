"""插值 oracle：精确恢复（同空间往返）、多项式重现（≤p 次精确）、收敛阶、
参数化性质、退化拒绝。"""

import math
import random

import pytest

from operators.curve_eval.impl import curve_point
from operators.curve_interpolation.impl import (
    averaged_knots,
    centripetal_params,
    chordal_params,
    interpolate_curve,
    uniform_params,
)
from primitives.bspline import DomainError, validate_knot_vector

from helpers import random_clamped_knots, random_points


@pytest.mark.parametrize("p,npts", [(1, 4), (2, 6), (3, 8), (4, 10), (5, 7)])
def test_exact_recovery_in_same_space(p, npts):
    """在「参数 → 平均节点」构造的空间内任取曲线，采样后插值必须恢复原控制点。"""
    rng = random.Random(12000 + p * 100 + npts)
    m = npts - 1
    # 随机严格递增参数（固定端点 0/1）
    interior = sorted(rng.uniform(0.05, 0.95) for _ in range(m - 1))
    # 去重保险：保证严格递增
    for i in range(1, len(interior)):
        if interior[i] <= interior[i - 1]:
            interior[i] = interior[i - 1] + 1e-6
    params = [0.0] + interior + [1.0]
    U = averaged_knots(params, p)
    P = random_points(rng, m + 1, 3)
    Q = [curve_point(U, p, P, u) for u in params]
    U2, P2 = interpolate_curve(Q, p, params=params)
    assert U2 == pytest.approx(U, abs=1e-15)
    for i in range(m + 1):
        assert P2[i] == pytest.approx(P[i], abs=1e-7), (p, i, P[i], P2[i])


@pytest.mark.parametrize("p", [1, 2, 3, 5])
@pytest.mark.parametrize("extra", [0, 3])
def test_polynomial_reproduction(p, extra):
    """多项式重现：在给定参数处采样 Q_i = f(ū_i)（f 为 ≤p 次多项式），
    则插值结果在全域恒等于 f（clamped 样条空间包含 Π_p + 平均节点下的 unisolvence）。"""
    rng = random.Random(13000 + p * 7 + extra)
    m = p + extra
    coeffs = [[rng.uniform(-2, 2) for _ in range(p + 1)] for _ in range(3)]

    def f(u):
        return tuple(sum(c * u**j for j, c in enumerate(row)) for row in coeffs)

    # 用均匀采样点的几何生成非均匀参数（弦长/向心），再在这些参数处采样数据
    ts = [i / m for i in range(m + 1)]
    sample = [f(t) for t in ts]
    method = rng.choice(["uniform", "chordal", "centripetal"])
    if method == "uniform":
        params = uniform_params(m)
    elif method == "chordal":
        params = chordal_params(sample)
    else:
        params = centripetal_params(sample)
    Q = [f(u) for u in params]
    U, P = interpolate_curve(Q, p, params=params)
    n = len(Q) - 1
    lo, hi = U[p], U[n + 1]
    for k in range(31):
        u = lo + (hi - lo) * k / 30
        val = curve_point(U, p, P, u)
        expect = f(u)
        assert val == pytest.approx(expect, abs=1e-7, rel=1e-7), (p, method, u, val, expect)


def test_interpolation_residual_end_to_end():
    """端到端：插值结果在数据参数处过点（用求值算子而非装配矩阵复检）。"""
    rng = random.Random(14000)
    p = 3
    m = 11
    ts = [i / m for i in range(m + 1)]
    Q = [(math.cos(2 * math.pi * t), math.sin(2 * math.pi * t), 0.3 * t) for t in ts]
    U, P = interpolate_curve(Q, p, params=ts)
    for t, q in zip(ts, Q):
        val = curve_point(U, p, P, t)
        assert val == pytest.approx(q, abs=1e-9), (t, val, q)


def test_sine_convergence():
    """三次插值对光滑函数的收敛性：误差随节点数单调下降（h^4 量级）。"""
    errs = []
    for m in (5, 9, 17, 33):
        ts = [i / m for i in range(m + 1)]
        Q = [(math.sin(2 * math.pi * t),) for t in ts]
        U, P = interpolate_curve(Q, 3, params=ts)
        worst = 0.0
        for k in range(1, 200):
            u = k / 200
            val = curve_point(U, 3, P, u)[0]
            worst = max(worst, abs(val - math.sin(2 * math.pi * u)))
        errs.append(worst)
    assert errs[0] > errs[1] > errs[2] > errs[3], errs
    assert errs[3] < 1e-4, errs


def test_parameterization_properties():
    # 共线均匀点：弦长参数化 = 均匀参数化
    pts = [((i / 4.0), 0.0) for i in range(5)]
    ch = chordal_params(pts)
    assert ch == pytest.approx(uniform_params(4), abs=1e-12)
    # 向心参数化严格递增且端点 0/1
    cp = centripetal_params([(-1.0, 0.0), (0.0, 0.0), (0.1, 0.05), (1.0, 0.0)])
    assert cp[0] == 0.0 and cp[-1] == 1.0
    assert all(cp[i + 1] > cp[i] for i in range(len(cp) - 1))
    # 重复数据点被显式拒绝（S 族退化：零长度段）
    with pytest.raises(DomainError):
        chordal_params([(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)])
    with pytest.raises(DomainError):
        centripetal_params([(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)])


def test_averaged_knots_structure():
    params = [0.0, 0.12, 0.3, 0.47, 0.61, 0.8, 1.0]
    p = 3
    U = averaged_knots(params, p)
    assert len(U) == len(params) + p + 1
    assert U[: p + 1] == [0.0] * (p + 1)
    assert U[-(p + 1) :] == [1.0] * (p + 1)
    assert all(U[i] <= U[i + 1] for i in range(len(U) - 1))
    validate_knot_vector(U, p, len(params) - 1)
    with pytest.raises(DomainError):
        averaged_knots([0.0, 0.5, 0.5, 1.0], 2)  # 非严格递增
    with pytest.raises(DomainError):
        averaged_knots([0.0, 1.0], 2)  # 数据点不足


def test_interpolation_domain_errors():
    pts3 = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.5)]
    with pytest.raises(DomainError):
        interpolate_curve(pts3, 0)  # p < 1
    with pytest.raises(DomainError):
        interpolate_curve(pts3, 3)  # 点数 < p+1
    with pytest.raises(DomainError):
        interpolate_curve(pts3, 1, params=[0.0, 0.5])  # 参数数量不符
    with pytest.raises(DomainError):
        interpolate_curve(pts3, 1, params=[0.0, 0.5, 0.5])  # 非严格递增
    with pytest.raises(DomainError):
        interpolate_curve([(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)], 1)  # 弦长退化（默认 chordal）
