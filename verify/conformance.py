"""算子级 conformance suite：声明式用例 → 可复跑的证据。

动机
----
2026 年出现的 CAD 评测（CADTests / CADBench / RealCADBench）全部是**黑盒**：喂一个模型、
收一个分数。没有任何一层在几何算子上检查「容差语义、退化分支、等价性」。本模块是那个
白盒缺口的第一个可运行实现——每个用例是一份 JSON，钉死一个算子在**具体输入**上的
可测行为；整套用例可离线复跑，并产出机器可读的证据报告。

用例格式（``verify/cases/<operator>.json``）
-------------------------------------------
::

    {
      "operator": "curve_eval",
      "cases": [
        {
          "case_id": "curve_eval.point.bezier_quadratic",
          "module": "operators.curve_eval.impl",
          "function": "curve_point",
          "args": [[0,0,0,1,1,1], 2, [[0,0],[1,1],[2,0]], 0.25],
          "checks": [{"kind": "close", "expected": [0.75, 0.375], "rel_tol": 1e-12}],
          "tags": ["analytic"]
        }
      ]
    }

检查类型
--------
- ``close``：与期望值逐元素比较（相对 + 绝对容差）；
- ``exact``：严格相等（布尔、整数、枚举、字符串）；
- ``raises``：期望抛指定异常（可带消息子串）。

设计边界：本套件**不**取代测试。用例是「回归钉」，公开、稳定、可对拍；探索性、
大规模随机、差分对拍仍留在 pytest。
"""

from __future__ import annotations

import importlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "CheckResult",
    "SuiteReport",
    "ROOT",
    "CASES_DIR",
    "load_cases",
    "run_case",
    "run_suite",
    "check_coverage",
    "EXCEPTIONS",
]

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / "cases"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # 例外名解析：DomainError 是本仓库的默认拒绝语义
    from primitives.bspline import DomainError
except ImportError:  # pragma: no cover - 仅在安装损坏时触发
    DomainError = ValueError  # type: ignore[assignment,misc]

EXCEPTIONS = {
    "DomainError": DomainError,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "ZeroDivisionError": ZeroDivisionError,
    "ArithmeticError": ArithmeticError,
    "NotImplementedError": NotImplementedError,
}


@dataclass(frozen=True)
class CheckResult:
    case_id: str
    operator: str
    index: int
    kind: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "operator": self.operator,
            "index": self.index,
            "kind": self.kind,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass
class SuiteReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def failures(self) -> List[CheckResult]:
        return [r for r in self.results if not r.ok]

    def cases(self) -> Dict[str, bool]:
        """按 case 聚合：任一检查失败即该 case 失败。"""
        out: Dict[str, bool] = {}
        for r in self.results:
            out[r.case_id] = out.get(r.case_id, True) and r.ok
        return out

    def summary(self) -> dict:
        cases = self.cases()
        by_operator: Dict[str, Dict[str, int]] = {}
        for r in self.results:
            slot = by_operator.setdefault(r.operator, {"checks": 0, "failed": 0})
            slot["checks"] += 1
            slot["failed"] += 0 if r.ok else 1
        return {
            "cases": len(cases),
            "cases_passed": sum(1 for ok in cases.values() if ok),
            "checks": len(self.results),
            "checks_passed": self.passed,
            "checks_failed": self.failed,
            "by_operator": by_operator,
        }

    def write_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": self.summary(), "results": [r.as_dict() for r in self.results]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ 加载


def load_cases(cases_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取 ``verify/cases/*.json``，展平为用例列表。结构非法 → ``ValueError``（不静默）。"""
    directory = Path(cases_dir) if cases_dir is not None else CASES_DIR
    if not directory.is_dir():
        raise ValueError(f"用例目录不存在：{directory}")
    cases: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(blob, dict) or "cases" not in blob:
            raise ValueError(f"{path.name}: 顶层必须是含 'cases' 的对象")
        operator = blob.get("operator")
        if not isinstance(operator, str) or not operator:
            raise ValueError(f"{path.name}: 缺少 operator 字段")
        if path.stem != operator:
            raise ValueError(f"{path.name}: 文件名与 operator={operator!r} 不一致")
        for case in blob["cases"]:
            if "case_id" not in case or "module" not in case or "function" not in case:
                raise ValueError(f"{path.name}: 用例缺少 case_id/module/function：{case!r}")
            case = dict(case)
            case.setdefault("operator", operator)
            cases.append(case)
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id 必须全局唯一")
    return cases


# ------------------------------------------------------------------ 比较


def _close(actual: Any, expected: Any, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if isinstance(actual, float) and math.isnan(actual):
            return False
        return abs(actual - expected) <= max(abs_tol, rel_tol * abs(float(expected)))
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(actual) != len(expected):
            return False
        return all(
            _close(a, e, rel_tol, abs_tol) for a, e in zip(actual, expected)
        )
    return actual == expected


def _exact(actual: Any, expected: Any) -> bool:
    """严格相等；序列按结构逐元素比较（tuple 与 JSON 的 list 视为同构）。"""
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        return len(actual) == len(expected) and all(_exact(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _resolve(name: str):
    if name in EXCEPTIONS:
        return EXCEPTIONS[name]
    module_name, _, attr = name.rpartition(".")
    if not module_name:
        raise ValueError(f"无法解析异常名 {name!r}")
    return getattr(importlib.import_module(module_name), attr)


# ------------------------------------------------------------------ 执行


def run_case(case: Dict[str, Any]) -> List[CheckResult]:
    case_id = case["case_id"]
    operator = case.get("operator", "?")
    func = getattr(importlib.import_module(case["module"]), case["function"])
    args = case.get("args", [])
    kwargs = case.get("kwargs", {})
    checks = case.get("checks") or []
    if not checks:
        raise ValueError(f"{case_id}: 至少需要一个 check")

    outcome: List[CheckResult] = []
    raised: Optional[BaseException] = None
    try:
        actual = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 被测算子抛什么都要能记录
        actual = None
        raised = exc

    for index, check in enumerate(checks):
        kind = check.get("kind")
        try:
            if kind == "raises":
                if raised is None:
                    outcome.append(CheckResult(case_id, operator, index, kind, False, "未抛异常"))
                    continue
                expected_exc = _resolve(check.get("exception", "DomainError"))
                ok = isinstance(raised, expected_exc)
                if ok and check.get("match"):
                    ok = check["match"] in str(raised)
                detail = "" if ok else f"实际异常 {type(raised).__name__}: {raised}"
                outcome.append(CheckResult(case_id, operator, index, kind, ok, detail))
                continue

            if raised is not None:
                outcome.append(
                    CheckResult(
                        case_id, operator, index, str(kind), False,
                        f"意外异常 {type(raised).__name__}: {raised}",
                    )
                )
                continue

            if kind == "close":
                ok = _close(
                    actual,
                    check["expected"],
                    float(check.get("rel_tol", 1e-9)),
                    float(check.get("abs_tol", 1e-12)),
                )
                detail = "" if ok else f"actual={actual!r} expected={check['expected']!r}"
                outcome.append(CheckResult(case_id, operator, index, kind, ok, detail))
            elif kind == "exact":
                ok = _exact(actual, check["expected"])
                detail = "" if ok else f"actual={actual!r} expected={check['expected']!r}"
                outcome.append(CheckResult(case_id, operator, index, kind, ok, detail))
            else:
                raise ValueError(f"{case_id}: 未知 check kind={kind!r}")
        except Exception as exc:  # noqa: BLE001 - 检查器自身出错也要记为该 case 失败
            outcome.append(
                CheckResult(case_id, operator, index, str(kind), False, f"检查执行失败：{exc}")
            )
    return outcome


def run_suite(cases: Optional[Sequence[Dict[str, Any]]] = None) -> SuiteReport:
    cases = list(cases) if cases is not None else load_cases()
    report = SuiteReport()
    for case in cases:
        report.results.extend(run_case(case))
    return report


def check_coverage(root: Path = ROOT, cases: Optional[Sequence[Dict[str, Any]]] = None) -> List[str]:
    """每个有 spec.json 的算子都必须有用例；返回缺失的算子 slug 列表。"""
    cases = list(cases) if cases is not None else load_cases()
    covered = {c["operator"] for c in cases}
    missing: List[str] = []
    for child in sorted((Path(root) / "operators").iterdir()):
        if child.is_dir() and (child / "spec.json").is_file() and child.name not in covered:
            missing.append(child.name)
    return missing
