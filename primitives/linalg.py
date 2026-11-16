"""线性代数基元：稠密线性方程组求解（部分主元高斯消元）。

只服务算子层的确定性数值核心，无 IO、无全局状态。规模定位：正确性优先的
Python-first 内核（设计文档 §1.2），算例尺寸 ≤ 数百；性能瓶颈出现时逐算子换后端。
"""

from __future__ import annotations

from typing import List, Sequence

from .bspline import DomainError

__all__ = ["solve_dense"]


def solve_dense(A: Sequence[Sequence[float]], b: Sequence[float]) -> List[float]:
    """求解 A x = b（方阵，部分主元高斯消元，原地副本上执行）。

    主元绝对值 < 1e-13 视为奇异（按行无穷范数相对判据近似），抛 DomainError——
    上游（如曲线插值）把奇异系统解释为参数/节点配置退化，而不是静默产出垃圾。
    """
    n = len(b)
    if len(A) != n or any(len(row) != n for row in A):
        raise DomainError(f"A 必须是 {n}x{n} 方阵")
    M = [list(row) for row in A]
    x = list(b)

    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-13:
            raise DomainError(f"线性系统奇异或严重病态（第 {col} 列主元 {M[piv][col]!r}）")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
            x[col], x[piv] = x[piv], x[col]
        inv = 1.0 / M[col][col]
        for r in range(col + 1, n):
            f = M[r][col] * inv
            if f == 0.0:
                continue
            Mrow, Mcol = M[r], M[col]
            for c in range(col, n):
                Mrow[c] -= f * Mcol[c]
            x[r] -= f * x[col]

    for r in range(n - 1, -1, -1):
        s = x[r]
        Mrow = M[r]
        for c in range(r + 1, n):
            s -= Mrow[c] * x[c]
        x[r] = s / Mrow[r]
    return x
