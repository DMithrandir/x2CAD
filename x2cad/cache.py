"""内容寻址产物缓存：x2cad 流水线各层输出的持久化缓存（Phase 0 学习教材）。

定位（母设计文档 §4.1/§4.4 的 LLM 工程对应物）：

- 五层提取（L0→L4）串行执行，修复轮只改某一层——未变的层不应重算，更不应重复花钱
  调 LLM。本模块按「stage + 版本 + 输入」的内容哈希存产物，命中即跳过计算。
- 修复轮会重复发送稳定前缀（spec + degeneracy 上下文）——那是 prompt 前缀缓存的问题，
  由调用方组织 prompt 时解决；本模块解决**产物缓存**这一半。

关键设计（每条都是学习点，对应
``docs/learning/2026-09-16-llm-harness-engineering.md``）：

1. ``key = sha256(规范 JSON(stage, version, deps, inputs))``：deps 是外部依赖版本
   （算子模板版本、退化语料版本），inputs 是本次计算的输入。版本 bump → 整体失效。
   这是「缓存与失效规则成对出现」的纪律（同构于构建系统的指纹缓存）。
2. 规范 JSON：``sort_keys`` + 紧凑分隔符 + ``ensure_ascii=False``，保证键与字典
   键序无关（tests/test_cache.py 有测试钉死）。
3. 原子写：先写临时文件再 ``os.replace``，崩溃不留下半截产物。
4. 完整性自检：载入时重算 payload 哈希，损坏即 ``CacheError``，绝不静默降级
   （与内核层「绝不静默产出错误结果」同一条纪律）。
5. 无全局状态：缓存实例持根目录；命中/未命中统计挂在实例上，供学习时打印命中率。

本模块是纯脚手架：不调任何 LLM、无 IO 之外的副作用。「同一输入第二次 0 次 API 调用」
由测试里的计数函数证明。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

__all__ = ["CacheError", "ArtifactCache"]


class CacheError(Exception):
    """缓存契约/完整性违规：非法 stage、输入不可序列化、产物为 None、载入损坏文件。

    与 primitives.bspline.DomainError 同一哲学：违规即显式报错，不静默降级。
    """


def _canonical(obj: Any) -> str:
    """规范 JSON 序列化：键序无关、紧凑分隔符。不可序列化输入 → CacheError。"""
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CacheError(f"缓存输入必须是 JSON 可序列化数据：{exc}") from exc


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactCache:
    """按内容寻址的产物缓存，根目录下每条目一个 ``<key>.json``。

    契约：
    - ``stage`` 不得含路径分隔符（防路径逃逸）；
    - ``inputs`` 与 ``payload`` 必须是 JSON 可序列化数据（NaN/Inf 不建议——JSON
      无标准表示，宁可先规整为字符串）；
    - ``payload`` 不得为 None（None 保留给「未命中」语义）。
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits: int = 0
        self.misses: int = 0

    def key(
        self, stage: str, version: str, inputs: Any, deps: Optional[Dict[str, str]] = None
    ) -> str:
        if not stage or "/" in stage or "\\" in stage:
            raise CacheError(f"stage 名不得为空且不得含路径分隔符：{stage!r}")
        envelope = {"stage": stage, "version": version, "deps": deps or {}, "inputs": inputs}
        return _sha256(_canonical(envelope))

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def load(
        self, stage: str, version: str, inputs: Any, deps: Optional[Dict[str, str]] = None
    ) -> Optional[Any]:
        """命中返回产物；未命中返回 None；文件损坏/结构非法抛 CacheError。"""
        key = self.key(stage, version, inputs, deps)
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            if blob["key"] != key or blob["stage"] != stage:
                raise CacheError(f"缓存元数据与请求不匹配：{path}")
            if _sha256(_canonical(blob["payload"])) != blob["payload_hash"]:
                raise CacheError(f"缓存产物损坏（payload 哈希不匹配）：{path}")
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise CacheError(f"缓存文件不可读或结构非法：{path}（{exc}）") from exc
        self.hits += 1
        return blob["payload"]

    def store(
        self,
        stage: str,
        version: str,
        inputs: Any,
        payload: Any,
        deps: Optional[Dict[str, str]] = None,
    ) -> None:
        if payload is None:
            raise CacheError("产物不得为 None（None 保留给未命中语义）")
        key = self.key(stage, version, inputs, deps)
        blob = {
            "key": key,
            "stage": stage,
            "version": version,
            "created_at": time.time(),
            "payload_hash": _sha256(_canonical(payload)),
            "payload": payload,
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(blob, f, sort_keys=True, ensure_ascii=False)
            os.replace(tmp, self._path(key))  # 原子落盘：崩溃不留半截产物
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get_or_compute(
        self,
        stage: str,
        version: str,
        inputs: Any,
        compute: Callable[[], Any],
        deps: Optional[Dict[str, str]] = None,
    ) -> Any:
        """命中即返回缓存；未命中才调用 compute() 并落盘。

        compute 应是无副作用的纯函数（本仓库全局纪律）；它抛异常时缓存不落盘，
        下次调用会重试。
        """
        hit = self.load(stage, version, inputs, deps)
        if hit is not None:
            return hit
        payload = compute()
        self.store(stage, version, inputs, payload, deps)
        return payload
