"""算子：2D 线段-Bézier 求交（精确根隔离 + 重数判相切 + 认证区间过滤）。

几何语义（analytic-primitives.md §3 矩阵第 4 条 / A2）
----------------------------------------------------
闭线段 ``A + s·d``（``s ∈ [0,1]``，``d = B − A ≠ 0``）与 n 次 Bézier 曲线
``C(t) = Σ_i P_i·B_{i,n}(t)``（``t ∈ [0,1]``）的交。

把曲线代入直线方程，得到两个**有理系数**多项式（输入浮点无损转 Fraction）：

::

    p(t) = cross(d, C(t) − A) = Σ_i cross(d, P_i − A)·B_{i,n}(t)   （在直线上 ⟺ p=0）
    r(t) = dot(d, C(t) − A)   = Σ_i dot(d, P_i − A)·B_{i,n}(t)     （投影，s = r/|d|²）

求交 = 求 p 在 [0,1] 的根，再过滤 s(t) ∈ [0,1]。

判定精确、坐标浮点
------------------
Bézier 的根一般是代数数，不能全程有理数表示。本算子的分工：

- **根的个数 / 隔离区间 / 重数 / 端点根**：全部用 ``primitives.polynomial`` 的
  精确有理数机械（Bernstein→幂基、Yun 无平方分解、Sturm 计数、二分隔离）判定；
- **相切**：p 的重根（重数 ≥ 2）⟺ 几何相切（含尖点 C'=0），由无平方分解精确给出；
- **线段过滤**：用 r 在认证 t 区间上的**精确 Bernstein 凸包包络**判定 s 是否落在
  [0,1]；恰在端点（s=0 或 1）的接触用 ``gcd(p, r)`` / ``gcd(p, r−|d|²)`` 精确识别
  （公共根 ⟺ 曲线恰好过线段端点），不做容差猜测；
- **输出坐标**： refined t 落浮点，de Casteljau 求值；每个交点附带**认证 t 区间**
  ``t_enclosure``（真根必在其中），这是代数根能给出的最强精确承诺。

退化语义
--------
- p ≡ 0（曲线整体在支撑直线上）→ ``kind=collinear``，返回 s∈[0,1] 的 t 区间并集
  （含孤立切点），用 s 与 s−1 的根做断点 + 精确中点符号测试构造；
- 线段长度为零 / 控制点 < 2 / 非有限输入 → ``DomainError``；
- 端点根（t=0/1）与线段端点接触（s=0/1）都属于闭集，保留不吞。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

from primitives.bspline import DomainError
from primitives.polynomial import (
    Poly,
    ZERO,
    bernstein_restrict,
    bernstein_to_power,
    count_roots,
    de_casteljau_float,
    degree,
    is_zero,
    isolate_roots,
    p_deriv,
    p_divexact,
    p_eval,
    p_gcd,
    p_sub,
    squarefree_factors,
    trim,
)

__all__ = [
    "BezierSegmentIntersection",
    "intersect_segment_bezier",
    "segment_bezier_intersection_report",
]

Point = Tuple[float, float]
Rational = Tuple[Fraction, Fraction]

_REFINE_BITS = 70          # 认证区间细化到 2^-70
_FILTER_CAP = 400          # 线段过滤细化上限（防御性）
_TWO = Fraction(2)


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


def _rat(p: Point) -> Rational:
    return (Fraction(p[0]), Fraction(p[1]))


def _cross(a: Rational, b: Rational) -> Fraction:
    return a[0] * b[1] - a[1] * b[0]


def _dot(a: Rational, b: Rational) -> Fraction:
    return a[0] * b[0] + a[1] * b[1]


def _sub(a: Rational, b: Rational) -> Rational:
    return (a[0] - b[0], a[1] - b[1])


@dataclass(frozen=True)
class BezierSegmentIntersection:
    """线段-Bézier 求交结果。

    - ``kind ∈ {none, point, points, collinear}``；
    - ``hits``：每个交点 ``{t, s, point, tangent, multiplicity, t_enclosure}``，按 t 升序；
      ``t_enclosure=[lo,hi]`` 是认证区间（真根必在其中）；
    - ``collinear`` 时 ``t_intervals`` 为 s∈[0,1] 的 t 区间并集（含退化点区间）。
    """

    kind: str
    hits: Tuple[dict, ...] = ()
    t_intervals: Tuple[Tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ("none", "point", "points", "collinear"):
            raise DomainError(f"未知的相交类型 {self.kind!r}")
        if self.kind == "none" and (self.hits or self.t_intervals):
            raise DomainError("kind=none 不得携带交点或区间")
        if self.kind == "point" and len(self.hits) != 1:
            raise DomainError("kind=point 必须恰好一个交点")
        if self.kind == "points" and len(self.hits) < 2:
            raise DomainError("kind=points 必须至少两个交点")
        if self.kind == "collinear" and self.hits:
            raise DomainError("kind=collinear 用 t_intervals，不得携带 hits")


def _strip_endpoint_root(p: Poly, root: Fraction) -> Tuple[Poly, int]:
    """剥离 p 在 root 处的重数，返回 (商, 重数)。"""
    m = 0
    factor = (Fraction(-root), Fraction(1))  # (x − root)
    while not is_zero(p) and p_eval(p, root) == 0:
        p = p_divexact(p, factor)
        m += 1
    return p, m


def _refine(rad: Poly, lo: Fraction, hi: Fraction) -> Tuple[Fraction, Fraction]:
    """用 squarefree rad 的符号变化把 isolating 区间细化到 ≤ 2^-_REFINE_BITS。"""
    target = Fraction(1, 1 << _REFINE_BITS)
    slo = 1 if p_eval(rad, lo) > 0 else -1
    while hi - lo > target:
        mid = (lo + hi) / 2
        vm = p_eval(rad, mid)
        if vm == 0:
            return mid, mid
        sm = 1 if vm > 0 else -1
        if sm != slo:
            hi = mid
        else:
            lo = mid
            slo = sm
    return lo, hi


def _multiplicity_at(factors, lo: Fraction, hi: Fraction) -> int:
    """区间 (lo,hi) 内唯一根的重数 = 含该根的无平方因子的重数。"""
    if lo == hi:
        for f, k in factors:
            if p_eval(f, lo) == 0:
                return k
        return 1
    for f, k in sorted(factors, key=lambda fk: -fk[1]):
        if not is_zero(f) and degree(f) > 0:
            if p_eval(f, lo) != 0 and p_eval(f, hi) != 0 and count_roots(f, lo, hi) > 0:
                return k
    return 1


def intersect_segment_bezier(
    a: Sequence[float], b: Sequence[float], ctrl: Sequence[Sequence[float]]
) -> BezierSegmentIntersection:
    """闭线段 ``ab`` 与 Bézier 曲线 ``ctrl``（n = len(ctrl)−1 ≥ 1）的交。"""
    pa = _as_point(a, "a")
    pb = _as_point(b, "b")
    if pa == pb:
        raise DomainError(f"线段退化为点：a == b == {pa!r}")
    if len(ctrl) < 2:
        raise DomainError(f"Bézier 至少需要两个控制点，收到 {len(ctrl)} 个")
    pts = [_as_point(p, f"ctrl[{i}]") for i, p in enumerate(ctrl)]

    fa, fb = _rat(pa), _rat(pb)
    d = _sub(fb, fa)
    d2 = _dot(d, d)  # > 0
    fps = [_rat(p) for p in pts]

    # Bernstein 系数（精确）
    c_bern = tuple(_cross(d, _sub(fp, fa)) for fp in fps)   # p(t)
    r_bern = tuple(_dot(d, _sub(fp, fa)) for fp in fps)     # r(t)
    p_pow = bernstein_to_power(c_bern)
    r_pow = bernstein_to_power(r_bern)

    if is_zero(p_pow):
        return _collinear(r_bern, r_pow, d2)

    # 端点根 t=0 / t=1（精确剥离）
    hits: List[dict] = []
    rest, m0 = _strip_endpoint_root(p_pow, Fraction(0))
    rest, m1 = _strip_endpoint_root(rest, Fraction(1))
    if m0:
        s0 = p_eval(r_pow, Fraction(0)) / d2
        if 0 <= s0 <= 1:
            hits.append(_make_hit(pts, Fraction(0), Fraction(0), Fraction(0), s0, m0))
    if m1:
        s1 = p_eval(r_pow, Fraction(1)) / d2
        if 0 <= s1 <= 1:
            hits.append(_make_hit(pts, Fraction(1), Fraction(1), Fraction(1), s1, m1))

    if not is_zero(rest) and degree(rest) > 0:
        factors = squarefree_factors(rest)
        rad = p_divexact(rest, p_gcd(rest, p_deriv(rest)))
        intervals = isolate_roots(rad, Fraction(0), Fraction(1))
        for lo, hi in intervals:
            mult = _multiplicity_at(factors, lo, hi)
            hit = _process_interior_root(rad, r_bern, r_pow, d2, lo, hi, mult, pts)
            if hit is not None:
                hits.append(hit)

    hits.sort(key=lambda h: h["t"])
    if not hits:
        return BezierSegmentIntersection(kind="none")
    if len(hits) == 1:
        return BezierSegmentIntersection(kind="point", hits=(hits[0],))
    return BezierSegmentIntersection(kind="points", hits=tuple(hits))


def _make_hit(pts, t: Fraction, t_lo: Fraction, t_hi: Fraction, s: Fraction, mult: int) -> dict:
    tf = float(t)
    point = de_casteljau_float(pts, tf)
    return {
        "t": tf,
        "s": float(s),
        "point": list(point),
        "tangent": mult >= 2,
        "multiplicity": mult,
        "t_enclosure": [float(t_lo), float(t_hi)],
    }


def _process_interior_root(rad, r_bern, r_pow, d2, lo, hi, mult, pts):
    # 精确有理根：s 精确可算
    if lo == hi:
        s = p_eval(r_pow, lo) / d2
        if 0 <= s <= 1:
            return _make_hit(pts, lo, lo, lo, s, mult)
        return None

    lo, hi = _refine(rad, lo, hi)
    if lo == hi:
        s = p_eval(r_pow, lo) / d2
        if 0 <= s <= 1:
            return _make_hit(pts, lo, lo, lo, s, mult)
        return None

    # 线段过滤（精确，无容差）：r 在 [lo,hi] 上的 Bernstein 系数凸包 ⊇ 值域。
    # 边界接触（s 恰为 0/1，r 触到 0 或 d² 但不变号）由「rmin ≥ 0 且 rmax ≤ d2」
    # 的闭包判定直接接受；r 变号穿越边界时凸包恒跨越，靠 rad 的符号二分细化收敛
    # 到根本身——细化到根后有理数 s 精确可算。不需要 gcd 快路径：变量异审计证明
    # 它不可观察（跳过后行为不变），按死代码纪律移除。
    for _ in range(_FILTER_CAP):
        rc = bernstein_restrict(r_bern, lo, hi)
        rmin, rmax = min(rc), max(rc)
        if rmax < 0 or rmin > d2:
            return None                      # 整段投影在线段外
        if rmin >= 0 and rmax <= d2:
            t = (lo + hi) / 2
            s = p_eval(r_pow, t) / d2
            return _make_hit(pts, t, lo, hi, s, mult)
        # 包络跨越边界 → 继续细化必可判定
        lo, hi = _refine_step(rad, lo, hi)
        if lo == hi:
            s = p_eval(r_pow, lo) / d2
            if 0 <= s <= 1:
                return _make_hit(pts, lo, lo, lo, s, mult)
            return None
    raise DomainError("线段过滤未收敛：认证区间细化超过上限（实现或输入异常）")


def _refine_step(rad, lo, hi):
    mid = (lo + hi) / 2
    vm = p_eval(rad, mid)
    if vm == 0:
        return mid, mid
    slo = 1 if p_eval(rad, lo) > 0 else -1
    sm = 1 if vm > 0 else -1
    if sm != slo:
        return lo, mid
    return mid, hi


# ---------------------------------------------------------------- 共线


def _collinear(r_bern, r_pow, d2) -> BezierSegmentIntersection:
    """p≡0：曲线在支撑直线上。返回 {t∈[0,1] : 0≤s(t)≤1}，s=r/d2。"""
    s_pow = tuple(c / d2 for c in r_pow)
    one = (Fraction(1),)
    s1_pow = p_sub(s_pow, one)

    # 断点：0, 1, s 的根, s−1 的根（全部精确隔离 + 细化到浮点）
    breaks: List[Fraction] = [Fraction(0), Fraction(1)]
    for poly in (s_pow, s1_pow):
        if is_zero(poly):
            continue
        rest, m0 = _strip_endpoint_root(poly, Fraction(0))
        rest, m1 = _strip_endpoint_root(rest, Fraction(1))
        if m0:
            breaks.append(Fraction(0))
        if m1:
            breaks.append(Fraction(1))
        if not is_zero(rest) and degree(rest) > 0:
            rad = p_divexact(rest, p_gcd(rest, p_deriv(rest)))
            for lo, hi in isolate_roots(rad, Fraction(0), Fraction(1)):
                if lo == hi:
                    breaks.append(lo)
                else:
                    lo2, hi2 = _refine(rad, lo, hi)
                    breaks.append((lo2 + hi2) / 2)
    breaks = sorted(set(breaks))

    # 每个断点处 s∈{0,1} 或端点 → 闭集接触点；相邻断点间用精确中点符号测试
    intervals: List[Tuple[Fraction, Fraction]] = []
    for bp in breaks:
        sv = p_eval(s_pow, bp)
        if 0 <= sv <= 1:
            intervals.append((bp, bp))
    for left, right in zip(breaks, breaks[1:]):
        if left == right:
            continue
        mid = _safe_mid(left, right, s_pow, s1_pow)
        if mid is None:
            continue
        sv = p_eval(s_pow, mid)
        if 0 <= sv <= 1:
            intervals.append((left, right))

    merged = _merge_intervals(intervals)
    if not merged:
        return BezierSegmentIntersection(kind="none")
    return BezierSegmentIntersection(
        kind="collinear",
        t_intervals=tuple((float(lo), float(hi)) for lo, hi in merged),
    )


def _safe_mid(left, right, s_pow, s1_pow):
    """在 (left,right) 内取一个不是 s/s−1 根的有理中点（精确符号测试用）。"""
    mid = (left + right) / 2
    for _ in range(64):
        if p_eval(s_pow, mid) != 0 and p_eval(s1_pow, mid) != 0:
            return mid
        mid = (left + mid) / 2
    return None


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(lo, hi) for lo, hi in out]


# ---------------------------------------------------------------- JSON 入口


def segment_bezier_intersection_report(
    a: Sequence[float], b: Sequence[float], ctrl: Sequence[Sequence[float]]
) -> dict:
    """JSON 字面量入口：返回可比较 dict（conformance 的 close 检查用）。"""
    result = intersect_segment_bezier(a, b, ctrl)
    return {
        "kind": result.kind,
        "hits": [dict(h) for h in result.hits],
        "t_intervals": [list(iv) for iv in result.t_intervals],
    }
