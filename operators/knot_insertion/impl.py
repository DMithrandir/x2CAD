"""算子：Boehm 节点插入（单次插入 + 重复插入到目标重数）。

数学定义
--------
在参数 u 处插入一个节点不改变曲线几何，只增加一段控制点与一个节点（NURBS Book A5.1）。
设 p 次、节点向量 U、控制点 P，u ∈ [U[k], U[k+1])，u 的现有重数为 s，插入 r 个：

::

    Q_i = P_i                                   i = 0 .. k-p
    Q_i = α_i P_i + (1-α_i) P_{i-1}             i = k-p+1 .. k-s
        α_i = (u - U_i) / (U_{i+p} - U_i)
    Q_{i+r} = P_i                               i = k-s .. n
    U' = U[0..k] ⊕ [u]^r ⊕ U[k+1..m]

**公式中的分母是 U_{i+p} − U_i（不是 U_{i+p+1} − U_i）**。这一细节是最容易抄错的地方，
本仓库用几何不变性 oracle 裁决（tests/test_knot_ops.py 的 `test_hand_example_p1` 是
p=1 的解析反例：错误分母给出 1.25，正确几何值是 1.5）。

重复插入按 r 次单次插入实现（Boehm 插入可结合），避免一次性公式在多重重数下的边界推导。

NURBS
-----
在齐次坐标 (w·x, w) 上做同样的插入，再投影回仿射空间：有理曲线在齐次空间是多项式曲线，
插入公式逐字适用。权重保持在正权重凸组合内（α ∈ (0,1)），无需额外规范化。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from primitives.bspline import DomainError, find_span, validate_knot_vector

__all__ = ["knot_multiplicity", "insert_knot", "insert_knot_nurbs"]

Point = Sequence[float]


def knot_multiplicity(U: Sequence[float], u: float) -> int:
    """u 在节点向量中的重数（精确相等计数；节点向量里的值就是定义值）。"""
    return sum(1 for x in U if x == u)


def _insert_once(U: Sequence[float], p: int, ctrl: Sequence[Point], u: float):
    n = len(ctrl) - 1
    dim = len(ctrl[0])
    s = knot_multiplicity(U, u)
    k = find_span(n, p, u, U)
    U_new: List[float] = list(U[: k + 1]) + [u] + list(U[k + 1 :])

    Q: List[object] = [None] * (n + 2)
    for i in range(0, k - p + 1):
        Q[i] = tuple(ctrl[i])
    for i in range(k - s, n + 1):
        Q[i + 1] = tuple(ctrl[i])
    for i in range(k - p + 1, k - s + 1):
        den = U[i + p] - U[i]
        if not den > 0.0:
            raise DomainError(
                f"插入公式分母 U[{i + p}]-U[{i}]={den!r} 非正：节点向量或 u 不满足插入前提"
            )
        alpha = (u - U[i]) / den
        Q[i] = tuple(alpha * ctrl[i][d] + (1.0 - alpha) * ctrl[i - 1][d] for d in range(dim))

    if any(q is None for q in Q):  # 算法覆盖性自检：任何 None 都是实现错误，不是输入错误
        raise DomainError("节点插入内部错误：控制点未被算法覆盖")
    return U_new, [tuple(q) for q in Q]  # type: ignore[arg-type]


def insert_knot(
    U: Sequence[float], p: int, ctrl: Sequence[Point], u: float, r: int = 1
) -> Tuple[List[float], List[Tuple[float, ...]]]:
    """在 u 处插入 r 个节点，返回 (U_new, ctrl_new)；几何严格不变。

    退化语义：
    - ``r + s > p`` → ``DomainError``（重数超过次数，C^{-1} 不再是有意义的曲线）；
    - u 在参数域外、``r < 0``、``NaN`` → ``DomainError``；
    - ``r = 0`` 返回输入的拷贝（无副作用）。
    """
    if not math.isfinite(u):
        raise DomainError(f"插入参数必须有限，收到 {u!r}")
    if not isinstance(r, int) or r < 0:
        raise DomainError(f"插入次数 r 必须是非负整数，收到 {r!r}")
    n = len(ctrl) - 1
    validate_knot_vector(U, p, n)
    if u < U[p] or u > U[n + 1]:
        raise DomainError(f"插入参数 u={u!r} 超出参数域 [{U[p]!r}, {U[n + 1]!r}]")
    s = knot_multiplicity(U, u)
    if r + s > p:
        raise DomainError(f"插入后重数 r+s={r + s} 超过次数 p={p}：拒绝产生不连续曲线")
    if r == 0:
        return list(U), [tuple(q) for q in ctrl]

    U_cur: List[float] = list(U)
    P_cur: List[Tuple[float, ...]] = [tuple(q) for q in ctrl]
    for _ in range(r):
        U_cur, P_cur = _insert_once(U_cur, p, P_cur, u)
    validate_knot_vector(U_cur, p, len(P_cur) - 1)
    return U_cur, P_cur


def insert_knot_nurbs(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    weights: Sequence[float],
    u: float,
    r: int = 1,
) -> Tuple[List[float], List[Tuple[float, ...]], List[float]]:
    """NURBS 曲线节点插入：齐次坐标里插入，再投影回仿射空间。"""
    n = len(ctrl) - 1
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(not (w > 0.0) or not math.isfinite(w) for w in weights):
        raise DomainError("NURBS 权重必须全为正的有限数")
    dim = len(ctrl[0])
    homogeneous = [[weights[i] * ctrl[i][d] for d in range(dim)] + [weights[i]] for i in range(n + 1)]
    U_new, Q = insert_knot(U, p, homogeneous, u, r)
    ctrl_new: List[Tuple[float, ...]] = []
    weights_new: List[float] = []
    for q in Q:
        w = q[-1]
        if not w > 0.0:
            raise DomainError("插入后齐次权重非正：实现错误")
        ctrl_new.append(tuple(c / w for c in q[:-1]))
        weights_new.append(w)
    return U_new, ctrl_new, weights_new
