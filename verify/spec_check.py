"""OperatorSpec 校验：spec.json 是算子与验证台之间的契约，格式错误必须当场拒绝。

校验分两层：
1. **结构层**（本模块）：必填字段、枚举取值、退化分支形状；
2. **语义层**（静态检查器 SC006）：``depends_on`` 指向的算子目录必须真实存在，
   实现里 import 的算子必须已声明。

spec 的五层提取内容（L0–L4）由流水线生成；本模块只保证生成物**可被机器消费**，
不评价生成得对不对——那是 HITL 与 oracle 的职责。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "FIVE_FAMILIES",
    "CATEGORIES",
    "REQUIRED_FIELDS",
    "load_spec",
    "load_operator_specs",
    "validate_spec",
]

FIVE_FAMILIES = {"T", "C", "S", "I", "N"}  # 相切 / 共面重合 / sliver / 自交非流形 / 数值抵消

CATEGORIES = {
    "curve",
    "surface",
    "topology",
    "boolean",
    "constraint",
    "sketch",
    "blend",
    "measure",
    "mesh",
}

REQUIRED_FIELDS = (
    "slug",
    "name",
    "category",
    "dim",
    "version",
    "source",
    "signature",
    "preconditions",
    "invariants",
    "degeneracy_branches",
    "oracle_tests",
)


def load_spec(path: Path) -> Dict[str, Any]:
    """读取 spec.json（UTF-8）。解析失败抛 ``json.JSONDecodeError``，由调用方决定是否升级。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_operator_specs(root: Path) -> Dict[str, Dict[str, Any]]:
    """扫描 ``operators/*/spec.json``，返回 {slug: spec}。"""
    specs: Dict[str, Dict[str, Any]] = {}
    operators = Path(root) / "operators"
    for child in sorted(operators.iterdir()):
        spec_path = child / "spec.json"
        if spec_path.is_file():
            spec = load_spec(spec_path)
            specs[child.name] = spec
    return specs


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_spec(spec: Dict[str, Any], expected_slug: Optional[str] = None) -> List[str]:
    """返回问题列表（空 = 合法）。消息要能直接当修复指令用。"""
    problems: List[str] = []

    for field in REQUIRED_FIELDS:
        if field not in spec:
            problems.append(f"缺少必填字段 {field!r}")
    if problems:
        return problems

    if not _non_empty_str(spec["slug"]):
        problems.append("slug 必须是非空字符串")
    if expected_slug is not None and spec["slug"] != expected_slug:
        problems.append(f"slug={spec['slug']!r} 与目录名 {expected_slug!r} 不一致")
    if not _non_empty_str(spec["name"]):
        problems.append("name 必须是非空字符串")
    if spec["category"] not in CATEGORIES:
        problems.append(f"category={spec['category']!r} 不在 {sorted(CATEGORIES)} 内")
    if spec["dim"] not in {"2D", "3D", "any"}:
        problems.append(f"dim={spec['dim']!r} 必须是 2D / 3D / any")
    if not _non_empty_str(spec["version"]):
        problems.append("version 必须是非空字符串")
    if not _non_empty_str(spec["source"]):
        problems.append("source 必须是非空字符串（公式/算法出处）")

    signature = spec["signature"]
    if not isinstance(signature, dict):
        problems.append("signature 必须是对象")
    else:
        if not isinstance(signature.get("inputs"), dict) or not signature["inputs"]:
            problems.append("signature.inputs 必须是非空对象")
        if not isinstance(signature.get("outputs"), (list, str)) or not signature["outputs"]:
            problems.append("signature.outputs 必须是非空列表或字符串")

    for field in ("preconditions", "invariants"):
        value = spec[field]
        if not isinstance(value, list) or not value or not all(_non_empty_str(v) for v in value):
            problems.append(f"{field} 必须是非空字符串列表")
    if not _non_empty_str(spec["oracle_tests"]):
        problems.append("oracle_tests 必须是非空字符串（测试出处）")

    branches = spec["degeneracy_branches"]
    if not isinstance(branches, list) or not branches:
        problems.append("degeneracy_branches 必须是非空列表")
    else:
        for i, branch in enumerate(branches):
            if not isinstance(branch, dict):
                problems.append(f"degeneracy_branches[{i}] 必须是对象")
                continue
            if branch.get("family") not in FIVE_FAMILIES:
                problems.append(
                    f"degeneracy_branches[{i}].family={branch.get('family')!r} 必须是五族之一 "
                    f"{sorted(FIVE_FAMILIES)}"
                )
            for key in ("trigger", "action"):
                if not _non_empty_str(branch.get(key)):
                    problems.append(f"degeneracy_branches[{i}].{key} 必须是非空字符串")

    depends_on = spec.get("depends_on", [])
    if not isinstance(depends_on, list) or not all(_non_empty_str(d) for d in depends_on):
        problems.append("depends_on 必须是算子 slug 字符串列表")
    return problems
