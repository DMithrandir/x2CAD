"""Tier 1 不变量检查器：算子后置自检与验证台共用的**同一份**实现。

设计文档 §4.3 明确要求「``post_invariants()`` 与验证台的检查器共用同一实现，防两套口径」。
本模块就是这个单一实现：算子内部调用它做后置自检，验证台调用它产出 Tier 1 证据。

返回约定
--------
检查函数返回**残差/问题列表**而不是布尔值：残差便于记录与排序，
问题列表便于定位。判定阈值由调用方（通常是 ``ToleranceContext``）决定，
这里不藏魔法常数。
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from primitives.bspline import DomainError, basis_function_ders, basis_functions, find_span

__all__ = [
    "partition_of_unity_residual",
    "derivative_partition_residual",
    "mesh_edge_uses",
    "closed_manifold_problems",
    "euler_characteristic",
    "degenerate_triangle_count",
]


# ------------------------------------------------------------------ 曲线层


def partition_of_unity_residual(U: Sequence[float], p: int, u: float) -> float:
    """|Σ_i N_{i,p}(u) − 1|：B 样条基函数的单位分解恒等式。"""
    n = len(U) - p - 2
    span = find_span(n, p, u, U)
    return abs(sum(basis_functions(span, u, p, U)) - 1.0)


def derivative_partition_residual(U: Sequence[float], p: int, u: float, order: int) -> float:
    """|Σ_i N^{(k)}_{i,p}(u)|：基函数 k 阶导之和恒为零（1 ≤ k ≤ p）。"""
    if not (1 <= order <= p):
        raise DomainError(f"order 必须在 [1, p]=[1, {p}] 内，收到 {order}")
    n = len(U) - p - 2
    span = find_span(n, p, u, U)
    ders = basis_function_ders(span, u, p, order, U)
    return abs(sum(ders[order]))


# ------------------------------------------------------------------ 网格拓扑层


def mesh_edge_uses(faces: Sequence[Sequence[int]]) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    """统计每条无向边被哪些**有向**边使用：键 (min,max)，值 [(a,b), ...]。"""
    uses: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for face in faces:
        if len(face) < 3:
            raise DomainError(f"面至少需要 3 个顶点，收到 {tuple(face)}")
        m = len(face)
        for k in range(m):
            a, b = int(face[k]), int(face[(k + 1) % m])
            if a == b:
                raise DomainError(f"面含退化边 ({a},{a})：{tuple(face)}")
            key = (a, b) if a < b else (b, a)
            uses.setdefault(key, []).append((a, b))
    return uses


def closed_manifold_problems(faces: Sequence[Sequence[int]]) -> List[str]:
    """闭合 + 定向一致性检查；返回问题描述列表，空列表 = 通过。

    规则（设计文档 §6.1 Tier 1）：
    - 每条无向边恰好被 2 个有向边使用（闭合/水密）；
    - 两次使用方向相反（法向一致），否则是翻面或非流形。
    """
    problems: List[str] = []
    for key, uses in sorted(mesh_edge_uses(faces).items()):
        if len(uses) != 2:
            problems.append(f"边 {key} 被 {len(uses)} 个面使用（应为 2）")
        elif uses[0] == uses[1]:
            problems.append(f"边 {key} 两次使用方向相同 {uses[0]}：法向不一致")
    return problems


def euler_characteristic(faces: Sequence[Sequence[int]]) -> Tuple[int, int, int, int]:
    """返回 (V, E, F, V−E+F)。闭合可定向曲面 V−E+F = 2(1−g)。"""
    vertices = set()
    for face in faces:
        vertices.update(int(v) for v in face)
    v = len(vertices)
    e = len(mesh_edge_uses(faces))
    f = len(faces)
    return v, e, f, v - e + f


def degenerate_triangle_count(
    points: Sequence[Sequence[float]], faces: Sequence[Sequence[int]], rel_tol: float = 1e-12
) -> int:
    """近零面积三角形计数：2·面积 ≤ rel_tol · (最长边)^2 判为退化。

    退化单元是退化知识库 S 族的核心信号；用**相对**判据（不是绝对面积阈值），
    这样它对全局尺度不敏感。
    """
    if rel_tol <= 0.0:
        raise DomainError("rel_tol 必须为正")
    count = 0
    for face in faces:
        if len(face) != 3:
            raise DomainError("degenerate_triangle_count 只接受三角形面")
        a, b, c = (points[i] for i in face)
        ab = [b[k] - a[k] for k in range(3)]
        ac = [c[k] - a[k] for k in range(3)]
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area2 = math.sqrt(sum(x * x for x in cross))
        if not math.isfinite(area2):
            raise DomainError("三角形面积非有限：输入含 NaN/Inf")
        edges = [
            math.dist(a, b),
            math.dist(b, c),
            math.dist(c, a),
        ]
        longest = max(edges)
        if longest == 0.0:
            count += 1
        elif area2 <= rel_tol * longest * longest:
            count += 1
    return count
