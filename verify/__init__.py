"""X2CAD 验证台（P0）：不变量、解析真值、鲁棒性平面、静态检查、conformance、变异自审。

分层（设计文档 §6 的四层 + §7.4 的预言机自审）：

- ``invariants``   Tier 1：数学恒等式 / 拓扑不变量（算子自检与验证台共用同一实现）
- ``analytic``    Tier 2：解析真值与误差度量
- ``robustness``  Tier 4：四维扰动平面（刚体变换 × 尺度 × 位错 × 容差）
- ``static_check``     生成物的静态红线（吞异常/非确定性/裸浮点比较/未声明依赖）
- ``spec_check``      OperatorSpec 结构契约
- ``conformance``     声明式算子级回归套件（本目录 ``cases/``）
- ``mutation``        预言机变异自审：先证明验证台抓得住错，再信任它
"""

__all__ = ["invariants", "analytic", "robustness", "static_check", "spec_check", "conformance"]
