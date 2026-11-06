"""模型客户端抽象（Port）。

业务代码只依赖本协议，不依赖任何厂商 SDK。
换供应商 / 换本地模型 / 断网降级，都只是换一个 Adapter。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class LLMResult:
    """一次模型调用的结果与计量信息。"""

    text: str
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    json_mode: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@runtime_checkable
class LLMClient(Protocol):
    def chat_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
    ) -> LLMResult: ...

    def chat_vision(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
        mime: str = "image/jpeg",
        image_url: str | None = None,
    ) -> LLMResult: ...


__all__ = ["LLMClient", "LLMResult"]
