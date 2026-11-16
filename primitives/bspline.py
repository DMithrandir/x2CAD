"""B 样条基函数基元：节点向量校验、区间定位、Cox-de Boor 递推及其各阶导数。

纯函数、无 IO、无全局状态（设计文档 §3.1 数值基元层约束）。

记号与约定（Piegl & Tiller, *The NURBS Book*, 2nd ed.）：

- 控制点下标 0..n（共 n+1 个），次数 p，节点向量 ``U`` 长度 n+p+2（下标 0..m, m=n+p+1）；
- 节点向量必须 clamped：首末重数恰为 p+1，内部重数 ≤ p；
- 参数域为闭区间 [U[p], U[n+1]]；基函数右连续，在右端点取左极限；
- 分母为零的递推项按惯例置零（该惯例仅在配对基函数恒为零时触发，见下述各函数文档）。

导数实现不照抄 A2.3，而是由一阶导递推式（NURBS Book 式 2.7）

    N'_{i,p}(u) = p/(U[i+p]-U[i]) * N_{i,p-1}(u) - p/(U[i+p+1]-U[i+1]) * N_{i+1,p-1}(u)

逐阶复合：k 阶导 = 对 (k-1) 阶导再求一次一阶导，系数与 u 无关，可层层递推。
正确性由 tests/test_basis.py 的独立 oracle（单位分解、导数和为零、原始递推参考实现、
有限差分、手算值）裁决，而非对代码形状的信任。
"""

from __future__ import annotations

from typing import List, Sequence

__all__ = [
    "DomainError",
    "validate_knot_vector",
    "find_span",
    "basis_functions",
    "basis_function_ders",
    "greville_abscissae",
]


class DomainError(ValueError):
    """调用参数违反数学定义域。算子层用它拒绝非法输入，绝不静默产出错误结果。"""


def validate_knot_vector(U: Sequence[float], p: int, n: int) -> None:
    """校验 clamped B 样条节点向量。

    前置：p ≥ 1；控制点数 n+1 ≥ p+1；len(U) == n+p+2。

    规则（按 maximal run 扫描）：
    - 非降；
    - 首run 恰覆盖下标 [0, p]，末 run 恰覆盖 [n+1, m]（端重数 = p+1，
      同时禁止内部节点取端点值粘连端块）；
    - 内部 run 长度 ≤ p（保证曲线至少 C^0）；
    - 至少一个非退化节点区间（整条曲线不至于坍缩成一点）。
    """
    if p < 1:
        raise DomainError(f"次数 p 必须 ≥ 1，收到 {p}")
    if n < p:
        raise DomainError(f"控制点数 n+1={n + 1} 必须至少为 p+1={p + 1}")
    m = n + p + 1
    if len(U) != m + 1:
        raise DomainError(f"节点向量长度应为 n+p+2={m + 2}，收到 {len(U)}")
    for k in range(m):
        if U[k + 1] < U[k]:
            raise DomainError(f"节点向量必须非降：U[{k}]={U[k]} > U[{k + 1}]={U[k + 1]}")

    runs: List[tuple] = []  # (value, start, end) 端点含
    k = 0
    while k <= m:
        j = k
        while j < m and U[j + 1] == U[k]:
            j += 1
        runs.append((U[k], k, j))
        k = j + 1

    if runs[0][2] != p:
        raise DomainError(f"起始节点重数必须恰为 p+1={p + 1}，实为 {runs[0][2] - runs[0][1] + 1}")
    if runs[-1][1] != n + 1:
        raise DomainError(f"末端节点重数必须恰为 p+1={p + 1}，实为 {runs[-1][2] - runs[-1][1] + 1}")
    for _, a, b in runs[1:-1]:
        if b - a + 1 > p:
            raise DomainError(f"内部节点重数 {b - a + 1} 超过 p={p}（曲线不再连续）")
    if not (U[p] < U[p + 1] and U[n] < U[n + 1]):
        raise DomainError("节点向量必须含至少一个非退化区间（不能整条坍缩为一点）")


def find_span(n: int, p: int, u: float, U: Sequence[float]) -> int:
    """A2.1：定位满足 U[span] ≤ u < U[span+1] 的区间下标（右端点特判为 n）。

    前置：u ∈ [U[p], U[n+1]]（参数域），否则 DomainError。
    """
    if u < U[p] or u > U[n + 1]:
        raise DomainError(f"参数 u={u!r} 超出参数域 [{U[p]!r}, {U[n + 1]!r}]")
    if u == U[n + 1]:
        return n
    lo, hi = p, n + 1  # 不变量：U[lo] ≤ u < U[hi]
    while True:
        mid = (lo + hi) // 2
        if u < U[mid]:
            hi = mid
        elif u >= U[mid + 1]:
            lo = mid
        else:
            return mid


def _basis_triangle(span: int, u: float, p: int, U: Sequence[float]) -> List[List[float]]:
    """计算 0..p 全部次数的基函数值三角。

    rows[j][r] = N_{span-j+r, j}(u)，j = 0..p，r = 0..j。

    递推（Cox-de Boor 的区间局部形式）::

        N_{i,j} = (u-U[i])/(U[i+j]-U[i]) * N_{i,j-1}
                + (U[i+j+1]-u)/(U[i+j+1]-U[i+1]) * N_{i+1,j-1}

    窗口外的低阶基恒为零（degree j-1 的非零窗口是 [span-j+1, span]），由下标守卫处理；
    零分母项按惯例置零。对合法 clamped 向量、u ∈ [U[span], U[span+1]] 且 span 为
    find_span 结果时，与数值非零配对的分母 U[k+j]-U[k] 必严格为正，不会损失精度。
    """
    rows: List[List[float]] = [[1.0]]
    for j in range(1, p + 1):
        prev = rows[j - 1]  # 下标 span-j+1+r, r=0..j-1
        row: List[float] = []
        for r in range(j + 1):
            i = span - j + r
            val = 0.0
            d_left = U[i + j] - U[i]
            if d_left > 0.0:
                prev_left = prev[r - 1] if r >= 1 else 0.0  # N_{i, j-1}
                val += (u - U[i]) / d_left * prev_left
            d_right = U[i + j + 1] - U[i + 1]
            if d_right > 0.0:
                prev_right = prev[r] if r <= j - 1 else 0.0  # N_{i+1, j-1}
                val += (U[i + j + 1] - u) / d_right * prev_right
            row.append(val)
        rows.append(row)
    return rows


def basis_functions(span: int, u: float, p: int, U: Sequence[float]) -> List[float]:
    """A2.2：返回 [N_{span-p,p}(u), ..., N_{span,p}(u)]（长度 p+1，其余基在 u 处为 0）。"""
    return _basis_triangle(span, u, p, U)[p]


def basis_function_ders(
    span: int, u: float, p: int, n_ders: int, U: Sequence[float]
) -> List[List[float]]:
    """各阶导数：ders[k][r] = N^{(k)}_{span-p+r, p}(u)，k = 0..n_ders。

    前置：0 ≤ n_ders ≤ p。k 阶导递推（对式 2.7 复合，系数与 u 无关）::

        N^{(k)}_{i,j} = j/(U[i+j]-U[i]) * N^{(k-1)}_{i, j-1}
                      - j/(U[i+j+1]-U[i+1]) * N^{(k-1)}_{i+1, j-1}

    零分母项置零：此时配对的低阶基支撑退化为一点（恒为零），惯例成立。
    在内部重数 s 的节点处，阶数 > p-s 的导数不存在；本函数返回右向单侧导数
    （基函数右连续），调用方需自行保证语义。
    """
    if not (0 <= n_ders <= p):
        raise DomainError(f"n_ders 必须在 [0, p]=[{0}, {p}] 内，收到 {n_ders}")
    rows = _basis_triangle(span, u, p, U)
    memo: dict = {}

    def ders(j: int, k: int) -> List[float]:
        if k == 0:
            return rows[j]
        key = (j, k)
        if key in memo:
            return memo[key]
        sub = ders(j - 1, k - 1)  # 下标 span-j+1+s, s=0..j-1 的 (k-1) 阶导
        out = [0.0] * (j + 1)
        for r in range(j + 1):
            i = span - j + r
            d_left = U[i + j] - U[i]
            d_right = U[i + j + 1] - U[i + 1]
            left = sub[r - 1] if 1 <= r <= j else 0.0  # N^{(k-1)}_{i, j-1}
            right = sub[r] if r <= j - 1 else 0.0  # N^{(k-1)}_{i+1, j-1}
            out[r] = (j / d_left * left if d_left > 0.0 else 0.0) - (
                j / d_right * right if d_right > 0.0 else 0.0
            )
        memo[key] = out
        return out

    return [ders(p, k) for k in range(n_ders + 1)]


def greville_abscissae(U: Sequence[float], p: int, n: int) -> List[float]:
    """Greville 横坐标 ξ_i = (U[i+1] + ... + U[i+p]) / p，i = 0..n。

    用途：线性精度性质的控制点配置、插值质量参考。ξ_0 = U[p]，ξ_n = U[n+1]。
    """
    return [sum(U[i + 1 : i + p + 1]) / p for i in range(n + 1)]
