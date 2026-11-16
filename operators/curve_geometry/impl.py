"""算子：曲线微分几何量——弧长、单位切矢、曲率（B 样条 + NURBS）。

定义
----
- 弧长：``s = ∫_{u0}^{u1} |C'(u)| du``，按节点区间分段后用 Gauss–Legendre 求积；
- 单位切矢：``T = C' / |C'|``；
- 曲率：``κ = |C' × C''| / |C'|³``（三维叉积；二维取叉积标量 ``x'y'' − y'x''`` 的绝对值）。

前置与退化
----------
- 弧长对 p ≥ 1 有定义；曲率需要二阶导，要求 p ≥ 2（p=1 的直线段曲率恒为 0，
  但"恒为 0"是几何事实而非可计算的量，显式拒绝比返回 0 更诚实）；
- ``|C'| = 0``（尖点/重节点）→ ``DomainError``：切矢与曲率在奇点无定义；
- 维度只支持 2D/3D（叉积只在 2D/3D 有意义）。

依赖声明
--------
本算子调用 ``operators.curve_eval`` 的**公共**求导入口（不复制其实现，不 import 私有符号），
依赖关系在 spec.depends_on 中声明，由静态检查器 SC006 强制。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from operators.curve_eval.impl import curve_derivatives, nurbs_curve_derivatives
from primitives.bspline import DomainError, validate_knot_vector
from primitives.quadrature import integrate_adaptive

__all__ = [
    "arc_length",
    "nurbs_arc_length",
    "speed",
    "unit_tangent",
    "nurbs_unit_tangent",
    "curvature",
    "nurbs_curvature",
]

Point = Sequence[float]


def _domain(U: Sequence[float], p: int, ctrl: Sequence[Point]) -> Tuple[int, float, float]:
    n = len(ctrl) - 1
    validate_knot_vector(U, p, n)
    return n, U[p], U[n + 1]


def _check_interval(u0: float, u1: float, lo: float, hi: float) -> None:
    for u in (u0, u1):
        if not math.isfinite(u) or u < lo or u > hi:
            raise DomainError(f"积分端点 {u!r} 必须在参数域 [{lo!r}, {hi!r}] 内")
    if not (u1 > u0):
        raise DomainError(f"积分区间必须非退化：u0={u0!r} >= u1={u1!r}")


def speed(U: Sequence[float], p: int, ctrl: Sequence[Point], u: float) -> float:
    """|C'(u)|。"""
    d = curve_derivatives(U, p, ctrl, u, 1)[1]
    return math.hypot(*d)


def _breaks(U: Sequence[float], lo: float, hi: float) -> List[float]:
    """区间 [lo,hi] 上的积分断点：端点 + 落在内部的节点（跨节点处 |C'| 只到 C^{p-1}）。"""
    return sorted({lo, hi} | {x for x in U if lo < x < hi})


def arc_length(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    u0: float | None = None,
    u1: float | None = None,
    *,
    rel_tol: float = 1e-12,
    max_depth: int = 24,
) -> float:
    """B 样条曲线弧长（默认整条曲线），按节点断点分段后自适应 Gauss 求积。"""
    _n, lo, hi = _domain(U, p, ctrl)
    u0 = lo if u0 is None else u0
    u1 = hi if u1 is None else u1
    _check_interval(u0, u1, lo, hi)
    total = 0.0
    breaks = _breaks(U, u0, u1)
    for a, b in zip(breaks, breaks[1:]):
        total += integrate_adaptive(
            lambda t: speed(U, p, ctrl, t), a, b, rel_tol=rel_tol, max_depth=max_depth
        )
    return total


def nurbs_arc_length(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    weights: Sequence[float],
    u0: float | None = None,
    u1: float | None = None,
    *,
    rel_tol: float = 1e-12,
    max_depth: int = 24,
) -> float:
    """NURBS 曲线弧长：被积函数用齐次导矢投影后的速度。"""
    n, lo, hi = _domain(U, p, ctrl)
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(not (w > 0.0) or not math.isfinite(w) for w in weights):
        raise DomainError("NURBS 权重必须全为正的有限数")
    u0 = lo if u0 is None else u0
    u1 = hi if u1 is None else u1
    _check_interval(u0, u1, lo, hi)

    def _speed(t: float) -> float:
        d = nurbs_curve_derivatives(U, p, ctrl, weights, t, 1)[1]
        return math.hypot(*d)

    total = 0.0
    breaks = _breaks(U, u0, u1)
    for a, b in zip(breaks, breaks[1:]):
        total += integrate_adaptive(_speed, a, b, rel_tol=rel_tol, max_depth=max_depth)
    return total


def _check_weights(ctrl: Sequence[Point], weights: Sequence[float]) -> None:
    n = len(ctrl) - 1
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(not (w > 0.0) or not math.isfinite(w) for w in weights):
        raise DomainError("NURBS 权重必须全为正的有限数")


def unit_tangent(U: Sequence[float], p: int, ctrl: Sequence[Point], u: float) -> Tuple[float, ...]:
    """单位切矢 T(u)；|C'|=0 时 DomainError（奇点无切向）。"""
    d = curve_derivatives(U, p, ctrl, u, 1)[1]
    norm = math.hypot(*d)
    if not norm > 0.0:
        raise DomainError(f"u={u!r} 处 |C'|=0：切矢无定义（尖点/重节点）")
    return tuple(c / norm for c in d)


def nurbs_unit_tangent(
    U: Sequence[float], p: int, ctrl: Sequence[Point], weights: Sequence[float], u: float
) -> Tuple[float, ...]:
    """NURBS 单位切矢（齐次投影后的真实切矢）。"""
    _check_weights(ctrl, weights)
    d = nurbs_curve_derivatives(U, p, ctrl, weights, u, 1)[1]
    norm = math.hypot(*d)
    if not norm > 0.0:
        raise DomainError(f"u={u!r} 处 |C'|=0：切矢无定义")
    return tuple(c / norm for c in d)


def _curvature_from_derivatives(d1: Sequence[float], d2: Sequence[float], u: float) -> float:
    dim = len(d1)
    speed_sq = sum(c * c for c in d1)
    if not speed_sq > 0.0:
        raise DomainError(f"u={u!r} 处 |C'|=0：曲率无定义")
    if dim == 2:
        num = abs(d1[0] * d2[1] - d1[1] * d2[0])
    elif dim == 3:
        cx = d1[1] * d2[2] - d1[2] * d2[1]
        cy = d1[2] * d2[0] - d1[0] * d2[2]
        cz = d1[0] * d2[1] - d1[1] * d2[0]
        num = math.sqrt(cx * cx + cy * cy + cz * cz)
    else:
        raise DomainError(f"曲率只支持 2D/3D，收到 {dim}D")
    return num / (speed_sq ** 1.5)


def curvature(U: Sequence[float], p: int, ctrl: Sequence[Point], u: float) -> float:
    """B 样条曲率 κ(u)。二维/三维；p ≥ 2；|C'|=0 → DomainError。"""
    if p < 2:
        raise DomainError(f"曲率需要二阶导，p 必须 ≥ 2，收到 p={p}")
    ders = curve_derivatives(U, p, ctrl, u, 2)
    return _curvature_from_derivatives(ders[1], ders[2], u)


def nurbs_curvature(
    U: Sequence[float], p: int, ctrl: Sequence[Point], weights: Sequence[float], u: float
) -> float:
    """NURBS 曲率 κ(u)（齐次投影后的真实曲率）。"""
    if p < 2:
        raise DomainError(f"曲率需要二阶导，p 必须 ≥ 2，收到 p={p}")
    _check_weights(ctrl, weights)
    ders = nurbs_curve_derivatives(U, p, ctrl, weights, u, 2)
    return _curvature_from_derivatives(ders[1], ders[2], u)
