"""EntityRef 契约的 oracle：重放不变量、tombstone 拒绝、类型安全、选择歧义、派生寻址。"""

import math

import pytest

from kernel.entity_ref import (
    DerivedRef,
    EntityKind,
    EntityRef,
    EntityTable,
    RefMapping,
    RefResolutionError,
    TombstoneError,
    resolve,
    resolve_derived,
    select_nearest,
)
from primitives.bspline import DomainError
from primitives.tolerance import ToleranceContext


def _build_model() -> EntityTable:
    """一个确定性的建模脚本等价物：3 个顶点、2 条边、1 个面。"""
    table = EntityTable()
    v0 = table.create(EntityKind.VERTEX, (0.0, 0.0))
    v1 = table.create(EntityKind.VERTEX, (1.0, 0.0))
    v2 = table.create(EntityKind.VERTEX, (0.0, 1.0))
    table.create(EntityKind.EDGE, (v0, v1))
    table.create(EntityKind.EDGE, (v1, v2))
    table.create(EntityKind.FACE, (v0, v1, v2))
    return table


def test_ids_are_deterministic_and_prefixed():
    table = _build_model()
    assert [r.id for r in table.refs()] == ["v0", "v1", "v2", "e0", "e1", "f0"]
    assert [r.kind for r in table.refs(EntityKind.EDGE)] == [EntityKind.EDGE, EntityKind.EDGE]
    assert len(table) == 6


def test_replay_invariance():
    """同一脚本重放两遍，id 序列（快照）必须逐位相同。"""
    first = _build_model().snapshot()
    second = _build_model().snapshot()
    assert first == second
    assert first[0] == ("vertex", "v0")


def test_get_returns_payload_and_checks_kind():
    table = EntityTable()
    v0 = table.create(EntityKind.VERTEX, (3.0, 4.0))
    assert table.get(v0) == (3.0, 4.0)
    wrong = EntityRef(EntityKind.EDGE, v0.id)
    with pytest.raises(RefResolutionError, match="类型"):
        table.get(wrong)


def test_unknown_ref_is_rejected():
    table = EntityTable()
    with pytest.raises(RefResolutionError, match="不在当前模型"):
        table.get(EntityRef(EntityKind.VERTEX, "v99"))


def test_remap_preserves_kind_and_resolves_to_new_payload():
    new = EntityTable()
    moved = new.create(EntityKind.VERTEX, (10.0, 0.0))
    kept = new.create(EntityKind.VERTEX, (11.0, 0.0))
    mapping = RefMapping().remap(EntityRef(EntityKind.VERTEX, "v0"), moved)
    current, payload = resolve(EntityRef(EntityKind.VERTEX, "v0"), new, mapping)
    assert current == moved
    assert payload == (10.0, 0.0)
    # 未出现在映射中的 id 视为恒等（实体未变异 → id 不变）
    other, other_payload = resolve(EntityRef(EntityKind.VERTEX, "v1"), new, mapping)
    assert other == kept
    assert other_payload == (11.0, 0.0)


def test_remap_kind_mismatch_is_rejected():
    mapping = RefMapping()
    with pytest.raises(DomainError):
        mapping.remap(
            EntityRef(EntityKind.EDGE, "e0"), EntityRef(EntityKind.FACE, "f0")
        )


def test_tombstone_reference_raises_and_cannot_be_remapped():
    mapping = RefMapping().tombstone(EntityRef(EntityKind.EDGE, "e0"))
    with pytest.raises(TombstoneError, match="删除"):
        mapping.map(EntityRef(EntityKind.EDGE, "e0"))
    with pytest.raises(TombstoneError):
        resolve(EntityRef(EntityKind.EDGE, "e0"), EntityTable(), mapping)
    with pytest.raises(DomainError):
        mapping.remap(EntityRef(EntityKind.EDGE, "e0"), EntityRef(EntityKind.EDGE, "e9"))


def test_mapping_report_is_serializable():
    v_new = EntityRef(EntityKind.VERTEX, "v7")
    mapping = (
        RefMapping()
        .remap(EntityRef(EntityKind.VERTEX, "v0"), v_new)
        .tombstone(EntityRef(EntityKind.EDGE, "e1"))
    )
    blob = mapping.to_dict()
    assert blob["mapped"]["v0"] == {"kind": "vertex", "id": "v7"}
    assert blob["tombstones"] == ["e1"]
    assert EntityRef.from_dict(blob["mapped"]["v0"]) == v_new


def test_refs_are_hashable_and_ordered():
    refs = {
        EntityRef(EntityKind.VERTEX, "v0"),
        EntityRef(EntityKind.VERTEX, "v0"),
        EntityRef(EntityKind.EDGE, "e0"),
    }
    assert len(refs) == 2
    assert EntityRef(EntityKind.VERTEX, "v0") < EntityRef(EntityKind.VERTEX, "v1")


def test_select_nearest_unique_choice():
    candidates = [EntityRef(EntityKind.FACE, "f0"), EntityRef(EntityKind.FACE, "f1")]
    dists = {"f0": 0.5, "f1": 0.2}
    tol = ToleranceContext(atol=1e-12, rtol=0.0)
    assert select_nearest(candidates, lambda r: dists[r.id], tol).id == "f1"


def test_select_nearest_tie_is_explicit_error():
    candidates = [EntityRef(EntityKind.EDGE, "e0"), EntityRef(EntityKind.EDGE, "e1")]
    tol = ToleranceContext(atol=1e-12, rtol=0.0)
    with pytest.raises(DomainError, match="歧义"):
        select_nearest(candidates, lambda r: 0.5, tol)
    # 差距超出容差 → 不算平局
    dists = {"e0": 0.5, "e1": 0.5001}
    assert select_nearest(candidates, lambda r: dists[r.id], tol).id == "e0"


def test_select_nearest_rejects_empty_and_nan():
    tol = ToleranceContext()
    with pytest.raises(RefResolutionError):
        select_nearest([], lambda r: 0.0, tol)
    with pytest.raises(DomainError):
        select_nearest([EntityRef(EntityKind.EDGE, "e0")], lambda r: float("nan"), tol)


def test_invalid_ref_construction():
    with pytest.raises(DomainError):
        EntityRef(EntityKind.VERTEX, "")
    with pytest.raises(DomainError):
        EntityRef("vertex", "v0")


# ---------------------------------------------------------------- 派生寻址

OP = "split_e0"


def _split_setup(with_ranges: bool = True):
    """一条边被切成两段：e0 → [e1(左), e2(右)]，参数域 [0,1] 在 0.5 处分裂。"""
    table = EntityTable()
    parent = table.create(EntityKind.EDGE, "parent")
    left = table.create(EntityKind.EDGE, "left")
    right = table.create(EntityKind.EDGE, "right")
    ranges = [(0.0, 0.5), (0.5, 1.0)] if with_ranges else None
    mapping = RefMapping().split(parent, [left, right], op_id=OP, param_ranges=ranges)
    return table, parent, left, right, mapping


def test_split_does_not_tombstone_or_remap_parent():
    table, parent, _, _, mapping = _split_setup()
    assert mapping.map(parent) == parent
    current, payload = resolve(parent, table, mapping)
    assert current == parent and payload == "parent"


def test_split_lineage_resolves_by_index():
    table, parent, left, right, mapping = _split_setup()
    assert resolve_derived(DerivedRef.by_index(OP, parent, 0), table, mapping) == (left, "left")
    assert resolve_derived(DerivedRef.by_index(OP, parent, 1), table, mapping) == (right, "right")


def test_split_lineage_resolves_by_param_with_right_continuity():
    table, parent, left, right, mapping = _split_setup()
    # 段内
    assert resolve_derived(DerivedRef.by_param(OP, parent, 0.25), table, mapping)[0] == left
    assert resolve_derived(DerivedRef.by_param(OP, parent, 0.75), table, mapping)[0] == right
    # 右连续：恰好 0.5 属于右段；整段末端 1.0 归最后一段
    assert resolve_derived(DerivedRef.by_param(OP, parent, 0.5), table, mapping)[0] == right
    assert resolve_derived(DerivedRef.by_param(OP, parent, 1.0), table, mapping)[0] == right


def test_param_selector_without_ranges_is_rejected():
    table, parent, left, _, mapping = _split_setup(with_ranges=False)
    with pytest.raises(RefResolutionError, match="未记录 param_ranges"):
        resolve_derived(DerivedRef.by_param(OP, parent, 0.25), table, mapping)
    # 没有区间记录时，序号选择仍然可用（谱系本身存在）
    assert resolve_derived(DerivedRef.by_index(OP, parent, 0), table, mapping)[0] == left


def test_param_outside_domain_or_gap_is_rejected():
    table, parent, _, _, mapping = _split_setup()
    with pytest.raises(RefResolutionError, match="不落在"):
        resolve_derived(DerivedRef.by_param(OP, parent, 1.5), table, mapping)
    with pytest.raises(RefResolutionError, match="不落在"):
        resolve_derived(DerivedRef.by_param(OP, parent, -0.1), table, mapping)
    gap_table = EntityTable()
    gap_parent = gap_table.create(EntityKind.EDGE, "p")
    a = gap_table.create(EntityKind.EDGE, "a")
    b = gap_table.create(EntityKind.EDGE, "b")
    gap_mapping = RefMapping().split(
        gap_parent, [a, b], op_id="split_gap", param_ranges=[(0.0, 0.4), (0.6, 1.0)]
    )
    with pytest.raises(RefResolutionError, match="不落在"):
        resolve_derived(DerivedRef.by_param("split_gap", gap_parent, 0.5), gap_table, gap_mapping)


def test_derived_index_out_of_range_is_explicit():
    table, parent, _, _, mapping = _split_setup()
    with pytest.raises(RefResolutionError, match="第 2 段"):
        resolve_derived(DerivedRef.by_index(OP, parent, 2), table, mapping)


def test_unknown_lineage_is_explicit():
    table, parent, _, _, mapping = _split_setup()
    with pytest.raises(RefResolutionError, match="没有 .* 的分裂谱系"):
        resolve_derived(DerivedRef.by_index("other_op", parent, 0), table, mapping)


def test_nested_split_lineage():
    table, parent, left, right, mapping = _split_setup()
    sub_left = table.create(EntityKind.EDGE, "sub_left")
    sub_right = table.create(EntityKind.EDGE, "sub_right")
    mapping.split(left, [sub_left, sub_right], op_id="split_left", param_ranges=[(0.0, 0.25), (0.25, 0.5)])
    assert resolve_derived(DerivedRef.by_index(OP, parent, 0), table, mapping)[0] == left
    assert resolve_derived(
        DerivedRef.by_param("split_left", left, 0.25), table, mapping
    )[0] == sub_right


def test_split_validates_children_and_ranges():
    table = EntityTable()
    parent = table.create(EntityKind.EDGE, "parent")
    face = table.create(EntityKind.FACE, "f")
    child = table.create(EntityKind.EDGE, "child")
    with pytest.raises(DomainError, match="至少需要一个子实体"):
        RefMapping().split(parent, [], op_id=OP)
    with pytest.raises(DomainError, match="类型不一致"):
        RefMapping().split(parent, [child, face], op_id=OP)
    with pytest.raises(DomainError, match="复用父实体"):
        RefMapping().split(parent, [parent], op_id=OP)
    with pytest.raises(DomainError, match="互不相同"):
        RefMapping().split(parent, [child, child], op_id=OP)
    with pytest.raises(DomainError, match="数量"):
        RefMapping().split(parent, [child], op_id=OP, param_ranges=[(0.0, 1.0), (1.0, 2.0)])
    with pytest.raises(DomainError, match="互不重叠"):
        other = table.create(EntityKind.EDGE, "other")
        RefMapping().split(
            parent, [child, other], op_id=OP, param_ranges=[(0.0, 0.6), (0.5, 1.0)]
        )
    with pytest.raises(DomainError, match="必须递增"):
        other = table.create(EntityKind.EDGE, "other")
        RefMapping().split(parent, [child, other], op_id=OP, param_ranges=[(1.0, 0.0), (0.5, 1.0)])
    with pytest.raises(DomainError, match="已记录过"):
        mapping = RefMapping().split(parent, [child], op_id=OP)
        mapping.split(parent, [child], op_id=OP)
    with pytest.raises(DomainError, match="tombstone"):
        RefMapping().tombstone(parent).split(parent, [child], op_id=OP)


def test_merge_records_lineage_and_remaps_sources():
    table = EntityTable()
    a = table.create(EntityKind.EDGE, "a")
    b = table.create(EntityKind.EDGE, "b")
    merged = table.create(EntityKind.EDGE, "merged")
    mapping = RefMapping().merge([a, b], merged, op_id="merge_ab")
    assert resolve(a, table, mapping)[0] == merged
    assert resolve(b, table, mapping)[0] == merged
    blob = mapping.to_dict()
    assert blob["merges"] == [
        {
            "op_id": "merge_ab",
            "sources": [a.to_dict(), b.to_dict()],
            "merged": merged.to_dict(),
        }
    ]


def test_merge_conflicts_are_rejected():
    table = EntityTable()
    a = table.create(EntityKind.EDGE, "a")
    b = table.create(EntityKind.EDGE, "b")
    merged = table.create(EntityKind.EDGE, "merged")
    other = table.create(EntityKind.EDGE, "other")
    face = table.create(EntityKind.FACE, "f")
    with pytest.raises(DomainError, match="至少需要一个源实体"):
        RefMapping().merge([], merged, op_id="m")
    with pytest.raises(DomainError, match="类型不一致"):
        RefMapping().merge([face], merged, op_id="m")
    with pytest.raises(DomainError, match="同 id"):
        RefMapping().merge([merged], merged, op_id="m")
    with pytest.raises(DomainError, match="已有重编号目标"):
        RefMapping().remap(a, other).merge([a], merged, op_id="m")
    with pytest.raises(DomainError, match="tombstone"):
        RefMapping().tombstone(a).merge([a], merged, op_id="m")
    with pytest.raises(DomainError, match="已记录过"):
        RefMapping().merge([a, b], merged, op_id="m").merge([a, b], merged, op_id="m")


def test_lineage_report_is_deterministic_and_serializable():
    table = EntityTable()
    parent = table.create(EntityKind.EDGE, "parent")
    left = table.create(EntityKind.EDGE, "left")
    right = table.create(EntityKind.EDGE, "right")
    ranges = [(0.0, 0.5), (0.5, 1.0)]

    def build():
        return RefMapping().split(parent, [left, right], op_id=OP, param_ranges=ranges)

    first, second = build().to_dict(), build().to_dict()
    assert first == second
    assert first["derivations"][0]["param_ranges"] == [[0.0, 0.5], [0.5, 1.0]]
    assert first["derivations"][0]["parts"] == [left.to_dict(), right.to_dict()]

    derived = DerivedRef.by_param(OP, parent, 1)  # int 归一化为 float
    assert derived.selector == ("param", 1.0)
    assert DerivedRef.from_dict(derived.to_dict()) == derived


def test_derived_ref_validation():
    source = EntityRef(EntityKind.EDGE, "e0")
    with pytest.raises(DomainError):
        DerivedRef(op_id="", source=source)
    with pytest.raises(DomainError):
        DerivedRef(op_id=OP, source=source, _selector=("bogus", 0))
    with pytest.raises(DomainError):
        DerivedRef(op_id=OP, source=source, _selector=("index", -1))
    with pytest.raises(DomainError):
        DerivedRef(op_id=OP, source=source, _selector=("index", True))
    with pytest.raises(DomainError):
        DerivedRef.by_param(OP, source, math.nan)
    with pytest.raises(DomainError):
        DerivedRef(op_id=OP, source="e0")  # type: ignore[arg-type]
