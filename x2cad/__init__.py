"""x2cad 流水线（母设计文档 §4/§9）。

当前只有脚手架：内容寻址产物缓存。ref2spec / spec2op / schemas 仍只是设计。
"""

from x2cad.cache import ArtifactCache, CacheError

__all__ = ["ArtifactCache", "CacheError"]
