"""预言机变异自审的测试（设计文档 §7.4 的硬性里程碑）。

约定：**捕获率必须 100%**。任何一个变异存活都意味着验证台有盲区——
先修 oracle，再继续加算子。这个测试本身是本仓库最慢的一个（每个变异起一个 pytest
子进程），但它证明的是"所有其它绿都是真的"。
"""

from pathlib import Path

import pytest

from verify.mutation import load_mutants, run_audit

ROOT = Path(__file__).resolve().parents[1]


def test_mutant_definitions_are_well_formed():
    mutants = load_mutants()
    assert len(mutants) >= 8
    assert len({m.id for m in mutants}) == len(mutants)
    for mutant in mutants:
        text = (ROOT / mutant.file).read_text(encoding="utf-8")
        assert text.count(mutant.find) == 1, mutant.id
        assert mutant.tests, mutant.id


def test_oracle_mutation_audit_captures_every_mutant():
    mutants = load_mutants()
    report = run_audit(mutants, ROOT)
    survived = [o.mutant_id for o in report.survived]
    assert survived == [], f"验证台存在盲区，以下变异存活：{survived}"
    assert report.capture_rate == pytest.approx(1.0)
    assert report.total >= 8
    # 审计必须把工作区恢复原样：这是 2026-11-09 实测踩坑后加的回归断言。
    # 当时变异前后的源码长度相同（- → +），恢复发生在同一整数秒内，CPython 的
    # (mtime, size) 校验复用了变异后的 .pyc，导致"磁盘已恢复、行为仍坏"。
    for mutant in mutants:
        text = (ROOT / mutant.file).read_text(encoding="utf-8")
        assert text.count(mutant.find) == 1, f"审计后 {mutant.file} 未恢复原样（{mutant.id}）"
