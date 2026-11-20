"""精确有理数单变量多项式基元：Bernstein↔幂基转换、gcd、无平方分解、Sturm 根隔离。

为什么需要
----------
线段-Bézier 求交把几何问题化为单变量多项式 p(t)=0 的根问题。与线段/圆求交不同，
Bézier 的根一般是**代数数**（含开方），不能全程用有理数表示。但根的**个数、隔离区间、
重数（相切）、端点根**这些拓扑判定必须精确——否则相切丢根、端点吞根、重根误判都会
污染下游布尔装配。本基元提供「判定精确、坐标浮点」所需的全部纯数学工具：

1. Bernstein → 幂基转换（精确有理数）；
2. 多项式 gcd / 精确除法 / 无平方分解（Yun 算法，给出每个重数的因子）；
3. Sturm 序列 + 符号变差 → 区间内**精确实根计数**；
4. 递归二分根隔离（每个区间恰含一个不同实根）；
5. Bernstein 形式在子区间上的精确限制（有理 de Casteljau，凸包性质用于区间过滤）。

约定
----
- 多项式用**低次在前**的系数元组表示：``(a0, a1, ..., an)`` = a0 + a1·x + ... + an·xⁿ；
- 系数为 ``Fraction``（或可无损转 Fraction 的 int/float）；全程精确有理数算术；
- 零多项式表示为 ``()``；常数非零为 ``(c,)``；
- 非法输入（除零、负次数等）一律 ``DomainError``，绝不静默。

本模块是纯数学基元，不含任何几何/算子逻辑（ADR-0001 分层纪律）。
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import List, Sequence, Tuple

from primitives.bspline import DomainError

__all__ = [
    "Poly",
    "ZERO",
    "trim",
    "degree",
    "is_zero",
    "p_eval",
    "p_deriv",
    "p_add",
    "p_sub",
    "p_scale",
    "p_monic",
    "p_divrem",
    "p_divexact",
    "p_gcd",
    "bernstein_to_power",
    "power_to_bernstein",
    "squarefree_factors",
    "sturm_sequence",
    "sign_variations",
    "count_roots",
    "isolate_roots",
    "bernstein_split",
    "bernstein_restrict",
    "de_casteljau_float",
]

Poly = Tuple[Fraction, ...]
ZERO: Poly = ()


def _coeffs(values: Sequence) -> Poly:
    out = []
    for v in values:
        if isinstance(v, Fraction):
            out.append(v)
        elif isinstance(v, (int, float)):
            if isinstance(v, float) and not math.isfinite(v):
                raise DomainError(f"多项式系数必须是有限数，收到 {v!r}")
            out.append(Fraction(v))
        else:
            raise DomainError(f"多项式系数必须是数，收到 {v!r}")
    return trim(tuple(out))


def trim(p: Sequence) -> Poly:
    """去掉高次端的零系数；零多项式归一为 ()。"""
    coeffs = list(p)
    while coeffs and coeffs[-1] == 0:
        coeffs.pop()
    return tuple(coeffs)


def degree(p: Poly) -> int:
    return len(p) - 1


def is_zero(p: Poly) -> bool:
    return len(p) == 0


def p_eval(p: Poly, x) -> Fraction:
    """Horner 求值（精确）。x 为有理数。"""
    x = Fraction(x)
    acc = Fraction(0)
    for c in reversed(p):
        acc = acc * x + c
    return acc


def p_deriv(p: Poly) -> Poly:
    if len(p) <= 1:
        return ZERO
    return trim(tuple(Fraction(i) * p[i] for i in range(1, len(p))))


def p_add(a: Poly, b: Poly) -> Poly:
    n = max(len(a), len(b))
    out = []
    for i in range(n):
        ai = a[i] if i < len(a) else Fraction(0)
        bi = b[i] if i < len(b) else Fraction(0)
        out.append(ai + bi)
    return trim(tuple(out))


def p_sub(a: Poly, b: Poly) -> Poly:
    return p_add(a, p_scale(b, Fraction(-1)))


def p_scale(a: Poly, k) -> Poly:
    k = Fraction(k)
    if k == 0:
        return ZERO
    return trim(tuple(c * k for c in a))


def p_monic(a: Poly) -> Poly:
    if is_zero(a):
        return ZERO
    return p_scale(a, Fraction(1) / a[-1])


def p_divrem(a: Poly, b: Poly) -> Tuple[Poly, Poly]:
    """多项式带余除法（精确有理数）。b 非零。返回 (商, 余式)。"""
    if is_zero(b):
        raise DomainError("多项式除法：除式为零")
    a = trim(a)
    b = trim(b)
    if degree(a) < degree(b):
        return ZERO, a
    rem = list(a)
    quot = [Fraction(0)] * (degree(a) - degree(b) + 1)
    db = degree(b)
    lead = b[-1]
    while len(rem) - 1 >= db and any(c != 0 for c in rem):
        dr = len(rem) - 1
        factor = rem[-1] / lead
        shift = dr - db
        quot[shift] = factor
        for i in range(db + 1):
            rem[shift + i] -= factor * b[i]
        while rem and rem[-1] == 0:
            rem.pop()
    return trim(tuple(quot)), trim(tuple(rem))


def p_divexact(a: Poly, b: Poly) -> Poly:
    """精确除法：余式必须为零，否则 DomainError（不静默截断）。"""
    q, r = p_divrem(a, b)
    if not is_zero(r):
        raise DomainError("精确除法失败：余式非零")
    return q


def p_gcd(a: Poly, b: Poly) -> Poly:
    """欧几里得 gcd，归一为首一（monic）。gcd(a, 0) = monic(a)。"""
    a = trim(a)
    b = trim(b)
    while not is_zero(b):
        _, r = p_divrem(a, b)
        a, b = b, r
    return p_monic(a)


# ---------------------------------------------------------------- Bernstein


def bernstein_to_power(coeffs: Sequence) -> Poly:
    """Bernstein 基（次数 n = len−1）→ 幂基，精确。

    p(x) = Σ_i c_i·C(n,i)·x^i·(1−x)^{n−i}；
    x^k 系数 = Σ_{i≤k} c_i·C(n,i)·C(n−i, k−i)·(−1)^{k−i}。
    """
    c = _coeffs(coeffs)
    n = len(c) - 1
    if n < 0:
        return ZERO
    out = [Fraction(0)] * (n + 1)
    for i in range(n + 1):
        if c[i] == 0:
            continue
        bin_i = math.comb(n, i)
        for j in range(n - i + 1):
            k = i + j
            sign = -1 if (j % 2) else 1
            out[k] += c[i] * bin_i * math.comb(n - i, j) * sign
    return trim(tuple(out))


def power_to_bernstein(p: Poly, n: int) -> Tuple[Fraction, ...]:
    """幂基 → n 次 Bernstein 基（精确）。要求 deg(p) ≤ n。

    c_i = Σ_{k≤i} a_k·C(i,k) / C(n,k)。
    """
    p = trim(p)
    if n < 0:
        raise DomainError(f"Bernstein 次数必须非负，收到 {n}")
    if degree(p) > n:
        raise DomainError(f"多项式次数 {degree(p)} 超过 Bernstein 次数 {n}")
    out = []
    for i in range(n + 1):
        acc = Fraction(0)
        for k in range(min(i, degree(p)) + 1):
            acc += p[k] * Fraction(math.comb(i, k), math.comb(n, k))
        out.append(acc)
    return tuple(out)


def bernstein_split(coeffs: Sequence, t) -> Tuple[Tuple[Fraction, ...], Tuple[Fraction, ...]]:
    """有理 de Casteljau 分裂：返回 (左段 [0,t] 重参数化, 右段 [t,1] 重参数化)。"""
    c = list(_coeffs(coeffs))
    t = Fraction(t)
    n = len(c) - 1
    if n < 0:
        raise DomainError("Bernstein 分裂：控制点为空")
    levels = [c]
    for _ in range(n):
        prev = levels[-1]
        levels.append([(1 - t) * prev[i] + t * prev[i + 1] for i in range(len(prev) - 1)])
    left = tuple(levels[r][0] for r in range(n + 1))
    right = tuple(levels[n - r][r] for r in range(n + 1))
    return left, right


def bernstein_restrict(coeffs: Sequence, a, b) -> Tuple[Fraction, ...]:
    """把 Bernstein 多项式限制到子区间 [a,b]（0 ≤ a < b ≤ 1），返回该区间上的
    Bernstein 系数（精确）。凸包性质：值域 ⊆ [min(coeff), max(coeff)]。"""
    a = Fraction(a)
    b = Fraction(b)
    if not (0 <= a < b <= 1):
        raise DomainError(f"限制区间必须满足 0 ≤ a < b ≤ 1，收到 [{a}, {b}]")
    _, right = bernstein_split(coeffs, a)
    if b == 1:
        return right
    t2 = (b - a) / (1 - a)
    left, _ = bernstein_split(right, t2)
    return left


def de_casteljau_float(ctrl: Sequence[Sequence[float]], t: float) -> Tuple[float, float]:
    """浮点 de Casteljau 求值（数值稳定），用于输出交点坐标。"""
    pts = [(float(p[0]), float(p[1])) for p in ctrl]
    while len(pts) > 1:
        pts = [
            ((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])
            for a, b in zip(pts, pts[1:])
        ]
    return pts[0]


# ---------------------------------------------------------------- 无平方分解


def squarefree_factors(p: Poly) -> List[Tuple[Poly, int]]:
    """Yun 算法：返回 [(首一无平方因子, 重数), ...]。

    每个因子含且仅含原多项式中重数恰为该值的不可约因子之积；因子本身无平方。
    重数 ≥ 2 的根即相切/重根。零多项式/常数返回 []。
    """
    p = p_monic(trim(p))
    if degree(p) <= 0:
        return []
    fp = p_deriv(p)
    a0 = p_gcd(p, fp)
    b = p_divexact(p, a0)
    c = p_divexact(fp, a0)
    d = p_sub(c, p_deriv(b))
    factors: List[Tuple[Poly, int]] = []
    i = 1
    while degree(b) > 0:
        a = p_gcd(b, d)
        if degree(a) > 0:
            factors.append((p_monic(a), i))
        b = p_divexact(b, a)
        c = p_divexact(d, a)
        d = p_sub(c, p_deriv(b))
        i += 1
        if i > degree(p) + 1:  # pragma: no cover - 防御性上限
            raise DomainError("无平方分解未收敛")
    return factors


# ---------------------------------------------------------------- Sturm


def sturm_sequence(p: Poly) -> List[Poly]:
    """squarefree 多项式 p 的 Sturm 序列：S0=p, S1=p', S_{k+1}=−rem(S_{k−1},S_k)。"""
    p = trim(p)
    if degree(p) <= 0:
        return [p] if not is_zero(p) else []
    seq = [p, p_deriv(p)]
    while True:
        _, r = p_divrem(seq[-2], seq[-1])
        if is_zero(r):
            break
        seq.append(p_scale(r, Fraction(-1)))
        if degree(seq[-1]) == 0:
            break
    return seq


def sign_variations(seq: Sequence[Poly], x) -> int:
    """Sturm 序列在 x 处的符号变差数（跳过零值）。x 为有理数。"""
    x = Fraction(x)
    signs = []
    for p in seq:
        v = p_eval(p, x)
        if v > 0:
            signs.append(1)
        elif v < 0:
            signs.append(-1)
    var = 0
    for a, b in zip(signs, signs[1:]):
        if a != b:
            var += 1
    return var


def count_roots(p: Poly, a, b) -> int:
    """squarefree p 在开区间 (a,b) 内的不同实根数（精确）。要求 p(a)≠0, p(b)≠0。"""
    p = trim(p)
    if is_zero(p) or degree(p) == 0:
        return 0
    a = Fraction(a)
    b = Fraction(b)
    if p_eval(p, a) == 0 or p_eval(p, b) == 0:
        raise DomainError("count_roots 要求区间端点不是根（请先剥离端点根）")
    seq = sturm_sequence(p)
    return sign_variations(seq, a) - sign_variations(seq, b)


def isolate_roots(p: Poly, lo, hi, _depth: int = 0) -> List[Tuple[Fraction, Fraction]]:
    """隔离 squarefree p 在 (lo,hi) 内的全部不同实根。

    返回区间列表，每个区间恰含一个不同实根；有理根返回退化区间 (r, r)。
    要求 p(lo)≠0, p(hi)≠0。递归二分 + Sturm 计数，精确无浮点。
    """
    p = trim(p)
    lo = Fraction(lo)
    hi = Fraction(hi)
    if is_zero(p) or degree(p) == 0:
        return []
    if p_eval(p, lo) == 0 or p_eval(p, hi) == 0:
        raise DomainError("isolate_roots 要求区间端点不是根")
    seq = sturm_sequence(p)
    n = sign_variations(seq, lo) - sign_variations(seq, hi)
    if n == 0:
        return []
    if n == 1:
        return [(lo, hi)]
    if _depth > 512:  # pragma: no cover - 不同实根必可分离，防御性上限
        raise DomainError("根隔离超过深度上限")
    mid = (lo + hi) / 2
    if p_eval(p, mid) == 0:
        # 精确有理根：剥离 (x−mid) 后继续隔离其余根
        q = p_divexact(p, (Fraction(-mid), Fraction(1)))
        return [(mid, mid)] + isolate_roots(q, lo, hi, _depth)
    left = isolate_roots(p, lo, mid, _depth + 1)
    right = isolate_roots(p, mid, hi, _depth + 1)
    return left + right
