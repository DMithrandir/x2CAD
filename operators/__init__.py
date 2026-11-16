"""算子层（设计文档 §3.1）：每个几何算子独立目录（spec + impl + evidence）。

算子之间不得相互 import 实现细节；公共依赖只允许 primitives/。
"""
