# 算子级 conformance suite（白盒评测规范）

> 版本 0.2.0 | 2026-11-18 | 实现：`verify/conformance.py` + `verify/cases/*.json`
> 关联：`docs/plans/2026-08-20-x2cad-kernel-design.md` §6（四层证据）、§7.4（变异自审）

---

## 1. 为什么需要它

2026 年的 CAD 评测（CADTests、CADBench、BenchCAD、RealCADBench）全部是**黑盒**：
输入一个模型或一段文本，输出一个分数。它们回答"生成得像不像"，不回答**几何算子在
具体输入上是否守约**：容差语义、退化分支、端点行为、NURBS 与多项式的口径差异。

本套件是那个白盒缺口的第一个可运行实现：每个用例是一份 JSON，钉死一个算子在**具体
输入**上的可测行为；整套用例离线可复跑，并产出机器可读的证据报告。它的定位是
**回归钉 + 契约证明**，不是随机测试的替代品：

| 手段 | 回答的问题 | 本仓库位置 |
|:--|:--|:--|
| 单元/oracle 测试 | 实现对不对（解析真值、差分对拍、有限差分） | `tests/` |
| **conformance 用例** | 行为契约有没有变（跨版本回归） | `verify/cases/` |
| 鲁棒性平面（Tier 4） | 扰动下还能不能给出正确答案 | `verify/robustness.py` + 测试 |
| 变异自审（§7.4） | 验证台本身抓不抓得住错 | `verify/mutation.py` |

## 2. 目录布局

```
verify/
├── conformance.py          # 用例加载 / 执行 / 报告
├── cases/<operator>.json   # 每个算子一份用例文件，文件名 = operator
├── invariants.py           # Tier 1 检查器（算子自检与验证台共用）
├── analytic.py             # Tier 2 真值与误差度量
├── robustness.py           # Tier 4 四维扰动平面
├── static_check.py         # 静态红线（SC001–SC008）
├── spec_check.py           # OperatorSpec 结构契约
├── mutation.py             # 预言机变异自审
├── audit/mutants.json      # 变异集
├── audit/mutation_report.json   # 自审证据
├── evidence/report.json    # 最近一次 `python -m verify` 的证据
└── cases/                  # 用例
```

## 3. 用例格式

```json
{
  "operator": "curve_eval",
  "cases": [
    {
      "case_id": "curve_eval.point.quadratic_bezier_t025",
      "module": "operators.curve_eval.impl",
      "function": "curve_point",
      "args": [[0,0,0,1,1,1], 2, [[0,0],[1,1],[2,0]], 0.25],
      "checks": [{"kind": "close", "expected": [0.5, 0.375], "rel_tol": 1e-12}],
      "tags": ["analytic", "bezier"]
    }
  ]
}
```

约束（由 `load_cases` 强制，违反即 `ValueError`）：

- 文件名必须等于 `operator`；顶层必须是含 `cases` 的对象；
- `case_id` 全局唯一，建议 `operator.子域.断言` 命名；
- 每个 case 必须有 `case_id`、`module`、`function`、至少一个 `check`；
- `args` 是位置参数 JSON 数组，`kwargs` 可选；
- 输入必须是 JSON 可表示的字面量——**不允许表达式**（不引入 eval）。

## 4. 检查类型

| kind | 语义 | 字段 |
|:--|:--|:--|
| `close` | 与期望值比较：`|a−e| ≤ max(abs_tol, rel_tol·|e|)`，支持嵌套序列 | `expected`, `rel_tol`(默认 1e-9), `abs_tol`(默认 1e-12) |
| `exact` | 严格相等；序列逐元素；tuple 与 list 视为同构 | `expected` |
| `raises` | 期望抛异常 | `exception`（默认 `DomainError`）, `match`（消息子串） |

设计边界：`close` 的容差是**用例自己声明的**，不是全局默认——每个用例都能独立回答
"这个算子在这一点上承诺的精度是多少"。

## 5. 覆盖规则

- `check_coverage()`：每个带 `spec.json` 的算子目录**必须**有同名用例文件；
- `python -m verify` 把覆盖率缺口视为失败；
- 新增算子时，PR 必须同时包含：`impl.py`、`spec.json`、`tests/test_*.py`、`verify/cases/<slug>.json`。

## 6. 运行与证据

```pwsh
python -m pytest tests/test_verify_core.py -q   # 套件自测（含覆盖率）
python -m verify                                # 全量门禁：静态 + 覆盖率 + conformance
python -m verify.mutation                       # 预言机变异自审
```

`python -m verify` 写出 `verify/evidence/report.json`：

```json
{
  "generated_at": "...",
  "static": {"findings": 0, "details": []},
  "coverage": {"missing_operators": []},
  "conformance": {"cases": 47, "cases_passed": 47, "checks": 47, "checks_passed": 47, "by_operator": {...}},
  "failures": []
}
```

退出码 0 = 全绿，1 = 有问题（CI 可直接使用）。

## 7. 验收线（当前）

| 项 | 线 | 现状 |
|:--|:--|:--|
| 静态检查问题 | 0 | 0 |
| 覆盖率缺口 | 0 | 0（9 个算子全有 cases） |
| conformance 失败 | 0 | 0（47 cases / 47 checks） |
| 变异捕获率 | 100% | 15/15 = 100% |
| 默认域鲁棒性通过率 | 100% | 已对四分之一圆弧长验证（Tier 4 测试） |

## 8. 已知限制

1. **Tier 3 差分对拍未启用**：本机缺 `shapely` / `manifold3d` / `trimesh`，
   `verify` 中与参考实现对拍的一层留待依赖安装后接入（Tier 2 解析真值已覆盖现有算子）。
   接入口径见 §10：**Shapely 只对折线**，精确曲线走解析构造 + 区间算术。
2. **用例是点值钉**，不做参数化；参数扫描留在 pytest。
3. **未覆盖 Tier 5 过程化重放**：需要 P1 的 sketch/extrude 算子链；EntityRef 契约
   （`kernel/entity_ref.py`）已先行落地，为重放提供引用基础。
4. **不评测 AI 生成**：本套件评的是确定性算子。对 LLM 生成物，它只能作为"下游验收器"，
   不构成生成能力评测。

## 9. 下一步（对外发布路线）

1. 把 `cases/` 扩成算子族矩阵（曲线 → 曲面 → 2D 布尔 → 网格布尔），每族固定
   "basic / degenerate / nurbs" 三类用例；
2. 每个 case 绑定退化族标签（`T/C/S/I/N`），让通过率可以按族聚合；
3. 与 `degeneracy/index.json` 打通：语料条目引用 case_id，case 反查 pitfall；
4. 对拍引擎以可选依赖注入，缺依赖时跳过并标注（而非静默全绿）。

## 10. Tier 3 接入口径（预定规则，接入前即生效）

Tier 3 是"与独立参考实现对拍"。参考实现各有几何口径，接错对拍会产出**假一致**
或**假分歧**，比没有对拍更危险。接入时必须按几何类型分层：

| 几何 | 对拍基准 | 口径 |
|:--|:--|:--|
| 折线/多边形布尔（2D） | Shapely（GEOS） | 全量拓扑对拍：集合往返、面积/周长、点包含（Point-in-Region） |
| 精确曲线（圆弧/NURBS/自由曲线，2D） | Shapely **不适用**（GEOS 只支持线性几何） | 解析构造法（Manufactured Solutions：已知精确代数交点的合成曲线对）+ 区间算术包络；离散化只用于宏观面积/点包含抽样 |
| 网格布尔（3D） | manifold3d / trimesh | 体积、表面积、Euler 特征、流形性；引用语义不入对拍 |

硬规则：

1. **禁止**把离散化后的折线喂给 Shapely 当作"曲线布尔真值"：相切、微重叠、极小交角
   三种输入下，折线近似会改变拓扑连通性（伪交点/吞真交点），对拍结论随之反转；
2. 缺依赖时该层**显式 skip 并在证据里标注**（`status: "skipped"`），不得静默全绿——
   与静态检查"0 findings 才是通过"同一条纪律；
3. 对拍不一致时先怀疑参考实现的口径（例如 GEOS `overlay` 对自交输入的行为），
   再怀疑被测代码；判定依据必须写进用例或测试注释，供后续审计。

