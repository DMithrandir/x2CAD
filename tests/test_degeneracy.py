"""退化知识库的 schema 校验：语料必须可被机器消费，且每条都指向真实可执行的用例。

校验内容（对应母文档 §5 的「索引机制」）：
- 五族齐全，每族 ≥ 3 条；
- id 唯一且前缀与 family 一致；
- 每条都有触发信号（可编译的 regex）、场景、修复模式、最小用例、关联算子；
- 触发器正则必须能编译（检索注入时直接使用）；
- ``test`` 指向的测试文件与函数必须真实存在（否则语料就是死链）。
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "degeneracy" / "index.json"
FAMILIES = {"T", "C", "S", "I", "N"}

_MODULE_CACHE = {}


def _load_test_module(path: Path):
    key = str(path)
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]
    modname = "degeneracy_target_" + path.stem
    tests_dir = str(path.parent)
    inserted = False
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(tests_dir)
    _MODULE_CACHE[key] = module
    return module


def _index():
    return json.loads(INDEX.read_text(encoding="utf-8"))


def test_index_structure_and_family_coverage():
    blob = _index()
    assert blob["version"]
    assert set(blob["families"]) == FAMILIES
    entries = blob["entries"]
    assert len(entries) >= 15
    counts = {family: 0 for family in FAMILIES}
    for entry in entries:
        family = entry["family"]
        assert family in FAMILIES, entry["id"]
        counts[family] += 1
        assert entry["id"].startswith(family + "-"), entry["id"]
        assert entry["title"].strip()
        assert entry["scenario"].strip()
        assert entry["remediation"].strip()
        assert isinstance(entry["triggers"], list) and entry["triggers"]
        assert isinstance(entry["operators"], list) and entry["operators"]
        for trigger in entry["triggers"]:
            re.compile(trigger)  # 必须可编译
    for family, count in counts.items():
        assert count >= 3, f"{family} 族条目不足：{count}"


def test_ids_are_unique():
    ids = [entry["id"] for entry in _index()["entries"]]
    assert len(ids) == len(set(ids))


def test_every_entry_points_to_a_real_test():
    missing = []
    for entry in _index()["entries"]:
        node = entry["test"]
        file_part, sep, func = node.partition("::")
        assert sep and file_part and func, node
        path = ROOT / file_part
        if not path.is_file():
            missing.append((entry["id"], f"缺少文件 {file_part}"))
            continue
        module = _load_test_module(path)
        if not hasattr(module, func):
            missing.append((entry["id"], f"{file_part} 中无 {func}"))
    assert missing == [], f"语料死链：{missing}"


def test_triggers_are_lowercase_keywords():
    """触发词用于 L2/L4 输出上的词法匹配：统一小写，避免大小写两套口径。"""
    for entry in _index()["entries"]:
        for trigger in entry["triggers"]:
            assert trigger == trigger.lower(), (entry["id"], trigger)
