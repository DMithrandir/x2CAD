# ADR-0003：EntityRef 派生寻址（1-to-N / N-to-1 谱系）

- 状态：已接受
- 日期：2026-11-16
- 决策人：用户（对路线图的审计意见）+ 主会话（契约与测试落地）
- 关联：`docs/specs/entity-ref-contract.md` v0.2；
  `kernel/entity_ref.py`；`tests/test_entity_ref.py`；
  `docs/adr/0002-p0-verification-and-ref-contract.md` D1；
  Pointer-CAD 文档 §4.2；路线图评审意见（"分裂/合并谱系缺失"一条）

## 背景

v0.1 的 `EntityRef` 契约只覆盖三种情形：**恒等**、**1-to-1 重编号**（`remap`）与
**1-to-0 失效**（`tombstone`）。验收线也止于"重放两遍 id 序列一致 + tombstone 引用抛错"。

这条线在 N2 立刻不够用：Boehm 节点插入后的 `curve_split` 把一条边切成两条（1-to-N），
P1 布尔裁剪会在交点处切边，共线碎片会被合并（N-to-1）。若契约只有"重编号或 tombstone"，
脚本对"原边靠近 u=0.3 的那一段"的引用只能两个选择：整条 tombstone（丢失信息），
或 remap 到"最接近"的某一段（隐式猜段）。两者都会在 P1 之后引发成批引用失效或错指。

Pointer-CAD 用指针解决"选哪个实体"，但没有回答"实体被切开后选哪一段"。
本 ADR 补上这一段语义，仍严格停在契约层（ADR-0001：不含拓扑变异）。

## 决策

### D12 新增 `DerivedRef` 与 `split`/`merge` 谱系

- `RefMapping.split(old, parts, op_id=..., param_ranges=None)` 记录 1-to-N 谱系；
- `RefMapping.merge(sources, merged, op_id=...)` 记录 N-to-1 谱系；
- `DerivedRef.by_index(op_id, source, i)` / `DerivedRef.by_param(op_id, source, u)`
  指代"第 i 段"或"参数 u 所在段"；`resolve_derived` 解析并返回 `(EntityRef, payload)`；
- 谱系键为 `(op_id, source.id)`；`op_id` 由算子生成、必须非空，是审计与去重的锚点。

### D13 分裂不重编号父实体，合并重编号源实体

- **分裂**：父实体语义未变（它仍存在或由调用方另行 `remap`/`tombstone`），
  "哪一段"只能靠 `DerivedRef` 显式寻址。自动 remap 到任一段都会制造隐式猜测；
- **合并**：源实体确实被合并结果替代，`merge` 自动把每个源 `remap` 到 `merged`，
  旧引用仍可解析（不悬空），谱系单独保留供反向审计。

### D14 参数选择采用右连续口径

`param_ranges` 与 `parts` 一一对应；选段规则 `lo <= u < hi`，`u` 等于整段末端点时
归最后一段。这与基函数/曲线求值的右连续约定一致（`CLAUDE.md`"求导类算子的约定"），
也避免了分裂点归属的二次歧义。`param_ranges` 可选：只给序号也能工作，此时按参数
选择必须显式报错（拒绝猜）。

### D15 失败一律显式

序号越界、参数落在缝隙或域外、谱系不存在、区间未记录、子实体已不在当前表——
全部 `RefResolutionError`。不允许"取最近一段"、不允许返回 `None`，与 SC001 同一条纪律。

### D16 报告向后兼容

`RefMapping.to_dict()` 保留既有 `mapped` / `tombstones` 键，新增 `derivations` /
`merges`；排序固定（op_id、源 id 序列），同一脚本两遍输出逐位相同。

## 被否方案

| 方案 | 否决理由 |
|:--|:--|
| 父实体分裂后一律 tombstone | 脚本对"原曲线的某段"的引用全部失效；丢失 1-to-N 信息，违反"可变但可引用"的目标 |
| 父实体自动 remap 到第一段/最近段 | 隐式猜段，与 `select_nearest` 平局即报错的纪律冲突；分裂点附近必然错指 |
| 用全局自增 op 计数器代替字符串 `op_id` | 计数器依赖执行顺序，重放审计困难；字符串由算子确定性生成更易核对 |
| 等 P1 布尔实现时再补谱系 | 契约冻结点已过，后补意味着改 API 与所有调用方；与 D1 的"先冻结"理由相同 |

## 后果

**正面**

- EntityRef 从"生灭 + 1-to-1"扩展到完整的生灭/替代/分裂/合并四类谱系；
- N2 的 Boehm 分裂与 P1 曲线裁剪有了确定性寻址基础，脚本不必在切边后集体失效；
- 谱系进入 `to_dict()` 证据链，可静态审计"谁切了谁、谁并了谁"。

**负面 / 风险**

- 契约面积增大：`DerivedRef`、两种选择子、区间校验都是新的维护面；
- `param_ranges` 的正确性依赖调用方（算子）如实记录；契约层只能校验形状
  （有限、递增、不重叠、数量匹配），不能校验"区间真的对应那段几何"——后者必须由
  算子级 oracle 钉住；
- 仍未实现拓扑变异与 Tier 5 重放（边界未变）。

## 验收（本次落地）

- `tests/test_entity_ref.py`：新增 13 个用例（序号/参数/右连续/缝隙/嵌套谱系/
  合并/冲突拒绝/确定性序列化/构造校验），该文件 26 例通过、全套 232 例通过；
- `python -m verify` 门禁保持 PASS（本 ADR 不改算子，静态检查与 conformance 无变化）；
- 文档：`docs/specs/entity-ref-contract.md` 升到 v0.2，`docs/plans/…-kernel-design.md`
  §11 追加执行记录。
