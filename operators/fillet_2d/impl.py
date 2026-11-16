"""算子：2D 圆角（两条线段夹角处的相切圆弧）。

几何构造
--------
角点在 ``p2``，两条边分别指向 ``p1`` 与 ``p3``。记单位方向 u=(p1−p2)/|p1−p2|、
v=(p3−p2)/|p3−p2|，夹角 θ ∈ (0, π)。圆角半径为 r 的圆与两边相切时：

::

    d = r / sin(θ/2)           圆心到角点的距离（沿角平分线）
    t = r / tan(θ/2)           切点到角点的距离（沿两边）
    C = p2 + (u+v)/|u+v| · d    圆心
    T1 = p2 + u·t,  T2 = p2 + v·t
    圆弧圆心角 = π − θ（四边形 p2-T1-C-T2 在 T1/T2 处为直角）

圆弧方向由 ``cross(u,v)`` 的符号决定：从 T1 到 T2 走**劣弧**，扫角带符号
``sweep = −sign(cross(u,v))·(π−θ)``。

退化语义（设计文档 §4.5：圆角是表示能力的酸测试）
------------------------------------------------
- 半径非正 → ``DomainError``；
- 边长为零 → ``DomainError``；
- 两边共线（θ=0 或 π，``cross(u,v)=0``）→ ``DomainError``：没有夹角就没有圆角；
- 切点超出线段（r 太大）→ ``DomainError``：不允许把切点放到线段延长线上假装成功。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Tuple

from primitives.bspline import DomainError

__all__ = ["Fillet2D", "fillet_corner", "fillet_arc_length"]

Point = Sequence[float]


def _vec(a: Point, b: Point) -> Tuple[float, float]:
    return (b[0] - a[0], b[1] - a[1])


def _norm(v: Tuple[float, float]) -> float:
    return math.hypot(v[0], v[1])


@dataclass(frozen=True)
class Fillet2D:
    """一段 2D 圆角圆弧（圆心、切点、带符号扫角）。"""

    center: Tuple[float, float]
    tangent1: Tuple[float, float]
    tangent2: Tuple[float, float]
    radius: float
    start_angle: float
    sweep: float  # 带符号，单位弧度
    corner: Tuple[float, float]
    angle: float  # 夹角 θ

    @property
    def length(self) -> float:
        return self.radius * abs(self.sweep)

    def point(self, s: float) -> Tuple[float, float]:
        """圆弧上参数 s ∈ [0,1] 的点（s=0 → T1，s=1 → T2）。"""
        if not (0.0 <= s <= 1.0):
            raise DomainError(f"圆弧参数 s={s!r} 必须在 [0,1] 内")
        a = self.start_angle + self.sweep * s
        return (
            self.center[0] + self.radius * math.cos(a),
            self.center[1] + self.radius * math.sin(a),
        )


def fillet_corner(p1: Point, p2: Point, p3: Point, radius: float) -> Fillet2D:
    """在 p1-p2-p3 的角点 p2 处构造半径 radius 的相切圆弧。"""
    if not math.isfinite(radius) or radius <= 0.0:
        raise DomainError(f"圆角半径必须是正的有限数，收到 {radius!r}")
    for name, p in (("p1", p1), ("p2", p2), ("p3", p3)):
        if len(p) != 2 or any(not math.isfinite(c) for c in p):
            raise DomainError(f"{name} 必须是有限的二维点，收到 {p!r}")

    e1 = _vec(p2, p1)
    e2 = _vec(p2, p3)
    len1, len2 = _norm(e1), _norm(e2)
    if len1 == 0.0 or len2 == 0.0:
        raise DomainError("圆角的两条边长度必须非零（p1/p3 不能与角点重合）")
    u = (e1[0] / len1, e1[1] / len1)
    v = (e2[0] / len2, e2[1] / len2)

    cross = u[0] * v[1] - u[1] * v[0]
    dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    if cross == 0.0:
        raise DomainError("两条边共线（夹角 0 或 π）：没有夹角可倒圆角")
    theta = math.atan2(abs(cross), dot)  # ∈ (0, π)

    half = 0.5 * theta
    t = radius / math.tan(half)
    d = radius / math.sin(half)
    tol = 1e-12 * max(len1, len2)
    if t > len1 + tol or t > len2 + tol:
        raise DomainError(
            f"圆角半径 {radius!r} 过大：切点距离 {t!r} 超出边长 ({len1!r}, {len2!r})"
        )

    bisector = (u[0] + v[0], u[1] + v[1])
    blen = _norm(bisector)
    if blen == 0.0:
        raise DomainError("角平分线退化（两边反向）")
    center = (p2[0] + bisector[0] / blen * d, p2[1] + bisector[1] / blen * d)
    t1 = (p2[0] + u[0] * t, p2[1] + u[1] * t)
    t2 = (p2[0] + v[0] * t, p2[1] + v[1] * t)

    start_angle = math.atan2(t1[1] - center[1], t1[0] - center[0])
    direction = -1.0 if cross > 0.0 else 1.0
    sweep = direction * (math.pi - theta)

    # 后置不变量：切点确在圆上（实现错误当场暴露，不静默产出坏圆弧）
    for name, tp in (("T1", t1), ("T2", t2)):
        dist = math.hypot(tp[0] - center[0], tp[1] - center[1])
        if abs(dist - radius) > 1e-9 * max(radius, 1.0):
            raise DomainError(f"后置不变量失败：{name} 到圆心距离 {dist!r} ≠ r={radius!r}")

    return Fillet2D(
        center=center,
        tangent1=t1,
        tangent2=t2,
        radius=float(radius),
        start_angle=start_angle,
        sweep=sweep,
        corner=(float(p2[0]), float(p2[1])),
        angle=theta,
    )


def fillet_arc_length(p1: Point, p2: Point, p3: Point, radius: float) -> float:
    """圆角弧长 = r·|π−θ|（薄封装，供 conformance 套件与调用方使用）。"""
    return fillet_corner(p1, p2, p3, radius).length
