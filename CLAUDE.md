# X2CAD 项目路由

用 harness + agent 渐进生长的 CAD 几何内核。母设计文档：`docs/plans/2026-08-20-x2cad-kernel-design.md`。
决策记录：`docs/adr/`（ADR-0001 范围纪律、ADR-0002 P0 验证台与算子契约、
ADR-0003 EntityRef 派生寻址、ADR-0004 确定性重放 ≠ TNP）。

## 硬性范围纪律（ADR-0001 / ADR-0002）

- **AI 只直接成文：纯数学叶子算法 + 可静态验证的脚手架**（基函数、求值、求导、
  插值、节点操作、谓词、求积、测试）。
- **B-Rep 拓扑结构变异代码不由 AI 硬写**：必须规格先行、分步小实现、人工审查，
  或封装参考实现（manifold3d/OCCT/Shapely）。
- **LLM 从不被信任直接做几何计算**（运行时数值全部在确定性代码里）；
  同样不被信任的还有「未经预言机裁决的几何代码」。任何算子的正确性唯一判据
  是 oracle 测试/证据，不是代码看起来对。
- 算子可以调用**另一个算子的公共函数**，但必须在 `spec.json` 的 `depends_on` 声明；
  私有符号跨算子 import 一律禁止（静态检查器 SC005/SC006 强制）。依赖必须无环。

## 常用命令

```pwsh
python -m pytest                  # 全部 oracle 测试（在仓库根执行）
python -m verify                  # 全量门禁：静态检查 + 覆盖率 + conformance（写证据）
python -m verify.mutation         # 预言机变异自审（捕获率必须 100%）
```

新增算子 = 四件套：`impl.py` + `spec.json` + oracle 测试 + `verify/cases/<slug>.json`。
缺任何一件，`python -m verify` 会失败。

## 布局

```
primitives/    数值基元：B 样条基函数、稠密求解、精确谓词（predicates.py）、
               容差上下文（tolerance.py）、Gauss 求积（quadrature.py）。禁止算子逻辑。
operators/     算子库，每算子独立目录：spec.json + impl.py
  curve_eval/            B 样条/NURBS 曲线求值、各阶导数（方法 A/B 双实现）
  surface_eval/          张量积曲面求值、偏导
  curve_interpolation/   全局插值（参数化 + 节点平均 + 求解 + 残差后置检查）
  knot_insertion/        Boehm 节点插入（单次/重复，含 NURBS）
  curve_split/           曲线在参数 u 处分割（依赖 knot_insertion）
  degree_elevation/      Bézier 升阶（单步/重复，含 NURBS）
  curve_geometry/        弧长（自适应求积）、单位切矢、曲率（依赖 curve_eval）
  fillet_2d/             二维圆角：两线段夹角处的相切圆弧
  line_line_intersection/ 2D 线段求交（精确有理数判定，共线重叠/端点接触分类）
  segment_arc_intersection/ 2D 线段-圆弧求交（判别式精确判号 + 弧段向量过滤）
kernel/        公共层（ADR-0001 装配层）：entity_ref.py = 实体引用契约（无拓扑变异）
verify/        验证台：invariants / analytic / robustness / static_check / spec_check /
               conformance（cases/）/ mutation（audit/）/ evidence/
degeneracy/    退化五族知识库：index.json（可检索语料）+ README（schema 与用法）
x2cad/         流水线脚手架：内容寻址产物缓存（cache.py）。ref2spec/spec2op 仍是设计。
tests/         oracle 测试：解析真值 / 独立参考实现 / 有限差分 / 不变量 四路对拍
docs/plans/    设计文档；docs/adr/ 决策记录；docs/specs/ 契约规范；docs/learning/ 学习路线
```

## 层间规则

- 算子只允许 import `primitives/`（+ 标准库 + 已声明依赖的算子公共函数）。
- 测试可以 import 任何层（跨算子端到端一致性检查放在测试层）。
- 非法输入一律 `DomainError`（primitives.bspline 导出），绝不静默产出错误结果。
- 几何量比较走 `primitives.tolerance.ToleranceContext`；符号判定走 `primitives.predicates`
  的精确谓词。两者不可互相替代（见 `primitives/tolerance.py` 模块文档）。

## 求导类算子的约定

- 基函数/曲线右连续；右端点取左极限；重数 s 节点处 > p-s 阶导返回右向单侧值（方法 A）
  或被方法 B 的光滑性前置拒绝。
- 有限差分 oracle 的 h 与容差已在测试中按节点间距定标，勿随意放宽断言；
  断言失败时先怀疑被测代码与测试构造，再怀疑容差。

## 验证台纪律

- 静态检查 0 findings、conformance 0 失败、变异捕获率 100% 是硬线；
- 变异审计会临时改写源码：**必须**禁用字节码写入并在恢复后清除 `.pyc`
  （否则 CPython 的 `(mtime, size)` 校验会复用变异后的字节码，详见 `verify/mutation.py`）；
- 断言失败时禁止为了变绿而放宽容差——先怀疑代码或测试构造（ADR-0001 修正记录）。
