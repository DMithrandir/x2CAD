"""算子：2D 线段-线段求交（精确有理数判定 + 显式退化分类）。

几何语义
--------
两条**闭**线段 ``P0P1`` 与 ``Q0Q1`` 的相交结果只有三种：

- ``point``：唯一交点（横截、端点接触、T 形接触都归入这一类），给出
  交点坐标与两条线段上的参数 ``t, u ∈ [0, 1]``；
- ``overlap``：共线且重叠长度大于零，给出第一条线段上的参数区间
  ``t_interval``，以及与之对应的第二条线段参数区间 ``u_interval``
  （两条线段方向相反时 ``u_interval`` 是递减的，保留对应关系）；
- ``none``：不相交（平行、共线但不重叠、参数落在区间外）。

为什么用有理数 + 为什么必须给精确输出
------------------------------------
线段求交的分支全部依赖**符号**与**区间端点顺序**：平行判定、``t ∈ [0,1]``、
共线重叠的端点比较。浮点行列式在近共线（退化 N 族）输入上会翻转符号，
把"不相交"判成"相交"。本算子把输入浮点值无损转成 ``Fraction`` 后：
平行/共线判定、参数界判定、重叠区间排序都是精确的。

**关键契约（级联容差）**：只把结果舍入成 ``float`` 会在下一步反咬——
下一步的精确谓词会判"这个 float 交点不在原线段上"。因此 ``point`` 结果同时携带
``point_exact``（``Fraction`` 坐标），跨算子链必须传 ``point_exact`` / 用
``intersection_point_exact``；``point`` 的 float 坐标只用于展示、序列化与
需要容差的装配层。``point_on_segment_exact`` 是给下一层做精确包含判定的入口。

退化语义
--------
- 线段长度为零（两端点重合）→ ``DomainError``：没有方向，交点语义未定义；
- 共线重叠 → 返回 ``overlap`` 区间（不硬凑成单点）；
- 输入含 NaN/Inf 或不是二维点 → ``DomainError``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Sequence, Tuple

from primitives.bspline import DomainError

__all__ = [
    "SegmentIntersection",
    "intersect_segments",
    "intersection_kind",
    "intersection_point",
    "intersection_point_exact",
    "overlap_intervals",
    "point_on_segment_exact",
]

Point = Tuple[float, float]
Vector = Tuple[Fraction, Fraction]


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


def _rational(point: Point) -> Vector:
    return (Fraction(point[0]), Fraction(point[1]))


def _sub(a: Vector, b: Vector) -> Vector:
    return (a[0] - b[0], a[1] - b[1])


def _cross(a: Vector, b: Vector) -> Fraction:
    return a[0] * b[1] - a[1] * b[0]


@dataclass(frozen=True)
class SegmentIntersection:
    """求交结果：``kind`` 决定哪些字段有效。"""

    kind: str
    point: Optional[Point] = None
    point_exact: Optional[Tuple[Fraction, Fraction]] = None
    t: Optional[float] = None
    u: Optional[float] = None
    t_interval: Optional[Tuple[float, float]] = None
    u_interval: Optional[Tuple[float, float]] = None

    def __post_init__(self) -> None:
        if self.kind == "none":
            if any(
                v is not None
                for v in (self.point, self.point_exact, self.t, self.u, self.t_interval, self.u_interval)
            ):
                raise DomainError("kind=none 的结果不得携带交点或区间")
        elif self.kind == "point":
            if self.point is None or self.point_exact is None or self.t is None or self.u is None:
                raise DomainError("kind=point 的结果必须带 point/point_exact/t/u")
            if self.t_interval is not None or self.u_interval is not None:
                raise DomainError("kind=point 的结果不得带参数区间")
        elif self.kind == "overlap":
            if self.t_interval is None or self.u_interval is None:
                raise DomainError("kind=overlap 的结果必须带 t_interval/u_interval")
            if self.point is not None or self.point_exact is not None or self.t is not None or self.u is not None:
                raise DomainError("kind=overlap 的结果不得带单点字段")
        else:
            raise DomainError(f"未知的相交类型 {self.kind!r}")


def intersect_segments(
    p: Sequence[float],
    q: Sequence[float],
    r: Sequence[float],
    s: Sequence[float],
) -> SegmentIntersection:
    """求两条闭线段 ``pq`` 与 ``rs`` 的交（精确判定）。"""
    first = _as_point(p, "p")
    second = _as_point(q, "q")
    third = _as_point(r, "r")
    fourth = _as_point(s, "s")
    if first == second:
        raise DomainError(f"第一条线段退化为点：p == q == {first!r}")
    if third == fourth:
        raise DomainError(f"第二条线段退化为点：r == s == {third!r}")

    pf, qf, rf, sf = map(_rational, (first, second, third, fourth))
    d1 = _sub(qf, pf)
    d2 = _sub(sf, rf)
    w = _sub(rf, pf)
    denom = _cross(d1, d2)

    if denom != 0:
        t = _cross(w, d2) / denom
        u = _cross(w, d1) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            x = pf[0] + t * d1[0]
            y = pf[1] + t * d1[1]
            # 后置不变量：同一点用第二条线段重算必须一致（代数错位当场暴露）
            if rf[0] + u * d2[0] != x or rf[1] + u * d2[1] != y:
                raise DomainError("后置不变量失败：交点参数与坐标不自洽")
            return SegmentIntersection(
                kind="point",
                point=(float(x), float(y)),
                point_exact=(x, y),
                t=float(t),
                u=float(u),
            )
        return SegmentIntersection(kind="none")

    # 平行：不共线则无交；共线转一维区间求交
    if _cross(d1, w) != 0:
        return SegmentIntersection(kind="none")
    return _collinear_overlap(pf, qf, rf, sf)


def _collinear_overlap(pf: Vector, qf: Vector, rf: Vector, sf: Vector) -> SegmentIntersection:
    """四条点共线：投影到变化最大的坐标轴，化为一维闭区间求交。"""
    axis = 0 if pf[0] != qf[0] else 1
    a0, a1 = pf[axis], qf[axis]
    b0, b1 = rf[axis], sf[axis]
    span1 = a1 - a0
    span2 = b1 - b0
    if span2 == 0:  # pragma: no cover - 共线且两条线段都非退化时不可能进入
        raise DomainError("共线判定失败：第二条线段在投影轴上退化为点")

    t_r = (b0 - a0) / span1
    t_s = (b1 - a0) / span1
    lo_t = max(Fraction(0), min(t_r, t_s))
    hi_t = min(Fraction(1), max(t_r, t_s))
    if lo_t > hi_t:
        return SegmentIntersection(kind="none")

    # u 与 t 的对应：a0 + t·span1 = b0 + u·span2
    u_lo = (a0 + lo_t * span1 - b0) / span2
    u_hi = (a0 + hi_t * span1 - b0) / span2
    if lo_t == hi_t:
        x = pf[0] + lo_t * (qf[0] - pf[0])
        y = pf[1] + lo_t * (qf[1] - pf[1])
        return SegmentIntersection(
            kind="point",
            point=(float(x), float(y)),
            point_exact=(x, y),
            t=float(lo_t),
            u=float(u_lo),
        )
    return SegmentIntersection(
        kind="overlap",
        t_interval=(float(lo_t), float(hi_t)),
        u_interval=(float(u_lo), float(u_hi)),
    )


def intersection_kind(
    p: Sequence[float],
    q: Sequence[float],
    r: Sequence[float],
    s: Sequence[float],
) -> str:
    """只返回相交类型（conformance 与装配阶段的分支入口）。"""
    return intersect_segments(p, q, r, s).kind


def intersection_point(
    p: Sequence[float],
    q: Sequence[float],
    r: Sequence[float],
    s: Sequence[float],
) -> Point:
    """返回唯一交点的浮点坐标；不是 ``point`` 类型时显式拒绝（不返回近似点）。

    跨算子链请改用 :func:`intersection_point_exact`：浮点坐标在下一步的精确谓词里
    可能不再落在原线段上（级联容差）。
    """
    result = intersect_segments(p, q, r, s)
    if result.kind != "point" or result.point is None:
        raise DomainError(f"两条线段不交于唯一一点（kind={result.kind}）")
    return result.point


def intersection_point_exact(
    p: Sequence[float],
    q: Sequence[float],
    r: Sequence[float],
    s: Sequence[float],
) -> Tuple[Fraction, Fraction]:
    """返回唯一交点的**精确有理数坐标**；跨算子链使用这个入口。"""
    result = intersect_segments(p, q, r, s)
    if result.kind != "point" or result.point_exact is None:
        raise DomainError(f"两条线段不交于唯一一点（kind={result.kind}）")
    return result.point_exact


def point_on_segment_exact(
    p: Sequence[float], q: Sequence[float], point: Sequence[float]
) -> bool:
    """精确判定 ``point`` 是否在闭线段 ``pq`` 上（用于精确求交结果的下一层校验）。

    输入点可以是 ``float`` 或 ``Fraction``；``float`` 会按其二进制值无损转有理数，
    所以传 ``intersection_point_exact`` 的结果才保证不引入新的舍入。
    """
    pf = _rational(_as_point(p, "p"))
    qf = _rational(_as_point(q, "q"))
    try:
        x = (Fraction(point[0]), Fraction(point[1]))
    except (TypeError, ValueError, IndexError) as exc:
        raise DomainError(f"point 必须是二维坐标，收到 {point!r}") from exc
    d = _sub(qf, pf)
    w = _sub(x, pf)
    if _cross(d, w) != 0:
        return False
    dot = d[0] * w[0] + d[1] * w[1]
    return 0 <= dot <= d[0] * d[0] + d[1] * d[1]


def overlap_intervals(
    p: Sequence[float],
    q: Sequence[float],
    r: Sequence[float],
    s: Sequence[float],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """返回共线重叠区间 ``(t_interval, u_interval)``；不是重叠时显式拒绝。"""
    result = intersect_segments(p, q, r, s)
    if result.kind != "overlap" or result.t_interval is None or result.u_interval is None:
        raise DomainError(f"两条线段没有共线重叠区段（kind={result.kind}）")
    return result.t_interval, result.u_interval
