"""线段-圆弧求交的 oracle：解析真值、精确判号、弧段过滤、退化拒绝。"""

import math

import pytest

from operators.segment_arc_intersection.impl import (
    Arc2D,
    arc_contains_angle_exact,
    intersect_segment_arc,
    intersect_segment_circle,
)
from primitives.bspline import DomainError

PI = math.pi
HALF_PI = math.pi / 2


# ---------------------------------------------------------------- 整圆


def test_chord_two_points_symmetric():
    result = intersect_segment_circle((-2.0, 0.0), (2.0, 0.0), (0.0, 0.0), 1.0)
    assert result.kind == "points"
    (h1, h2) = result.hits
    assert h1["point"] == pytest.approx((-1.0, 0.0), abs=1e-12)
    assert h2["point"] == pytest.approx((1.0, 0.0), abs=1e-12)
    assert h1["t"] == pytest.approx(0.25, abs=1e-12)
    assert h2["t"] == pytest.approx(0.75, abs=1e-12)
    assert h1["t"] < h2["t"]
    assert not h1["tangent"] and not h2["tangent"]
    # 圆不变量：交点到圆心距离 = r
    for h in result.hits:
        d = math.hypot(h["point"][0], h["point"][1])
        assert d == pytest.approx(1.0, abs=1e-12)


def test_tangent_single_point():
    # 线段 y=1 与单位圆相切于 (0,1)
    result = intersect_segment_circle((-2.0, 1.0), (2.0, 1.0), (0.0, 0.0), 1.0)
    assert result.kind == "point"
    h = result.hits[0]
    assert h["point"] == pytest.approx((0.0, 1.0), abs=1e-12)
    assert h["tangent"] is True
    assert h["t"] == pytest.approx(0.5, abs=1e-12)


def test_tangent_at_segment_endpoint():
    # 线段终点恰在圆上（半径 = 距离）：判别式应为 0，端点是切点
    result = intersect_segment_circle((0.0, 0.0), (1.0, 0.0), (1.0, 0.0), 1.0)
    # 圆心在 (1,0) 半径 1：起点 (0,0) 在圆上，t=0 是唯一根？c = |P0-C|^2 - r^2 = 0，b = 2 d·w = -2
    # a = 1 → t = 0 (重根) 或 t = 2。t=0 在段内 → 单点
    assert result.kind in ("point", "points")
    assert result.hits[0]["t"] == pytest.approx(0.0, abs=1e-12)
    assert result.hits[0]["point"] == pytest.approx((0.0, 0.0), abs=1e-12)


def test_miss_and_containment():
    # 相离：线段在圆外
    miss = intersect_segment_circle((3.0, 0.0), (4.0, 0.0), (0.0, 0.0), 1.0)
    assert miss.kind == "none" and miss.contained is False
    # 包含：线段整体在圆内，无交点但 contained=True
    inside = intersect_segment_circle((0.2, 0.0), (0.5, 0.0), (0.0, 0.0), 1.0)
    assert inside.kind == "none" and inside.contained is True


def test_entry_exit_through_circle():
    # 穿过：t 较小的点是入点（靠近起点）
    result = intersect_segment_circle((0.0, 0.0), (0.0, 10.0), (0.0, 5.0), 2.0)
    assert result.kind == "points"
    h1, h2 = result.hits
    assert h1["t"] == pytest.approx(0.3, abs=1e-12)
    assert h2["t"] == pytest.approx(0.7, abs=1e-12)
    assert h1["point"] == pytest.approx((0.0, 3.0), abs=1e-12)
    assert h2["point"] == pytest.approx((0.0, 7.0), abs=1e-12)


# ---------------------------------------------------------------- 弧段


def _quarter_arc() -> Arc2D:
    return Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=HALF_PI)


def test_arc_filters_to_quarter():
    arc = _quarter_arc()
    # 水平线 y=0：与整圆交于 (-1,0) 与 (1,0)；只有 (1,0) 在第一象限弧上
    result = intersect_segment_arc((-2.0, 0.0), (2.0, 0.0), arc)
    assert result.kind == "point"
    assert result.hits[0]["point"] == pytest.approx((1.0, 0.0), abs=1e-12)
    assert result.hits[0]["t"] == pytest.approx(0.75, abs=1e-12)


def test_arc_quarter_crossing_exact_values():
    arc = _quarter_arc()
    result = intersect_segment_arc((-1.0, -1.0), (1.0, 1.0), arc)
    assert result.kind == "point"  # 只有 (k,k) 落在 0..90° 弧上
    k = math.sqrt(0.5)
    assert result.hits[0]["point"] == pytest.approx((k, k), abs=1e-12)


def test_cw_arc_filters_by_orientation():
    # 顺时针弧：从 90° 扫到 0°（sweep<0），覆盖第一象限
    arc = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=HALF_PI, sweep=-HALF_PI)
    result = intersect_segment_arc((-2.0, 0.0), (2.0, 0.0), arc)
    assert result.kind == "point"
    assert result.hits[0]["point"] == pytest.approx((1.0, 0.0), abs=1e-12)
    # 逆时针弧 0→90 不包含 (1,0)?? 它是弧起点，闭弧应包含；换 (−1,0) 不在
    ccw = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=HALF_PI)
    r2 = intersect_segment_arc((-2.0, 0.0), (2.0, 0.0), ccw)
    assert r2.kind == "point"
    assert r2.hits[0]["point"] == pytest.approx((1.0, 0.0), abs=1e-12)


def test_full_circle_arc_contains_both():
    arc = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=2.0 * PI)
    result = intersect_segment_arc((-2.0, 0.0), (2.0, 0.0), arc)
    assert result.kind == "points"


def test_arc_miss_returns_none():
    arc = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=HALF_PI)
    # 圆在 y=−1 相切，第一象限弧不含 (0,−1)
    result = intersect_segment_arc((-2.0, -1.0), (2.0, -1.0), arc)
    assert result.kind == "none"


# ---------------------------------------------------------------- 包含判定


def test_arc_contains_angle_boundaries():
    arc = _quarter_arc()
    assert arc_contains_angle_exact(arc, 0.0)         # 起点
    assert arc_contains_angle_exact(arc, HALF_PI)     # 终点
    assert arc_contains_angle_exact(arc, 0.25 * PI)   # 中间
    assert not arc_contains_angle_exact(arc, PI)      # 对侧
    assert not arc_contains_angle_exact(arc, -0.1)


def test_arc_contains_midpoint_of_large_sweep():
    # 优弧：从 0° 逆时针扫 270°，覆盖第一、二、三象限；不含第四象限 -45°
    arc = Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=1.5 * PI)
    assert arc_contains_angle_exact(arc, 0.5 * PI)
    assert arc_contains_angle_exact(arc, PI)
    assert arc_contains_angle_exact(arc, -0.75 * PI)  # 135°? -0.75π = -135° ≡ 225° 在弧上
    assert not arc_contains_angle_exact(arc, -0.25 * PI)  # -45° ≡ 315° 不在


# ---------------------------------------------------------------- 退化拒绝


def test_zero_length_segment_rejected():
    with pytest.raises(DomainError, match="退化为点"):
        intersect_segment_circle((1.0, 1.0), (1.0, 1.0), (0.0, 0.0), 1.0)
    with pytest.raises(DomainError, match="退化为点"):
        intersect_segment_arc((1.0, 1.0), (1.0, 1.0), _quarter_arc())


def test_bad_radius_and_sweep_rejected():
    with pytest.raises(DomainError, match="半径"):
        intersect_segment_circle((0.0, 0.0), (1.0, 0.0), (0.0, 0.0), 0.0)
    with pytest.raises(DomainError, match="半径"):
        intersect_segment_circle((0.0, 0.0), (1.0, 0.0), (0.0, 0.0), float("nan"))
    with pytest.raises(DomainError, match="扫角"):
        Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=0.0)
    with pytest.raises(DomainError, match="扫角"):
        Arc2D(center=(0.0, 0.0), radius=1.0, start_angle=0.0, sweep=2.5 * PI)
    with pytest.raises(DomainError, match="半径"):
        Arc2D(center=(0.0, 0.0), radius=-1.0, start_angle=0.0, sweep=PI)


def test_non_finite_points_rejected():
    with pytest.raises(DomainError):
        intersect_segment_circle((0.0, float("nan")), (1.0, 0.0), (0.0, 0.0), 1.0)
    with pytest.raises(DomainError, match="二维点"):
        intersect_segment_circle((0.0,), (1.0, 0.0), (0.0, 0.0), 1.0)


# ---------------------------------------------------------------- 不变量


def test_hits_are_ordered_by_t_and_on_circle():
    result = intersect_segment_circle((-3.0, 0.5), (3.0, 0.5), (0.0, 0.0), 1.0)
    assert result.kind == "points"
    ts = [h["t"] for h in result.hits]
    assert ts[0] < ts[1]
    for h in result.hits:
        x, y = h["point"]
        assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-12)
        # 线段参数回代：P0 + t·d == point
        t = h["t"]
        assert (-3.0 + t * 6.0) == pytest.approx(x, abs=1e-12)
        assert 0.5 == pytest.approx(y, abs=1e-12)


def test_tangent_point_on_both_circle_and_line():
    result = intersect_segment_circle((0.0, 2.0), (4.0, 2.0), (2.0, 0.0), 2.0)
    assert result.kind == "point"
    h = result.hits[0]
    assert h["tangent"] is True
    assert h["point"] == pytest.approx((2.0, 2.0), abs=1e-12)
    d = math.hypot(h["point"][0] - 2.0, h["point"][1] - 0.0)
    assert d == pytest.approx(2.0, abs=1e-12)


def test_endpoint_root_is_kept():
    # 两根之一恰在 t=0（起点在圆上）：闭线段必须保留端点交点
    result = intersect_segment_circle((0.0, 0.0), (0.0, 10.0), (0.0, 5.0), 5.0)
    assert result.kind in ("point", "points")
    assert result.hits[0]["t"] == pytest.approx(0.0, abs=1e-12)
    assert result.hits[0]["point"] == pytest.approx((0.0, 0.0), abs=1e-12)
    # t=1 端点在圆上的情形
    result2 = intersect_segment_circle((0.0, 0.0), (0.0, 10.0), (0.0, 5.0), 5.0)
    assert result2.hits[-1]["t"] == pytest.approx(1.0, abs=1e-12)
