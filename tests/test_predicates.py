"""精确谓词的 oracle：有理数真值、尺度对抗用例、已知退化构型、定向不变性。

独立性说明：测试里的真值用 ``fractions.Fraction`` **独立重算**（不复用实现里的
``*_exact`` 辅助函数），因此实现若把公式写错，这里抓得到。
"""

import random
from fractions import Fraction

import pytest

from primitives.bspline import DomainError
from primitives.predicates import incircle, insphere, orient2d, orient3d


def _sgn(x) -> int:
    return (x > 0) - (x < 0)


def _det2(a, b, c) -> Fraction:
    ax, ay = Fraction(a[0]), Fraction(a[1])
    bx, by = Fraction(b[0]), Fraction(b[1])
    cx, cy = Fraction(c[0]), Fraction(c[1])
    return (ax - cx) * (by - cy) - (ay - cy) * (bx - cx)


def _det3(a, b, c, d) -> Fraction:
    fx = [Fraction(v) for v in a]
    fy = [Fraction(v) for v in b]
    fz = [Fraction(v) for v in c]
    fw = [Fraction(v) for v in d]
    adx, ady, adz = (fx[0] - fw[0], fx[1] - fw[1], fx[2] - fw[2])
    bdx, bdy, bdz = (fy[0] - fw[0], fy[1] - fw[1], fy[2] - fw[2])
    cdx, cdy, cdz = (fz[0] - fw[0], fz[1] - fw[1], fz[2] - fw[2])
    return (
        adx * (bdy * cdz - bdz * cdy)
        - ady * (bdx * cdz - bdz * cdx)
        + adz * (bdx * cdy - bdy * cdx)
    )


def _incircle4(a, b, c, d) -> Fraction:
    fa = [Fraction(v) for v in a]
    fb = [Fraction(v) for v in b]
    fc = [Fraction(v) for v in c]
    fd = [Fraction(v) for v in d]
    adx, ady = fa[0] - fd[0], fa[1] - fd[1]
    bdx, bdy = fb[0] - fd[0], fb[1] - fd[1]
    cdx, cdy = fc[0] - fd[0], fc[1] - fd[1]
    alift = adx * adx + ady * ady
    blift = bdx * bdx + bdy * bdy
    clift = cdx * cdx + cdy * cdy
    return (
        alift * (bdx * cdy - cdx * bdy)
        + blift * (cdx * ady - adx * cdy)
        + clift * (adx * bdy - bdx * ady)
    )


def _random_points(rng: random.Random, count: int, dim: int):
    out = []
    for _ in range(count):
        e1 = rng.randint(-25, 25)
        e2 = rng.randint(-25, 25)
        base = (rng.uniform(-1.0, 1.0) * 10.0**e1, rng.uniform(-1.0, 1.0) * 10.0**e2)
        out.append(base if dim == 2 else base + (rng.uniform(-1.0, 1.0) * 10.0**e1,))
    return out


# ---------------------------------------------------------------- orient2d


def test_orient2d_matches_rational_ground_truth():
    rng = random.Random(20261109)
    for _ in range(1500):
        a, b, c = _random_points(rng, 3, 2)
        assert orient2d(a, b, c) == _sgn(_det2(a, b, c)), (a, b, c)


def test_orient2d_float_filter_failure_is_caught():
    """构造 naive 浮点行列式**恰好抵消为 0**、而精确符号为正的极小三角形。

    u = 2^-52；取 a=(1+2u, 1+4u), b=(1, 1+2u), c=(0,0)：
    精确值 = (1+2u)^2 - (1+4u) = 4u^2 > 0，但两个乘积都舍入到 1+4u，浮点差为 0。
    """
    u = 2.0**-52
    a = (1.0 + 2.0 * u, 1.0 + 4.0 * u)
    b = (1.0, 1.0 + 2.0 * u)
    c = (0.0, 0.0)
    naive = (a[0] - c[0]) * (b[1] - c[1]) - (a[1] - c[1]) * (b[0] - c[0])
    assert naive == 0.0  # 浮点滤波器会把它当共线
    assert _det2(a, b, c) > 0
    assert orient2d(a, b, c) == 1


def test_orient2d_exact_collinear_is_zero():
    assert orient2d((0.0, 0.0), (2.0, 1.0), (4.0, 2.0)) == 0
    big = 1e16
    assert orient2d((big, big), (big + 2.0, big + 2.0), (big + 4.0, big + 4.0)) == 0


def test_orient2d_rigid_motion_invariance():
    """整数坐标 + 90° 旋转/整数平移：变换本身精确，符号必须严格不变。"""
    rng = random.Random(7)
    for _ in range(300):
        pts = [(rng.randint(-5, 5), rng.randint(-5, 5)) for _ in range(3)]
        swapped = [(y, x) for x, y in pts]  # 沿 y=x 反射：翻转定向
        assert orient2d(*pts) == -orient2d(*swapped)
        rot90 = [(-y, x) for x, y in pts]  # 精确 90° 旋转：保持定向
        assert orient2d(*pts) == orient2d(*rot90)
        shift = (rng.randint(-100, 100), rng.randint(-100, 100))
        assert orient2d(*pts) == orient2d(*[(x + shift[0], y + shift[1]) for x, y in pts])


def test_orient2d_rejects_bad_input():
    with pytest.raises(DomainError):
        orient2d((0.0, 0.0), (1.0, 0.0), (0.0, 1.0, 2.0))
    with pytest.raises(DomainError):
        orient2d((0.0, float("nan")), (1.0, 0.0), (0.0, 1.0))
    with pytest.raises(DomainError):
        orient2d((0.0, float("inf")), (1.0, 0.0), (0.0, 1.0))


# ---------------------------------------------------------------- orient3d


def test_orient3d_matches_rational_ground_truth():
    rng = random.Random(20261110)
    for _ in range(800):
        a, b, c, d = _random_points(rng, 4, 3)
        assert orient3d(a, b, c, d) == _sgn(_det3(a, b, c, d)), (a, b, c, d)


def test_orient3d_coplanar_is_zero():
    assert orient3d((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)) == 0


def test_orient3d_swap_flips_sign():
    a, b, c, d = (0.1, -0.2, 0.3), (1.3, 0.4, -0.5), (-0.7, 2.1, 0.9), (0.2, 0.3, 1.7)
    assert orient3d(a, b, c, d) == -orient3d(a, c, b, d) or orient3d(a, b, c, d) == 0


def test_orient3d_translation_invariance():
    """整数坐标 + 整数平移：平移精确，符号必须不变。"""
    rng = random.Random(11)
    for _ in range(300):
        pts = [tuple(rng.randint(-4, 4) for _ in range(3)) for _ in range(4)]
        shift = tuple(rng.randint(-50, 50) for _ in range(3))
        moved = [tuple(p[k] + shift[k] for k in range(3)) for p in pts]
        assert orient3d(*pts) == orient3d(*moved)


# ---------------------------------------------------------------- incircle


def test_incircle_unit_circle_cases():
    ccw = (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)
    assert incircle(*ccw, (0.0, -1.0)) == 0  # 圆上
    assert incircle(*ccw, (0.0, 0.0)) == 1  # 圆内
    assert incircle(*ccw, (0.0, -2.0)) == -1  # 圆外
    assert incircle(ccw[2], ccw[1], ccw[0], (0.0, 0.0)) == -1  # 反向定向，符号反转


def test_incircle_matches_rational_ground_truth():
    rng = random.Random(20261111)
    for _ in range(600):
        a, b, c, d = _random_points(rng, 4, 2)
        expected = _sgn(_incircle4(a, b, c, d))
        assert incircle(a, b, c, d) == expected, (a, b, c, d)


# ---------------------------------------------------------------- insphere


def test_insphere_unit_sphere_cases():
    # 四面体顶点与测试点全部落在单位球上/内/外，且坐标可精确表示
    tet = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)
    o = orient3d(*tet)
    assert o != 0
    # 球面上的点（不在四面体顶点里）→ 精确 0
    assert insphere(*tet, (0.0, 0.0, -1.0)) == 0
    # 球心 → 与定向同号；球外 → 反号
    assert insphere(*tet, (0.0, 0.0, 0.0)) == o
    assert insphere(*tet, (2.0, 0.0, 0.0)) == -o


def test_insphere_on_circumsphere_and_orientation_flip():
    # 正四面体顶点 (±1,±1,±1) 的偶置换，外接球半径 sqrt(3)
    a, b, c, d = (1.0, 1.0, 1.0), (1.0, -1.0, -1.0), (-1.0, 1.0, -1.0), (-1.0, -1.0, 1.0)
    o = orient3d(a, b, c, d)
    assert insphere(a, b, c, d, (0.0, 0.0, 0.0)) == o
    assert insphere(a, b, c, d, (3.0, 3.0, 3.0)) == -o
    assert insphere(a, b, c, d, (b[0], b[1], b[2])) == 0  # 顶点在球上
    # 交换两个顶点 → 定向反转 → 符号整体反转
    assert insphere(a, c, b, d, (0.0, 0.0, 0.0)) == -o


def test_insphere_rejects_bad_input():
    with pytest.raises(DomainError):
        insphere((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0))
