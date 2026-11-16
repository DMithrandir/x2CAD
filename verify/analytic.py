"""解析真值（Tier 2 证据）与误差度量：闭式几何量 + 统一的相对误差定义。

Tier 2 的判定线（设计文档 §6.2）：解析量相对误差 < 1e-6，且与算子声明的容差绑定。
本模块只提供**真值**与**度量**，不提供判定——阈值属于算子规格（spec），不属于真值库。
"""

from __future__ import annotations

import math

__all__ = [
    "abs_error",
    "rel_error",
    "circle_circumference",
    "circle_arc_length",
    "sphere_surface_area",
    "sphere_volume",
    "cube_volume",
    "cylinder_volume",
    "torus_volume",
]


def abs_error(actual: float, expected: float) -> float:
    return abs(actual - expected)


def rel_error(actual: float, expected: float) -> float:
    """相对误差 |a−e|/|e|；expected=0 时退化为绝对误差，actual≠0 时返回 inf。"""
    if expected == 0.0:
        return 0.0 if actual == 0.0 else math.inf
    return abs(actual - expected) / abs(expected)


def circle_circumference(radius: float) -> float:
    return 2.0 * math.pi * radius


def circle_arc_length(radius: float, angle_radians: float) -> float:
    return abs(radius * angle_radians)


def sphere_surface_area(radius: float) -> float:
    return 4.0 * math.pi * radius * radius


def sphere_volume(radius: float) -> float:
    return 4.0 / 3.0 * math.pi * radius**3


def cube_volume(edge: float) -> float:
    return float(edge) ** 3


def cylinder_volume(radius: float, height: float) -> float:
    return math.pi * radius * radius * height


def torus_volume(major_radius: float, minor_radius: float) -> float:
    return 2.0 * math.pi**2 * major_radius * minor_radius * minor_radius
