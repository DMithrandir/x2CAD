"""算子：全局 B 样条曲线插值（NURBS Book A9.1 路线）。

给定 m+1 个数据点 Q_i、次数 p 与参数化方法：

1. 参数化：uniform / chordal（弦长）/ centripetal（向心）；
2. 节点向量：de Boor 平均（式 9.8）：U[p+j] = (1/p) Σ_{i=j}^{j+p-1} ū_i；
3. 解线性系统 A P = Q，A[i][j] = N_{j,p}(ū_i)（带状、全正，部分主元消元）；
4. 后置不变量：max_i |C(ū_i) - Q_i| ≤ 1e-8，超出即抛错（不静默产出坏插值）。

退化语义（对应退化知识库 S 族/N 族）：
- 相邻重复数据点（弦长/向心参数化零增量）→ DomainError（显式拒绝，不静默扰动）；
- 奇异/病态系统 → DomainError（由 linalg 主元判据触发）。
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from primitives.bspline import (
    DomainError,
    basis_functions,
    find_span,
    validate_knot_vector,
)
from primitives.linalg import solve_dense

__all__ = [
    "uniform_params",
    "chordal_params",
    "centripetal_params",
    "averaged_knots",
    "interpolate_curve",
]

Point = Sequence[float]


def _params_from_dist(points: Sequence[Point], power: float) -> List[float]:
    m = len(points) - 1
    dists = []
    for i in range(m):
        s = 0.0
        for d in range(len(points[0])):
            diff = points[i + 1][d] - points[i][d]
            s += diff * diff
        dist = math.sqrt(s) ** power
        if dist <= 0.0:
            raise DomainError(
                f"第 {i}→{i + 1} 段长度为零：重复数据点无法参数化（需显式去重或改用给定参数）"
            )
        dists.append(dist)
    total = sum(dists)
    if not (total > 0.0) or not math.isfinite(total):
        raise DomainError("参数化总长度退化")
    params = [0.0]
    for dist in dists:
        params.append(params[-1] + dist / total)
    params[-1] = 1.0  # 消除累入误差
    return params


def uniform_params(m: int) -> List[float]:
    """均匀参数化：m+1 个点，ū_i = i/m。"""
    if m < 1:
        raise DomainError("至少需要两个数据点")
    return [i / m for i in range(m + 1)]


def chordal_params(points: Sequence[Point]) -> List[float]:
    """弦长参数化（power=1）。"""
    return _params_from_dist(points, 1.0)


def centripetal_params(points: Sequence[Point]) -> List[float]:
    """向心参数化（power=0.5）。"""
    return _params_from_dist(points, 0.5)


def averaged_knots(params: Sequence[float], p: int) -> List[float]:
    """de Boor 节点平均（式 9.8）。前置：params 严格递增，len(params) ≥ p+1。"""
    m = len(params) - 1
    if m < p:
        raise DomainError(f"数据点数 {m + 1} 必须至少为 p+1={p + 1}")
    for i in range(m):
        if not (params[i + 1] > params[i]):
            raise DomainError(f"参数必须严格递增：ū[{i}]={params[i]!r} ≥ ū[{i + 1}]={params[i + 1]!r}")
    U: List[float] = [params[0]] * (p + 1)
    for j in range(1, m - p + 1):
        U.append(sum(params[j : j + p]) / p)
    U.extend([params[-1]] * (p + 1))
    return U


def _validate_points(points: Sequence[Point]) -> Tuple[int, int]:
    if len(points) < 2:
        raise DomainError("至少需要两个数据点")
    dim = len(points[0])
    if dim == 0 or any(len(q) != dim for q in points):
        raise DomainError(f"数据点必须同维，首点维度 {dim}")
    return len(points) - 1, dim


def interpolate_curve(
    points: Sequence[Point],
    p: int,
    params: Optional[Sequence[float]] = None,
    param_method: str = "chordal",
) -> Tuple[List[float], List[Tuple[float, ...]]]:
    """全局曲线插值：返回 (knots, ctrl)。

    ``params`` 给定时按给定参数插值（严格递增、覆盖 [0,1] 端点语义由调用方负责）；
    否则按 ``param_method`` ∈ {uniform, chordal, centripetal} 计算。
    """
    m, dim = _validate_points(points)
    if p < 1:
        raise DomainError(f"次数 p 必须 ≥ 1，收到 {p}")
    if m < p:
        raise DomainError(f"数据点数 {m + 1} 不足：全局插值需要 ≥ p+1={p + 1}")

    if params is None:
        if param_method == "uniform":
            params = uniform_params(m)
        elif param_method == "chordal":
            params = chordal_params(points)
        elif param_method == "centripetal":
            params = centripetal_params(points)
        else:
            raise DomainError(f"未知参数化方法 {param_method!r}")
    else:
        if len(params) != m + 1:
            raise DomainError(f"参数数量应为 {m + 1}，收到 {len(params)}")
        for i in range(m):
            if not (params[i + 1] > params[i]):
                raise DomainError(f"参数必须严格递增：ū[{i}]={params[i]!r} ≥ ū[{i + 1}]={params[i + 1]!r}")

    U = averaged_knots(params, p)
    n = m  # 控制点数与数据点数相同

    # 装配矩阵 A[i][j] = N_{j,p}(ū_i)（行稀疏：仅 span 窗口 p+1 个非零）
    A: List[List[float]] = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i, ub in enumerate(params):
        span = find_span(n, p, ub, U)
        for r, N in enumerate(basis_functions(span, ub, p, U)):
            A[i][span - p + r] = N

    # 逐维求解（同一矩阵）
    cols = [
        solve_dense(A, [points[i][d] for i in range(m + 1)])
        for d in range(dim)
    ]
    ctrl = [tuple(cols[d][i] for d in range(dim)) for i in range(n + 1)]

    # 后置不变量：插值残差（用装配好的同一矩阵检查解，端到端求值检查在测试层）
    worst = 0.0
    for i in range(m + 1):
        for d in range(dim):
            s = sum(A[i][j] * cols[d][j] for j in range(n + 1))
            worst = max(worst, abs(s - points[i][d]))
    if worst > 1e-8:
        raise DomainError(f"插值残差 {worst:.3e} 超过 1e-8：系统病态或实现错误")

    # 产物自洽：所得 (U, ctrl) 必须是合法 B 样条
    validate_knot_vector(U, p, n)
    return U, ctrl
