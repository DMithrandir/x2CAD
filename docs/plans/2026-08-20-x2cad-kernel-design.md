# X2CAD：用 harness + agent 生长式开发 CAD 内核 — 设计文档

> 版本 0.1.0 | 2026-08-20 | 项目根目录 `C:\Users\desha\Desktop\CAD`
> 方法论母本：x2strategy（`.claude/skills/x2strategy/`，ALAGENT-HKU paper2spec/spec2code 流水线）

---

## 1. 目标与非目标

### 1.1 目标

参考 x2strategy 的设计思路，用 harness + agent 渐进地「生长」一个 CAD 几何内核：

1. **x2cad 流水线**：几何文献/算法文档 → 算子规格 → 可执行算子代码 → 验证 → 诊断，全程 JSON 契约 + schema 校验。
2. **强自动预言机（oracle）**：CAD 与量化不同，几何有**数学真值**（体积/面积/质心/拓扑不变量）+ **参考实现可对拍**（OpenCASCADE / manifold3d / CGAL / Shapely），agent 循环的「过/不过」判定可以完全自动化。
3. **退化知识库（degeneracy index）**：CAD 的 pitfall 语料 —— 相切、共面、重叠、自交、浮点抵消。这是整个项目价值密度最高的知识资产。
4. **算子库生长**：每个几何算子 = 独立目录（spec + 实现 + 验证证据），通过验证台的算子才进内核公共 API。

### 1.2 非目标（YAGNI）

- 不追求性能基准（Python-first；接口留 Rust 后端接缝，真需要时逐算子替换）。
- 不实现渲染引擎（诊断只出 headless 图片/数据，可视化用现成库）。
- 不做 GUI、不做文件格式全谱支持（初期只做 STL/OBJ/3MF 与自研 JSON，STEP 是终局里程碑）。
- 不保证任何算子是生产级（OCCT 级 SSI/倒角按年级目标规划，见 §8 分阶段）。

---

## 2. x2strategy 设计 DNA 与 CAD 映射

x2strategy 的本质不是「论文转代码」，而是七个可迁移的设计决策。下表是逐条映射：

| # | x2strategy 设计 DNA | 为什么有效 | CAD 内核对应物 |
|:--|:--|:--|:--|
| 1 | **规格先行**：论文先变成 JSON spec，代码后生成 | LLM 在结构化约束下提取，比直接写代码稳定一个数量级 | 算子规格（OperatorSpec）先于实现 |
| 2 | **五层提取**：L0 检测 → L1 元数据 → L2 指标 → L3 逻辑 → L4 执行，逐层喂给 LLM，层间串行 | 每层上下文小、输出可校验，错误被逐层截断 | ref2spec 五层：L0 算子检测 → L1 签名与域 → L2 数学域 → L3 算法管线 → L4 **容差治理与退化语义** |
| 3 | **领域 pitfall 检索语料**：`operator_pitfall_index.md`，提取后按公式/语义检索注入修复上下文 | 把资深从业者的隐性知识变成可检索的显式语料 | **degeneracy index**：tangency / coplanar / sliver / self-intersection / cancellation 五大族，每条带触发信号、修复模式、验证用例 |
| 4 | **模板 + 注册表**：代码从 `research_strategy_template.py` 生成，结构固定 | 生成代码的结构方差收敛，验证器才能静态检查 | 算子模板（统一 precondition / tolerance / 不变量后置检查 / 退化分支表）+ 算子注册表 |
| 5 | **回测 = 可执行规格**：`backtest_output.txt` / `metrics.json` / 参数平面 / 诊断报告，全部 headless | 无人值守 CI 也能给出完整证据链 | **验证台（verification harness）**，四层证据（见 §6） |
| 6 | **HITL 只放在真歧义点**：`needs_human_review` 列表，其余全自动 | LLM 不该被问「对不对」，只该被问「语义选哪个」 | 容差语义裁决、不可解析的算法矛盾、公开 API 冻结 —— 三处人工闸门 |
| 7 | **有界重试纪律**：生成一次 + 至多一轮修复；同类错误最多 3 次；超出即停并报告 | 防止 agent 无限打补丁 | 同构保留：`generate → verify → (最多一轮) repair → 停` |

### 2.1 与 x2strategy 的刻意差异（按第一性推导，不是抄）

| 维度 | x2strategy | x2cad | 理由 |
|:--|:--|:--|:--|
| 构建顺序 | 先流水线，后回测 | **先验证台，后流水线，最后内核** | 量化回测是弱预言机；CAD 有强预言机。预言机先于内核，agent 的每一步才有客观判据 |
| 预言机强度 | 只有历史数据（无真值） | 解析真值 + 拓扑不变量 + 差分对拍 + 扰动平面 | 数学真值使「正确」可判定 |
| 鲁棒性平面的扰动源 | 参数网格（strategy 参数） | 随机刚体变换 × 尺度阶梯 × 相对位错 × 容差阶梯 | CAD 的病根是数值/退化，不是参数过拟合 |
| 知识库内容 | 指标公式 pitfall | 退化几何 pitfall（五族，见 §5） | 域知识不同 |
| 参考实现 | 论文报告的指标 | OpenCASCADE / manifold3d / CGAL / Shapely | 差分测试在几何域有成熟开源 oracle |
| 变异测试 | 无 | **预言机自审是硬性里程碑**（§7.4） | 一个会漏报的验证台比没有更危险：agent 会「通过」一个假及格线 |

---

## 3. 总体架构

```
                        ┌────────────────────────────────────────────┐
 几何文献/算法文档 ────▶│  x2cad 流水线（agent 编排层，Python）        │
 (PDF/MD/代码/笔记)     │  ref2spec → degeneracy 检索 → spec2op       │
                        │  → verify → diagnosis                      │
                        └──────────────┬─────────────────────────────┘
                                       │ 产出/消费
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────┐     ┌───────────────────┐    ┌────────────────────┐
   │ 算子库 operators/│     │ 内核 kernel/       │    │ 验证台 verify/      │
   │ spec + impl +    │◀───▶│ 纯几何无 IO，       │◀──▶│ 四层证据           │
   │ 证据链           │ 注册 │ 通过验证才进 API   │    │ (invariant/analytic/│
   └──────────────────┘     └───────────────────┘    │  differential/plane)│
                                                     └────────────────────┘
                                │
                     ┌──────────┴──────────┐
                     ▼                     ▼
            ┌────────────────┐   ┌────────────────────┐
            │ primitives/    │   │ degeneracy/        │
            │ 精确谓词       │   │ 退化知识库 +        │
            │ 容差上下文     │   │ 用例语料            │
            │ 数值基元       │   │ (五族 pitfall)      │
            └────────────────┘   └────────────────────┘
```

### 3.1 分层职责（对应量化四层的组织约束）

| 层 | 目录 | 职责 | 禁止 |
|:--|:--|:--|:--|
| 数值基元层 | `primitives/` | 精确谓词、容差上下文、向量/矩阵/多项式基函数、自适应浮点展开 | 不含任何算子逻辑 |
| 算子层 | `operators/<slug>/` | 每个几何算子独立目录：`spec.json`、`impl.py`、`evidence/` | 算子间不得相互 import 实现细节，只经注册表 |
| 内核层 | `kernel/` | 公共 API 装配（只暴露通过验证台的算子）+ 模型数据结构 | 不写新算法 |
| 验证层 | `verify/` | 四层证据生成 + 报告，不变量检查器 | 不改被测代码、不允许放水 |

**关键不变量：算子能否进入 `kernel/` 公共 API，唯一判据是 `operators/<slug>/evidence/` 中的验证证据，任何文档/口碑/代码审查都不能替代。**

---

## 4. x2cad 流水线（ref2spec → spec2op）

### 4.1 Stage 1：ref2spec（文档 → OperatorSpec）

输入任意形式（PDF / Markdown / 论文 / OCCT 算法文档 / 伪代码）。解析层与 x2strategy 同构：
Mode A 直接 LLM（≤100K 字符，头+尾截断）；Mode B 语义检索（超长文档）。解析出三个区段：**数学定义（math）**、**算法步骤（algorithm）**、**退化与容差说明（degeneracy_notes）**。

随后五层提取（层间串行、每层输出 JSON、schema 校验）：

| 层 | 内容 | 产出 |
|:--|:--|:--|
| **L0 算子检测** | 识别文档中的独立几何算子（如「NURBS 曲线插值」「网格布尔差」），一个文档可出 N 个算子，N>1 时并行提取、逐算子注入 focus | `List[OpBrief]` |
| **L1 签名与域** | 算子名、类别（curve/surface/topology/boolean/constraint/…）、维度（2D/3D）、输入输出类型、前置条件、几何域（流形假设等） | 签名 + 域 |
| **L2 数学域** | 参数化、基函数、精确谓词需求、数值核心公式，**带显式符号表**（每个符号：含义、单位、容差敏感度） | `MathDomain` |
| **L3 算法管线** | 步骤序列：预处理 → 主循环（细分/推进/分治）→ 拓扑装配 → 后处理；标注每步可并行性 | `List[AlgoStep]` |
| **L4 容差治理与退化语义** | CAD 独有层。逐退化族声明行为：**EXACT / SNAP / PERTURB / SUBDIVIDE / FAIL**；定义该算子的不变量契约 | `TolerancePolicy` + `InvariantContract` |

### 4.2 退化知识检索

L4 输出后，按 L2 符号表 + L4 退化族检索 `degeneracy/` 语料（索引同构于 x2strategy 的 `operator_pitfall_index.md`），产出 `degeneracy_context.md` 注入后续所有环节。检索到的每条 pitfall 若未在 L4 或实现中有显式处置，**升级为 `needs_human_review` 项**。

### 4.3 Stage 2：spec2op（OperatorSpec → 可执行算子）

从算子模板生成 `operators/<slug>/impl.py`。模板强制四段结构：

1. `preconditions()` —— 域校验，违规即 `DomainError`（不是静默错误结果）。
2. `execute(tol: ToleranceContext, inputs) -> outputs` —— 纯函数，无 IO、无全局状态、无随机性（随机性只在验证台一侧注入）。
3. `degeneracy_branches` —— 分支表：每条 pitfall 要么有对应代码分支，要么显式 `NotImplementedError` 并在 spec 中标 `unhandled`。
4. `post_invariants()` —— 自检不变量（与验证台的检查器共用同一实现，防两套口径）。

静态验证器（`verify/static_check.py`）拒绝：几何量裸 `==`/`!=` 比较（必须经容差上下文）、无分支的 pitfall、无后置不变量、精度魔法数。先静态过、再进验证台。

### 4.4 有界重试纪律（同构保留）

- 生成一次 → 验证。失败 → **至多一轮**定向修复 → 再验证。
- 同类运行时错误类别最多 3 次修复尝试；超过即停，产出 `[ERROR]` + 根因假设，交人。
- 每次重试都以 `[PROGRESS]` / `[ERROR]` 标记可见，禁止静默循环。

---

## 5. 退化知识库（degeneracy index）— 五族

CAD 内核开发的真实成本 80% 在退化几何。语料按五族组织，每条含：**触发信号（可从 spec/代码静态匹配）→ 典型场景 → 标准修复模式 → 最小验证用例**。

| 族 | 典型场景 | 标准修复模式 |
|:--|:--|:--|
| **T 相切** | 圆-圆相切、曲面-曲面一阶接触、SSI 在切点附近条件数爆炸 | 低阶近似 → 细分至分离度可辨；切点单独作为退化点处理 |
| **C 共面/重合** | 布尔运算共面面片、重合边、identical 实体差集 | 显式定向规则；重合面按面法向决断（EXACT 面分区）；identical 短路 |
| **S sliver/退化单元** | 近零面积三角形、近零体积四面体、近似退化 B 样条 span | 重参数化/分裂；质量阈值过滤 + 拓扑修复（collapse/split） |
| **I 自交/非流形** | 布尔结果自交边、非流形顶点、共享一条边多于两面 | 交点解析；自交边引入后分裂重建；非流形显式降级或拒绝 |
| **N 数值抵消/条件数** | 近平行线段求交、近共线三点 orient2d、大坐标小尺度 | 精确算术谓词（自适应浮点展开）；局部坐标系平移；相对容差而非绝对容差 |

**索引机制**：每条 pitfall 带正则/语义触发词（"tangent", "coplanar", "coincident", "nearly", "epsilon", "degenerate", "self-intersect", …），L2/L4 输出做词法 + LLM 双路匹配。

---

## 6. 验证台（verification harness）— 四层证据

每个算子目录产出 `evidence/`，含四层证据。**四层全绿 = 通过**；任何一层红即回 §4.4。

### 6.1 Tier 1 — 不变量（invariant）

输出对象必须满足的数学恒等式（拓扑为主）：
- 流形性：每条边恰好属于 1 或 2 个面（3D 网格/BRep）；
- 水密性：无边界面（closed 实体）；方向一致性；
- Euler-Poincaré 特征：`V − E + F = 2(1 − g)`（球拓扑 `g=0` 时 =2，与壳数/洞数一致）；
- 无自交、无退化单元（面积/体积低于相对阈值的单元计数为零）。

### 6.2 Tier 2 — 解析真值（analytic ground truth）

`measure(输出) vs 闭式真值`，报告相对误差：

| 量 | 真值来源 |
|:--|:--|
| 曲线弧长 | 圆弧/椭圆弧积分闭式；NURBS 圆参数化对拍 |
| 面积/体积/质心/惯性矩 | 球 `4/3πr³`、立方体、圆柱、圆环等闭式 |
| 布尔结果体积 | 两盒/球-盒相交体积的解析或数值积分高精度解 |
| 约束求解残差 | 构造即满足的配置（残差 = 0） |

**基准要求：任何通过算子，解析量相对误差 < 1e-6（与所声明容差绑定，容差放宽需 HITL 记录豁免）。**

### 6.3 Tier 3 — 差分对拍（differential）

与成熟开源参考实现对比：
- 2D：Shapely（GEOS）—— 面积/边界一致性/DE-9IM 关系矩阵；
- 3D 网格：manifold3d / trimesh（`boolean` 后对比体积、面数、水密性）；
- BRep/STEP：pythonocc-core（OpenCASCADE）—— 质量属性对比。

**注意**：对拍只比「可测的量」，不比内部表示；双方分歧时以解析真值（Tier 2）为最终裁决，参考实现仅作规模化回归语料。

### 6.4 Tier 4 — 鲁棒性平面（robustness plane）

x2strategy 参数平面的 CAD 版。对固定用例族做四维扰动扫描，产出通过率矩阵 + 热图：

```
随机刚体变换 (N=50 种子)
  × 全局尺度 {1e-3, 1e-1, 1, 1e3, 1e6}
  × 相对位错 {0, 1e-9, 1e-6, 1e-3, 1e-2}·s   (s=特征尺寸)
  × 容差阶梯 {1e-12, 1e-9, 1e-6}·s
```

输出 `robustness_plane.csv`（每格：通过率、最坏相对误差、失败退化族标签）+ `robustness_heatmap.png`。**验收线：默认域（尺度 1e-1~1e3、位错 ≤ 1e-6）通过率 100%，边界域 ≥ 95% 且所有失败可标注到退化族。**

### 6.5 证据产出清单（每算子）

```
operators/<slug>/
├── spec.json            # 五层提取结果（含 TolerancePolicy + InvariantContract）
├── spec.md              # 人类可读渲染
├── degeneracy_context.md
├── impl.py              # 模板生成
├── hitl_review.json     # needs_human_review 项与裁决
└── evidence/
    ├── invariants.json          # Tier1 检查明细
    ├── analytic.json            # Tier2 相对误差
    ├── differential.json        # Tier3 对拍差异
    ├── robustness_plane.csv     # Tier4 矩阵
    ├── robustness_heatmap.png
    ├── cases/*.json             # 用例（含退化用例）与几何序列化
    └── diagnosis_report.md      # 规格 vs 实测对照
```

---

## 7. Agent / Harness 协作模式

### 7.1 角色分工

| 组件 | 职责 |
|:--|:--|
| **主会话（harness 编排）** | 定序、HITL 闸门、调用流水线脚本、汇总报告 |
| **子代理（研究/修复）** | 单算子文献检索；失败算子定向修复（带完整证据上下文） |
| **工作流（workflow）** | 批量算子提取与生成时的扇出：`pipeline(items, parse → extract → pitfall → codegen)`，每 item 独立 |
| **Ralph 循环** | 单算子攻坚：目标 = 「鲁棒性平面验收线 + 零不变量违规」，以工作区文件为持久记忆，多轮新上下文推进 |
| **确定性脚本** | 所有数值核心：精确谓词、不变量检查、鲁棒性平面 runner、静态检查器、报告生成。**LLM 从不被信任直接做几何计算** |

### 7.2 HITL 闸门（只有三处，其余全自动）

1. **容差语义裁决**：两个合法规格冲突、或容差放宽请求（如「该算子 1e-4 已是最优」）时。
2. **API 冻结**：算子进入 `kernel/` 公共 API 前，人看一眼签名与语义。
3. **`unhandled` 显式声明**：pitfall 无分支且 spec 标 `unhandled` 时，确认是否接受。

### 7.3 进度标记协议

同构保留 `[PROGRESS]` / `[ARTIFACT]` / `[ERROR]` 三标记；`[ARTIFACT]` 必须给出真实相对路径。

### 7.4 预言机自审（oracle mutation audit）— 硬性里程碑

在信任验证台之前，先证明它会抓错。对一个已知良好的算子注入 **N 个故意变异**（符号翻转、容差硬编码、跳过退化分支、静默 NaN、结果加小偏置），验证台必须全部捕获。**任一变异漏检 = 验证台本身有 bug，先修验证台。** 该审计产出 `verify/audit/mutation_report.json` 归档。

---

## 8. 分阶段路线（D → B → C，每阶段可交付）

> 形态默认：先 2D 垂直切片，再精确谓词网格 BRep，最后 NURBS 算子库生长。
> 技术栈默认：Python-first（当前机器无 Rust/C++ 工具链）；算子接口按可替换后端设计，性能瓶颈出现时逐算子换 Rust 后端（pyo3 接缝）。
> **2026-08-24 修订（ADR-0001）**：NURBS 数学核心（下表 P3 的曲线求值/求导/插值部分）已提前实施为首阶段 N1（`primitives/` + `operators/curve_eval|surface_eval|curve_interpolation` + 73 例 oracle 测试）；P1/P2 中一切 B-Rep 拓扑结构变异代码不由 AI 直接成文，改为规格先行 + 人审查分步实现或封装参考实现，AI 只承担其中可独立验证的叶子算法。

| 阶段 | 内容 | 交付物 | 验收线 |
|:--|:--|:--|:--|
| **P0 预言机地基** | 精确谓词（orient2d/3d、incircle/insphere 自适应浮点展开）、容差上下文、不变量检查器、鲁棒性平面 runner、静态检查器；**预言机变异自审** | 能对「已知错误实现」全量抓错的验证台 | 变异捕获率 100% |
| **P1 2D 垂直切片** | 草图实体（点/线/圆/弧/NURBS 曲线）、2D 布尔、约束求解器（牛顿法 + DOF 分析，SolveSpace 路线）、几何序列化 | 可脚本化参数草图，`sketch.json` 进出，Shapely 对拍 | 约束残差 < 1e-10，布尔对拍一致 |
| **P2 3D 网格 BRep** | 三角网格 BRep：精确谓词布尔（交线解析→三角剖分→分类）、水密/流形修复、质量属性 | `kernel.boolean` 全验证；STL/OBJ/3MF 导出 | 布尔差分对拍（manifold3d）体积一致 + Tier4 验收线 |
| **P3 NURBS 算子生长** | B 样条基函数/求值/导矢、NURBS 曲线面、插值/升阶/节点插入/分割、曲面求交（分阶段：平面-曲面 → 曲-曲） | 每算子独立证据链 | 同 x2strategy 的渐进规模：先曲线域，曲面求交按年级规划 |
| **P4 内核 API + STEP** | 算子库装配为公共 API；STEP（AP203/214）读写 | 可用的 `kernel` 包 + STEP 往返稳定性测试 | STEP 往返质量属性漂移 < 容差 |

**每个算子无论哪个阶段，都必须走完整 x2cad 流水线 + 四层证据。P0 是进入一切的前提。**

---

## 9. 目录结构（本项目根）

```
CAD/
├── CLAUDE.md                     # 项目路由（同构 Songkoro CLAUDE.md 的定位）
├── docs/plans/                   # 设计文档（本文件）与后续 ADR
├── x2cad/                        # agent 流水线（同构 paper2spec/spec2code）
│   ├── run.py                    # 一键：parse → extract → pitfall → codegen → verify
│   ├── ref2spec/                 # 解析 + 五层提取
│   ├── spec2op/                  # 模板代码生成 + 静态检查
│   ├── schemas/                  # operator_spec.schema.json 等
│   └── assets/                   # 算子模板
├── degeneracy/                   # 五族 pitfall 语料 + 索引
├── primitives/                   # 精确谓词、容差上下文、数值基元
├── operators/<slug>/             # 算子库（spec + impl + evidence）
├── kernel/                       # 公共 API（只装配已验证算子）
├── verify/                       # 四层验证台 + 变异自审
├── references/                   # 文献笔记、对拍实现使用说明
└── tests/                        # 单元/集成测试（pytest）
```

---

## 10. 开放决策（默认值已选，均可一句话回退）

| 决策 | 默认 | 备选 |
|:--|:--|:--|
| 项目位置 | `C:\Users\desha\Desktop\CAD`（独立仓库） | 迁入任意位置不影响内部路径 |
| 内核语言 | Python-first，Rust 接缝预留 | 全 Rust（需先装 rustup）|
| 阶段顺序 | **NURBS 数学核心先行（ADR-0001，已实施 N1）**；拓扑变异部分规格驱动 + 人工主导 | 回到 D(2D)→B(网格BRep)→C(NURBS) |
| LLM | 复用 x2strategy 的 DeepSeek key 约定 | litellm 支持任意模型 |
| 参考实现 | Shapely / manifold3d / trimesh / pythonocc-core | 纯自研真值 + 解析解 |
| AI 代码范围 | **只写纯数学叶子算法 + 可静态验证的脚手架**；拓扑变异/公共 API 装配走 HITL 闸门（ADR-0001） | — |

---

## 11. 首个里程碑（写完本文档即执行）

1. 初始化仓库结构 + `CLAUDE.md` 项目路由。
2. P0：精确谓词 + 容差上下文 + 不变量检查器（TDD，解析用例先行）。
3. P0：鲁棒性平面 runner + 静态检查器。
4. **预言机变异自审**（§7.4）—— 通过后才谈任何算子。
5. 写 `degeneracy/` 五族首批语料（每族 ≥ 3 条，带最小用例）。
6. 用 P1 第一个算子（线段-线段求交）端到端跑通整条 x2cad 流水线。

> **执行记录（2026-08-24，ADR-0001）**：里程碑 6 的「第一个算子」改为 NURBS 曲线
> 求值/求导/插值组（`operators/curve_eval|surface_eval|curve_interpolation`），
> 已以 pytest oracle（73 例全绿）先行落地——四层证据台（§6）中的 Tier 2（解析真值）
> 与差分对拍以测试形式就位，Tier 1/4 与变异自审仍待 P0 验证台补齐。

> **执行记录（2026-11-09，ADR-0002）**：P0 验证台与 N2 算子族落地。母文档此前只有设计的
> 部分，现在全部可运行、可复跑、有证据。测试总数 219 例全绿；`python -m verify` 门禁 PASS；
> 变异捕获率 9/9 = 100%。
>
> | P0 验证台 | 产物 | 证据 |
> |:--|:--|:--|
> | 精确谓词 | `primitives/predicates.py`：orient2d/orient3d/incircle/insphere，滤波 + Fraction 回退 | `tests/test_predicates.py`（含浮点滤波失效反例） |
> | 容差上下文 | `primitives/tolerance.py`：相对容差、三值比较、snap 平局拒绝 | `tests/test_tolerance.py` |
> | 求积基元 | `primitives/quadrature.py`：Gauss–Legendre（Newton 求根）+ 自适应二分 | `tests/test_curve_geometry.py` |
> | Tier 1 不变量 | `verify/invariants.py`：单位分解/导数零和/闭合流形/定向/Euler/退化三角形 | `tests/test_verify_core.py` |
> | Tier 2 真值 | `verify/analytic.py` + conformance 的 `close` 检查 | 各算子 oracle 测试 |
> | Tier 4 鲁棒性平面 | `verify/robustness.py`：四维扰动扫描 + CSV + 默认域通过率 | `test_arc_length_robustness_plane` |
> | 静态检查器 | `verify/static_check.py`：SC001–SC008 | `tests/test_verify_core.py` |
> | spec 校验 | `verify/spec_check.py` | 同上 |
> | conformance suite | `verify/conformance.py` + `verify/cases/*.json`（39 cases） | `tests/test_verify_core.py` |
> | **变异自审** | `verify/mutation.py` + 9 个变异 | 9/9 全捕获，`verify/audit/mutation_report.json` |
>
> | 退化语料（里程碑 5） | 产物 |
> |:--|:--|
> | 五族知识库 | `degeneracy/index.json`（15 条，每族 3 条）+ `README.md`；每条指向真实可执行用例（零死链） |
>
> | N2 算子生长 | 产物 |
> |:--|:--|
> | 节点操作 | `knot_insertion`（Boehm，单次/重复，NURBS）、`curve_split`、`degree_elevation`（Bézier，含 NURBS） |
> | 曲线微分几何 | `curve_geometry`：自适应弧长、单位切矢、曲率（2D/3D，NURBS） |
> | 2D 圆角 | `fillet_2d`：相切圆弧（Pointer-CAD §4.5 酸测试的 2D 版） |
> | 引用契约 | `kernel/entity_ref.py` + `docs/specs/entity-ref-contract.md`（D1 落地） |
>
> **仍未做（显式缺口）**：Tier 3 差分对拍（本机缺 shapely/manifold3d/trimesh）；Tier 5
> 过程化重放（需 P1 sketch/extrude 链）；P1 约束求解器与 2D 布尔；P2 网格 B-Rep；3D
> fillet/chamfer；SSI。下一步按 ADR-0002 D6–D11 与 Pointer-CAD 文档 §7 推进。

> **执行记录（2026-11-16，ADR-0003）**：EntityRef 契约补上派生寻址，堵住"分裂/合并后
> 引用失效"的缺口。`RefMapping.split` 记录 1-to-N 谱系（不重编号父实体），`merge` 记录
> N-to-1 并把源实体重编号到合并结果，`DerivedRef`（序号/参数两种选择子）+ `resolve_derived`
> 做确定性局部寻址；参数口径为右连续（分裂点归右段、末端归最后一段）。新增 13 个契约
> 用例（该文件 26 例、全套 232 例通过），`docs/specs/entity-ref-contract.md` 升到 v0.2。
>
> 仍显式不做：拓扑变异本身（`split`/`merge` 只记录事实）；按距离自动选段（拒绝猜，
> 留给 P1 带几何信息的操作显式给出序号或参数）；Tier 5 重放 runner。

> **执行记录（2026-11-18，P1-A1）**：进入 P1。新增 `operators/line_line_intersection`：
> 2D 线段求交，输入浮点无损转 `Fraction` 后判定，返回 `none / point / overlap` 三分类；
> 共线重叠返回参数区间并保留反向对应，端点接触归 `point`，零长度线段 `DomainError`。
> 19 例 oracle（含 250 组与独立 Fraction 参考的差分对拍）、8 条 conformance、5 个新变异；
> 全套 251 例通过，门禁 PASS，变异捕获率 14/14。退化语料补 C-004 / S-004（共 17 条）。
>
> 下一步：P1-A2（直线-Bézier 求交，代数求根 + 区间裁剪）与 A3（Bézier-Bézier 细分 + Newton），
> 再进入 2D 布尔装配；Tier 3 外部对拍仍受本机依赖限制。

> **执行记录（2026-11-20，阶段 review 与修复）**：新增 `docs/reviews/2026-11-20-stage-review.md`，
> 明确"判据层/Harness 范式有价值、全功能内核落后两代且不追"的边界。修复两处 P1 内伤：
> ① 求交结果增加精确坐标 `point_exact` + `intersection_point_exact` + `point_on_segment_exact`，
> 用 `(1, 5/3)` 回归证明 float 交点回推不在原线段上（级联容差）；
> ② 新增 ADR-0004，收准 `EntityRef` 口径为"确定性重放 + 单步派生寻址"，参数化 TNP 单列阶段。
> 另补 `docs/specs/constraint-solver.md`（分支手性验收线）与 `docs/specs/analytic-primitives.md`
> （Segment×Arc / Arc×Arc 闭式矩阵），README 增补工业深水区非目标。254 例测试、15/15 变异、PASS。



