"""EntityRef 实体引用契约：指针式实体引用 + 重编号 + tombstone（规格先行层）。

为什么需要（Pointer-CAD 文档 §4.2 的核心结论）
---------------------------------------------
命令序列表示的天花板是「实体不可引用」：不能选边就没有倒角，不能选面就没有拉伸。
而一旦内核开始做布尔/修复/简化，**实体编号会变**——如果引用规则不先定死，每个后续
算子都会发明自己的方案，到 P2 布尔时全部作废。

本模块只实现契约的**数据结构与规则**，不实现拓扑变异：

1. 实体类型：``VERTEX`` / ``EDGE`` / ``FACE``（3D）与 ``POINT`` / ``CURVE``（2D）；
2. id 确定性：按类型前缀 + 单调计数（``v0``、``e3``、``f1``…），同一脚本重放得到同一
   id 序列（``EntityTable.snapshot()`` 可逐位比较）；
3. 持久性规则：未被直接变异的实体 id 不变；变异产生的替代实体取新 id；
   被删除实体进 tombstone，后续引用一律 ``TombstoneError``（**不静默指向别处**）；
4. 解析语义：``resolve`` 先应用 ``RefMapping`` 再在当前模型里校验存在性与类型；
   ``select_nearest`` 按容差选最近的候选，平局即 ``DomainError``（不猜）；
5. 派生寻址（1-to-N / N-to-1 谱系）：``RefMapping.split`` 记录"一条实体被切成哪几段"，
   ``DerivedRef`` 用 ``(op_id, source, 局部选择子)`` 指向其中一段——按序号或按参数区间
   （右连续口径：分段起点属于本段，末端点归最后一段）。``RefMapping.merge`` 记录 N-to-1
   合并并把各源实体显式重编号到合并结果；谱系只记录事实，**不做拓扑变异**。

验收线（docs/specs/entity-ref-contract.md）
------------------------------------------
- 同一脚本重放两遍，``snapshot()`` 完全一致；
- tombstone 引用必须 ``TombstoneError``；
- 类型不匹配的引用必须 ``RefResolutionError``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from primitives.bspline import DomainError
from primitives.tolerance import ToleranceContext

__all__ = [
    "EntityKind",
    "EntityRef",
    "DerivedRef",
    "Entity",
    "EntityTable",
    "RefMapping",
    "RefResolutionError",
    "TombstoneError",
    "resolve",
    "resolve_derived",
    "select_nearest",
]


class RefResolutionError(DomainError):
    """引用无法解析（实体不存在、类型不匹配）。"""


class TombstoneError(RefResolutionError):
    """引用了已被删除（tombstone）的实体：拒绝猜测它「现在指的是谁」。"""


class EntityKind(str, Enum):
    VERTEX = "vertex"
    EDGE = "edge"
    FACE = "face"
    POINT = "point"
    CURVE = "curve"

    @property
    def prefix(self) -> str:
        return {
            EntityKind.VERTEX: "v",
            EntityKind.EDGE: "e",
            EntityKind.FACE: "f",
            EntityKind.POINT: "p",
            EntityKind.CURVE: "c",
        }[self]


@dataclass(frozen=True, order=True)
class EntityRef:
    """对某个几何实体的稳定引用（可哈希、可比较、可序列化）。"""

    kind: EntityKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EntityKind):
            raise DomainError(f"kind 必须是 EntityKind，收到 {self.kind!r}")
        if not isinstance(self.id, str) or not self.id:
            raise DomainError(f"实体 id 必须是非空字符串，收到 {self.id!r}")

    def require_kind(self, kind: EntityKind) -> "EntityRef":
        if self.kind is not kind:
            raise RefResolutionError(f"引用 {self.id} 是 {self.kind.value}，期望 {kind.value}")
        return self

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "id": self.id}

    @classmethod
    def from_dict(cls, blob: dict) -> "EntityRef":
        return cls(kind=EntityKind(blob["kind"]), id=blob["id"])


@dataclass(frozen=True)
class DerivedRef:
    """派生引用：指向一次 1-to-N 操作产出的「第 i 段」或「参数 u 所在的那一段」。

    ``EntityRef`` 回答"哪个实体"；``DerivedRef`` 回答"实体被切开后，是哪一段"。
    它只携带 ``(op_id, source, selector)``，不含几何数据：解析时由 ``RefMapping`` 的
    谱系记录把选择子变成具体子实体，再由 ``EntityTable`` 校验存在性。这样 Boolean 裁剪
    与 Boehm 分裂之后，脚本里对原实体"某一段"的引用不会变成悬空 tombstone。

    选择子两种口径：

    - ``("index", i)``：按 ``split`` 时给出的子实体顺序取第 ``i`` 段（确定性、与参数无关）；
    - ``("param", u)``：按参数域取含有 ``u`` 的那一段，需要 ``split`` 同时记录
      ``param_ranges``。口径是**右连续**（与基函数/曲线求值一致）：``u`` 恰为分段
      起点时属于该段，``u`` 等于整段末端点时归最后一段。
    """

    op_id: str
    source: EntityRef
    _selector: Tuple[str, Union[int, float]] = ("index", 0)

    def __post_init__(self) -> None:
        if not isinstance(self.source, EntityRef):
            raise DomainError(f"DerivedRef.source 必须是 EntityRef，收到 {self.source!r}")
        if not isinstance(self.op_id, str) or not self.op_id:
            raise DomainError(f"DerivedRef.op_id 必须是非空字符串，收到 {self.op_id!r}")
        selector = self._selector
        if not isinstance(selector, tuple) or len(selector) != 2:
            raise DomainError(f"selector 必须是 (kind, value) 二元组，收到 {selector!r}")
        kind, value = selector
        if kind == "index":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DomainError(f"index 选择子必须是非负整数，收到 {value!r}")
            return
        if kind == "param":
            if isinstance(value, bool):
                raise DomainError(f"param 选择子必须是有限实数，收到 {value!r}")
            try:
                u = float(value)
            except (TypeError, ValueError) as exc:
                raise DomainError(f"param 选择子必须是有限实数，收到 {value!r}") from exc
            if not math.isfinite(u):
                raise DomainError(f"param 选择子必须是有限实数，收到 {value!r}")
            object.__setattr__(self, "_selector", ("param", u))
            return
        raise DomainError(f"selector.kind 只能是 'index' 或 'param'，收到 {kind!r}")

    # ---- 构造 ---------------------------------------------------------
    @classmethod
    def by_index(cls, op_id: str, source: EntityRef, index: int) -> "DerivedRef":
        return cls(op_id=op_id, source=source, _selector=("index", index))

    @classmethod
    def by_param(cls, op_id: str, source: EntityRef, u: float) -> "DerivedRef":
        return cls(op_id=op_id, source=source, _selector=("param", u))

    # ---- 访问 ---------------------------------------------------------
    @property
    def selector(self) -> Tuple[str, Union[int, float]]:
        return self._selector

    @property
    def kind(self) -> EntityKind:
        return self.source.kind

    def to_dict(self) -> dict:
        return {
            "op_id": self.op_id,
            "source": self.source.to_dict(),
            "selector": {"kind": self._selector[0], "value": self._selector[1]},
        }

    @classmethod
    def from_dict(cls, blob: dict) -> "DerivedRef":
        selector = blob["selector"]
        return cls(
            op_id=blob["op_id"],
            source=EntityRef.from_dict(blob["source"]),
            _selector=(selector["kind"], selector["value"]),
        )


@dataclass(frozen=True)
class Entity:
    """实体表里的一条记录；payload 是内核层的不透明句柄（本层不解释它）。"""

    kind: EntityKind
    id: str
    payload: object = None


class EntityTable:
    """模型实体表：确定性 id 分配 + 快照（重放不变量用）。

    作用域：一张表对应一个模型状态。跨状态的重编号由 ``RefMapping`` 表达。
    """

    def __init__(self) -> None:
        self._entities: Dict[str, Entity] = {}
        self._counters: Dict[EntityKind, int] = {kind: 0 for kind in EntityKind}
        self._creation_order: List[EntityRef] = []

    # ---- 分配/访问 ----------------------------------------------------
    def create(self, kind: EntityKind, payload: object = None) -> EntityRef:
        if not isinstance(kind, EntityKind):
            raise DomainError(f"kind 必须是 EntityKind，收到 {kind!r}")
        index = self._counters[kind]
        self._counters[kind] = index + 1
        ref = EntityRef(kind, f"{kind.prefix}{index}")
        self._entities[ref.id] = Entity(kind, ref.id, payload)
        self._creation_order.append(ref)
        return ref

    def get(self, ref: EntityRef) -> object:
        entity = self._entities.get(ref.id)
        if entity is None:
            raise RefResolutionError(f"引用 {ref.id} 不在当前模型中")
        if entity.kind is not ref.kind:
            raise RefResolutionError(
                f"引用 {ref.id} 的类型是 {entity.kind.value}，与引用声明 {ref.kind.value} 不符"
            )
        return entity.payload

    def contains(self, ref: EntityRef) -> bool:
        return ref.id in self._entities

    def refs(self, kind: Optional[EntityKind] = None) -> Tuple[EntityRef, ...]:
        if kind is None:
            return tuple(self._creation_order)
        return tuple(r for r in self._creation_order if r.kind is kind)

    def __len__(self) -> int:
        return len(self._entities)

    def snapshot(self) -> Tuple[Tuple[str, str], ...]:
        """(kind, id) 序列：同一脚本重放两遍必须逐位相同。"""
        return tuple((r.kind.value, r.id) for r in self._creation_order)


@dataclass(frozen=True)
class _Split:
    """一条 1-to-N 谱系记录：``op_id`` 把 ``source`` 切成了 ``parts``。"""

    op_id: str
    source: EntityRef
    parts: Tuple[EntityRef, ...]
    param_ranges: Optional[Tuple[Tuple[float, float], ...]]


@dataclass(frozen=True)
class _Merge:
    """一条 N-to-1 谱系记录：``op_id`` 把 ``sources`` 合并成了 ``merged``。"""

    op_id: str
    sources: Tuple[EntityRef, ...]
    merged: EntityRef


@dataclass
class RefMapping:
    """一次操作后的重编号报告：旧 id → 新引用 / tombstone / 谱系。

    规则（Pointer-CAD 文档 §4.2）：
    - 未变异的实体可以显式映射到自身（也可缺省，``resolve`` 视为恒等）；
    - 被删除的实体进 tombstone，后续引用抛 ``TombstoneError``；
    - 替代实体的类型必须与旧实体一致，否则 ``DomainError``；
    - 1-to-N（分裂/裁剪）与 N-to-1（合并）用 ``split`` / ``merge`` 记录谱系，
      供 ``resolve_derived`` 做确定性的局部寻址。
    """

    _mapped: Dict[str, EntityRef] = field(default_factory=dict)
    _tombstones: Dict[str, EntityRef] = field(default_factory=dict)
    _derivations: Dict[Tuple[str, str], "_Split"] = field(default_factory=dict)
    _merges: List["_Merge"] = field(default_factory=list)

    def remap(self, old: EntityRef, new: EntityRef) -> "RefMapping":
        if old.kind is not new.kind:
            raise DomainError(
                f"重编号类型不一致：{old.id}({old.kind.value}) → {new.id}({new.kind.value})"
            )
        if old.id in self._tombstones:
            raise DomainError(f"{old.id} 已被标记为 tombstone，不能再重编号")
        self._mapped[old.id] = new
        return self

    def tombstone(self, old: EntityRef) -> "RefMapping":
        if old.id in self._mapped:
            raise DomainError(f"{old.id} 已有重编号目标，不能再标记 tombstone")
        self._tombstones[old.id] = old
        return self

    def map(self, ref: EntityRef) -> EntityRef:
        """把旧引用映射到当前状态；tombstone → ``TombstoneError``。

        未出现在映射里的 id 视为恒等（未被操作触及的实体 id 不变）。
        """
        if ref.id in self._tombstones:
            raise TombstoneError(f"引用 {ref.id} 已被删除（tombstone），拒绝重解析")
        target = self._mapped.get(ref.id)
        if target is None:
            return ref
        if target.kind is not ref.kind:
            raise RefResolutionError(
                f"重编号映射把 {ref.kind.value} 映成了 {target.kind.value}：拒绝"
            )
        return target

    # ---- 1-to-N / N-to-1 谱系 -----------------------------------------
    def split(
        self,
        old: EntityRef,
        parts: Sequence[EntityRef],
        *,
        op_id: str,
        param_ranges: Optional[Sequence[Tuple[float, float]]] = None,
    ) -> "RefMapping":
        """记录 1-to-N：``old`` 被 ``op_id`` 切成 ``parts``（顺序即局部序号）。

        规则：

        - **不自动重编号** ``old``：直接引用 ``old`` 仍由 ``map`` 决定（未记录则恒等）；
          "第几段/哪一段"必须用 ``DerivedRef`` + ``resolve_derived`` 显式寻址；
        - 子实体取新 id、类型与父实体一致、id 互不相同且不得复用父 id；
        - ``param_ranges`` 可选，与 ``parts`` 一一对应、按参数递增、互不重叠；
          记录后 ``DerivedRef.by_param`` 才能解析（右连续口径）。
        """
        if not isinstance(old, EntityRef):
            raise DomainError(f"split 的 old 必须是 EntityRef，收到 {old!r}")
        if not isinstance(op_id, str) or not op_id:
            raise DomainError(f"split 的 op_id 必须是非空字符串，收到 {op_id!r}")
        children = tuple(parts)
        if not children:
            raise DomainError("split 至少需要一个子实体")
        for child in children:
            if not isinstance(child, EntityRef):
                raise DomainError(f"split 的子实体必须是 EntityRef，收到 {child!r}")
            if child.kind is not old.kind:
                raise DomainError(
                    f"split 类型不一致：{old.id}({old.kind.value}) 的子实体 "
                    f"{child.id}({child.kind.value})"
                )
            if child.id == old.id:
                raise DomainError(f"子实体不得复用父实体 id {old.id!r}")
        if len({child.id for child in children}) != len(children):
            raise DomainError("split 的子实体 id 必须互不相同")
        if old.id in self._tombstones:
            raise DomainError(f"{old.id} 已被标记为 tombstone，不能再记录分裂谱系")
        key = (op_id, old.id)
        if key in self._derivations:
            raise DomainError(f"{op_id} 已记录过 {old.id} 的分裂谱系")
        ranges = (
            self._validate_param_ranges(param_ranges, len(children))
            if param_ranges is not None
            else None
        )
        self._derivations[key] = _Split(
            op_id=op_id, source=old, parts=children, param_ranges=ranges
        )
        return self

    def merge(
        self,
        sources: Sequence[EntityRef],
        merged: EntityRef,
        *,
        op_id: str,
    ) -> "RefMapping":
        """记录 N-to-1：``op_id`` 把 ``sources`` 合并成 ``merged``，并把各源重编号到它。

        与 ``split`` 不同，合并后的源实体确实"变成"了 ``merged``（共线边合并、碎片消解），
        因此这里直接写 ``_mapped``：旧引用解析到 ``merged`` 而不是悬空。谱系单独保留，
        供审计与反向查询（哪个合并操作吞掉了哪几条边）。
        """
        if not isinstance(merged, EntityRef):
            raise DomainError(f"merge 的 merged 必须是 EntityRef，收到 {merged!r}")
        if not isinstance(op_id, str) or not op_id:
            raise DomainError(f"merge 的 op_id 必须是非空字符串，收到 {op_id!r}")
        srcs = tuple(sources)
        if not srcs:
            raise DomainError("merge 至少需要一个源实体")
        for src in srcs:
            if not isinstance(src, EntityRef):
                raise DomainError(f"merge 的源实体必须是 EntityRef，收到 {src!r}")
            if src.kind is not merged.kind:
                raise DomainError(
                    f"merge 类型不一致：{src.id}({src.kind.value}) → "
                    f"{merged.id}({merged.kind.value})"
                )
            if src.id == merged.id:
                raise DomainError(f"合并结果 {merged.id} 不得与源实体同 id")
            if src.id in self._tombstones:
                raise DomainError(f"{src.id} 已被标记为 tombstone，不能再并入 {merged.id}")
            existing = self._mapped.get(src.id)
            if existing is not None and existing != merged:
                raise DomainError(f"{src.id} 已有重编号目标 {existing.id}，不能再并入 {merged.id}")
        if len({src.id for src in srcs}) != len(srcs):
            raise DomainError("merge 的源实体 id 必须互不相同")
        if any(
            record.op_id == op_id and record.sources == srcs and record.merged == merged
            for record in self._merges
        ):
            raise DomainError(f"{op_id} 已记录过同一组合并谱系")
        self._merges.append(_Merge(op_id=op_id, sources=srcs, merged=merged))
        for src in srcs:
            self._mapped[src.id] = merged
        return self

    @staticmethod
    def _validate_param_ranges(
        param_ranges: Sequence[Tuple[float, float]], expected: int
    ) -> Tuple[Tuple[float, float], ...]:
        ranges: List[Tuple[float, float]] = []
        for item in param_ranges:
            try:
                lo, hi = (float(value) for value in item)
            except (TypeError, ValueError) as exc:
                raise DomainError(f"param_ranges 必须是 (lo, hi) 二元组序列，收到 {item!r}") from exc
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise DomainError(f"param_ranges 必须是有限数，收到 {(lo, hi)!r}")
            if not hi > lo:
                raise DomainError(f"param_ranges 必须递增：{lo!r} !< {hi!r}")
            if ranges and lo < ranges[-1][1]:
                raise DomainError(f"param_ranges 互不重叠且递增：{ranges[-1]!r} 与 {(lo, hi)!r}")
            ranges.append((lo, hi))
        if len(ranges) != expected:
            raise DomainError(
                f"param_ranges 数量 {len(ranges)} 与子实体数量 {expected} 不一致"
            )
        return tuple(ranges)

    def _lookup_split(self, derived: "DerivedRef") -> _Split:
        key = (derived.op_id, derived.source.id)
        split = self._derivations.get(key)
        if split is None:
            raise RefResolutionError(
                f"没有 {derived.op_id} 对 {derived.source.id} 的分裂谱系："
                f"派生引用无法解析（先调用 RefMapping.split 记录）"
            )
        return split

    def to_dict(self) -> dict:
        return {
            "mapped": {old: new.to_dict() for old, new in sorted(self._mapped.items())},
            "tombstones": sorted(self._tombstones),
            "derivations": [
                {
                    "op_id": split.op_id,
                    "source": split.source.to_dict(),
                    "parts": [part.to_dict() for part in split.parts],
                    "param_ranges": (
                        [list(rng) for rng in split.param_ranges]
                        if split.param_ranges is not None
                        else None
                    ),
                }
                for _, split in sorted(self._derivations.items())
            ],
            "merges": [
                {
                    "op_id": record.op_id,
                    "sources": [src.to_dict() for src in record.sources],
                    "merged": record.merged.to_dict(),
                }
                for record in sorted(
                    self._merges, key=lambda rec: (rec.op_id, tuple(src.id for src in rec.sources))
                )
            ],
        }


def resolve(
    ref: EntityRef, table: EntityTable, mapping: Optional[RefMapping] = None
) -> Tuple[EntityRef, object]:
    """解析引用：先应用重编号，再在当前模型里校验存在性与类型。返回 (当前引用, payload)。"""
    current = mapping.map(ref) if mapping is not None else ref
    payload = table.get(current)
    return current, payload


def resolve_derived(
    derived: DerivedRef, table: EntityTable, mapping: RefMapping
) -> Tuple[EntityRef, object]:
    """解析派生引用：按 ``(op_id, source)`` 找谱系，再用选择子定位具体子实体。

    - ``index`` 选择子：越界 → ``RefResolutionError``（不退化为"最后一段"）；
    - ``param`` 选择子：需谱系记录过 ``param_ranges``；按右连续口径取段，
      落在缝隙或参数域外 → ``RefResolutionError``（不猜最近段）；
    - 定位到的子实体仍要过 ``EntityTable.get``（存在性 + 类型校验）。
    """
    if not isinstance(derived, DerivedRef):
        raise DomainError(f"resolve_derived 需要 DerivedRef，收到 {derived!r}")
    if not isinstance(mapping, RefMapping):
        raise DomainError(f"resolve_derived 需要 RefMapping，收到 {mapping!r}")
    split = mapping._lookup_split(derived)
    kind, value = derived.selector
    if kind == "index":
        index = value
        if index >= len(split.parts):
            raise RefResolutionError(
                f"派生引用 {derived.op_id}/{derived.source.id} 的第 {index} 段不存在"
                f"（共 {len(split.parts)} 段）"
            )
        target = split.parts[index]
    else:
        target = _select_part_by_param(split, float(value), derived)
    return target, table.get(target)


def _select_part_by_param(split: _Split, u: float, derived: DerivedRef) -> EntityRef:
    """右连续口径按参数选段：``lo <= u < hi``；整段末端点归最后一段。"""
    ranges = split.param_ranges
    if ranges is None:
        raise RefResolutionError(
            f"派生引用 {derived.op_id}/{derived.source.id} 按参数选择，"
            f"但 split 未记录 param_ranges：拒绝猜"
        )
    for index, (lo, hi) in enumerate(ranges):
        if lo <= u < hi:
            return split.parts[index]
    last_lo, last_hi = ranges[-1]
    if u == last_hi:
        return split.parts[-1]
    raise RefResolutionError(
        f"参数 {u!r} 不落在 {derived.source.id} 的任何分段内"
        f"（域 [{ranges[0][0]!r}, {last_hi!r}]，含缝隙或越界）"
    )


def select_nearest(
    candidates: Sequence[EntityRef],
    distance: Callable[[EntityRef], float],
    tol: ToleranceContext,
) -> EntityRef:
    """从候选实体中选"特征最一致"的一个：距离最近；平局 → ``DomainError``。

    对应 Pointer-CAD 的 pointer 选择机制，但实现为确定性算法（LLM 不参与选择）。
    """
    if not candidates:
        raise RefResolutionError("候选实体集为空，无法选择")
    scored: List[Tuple[float, EntityRef]] = []
    for ref in candidates:
        d = float(distance(ref))
        if math.isnan(d):
            raise DomainError(f"候选 {ref.id} 的距离为 NaN")
        scored.append((d, ref))
    scored.sort(key=lambda pair: (pair[0], pair[1].id))
    best_d, best_ref = scored[0]
    if len(scored) > 1:
        second_d = scored[1][0]
        if second_d - best_d <= tol.tol(max(best_d, second_d)):
            raise DomainError(
                f"实体选择歧义：{best_ref.id} 与 {scored[1][1].id} 的距离差 "
                f"{second_d - best_d:.3e} 在容差内，拒绝猜"
            )
    return best_ref
