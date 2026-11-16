"""退化知识库的最小可执行用例：每条 pitfall 都能被机器复现。

索引条目（``degeneracy/index.json``）里的 ``test`` 字段指向本文件或既有测试。
本文件只放**尚未被其它测试覆盖**的退化场景，避免语料与测试两套口径。
"""

import math

import pytest

from primitives.quadrature import integrate, integrate_adaptive
from verify.invariants import closed_manifold_problems


def test_non_manifold_edge_detected():
    """I-003：一条边被 3 个面共享（T 型连接）必须被 Tier 1 检查抓到。"""
    faces = [(0, 1, 2), (0, 1, 3), (1, 0, 4)]
    problems = closed_manifold_problems(faces)
    assert any("被 3 个面使用" in p for p in problems), problems


def test_adaptive_quadrature_beats_fixed_panels():
    """N-002：|C'| 型被积函数在极小值附近有复奇点，固定面板收敛意外地慢。

    f(x) = sqrt((x-1/2)^2 + a^2) 的解析积分可用
    ∫sqrt(x²+a²)dx = (x·sqrt(x²+a²) + a²·asinh(x/a))/2 得到。
    """
    a = 1e-3
    f = lambda t: math.sqrt((t - 0.5) ** 2 + a * a)

    def F(x):
        return 0.5 * (x * math.sqrt(x * x + a * a) + a * a * math.asinh(x / a))

    exact = F(0.5) - F(-0.5)
    panels = 4
    fixed = sum(integrate(f, i / panels, (i + 1) / panels, 8) for i in range(panels))
    adaptive = integrate_adaptive(f, 0.0, 1.0, rel_tol=1e-12)

    fixed_rel = abs(fixed - exact) / exact
    adaptive_rel = abs(adaptive - exact) / exact
    assert fixed_rel > 1e-6, "固定面板应当表现出明显误差（否则本用例不再是 witness）"
    assert adaptive_rel < 1e-12, f"自适应求积精度不足：{adaptive_rel:.3e}"


@pytest.mark.parametrize("panels", [1, 2, 4, 8])
def test_fixed_panel_error_does_not_vanish_quickly(panels):
    """补充证据：增加固定面板数并不能指数收敛（不是"面板太少"的问题）。"""
    a = 1e-3
    f = lambda t: math.sqrt((t - 0.5) ** 2 + a * a)
    exact = 0.25000740775577895
    got = sum(integrate(f, i / panels, (i + 1) / panels, 8) for i in range(panels))
    assert abs(got - exact) / exact > 1e-7
