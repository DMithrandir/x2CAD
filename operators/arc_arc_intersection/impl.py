"""算子：2D 圆弧/圆-圆弧/圆求交（根轴法 + 精确判号 + 弧段向量过滤）。

几何语义（analytic-primitives.md §3 矩阵第 3 条）
------------------------------------------------
两圆 ``(x-cx1)² + (y-cy1)² = r1²`` 与 ``(x-cx2)² + (y-cy2)² = r2²`` 的交。
记圆心距向量 ``w = C2 - C1``、``d = |w|``、``r1, r2 > 0``。

分类（全部在有理数上判号，``d²`` 精确、``d`` 本身含开方不出现在判定里）：

- ``d == 0``（同心）：
  - ``r1 == r2`` → **重合**（``kind=overlap``，闭曲面重叠不是交点问题）；
  - ``r1 != r2`` → **内含**（``kind=none``，``contained=True`` 标记小圆被大圆包含）；
- ``d > 0``：
  - ``d > r1 + r2`` → 外离（``none``）；
  - ``d == r1 + r2`` → **外切**（单点，``tangent=True``）；
  - ``|r1 - r2| < d < r1 + r2`` → 两交点；
  - ``d == |r1 - r2|``（且 r1 ≠ r2）→ **内切**（单点，``tangent=True``）；
  - ``d < |r1 - r2|`` → 内含（``none``，``contained=True``）。

交点求解：根轴是 ``2·w·P = c1² - c2² + r1² - r2²`` 的直线，与 ``w`` 垂直。
设 ``a = (d² + r1² - r2²) / (2d)``（圆心 C1 到根轴足点的距离）、
``h² = r1² - a²``（``h ≥ 0``），交点 = ``C1 + a·ŵ ± h·ŵ⊥``。
``a`` 与 ``h²`` 是有理数；``h = sqrt(h²)`` 含开方——交点坐标落浮点，
但 ``a`` 的符号区间（``a ∈ [0, d]`` 等价于 ``h² ≥ 0``）与分类全部精确。

弧段过滤
--------
与矩阵 #2 完全同口径（复用 ``segment_arc_intersection`` 的向量叉积逻辑，
通过公共函数 ``arc_contains_dir``）：交点方向向量与弧起终向量做有理数叉积，
端点属闭弧；顺时针取反符号；优弧判补集。

输出契约
--------
- ``kind ∈ {none, point, points, overlap}``；
- 每个交点：``point``（float）、``theta1`` / ``theta2``（两圆上的极角）、
  ``tangent``；按 ``theta1`` 升序；
- ``overlap``（同心同半径重合）返回 ``kind=overlap``，无交点字段；
- ``contained``：内含时 ``True``，其余 ``False``。

退化语义
--------
- 半径非正 / 非有限 → ``DomainError``；
- 输入含 NaN/Inf → ``DomainError``；
- 相切/内切/重合/包含都是**结果分类**（不是拒绝）；只有构造非法才 ``DomainError``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence, Tuple

from primitives.bspline import DomainError
from operators.segment_arc_intersection.impl import Arc2D, arc_contains_dir

__all__ = [
    "arc_arc_intersection",
    "arc_arc_intersection_report",
    "intersect_circles",
    "intersect_arc_arc",
]

Point = Tuple[float, float]
Rational = Tuple[Fraction, Fraction]


@dataclass(frozen=True)
class _Circle:
    center: Point
    radius: float

    def __post_init__(self) -> None:
        cx, cy = self.center
        if not (math.isfinite(cx) and math.isfinite(cy)):
            raise DomainError(f"圆心必须是有限数，收到 {self.center!r}")
        if not math.isfinite(self.radius) or self.radius <= 0.0:
            raise DomainError(f"半径必须是正的有限数，收到 {self.radius!r}")


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


def _hit(point: Point, theta1: float, theta2: float, tangent: bool) -> dict:
    return {
        "point": list(point),
        "theta1": theta1,
        "theta2": theta2,
        "tangent": tangent,
    }


def intersect_circles(
    c1: Sequence[float], r1: float, c2: Sequence[float], r2: float
) -> Tuple[str, Tuple[dict, ...], bool]:
    """两圆求交的分类核：返回 ``(kind, hits, contained)``。

    ``kind ∈ {none, point, points, overlap}``。分类全部在有理数上判定；
    交点坐标含开方，落浮点。
    """
    p1 = _as_point(c1, "c1")
    p2 = _as_point(c2, "c2")
    circ1 = _Circle(p1, r1)
    circ2 = _Circle(p2, r2)

    f1, f2 = _rat(p1), _rat(p2)
    w = _sub(f2, f1)  # C2 - C1
    d2 = w[0] * w[0] + w[1] * w[1]  # 精确 d²
    r1f, r2f = Fraction(circ1.radius), Fraction(circ2.radius)

    if d2 == 0:
        # 同心：半径相同 → 重合；不同 → 内含
        if r1f == r2f:
            return "overlap", (), False
        return "none", (), True

    rsum = r1f + r2f
    rdiff = r1f - r2f
    # 分类：d 与 r1+r2、|r1-r2| 的比较都平方化（非负侧单调），保持精确
    if d2 > rsum * rsum:
        return "none", (), False
    if d2 == rsum * rsum:
        # 外切：交点在 C1 + r1·ŵ 上
        point = _point_on_ray(f1, w, r1f)
        return "point", (_hit(point, _theta(point, f1), _theta(point, f2), True),), False
    if rdiff != 0 and d2 == rdiff * rdiff:
        # 内切：切点在根轴上，也在两圆上
        a = (d2 + r1f * r1f - r2f * r2f) / (2 * Fraction(math.sqrt(float(d2))))
        point = _point_on_ray(f1, w, a)
        return "point", (_hit(point, _theta(point, f1), _theta(point, f2), True),), False
    if d2 < rdiff * rdiff:
        # 内含（|r1-r2| > d，含同心已在上面处理）
        return "none", (), True

    # 两交点：根轴法
    dd = Fraction(math.sqrt(float(d2)))  # d 的浮点近似，仅在除法中使用
    a = (d2 + r1f * r1f - r2f * r2f) / (2 * dd)  # C1 沿 w 到根轴足点的距离
    h2 = r1f * r1f - a * a
    # 分类（§上）已在有理数上保证 |r1−r2| ≤ d ≤ r1+r2，等价于 h2 ≥ 0：
    # h2 = r1² − a² < 0 ⟺ a > r1 ⟺ d² < (r1−r2)² 或 d² > (r1+r2)²，均被上方分支拦截。
    # 因此这里不需要防御性守卫——加了也永远不会执行（变异审计证实：跳过它无法被任何
    # 测试捕获，属于死代码）。数学上若 h2 < 0，说明分类错了，应修分类而不是在这里兜底。
    h = Fraction(math.sqrt(float(h2)))

    ux, uy = w[0] / dd, w[1] / dd  # 单位向量 ŵ（浮点）
    px, py = -float(uy), float(ux)  # 垂直向量
    base_x = float(f1[0]) + float(a) * float(ux)
    base_y = float(f1[1]) + float(a) * float(uy)
    off_x = float(h) * px
    off_y = float(h) * py

    pt_a = (base_x + off_x, base_y + off_y)
    pt_b = (base_x - off_x, base_y - off_y)
    hits = (
        _hit(pt_a, _theta(pt_a, f1), _theta(pt_a, f2), False),
        _hit(pt_b, _theta(pt_b, f1), _theta(pt_b, f2), False),
    )
    # 按 theta1 升序（(-π, π] 归一化后）
    if hits[0]["theta1"] > hits[1]["theta1"]:
        hits = (hits[1], hits[0])
    return "points", hits, False


def _point_on_ray(origin: Rational, direction: Rational, dist: Fraction) -> Point:
    """从 origin 沿 direction 单位方向前进 dist（dist 为有理数）。"""
    dd = Fraction(math.sqrt(float(direction[0] * direction[0] + direction[1] * direction[1])))
    ux = direction[0] / dd
    uy = direction[1] / dd
    return (
        float(origin[0] + ux * dist),
        float(origin[1] + uy * dist),
    )


def _theta(point: Point, center: Rational) -> float:
    return math.atan2(point[1] - float(center[1]), point[0] - float(center[0]))


def intersect_arc_arc(arc1: Arc2D, arc2: Arc2D) -> Tuple[str, Tuple[dict, ...], bool]:
    """两弧求交：先做整圆分类，再把交点按两条弧的扇形精确过滤。"""
    kind, hits, contained = intersect_circles(arc1.center, arc1.radius, arc2.center, arc2.radius)
    if kind in ("none", "overlap"):
        return kind, hits, contained

    def _on_both(h: dict) -> bool:
        p = h["point"]
        w1 = (p[0] - arc1.center[0], p[1] - arc1.center[1])
        w2 = (p[0] - arc2.center[0], p[1] - arc2.center[1])
        return arc_contains_dir(arc1, w1) and arc_contains_dir(arc2, w2)

    kept = tuple(h for h in hits if _on_both(h))
    if not kept:
        return "none", (), False
    if len(kept) == 1:
        return "point", kept, False
    return "points", kept, False


def arc_arc_intersection(
    c1: Sequence[float],
    r1: float,
    start1: float,
    sweep1: float,
    c2: Sequence[float],
    r2: float,
    start2: float,
    sweep2: float,
) -> dict:
    """JSON 字面量入口：返回可比较 dict（conformance 的 close 检查用）。"""
    arc1 = Arc2D(_as_point(c1, "c1"), r1, start1, sweep1)
    arc2 = Arc2D(_as_point(c2, "c2"), r2, start2, sweep2)
    kind, hits, contained = intersect_arc_arc(arc1, arc2)
    return {"kind": kind, "hits": [dict(h) for h in hits], "contained": contained}


def arc_arc_intersection_report(
    c1: Sequence[float],
    r1: float,
    c2: Sequence[float],
    r2: float,
) -> dict:
    """JSON 字面量入口：整圆-整圆求交的可比较 dict。"""
    kind, hits, contained = intersect_circles(c1, r1, c2, r2)
    return {"kind": kind, "hits": [dict(h) for h in hits], "contained": contained}
