"""Mock 模型客户端。

用途：
1. 单测不依赖网络（CI/离线环境可跑）
2. 没有 API Key 时仍能演示完整链路（`NETWORK_MODE=offline` + Mock）
"""

from __future__ import annotations

import json

from .base import LLMResult
from .maas import MaasError

DEFAULT_SUB_ITEM_JSON = json.dumps(
    {
        "present": False,
        "confidence": 0.2,
        "evidence": "mock: 未发现该子项缺陷",
        "bbox": None,
        "undecidable": False,
        "reason": "mock",
    },
    ensure_ascii=False,
)

DEFAULT_VISION_JSON = json.dumps(
    {
        "detections": [
            {
                "hazard_type": "HZ-06",
                "present": True,
                "confidence": 0.91,
                "bbox": [600, 200, 900, 900],
                "evidence": "出口门前堆放纸箱，通行受阻",
            },
            {
                "hazard_type": "HZ-01",
                "present": False,
                "confidence": 0.1,
                "bbox": None,
                "evidence": "画面内无人员",
            },
        ],
        "other_observations": "",
    },
    ensure_ascii=False,
)


class MockClient:
    """按构造参数返回固定响应的假客户端。"""

    def __init__(
        self,
        vision_json: str = DEFAULT_VISION_JSON,
        *,
        sub_item_json: str = DEFAULT_SUB_ITEM_JSON,
        fail_vision_times: int = 0,
        model: str = "mock-vl",
        latency_ms: int = 42,
    ) -> None:
        self._vision_json = vision_json
        self._sub_item_json = sub_item_json
        self._remaining_failures = fail_vision_times
        self._model = model
        self._latency = latency_ms
        self.calls: list[str] = []

    def chat_text(self, prompt: str, *, model: str | None = None, json_mode: bool = False, **_: object) -> LLMResult:
        self.calls.append("text")
        return LLMResult(
            text='{"ok": true}',
            model=model or self._model,
            latency_ms=self._latency,
            prompt_tokens=10,
            completion_tokens=5,
            json_mode=json_mode,
        )

    def chat_vision(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
        **_: object,
    ) -> LLMResult:
        self.calls.append("vision")
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise MaasError("mock: upstream timeout", status_code=504)
        text = (
            self._sub_item_json
            if "只判断一个检查项" in prompt
            else self._vision_json
        )
        return LLMResult(
            text=text,
            model=model or self._model,
            latency_ms=self._latency,
            prompt_tokens=1000,
            completion_tokens=200,
            json_mode=json_mode,
        )


__all__ = ["DEFAULT_SUB_ITEM_JSON", "DEFAULT_VISION_JSON", "MockClient"]
