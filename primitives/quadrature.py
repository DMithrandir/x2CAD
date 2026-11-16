"""数值积分基元：Gauss–Legendre 求积节点/权重（Newton 迭代生成，非查表常数）。

为什么放在 primitives
---------------------
弧长、面积、体积这类几何量最终都是积分。积分器的精度性质是纯数学事实（n 点
Gauss–Legendre 对次数 ≤ 2n−1 的多项式精确），与具体几何算子无关，因此属于数值基元层。

实现用标准 Newton 迭代求 Legendre 多项式 P_n 的根（初始猜测 cos(π(i−1/4)/(n+1/2))），
不依赖 numpy/scipy。节点升序返回，权重对称：w_i = w_{n-1-i}。
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable, List, Tuple

from primitives.bspline import DomainError

__all__ = ["gauss_legendre", "integrate", "integrate_adaptive"]


@lru_cache(maxsize=None)
def gauss_legendre(n: int) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """[-1,1] 上的 n 点 Gauss–Legendre 节点与权重（升序）。"""
    if not isinstance(n, int) or n < 1:
        raise DomainError(f"求积点数必须是正整数，收到 {n!r}")
    nodes: List[float] = []
    weights: List[float] = []
    for i in range(1, n + 1):
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        pp = 0.0
        for _ in range(100):
            p1, p2 = 1.0, 0.0
            for j in range(1, n + 1):
                p3 = p2
                p2 = p1
                p1 = ((2.0 * j - 1.0) * x * p2 - (j - 1.0) * p3) / j
            pp = n * (x * p1 - p2) / (x * x - 1.0)
            dx = p1 / pp
            x -= dx
            if abs(dx) <= 1e-16:
                break
        if not math.isfinite(x) or pp == 0.0:
            raise DomainError(f"Legendre 根求解失败（n={n}, i={i}）")
        nodes.append(x)
        weights.append(2.0 / ((1.0 - x * x) * pp * pp))
    order = sorted(range(n), key=lambda k: nodes[k])
    return tuple(nodes[k] for k in order), tuple(weights[k] for k in order)


def integrate(f: Callable[[float], float], a: float, b: float, n: int = 8) -> float:
    """用 n 点 Gauss–Legendre 在 [a,b] 上积分标量函数 f。

    对次数 ≤ 2n−1 的多项式精确；光滑函数误差随 n 指数下降。
    """
    if not (math.isfinite(a) and math.isfinite(b)):
        raise DomainError(f"积分区间端点必须有限，收到 [{a!r}, {b!r}]")
    if a == b:
        return 0.0
    if b < a:
        return -integrate(f, b, a, n)
    nodes, weights = gauss_legendre(n)
    half = 0.5 * (b - a)
    mid = 0.5 * (a + b)
    return half * sum(w * f(mid + half * x) for x, w in zip(nodes, weights))


def integrate_adaptive(
    f: Callable[[float], float],
    a: float,
    b: float,
    *,
    rel_tol: float = 1e-12,
    abs_tol: float = 0.0,
    max_depth: int = 20,
    n: int = 8,
) -> float:
    """自适应 Gauss–Legendre：递归二分，直到上下估计差落在容差内。

    为什么需要它：被积函数即使光滑，也可能在实轴附近有复奇点（例如 ``sqrt(二次式)``
    在极小值附近），固定面板的收敛率会意外地慢。弧长积分的被积函数 ``|C'|`` 正是
    这种形状——速度接近零时，8 点 Gauss 在固定面板上可能只给到 1e-5 相对精度。
    自适应二分把误差压到容差内，且二分点在参数上确定性生成（可重放）。
    """
    if not (math.isfinite(a) and math.isfinite(b)):
        raise DomainError(f"积分区间端点必须有限，收到 [{a!r}, {b!r}]")
    if b == a:
        return 0.0
    if b < a:
        return -integrate_adaptive(
            f, b, a, rel_tol=rel_tol, abs_tol=abs_tol, max_depth=max_depth, n=n
        )
    if rel_tol < 0.0 or abs_tol < 0.0 or max_depth < 0:
        raise DomainError("容差与递归深度必须非负")

    def recurse(lo: float, hi: float, depth: int) -> float:
        whole = integrate(f, lo, hi, n)
        mid = 0.5 * (lo + hi)
        left = integrate(f, lo, mid, n)
        right = integrate(f, mid, hi, n)
        refined = left + right
        tol = abs_tol + rel_tol * abs(refined)
        if depth <= 0 or abs(refined - whole) <= tol:
            return refined
        return recurse(lo, mid, depth - 1) + recurse(mid, hi, depth - 1)

    return recurse(a, b, max_depth)
