"""预言机变异自审（设计文档 §7.4）：先证明验证台抓得住错，再信任它。

做法
----
对已知正确的算子源码注入**故意变异**（符号翻转、公式改错、跳过退化分支、放宽容差），
跑该算子对应的测试子集：
- 测试变红 → 变异被**杀死**（oracle 有效）；
- 测试仍绿 → 变异**存活**（oracle 有盲区，必须先修 oracle，不能继续加算子）。

变异用「源码里的唯一子串替换」表达（``find`` → ``replace``），因此：
1. 变异是**真实代码**上的，不是 mock；被杀死说明真实测试路径覆盖了该逻辑；
2. 每个变异必须命中恰好一次，否则视为变异定义失效（报错，不静默跳过）；
3. 变更后立即恢复原文件（``finally``），并校验恢复后的哈希；
4. 变异后源码必须仍可解析（``ast.parse``），避免"语法错误导致的假杀死"；
5. **禁用字节码写入并清除对应 .pyc**。这条是实测踩坑后的硬要求：变异前后的源码常常
   **长度相同**（如 ``-`` → ``+``），若注入与恢复发生在同一整数秒内，CPython 的
   ``(mtime, size)`` 校验会认为旧 .pyc 有效——于是后续进程加载的是**变异后的字节码**，
   工作区看起来已恢复、行为却仍是坏的。这正是"预言机本身必须被审计"的又一例证。

这一步的产出 ``mutation_report.json`` 是验证台的**校准证书**：捕获率 100% 之前，
任何算子的"全绿"都不算数。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

__all__ = ["Mutant", "MutationOutcome", "MutationReport", "load_mutants", "run_audit", "main"]

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MUTANTS = Path(__file__).resolve().parent / "audit" / "mutants.json"


@dataclass(frozen=True)
class Mutant:
    id: str
    file: str
    find: str
    replace: str
    tests: Sequence[str]
    description: str = ""
    expect: str = "killed"


@dataclass(frozen=True)
class MutationOutcome:
    mutant_id: str
    description: str
    killed: bool
    returncode: int
    detail: str = ""


@dataclass
class MutationReport:
    outcomes: List[MutationOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def killed(self) -> int:
        return sum(1 for o in self.outcomes if o.killed)

    @property
    def survived(self) -> List[MutationOutcome]:
        return [o for o in self.outcomes if not o.killed]

    @property
    def capture_rate(self) -> float:
        return self.killed / self.total if self.total else 0.0

    def summary(self) -> dict:
        return {
            "total": self.total,
            "killed": self.killed,
            "survived": len(self.survived),
            "capture_rate": self.capture_rate,
        }

    def to_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": self.summary(),
            "outcomes": [o.__dict__ for o in self.outcomes],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_mutants(path: Path = DEFAULT_MUTANTS) -> List[Mutant]:
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    mutants = []
    for item in blob["mutants"]:
        mutants.append(
            Mutant(
                id=item["id"],
                file=item["file"],
                find=item["find"],
                replace=item["replace"],
                tests=tuple(item["tests"]),
                description=item.get("description", ""),
                expect=item.get("expect", "killed"),
            )
        )
    ids = [m.id for m in mutants]
    if len(ids) != len(set(ids)):
        raise ValueError("变异 id 必须唯一")
    return mutants


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _invalidate_bytecode(path: Path) -> None:
    """删除该源文件对应的 .pyc：防止 CPython 用 (mtime, size) 复用变异后的字节码。"""
    cache_dir = path.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    for pyc in cache_dir.glob(f"{path.stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def run_audit(
    mutants: Sequence[Mutant],
    root: Path = ROOT,
    *,
    timeout: int = 120,
) -> MutationReport:
    """逐个注入变异、跑指定测试、恢复源码，返回捕获报告。"""
    root = Path(root)
    report = MutationReport()
    for mutant in mutants:
        path = root / mutant.file
        original = path.read_text(encoding="utf-8")
        hits = original.count(mutant.find)
        if hits != 1:
            raise ValueError(
                f"变异 {mutant.id}: {mutant.file} 中 find 子串出现 {hits} 次（必须恰好 1 次）"
            )
        mutated = original.replace(mutant.find, mutant.replace)
        ast.parse(mutated)  # 语法错误 → 这里直接抛，不会误记为"杀死"

        before = _sha256(original)
        path.write_text(mutated, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # 变异期间绝不生成 .pyc
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
                    *mutant.tests,
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
            killed = proc.returncode != 0
            tail = (proc.stdout or "").strip().splitlines()
            detail = tail[-1] if tail else ""
            if proc.returncode == 5:
                raise ValueError(f"变异 {mutant.id}: 测试选择为空（pytest 退出码 5）")
            report.outcomes.append(
                MutationOutcome(mutant.id, mutant.description, killed, proc.returncode, detail)
            )
        finally:
            path.write_text(original, encoding="utf-8")
            _invalidate_bytecode(path)
            if _sha256(path.read_text(encoding="utf-8")) != before:
                raise RuntimeError(f"变异 {mutant.id}: 源码恢复失败，工作区可能已损坏")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="预言机变异自审")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--mutants", default=str(DEFAULT_MUTANTS))
    parser.add_argument(
        "--report", default=str(Path(__file__).resolve().parent / "audit" / "mutation_report.json")
    )
    args = parser.parse_args(argv)

    mutants = load_mutants(Path(args.mutants))
    report = run_audit(mutants, Path(args.root))
    report.to_json(Path(args.report))
    for outcome in report.outcomes:
        status = "KILLED" if outcome.killed else "SURVIVED"
        print(f"{status:9s} {outcome.mutant_id:36s} {outcome.description}")
    print(
        f"捕获率 {report.killed}/{report.total} = {report.capture_rate:.0%}；"
        f"报告 {args.report}"
    )
    return 0 if not report.survived else 1


if __name__ == "__main__":
    sys.exit(main())
