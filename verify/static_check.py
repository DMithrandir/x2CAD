"""静态检查器：把「AI 会脑补的东西」变成机器可拒绝的形状。

设计文档 §4.3 要求 spec2op 产出的实现先过静态检查、再进验证台。本模块是那道闸门的最小实现，
规则全部是**可静态判定**的（AST 级），不做语义猜测：

======================  ==================================================
规则                     拒绝什么
======================  ==================================================
SC001 SWALLOWED_ERROR    ``except ...: pass`` / ``return None`` —— 吞异常
SC002 NONDETERMINISM     算子实现 import ``random`` / ``time`` / ``uuid`` 等，
                         或调用 ``id()`` —— 同输入必须同输出
SC003 IO_IN_OPERATOR     算子实现里 ``print`` / ``open`` —— 纯函数纪律
SC004 FLOAT_LITERAL_EQ   与非零浮点字面量做 ``==`` / ``!=`` —— 裸比较几何量
SC005 PRIVATE_IMPORT     跨算子 import 私有符号（下划线开头）
SC006 UNDECLARED_DEPENDENCY  import 了别的算子但 spec.depends_on 没声明
======================  ==================================================

SC004 的口径是「**非零**浮点字面量」，不是「任何浮点比较」：``u == U[n+1]`` 这类对节点值的
精确比较是行内约定（右连续），静态上无法与 bug 区分，交给人工审查；``x == 0.0`` 是
"精确为零"的退化分支守卫（零在浮点里精确可表示），也放行；而 ``if x == 0.5`` 这种写法
在任何语义下都该走容差上下文。
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from verify.spec_check import load_spec, validate_spec

__all__ = ["Finding", "check_source", "check_operator_dir", "check_repo", "format_findings"]

_NONDETERMINISTIC_MODULES = {"random", "time", "secrets", "uuid", "tempfile"}
_IO_CALLS = {"print", "open", "input"}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.path}:{self.line} {self.message}"


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: List[Finding] = []

    def _add(self, rule: str, node: ast.AST, message: str) -> None:
        self.findings.append(Finding(rule, self.path, getattr(node, "lineno", 0), message))

    # ---- SC001 --------------------------------------------------------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        body = node.body
        swallowed = all(
            isinstance(stmt, ast.Pass)
            or (isinstance(stmt, ast.Return) and (stmt.value is None or _is_none(stmt.value)))
            for stmt in body
        )
        if swallowed and body:
            self._add("SC001", node, "异常被静默吞掉（pass / return None）；违者必须让错误显式传播")
        self.generic_visit(node)

    # ---- SC002 / SC003 / SC005 ---------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in _NONDETERMINISTIC_MODULES:
                self._add("SC002", node, f"算子实现不得 import 非确定性模块 {alias.name!r}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.split(".")[0] in _NONDETERMINISTIC_MODULES:
            self._add("SC002", node, f"算子实现不得 import 非确定性模块 {module!r}")
        if module.startswith("operators."):
            for alias in node.names:
                if alias.name.startswith("_"):
                    self._add(
                        "SC005", node,
                        f"不得 import 其它算子的私有符号 {module}.{alias.name}",
                    )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in _IO_CALLS:
                self._add("SC003", node, f"算子实现不得调用 {node.func.id}()（纯函数、无 IO）")
            if node.func.id in {"id", "eval", "exec"}:
                self._add("SC002", node, f"算子实现不得调用 {node.func.id}()")
        self.generic_visit(node)

    # ---- SC004 --------------------------------------------------------
    def visit_Compare(self, node: ast.Compare) -> None:
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            operands = [node.left] + list(node.comparators)
            for operand in operands:
                if (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, float)
                    and operand.value != 0.0
                ):
                    self._add(
                        "SC004", node,
                        f"与浮点字面量 {operand.value!r} 做 ==/!=：几何量比较必须经容差上下文",
                    )
                    break
        self.generic_visit(node)


def check_source(text: str, path: str = "<memory>") -> List[Finding]:
    """对一段 Python 源码跑全部静态规则。语法错误直接抛 ``SyntaxError``（不静默）。"""
    tree = ast.parse(text, filename=path)
    visitor = _Visitor(path)
    visitor.visit(tree)
    return sorted(visitor.findings, key=lambda f: (f.line, f.rule))


# ------------------------------------------------------------------ 目录级


def _operator_imports(text: str) -> List[str]:
    tree = ast.parse(text)
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("operators."):
            parts = node.module.split(".")
            if len(parts) >= 2:
                deps.add(parts[1])
    return sorted(deps)


def check_operator_dir(path: Path) -> List[Finding]:
    """检查一个算子目录：spec 合法 + impl 通过静态规则 + 依赖声明齐全。"""
    path = Path(path)
    findings: List[Finding] = []
    spec_path = path / "spec.json"
    impl_path = path / "impl.py"
    if not spec_path.exists():
        findings.append(Finding("SC007", str(spec_path), 0, "缺少 spec.json"))
        return findings
    if not impl_path.exists():
        findings.append(Finding("SC007", str(impl_path), 0, "缺少 impl.py"))
        return findings

    try:
        spec = load_spec(spec_path)
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(Finding("SC007", str(spec_path), 0, f"spec.json 不可解析：{exc}"))
        return findings
    for problem in validate_spec(spec, expected_slug=path.name):
        findings.append(Finding("SC008", str(spec_path), 0, problem))

    text = impl_path.read_text(encoding="utf-8")
    findings.extend(check_source(text, str(impl_path)))

    declared = set(spec.get("depends_on") or [])
    for dep in _operator_imports(text):
        if dep != path.name and dep not in declared:
            findings.append(
                Finding(
                    "SC006", str(impl_path), 0,
                    f"依赖算子 {dep!r} 未在 spec.depends_on 中声明",
                )
            )
    for dep in declared:
        if not (path.parent / dep).is_dir():
            findings.append(
                Finding("SC008", str(spec_path), 0, f"spec.depends_on 指向不存在的算子目录 {dep!r}")
            )
    return sorted(findings, key=lambda f: (f.path, f.line, f.rule))


def check_repo(root: Path) -> List[Finding]:
    operators = Path(root) / "operators"
    findings: List[Finding] = []
    for child in sorted(operators.iterdir()):
        if child.is_dir() and (child / "spec.json").exists():
            findings.extend(check_operator_dir(child))
    return findings


def format_findings(findings: Sequence[Finding]) -> str:
    if not findings:
        return "OK：0 条静态检查问题"
    return "\n".join(str(f) for f in findings)
