# EntityRef 实体引用契约 v0.2（含派生寻址，规格先行）

> 版本 0.2.1 | 2026-11-20 | 实现：`kernel/entity_ref.py` | 测试：`tests/test_entity_ref.py`
> 来源：`docs/plans/2026-09-16-pointer-cad-reference.md` §4.2（D1 决策）；
> `docs/adr/0003-entity-derivation-lineage.md`（v0.2 派生寻址）；
> `docs/adr/0004-determinism-vs-tnp.md`（确定性重放 ≠ TNP 的边界）；
> 硬约束：`docs/adr/0001-nurbs-first.md`（本层只定契约，不含拓扑变异）

---

## 1. 问题

命令序列表示的天花板是**实体不可引用**：不能选边就没有倒角，不能选面就没有拉伸（Pointer-CAD, CVPR 2026）。
一旦内核开始做布尔/修复/简化，实体编号会变——如果引用规则不在公共 API 定型前定死，
每个后续算子都会发明自己的方案，到 P2 布尔时全部作废。

本层解决四件事，且只解决这四件事：

1. 实体如何被**稳定引用**（类型 + 确定性 id）；
2. 变异之后引用**如何重编号**（`RefMapping`）；
3. 失效引用**如何被显式拒绝**（tombstone → `TombstoneError`）；
4. 实体被**切开/合并**之后，脚本如何引用"其中一段"（`DerivedRef` + `split`/`merge` 谱系，
   v0.2 新增）。

**不做**：不实现任何拓扑变异；不实现布尔重编号算法；不实现 Tier 5 过程化重放 runner。

## 2. 实体类型与 id

| 维度 | 类型 | 前缀 | 说明 |
|:--|:--|:--|:--|
| 3D | `VERTEX` / `EDGE` / `FACE` | `v` / `e` / `f` | B-Rep 顶点/边/面 |
| 2D | `POINT` / `CURVE` | `p` / `c` | 草图点/曲线 |

- id 格式：`<前缀><单调计数>`，例如 `v0`、`e3`、`f1`；
- 分配按类型独立计数，顺序由**创建顺序**决定；
- 同一脚本重放两遍，`EntityTable.snapshot()` 必须逐位相同（`tests/test_entity_ref.py::test_replay_invariance`）。

## 3. 持久性契约

| 情形 | 规则 |
|:--|:--|
| 实体未被直接变异 | id 保持不变（`RefMapping` 中可不出现，`resolve` 视为恒等） |
| 实体被替代（1-to-1，如裁剪） | 子实体取**新 id**；旧 id 通过 `remap` 指向替代实体或进 tombstone |
| 实体被分裂（1-to-N，如 Boehm 分裂/求交切边） | 子实体取**新 id**；谱系由 `split` 记录；旧 id **不自动**重编号，局部引用走 `DerivedRef` |
| 实体被合并（N-to-1，如共线边合并） | 各源实体显式重编号到合并结果（`merge` 自动写 `remap`），谱系保留 |
| 实体被删除 | id 进 tombstone；后续任何解析抛 `TombstoneError`，**绝不静默指向别处** |
| 类型不匹配 | `RefResolutionError`（例如拿 edge 引用去查 face 表） |

`RefMapping` 的写入规则也由契约强制：

- 同一个旧 id 不能既重编号又 tombstone（`DomainError`）；
- 重编号的目标类型必须与旧实体一致（`DomainError`）；
- 已 tombstone 的 id 不能再重编号、不能再记录分裂或合并谱系（`DomainError`）；
- 分裂子实体：类型与父实体一致、id 互不相同、不得复用父 id（`DomainError`）；
- 合并源实体：不得已被重编号到别处、不得与合并结果同 id、同一操作不得重复记录（`DomainError`）。

## 4. 派生寻址（1-to-N / N-to-1）

`EntityRef` 回答"哪个实体"；`DerivedRef` 回答"被切开后是哪一段"：

```python
DerivedRef.by_index(op_id, source, i)   # 第 i 段（按 split 时的顺序）
DerivedRef.by_param(op_id, source, u)   # 参数 u 所在的那一段
current, payload = resolve_derived(derived, table, mapping)
```

规则：

- **谱系键**：`(op_id, source.id)`。同一操作不得对同一父实体重复记录（`DomainError`）；
- `split(old, parts, op_id=..., param_ranges=None)`：按给定顺序记录子实体；`param_ranges`
  可选，与 `parts` 一一对应、有限、递增、互不重叠；**不**自动重编号 `old`；
- `merge(sources, merged, op_id=...)`：记录谱系并**自动**把每个源 `remap` 到 `merged`
  （合并是"替代"，旧引用必须还能解析到结果）；
- **参数口径是右连续**（与基函数/曲线求值一致）：`u` 恰为分段起点时属于该段；
  `u` 等于整段末端点时归最后一段；
- 解析失败一律显式：序号越界、参数落在缝隙/域外、谱系不存在、`param_ranges` 未记录、
  子实体已不在当前表中——全部抛 `RefResolutionError`，不退化为"取最近一段"或 `None`。

`index` 与 `param` 是两种独立口径：只记了序号时 `param` 选择子必须报错（拒绝猜），
只记了区间时 `index` 选择子仍然可用（谱系顺序确定）。

## 5. 解析语义

```python
current, payload = resolve(ref, table, mapping)          # EntityRef：先映射，再校验存在性与类型
current, payload = resolve_derived(derived, table, mapping)  # DerivedRef：先查谱系，再校验
```

- `mapping=None` 表示无变异，直接在当前表里解析；
- 解析失败一律抛异常，不返回 `None`（静态检查器 SC001 同一条纪律）。

## 6. 选择语义（pointer）

```python
chosen = select_nearest(candidates, distance, tolerance)
```

- 取距离最近的候选；
- **平局**（次近与最近的距离差在容差内）→ `DomainError("实体选择歧义…")`；
- 候选为空 → `RefResolutionError`；
- 距离为 NaN → `DomainError`。

这对应 Pointer-CAD 的 pointer 选择，但实现为**确定性算法**：LLM 不参与选择。

## 7. 验收线

| 项 | 线 | 测试 |
|:--|:--|:--|
| 重放确定性 | 两遍 `snapshot()` 相同 | `test_replay_invariance` |
| tombstone 拒绝 | 必须 `TombstoneError` | `test_tombstone_reference_raises_and_cannot_be_remapped` |
| 类型安全 | 类型不符必须拒绝 | `test_get_returns_payload_and_checks_kind` |
| 选择歧义 | 平局必须 `DomainError` | `test_select_nearest_tie_is_explicit_error` |
| 映射报告 | `to_dict()` 可序列化、可逆 | `test_mapping_report_is_serializable` |
| 分裂谱系 | 序号/参数两种选择子均落到正确子实体 | `test_split_lineage_resolves_by_index` / `..._by_param_with_right_continuity` |
| 参数口径 | 分裂点归右段、末端归最后一段、缝隙/越界显式拒绝 | `test_param_outside_domain_or_gap_is_rejected` |
| 合并谱系 | 源实体解析到合并结果、谱系可序列化 | `test_merge_records_lineage_and_remaps_sources` |
| 谱系确定性 | 同一脚本两遍 `to_dict()` 相同 | `test_lineage_report_is_deterministic_and_serializable` |

## 8. 与参考实现的映射

| 本层 | OCCT（pythonocc-core） | manifold3d |
|:--|:--|:--|
| `EntityTable` | `TopoDS_Shape` + `TopTools_IndexedMapOfShape` | 无持久引用概念 |
| `RefMapping` | `BRepBuilderAPI_*` 的历史记录（`Modified`/`Generated`/`IsDeleted`） | 需先自建引用层，再按实体计数对拍 |
| `split` 谱系（1-to-N） | `Modified` 的多目标 + `Generated` | 需按顶点/边计数自建谱系 |
| `merge` 谱系（N-to-1） | `Modified` 的合并历史（多对一） | 同上 |
| tombstone | `BRepBuilderAPI_*` 的 `IsDeleted` | 无对应物 |

**结论**：3D B-Rep 阶段的重编号实现，优先封装 OCCT 的历史记录并以其为对拍基准；
manifold3d 只用于网格布尔的质量属性对拍，不承载引用语义。

## 9. 未实现（明确边界）

1. **拓扑变异本身**：`split`/`merge` 只记录谱系，不创建/删除拓扑；实际切边、合并
   走 ADR-0001 通道（规格先行 + 人工审查分步实现，或封装 OCCT）。
2. **自动选段**：不实现"取离某点最近的一段"这类启发式；局部寻址必须显式给出
   序号或参数，平局/缝隙一律报错。
3. **Tier 5 过程化重放 runner**：需要 P1 的 sketch/extrude 算子链；本契约提供其引用基础。
4. **`sketch.json` 指针脚本格式**：等 P1 草图实体落地后按本契约扩展。

## 10. 边界：确定性重放 ≠ 拓扑持久命名（TNP）

本契约的验收线（重放一致、tombstone、split/merge 谱系）证明的是**确定性重放与单步派生寻址**，
不是工业界所说的 TNP。两者差一整层：

| | 本契约已保证 | 工业界 TNP 要保证 |
|:--|:--|:--|
| 输入变化 | 同一脚本、同一顺序重跑 | 草图尺寸/特征增删后的参数化重生成 |
| 引用目标 | 同一创建序号的实体与单步派生关系 | 语义实体（"顶面右前边"），即使 id/参数/边数都变了 |
| 机制 | 单调计数 + `RefMapping` + `DerivedRef` | 特征历史锚点 + 邻接语义签名 + 候选重匹配 |

结论：`EntityTable` 的 `e0, e1, ...` 与 `DerivedRef` 的局部序号/参数**不是**持久命名。
参数化 TNP 列为独立阶段（ADR-0004），不在本契约内承诺；对外材料不得把确定性重放
表述为 TNP。

