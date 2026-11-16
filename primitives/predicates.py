"""精确几何谓词：浮点滤波 + 精确有理数回退（Shewchuk 滤波思想，回退用 ``Fraction``）。

为什么需要
----------
CAD 的退化几何（近共线、近共面、近共圆/共球）会让浮点行列式在真值附近发生
**符号翻转**，而几何算子的分支（点在三角形内/外、凸/凹、线段是否相交、四点是否
可共圆）一律依赖符号。符号错一位，拓扑错一片——这正是退化知识库 N 族
（数值抵消/条件数）的根因。

设计
----
1. **快速路径**：浮点计算行列式，并用前向误差上界判定符号是否可信。可信则直接返回；
   ``orient2d`` / ``orient3d`` / ``incircle`` 使用 Shewchuk 的标准误差常数
   ``(3+16ε)ε``、``(7+56ε)ε``、``(10+96ε)ε``。
2. **慢速路径**：把握到的浮点数无损转换为 ``Fraction``（二进制浮点值本身是精确有理数），
   用有理数算术重算行列式，符号**绝对正确**。这里的"精确"指精确于给定的浮点值，
   不引入任何新的数值语义。
3. **返回值统一为符号** ``int ∈ {-1, 0, 1}``。行列式的量级不作承诺——调用方不得用
   谓词返回值做容差判断（容差判断走 ``primitives.tolerance``）。

约定
----
- ``orient2d(a, b, c)``：a→b→c 逆时针为正。
- ``orient3d(a, b, c, d)``：``det[(a-d), (b-d), (c-d)]`` 的符号；与 Shewchuk 约定一致，
  即 a,b,c 从法向 ``(b-a)×(c-a)`` 一侧看逆时针时，d 在平面**另一侧**（"下方"）为正。
- ``incircle(a, b, c, d)``：当 a,b,c 逆时针时，d **严格在**外接圆内为正。
- ``insphere(a, b, c, d, e)``：当 a,b,c,d 正定向（``orient3d(a,b,c,d) > 0``）时，e **严格在**
  外接球内为正；定向为负时符号整体反转（与 Shewchuk 一致）。
- 所有坐标必须是 ``float``（或可无损转 ``Fraction`` 的 ``int``/``float``）；``NaN``/``Inf``
  一律 ``DomainError``——谓词不猜。
"""

from __future__ import annotations

import sys
from fractions import Fraction
from typing import Sequence, Tuple

from primitives.bspline import DomainError

__all__ = [
    "orient2d",
    "orient3d",
    "incircle",
    "insphere",
    "orient2d_exact",
    "orient3d_exact",
]

_EPS = sys.float_info.epsilon
_CCW_ERRBOUND_A = (3.0 + 16.0 * _EPS) * _EPS
_O3D_ERRBOUND_A = (7.0 + 56.0 * _EPS) * _EPS
_ICC_ERRBOUND_A = (10.0 + 96.0 * _EPS) * _EPS
# insphere 的浮点滤波常数：4x4 行列式 24 个排列项，每项 4 次乘法的舍入误差
# 被 (1 + few·ε) 放大；1000 倍余量足以覆盖，慢一点也无妨（退化输入才走精确路径）。
_ISPHERE_FILTER = 1000.0


def _sign(x) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _point(p: Sequence[float], dim: int) -> Tuple[float, ...]:
    if len(p) != dim:
        raise DomainError(f"点必须为 {dim} 维，收到 {len(p)} 维：{p!r}")
    q = tuple(float(c) for c in p)
    for c in q:
        if c != c or c in (float("inf"), float("-inf")):
            raise DomainError(f"谓词不接受 NaN/Inf 坐标：{p!r}")
    return q


def _frac(p: Sequence[float]) -> Tuple[Fraction, ...]:
    return tuple(Fraction(c) for c in p)


def _det3(m) -> Fraction:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _det4(m) -> Fraction:
    total = Fraction(0)
    for col in range(4):
        minor = [[m[r][c] for c in range(4) if c != col] for r in range(1, 4)]
        total += (1 if col % 2 == 0 else -1) * m[0][col] * _det3(minor)
    return total


def _orient2d_frac(a, b, c) -> Fraction:
    return (a[0] - c[0]) * (b[1] - c[1]) - (a[1] - c[1]) * (b[0] - c[0])


def orient2d_exact(a, b, c) -> int:
    """精确（Fraction）版本的 orient2d 符号；仅用于测试与诊断，勿在热路径调用。"""
    return _sign(_orient2d_frac(_frac(a), _frac(b), _frac(c)))


def orient2d(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> int:
    """二维定向谓词：a→b→c 逆时针为 +1，共线为 0，顺时针为 -1。"""
    ax, ay = _point(a, 2)
    bx, by = _point(b, 2)
    cx, cy = _point(c, 2)
    detleft = (ax - cx) * (by - cy)
    detright = (ay - cy) * (bx - cx)
    det = detleft - detright
    if detleft > 0.0:
        if detright <= 0.0:
            return _sign(det)
    elif detleft < 0.0:
        if detright >= 0.0:
            return _sign(det)
    errbound = _CCW_ERRBOUND_A * (abs(detleft) + abs(detright))
    if abs(det) > errbound:
        return _sign(det)
    return _sign(_orient2d_frac(_frac(a), _frac(b), _frac(c)))


def orient3d_exact(a, b, c, d) -> int:
    """精确（Fraction）版本的 orient3d 符号；仅用于测试与诊断。"""
    fa, fb, fc, fd = _frac(a), _frac(b), _frac(c), _frac(d)
    adx, ady, adz = fa[0] - fd[0], fa[1] - fd[1], fa[2] - fd[2]
    bdx, bdy, bdz = fb[0] - fd[0], fb[1] - fd[1], fb[2] - fd[2]
    cdx, cdy, cdz = fc[0] - fd[0], fc[1] - fd[1], fc[2] - fd[2]
    det = (
        adx * (bdy * cdz - bdz * cdy)
        - ady * (bdx * cdz - bdz * cdx)
        + adz * (bdx * cdy - bdy * cdx)
    )
    return _sign(det)


def orient3d(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> int:
    """三维定向谓词：``det[(b-a), (c-a), (d-a)]`` 的符号（正值含义见模块文档）。"""
    ax, ay, az = _point(a, 3)
    bx, by, bz = _point(b, 3)
    cx, cy, cz = _point(c, 3)
    dx, dy, dz = _point(d, 3)

    adx, ady, adz = ax - dx, ay - dy, az - dz
    bdx, bdy, bdz = bx - dx, by - dy, bz - dz
    cdx, cdy, cdz = cx - dx, cy - dy, cz - dz

    bdxcdy = bdx * cdy
    cdxbdy = cdx * bdy
    cdxady = cdx * ady
    adxcdy = adx * cdy
    adxbdy = adx * bdy
    bdxady = bdx * ady

    det = adz * (bdxcdy - cdxbdy) + bdz * (cdxady - adxcdy) + cdz * (adxbdy - bdxady)
    permanent = (
        (abs(bdxcdy) + abs(cdxbdy)) * abs(adz)
        + (abs(cdxady) + abs(adxcdy)) * abs(bdz)
        + (abs(adxbdy) + abs(bdxady)) * abs(cdz)
    )
    errbound = _O3D_ERRBOUND_A * permanent
    if abs(det) > errbound:
        return _sign(det)
    return orient3d_exact(a, b, c, d)


def incircle(a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]) -> int:
    """内圆谓词：a,b,c 逆时针时，d 在外接圆内为正（共圆为 0）。"""
    ax, ay = _point(a, 2)
    bx, by = _point(b, 2)
    cx, cy = _point(c, 2)
    dx, dy = _point(d, 2)

    adx, ady = ax - dx, ay - dy
    bdx, bdy = bx - dx, by - dy
    cdx, cdy = cx - dx, cy - dy

    bdxcdy = bdx * cdy
    cdxbdy = cdx * bdy
    cdxady = cdx * ady
    adxcdy = adx * cdy
    adxbdy = adx * bdy
    bdxady = bdx * ady

    alift = adx * adx + ady * ady
    blift = bdx * bdx + bdy * bdy
    clift = cdx * cdx + cdy * cdy

    det = (
        alift * (bdxcdy - cdxbdy)
        + blift * (cdxady - adxcdy)
        + clift * (adxbdy - bdxady)
    )
    permanent = (
        (abs(bdxcdy) + abs(cdxbdy)) * alift
        + (abs(cdxady) + abs(adxcdy)) * blift
        + (abs(adxbdy) + abs(bdxady)) * clift
    )
    errbound = _ICC_ERRBOUND_A * permanent
    if abs(det) > errbound:
        return _sign(det)

    fa, fb, fc, fd = _frac(a), _frac(b), _frac(c), _frac(d)
    adx2, ady2 = fa[0] - fd[0], fa[1] - fd[1]
    bdx2, bdy2 = fb[0] - fd[0], fb[1] - fd[1]
    cdx2, cdy2 = fc[0] - fd[0], fc[1] - fd[1]
    alift2 = adx2 * adx2 + ady2 * ady2
    blift2 = bdx2 * bdx2 + bdy2 * bdy2
    clift2 = cdx2 * cdx2 + cdy2 * cdy2
    det2 = (
        alift2 * (bdx2 * cdy2 - cdx2 * bdy2)
        + blift2 * (cdx2 * ady2 - adx2 * cdy2)
        + clift2 * (adx2 * bdy2 - bdx2 * ady2)
    )
    return _sign(det2)


def insphere(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
    e: Sequence[float],
) -> int:
    """内球谓词：a,b,c,d 正定向时，e 在外接球内为正（共球为 0）。"""
    pa = _point(a, 3)
    pb = _point(b, 3)
    pc = _point(c, 3)
    pd = _point(d, 3)
    pe = _point(e, 3)

    def row(p, q):
        dx, dy, dz = p[0] - q[0], p[1] - q[1], p[2] - q[2]
        return [dx, dy, dz, dx * dx + dy * dy + dz * dz]

    m = [row(pa, pe), row(pb, pe), row(pc, pe), row(pd, pe)]
    det = (
        m[0][0] * (m[1][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2])
                   - m[1][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1])
                   + m[1][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]))
        - m[0][1] * (m[1][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2])
                     - m[1][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0])
                     + m[1][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]))
        + m[0][2] * (m[1][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1])
                     - m[1][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0])
                     + m[1][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
        - m[0][3] * (m[1][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1])
                     - m[1][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0])
                     + m[1][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0]))
    )
    scale = max(abs(v) for r in m for v in r)
    errbound = _ISPHERE_FILTER * _EPS * scale**4
    if abs(det) > errbound:
        return _sign(det)

    fe = _frac(pe)
    fm = []
    for p in (pa, pb, pc, pd):
        ddx = Fraction(p[0]) - fe[0]
        ddy = Fraction(p[1]) - fe[1]
        ddz = Fraction(p[2]) - fe[2]
        fm.append([ddx, ddy, ddz, ddx * ddx + ddy * ddy + ddz * ddz])
    return _sign(_det4(fm))
