# X2CAD — Oracle-First CAD Kernel & White-Box Conformance Suite

**把几何内核的“经验玄学”，变成可形式化验证、可变异自审、可跨内核对拍的工程判据。**

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Tests](https://img.shields.io/badge/tests-289%20passed-brightgreen)
![Conformance](https://img.shields.io/badge/conformance-65%20cases-blue)
![Mutation](https://img.shields.io/badge/mutation-21%2F21%20killed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

> 仓库地址：<https://github.com/DMithrandir/x2CAD>

---

## 1. 为什么做这件事（Why This Exists）

AI 与 CAD 交叉领域的瓶颈，已经从**“能不能生成几何”**转移到**“什么算生成对了、算子在容差边界下到底稳不稳”**：

* **生成侧早已拥挤不堪**：无论是基于指针序列统一 B-Rep 与命令生成的 [Pointer-CAD (arXiv:2603.04337)](https://arxiv.org/abs/2603.04337)、多模态条件生成的 [CAD-MLLM (arXiv:2411.04954)](https://www.alphaxiv.org/abs/2411.04954)，还是引入显式构建计划中间表示的 [MIRAGE-CAD (arXiv:2608.28669)](https://arxiv.org/abs/2608.28669) 与连续场表示的 [DualBrep (arXiv:2606.31579)](https://arxiv.org/abs/2606.31579)，都在争夺上游生成能力。
* **评测侧仍停留在“系统级黑盒”**：现有的主流评测基准（[CADTests / CADTestBench (arXiv:2605.07807)](https://arxiv.org/abs/2605.07807)、[CADBench (arXiv:2605.10873)](https://arxiv.org/abs/2605.10873)、[RealCADBench (arXiv:2609.03773)](https://arxiv.org/abs/2609.03773)）普遍采用“输入模型/脚本 → 运行时导出网格 → 算体积 IoU 或视觉打分”的黑盒模式。当底层几何内核发生布尔失败或相切崩溃时，黑盒分数既无法暴露非流形微裂缝，也无法定位是哪一个算子、在哪一类退化配置下失手。
* **开源内核缺乏白盒证据链**：工业界长期被 Parasolid、ACIS 等商业几何内核与西门子 [D-Cubed](https://www.siemens.com/en-us/products/plm-components/d-cubed/) 等约束求解组件垄断；开源界唯一的全功能 B-Rep 内核 [Open CASCADE Technology (OCCT)](https://occt3d.com/open-cascade-technology/) 虽功能庞大，但容差行为（Fuzzy Tolerance）缺乏形式化证据链，也缺少公开的算子级 Conformance Suite。

**本项目的定位不是重写一遍大而全的 [OCCT](https://occt3d.com/open-cascade-technology/)，而是补齐开源 CAD 与 AI-for-CAD 缺失的“判据层 + 最小可证明内核切片”**：以 **预言机先于内核（Oracle-First）** 为铁律，将退化五族语料、四层证据链、变异自审与支撑确定性重放/单步派生寻址的**实体引用契约（`EntityRef`；参数化 TNP 不在本层承诺，见 [ADR-0004](docs/adr/0004-determinism-vs-tnp.md)）** 打造为可复用的公开基础设施。

当前状态（2026-11-20）：N1 曲线算子、N2 节点操作、P0 验证台与 `EntityRef` 契约（含分裂/合并谱系）已落地；P1 解析图元通道三条闭式组合全部落地（线段×线段、线段×圆弧、圆×圆），判别式/根轴/弧段过滤全部有理数精确判号。289 例 oracle 测试全绿，`python -m verify` 门禁 PASS，变异捕获率 21/21。下一步：A2 直线-Bézier 求交。

---

## 2. 核心方法论（The 4-Pillar Methodology）

### 2.1 预言机先于内核 + 变异自审（Oracle-First & Mutation Self-Audit）

算子代码未动，黄金预测集（Oracle）先行。为防止测试集本身存在静默漏报（False Negative），P0 验证台内置**算子变异注入器**：符号翻转、分母取错节点、指数写错、装配下标错位、重数守卫删除等。任何 Oracle 必须对全部注入变异达到 **100% 缺陷捕获率（Mutation Kill Rate）**，才允许准入作为内核验收基准。

工程细节（ADR-0002 D10）：变异会临时改写源码，必须禁用字节码写入并在恢复后清除 `.pyc`，否则 CPython 的 `(mtime, size)` 校验会复用变异后的字节码——这是真实踩过的坑，已固化为回归断言。

### 2.2 四层证据链（4-Layer Evidence Chain）

拒绝单一的 `assert_near(a, b, 1e-6)`。每一个叶子数学算子与拓扑算子的验收必须同时穿过四层正交证据：

1. **L1 代数恒等与不变量（Algebraic Invariants）**：如 B-Spline 单位分解性（Partition of Unity）、仿射协变性、Boehm 节点插入前后几何轨迹与各阶导数零漂移。
2. **L2 微分与数值一致性（Differential Consistency）**：解析求导与高精度有限差分（含按节点间距定标的步长）的收敛与一致性验证。
3. **L3 外部多路独立对拍（Cross-Oracle Differential Testing）**：高精度符号解、区间算术包络，以及 [Shapely](https://shapely.readthedocs.io/)（仅针对折线/多边形拓扑层）、[OCCT](https://occt3d.com/open-cascade-technology/) 等外部基线。**当前状态**：本机缺 `shapely` / `manifold3d` / `trimesh`，该层显式标注为未启用（Tier 2 解析真值已覆盖现有算子）；接入口径见 `docs/specs/cad-operator-conformance.md` §10。
4. **L4 退化五族压力扫描（Degeneracy Pitfall Sweep）**：在参数平面与容差平面（Robustness Plane）上自动扫掠极端病态输入，输出鲁棒性热力图。

### 2.3 退化五族形式化语料库（The 5-Family Degeneracy Corpus）

将传统 CAD 内核开发中口耳相传的“老师傅经验”，沉淀为带触发信号（Trigger Signals）、数学判据与最小复现用例（Minimal Reproducible Cases）的结构化 JSON 语料资产（`degeneracy/index.json`，当前 17 条，每条指向真实可执行用例、零死链）：

* **T 相切 / 极近掠过（Tangency & Grazing）**：曲线以极小交角掠过或高阶相切，牛顿迭代雅可比矩阵奇异。
* **C 重合 / 部分重叠（Coincidence & Partial Overlap）**：共线边、共面片、参数域局部重合，使交点从零维退化为一维区间或二维面域。
* **S 微小特征 / sliver（Sliver & Micro-Features）**：尺度逼近或跨过局部容差的碎边、狭长三角形面片、高重数紧邻节点（Knot Clustering）。
* **I 自交 / 非流形（Self-Intersection & Non-Manifold）**：导数归零点（尖点 Cusp）、极点退化、偏移曲线局部自交环、非流形边。
* **N 数值抵消 / 尺度悬殊（Cancellation & Scale Disparity）**：大坐标偏移下的微小几何特征引发的灾难性有效数字相消。

### 2.4 `EntityRef` 指针式引用与确定性重放契约

受 [Pointer-CAD (arXiv:2603.04337)](https://arxiv.org/abs/2603.04337) 启发并向内核底层延伸：表示层决定能力上限。本项目在启动二维布尔之前，率先冻结 `EntityRef` 契约（v0.2，ADR-0003）：

* **确定性重放（Deterministic Replay）**：同一建模脚本或 `sketch.json` 重放任意次，实体 id 序列（`snapshot()`）逐位一致。
* **显式生命周期与 Tombstone 拦截**：被删除的实体引用立即转为 `Tombstone`，任何后续解引用强制抛出结构化 `DomainError`/`TombstoneError`，杜绝静默张冠李戴。
* **派生谱系追踪（1-to-N / N-to-1 Lineage）**：Boehm 分裂与求交打断产生子实体时，用 `DerivedRef`（序号或参数选择子，右连续口径）确定性寻址；共线边合并用 `merge` 显式重编号并保留来源谱系。

**边界（ADR-0004）**：以上保证的是**确定性重放与单步派生寻址**，不是参数化 CAD 的拓扑持久命名（TNP）。修改草图尺寸导致实体增删后，如何让"顶面右前边"仍指向同一条语义边，需要特征历史锚点 + 邻接签名，属独立阶段，本契约不承诺。

---

## 3. 演进路线图与验收红线（Dependency-Driven Roadmap）

本项目严格按**工程依赖顺序**（而非灵感顺序）推进，每一阶段均设定硬性量化准入线（Gate）：

| 阶段 | 模块范围 | 为什么处于该依赖位置 | 硬性验收线（Acceptance Gate） | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **N1** | **曲线基础算子**<br>（求值、解析求导、插值） | 占 CAD 内核功能面积 ~5%，但属于唯一能被 100% 形式化证明正确的纯数学基座 | 解析真值 / 差分对拍 / 不变量全绿；边界重数与端点插值零漂移 | **Done**（2026-08） |
| **#1 (P0)** | **白盒验证台 + 预言机变异自审** | 算子未大规模入核前，必须先审计裁判本身；此时构建成本最低、后续复利最高 | 静态检查 0 findings；覆盖率 0 缺口；conformance 0 失败；变异捕获率 **21/21 = 100%** | **Done**（2026-11-09） |
| **#2** | **`EntityRef` 契约**<br>（指针引用 + 重编号 + 谱系） | 一旦布尔运算动工，无契约的引用机制必将全盘返工 | 同一脚本重放两遍 id 序列严格一致；Tombstone 引用 100% 报错；1-to-N / N-to-1 谱系可解析 | **Done**（2026-11-16，v0.2） |
| **#4 (N2)** | **节点操作与曲线微分几何**<br>（Boehm、升阶、分裂、弧长/切矢/曲率、2D 圆角） | 纯数学叶子分支收口，为参数域求交打断提供无损几何操作 | 四路 Oracle 全部通过；节点插入几何误差 < 1e-12（测试钉住） | **Done**（2026-11-09） |
| **#3 (P1)** | **二维完整垂直切片**<br>（2D 约束求解 + 2D 曲线布尔） | 二维是唯一能由个人将“所有算子与拓扑装配都做对”的完整闭环（参考 [SolveSpace](https://solvespace.com/) / [arXiv:1006.1126](https://arxiv.org/abs/1006.1126)） | 约束残差 < 1e-10；多边形层与 [Shapely](https://shapely.readthedocs.io/) 对拍一致，曲线层通过合成解析解对拍 | **In Progress**（P1-A1 线段求交已落地；A2/A3 进行中） |
| **#5** | **曲线求交 (CCI) → 曲面求交 (SSI)** | 从“纯数学叶子算法”跨入“三维拓扑连通判定”（参见 [arXiv:2604.12631](https://arxiv.org/abs/2604.12631)）的终极门槛 | `区间隔离 → Bézier Clipping/区间牛顿 → Boehm 插入 → 区间分类 → 装配` 全链路白盒对拍通过 | **Future** |

> **关键架构纪律（ADR-0001 / ADR-0002）**：AI 只直接成文**纯数学叶子算法 + 可静态验证的脚手架**；B-Rep 拓扑变异必须规格先行、分步小实现、人工审查，或封装参考实现。二维曲线布尔与求交链上的每一步（区间隔离、求根、Boehm 节点插入、区间内外分类、半边装配）必须拆解为**无状态、可独立对拍的纯数学叶子函数（Leaf Algorithms）**。

---

## 4. 仓库目录结构（Repository Layout）

```text
x2cad/
├── docs/
│   ├── adr/                       # 决策记录：0001 范围纪律 / 0002 P0 验证台 / 0003 EntityRef 谱系
│   ├── plans/                     # 母设计文档 + Pointer-CAD 参考文档
│   ├── specs/                     # 契约规范：算子 conformance、EntityRef 契约
│   └── learning/                  # 学习路线与练习
├── primitives/                    # 数值基元：B 样条基、精确谓词、容差上下文、Gauss 求积
├── operators/                     # 算子库（每算子 = impl.py + spec.json + oracle 测试 + conformance case）
│   ├── curve_eval/                # B 样条 / NURBS 曲线求值与各阶导数
│   ├── surface_eval/              # 张量积曲面求值、偏导
│   ├── curve_interpolation/       # 全局插值
│   ├── knot_insertion/            # Boehm 节点插入（单次/重复，含 NURBS）
│   ├── curve_split/               # 曲线分割（依赖 knot_insertion）
│   ├── degree_elevation/          # Bézier 升阶（含 NURBS）
│   ├── curve_geometry/            # 弧长、单位切矢、曲率
│   ├── fillet_2d/                 # 二维相切圆角
│   ├── line_line_intersection/    # 线段求交（精确有理数判定，含共线重叠）
│   ├── segment_arc_intersection/  # 线段-圆弧求交（判别式精确判号 + 弧段过滤）
│   └── arc_arc_intersection/      # 圆-圆求交（根轴法 + 六分类 + 弧段过滤）
├── kernel/                        # 公共层：entity_ref.py（引用契约 + 派生谱系，无拓扑变异）
├── verify/                        # 验证台：invariants / analytic / robustness / static_check /
│                                  # spec_check / conformance（cases/）/ mutation（audit/）/ evidence/
├── degeneracy/                    # 退化五族知识库：index.json + README（schema 与用法）
├── x2cad/                         # 流水线脚手架：内容寻址产物缓存
├── tests/                         # 289 例 oracle 测试
├── conftest.py                    # pytest 根目录锚点
├── pyproject.toml                 # 包元数据与 pytest 配置
├── CLAUDE.md                      # 项目路由与硬性范围纪律（协作入口）
└── README.md
```

---

## 5. 快速开始：运行白盒验证台与变异自审（Quick Start）

纯 Python 实现，**无第三方运行时依赖**（仅测试需要 `pytest`，Python ≥ 3.9）：

```pwsh
git clone https://github.com/DMithrandir/x2CAD.git
cd x2cad

# 1. 全部 oracle 测试（解析真值 / 独立参考实现 / 有限差分 / 不变量 四路对拍）
python -m pytest

# 2. 全量门禁：静态检查 SC001–SC008 + 覆盖率 + conformance，并写出证据
#    → verify/evidence/report.json
python -m verify

# 3. 预言机变异自审：临时注入 9 个变异，捕获率必须 100%
#    → verify/audit/mutation_report.json
python -m verify.mutation
```

输出示例（`python -m verify`）：

```text
静态检查：0 条问题
conformance：47/47 cases，47/47 checks，证据 verify/evidence/report.json
门禁：PASS
```

新增算子 = 四件套：`impl.py` + `spec.json` + oracle 测试 + `verify/cases/<slug>.json`。缺任何一件，`python -m verify` 会失败。

---

## 6. 明确的非目标（Explicit Non-Goals）

为了保持极高的工程信噪比，本项目**明确不做**以下事项：

* **不训练端到端 Text-to-CAD / Image-to-CAD 大模型**：不参与拼算力与合成数据规模的生成竞赛，专注为生成模型提供底层几何验证器（Verifier）与显式判据。
* **不盲目复刻 [OCCT](https://occt3d.com/open-cascade-technology/) 的全量工业长尾特性**：在未建立完备的退化语料与四层 Oracle 之前，绝不堆砌缺乏正确性证明的 3D 变半径倒角或复杂特判。
* **不把容差当作全局魔法常量（Global Magic Epsilon）**：拒绝在代码里散落硬编码的 `1e-7`；容差是显式类型（`ToleranceContext`），符号判定走精确谓词，两者不可互相替代。
* **不在 P1 阶段自研符号图分解约束求解器**：P1 只做最小闭包（局部 LM + SVD 欠定诊断）或封装 `libslvs`，避免陷入图约简长尾。
* **不追工业内核的三大深水区**：3D 变半径圆角/顶点混合（rolling-ball fillet、setback vertex blend）、等距偏移/抽壳的自交裁剪（swallowtail）、直接建模（推拉面 + 删面自愈）。这些是百人年级工程，追了必烂尾；本项目的判据台只覆盖可独立对拍的叶子与单步装配。
* **不做 STEP 脏几何修复（Shape Healing）与 GPU 隐式场**：`DomainError` 是本项目对自产几何的纪律；外部破面/脏容差与 SDF/GPU 路线属另一条产品线。

---

## 7. 当前证据与已知边界（Evidence & Boundaries）

| 项 | 状态 |
| :--- | :--- |
| oracle 测试 | 289 例全绿（`tests/test_entity_ref.py` 26 例、`tests/test_line_line_intersection.py` 22 例、`tests/test_segment_arc_intersection.py` 18 例、`tests/test_arc_arc_intersection.py` 17 例） |
| `python -m verify` | PASS：静态检查 0 findings、覆盖率 0 缺口、conformance 65/65 cases |
| 变异自审 | 21/21 = 100% 捕获（`verify/audit/mutation_report.json`） |
| 退化语料 | 17 条，覆盖 T/C/S/I/N 五族，零死链 |
| Tier 3 外部对拍 | **未启用**：缺 `shapely` / `manifold3d` / `trimesh`；接入口径见 `docs/specs/cad-operator-conformance.md` §10 |
| Tier 5 过程化重放 | **未实现**：需要 P1 的 sketch/extrude 链；`EntityRef` 契约已为其提供引用基础 |
| 拓扑变异（布尔/修复/倒角重编号） | **未实现**：ADR-0001 划定的通道（规格先行 + 人工审查 + 参考实现封装） |

验证台证据（`verify/evidence/report.json`、`verify/audit/mutation_report.json`）随代码提交，作为“这批代码当时确实通过了什么”的存档。

---

## 8. 参考文献与领域坐标（References & Landscape）

* **表示层与过程化生成**：[Pointer-CAD (arXiv:2603.04337)](https://arxiv.org/abs/2603.04337) · [CAD-MLLM (arXiv:2411.04954)](https://www.alphaxiv.org/abs/2411.04954) · [MIRAGE-CAD (arXiv:2608.28669)](https://arxiv.org/abs/2608.28669) · [DualBrep (arXiv:2606.31579)](https://arxiv.org/abs/2606.31579)
* **评测基准与真实工程特征分割**：[CADTests (arXiv:2605.07807)](https://arxiv.org/abs/2605.07807) · [CADBench (arXiv:2605.10873)](https://arxiv.org/abs/2605.10873) · [RealCADBench (arXiv:2609.03773)](https://arxiv.org/abs/2609.03773) · [Real-World CAD Segmentation Benchmark (arXiv:2610.13466)](https://arxiv.org/abs/2610.13466)
* **求交拓扑判定与几何约束系统刚度理论**：[B-Spline Surface/Surface Intersection with Mapper (arXiv:2604.12631)](https://arxiv.org/abs/2604.12631) · [Body-and-cad Geometric Constraint Systems (arXiv:1006.1126)](https://arxiv.org/abs/1006.1126)
* **开源几何与约束基线**：[Open CASCADE Technology (OCCT)](https://occt3d.com/open-cascade-technology/) · [SolveSpace](https://solvespace.com/) · [Shapely](https://shapely.readthedocs.io/)

---

## 9. 文档索引（Where to Read More）

* 决策记录：[ADR-0001](docs/adr/0001-nurbs-first.md)（范围纪律）、[ADR-0002](docs/adr/0002-p0-verification-and-ref-contract.md)（P0 验证台与算子契约）、[ADR-0003](docs/adr/0003-entity-derivation-lineage.md)（EntityRef 派生寻址）
* 母设计文档：[docs/plans/2026-08-20-x2cad-kernel-design.md](docs/plans/2026-08-20-x2cad-kernel-design.md)
* 契约规范：[算子 conformance 规范](docs/specs/cad-operator-conformance.md)、[EntityRef 契约 v0.2](docs/specs/entity-ref-contract.md)
* 协作入口：[CLAUDE.md](CLAUDE.md)

---

## 10. License

MIT，详见 [LICENSE](LICENSE)。

