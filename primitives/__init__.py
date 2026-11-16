"""数值基元层（设计文档 §3.1）：精确谓词、容差上下文、基函数、线性代数。

本层禁止任何算子业务逻辑。
"""

from .bspline import (
    DomainError,
    basis_function_ders,
    basis_functions,
    find_span,
    greville_abscissae,
    validate_knot_vector,
)
from .linalg import solve_dense

__all__ = [
    "DomainError",
    "validate_knot_vector",
    "find_span",
    "basis_functions",
    "basis_function_ders",
    "greville_abscissae",
    "solve_dense",
]
