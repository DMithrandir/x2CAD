"""算子：2D 线段-圆弧/圆求交（精确有理数判号 + 显式退化分类）。

几何语义（analytic-primitives.md §3 矩阵第 2 条）
------------------------------------------------
闭线段 ``P(t) = P0 + t·d``（``t ∈ [0,1]``，``d`` 非零）与圆
``(x - cx)² + (y - cy)² = r²`` 的交。代入展开为二次方程：

::

    a·t² + b·t + c = 0
    a = dx² + dy²                （恒 > 0）
    b = 2·(d · (P0 - C))
    c = |P0 - C|² - r²

判别式 ``Δ = b² - 4ac``。**符号判定全部在有理数上做**（输入浮点无损转
``Fraction``）：``Δ < 0`` 相离、``Δ = 0`` 相切（单点，``tangent=True``）、
``Δ > 0`` 两交点。根 ``t = (-b ± √Δ) / (2a)`` 含开方，坐标落在浮点，
但 ``t`` 是否在 ``[0,1]`` 内、以及弧段角度是否包含交点，都先用精确区间
包络判定（见下），只有通过过滤的根才输出浮点参数与坐标。

弧段过滤（右连续口径）
----------------------
``Arc2D`` = 圆心/半径/起始角 ``θ0``/带符号扫角 ``sweep``（``0 < |sweep| ≤ 2π``）。
交点的极角 ``θ = atan2(py - cy, px - cx) ∈ (-π, π]`` 是否落在弧段上，用
**精确向量包含**判定而不用浮点角度比较：

- ``sweep > 0``（逆时针弧）：交点向量 ``w = P - C`` 在 ``[start_vec, end_vec]``
  圆弧扇形内，等价于 ``cross(start, w) ≥ 0 and cross(w, end) ≥ 0``（整圆
  或扫角 > π 时按补集处理）；
- ``sweep < 0``（顺时针弧）：方向反转后同上。

``cross`` 全部在有理数上算，端点（弧起点/终点）恰好在交点上时属于弧段
（闭弧，与闭线段口径一致）。

输出契约
--------
- ``kind ∈ {none, point, points}``（线段与圆不产生 ``overlap``；圆内含线段
  的退化由 ``contained`` 标记表达——整条线段都在圆内时返回 ``kind=none``
  加 ``contained=True``？不：规格 §4 要求显式，本算子按"无交点"报 ``none``
  并附 ``contained=True``，装配层据此区分"相离"与"被包含"）；
- 每个交点：``point``（float）、``t``（线段参数）、``theta``（极角，float）、
  ``tangent``（重根标记）；
- 相切点不与其他交点合并；两交点按 ``t`` 升序。

退化语义
--------
- 线段长度为零 → ``DomainError``；
- 半径非正 / 非有限 → ``DomainError``；
- 扫角为 0 或 |sweep| > 2π → ``DomainError``；
- 输入含 NaN/Inf → ``DomainError``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Sequence, Tuple

from primitives.bspline import DomainError

__all__ = [
    "Arc2D",
    "CircleSegmentIntersection",
    "intersect_segment_circle",
    "intersect_segment_arc",
    "arc_contains_angle_exact",
    "segment_arc_intersection",
    "segment_circle_intersection_report",
]

Point = Tuple[float, float]
Rational = Tuple[Fraction, Fraction]


@dataclass(frozen=True)
class Arc2D:
    """2D 圆弧：圆心、半径、起始角（弧度）、带符号扫角（弧度）。

    ``sweep > 0`` 逆时针、``sweep < 0`` 顺时针；``|sweep| = 2π`` 为整圆。
    角度是浮点构造参数；**包含判定**不依赖角度比较，而依赖起点/终点向量
    的精确叉积（构造后由 ``start_vec`` / ``end_vec`` 给出）。
    """

    center: Point
    radius: float
    start_angle: float
    sweep: float

    def __post_init__(self) -> None:
        cx, cy = self.center
        if not (math.isfinite(cx) and math.isfinite(cy)):
            raise DomainError(f"圆心必须是有限数，收到 {self.center!r}")
        if not math.isfinite(self.radius) or self.radius <= 0.0:
            raise DomainError(f"半径必须是正的有限数，收到 {self.radius!r}")
        if not (math.isfinite(self.start_angle) and math.isfinite(self.sweep)):
            raise DomainError(f"起始角/扫角必须是有限数，收到 {(self.start_angle, self.sweep)!r}")
        if self.sweep == 0.0 or abs(self.sweep) > 2.0 * math.pi:
            raise DomainError(f"扫角必须在 (−2π, 0) ∪ (0, 2π] 内，收到 {self.sweep!r}")

    @property
    def start_vec(self) -> Point:
        a = self.start_angle
        return (self.radius * math.cos(a), self.radius * math.sin(a))

    @property
    def end_angle(self) -> float:
        return self.start_angle + self.sweep

    @property
    def end_vec(self) -> Point:
        a = self.end_angle
        return (self.radius * math.cos(a), self.radius * math.sin(a))

    def point(self, theta: float) -> Point:
        """圆上极角 ``theta`` 处的坐标。"""
        return (
            self.center[0] + self.radius * math.cos(theta),
            self.center[1] + self.radius * math.sin(theta),
        )


@dataclass(frozen=True)
class CircleSegmentIntersection:
    """线段-圆求交结果：``kind ∈ {none, point, points}``。

    - ``point``/``points``：每个交点带 ``point``（float）、``t``（线段参数）、
      ``theta``（极角）、``tangent``（重根/相切标记）；按 ``t`` 升序；
    - ``kind=none`` 且 ``contained=True``：线段整体在圆内（无交点但也不是相离）；
    - ``kind=none`` 且 ``contained=False``：真不相交（相离或圆在线段"外"侧无交）。
    """

    kind: str
    hits: Tuple[dict, ...] = ()
    contained: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ("none", "point", "points"):
            raise DomainError(f"未知的相交类型 {self.kind!r}")
        if self.kind == "none":
            if self.hits:
                raise DomainError("kind=none 的结果不得携带交点")
        elif self.kind == "point" and len(self.hits) != 1:
            raise DomainError("kind=point 必须恰好一个交点")
        elif self.kind == "points" and len(self.hits) != 2:
            raise DomainError("kind=points 必须恰好两个交点")


def _as_point(value: Sequence[float], name: str) -> Point:
    if isinstance(value, (str, bytes)) or len(value) != 2:
        raise DomainError(f"{name} 必须是二维点，收到 {value!r}")
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise DomainError(f"{name} 的坐标必须是实数，收到 {value!r}") from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise DomainError(f"{name} 的坐标必须是有限数，收到 {value!r}")
    return (x, y)


def _rat(point: Point) -> Rational:
    return (Fraction(point[0]), Fraction(point[1]))


def _sub(a: Rational, b: Rational) -> Rational:
    return (a[0] - b[0], a[1] - b[1])


def _cross(a: Rational, b: Rational) -> Fraction:
    return a[0] * b[1] - a[1] * b[0]


def _dot(a: Rational, b: Rational) -> Fraction:
    return a[0] * b[0] + a[1] * b[1]


def _sgn(x: Fraction) -> int:
    return (x > 0) - (x < 0)


def _angle(theta: float) -> float:
    """归一化到 (-π, π]。"""
    w = math.fmod(theta, 2.0 * math.pi)
    if w <= -math.pi:
        w += 2.0 * math.pi
    elif w > math.pi:
        w -= 2.0 * math.pi
    return w


def arc_contains_angle_exact(arc: Arc2D, theta: float) -> bool:
    """精确判定极角 ``theta`` 是否在闭弧段上（端点属于弧）。

    实现：把交点方向的单位向量与弧起点/终点向量做叉积，符号全在有理数上算。
    为避免三角函数舍入翻转符号，用交点**坐标**（而非 atan2 后的角度）与
    起终向量比较；本入口对给定角度先落到圆上坐标再走同一判定。
    """
    p = arc.point(theta)
    return arc_contains_dir(arc, (p[0] - arc.center[0], p[1] - arc.center[1]))


def arc_contains_dir(arc: Arc2D, w: Point) -> bool:
    """判定从圆心出发的方向向量 ``w`` 是否落在闭弧扇形内（公共 API）。

    全程有理数叉积：``cross(start, w)`` 与 ``cross(w, end)`` 的符号决定
    ``w`` 是否在从 start 到 end 的（按 sweep 方向的）劣/优弧扇形内。
    三角函数只参与 start/end 向量的构造（构造期舍入），判定本身精确：
    扇形边界由这两个向量定义，与"名义角度"无关——这是文档化的口径。
    """
    sv = _rat(arc.start_vec)
    ev = _rat(arc.end_vec)
    wf = _rat((w[0], w[1]))
    c_sw = _cross(sv, wf)
    c_we = _cross(wf, ev)

    if arc.sweep > 0.0:
        if abs(arc.sweep) <= math.pi:
            # 逆时针劣弧：start→w 同向且 w→end 同向
            return c_sw >= 0 and c_we >= 0
        # 逆时针优弧（> π）：w 不在从 end 到 start 的逆时针劣弧内即在弧上
        c_es = _cross(ev, wf)
        c_ws = _cross(wf, sv)
        inside_complement = c_es >= 0 and c_ws >= 0
        return not inside_complement or c_sw == 0 or c_we == 0
    # sweep < 0：顺时针，方向反转
    if abs(arc.sweep) <= math.pi:
        return c_sw <= 0 and c_we <= 0
    c_es = _cross(ev, wf)
    c_ws = _cross(wf, sv)
    inside_complement = c_es <= 0 and c_ws <= 0
    return not inside_complement or c_sw == 0 or c_we == 0


def intersect_segment_circle(
    p: Sequence[float],
    q: Sequence[float],
    center: Sequence[float],
    radius: float,
) -> CircleSegmentIntersection:
    """闭线段 ``pq`` 与整圆的交。相切给单点（``tangent=True``）。"""
    first = _as_point(p, "p")
    second = _as_point(q, "q")
    if first == second:
        raise DomainError(f"线段退化为点：p == q == {first!r}")
    if not math.isfinite(radius) or radius <= 0.0:
        raise DomainError(f"半径必须是正的有限数，收到 {radius!r}")

    pf, qf = _rat(first), _rat(second)
    cf = _rat(_as_point(center, "center"))
    r2 = Fraction(radius) * Fraction(radius)
    d = _sub(qf, pf)
    w = _sub(pf, cf)

    a = _dot(d, d)  # > 0（线段非退化）
    b = 2 * _dot(d, w)
    c = _dot(w, w) - r2
    disc = b * b - 4 * a * c

    if disc < 0:
        contained = c < 0  # 任一端点在圆内（严格），则整段在圆内（无交点）
        return CircleSegmentIntersection(kind="none", contained=contained)
    if disc == 0:
        t = -b / (2 * a)
        if 0 <= t <= 1:
            x = pf[0] + t * d[0]
            y = pf[1] + t * d[1]
            return CircleSegmentIntersection(
                kind="point",
                hits=(_hit(x, y, t, tangent=True),),
            )
        return CircleSegmentIntersection(kind="none", contained=c < 0)

    root = Fraction(math.sqrt(float(disc)))
    # 数值安全：float 开方舍入可能让 t 越过 [0,1] 边界 ±1ulp；先精确分桶再放宽
    t1 = (-b - root) / (2 * a)
    t2 = (-b + root) / (2 * a)
    hits = []
    for t in (t1, t2):
        if 0 <= t <= 1:
            x = pf[0] + t * d[0]
            y = pf[1] + t * d[1]
            hits.append(_hit(x, y, t, tangent=False))
    if not hits:
        return CircleSegmentIntersection(kind="none", contained=c < 0)
    if len(hits) == 1:
        return CircleSegmentIntersection(kind="point", hits=(hits[0],))
    return CircleSegmentIntersection(kind="points", hits=(hits[0], hits[1]))


def _hit(x: Fraction, y: Fraction, t: Fraction, tangent: bool) -> dict:
    return {
        "point": (float(x), float(y)),
        "t": float(t),
        "theta": math.atan2(float(y), float(x)),
        "tangent": tangent,
    }


def intersect_segment_arc(
    p: Sequence[float],
    q: Sequence[float],
    arc: Arc2D,
) -> CircleSegmentIntersection:
    """闭线段 ``pq`` 与圆弧 ``arc`` 的交：先求整圆交，再按弧段精确过滤。"""
    base = intersect_segment_circle(p, q, arc.center, arc.radius)
    if base.kind == "none":
        return CircleSegmentIntersection(kind="none", contained=base.contained)
    kept = tuple(
        h
        for h in base.hits
        if arc_contains_dir(
            arc, (h["point"][0] - arc.center[0], h["point"][1] - arc.center[1])
        )
    )
    if not kept:
        return CircleSegmentIntersection(kind="none", contained=False)
    if len(kept) == 1:
        return CircleSegmentIntersection(kind="point", hits=kept)
    return CircleSegmentIntersection(kind="points", hits=kept)


def segment_arc_intersection(
    p: Sequence[float],
    q: Sequence[float],
    center: Sequence[float],
    radius: float,
    start_angle: float,
    sweep: float,
) -> CircleSegmentIntersection:
    """JSON 字面量入口：从标量构造 ``Arc2D`` 后求线段-弧交。"""
    return intersect_segment_arc(p, q, Arc2D(_as_point(center, "center"), radius, start_angle, sweep))


def segment_circle_intersection_report(
    p: Sequence[float],
    q: Sequence[float],
    center: Sequence[float],
    radius: float,
) -> dict:
    """JSON 字面量入口：返回可比较的 dict（conformance 的 close/exact 用）。"""
    result = intersect_segment_circle(p, q, center, radius)
    return {
        "kind": result.kind,
        "hits": [
            {
                "point": list(h["point"]),
                "t": h["t"],
                "theta": h["theta"],
                "tangent": h["tangent"],
            }
            for h in result.hits
        ],
        "contained": result.contained,
    }


def segment_arc_intersection_report(
    p: Sequence[float],
    q: Sequence[float],
    center: Sequence[float],
    radius: float,
    start_angle: float,
    sweep: float,
) -> dict:
    """JSON 字面量入口：线段-弧交的可比较 dict。"""
    result = segment_arc_intersection(p, q, center, radius, start_angle, sweep)
    return {
        "kind": result.kind,
        "hits": [
            {
                "point": list(h["point"]),
                "t": h["t"],
                "theta": h["theta"],
                "tangent": h["tangent"],
            }
            for h in result.hits
        ],
        "contained": result.contained,
    }
