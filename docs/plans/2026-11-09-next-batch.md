# 探索日志与下一批计划（2026-11-09）

> 状态：本批已完成；下一批待执行（自主探索模式，用户授权"自主进入接下来全部探索"）
> 关联：`docs/adr/0002-p0-verification-and-ref-contract.md`、母文档 §11 执行记录

---

## 1. 本批交付（已完成，可复跑）

| 类别 | 产物 | 验证 |
|:--|:--|:--|
| 数值基元 | 精确谓词（orient2d/3d、incircle/insphere）、容差上下文、Gauss 求积（含自适应） | `tests/test_predicates.py`、`test_tolerance.py`、`test_curve_geometry.py` |
| 验证台 | 不变量 / 解析真值 / 鲁棒性平面 / 静态检查（SC001–SC008）/ spec 校验 / conformance（39 cases）/ 变异自审（9/9） | `python -m verify` PASS；`verify/audit/mutation_report.json` |
| N2 算子 | `knot_insertion`、`curve_split`、`degree_elevation`、`curve_geometry`、`fillet_2d` | 各算子 oracle 测试 + conformance cases |
| 契约 | `kernel/entity_ref.py`（重放不变量、tombstone、类型安全、选择歧义） | `tests/test_entity_ref.py` |
| 退化语料 | 五族 15 条（T/C/S/I/N 各 3），每条指向真实用例 | `tests/test_degeneracy.py` |
| 文档 | ADR-0002、conformance 规范、EntityRef 契约、degeneracy README、CLAUDE.md/母文档/学习文档更新 | — |

**规模**：219 个测试全绿；8 个算子全部有 spec + impl + oracle 测试 + conformance 覆盖。

## 2. 已知缺口（显式记录，不假装完整）

1. **Tier 3 差分对拍**：本机缺 `shapely` / `manifold3d` / `trimesh`；`verify` 目前靠 Tier 2
   解析真值（现有算子都适用），对拍层留待依赖安装。
2. **Tier 5 过程化重放**：需要 P1 的 sketch/extrude 链；EntityRef 契约已就位。
3. **P1 尚未开始**：2D 草图实体、约束求解器、2D 布尔。
4. **3D 进阶**：fillet/chamfer 规格、SSI、网格 B-Rep 全在 P2+。

## 3. 下一批计划（按依赖序，每步可独立验收）

### P1-A：2D 图元与曲线求交（进入拓扑化几何的第一步）

| 步 | 内容 | oracle | 验收线 |
|:--|:--|:--|:--|
| A1 | `operators/line_line_intersection`：线段-线段求交，含平行/共线/端点接触 | 有理数精确判定（orient2d 符号）+ sympy 解析解 | 退化分类与参数值全部对拍；共线重叠区间的端点正确 |
| A2 | `operators/line_bezier_intersection`：直线与二次/三次 Bézier 求交 | 代数求根（sympy）+ 代入回代残差 | 根的个数、去重、区间裁剪（Bézier clipping）与残差 < 1e-12 |
| A3 | `operators/bezier_bezier_intersection`：细分 + 包围盒 + Newton 精修 | 细分自洽性 + 交点代入两条曲线残差 + sympy resultant | 横截/相切/重合三类用例；相切点不丢不重 |

### P1-B：2D 约束求解器（P1 的主心骨）

| 步 | 内容 | oracle | 验收线 |
|:--|:--|:--|:--|
| B1 | 约束模型：点、直线段、圆弧；距离/水平/垂直/平行/相切/同心/重合 | 构造即满足的配置（残差=0） | 残差 < 1e-10 |
| B2 | Newton 求解 + 阻尼 + DOF 分析（Jacobian 秩） | 已知 DOF 的草图（矩形=4、三角形=3、欠约束/过约束构造） | DOF 分类 100% 正确 |
| B3 | 奇异/不一致检测 + 显式 `DomainError` | 冗余约束、矛盾约束的构造用例 | 不静默给出"近似解" |
| B4 | `sketch.json` 指针脚本（EntityRef 驱动） | Tier 5 重放的前半部分 | 重放 id 一致 + 每条引用可解析 |

### P0-C：补齐验证台

1. 安装 `shapely`（可用 pip 时）后接入 Tier 3：2D 布尔/求交对拍 Shapely；
2. 把 `verify/evidence` 扩展为按算子分目录（`operators/<slug>/evidence/`），母文档 §6.5 的清单；
3. 变异集随新算子扩充（每个核心公式至少 1 个变异）。

## 4. 风险与待裁决

- **曲线求交的鲁棒性是年级问题**：先做解析可解的组合（线-线、线-Bézier），
  Bézier-Bézier 只承诺"横截 + 简单相切"，自交/重合曲线显式拒绝，不为通过率硬凑；
- **约束求解器的数值稳定性**：Newton + 阻尼可能在近奇异处失败，语义上应 `DomainError`
  而不是返回"最接近的解"——这需要一次 HITL 裁决（容差语义闸门）；
- **Tier 3 依赖**：若无法安装 shapely，则 2D 布尔只能用自研真值 + 解析解，覆盖面下降，
  需在证据中标注。
