"""鲁棒性平面（Tier 4 证据）：对固定用例族做四维扰动扫描，产出通过率矩阵。

设计文档 §6.4：``随机刚体变换 × 全局尺度 × 相对位错 × 容差阶梯``。本模块只做
**调度与记账**：构造用例、计算一个可度量的量、与解析真值比较、落表。算子相关的
内容全部由调用方以 ``build`` / ``measure`` / ``truth`` 三个纯函数注入。

判定线（设计文档 §6.4，验收线写入 spec）：
- 默认域：尺度 1e-1 ~ 1e3、相对位错 ≤ 1e-6 → 通过率 100%；
- 边界域：其余格子 → ≥ 95%，且每个失败必须能标注到退化族标签。
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence

from primitives.bspline import DomainError
from verify.analytic import rel_error

__all__ = [
    "PlaneRow",
    "PlaneResult",
    "run_plane",
    "random_rotation_2d",
    "rigid_transform_2d",
]

DEFAULT_SCALES = (1e-3, 1e-1, 1.0, 1e3, 1e6)
DEFAULT_OFFSETS = (0.0, 1e-9, 1e-6, 1e-3, 1e-2)
DEFAULT_TOLERANCES = (1e-12, 1e-9, 1e-6)


@dataclass(frozen=True)
class PlaneRow:
    """平面上的一格：一次 (seed, scale, offset_ratio, tol) 组合的实测。"""

    seed: int
    scale: float
    offset_ratio: float
    tol: float
    error: float
    ok: bool
    family: Optional[str] = None  # 失败时标注退化族；None 表示未标注（边界域不合规）

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "scale": self.scale,
            "offset_ratio": self.offset_ratio,
            "tol": self.tol,
            "error": self.error,
            "ok": self.ok,
            "family": self.family,
        }


@dataclass
class PlaneResult:
    name: str
    rows: List[PlaneRow] = field(default_factory=list)
    threshold: float = 1e-9

    # ---- 统计 ---------------------------------------------------------
    @staticmethod
    def in_default_domain(row: PlaneRow) -> bool:
        """默认域：尺度 1e-1~1e3、相对位错 ≤ 1e-6（设计文档 §6.4）。"""
        return 1e-1 <= row.scale <= 1e3 and row.offset_ratio <= 1e-6

    def pass_rate(self, predicate: Optional[Callable[[PlaneRow], bool]] = None) -> float:
        rows = [r for r in self.rows if predicate is None or predicate(r)]
        if not rows:
            return 1.0  # 空子域视为通过（vacuous truth），由 summary 里的 cells 计数暴露空扫描
        return sum(1 for r in rows if r.ok) / len(rows)

    def default_domain_pass_rate(self) -> float:
        return self.pass_rate(self.in_default_domain)

    def boundary_pass_rate(self) -> float:
        return self.pass_rate(lambda r: not self.in_default_domain(r))

    def unlabeled_failures(self) -> List[PlaneRow]:
        return [r for r in self.rows if not r.ok and r.family is None]

    def worst_error(self) -> float:
        return max((r.error for r in self.rows), default=0.0)

    # ---- 落盘 ---------------------------------------------------------
    def to_csv(self, path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["seed", "scale", "offset_ratio", "tol", "error", "ok", "family"]
            )
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row.as_dict())

    def summary(self) -> dict:
        return {
            "name": self.name,
            "cells": len(self.rows),
            "threshold": self.threshold,
            "default_domain_pass_rate": self.default_domain_pass_rate(),
            "boundary_pass_rate": self.boundary_pass_rate(),
            "worst_error": self.worst_error(),
            "unlabeled_failures": len(self.unlabeled_failures()),
        }


def run_plane(
    name: str,
    build: Callable[[float, float, float, random.Random], object],
    measure: Callable[[object], float],
    truth: Callable[[object], float],
    *,
    seeds: Sequence[int] = (0, 1, 2),
    scales: Sequence[float] = DEFAULT_SCALES,
    offsets: Sequence[float] = DEFAULT_OFFSETS,
    tolerances: Sequence[float] = DEFAULT_TOLERANCES,
    threshold: float = 1e-9,
    family: Optional[Callable[[object], Optional[str]]] = None,
) -> PlaneResult:
    """执行四维扫描。

    参数
    ----
    build(scale, offset_ratio, tol, rng) -> 用例对象
        按扰动构造一个实例；``offset_ratio`` 是相对特征尺寸的位错比例。
    measure(obj) -> float
        被测算子在该实例上的输出（可度量标量）。
    truth(obj) -> float
        同一实例的解析真值（必须**独立于**被测实现）。
    family(obj) -> str | None
        失败时返回退化族标签（T/C/S/I/N），用于边界域归因。

    注意：``build`` 里抛 ``DomainError`` 视为"算子显式拒绝"，记为失败但标 ``FAIL``；
    这是有意为之——鲁棒性平面统计的是"在扰动下还能给出正确答案"的比例。
    """
    if threshold <= 0.0:
        raise DomainError("threshold 必须为正")
    result = PlaneResult(name=name, threshold=threshold)
    for seed in seeds:
        rng = random.Random(10_000 * seed + 17)
        for scale in scales:
            for offset_ratio in offsets:
                for tol in tolerances:
                    obj = None
                    try:
                        obj = build(scale, offset_ratio, tol, rng)
                        err = abs(rel_error(float(measure(obj)), float(truth(obj))))
                        if not math.isfinite(err):
                            err = math.inf
                        row = PlaneRow(seed, scale, offset_ratio, tol, err, err <= threshold)
                    except DomainError:
                        row = PlaneRow(seed, scale, offset_ratio, tol, math.inf, False, family="FAIL")
                    except (ArithmeticError, ValueError):
                        row = PlaneRow(seed, scale, offset_ratio, tol, math.inf, False, family="FAIL")
                    if not row.ok and row.family is None and family is not None and obj is not None:
                        row = PlaneRow(
                            row.seed, row.scale, row.offset_ratio, row.tol,
                            row.error, row.ok, family(obj),
                        )
                    result.rows.append(row)
    return result


def random_rotation_2d(rng: random.Random) -> tuple:
    """返回精确可逆的 2×2 旋转矩阵 (cos, -sin; sin, cos)。"""
    theta = rng.uniform(-math.pi, math.pi)
    c, s = math.cos(theta), math.sin(theta)
    return ((c, -s), (s, c))


def rigid_transform_2d(points: Iterable[Sequence[float]], rotation, translation) -> List[tuple]:
    """对点集施加刚体变换：先旋转再平移（浮点，非精确——这正是 Tier 4 要打的）。"""
    c, s = rotation[0][0], rotation[1][0]
    tx, ty = translation
    out = []
    for x, y in points:
        out.append((c * x - s * y + tx, s * x + c * y + ty))
    return out
