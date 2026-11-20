"""圆弧/圆-圆弧/圆求交的 oracle：解析真值、六分类、根轴坐标、弧段过滤。"""

import math

import pytest

from operators.arc_arc_intersection.impl import (
    Arc2D,
    arc_arc_intersection_report,
    intersect_arc_arc,
    intersect_circles,
)
from operators.segment_arc_intersection.impl import Arc2D as _ArcRef  # noqa: F401  同一类型
from primitives.bspline import DomainError

PI = math.pi
HALF_PI = math.pi / 2


def _on_circle(pt, c, r, tol=1e-9):
    return math.hypot(pt[0] - c[0], pt[1] - c[1]) == pytest.approx(r, abs=tol)


# ---------------------------------------------------------------- 六分类


def test_two_points_symmetric():
    kind, hits, contained = intersect_circles([0.0, 0.0], 2.0, [3.0, 0.0], 2.0)
    assert kind == "points" and contained is False
    assert len(hits) == 2
    k = math.sqrt(4.0 - 2.25)  # √1.75
    pts = sorted(h["point"] for h in hits)
    assert pts[1] == pytest.approx([1.5, k], abs=1e-9)
    assert pts[0] == pytest.approx([1.5, -k], abs=1e-9)
    for h in hits:
        assert _on_circle(h["point"], (0.0, 0.0), 2.0)
        assert _on_circle(h["point"], (3.0, 0.0), 2.0)
        assert h["tangent"] is False
    # 按 theta1 升序
    assert hits[0]["theta1"] < hits[1]["theta1"]


def test_external_tangency():
    kind, hits, contained = intersect_circles([0.0, 0.0], 1.0, [2.0, 0.0], 1.0)
    assert kind == "point" and contained is False
    h = hits[0]
    assert h["point"] == pytest.approx([1.0, 0.0], abs=1e-9)
    assert h["tangent"] is True
    assert h["theta1"] == pytest.approx(0.0, abs=1e-9)
    assert h["theta2"] == pytest.approx(PI, abs=1e-9)


def test_internal_tangency():
    # 大圆 r=3 圆心在原点，小圆 r=1 圆心在 (2,0)：内切于 (3,0)
    kind, hits, contained = intersect_circles([0.0, 0.0], 3.0, [2.0, 0.0], 1.0)
    assert kind == "point" and contained is False
    h = hits[0]
    assert h["point"] == pytest.approx([3.0, 0.0], abs=1e-9)
    assert h["tangent"] is True


def test_separate():
    kind, hits, contained = intersect_circles([0.0, 0.0], 1.0, [5.0, 0.0], 1.0)
    assert kind == "none" and contained is False and hits == ()


def test_containment():
    kind, hits, contained = intersect_circles([0.0, 0.0], 5.0, [1.0, 0.0], 1.0)
    assert kind == "none" and contained is True
    # 贴边内含：d 严格小于 |r1-r2| 但接近。守卫被跳过时这类输入会进根轴分支，
    # h² = r1² - a² 在 a>r1 时为负 —— math.sqrt 抛 ValueError（而非静默坏点）。
    # 该测试把"内含必须走守卫"变成可变异验证的行为。
    kind2, hits2, contained2 = intersect_circles([0.0, 0.0], 3.0, [0.001, 0.0], 1.0)
    assert kind2 == "none" and contained2 is True and hits2 == ()


def test_concentric_overlap_and_containment():
    kind, hits, contained = intersect_circles([0.0, 0.0], 1.0, [0.0, 0.0], 1.0)
    assert kind == "overlap" and hits == ()
    kind, hits, contained = intersect_circles([0.0, 0.0], 2.0, [0.0, 0.0], 1.0)
    assert kind == "none" and contained is True


# ---------------------------------------------------------------- 根轴坐标


def test_radical_axis_coordinates_off_center():
    # C1=(1,2) r=5, C2=(6,2) r=3：a = (25+25-9)/(2·5) = 4.1；h² = 25-16.81
    kind, hits, _ = intersect_circles([1.0, 2.0], 5.0, [6.0, 2.0], 3.0)
    assert kind == "points"
    h2 = 25.0 - 4.1**2
    k = math.sqrt(h2)
    expected = [(5.1, 2.0 + k), (5.1, 2.0 - k)]
    got = sorted(h["point"] for h in hits)
    assert got[0] == pytest.approx(expected[1], abs=1e-9)
    assert got[1] == pytest.approx(expected[0], abs=1e-9)
    for h in hits:
        assert _on_circle(h["point"], (1.0, 2.0), 5.0)
        assert _on_circle(h["point"], (6.0, 2.0), 3.0)


def test_diagonal_orientation_hits():
    # 圆心沿对角线：验证非水平布局的根轴
    c1, c2 = (0.0, 0.0), (4.0, 4.0)
    kind, hits, _ = intersect_circles(c1, math.sqrt(10.0), c2, math.sqrt(10.0))
    assert kind == "points"
    mid = (2.0, 2.0)
    k = math.sqrt(10.0 - 8.0)  # a = d/2, h² = 10 - 8
    # 根轴过 mid 垂直于 (1,1) 方向 → 方向 (1,-1)/√2
    for h in hits:
        assert _on_circle(h["point"], c1, math.sqrt(10.0))
        assert _on_circle(h["point"], c2, math.sqrt(10.0))
        # 到 mid 的距离应为 k
        assert math.hypot(h["point"][0] - mid[0], h["point"][1] - mid[1]) == pytest.approx(k, abs=1e-9)


# ---------------------------------------------------------------- 弧段过滤


def test_arc_arc_quarter_overlap_both_kept():
    # 两个半径 2、圆心 (0,0) 与 (3,0) 的圆交于 (1.5, ±√1.75)。
    # 交点相对 C2 的极角约 ±138.6°；第二条弧取从 180° 逆时针扫 330° 的大弧
    # （覆盖 180°→360°→90°，即同时含 +138.6° 与 -138.6°≡221.4°）。
    a1 = Arc2D(center=(0.0, 0.0), radius=2.0, start_angle=0.0, sweep=2.0 * PI)
    a2 = Arc2D(center=(3.0, 0.0), radius=2.0, start_angle=PI, sweep=(330.0 / 180.0) * PI)
    kind, hits, contained = intersect_arc_arc(a1, a2)
    assert kind == "points"
    assert len(hits) == 2
    for h in hits:
        assert h["point"][0] == pytest.approx(1.5, abs=1e-9)


def test_arc_arc_filters_to_one_point():
    # 整圆交两点 (1.5, ±√1.75)；交点相对 C2 的极角约 +138.6° 与 -138.6°（≡221.4°）。
    # 第二条弧取 90° → 162°（sweep=72°），只覆盖上交点。
    a1 = Arc2D(center=(0.0, 0.0), radius=2.0, start_angle=0.0, sweep=2.0 * PI)
    a2 = Arc2D(center=(3.0, 0.0), radius=2.0, start_angle=HALF_PI, sweep=0.4 * PI)
    kind, hits, contained = intersect_arc_arc(a1, a2)
    assert kind == "point"
    k = math.sqrt(4.0 - 2.25)
    assert hits[0]["point"] == pytest.approx([1.5, k], abs=1e-9)


def test_arc_arc_none_when_arcs_miss():
    a1 = Arc2D(center=(0.0, 0.0), radius=2.0, start_angle=PI, sweep=HALF_PI)  # 第二象限
    a2 = Arc2D(center=(3.0, 0.0), radius=2.0, start_angle=-HALF_PI, sweep=HALF_PI)  # 第四象限
    kind, hits, contained = intersect_arc_arc(a1, a2)
    assert kind == "none" and hits == ()


def test_arc_arc_overlap_for_full_circles():
    a1 = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=2.0 * PI)
    a2 = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=PI, sweep=2.0 * PI)
    kind, hits, contained = intersect_arc_arc(a1, a2)
    assert kind == "overlap"


# ---------------------------------------------------------------- JSON 入口


def test_report_entry_matches_core():
    core = intersect_circles([0.0, 0.0], 2.0, [3.0, 0.0], 2.0)
    report = arc_arc_intersection_report([0.0, 0.0], 2.0, [3.0, 0.0], 2.0)
    assert report["kind"] == core[0]
    assert len(report["hits"]) == len(core[1])


# ---------------------------------------------------------------- 退化拒绝


def test_bad_radius_rejected():
    with pytest.raises(DomainError, match="半径"):
        intersect_circles([0.0, 0.0], 0.0, [1.0, 0.0], 1.0)
    with pytest.raises(DomainError, match="半径"):
        intersect_circles([0.0, 0.0], 1.0, [1.0, 0.0], -1.0)
    with pytest.raises(DomainError, match="半径"):
        intersect_circles([0.0, 0.0], float("inf"), [1.0, 0.0], 1.0)


def test_non_finite_center_rejected():
    with pytest.raises(DomainError):
        intersect_circles([0.0, float("nan")], 1.0, [1.0, 0.0], 1.0)
    with pytest.raises(DomainError, match="二维点"):
        intersect_circles([0.0, 0.0, 0.0], 1.0, [1.0, 0.0], 1.0)


def test_bad_sweep_in_arc_entry_rejected():
    with pytest.raises(DomainError, match="扫角"):
        Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=2.5 * PI)


# ---------------------------------------------------------------- 不变量


def test_hits_sorted_and_tangent_consistent():
    kind, hits, _ = intersect_circles([0.0, 0.0], 2.0, [3.0, 0.0], 2.0)
    assert hits[0]["theta1"] < hits[1]["theta1"]
    for h in hits:
        assert h["tangent"] is False
    _, thits, _ = intersect_circles([0.0, 0.0], 1.0, [2.0, 0.0], 1.0)
    assert thits[0]["tangent"] is True
