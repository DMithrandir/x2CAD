"""产物缓存 oracle：命中/未命中、失效矩阵、持久化、完整性自检、原子性。

这是 Phase 0 学习教材的「红绿见证」：缓存正确性的唯一判据是这些测试，
不是缓存代码看起来对（CLAUDE.md 纪律的脚手架版）。

核心判据：同一 (stage, version, inputs, deps) 第二次访问必须 0 次 compute 调用；
任一维变化（输入 / 版本 / 依赖）必须重算——「缓存与失效规则成对出现」。
"""

import json

import pytest

from x2cad import ArtifactCache, CacheError

STAGE = "ref2spec_L2"
VERSION = "v1"
INPUTS = {
    "doc_id": "nurbs-book-a5.1",
    "slice": "boehm knot insertion",
    "focus": ["algo", "domain"],
}


def _counting(fn):
    """包一层计数函数：模拟「一次 LLM API 调用」。"""
    calls = {"n": 0}

    def wrapped():
        calls["n"] += 1
        return fn()

    return wrapped, calls


def test_same_inputs_compute_once(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    compute, calls = _counting(lambda: {"L2": "math domain"})

    first = cache.get_or_compute(STAGE, VERSION, INPUTS, compute)
    second = cache.get_or_compute(STAGE, VERSION, INPUTS, compute)

    assert first == second == {"L2": "math domain"}
    assert calls["n"] == 1  # 第二次 0 次「API 调用」
    assert (cache.hits, cache.misses) == (1, 1)


def test_changed_input_recomputes(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    compute, calls = _counting(lambda: {"n": calls["n"]})

    cache.get_or_compute(STAGE, VERSION, INPUTS, compute)
    changed = dict(INPUTS, focus=["algo"])  # 输入任一变化 → 键变化
    out = cache.get_or_compute(STAGE, VERSION, changed, compute)

    assert calls["n"] == 2
    assert out == {"n": 2}


def test_version_bump_invalidates(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    compute, calls = _counting(lambda: "impl-v1")

    assert cache.get_or_compute(STAGE, "v1", INPUTS, compute) == "impl-v1"
    assert cache.get_or_compute(STAGE, "v2", INPUTS, compute) == "impl-v1"
    assert calls["n"] == 2  # 模板版本 bump → 整体失效，这正是失效纪律


def test_deps_bump_invalidates(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    compute, calls = _counting(lambda: "codegen")

    cache.get_or_compute(STAGE, VERSION, INPUTS, compute, deps={"template": "v1"})
    cache.get_or_compute(STAGE, VERSION, INPUTS, compute, deps={"template": "v2"})

    assert calls["n"] == 2  # 退化语料/模板版本经 deps 进入键


def test_key_independent_of_dict_order(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    reordered = {"focus": INPUTS["focus"], "doc_id": INPUTS["doc_id"], "slice": INPUTS["slice"]}
    assert cache.key(STAGE, VERSION, INPUTS) == cache.key(STAGE, VERSION, reordered)


def test_persists_across_instances(tmp_path):
    root = tmp_path / ".cache"
    ArtifactCache(root).store(STAGE, VERSION, INPUTS, {"L3": "pipeline"})

    fresh = ArtifactCache(root)
    assert fresh.load(STAGE, VERSION, INPUTS) == {"L3": "pipeline"}
    assert fresh.hits == 1


def test_corrupted_payload_raises(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    cache.store(STAGE, VERSION, INPUTS, {"L2": "intact"})

    path = tmp_path / ".cache" / (cache.key(STAGE, VERSION, INPUTS) + ".json")
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["payload"] = {"L2": "tampered"}  # 篡改但不改哈希 → 必须被抓
    path.write_text(json.dumps(blob), encoding="utf-8")

    with pytest.raises(CacheError, match="损坏"):
        cache.load(STAGE, VERSION, INPUTS)


def test_failed_compute_stores_nothing(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")

    def boom():
        raise RuntimeError("LLM 调用失败")

    with pytest.raises(RuntimeError):
        cache.get_or_compute(STAGE, VERSION, INPUTS, boom)

    assert cache.load(STAGE, VERSION, INPUTS) is None  # 不落半截产物
    assert list((tmp_path / ".cache").glob("*.json")) == []  # 连 tmp 也不残留


def test_invalid_inputs_rejected(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    with pytest.raises(CacheError, match="JSON 可序列化"):
        cache.key(STAGE, VERSION, {"bad": object()})


def test_invalid_stage_rejected(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    with pytest.raises(CacheError, match="stage"):
        cache.key("a/b", VERSION, INPUTS)


def test_none_payload_rejected(tmp_path):
    cache = ArtifactCache(tmp_path / ".cache")
    with pytest.raises(CacheError, match="None"):
        cache.store(STAGE, VERSION, INPUTS, None)
