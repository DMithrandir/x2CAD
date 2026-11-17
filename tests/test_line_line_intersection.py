"""线段求交的 oracle：解析交点、精确有理数参考、共线重叠、端点接触、对称与退化拒绝。"""

import math
import random
from fractions import Fraction

import pytest

from operators.line_line_intersection.impl import (
    SegmentIntersection,
    intersect_segments,
    intersection_kind,
    intersection_point,
    overlap_intervals,
)
from primitives.bspline import DomainError


def _close(a, b, tol=1e-15):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def test_crossing_point_and_parameters():
    result = intersect_segments((0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0))
    assert result.kind == "point"
    assert result.point == pytest.approx((1.0, 1.0), abs=1e-15)
    assert _close(result.t, 0.5)
    assert _close(result.u, 0.5)


def test_endpoint_touch_on_second_segment():
    # 交点落在第一条线段内部、第二条线段的端点
    result = intersect_segments((0.0, 0.0), (2.0, 0.0), (1.0, 0.0), (1.0, 2.0))
    assert result.kind == "point"
    assert result.point == pytest.approx((1.0, 0.0), abs=1e-15)
    assert _close(result.t, 0.5)
    assert _close(result.u, 0.0)


def test_shared_endpoint_is_a_point():
    result = intersect_segments((0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (2.0, 2.0))
    assert result.kind == "point"
    assert result.point == pytest.approx((2.0, 0.0), abs=1e-15)
    assert _close(result.t, 1.0)
    assert _close(result.u, 0.0)


def test_parallel_segments_do_not_intersect():
    result = intersect_segments((0.0, 0.0), (2.0, 0.0), (0.0, 1.0), (2.0, 1.0))
    assert result.kind == "none"


def test_collinear_overlap_interval():
    result = intersect_segments((0.0, 0.0), (4.0, 0.0), (2.0, 0.0), (6.0, 0.0))
    assert result.kind == "overlap"
    assert result.t_interval == pytest.approx((0.5, 1.0), abs=1e-15)
    assert result.u_interval == pytest.approx((0.0, 0.5), abs=1e-15)


def test_collinear_overlap_preserves_antiparallel_correspondence():
    # 第二条线段反向：t 增大时 u 应减小，不能悄悄排序成递增
    result = intersect_segments((0.0, 0.0), (4.0, 0.0), (6.0, 0.0), (2.0, 0.0))
    assert result.kind == "overlap"
    assert result.t_interval == pytest.approx((0.5, 1.0), abs=1e-15)
    assert result.u_interval == pytest.approx((1.0, 0.5), abs=1e-15)


def test_collinear_touching_at_one_endpoint():
    result = intersect_segments((0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (4.0, 0.0))
    assert result.kind == "point"
    assert result.point == pytest.approx((2.0, 0.0), abs=1e-15)
    assert _close(result.t, 1.0)
    assert _close(result.u, 0.0)


def test_collinear_disjoint_segments():
    result = intersect_segments((0.0, 0.0), (2.0, 0.0), (3.0, 0.0), (5.0, 0.0))
    assert result.kind == "none"


def test_overlap_length_ratio_invariant():
    (t0, t1), (u0, u1) = overlap_intervals(
        (0.0, 0.0), (4.0, 0.0), (1.0, 0.0), (3.0, 0.0)
    )
    len1 = 4.0
    len2 = 2.0
    assert _close((t1 - t0) * len1, abs(u1 - u0) * len2, 1e-14)


def test_large_coordinates_stay_exact():
    big = 1e16
    result = intersect_segments((0.0, 0.0), (big, big), (0.0, big), (big, 0.0))
    assert result.kind == "point"
    assert result.point == pytest.approx((5e15, 5e15), rel=1e-15)
    assert _close(result.t, 0.5)
    assert _close(result.u, 0.5)


def test_near_parallel_intersection_outside_is_none():
    # 斜率差约 1e-15：交点落在两线段之外，精确判定必须给 none
    result = intersect_segments(
        (0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0 + 1e-15)
    )
    assert result.kind == "none"


def test_swap_symmetry():
    p, q, r, s = (0.0, 0.0), (3.0, 1.0), (0.0, 1.0), (2.0, -1.0)
    a = intersect_segments(p, q, r, s)
    b = intersect_segments(r, s, p, q)
    assert a.kind == b.kind == "point"
    assert a.point == pytest.approx(b.point, abs=1e-15)
    assert _close(a.t, b.u)
    assert _close(a.u, b.t)


def test_translation_and_scaling_covariance():
    p, q, r, s = (0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)
    base = intersect_segments(p, q, r, s)
    dx, dy, scale = 1000.0, -250.0, 3.0
    moved = intersect_segments(
        (p[0] + dx, p[1] + dy),
        (q[0] + dx, q[1] + dy),
        (r[0] + dx, r[1] + dy),
        (s[0] + dx, s[1] + dy),
    )
    assert moved.point == pytest.approx(
        (base.point[0] + dx, base.point[1] + dy), abs=1e-12
    )
    assert _close(moved.t, base.t)
    assert _close(moved.u, base.u)

    scaled = intersect_segments(
        (p[0] * scale, p[1] * scale),
        (q[0] * scale, q[1] * scale),
        (r[0] * scale, r[1] * scale),
        (s[0] * scale, s[1] * scale),
    )
    assert scaled.point == pytest.approx(
        (base.point[0] * scale, base.point[1] * scale), abs=1e-12
    )


def test_point_lies_on_both_segments():
    p, q, r, s = (0.0, 0.0), (4.0, 1.0), (0.0, 3.0), (5.0, -2.0)
    result = intersect_segments(p, q, r, s)
    assert result.kind == "point"

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    scale = max(1.0, math.hypot(q[0] - p[0], q[1] - p[1]))
    assert abs(cross(p, q, result.point)) <= 1e-12 * scale
    scale = max(1.0, math.hypot(s[0] - r[0], s[1] - r[1]))
    assert abs(cross(r, s, result.point)) <= 1e-12 * scale


def test_zero_length_segments_are_rejected():
    # 断言到具体是哪一条线段：否则共线分支的兜底报错会掩盖 S 族守卫被绕过
    with pytest.raises(DomainError, match="第一条线段退化为点"):
        intersect_segments((1.0, 1.0), (1.0, 1.0), (0.0, 0.0), (1.0, 0.0))
    with pytest.raises(DomainError, match="第二条线段退化为点"):
        intersect_segments((0.0, 0.0), (1.0, 0.0), (2.0, 2.0), (2.0, 2.0))


def test_non_finite_and_wrong_shape_are_rejected():
    with pytest.raises(DomainError):
        intersect_segments((0.0, float("nan")), (1.0, 0.0), (0.0, 0.0), (1.0, 1.0))
    with pytest.raises(DomainError):
        intersect_segments((0.0, 0.0), (float("inf"), 0.0), (0.0, 0.0), (1.0, 1.0))
    with pytest.raises(DomainError, match="二维点"):
        intersect_segments((0.0,), (1.0, 0.0), (0.0, 0.0), (1.0, 1.0))
    with pytest.raises(DomainError, match="二维点"):
        intersect_segments("ab", (1.0, 0.0), (0.0, 0.0), (1.0, 1.0))


def test_helpers_reject_wrong_kind():
    assert intersection_kind((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)) == "none"
    with pytest.raises(DomainError, match="不交于唯一"):
        intersection_point((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
    with pytest.raises(DomainError, match="不交于唯一"):
        intersection_point((0.0, 0.0), (2.0, 0.0), (1.0, 0.0), (3.0, 0.0))
    with pytest.raises(DomainError, match="没有共线重叠"):
        overlap_intervals((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
    with pytest.raises(DomainError, match="没有共线重叠"):
        overlap_intervals((0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0))


def test_result_object_validates_field_combinations():
    with pytest.raises(DomainError):
        SegmentIntersection("point")
    with pytest.raises(DomainError):
        SegmentIntersection("none", point=(0.0, 0.0))
    with pytest.raises(DomainError):
        SegmentIntersection("overlap", t_interval=(0.0, 1.0))
    with pytest.raises(DomainError):
        SegmentIntersection("bogus")


# ---------------------------------------------------------------- 独立参考实现


def _reference(p, q, r, s):
    """Fraction 上的独立实现：返回 (kind, payload)。只用整数/有理数比较。"""

    def pt(v):
        return (Fraction(v[0]), Fraction(v[1]))

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    P, Q, R, S = pt(p), pt(q), pt(r), pt(s)
    d1, d2, w = sub(Q, P), sub(S, R), sub(R, P)
    den = cross(d1, d2)
    if den != 0:
        t = cross(w, d2) / den
        u = cross(w, d1) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return ("point", (float(P[0] + t * d1[0]), float(P[1] + t * d1[1])), float(t), float(u))
        return ("none",)
    if cross(d1, w) != 0:
        return ("none",)
    axis = 0 if P[0] != Q[0] else 1
    a0, a1, b0, b1 = P[axis], Q[axis], R[axis], S[axis]
    sp1, sp2 = a1 - a0, b1 - b0
    tr, ts = (b0 - a0) / sp1, (b1 - a0) / sp1
    lo = max(Fraction(0), min(tr, ts))
    hi = min(Fraction(1), max(tr, ts))
    if lo > hi:
        return ("none",)
    ulo = (a0 + lo * sp1 - b0) / sp2
    uhi = (a0 + hi * sp1 - b0) / sp2
    if lo == hi:
        return (
            "point",
            (float(P[0] + lo * (Q[0] - P[0])), float(P[1] + lo * (Q[1] - P[1]))),
            float(lo),
            float(ulo),
        )
    return ("overlap", (float(lo), float(hi)), (float(ulo), float(uhi)))


def test_differential_against_rational_reference():
    rng = random.Random(20261118)
    for _ in range(250):
        pts = [
            (float(rng.randint(-8, 8)), float(rng.randint(-8, 8))) for _ in range(4)
        ]
        p, q, r, s = pts
        if p == q or r == s:
            continue
        got = intersect_segments(p, q, r, s)
        want = _reference(p, q, r, s)
        assert got.kind == want[0], (p, q, r, s)
        if want[0] == "point":
            assert got.point == pytest.approx(want[1], abs=1e-15), (p, q, r, s)
            assert _close(got.t, want[2])
            assert _close(got.u, want[3])
        elif want[0] == "overlap":
            assert got.t_interval == pytest.approx(want[1], abs=1e-15), (p, q, r, s)
            assert got.u_interval == pytest.approx(want[2], abs=1e-15), (p, q, r, s)
