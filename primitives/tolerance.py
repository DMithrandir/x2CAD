"""容差上下文：把"是否算相等"从代码里散落的魔法常数收拢为一个显式对象。

为什么需要
----------
CAD 里不存在「恰好重合」，只有「在容差内重合」。但容差是**相对**的：同一个 1e-9
的绝对阈值，用在 1e6 尺度的零件上是 1e-15 相对量（比浮点分辨率还小），用在
1e-3 尺度的特征上又粗得离谱。散落的 ``abs(a-b) < 1e-9`` 是退化知识库 N 族
（数值抵消/条件数）的高发区。

语义（唯一一条）
----------------
``tol(m) = max(atol, rtol * |m|)``，其中 ``m`` 是参与比较的量级
（通常是 ``max(|a|, |b|)``）。所有比较都走这一个函数，没有第二个口径。

与精确谓词的分工
----------------
- **谓词**（``primitives.predicates``）回答"符号到底是什么"，输入是浮点值，答案精确；
- **容差上下文**回答"这点误差算不算同一件事"，是工程语义。
两者不可互相替代：用容差给谓词"留余地"会让拓扑在边界处抖动；用精确谓词做
容差判断会把噪声当信号。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from primitives.bspline import DomainError

__all__ = ["ToleranceContext"]


@dataclass(frozen=True)
class ToleranceContext:
    """不可变容差上下文。非法参数一律 ``DomainError``，绝不静默夹逼。"""

    atol: float = 1e-12
    rtol: float = 1e-9
    snap_tol: Optional[float] = None

    def __post_init__(self) -> None:
        for name in ("atol", "rtol"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0.0:
                raise DomainError(f"{name} 必须是非负有限数，收到 {value!r}")
        if self.snap_tol is not None:
            if not math.isfinite(self.snap_tol) or self.snap_tol < 0.0:
                raise DomainError(f"snap_tol 必须是非负有限数或 None，收到 {self.snap_tol!r}")

    # ---- 构造 ---------------------------------------------------------
    @classmethod
    def from_scale(
        cls,
        scale: float,
        *,
        atol_factor: float = 1e-12,
        rtol: float = 1e-9,
        snap_factor: Optional[float] = None,
    ) -> "ToleranceContext":
        """按特征尺寸构造：atol = atol_factor * |scale|，snap_tol = snap_factor * |scale|。

        ``scale`` 为 0 时退化为纯相对上下文（atol=0）；负值按绝对值处理。
        """
        if not math.isfinite(scale):
            raise DomainError(f"scale 必须是有限数，收到 {scale!r}")
        s = abs(scale)
        snap = None if snap_factor is None else snap_factor * s
        return cls(atol=atol_factor * s, rtol=rtol, snap_tol=snap)

    @classmethod
    def absolute(cls, atol: float) -> "ToleranceContext":
        """纯绝对容差（rtol=0）：仅当调用方明确知道尺度时使用。"""
        return cls(atol=atol, rtol=0.0)

    # ---- 比较 ---------------------------------------------------------
    def tol(self, magnitude: float = 0.0) -> float:
        """该量级下的有效容差：``max(atol, rtol*|magnitude|)``。"""
        return max(self.atol, self.rtol * abs(magnitude))

    def almost_equal(self, a: float, b: float) -> bool:
        """|a-b| ≤ tol(max(|a|,|b|))。NaN 一律不相等（不猜）。"""
        if math.isnan(a) or math.isnan(b):
            return False
        return abs(a - b) <= self.tol(max(abs(a), abs(b)))

    def compare(self, a: float, b: float) -> int:
        """容差意义下的三值比较：-1 / 0 / +1。"""
        if self.almost_equal(a, b):
            return 0
        return 1 if a > b else -1

    def sign(self, x: float) -> int:
        """容差意义下的符号：|x| 在容差内返回 0。"""
        if math.isnan(x):
            raise DomainError("sign 不接受 NaN")
        t = self.tol(x)
        if abs(x) <= t:
            return 0
        return 1 if x > 0.0 else -1

    def is_zero(self, x: float) -> bool:
        return self.sign(x) == 0

    # ---- 吸附 ---------------------------------------------------------
    def snap_index(self, x: float, candidates: Sequence[float]) -> Optional[int]:
        """在 snap_tol 内吸附到最近的候选，返回其下标；无候选在范围内返回 None。

        平局（两个候选与 x 的距离之差在容差内）→ ``DomainError``：
        歧义必须显式暴露，绝不"随便选一个"（Pointer-CAD 文档 §4.3 的吸附歧义条目）。
        """
        if self.snap_tol is None:
            raise DomainError("该容差上下文未配置 snap_tol，不能做吸附")
        if not candidates:
            return None
        dists = [(abs(x - c), i) for i, c in enumerate(candidates)]
        for d, _ in dists:
            if math.isnan(d):
                raise DomainError("吸附候选含 NaN")
        dists.sort()
        best_d, best_i = dists[0]
        if best_d > self.snap_tol:
            return None
        if len(dists) > 1:
            second_d = dists[1][0]
            if second_d - best_d <= self.tol(max(best_d, second_d)):
                raise DomainError(
                    f"吸附歧义：候选 {best_i} 与 {dists[1][1]} 距离差 "
                    f"{second_d - best_d:.3e} 在容差内，拒绝猜"
                )
        return best_i
