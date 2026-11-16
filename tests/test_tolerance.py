"""容差上下文的 oracle：相对语义、尺度构造、三值比较、吸附歧义。"""

import pytest

from primitives.bspline import DomainError
from primitives.tolerance import ToleranceContext


def test_relative_semantics_scale_with_magnitude():
    tol = ToleranceContext(atol=0.0, rtol=1e-9)
    assert tol.tol(1.0) == pytest.approx(1e-9)
    assert tol.tol(1e6) == pytest.approx(1e-3)
    assert tol.almost_equal(1.0, 1.0 + 5e-10)
    assert not tol.almost_equal(1.0, 1.0 + 2e-9)
    # 同一绝对差在大尺度下可接受、在小尺度下不可接受
    d = 1e-6
    assert tol.almost_equal(1e6, 1e6 + d)
    assert not tol.almost_equal(1e-3, 1e-3 + d)


def test_atol_floor_protects_near_zero():
    tol = ToleranceContext(atol=1e-12, rtol=1e-9)
    assert tol.sign(0.0) == 0
    assert tol.sign(1e-13) == 0  # 低于 atol 底
    assert tol.sign(1e-11) == 1
    assert tol.sign(-1e-11) == -1
    assert tol.is_zero(1e-13)
    assert not tol.is_zero(1e-9)


def test_compare_three_valued():
    tol = ToleranceContext(atol=1e-12, rtol=1e-9)
    assert tol.compare(1.0, 1.0 + 1e-10) == 0
    assert tol.compare(1.0, 1.1) == -1
    assert tol.compare(1.1, 1.0) == 1


def test_from_scale_moves_threshold_with_geometry():
    small = ToleranceContext.from_scale(1e-3, atol_factor=1e-12, snap_factor=1e-6)
    big = ToleranceContext.from_scale(1e3, atol_factor=1e-12, snap_factor=1e-6)
    assert small.atol == pytest.approx(1e-15)
    assert big.atol == pytest.approx(1e-9)
    assert small.snap_tol == pytest.approx(1e-9)
    assert big.snap_tol == pytest.approx(1e-3)


def test_absolute_context_has_no_relative_term():
    tol = ToleranceContext.absolute(1e-9)
    assert tol.tol(1e12) == 1e-9


def test_nan_is_never_equal():
    tol = ToleranceContext()
    assert not tol.almost_equal(float("nan"), float("nan"))
    with pytest.raises(DomainError):
        tol.sign(float("nan"))


def test_invalid_parameters_are_rejected():
    with pytest.raises(DomainError):
        ToleranceContext(atol=-1.0)
    with pytest.raises(DomainError):
        ToleranceContext(rtol=float("inf"))
    with pytest.raises(DomainError):
        ToleranceContext(snap_tol=-1e-9)
    with pytest.raises(DomainError):
        ToleranceContext.from_scale(float("nan"))


def test_snap_returns_index_of_nearest_candidate():
    tol = ToleranceContext(atol=1e-12, rtol=0.0, snap_tol=1e-6)
    assert tol.snap_index(0.1 + 1e-7, [0.1, 0.2, 0.3]) == 0
    assert tol.snap_index(0.2 - 1e-7, [0.1, 0.2, 0.3]) == 1
    assert tol.snap_index(0.5, [0.1, 0.2]) is None  # 超出 snap_tol
    assert tol.snap_index(0.1, []) is None


def test_snap_tie_is_explicit_domain_error():
    tol = ToleranceContext(atol=1e-12, rtol=0.0, snap_tol=1.0)
    with pytest.raises(DomainError, match="吸附歧义"):
        tol.snap_index(0.5, [0.4, 0.6])
    # 只要差距超出容差，就不算平局
    assert tol.snap_index(0.5, [0.4, 0.6001]) in (0, 1)


def test_snap_requires_configured_snap_tol():
    with pytest.raises(DomainError):
        ToleranceContext().snap_index(0.0, [0.0])
