"""基函数 oracle：独立 Cox-de Boor 参考实现对拍 + 单位分解 + 导数不变量 + 手算值。

这层测试是整个 NURBS 栈的地基预言机：它们不信任任何实现内部结构，
只用数学恒等式与教科书定义裁决。
"""

import math
import random

import pytest

from primitives.bspline import (
    DomainError,
    basis_function_ders,
    basis_functions,
    find_span,
    greville_abscissae,
    validate_knot_vector,
)

from helpers import random_clamped_knots


def ref_basis(i: int, p: int, u: float, U) -> float:
    """原始 Cox-de Boor 递推（NURBS Book 式 2.5/2.6，指数复杂度的独立实现）。

    仅用于 u < U[-1]：右端点的左极限约定无法用右连续的 0 次基表达。
    """
    if p == 0:
        return 1.0 if U[i] <= u < U[i + 1] else 0.0
    val = 0.0
    d1 = U[i + p] - U[i]
    if d1 > 0.0:
        val += (u - U[i]) / d1 * ref_basis(i, p - 1, u, U)
    d2 = U[i + p + 1] - U[i + 1]
    if d2 > 0.0:
        val += (U[i + p + 1] - u) / d2 * ref_basis(i + 1, p - 1, u, U)
    return val


CASES = [
    (1, 3, 6),
    (2, 5, 40),
    (3, 4, 40),
    (3, 0, 40),
    (4, 6, 40),
    (5, 3, 40),
]


@pytest.mark.parametrize("p,n_int,gran", CASES)
def test_reference_agreement(p, n_int, gran):
    rng = random.Random(1000 + p * 17 + n_int)
    U = random_clamped_knots(rng, p, n_int, gran)
    n = p + n_int
    lo, hi = U[p], U[n + 1]
    for idx in range(201):
        u = lo + (hi - lo) * idx / 200
        if u >= hi - 1e-12:
            continue  # 参考实现的右端点约定不同，端点另行测试
        span = find_span(n, p, u, U)
        Ns = basis_functions(span, u, p, U)
        assert len(Ns) == p + 1
        for r, val in enumerate(Ns):
            assert val == pytest.approx(ref_basis(span - p + r, p, u, U), abs=1e-12), (u, r)
        # 窗口外基函数在 u 处必为 0（参考实现验证）
        for i in range(0, n + 1):
            if i < span - p or i > span:
                assert ref_basis(i, p, u, U) == 0.0


@pytest.mark.parametrize("p,n_int,gran", CASES)
def test_partition_of_unity_and_nonnegativity(p, n_int, gran):
    rng = random.Random(2000 + p * 31 + n_int)
    U = random_clamped_knots(rng, p, n_int, gran)
    n = p + n_int
    lo, hi = U[p], U[n + 1]
    us = [lo, hi] + [rng.uniform(lo, hi) for _ in range(50)] + [U[k] for k in range(p, n + 2)]
    for u in us:
        span = find_span(n, p, u, U)
        Ns = basis_functions(span, u, p, U)
        assert sum(Ns) == pytest.approx(1.0, abs=1e-12), u
        for val in Ns:
            assert val >= -1e-14, (u, val)


def test_endpoint_values():
    # clamped 端点：左端 N_{p,p}=1，右端 N_{n,p}=1，其余为 0（左极限语义）
    p, U = 3, [0.0, 0.0, 0.0, 0.0, 0.2, 0.5, 0.7, 1.0, 1.0, 1.0, 1.0]
    n = len(U) - p - 2
    Ns = basis_functions(find_span(n, p, U[p], U), U[p], p, U)
    assert Ns[0] == pytest.approx(1.0, abs=1e-12)
    assert all(v == pytest.approx(0.0, abs=1e-12) for v in Ns[1:])
    Ns = basis_functions(find_span(n, p, U[n + 1], U), U[n + 1], p, U)
    assert Ns[-1] == pytest.approx(1.0, abs=1e-12)
    assert all(v == pytest.approx(0.0, abs=1e-12) for v in Ns[:-1])


def test_hand_values_uniform_cubic():
    # 教科书经典：整数均匀三次基在节点处 [1,4,1]/6，在半节点处 [1,23,23,1]/48
    U = [float(k) for k in range(9)]  # p=3, n=4, 域 [3,5]
    p, n = 3, 4
    Ns = basis_functions(find_span(n, p, 4.0, U), 4.0, p, U)
    assert Ns == pytest.approx([1 / 6, 4 / 6, 1 / 6, 0.0], abs=1e-12)
    Ns = basis_functions(find_span(n, p, 4.5, U), 4.5, p, U)
    assert Ns == pytest.approx([1 / 48, 23 / 48, 23 / 48, 1 / 48], abs=1e-12)


def test_linear_basis_derivative_exact():
    # p=1：帽函数导数 = ±1/区间长，精确已知
    U = [0.0, 0.0, 0.3, 0.7, 1.0, 1.0]
    p, n = 1, 3
    for u, span in [(0.1, 1), (0.5, 2), (0.9, 3)]:
        ders = basis_function_ders(span, u, p, 1, U)
        assert ders[1] == pytest.approx([-1.0 / (U[span + 1] - U[span]), 1.0 / (U[span + 1] - U[span])], abs=1e-12)


@pytest.mark.parametrize("p,n_int", [(2, 5), (3, 4), (4, 6)])
def test_derivative_sum_zero(p, n_int):
    # 单位分解的推论：Σ_i N^{(k)}_{i,p}(u) = 0（k ≥ 1）
    rng = random.Random(3000 + p)
    U = random_clamped_knots(rng, p, n_int, 40)
    n = p + n_int
    for u in [rng.uniform(U[p] + 0.01, U[n + 1] - 0.01) for _ in range(30)]:
        span = find_span(n, p, u, U)
        ders = basis_function_ders(span, u, p, min(2, p), U)
        for k in range(1, len(ders)):
            assert abs(sum(ders[k])) < 1e-9, (u, k, sum(ders[k]))


@pytest.mark.parametrize("p,n_int", [(2, 5), (3, 4), (4, 6)])
def test_first_derivative_vs_finite_difference(p, n_int):
    # 与参考实现的中心差分对拍（h 按最小节点间距定标）
    rng = random.Random(4000 + p)
    U = random_clamped_knots(rng, p, n_int, 40)
    n = p + n_int
    gap = min(U[k + 1] - U[k] for k in range(p, n + 1))
    h = gap / 200.0
    for u in [rng.uniform(U[p] + 10 * h, U[n + 1] - 10 * h) for _ in range(20)]:
        span = find_span(n, p, u, U)
        ders = basis_function_ders(span, u, p, 1, U)
        for r in range(p + 1):
            i = span - p + r
            fd = (ref_basis(i, p, u + h, U) - ref_basis(i, p, u - h, U)) / (2 * h)
            if abs(fd) < 1e-12 and abs(ders[1][r]) < 1e-12:
                continue
            assert ders[1][r] == pytest.approx(fd, rel=0.05, abs=1e-3), (u, i)


def test_second_derivative_vs_finite_difference():
    # 二阶导对拍（大间距向量，控制截断误差）
    U = [0.0, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.0, 1.0, 1.0]
    p, n = 3, 11
    h = 1e-3
    for u in [0.13, 0.27, 0.44, 0.61, 0.78]:
        span = find_span(n, p, u, U)
        ders = basis_function_ders(span, u, p, 2, U)
        for r in range(p + 1):
            i = span - p + r
            fd = (ref_basis(i, p, u + h, U) - 2 * ref_basis(i, p, u, U) + ref_basis(i, p, u - h, U)) / (h * h)
            assert ders[2][r] == pytest.approx(fd, rel=0.01, abs=5e-2), (u, i, ders[2][r], fd)


def test_greville_properties():
    U = [0.0, 0.0, 0.0, 0.2, 0.5, 0.7, 1.0, 1.0, 1.0]
    p, n = 2, 5
    xi = greville_abscissae(U, p, n)
    assert len(xi) == n + 1
    assert xi[0] == pytest.approx(U[p], abs=1e-15)
    assert xi[-1] == pytest.approx(U[n + 1], abs=1e-15)
    assert all(xi[i] <= xi[i + 1] + 1e-15 for i in range(n))


def test_invalid_knot_vectors_rejected():
    good_len = lambda p, n: n + p + 2
    with pytest.raises(DomainError):
        validate_knot_vector([0.0, 0.0, 0.5, 1.0, 1.0], 2, 2)  # 长度错
    with pytest.raises(DomainError):
        validate_knot_vector([0.0, 0.0, 0.0, 0.5, 0.4, 1.0, 1.0, 1.0], 2, 5)  # 非降违反
    with pytest.raises(DomainError):
        validate_knot_vector([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0], 2, 5)  # 首重数 4 ≠ 3
    with pytest.raises(DomainError):
        validate_knot_vector([0.0, 0.0, 0.0, 0.5, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0], 3, 7)  # 内部重数 4 > 3
    with pytest.raises(DomainError):
        validate_knot_vector([float(k) for k in range(8)], 3, 3)  # 未 clamped
    with pytest.raises(DomainError):
        validate_knot_vector([0.0] * 8, 3, 3)  # 全部坍缩
    with pytest.raises(DomainError):
        validate_knot_vector([0.0, 0.0, 0.2, 1.0, 1.0, 1.0], 1, 3)  # 末重数 3 ≠ p+1=2


def test_find_span_domain_errors():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    p, n = 2, 4
    with pytest.raises(DomainError):
        find_span(n, p, -1e-9, U)
    with pytest.raises(DomainError):
        find_span(n, p, 1.0 + 1e-9, U)
    assert find_span(n, p, 0.0, U) == p
    assert find_span(n, p, 1.0, U) == n


def test_n_ders_validation():
    U = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    with pytest.raises(DomainError):
        basis_function_ders(2, 0.3, 2, 3, U)  # n_ders > p
