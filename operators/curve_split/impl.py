"""算子：B 样条 / NURBS 曲线在参数 u 处分割为两段。

数学定义
--------
把 u 处的重数补到 p（调用 ``knot_insertion``），曲线在 u 处降为 C^0；此时控制点序列
在某个下标 L 处分成两段，两段各自是 clamped 的 p 次 B 样条，参数域分别为
[U0[p], u] 与 [u, U0'[n'+1]]。分割点是**共享的**：左段末控制点 = 右段首控制点 = C(u)。

下标推导（见 tests/test_knot_ops.py 的解析例）::

    block_start = k - s + 1
    block_end   = k + r            # r = p - s
    L           = block_end + 1 - p
    left  = (U'[0 .. block_end]  ⊕ [u],  Q[0 .. L-1])
    right = ([u] ⊕ U'[block_start ..],    Q[L-1 ..])

其中 k 是插入前 u 所在 span（``find_span``）。分割后两段节点向量都必须是合法 clamped
向量——这是算子的后置不变量，由 ``validate_knot_vector`` 当场检查。

退化语义
--------
- u 在参数域外、或恰为端点 → ``DomainError``（端点分割无几何意义）；
- 曲线的非有理/有理形式各有一个入口；NURBS 版本在齐次坐标里做同样的操作。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from operators.knot_insertion.impl import insert_knot, knot_multiplicity
from primitives.bspline import DomainError, find_span, validate_knot_vector

__all__ = ["split_curve", "split_curve_nurbs"]

Point = Sequence[float]
Curve = Tuple[List[float], List[Tuple[float, ...]]]


def _split(
    U: Sequence[float], p: int, ctrl: Sequence[Point], u: float
) -> Tuple[Curve, Curve]:
    n = len(ctrl) - 1
    validate_knot_vector(U, p, n)
    if not math.isfinite(u):
        raise DomainError(f"分割参数必须有限，收到 {u!r}")
    lo, hi = U[p], U[n + 1]
    if not (lo < u < hi):
        raise DomainError(f"分割参数 u={u!r} 必须在开区间 ({lo!r}, {hi!r}) 内：端点分割无意义")

    s = knot_multiplicity(U, u)
    k = find_span(n, p, u, U)
    r = p - s
    U2, Q = insert_knot(U, p, ctrl, u, r) if r > 0 else (list(U), [tuple(q) for q in ctrl])

    block_start = k - s + 1
    block_end = k + r
    left_count = block_end + 1 - p

    left_u = list(U2[: block_end + 1]) + [u]
    left_p = Q[:left_count]
    right_u = [u] + list(U2[block_start:])
    right_p = Q[left_count - 1 :]

    # 后置不变量：两段都必须是合法 clamped 向量
    validate_knot_vector(left_u, p, len(left_p) - 1)
    validate_knot_vector(right_u, p, len(right_p) - 1)
    if left_p[-1] != right_p[0]:
        raise DomainError("分割内部错误：共享端点控制点不一致")
    return (left_u, left_p), (right_u, right_p)


def split_curve(
    U: Sequence[float], p: int, ctrl: Sequence[Point], u: float
) -> Tuple[Curve, Curve]:
    """B 样条曲线分割，返回 ((U_left, P_left), (U_right, P_right))。"""
    return _split(U, p, ctrl, u)


def split_curve_nurbs(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    weights: Sequence[float],
    u: float,
) -> Tuple[Tuple[List[float], List[Tuple[float, ...]], List[float]], Tuple[List[float], List[Tuple[float, ...]], List[float]]]:
    """NURBS 曲线分割：齐次坐标下分割，再逐段投影回仿射空间。"""
    n = len(ctrl) - 1
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(not (w > 0.0) or not math.isfinite(w) for w in weights):
        raise DomainError("NURBS 权重必须全为正的有限数")
    dim = len(ctrl[0])
    homogeneous = [[weights[i] * ctrl[i][d] for d in range(dim)] + [weights[i]] for i in range(n + 1)]
    (Ul, Ql), (Ur, Qr) = _split(U, p, homogeneous, u)

    def dehomogenize(U_: List[float], Q_: List[Tuple[float, ...]]):
        P: List[Tuple[float, ...]] = []
        W: List[float] = []
        for q in Q_:
            w = q[-1]
            if not w > 0.0:
                raise DomainError("分割后齐次权重非正：实现错误")
            P.append(tuple(c / w for c in q[:-1]))
            W.append(w)
        return U_, P, W

    return dehomogenize(Ul, Ql), dehomogenize(Ur, Qr)
