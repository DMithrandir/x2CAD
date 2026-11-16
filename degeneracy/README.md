# 退化知识库（degeneracy index）

> 版本 0.1.0 | 2026-11-09 | 机器可读索引：`index.json` | 校验：`tests/test_degeneracy.py`

母文档 §5 的落地：CAD 内核开发的真实成本 80% 在退化几何。本目录把"资深从业者的隐性
知识"变成**可检索、可测试、可注入**的显式语料——这是本项目价值密度最高的知识资产。

## 1. 五族

| 族 | 含义 | 典型触发 |
|:--|:--|:--|
| **T** | 相切 / 一阶接触 | 圆-圆相切、曲面一阶接触、切点附近条件数爆炸 |
| **C** | 共面 / 重合 | 共面面片、重合边、四点共面、共线边 |
| **S** | sliver / 退化单元 | 近零面积三角形、重复数据点、重数导致的光滑性不足 |
| **I** | 自交 / 非流形 | 缺面、翻面、一条边被 3 个面共享 |
| **N** | 数值抵消 / 条件数 | 浮点滤波漏判、近零速度被积函数、权重下溢 |

## 2. 条目 schema

```json
{
  "id": "N-001",
  "family": "N",
  "title": "浮点滤波漏判：定向谓词符号翻转",
  "triggers": ["cancellation", "floating point", "near-degenerate", "sign flip"],
  "scenario": "……为什么会发生、发生时症状是什么",
  "remediation": "……标准修复模式（EXACT / SNAP / PERTURB / SUBDIVIDE / FAIL）",
  "test": "tests/test_predicates.py::test_orient2d_float_filter_failure_is_caught",
  "operators": ["predicates"],
  "tags": ["predicate", "robustness"]
}
```

字段约束（由 `tests/test_degeneracy.py` 强制）：

- `id` 全局唯一，前缀必须等于 `family`；
- `triggers` 必须是非空、可编译、全小写的正则/关键词列表；
- `scenario` / `remediation` 非空；
- `test` 必须指向真实存在的测试文件与函数（**不允许死链**）；
- `operators` 非空，关联到实际算子 slug 或 `primitives`/`invariants` 等基础设施。

## 3. 怎么用

1. **ref2spec 的 L2/L4 注入**：LLM 提取出符号表与退化族后，用 `triggers` 做词法匹配
   （正则可直接用于 `re.search`），命中条目的 `remediation` 拼进 `degeneracy_context.md`；
2. **规格审查**：算子 `spec.json` 的 `degeneracy_branches` 若有条目未在语料中处置，
   升级为 `needs_human_review`；
3. **测试生成**：每条条目的 `test` 就是最小复现用例，新算子可以直接复用它们的构造。

## 4. 怎么加条目

1. 选定族（T/C/S/I/N），id 顺延；
2. 写 `scenario`（症状 + 根因）与 `remediation`（可执行的修复模式，不是"小心一点"）；
3. 在 `tests/` 或 `tests/test_degeneracy_cases.py` 里放一个**最小可执行用例**
   （能复现症状、或能证明修复生效），把节点路径填进 `test`；
4. 跑 `python -m pytest tests/test_degeneracy.py -q` 确认无死链、触发器可编译。

## 5. 当前覆盖

15 条（T×3、C×3、S×3、I×3、N×3），全部通过 schema 校验与死链检查。
`ref:` 标签（引用失效类 pitfall）按 ADR-0002 D5 暂记入既有族，语料足够后再裁决是否新增 R 族。
