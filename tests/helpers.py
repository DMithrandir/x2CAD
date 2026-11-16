"""测试共享工具：种子化随机算例生成。"""

import random
from typing import List, Tuple


def random_clamped_knots(rng: random.Random, p: int, n_interior: int, granularity: int = 40) -> List[float]:
    """随机 clamped 节点向量：内部节点取自 {1/granularity, ..., (granularity-1)/granularity}，
    保证互异且最小间距 1/granularity。返回长度 n_interior + 2(p+1)。"""
    if n_interior > granularity - 1:
        raise ValueError("n_interior 超过可用离散值")
    vals = sorted(rng.sample(range(1, granularity), n_interior))
    interior = [v / granularity for v in vals]
    return [0.0] * (p + 1) + interior + [1.0] * (p + 1)


def random_points(rng: random.Random, n: int, dim: int, scale: float = 2.0) -> List[Tuple[float, ...]]:
    return [tuple(rng.uniform(-scale, scale) for _ in range(dim)) for _ in range(n)]


def knot_grid(U: List[float], p: int, n: int, count: int, margin: float) -> List[float]:
    """参数域 [U[p], U[n+1]] 内避开节点 margin 的等距网格（含两端点）。"""
    lo, hi = U[p], U[n + 1]
    knots = set(U[p : n + 2])
    out = []
    for i in range(count + 1):
        u = lo + (hi - lo) * i / count
        ok = True
        for k in knots:
            if abs(u - k) < margin:
                ok = False
                break
        if ok:
            out.append(u)
    # 保证两端至少各进入一个点（margin 远小于域长时必然）
    return out
