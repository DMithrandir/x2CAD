# 阶段 review：X2CAD 路线图的真实价值与工业界代差（2026-11-20）

> 范围：`docs/plans/2026-08-20-x2cad-kernel-design.md`、`docs/adr/0001–0004`、
> 当前 9 个算子 + 验证台 + `EntityRef` 契约；
> 结论：**判断层与 Harness 范式有真实稀缺价值；全功能内核能力落后工业界两代，且不该正面追赶。**
> 本文件同时是修复执行单：已修项标 `[x]`，未做项标 `[ ]`。

---

## 1. 剥去修辞后的真实价值

### 1.1 「AI 写高风险数值代码」的 Harness 工程实证（已兑现）

计算几何的代码极短，但一行符号或下标写错就会引发静默数值灾难。仓库已用真实事故证明这套
约束有效：

| 事故 | 证据 |
|:--|:--|
| Boehm 插入分母抄错（`U[i+p]` 写成 `U[i+p+1]`） | [0002-p0-verification-and-ref-contract.md:99–101](../adr/0002-p0-verification-and-ref-contract.md#L99-L101) |
| 两次「存活变异」暴露测试断言过宽 | [0002-p0-verification-and-ref-contract.md:102–104](../adr/0002-p0-verification-and-ref-contract.md#L102-L104)、[2026-11-09-next-batch.md:70–74](../plans/2026-11-09-next-batch.md#L70-L74) |
| 等长变异 + 同秒恢复导致 `.pyc` 复用 | [mutation.py:15–18](../../verify/mutation.py#L15-L18) |

价值不在"造出了多强的 CAD"，而在**一套可复用的 Verifier-First AI 研发范式**。

### 1.2 AI-for-CAD 的细粒度归因器（高潜力，需 P1 兑现）

生成模型接到的是 `StdFail_NotDone` 级别的稀疏奖励；本仓库的退化语料 + 前置/后置契约能给出
结构化死因（`C-004 共线重叠`、`S-004 零长边`、圆角切点越界、`TombstoneError`）。兑现门槛是
P1 脚本链或 OCCT adapter，当前尚未打通。

### 1.3 零沉没成本的跨语言规范资产

黄金用例与退化语料是语言无关数据；内核迁 Rust 或改做 OCCT 上层验证器时，判据可 100% 继承。

---

## 2. 七个工业界代差

只谈架构模型与数学机制，不谈"商业内核有几百万行"这种体量差距。

| # | 代差 | 严重度 | 现状 | 工业界 |
|:--|:--|:--|:--|:--|
| 1 | **容差模型** | 高（P1 必修） | 算子入参 `ToleranceContext`；求交走 `Fraction` 后 `float` 输出 | 容差绑定到拓扑实体（顶点球/边管/面片），存在 `Tol(F) ≤ Tol(E) ≤ Tol(V)`；p-curve 与 3D 曲线双表示 |
| 2 | **拓扑持久命名（TNP）** | 高（口径必修） | 单调计数 id + 同脚本重放一致 | 特征历史锚点 + 邻接语义签名（Parasolid Tags、Onshape `qCreatedBy`、Realthunder ElementMap） |
| 3 | **解析图元通道** | 中高（P1 补） | NURBS 统一底座，求交规划为数值细分/Newton | Plane/Cylinder/Cone/Sphere 专用闭式矩阵；解析退化可精确分类 |
| 4 | **约束求解器** | 中（P1 定验收线） | 局部 LM + SVD 秩分析 | 图刚度分解、分支手性锁定、最小冲突集诊断 |
| 5 | **三大深水区算子** | 战略放弃 | 无 | 变半径圆角/顶点混合、偏移抽壳自交裁剪、直接建模 |
| 6 | **脏几何修复** | 战略放弃 | 非法输入一律 `DomainError` | `ShapeFix` 级缝合/降级，处理外部 STEP |
| 7 | **运行时底座** | 中（记录） | Python + `Fraction`，无空间索引 | BVH/R-tree、GPU 隐式场、Rust 类型化拓扑 |

### 2.1 级联容差（最隐蔽的一处内伤）

`line_line_intersection` 单步精确，但 `point` 是 `float`。把该点喂给下一步的精确谓词时，
按二进制值回推的 `Fraction` 已不在原线段上——**精确谓词会在下一步反咬自己**。CGAL 的
Exact Constructions 全程持有精确代数数，绝不中途退回 `float`。

### 2.2 TNP 的过度声明

"同脚本重放两遍 id 一致"只叫确定性执行。真正的 TNP 是：草图宽度从 20 改成 50 后，
"顶面右前边"仍是同一条语义边，即使 id、参数区间、边数都变了。当前契约解决的是
**AI 单趟顺序生成脚本时的局部指针传递**，不是参数化重生成。

### 2.3 解析通道缺失

真实机械模型 80%–90% 是解析几何。把圆柱/圆锥转成有理 NURBS 再数值求交，会把本可精确分类的
退化（同轴、内切、相切）变成"判别式接近零"。

### 2.4 约束求解只测残差不够

相切/距离约束是二次方程，存在多组合法解。纯 Newton/LM 在尺寸微调时会跳到镜像解；
"残差 < 1e-10"抓不住翻面。

---

## 3. 追 / 不追决策

| 差距 | 决策 | 理由 |
|:--|:--|:--|
| 3D 变半径圆角、抽壳自交、直接建模、STEP 修复、GPU 隐式场 | **不追** | 百人年级工程，追了必烂尾，偏离判据台定位 |
| 级联容差 | **P1 修** | 不修则多步布尔时精确谓词判自己上一步的交点不在边上 |
| TNP 口径 | **P1 修（文档 + 边界）** | 对外过度声明会损耗可信度；完整 TNP 另立阶段 |
| 解析图元（Line/Arc） | **P1 补** | 2D 闭式求交成本低，且可与 NURBS 通道互拍 |
| 约束多解翻转 | **P1 定验收线** | 求解器可只写局部 LM，但验证台必须测分支连续性 |

---

## 4. 本轮修复执行单

- [x] **级联容差**：`SegmentIntersection.point_exact`（`Fraction` 坐标）、
  `intersection_point_exact`、`point_on_segment_exact`；
  回归测试证明 `(1, 5/3)` 的 float 交点按二进制回推不在原线段上
  （[impl.py](../../operators/line_line_intersection/impl.py)、[test_line_line_intersection.py](../../tests/test_line_line_intersection.py)）。
- [x] **TNP 边界**：[ADR-0004](../adr/0004-determinism-vs-tnp.md)；
  契约文档 §10；README §1/§2.4 与站点页改口。
- [x] **约束求解器验收**：[constraint-solver.md](../specs/constraint-solver.md)，
  含手性/分支连续性、最小冲突集、DOF 诊断。
- [x] **解析图元规格**：[analytic-primitives.md](../specs/analytic-primitives.md)，
  给出 Segment×Arc、Arc×Arc 的判定与输出契约。
- [x] **非目标收口**：README §6 增加三大深水区、STEP 修复、GPU 隐式场的显式不追。
- [x] **实现 Segment×Arc**（2026-11-20 追加）：`operators/segment_arc_intersection`，
  判别式有理数精确判号，弧段过滤用起终向量叉积（见 analytic-primitives §3.1）；
  18 例 oracle（切点/弦交/入出点/顺逆时针/优弧/端点根/退化拒绝/圆不变量回代）、
  8 条 conformance、3 个新变异（判别式分类、顺时针符号、端点根过滤）。
  首轮变异 `SEGMENT_ARC_ROOT_FILTER_BOUND` 存活——原测试的弦交点不在端点，
  补 `test_endpoint_root_is_kept` 后捕获。当前 272 例测试、55 conformance、18/18 变异。
- [x] **实现 Arc×Arc / Circle×Circle**（2026-11-20 追加）：`operators/arc_arc_intersection`，
  根轴法 + 六分类（外离/外切/相交/内切/内含/同心重合），d² 与 (r1±r2)² 的比较全部
  有理数精确；弧段过滤复用 #2 的公共函数 `arc_contains_dir`（原私有符号改公开，
  spec `depends_on` 声明，SC005/SC006 通过）。17 例 oracle、10 条 conformance、
  3 个新变异（外切分类、根轴因子 2、内含守卫）。变异审计发现原写的 h²<0
  防御性守卫是**不可达死代码**（分类已在有理数上保证 h²≥0，跳过它无法被任何
  测试捕获）——删除并注释推导；"跳过内含守卫"变异由 `test_containment`
  的贴边内含用例捕获（守卫被跳过时 math.sqrt 收到负数抛 ValueError）。
  当前 289 例测试、65 conformance、21/21 变异。
- [x] **实现 A2 Segment×Bézier**（2026-11-20 追加）：新数值基元
  `primitives/polynomial.py`（Bernstein↔幂基、gcd、Yun 无平方分解、Sturm 隔离）；
  `operators/line_bezier_intersection`：根个数/隔离/重数精确判定，相切=重数≥2，
  端点根精确剥离，认证区间输出，共线退化返回 t 区间并集。21 例 oracle、9 条
  conformance、4 个新变异。两个发现：gcd 边界快路径变异审计证明行为不可观察
  （死代码，删除）；FILTER_REJECT 存活暴露 miss 测试未覆盖 rmin>d2 早退，
  补变体后捕获。当前 311 例测试、74 conformance、24/24 变异。
- [ ] **A3**：Bézier×Bézier 求交（细分 + 包围盒 + Newton，多项式通道收官）。
- [ ] **TNP 设计**：特征历史锚点 + 邻接签名（独立 ADR，不进 P1）。
- [ ] **脏几何修复 / 3D 深水区**：保持 Non-Goal，不排期。

---

## 5. 本轮证据

| 项 | 值 |
|:--|:--|
| oracle 测试 | 311 例全绿 |
| conformance | 74/74 cases |
| 变异自审 | 24/24 = 100% |
| 静态检查 | 0 findings |
| 门禁 | `python -m verify` PASS |

复跑：

```pwsh
python -m pytest
python -m verify
python -m verify.mutation
```

---

## 6. 一句话结论

这份路线图在**全功能工业内核**上落后商业巨头至少两代，且永远不该正面追赶；但在
**"用形式化不变量 + 变异自审约束 AI 生成几何代码、为 AI-for-CAD 提供白盒死因判据"**
这个生态位上，切入点真实且工业界没有现成开源替代品。先把级联容差与 TNP 口径这两处内功
补严，再谈 2D 布尔与更大范围的对拍。
