"""算子：张量积 B 样条曲面求值与偏导数。

S(u,v) = Σ_i Σ_j N_{i,pu}(u) N_{j,pv}(v) P_{i,j}；偏导数 S^{(k,l)} 用两个参数方向
各自的基函数导数直接加权（方法 A 的张量积推广）。与有限差分、Bézier 片闭式对拍。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from primitives.bspline import (
    DomainError,
    basis_function_ders,
    basis_functions,
    find_span,
    validate_knot_vector,
)

__all__ = ["surface_point", "surface_derivatives"]

Net = Sequence[Sequence[Sequence[float]]]


def _check_net(net: Net, pu: int, pv: int, U: Sequence[float], V: Sequence[float]):
    nu = len(net) - 1
    if nu < pu:
        raise DomainError(f"u 向控制点数 {nu + 1} 必须至少为 {pu + 1}")
    nv = len(net[0]) - 1
    dim = len(net[0][0])
    if dim == 0:
        raise DomainError("控制点维度为零")
    for row in net:
        if len(row) != nv + 1:
            raise DomainError(f"控制网必须是规则 (nu+1)x(nv+1) 网格，行长度 {len(row)} ≠ {nv + 1}")
        for q in row:
            if len(q) != dim:
                raise DomainError(f"控制点必须同维，首点维度 {dim}")
    validate_knot_vector(U, pu, nu)
    validate_knot_vector(V, pv, nv)
    return nu, nv, dim


def surface_point(
    U: Sequence[float],
    V: Sequence[float],
    pu: int,
    pv: int,
    net: Net,
    u: float,
    v: float,
) -> Tuple[float, ...]:
    """张量积 B 样条曲面点。"""
    nu, nv, dim = _check_net(net, pu, pv, U, V)
    su = find_span(nu, pu, u, U)
    sv = find_span(nv, pv, v, V)
    Nu = basis_functions(su, u, pu, U)
    Nv = basis_functions(sv, v, pv, V)
    acc = [0.0] * dim
    for a, Nua in enumerate(Nu):
        row = net[su - pu + a]
        c = Nua
        for b, Nvb in enumerate(Nv):
            P = row[sv - pv + b]
            w = c * Nvb
            for d in range(dim):
                acc[d] += w * P[d]
    return tuple(acc)


def surface_derivatives(
    U: Sequence[float],
    V: Sequence[float],
    pu: int,
    pv: int,
    net: Net,
    u: float,
    v: float,
    du: int,
    dv: int,
) -> List[List[Tuple[float, ...]]]:
    """偏导数矩阵 out[k][l] = S^{(k,l)}(u,v)，k = 0..du，l = 0..dv。

    前置：du ≤ pu，dv ≤ pv。重数内部节点处的单侧语义同曲线方法 A。
    """
    nu, nv, dim = _check_net(net, pu, pv, U, V)
    if not (0 <= du <= pu):
        raise DomainError(f"du 必须在 [0, pu]=[0, {pu}] 内，收到 {du}")
    if not (0 <= dv <= pv):
        raise DomainError(f"dv 必须在 [0, pv]=[0, {pv}] 内，收到 {dv}")
    su = find_span(nu, pu, u, U)
    sv = find_span(nv, pv, v, V)
    Du = basis_function_ders(su, u, pu, du, U)
    Dv = basis_function_ders(sv, v, pv, dv, V)

    out: List[List[Tuple[float, ...]]] = []
    for k in range(du + 1):
        row_out: List[Tuple[float, ...]] = []
        for l in range(dv + 1):
            acc = [0.0] * dim
            for a, Dua in enumerate(Du[k]):
                crow = net[su - pu + a]
                ca = Dua
                for b, Dvb in enumerate(Dv[l]):
                    P = crow[sv - pv + b]
                    w = ca * Dvb
                    for d in range(dim):
                        acc[d] += w * P[d]
            row_out.append(tuple(acc))
        out.append(row_out)
    return out
