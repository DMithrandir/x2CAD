# ADR-0002：P0 验证台落地、N2 算子族与 EntityRef 契约

- 状态：已接受
- 日期：2026-11-09
- 决策人：用户（"自主进入接下来全部探索"授权）+ 主会话（落地与记录）
- 关联：`docs/plans/2026-08-20-x2cad-kernel-design.md` §5/§6/§7.4；
  `docs/plans/2026-09-16-pointer-cad-reference.md` D1–D5；
  `docs/adr/0001-nurbs-first.md`；`docs/specs/cad-operator-conformance.md`；
  `docs/specs/entity-ref-contract.md`

## 背景

N1（曲线求值/求导/插值）之后，项目停在"三个数学算子 + 73 个测试"的状态。母文档 §11 的
里程碑 4（预言机变异自审）与 §6 的验证台仍只有设计；Pointer-CAD 文档的 D1–D5 待裁决；
N2 节点操作、2D 圆角、EntityRef 契约、退化语料库均未落地。

本次在 ADR-0001 的边界内（AI 只写纯数学叶子算法 + 可静态验证的脚手架）推进了一轮，
并把所有"此前只有设计的东西"变成可运行、可复跑、有证据的代码。本 ADR 记录裁决与新增规则。

## 决策

### D1–D5（Pointer-CAD 文档）——全部按默认建议接受

| 决策 | 结果 |
|:--|:--|
| D1 现在建 EntityRef 契约 | **是**。已实现 `kernel/entity_ref.py`（数据结构 + 规则），拓扑变异仍走 ADR-0001 通道 |
| D2 spec schema 升级 | **是**，但以增量字段落地：`depends_on`、`unhandled` 为可选键，旧 spec 原地兼容；未引入显式版本号 |
| D3 Tier 5 单列证据层 | **接受方向，暂缓实现**：需要 P1 的 sketch/extrude 链；EntityRef 重放不变量已作为它的前半部分落地 |
| D4 fillet 优先级 | **2D 已实现**（`operators/fillet_2d`）；3D fillet/chamfer 仍只做规格，不实现 |
| D5 退化五族不扩族 | **是**。引用失效以 `ref:` 语义记入既有族，暂不新开 R 族 |

### D6 算子间依赖规则（新增）

ADR-0001 只规定"算子不得相互 import 实现细节"，但没有回答"高层算子能否复用低层算子"。
裁决：

- **允许**算子调用另一个算子在 `spec.json` 中声明的**公共**函数（`depends_on`）；
- **禁止** import 其它算子的私有符号（下划线开头）——静态检查器 SC005；
- **禁止**未声明的跨算子依赖——静态检查器 SC006；
- 依赖方向必须无环（当前：`curve_geometry → curve_eval`、`curve_split → knot_insertion`）。

理由：真实内核天然分层（弧长依赖求导、分割依赖节点插入），复制实现会制造两套口径，
比依赖更危险。把"依赖"变成显式、可检查的声明，比假装算子互不相干更诚实。

### D7 精确谓词策略（新增）

- `orient2d` / `orient3d` / `incircle` 用 Shewchuk 标准误差界做浮点滤波；
- 滤波失败时回退到 `fractions.Fraction` 精确重算（输入是浮点值，精确于该值）；
- `insphere` 用保守误差界 + Fraction 回退；
- **不**实现 Shewchuk 的自适应展开（性能优化留到 Rust/展开阶段）；当前优先正确性。

### D8 弧长求积策略（新增）

- 弧长按节点断点分段，段内用**自适应** Gauss–Legendre（比较整段与两半的估计）；
- 固定面板的 Gauss 结果**不得**作为证据——实测 `|C'|` 的近零极小值会让 8 点固定面板
  停在 1e-5 相对误差，且增加面板数收敛缓慢（`degeneracy/index.json` N-002 有 witness）；
- 求积器落在 `primitives/quadrature.py`（纯数学基元），算子只负责几何语义。

### D9 conformance 覆盖规则（新增）

- 每个带 `spec.json` 的算子**必须**有 `verify/cases/<slug>.json`；
- `python -m verify` 是全量门禁：静态检查 0 findings、覆盖率 0 缺口、conformance 0 失败；
- 新增算子必须同时提交 impl / spec / oracle 测试 / conformance cases 四件套。

### D10 变异自审是发布门槛（新增，落地母文档 §7.4）

- 变异集 `verify/audit/mutants.json` 的捕获率必须 100%；
- **实测教训**：变异必须禁用字节码写入并在恢复后清除对应 `.pyc`。变异前后源码常等长
  （`-`→`+`），若注入与恢复在同一整数秒内，CPython 的 `(mtime, size)` 校验会复用变异后的
  字节码——磁盘已恢复、行为仍坏。此坑已写入 `verify/mutation.py` 文档与回归断言。
- 修改核心数学路径（基函数/谓词/求积）时必须同步增加或更新变异。

### D11 文档即证据（新增）

- 每个落地批次更新母文档 §11 的"执行记录"，写清产物、测试数、**未做**什么；
- 验证台证据（`verify/evidence/report.json`、`verify/audit/mutation_report.json`）随代码提交，
  作为"这批代码当时确实通过了什么"的存档。

## 后果

**正面**

- 验证台从"设计"变成可运行门禁：静态检查、spec 校验、conformance、变异自审四道闸门齐全；
- N2 算子族落地 5 个（节点插入、分割、升阶、曲线微分几何、2D 圆角），全部带四路 oracle；
- 退化五族语料库 15 条，每条指向真实可执行用例（无死链），可被流水线按触发词检索；
- EntityRef 契约在 P1/P2 之前冻结，Pointer-CAD 指出的表示层风险已消除一半；
- 新增 2 个数值基元（精确谓词、Gauss 求积），后续所有几何量的 oracle 可复用。

**负面 / 风险**

- `verify/` 与 `kernel/` 引入了新的维护面；静态检查器可能误报，需要人工裁决白名单；
- 精确谓词的 Fraction 回退在病态输入上会慢（可接受：只在滤波失败时触发）；
- 变异自审让完整测试变慢（每个变异启动一个 pytest 子进程，约 30–60 秒）；
- Tier 3（差分对拍）与 Tier 5（过程化重放）仍未实现，`verify` 的"四层证据"目前是
  1/2/4 三层 + 变异自审，文档中已显式标注缺口，不假装完整。

**修正记录**

- 2026-11-09：首次实现 Boehm 插入时，按记忆写成 `α_i=(u−U_i)/(U_{i+p+1}−U_i)`，
  几何不变性 oracle 立刻判红（p=1 手工例给出 1.25 而非 1.5）。正确分母是
  `U_{i+p}−U_i`。该反例已固化为解析测试与变异项——**公式抄错由预言机裁决，不由记忆裁决**。
- 2026-11-09：变异自审首次出现"存活变异"（重数守卫），根因是守卫与后置
  `validate_knot_vector` 重复、测试只匹配宽泛消息。已把断言收紧到守卫自己的消息，
  说明"存活变异"既可能是 oracle 盲区，也可能是**测试写得不够具体**。
