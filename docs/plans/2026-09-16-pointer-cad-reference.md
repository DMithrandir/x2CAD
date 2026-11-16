# X2CAD × Pointer-CAD：指针式实体引用与过程化建模 — 项目优化文档

> 版本 0.1.0 | 2026-09-16 | 项目根 `C:\Users\desha\Desktop\CAD`
> 参考对象：Pointer-CAD（CVPR 2026，[arXiv:2603.04337](https://arxiv.org/abs/2603.04337)），项目页 <https://snitro.github.io/Pointer-CAD-Page/>
> 母文档：`docs/plans/2026-08-20-x2cad-kernel-design.md`；硬约束：ADR-0001
> 本文档定位：一份**跨阶段优化文档**——提出 schema / 引用层 / 验证台 / 算子路线四类优化，
> 不推翻母文档总纲。文中所有 `[待裁决]` 项须经用户拍板并转 ADR-0002 后方可落地。

---

## 1. 一句话结论

Pointer-CAD 对 X2CAD 最有价值的不是它的生成模型，而是它被迫解决的两个**表示层**问题：
**几何实体的可引用性**与**过程化步骤间的中间几何条件化**。这两个问题不是文本生成特有的，
任何「先画草图再拉伸再倒角」的过程化建模内核都必然撞上它们——X2CAD 从 P1（2D 垂直切片）
起就会撞上，而**现在**（N1 刚落地、B-Rep 尚未动工）是代价最低的设计窗口。

本文件把 Pointer-CAD 的经验翻译成 X2CAD 自己的四类优化：

1. **算子规格（OperatorSpec）增加实体引用参数**（§4.1）；
2. **内核预置 EntityRef 实体引用层与重编号契约**（§4.2）——这是本文档的核心建议；
3. **验证台增加 Tier 5 过程化重放**（§4.4）；
4. **fillet / chamfer 以「指针算子」形式规格先行**（§4.5）。

---

## 2. Pointer-CAD 概要

### 2.1 论文要点

| 维度 | 内容 |
|:--|:--|
| 问题 | LLM 生成 CAD 时以**命令序列**表示模型：无法直接引用面/边等几何实体 → 无法表达倒角/圆角等复杂编辑；草图与拉伸中连续量被离散化 → 引入**量化导致的拓扑错误** |
| 表示 | **指针式命令序列**：命令不仅含参数，还含**指向 B-rep 实体的指针**（边/面），显式建模几何关系 |
| 生成 | 逐步（step-wise）生成：每步只预测一个基本操作（Sketch / Extrude / Chamfer / Fillet），且每一步都以「文本描述 + 上一步产出的中间 B-rep」为条件 |
| 选择机制 | 需要选实体时，LLM 预测一个 Pointer，从候选集中选出「特征最一致」的那个实体；选择本身也降低了量化误差 |
| 数据 | 自研标注管线产出专家级自然语言描述，构建约 575K 个 CAD 模型的数据集 |
| 结果 | 显著优于既有命令序列方法，分割/拓扑错误降到极低水平，能生成含倒角圆角的复杂结构 |

### 2.2 框架三组件

| 组件 | 职责 | X2CAD 对应物 |
|:--|:--|:--|
| Multimodal Fusion Module | 文本 + 当前 B-rep → 统一表示 | **不需要**（见 §2.3 与 ADR-0001） |
| LLM | 基于融合表示预测本步操作命令 | x2cad 流水线中的 ref2spec / spec2op（只写规格与受控代码，不做几何计算） |
| Vector Translation Module | 命令序列 → 更新后的 B-rep，作为下一步输入 | **确定性算子**（operators/ + primitives/），这正是 ADR-0001 划定的领域 |

### 2.3 对 X2CAD 成立的三条结论

1. **序列表示的真正天花板是「实体不可引用」**。倒角/圆角在纯参数命令表示下是不可表达操作——不是模型不够强，是表示不允许。→ X2CAD 的算子签名必须原生支持实体引用，否则 P2 之后每加一个编辑类算子都要返工。
2. **离散化误差 = 拓扑错误的温床**。连续坐标被量化后，本应重合/相切的点线面失配，产生自交、缝隙、错误邻接。→ 这正是 X2CAD 退化知识库 N 族（数值抵消）与鲁棒性平面（相对位错扰动）要治的病；Pointer-CAD 提供了独立的外部证据。
3. **逐步条件化 + 「选最一致候选」是可行解**。每步吃上一步的真实几何，比一次性生成整段序列稳定得多。→ X2CAD 的验证台应当有「跨算子链」的证据层：算子在上游算子真实输出上被验证，而不只是合成输入上。

**明确不采纳**（非目标）：text-to-CAD 生成模型本身、575K 数据集标注管线、多模态融合模块、任何「LLM 直接做几何」的用法。LLM 在 X2CAD 中的角色维持 ADR-0001 的边界不变。

---

## 3. 可迁移教训映射（五条）

| # | Pointer-CAD 教训 | X2CAD 现状缺口 | 优化动作 |
|:--|:--|:--|:--|
| L1 | **实体指针引用**：命令直接指向边/面，而非坐标值 | 现有三个算子的输入只有数值/数组（knots、控制点、权重），没有任何「引用既有实体」的类型；spec schema 无 references 字段 | §4.1 schema 扩展 + §4.2 EntityRef 层 |
| L2 | **中间几何条件化**：每步以上一步的 B-rep 为输入 | 验证只吃合成输入；没有「算子链」端到端证据，也没有引用有效性检查 | §4.4 Tier 5 过程化重放 |
| L3 | **吸附（snap）与量化误差**：选实体而非重发坐标，消除离散化误差 | `ToleranceContext` 只有比较语义，没有「把点吸附到既有实体并返回引用」的语义 | §4.6 snap 语义 |
| L4 | **实体选择是命令的一部分**：Pointer 从候选集中选「特征最一致」者 | spec L1（签名与域）没有实体选择语义的提取环节 | §4.1 + §4.7 ref2spec 扩展 |
| L5 | **分层评估协议**：basic ops（Sketch & Extrude）与 complex ops（Fillet & Chamfer）分开报告 | 鲁棒性平面按用例族扫描，但不按操作族分层，无法回答「复杂编辑类算子的鲁棒性是否达标」 | §4.8 分层报告 |

---

## 4. 优化方案

### 4.1 OperatorSpec schema v0.2：新增 `references` 字段

在 spec 五层提取的 L1（签名与域）产出中，输入除数值参数外允许声明**实体引用参数**：

```json
{
  "slug": "fillet_3d",
  "signature": {
    "inputs": {
      "radius": "float > 0",
      "edges": {
        "kind": "edge",
        "count": ">=1",
        "selection": "unique",
        "tolerance_binding": "ToleranceContext.snap"
      }
    },
    "references": ["edges"]
  }
}
```

规则（由 `verify/static_check.py` 增量校验）：

- 引用参数必须声明 `kind`（2D：`point`/`curve`；3D：`vertex`/`edge`/`face`）与 `selection` 语义（`unique` / `nearest` / `all`）；
- 引用必须在**输入几何体**中可解析；解析发生在 execute 入口（不是调用方），解析失败一律 `DomainError`；
- 任何「选实体」类算子（fillet/chamfer/snap/…）禁止裸坐标选择——必须走引用参数；
- schema 版本号进 `spec.json`（`"schema_version": "0.2"`），旧算子原地兼容（无 references 即纯参数算子）。

### 4.2 `kernel/` EntityRef 实体引用层（规格先行，本文档核心建议）

> 性质声明：本层是**数据结构 + 引用规则规格**，不是拓扑结构变异代码。布尔重编号等变异逻辑仍走
> ADR-0001 通道（规格先行 + 人工审查 / 封装参考实现）。现在只写契约，不写变异实现。

**问题**：若不在内核公共 API 定型前定死「实体如何被引用、被变异后引用何去何从」，每个后续算子
都会发明自己的引用方案，到 P2 布尔时全部作废。

**契约草案**：

1. **实体类型**：`VertexRef` / `EdgeRef` / `FaceRef`（2D 为 `PointRef` / `CurveRef`），每个实体带全局唯一、跨操作稳定的 `id`（如 `e17`、`f3`），id 生成确定性（同一脚本重放得到同一 id 序列）。
2. **持久性规则（引用稳定性契约）**：
   - 未被直接变异的实体：id 保持不变；
   - 变异产生的替代实体（如求交分裂一条边为两条）：子实体取新 id；
   - 被删除实体：id 进入 tombstone，同一脚本内后续引用报 `DomainError`（不静默指向别处）。
3. **解析语义**：`resolve(ref, geometry, tol)` 按 `selection` 语义解析（`unique` / `nearest` / `all`），带容差绑定——这直接对应 Pointer-CAD 的「从候选集选特征最一致的实体」，但实现为确定性算法。
4. **重编号报告**：每个算子执行后输出 `ref_mapping.json`（旧 id → 新 id / tombstone），验证台据此做引用有效性检查。
5. **参考实现映射**：OCCT 侧映射到 `TopoDS_Shape` + `TopTools_IndexedMapOfShape`（有历史记录可对拍）；manifold3d 无持久引用概念，3D 网格布尔的对拍需要我方先建引用层、再以实体计数对拍。

**验收线**：引用契约本身用「重放不变量」测试——同一脚本两遍重放，id 序列一致；注入一次非法引用（tombstone 引用），必须 `DomainError`。

### 4.3 退化知识库：引用失效 pitfall 语料（暂不扩族）

「实体被布尔/修复/简化改号后引用悬空」是 CAD 特有且高频的 pitfall。**现阶段不新增第六退化族**
（五族结构是母文档既定设计，扩族是 ADR 级决策），先以**跨族标记**方式积累语料：每条相关
pitfall 带 `ref:` 标签，归入最接近的族（如引用失效多归 C 共面/重合 或 I 自交/非流形），
待语料量足够再在 ADR-0002 中一并裁决是否单列「R 引用失效族」。

首批种子条目（每族 ≥ 1 条，带最小用例）：

| 条目 | 触发信号 | 修复模式 |
|:--|:--|:--|
| 布尔合并后边号漂移 | 引用 `e12` 在布尔后指向不同边 | tombstone + 重编号报告 + 引用重解析 |
| 面分裂后父面失效 | chamfer 后原 `f2` 不复存在 | 父面 tombstone，子面新 id |
| 吸附歧义 | snap 容差内多个候选实体 | `nearest` + 平局即 `DomainError`（不猜） |
| 引用悬空静默 | 解析失败被吞掉返回 None | 静态检查器：解析路径禁止 `None` 兜底 |

### 4.4 验证台 Tier 5：过程化重放（procedural replay）

在四层证据之外新增第五层，专门验证「算子链」与「引用有效性」——Pointer-CAD 评估协议的 X2CAD 版。

**协议**：一个重放用例 = 一个脚本（操作序列）+ 断言集：

```json
{
  "name": "sketch_extrude_fillet_chain",
  "ops": [
    {"op": "sketch", "params": {...}, "assert": ["refs: p0,p1,c2"]},
    {"op": "extrude", "refs": {"profile": "c2"}, "assert": ["refs: f1..f5, e1..e8"]},
    {"op": "fillet", "refs": {"edges": ["e3"]}, "params": {"radius": 2.0}}
  ],
  "oracle": {"engine": "pythonocc", "replay": "same_script"}
}
```

**判定**：① 每步引用全部可解析且指向断言指定实体；② 每步产出通过 Tier 1 不变量；③ 终态与
参考引擎重放同一脚本后的质量属性（体积/面积/质心）相对误差 < 1e-6；④ tombstone 引用被拒。
**验收线**：basic 脚本族（sketch→extrude）与 complex 脚本族（含 fillet/chamfer）各自 100% 通过。

### 4.5 fillet / chamfer 以指针算子形式规格先行

Pointer-CAD 证明倒角/圆角是**表示能力的酸测试**。X2CAD 据此把这两个算子从「远期话题」提前为
「规格先行」：

- **2D 圆角（fillet2d）**：N2/P1 内落地，输入 = 两条 `CurveRef` + 半径，属纯数学叶子层
  （圆弧构造 + 切点计算），AI 可按 ADR-0001 直写，oracle = 解析切点 + Shapely 对拍。
- **3D 倒角/圆角（chamfer3d / fillet3d）**：只先写 `spec.json`（L1-L4 全五层 + references），
  实现走 OCCT 封装（`pythonocc-core` 的 BRepFilletAPI 对拍）或人工审查分步实现；
  规格中必须含 §4.3 全部引用失效条目。
- 两个规格都进 `needs_human_review`（ADR-0001 的 `unhandled` 闸门）。

### 4.6 snap 吸附语义与 `sketch.json` 指针脚本

- 在 `primitives` 容差上下文增加 `snap(point, candidates, tol) -> (PointRef | None)`：吸附到容差内
  最近的既有实体，返回**引用而非坐标**（Pointer-CAD 的「sketch snapping」）；平局报 `DomainError`。
- P1 的 `sketch.json` 脚本格式从设计文档升级：实体间关系一律用引用表达（点在线端点、圆与线相切
  记 `tangent_to: c1`），不重复存储坐标——从源头杜绝「两处坐标漂移」类 bug。

### 4.7 ref2spec 流水线 L1 扩展

L1（签名与域）提取时新增「实体引用识别」：从文献/文档中识别「on the edge / at face / the selected
edge / tangent to」等选择语义，产出 references 字段候选，schema 校验后进入 spec。对超长文档的
语义检索增加引用语义查询模板。此为纯流水线脚手架，AI 可直写。

### 4.8 鲁棒性平面按操作族分层报告

`robustness_plane.csv` 增加 `op_family` 维度（basic：sketch/extrude/boolean；complex：fillet/chamfer/
constraint），分层出通过率与失败退化族标签。验收线沿用母文档 §6.4（默认域 100%，边界域 ≥ 95%），
但 complex 族单独成行，禁止用 basic 族的成绩稀释 complex 族。

---

## 5. 与 ADR-0001 的一致性检查

| 优化 | 是否触及拓扑变异 | 结论 |
|:--|:--|:--|
| §4.1 schema 扩展 | 否（规格脚手架） | AI 可直写 |
| §4.2 EntityRef 契约 | 契约是规则不是变异；重编号报告的实现属装配层 | 规格先行；变异实现走人工审查/封装 |
| §4.3 pitfall 语料 | 否 | AI 可直写 |
| §4.4 Tier 5 runner | 否（确定性验证代码） | AI 可直写 |
| §4.5 fillet2d | 否（叶子算法） | AI 可直写；3D 只写 spec |
| §4.6 snap / sketch.json | snap 是叶子；脚本格式是脚手架 | AI 可直写 |
| §4.7 ref2spec 扩展 | 否 | AI 可直写 |

LLM 角色不变：不做几何计算、不直写拓扑变异；Pointer-CAD 的 LLM 部分在 X2CAD 中由「确定性算子 +
验证台」承担。

---

## 6. 建议决策点（`[待裁决]`，拍板后转 ADR-0002）

| 决策 | 默认建议 | 备选 |
|:--|:--|:--|
| D1 是否现在建 EntityRef 契约（§4.2） | **是，规格先行**（P0 收尾时冻结 v0.1） | 拖到 P2 布尔再补（预计返工成本最高） |
| D2 spec schema 升级 0.2 | **是**，旧算子原地兼容 | 否 |
| D3 Tier 5 是否单列证据层 | **是**，与四层并列 | 并入 Tier 2/3（会模糊「引用有效性」这一独立判据） |
| D4 fillet/chamfer 优先级 | **2D 圆角进 N2/P1；3D 只写规格**（§4.5） | 3D 也提前实现（违反 ADR-0001 节奏，不推荐） |
| D5 退化五族是否扩为六族 | **暂不扩**，先积累 `ref:` 标签语料 | 直接新增 R 族 |

---

## 7. 实施顺序与验收线

| 序 | 动作 | 归属阶段 | 验收线 |
|:--|:--|:--|:--|
| 1 | spec schema v0.2 + 静态检查器扩展（§4.1） | P0 收尾 | 旧三算子 spec 无报错；带 references 的样例 spec 通过校验 |
| 2 | EntityRef 契约文档 + 重放不变量测试骨架（§4.2） | P0 收尾 | 契约测试可跑（先对 2D 实体，3D 占位） |
| 3 | `ref:` 标签 pitfall 种子语料（§4.3） | P0 收尾 | 每族 ≥ 1 条含最小用例 |
| 4 | Tier 5 runner + basic 脚本族（§4.4） | P1 | sketch→extrude 链 100% 通过（Shapely 对拍版先行） |
| 5 | snap 语义 + `sketch.json` 指针格式（§4.6） | P1 | 吸附歧义报 DomainError；脚本重放 id 一致 |
| 6 | fillet2d 算子 + fillet3d/chamfer3d 规格（§4.5） | N2/P1（2D）｜P4（3D 规格） | 2D：切点解析 + Shapely 对拍全绿；3D：规格过 HITL |
| 7 | 鲁棒性平面分层报告（§4.8） | 随 Tier 4 落地 | complex 族单独成行 |

顺序依赖：2 → 4 → 6（引用层先于 Tier 5，Tier 5 先于 fillet 规格的引用断言）；1、3、7 可并行。

---

## 8. 参考

- Qi, D. et al. *Pointer-CAD: Unifying B-Rep and Command Sequences via Pointer-based Edges & Faces Selection*. CVPR 2026. [arXiv:2603.04337](https://arxiv.org/abs/2603.04337)；项目页 <https://snitro.github.io/Pointer-CAD-Page/>
- 本仓库：`docs/plans/2026-08-20-x2cad-kernel-design.md`（母文档）；`docs/adr/0001-nurbs-first.md`（硬约束）
