"""千炼（MaaS 网关，OpenAI 兼容）客户端。

只做两件事：把请求发出去、把响应与计量信息带回来。
不做业务判断（阈值、判级、证据裁剪都在 pipeline 层）。

设计要点
- 只依赖 httpx，不绑定厂商 SDK，便于内网替换 / 换成本地 vLLM
- base64 内联图片（MVP 无需对象存储）；也支持直接传公网 URL
- 429 / 5xx / 超时自动退避重试；重试耗尽抛 MaasError，由上层降级为人工复核
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from .base import LLMResult


class MaasError(RuntimeError):
    """千炼调用失败。上层据此决定降级策略，不允许把异常直接抛给用户。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def to_data_url(image: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


class MaasClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_s: int = 90,
        max_retries: int = 2,
        retry_delays: tuple[float, ...] = (1.0, 4.0),
    ) -> None:
        if not api_key:
            raise ValueError("MaasClient 需要 api_key")
        self._api_key = api_key.strip()
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._max_retries = max(0, max_retries)
        self._retry_delays = retry_delays

    # ------------------------------------------------------------------ 基础

    @property
    def base_url(self) -> str:
        return self._base

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> list[str]:
        try:
            resp = httpx.get(
                f"{self._base}/models", headers=self._headers(), timeout=self._timeout
            )
        except httpx.HTTPError as exc:  # 网络层失败
            raise MaasError(f"无法连接千炼网关: {exc}") from exc
        if resp.status_code != 200:
            raise MaasError(
                f"获取模型列表失败 HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:500],
            )
        payload = resp.json()
        return [m["id"] for m in payload.get("data", [])]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}{path}"
        last_error: MaasError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = httpx.post(
                    url, headers=self._headers(), json=payload, timeout=self._timeout
                )
            except httpx.HTTPError as exc:
                last_error = MaasError(f"网络异常: {exc}")
            else:
                if resp.status_code == 200:
                    return resp.json()
                body = resp.text[:1000]
                last_error = MaasError(
                    f"HTTP {resp.status_code}: {body}",
                    status_code=resp.status_code,
                    body=body,
                )
                # 4xx（除 429）不重试，避免白烧配额
                if resp.status_code != 429 and resp.status_code < 500:
                    raise last_error
            if attempt < self._max_retries:
                delay = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
                time.sleep(delay)
        assert last_error is not None
        raise last_error


    # ------------------------------------------------------------------ 对话

    def _chat(self, payload: dict[str, Any], *, started: float, json_mode: bool) -> LLMResult:
        data = self._post("/chat/completions", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        choices = data.get("choices") or []
        if not choices:
            raise MaasError(
                "响应中没有 choices", body=json.dumps(data, ensure_ascii=False)[:500]
            )

        message = choices[0].get("message") or {}
        text = _flatten_content(message.get("content"))

        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=data.get("model") or payload.get("model", ""),
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            json_mode=json_mode,
            raw=data,
        )

    def chat_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not model:
            raise ValueError("chat_text 需要 model")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        started = time.perf_counter()
        return self._chat(payload, started=started, json_mode=json_mode)

    def chat_vision(
        self,
        image: bytes,
        prompt: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
        mime: str = "image/jpeg",
        image_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not model:
            raise ValueError("chat_vision 需要 model")
        url = image_url or to_data_url(image, mime)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        started = time.perf_counter()
        return self._chat(payload, started=started, json_mode=json_mode)


def _flatten_content(content: Any) -> str:
    """兼容 content 为 str 或 [{type: text, text: ...}] 两种返回形态。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content)


__all__ = ["MaasClient", "MaasError", "to_data_url"]

