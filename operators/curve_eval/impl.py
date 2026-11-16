"""算子：B 样条 / NURBS 曲线求值与各阶导数。

模板四段结构（设计文档 §4.3）中的执行核。求导提供两条独立路线：

- ``curve_derivatives``：基函数导数直接加权（方法 A，通用）；
- ``curve_derivatives_by_differencing``：控制点逐阶差分 + 逐层修剪节点向量
  （方法 B，A3.3 同构）。方法 B 要求曲线真有 k 阶导（内部节点重数 ≤ p-k），
  两侧在测试中对拍。

NURBS 采用齐次坐标求值 + Leibniz 展开投影（A^{(k)} = Σ_j C(k,j) C^{(j)} w^{(k-j)}
反解 C^{(k)}），与有限差分 / 圆不变量对拍。
"""

from __future__ import annotations

from math import comb
from typing import List, Sequence, Tuple

from primitives.bspline import (
    DomainError,
    basis_function_ders,
    basis_functions,
    find_span,
    validate_knot_vector,
)

__all__ = [
    "curve_point",
    "curve_derivatives",
    "curve_derivatives_by_differencing",
    "nurbs_curve_point",
    "nurbs_curve_derivatives",
]

Point = Sequence[float]


def _check_ctrl(ctrl: Sequence[Point]) -> Tuple[int, int]:
    """控制点列表同维性校验，返回 (n, dim)。"""
    if len(ctrl) == 0:
        raise DomainError("控制点列表为空")
    dim = len(ctrl[0])
    if dim == 0 or any(len(q) != dim for q in ctrl):
        raise DomainError(f"控制点必须同维，首点维度 {dim}")
    return len(ctrl) - 1, dim


def curve_point(U: Sequence[float], p: int, ctrl: Sequence[Point], u: float) -> Tuple[float, ...]:
    """B 样条曲线求值 C(u) = Σ_i N_{i,p}(u) P_i。"""
    n, dim = _check_ctrl(ctrl)
    validate_knot_vector(U, p, n)
    span = find_span(n, p, u, U)
    Ns = basis_functions(span, u, p, U)
    out = [0.0] * dim
    for r, N in enumerate(Ns):
        P = ctrl[span - p + r]
        for d in range(dim):
            out[d] += N * P[d]
    return tuple(out)


def curve_derivatives(
    U: Sequence[float], p: int, ctrl: Sequence[Point], u: float, n_ders: int
) -> List[Tuple[float, ...]]:
    """方法 A：C^{(k)}(u) = Σ_i N^{(k)}_{i,p}(u) P_i，k = 0..n_ders（n_ders ≤ p）。

    在重数 s 的内部节点处，阶数 > p-s 的导数取右向单侧值（基函数右连续约定）。
    """
    n, dim = _check_ctrl(ctrl)
    validate_knot_vector(U, p, n)
    if not (0 <= n_ders <= p):
        raise DomainError(f"n_ders 必须在 [0, p]=[0, {p}] 内，收到 {n_ders}")
    span = find_span(n, p, u, U)
    ders = basis_function_ders(span, u, p, n_ders, U)
    out: List[Tuple[float, ...]] = []
    for k in range(n_ders + 1):
        acc = [0.0] * dim
        for r, Nk in enumerate(ders[k]):
            P = ctrl[span - p + r]
            for d in range(dim):
                acc[d] += Nk * P[d]
        out.append(tuple(acc))
    return out


def curve_derivatives_by_differencing(
    U: Sequence[float], p: int, ctrl: Sequence[Point], u: float, n_ders: int
) -> List[Tuple[float, ...]]:
    """方法 B：控制点逐阶差分（导数曲线链）。

    一阶导曲线是次数 p-1、节点 U[1:-1]、控制点 D_i = p(P_{i+1}-P_i)/(U[i+p+1]-U[i+1])
    的 B 样条；对它重复该规则得更高阶。**前置**：内部节点重数 ≤ p-n_ders（否则
    k 阶导在节点处不存在，方法 B 无定义，抛 DomainError；方法 A 仍可给单侧值）。
    """
    n, dim = _check_ctrl(ctrl)
    validate_knot_vector(U, p, n)
    if not (0 <= n_ders <= p):
        raise DomainError(f"n_ders 必须在 [0, p]=[0, {p}] 内，收到 {n_ders}")

    # 光滑性前置：内部 run 重数 ≤ p - n_ders（n_ders = 0 时无额外要求）
    if n_ders >= 1:
        limit = p - n_ders
        run = 1
        for k in range(p + 1, n):  # 内部节点下标 p+1..n? 内部区域 (p, n+1) 开区间
            if U[k + 1] == U[k]:
                run += 1
                if run > limit:
                    raise DomainError(
                        f"内部重数 {run} > p-n_ders={limit}，{n_ders} 阶导在节点处不存在"
                    )
            else:
                run = 1

    P: List[List[float]] = [list(q) for q in ctrl]
    Uk: List[float] = list(U)
    pk = p
    nk = n
    out: List[Tuple[float, ...]] = []

    def _eval_current() -> Tuple[float, ...]:
        span = find_span(nk, pk, u, Uk)
        Ns = basis_functions(span, u, pk, Uk)
        acc = [0.0] * dim
        for r, N in enumerate(Ns):
            Q = P[span - pk + r]
            for d in range(dim):
                acc[d] += N * Q[d]
        return tuple(acc)

    out.append(_eval_current())
    for _k in range(1, n_ders + 1):
        newP: List[List[float]] = []
        for i in range(nk):  # 新控制点 0..nk-1
            den = Uk[i + pk + 1] - Uk[i + 1]
            if den > 0.0:
                newP.append([pk * (P[i + 1][d] - P[i][d]) / den for d in range(dim)])
            else:
                newP.append([0.0] * dim)
        P = newP
        Uk = Uk[1:-1]
        pk -= 1
        nk -= 1
        out.append(_eval_current())
    return out


def _homogeneous(ctrl: Sequence[Point], weights: Sequence[float]) -> List[List[float]]:
    dim = len(ctrl[0])
    Pw: List[List[float]] = []
    for pt, w in zip(ctrl, weights):
        Pw.append([w * c for c in pt] + [w])
    return Pw


def nurbs_curve_point(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    weights: Sequence[float],
    u: float,
) -> Tuple[float, ...]:
    """NURBS 曲线求值：齐次曲线求值后投影回仿射空间。"""
    n, dim = _check_ctrl(ctrl)
    validate_knot_vector(U, p, n)
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(w <= 0.0 for w in weights):
        raise DomainError("NURBS 权重必须全为正（本内核不支持非正权）")
    hw = curve_point(U, p, _homogeneous(ctrl, weights), u)
    w = hw[dim]
    if abs(w) < 1e-300:
        raise DomainError("齐次坐标 w(u) 下溢为零，无法投影")
    return tuple(c / w for c in hw[:dim])


def nurbs_curve_derivatives(
    U: Sequence[float],
    p: int,
    ctrl: Sequence[Point],
    weights: Sequence[float],
    u: float,
    n_ders: int,
) -> List[Tuple[float, ...]]:
    """NURBS 各阶导数：齐次导矢 + Leibniz 递推投影。

    记 A(u) = w(u)C(u)（齐次曲线的空间分量），则 A^{(k)} = Σ_j C(k,j) C^{(j)} w^{(k-j)}，
    逐步反解 C^{(k)} = (A^{(k)} - Σ_{j<k} C(k,j) C^{(j)} w^{(k-j)}) / w。
    """
    n, dim = _check_ctrl(ctrl)
    validate_knot_vector(U, p, n)
    if len(weights) != n + 1:
        raise DomainError(f"权重数应为 {n + 1}，收到 {len(weights)}")
    if any(w <= 0.0 for w in weights):
        raise DomainError("NURBS 权重必须全为正（本内核不支持非正权）")

    hw_ders = curve_derivatives(U, p, _homogeneous(ctrl, weights), u, n_ders)
    A = [tuple(vec[:dim]) for vec in hw_ders]
    W = [vec[dim] for vec in hw_ders]
    if abs(W[0]) < 1e-300:
        raise DomainError("w(u) 下溢为零，无法投影")

    C: List[List[float]] = []
    for k in range(n_ders + 1):
        rhs = list(A[k])
        for j in range(k):
            c = comb(k, j)
            wk = W[k - j]
            Cj = C[j]
            for d in range(dim):
                rhs[d] -= c * Cj[d] * wk
        C.append([r / W[0] for r in rhs])
    return [tuple(c) for c in C]
