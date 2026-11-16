"""算子：Bézier 曲线升阶（单步 + 重复升阶到目标次数）。

数学定义
--------
p 次 Bézier 曲线升一阶为 p+1 次，几何不变（NURBS Book A5.9）::

    Q_i = (i/(p+1)) P_{i-1} + (1 - i/(p+1)) P_i,   i = 0..p+1

重复 t 次即升到 p+t 次。升阶在齐次坐标下对 NURBS 同样成立（权重随控制点一起升阶）；
权重是正数的凸组合，保持为正。

范围声明
--------
本算子只处理**单段 Bézier**（clamped、无内部节点）。一般 B 样条的升阶需要先在内部节点处
分割成 Bézier 段、逐段升阶、再合并节点向量——那属于带拓扑装配的操作，按 ADR-0001 不由
AI 直接成文，列为 P4 的规格先行项（见 ``operators/degree_elevation/spec.json`` 的
``unhandled`` 段）。
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from primitives.bspline import DomainError

__all__ = ["elevate_bezier", "elevate_bezier_to", "elevate_bezier_nurbs"]

Point = Sequence[float]


def _check(ctrl: Sequence[Point]) -> int:
    if len(ctrl) < 2:
        raise DomainError(f"Bézier 升阶至少需要 2 个控制点，收到 {len(ctrl)}")
    dim = len(ctrl[0])
    if dim == 0 or any(len(q) != dim for q in ctrl):
        raise DomainError("控制点必须同维且非零维")
    return dim


def elevate_bezier(ctrl: Sequence[Point]) -> List[Tuple[float, ...]]:
    """p 次 → p+1 次（单步升阶）。"""
    dim = _check(ctrl)
    p = len(ctrl) - 1
    q = p + 1
    out: List[Tuple[float, ...]] = [tuple(ctrl[0])]
    for i in range(1, q):
        a = i / q
        out.append(tuple(a * ctrl[i - 1][d] + (1.0 - a) * ctrl[i][d] for d in range(dim)))
    out.append(tuple(ctrl[-1]))
    return out


def elevate_bezier_to(ctrl: Sequence[Point], target_degree: int) -> List[Tuple[float, ...]]:
    """重复升阶到 ``target_degree``（>= 当前次数）。"""
    _check(ctrl)
    p = len(ctrl) - 1
    if not isinstance(target_degree, int) or target_degree < p:
        raise DomainError(f"目标次数 {target_degree!r} 必须是不小于当前次数 {p} 的整数")
    out = [tuple(q) for q in ctrl]
    while len(out) - 1 < target_degree:
        out = elevate_bezier(out)
    return out


def elevate_bezier_nurbs(
    ctrl: Sequence[Point], weights: Sequence[float], target_degree: int
) -> Tuple[List[Tuple[float, ...]], List[float]]:
    """NURBS Bézier 升阶：齐次坐标升阶后投影；权重保持为正。"""
    dim = _check(ctrl)
    if len(weights) != len(ctrl):
        raise DomainError(f"权重数应为 {len(ctrl)}，收到 {len(weights)}")
    if any(not (w > 0.0) or not math.isfinite(w) for w in weights):
        raise DomainError("NURBS 权重必须全为正的有限数")
    homogeneous = [[weights[i] * ctrl[i][d] for d in range(dim)] + [weights[i]] for i in range(len(ctrl))]
    elevated = elevate_bezier_to(homogeneous, target_degree)
    out_p: List[Tuple[float, ...]] = []
    out_w: List[float] = []
    for row in elevated:
        w = row[-1]
        if not w > 0.0:
            raise DomainError("升阶后齐次权重非正：实现错误")
        out_p.append(tuple(c / w for c in row[:-1]))
        out_w.append(w)
    return out_p, out_w
