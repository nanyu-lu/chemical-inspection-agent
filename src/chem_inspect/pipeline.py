"""单帧判定流水线（核心业务）。

`judge_frame()` 是**纯业务函数**：输入图像字节 + 帧引用 + 点位上下文，输出 `HazardEvent`。
不读数据库、不依赖 FastAPI —— 这样才能：
- 用 Mock 客户端做单测
- 后期原样搬到阿里云 FC（handler 只包一层）
- 断网时由上层决定降级策略

流程：预处理 → 提示词 → 千炼 VL → 契约校验（失败重试 1 次）→ 规则裁决 → 证据裁剪 → 组装事件
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from . import imaging
from .contracts import (
    Detection,
    EngineInfo,
    FrameRef,
    HazardEvent,
    NetworkMode,
    UsageInfo,
    Verdict,
    VLJudgeOutput,
    new_event_id,
)
from .llm.base import LLMClient
from .llm.maas import MaasError
from .prompt import PROMPT_VERSION, build_judge_prompt, vl_categories
from .rules import RuleSet, decide, sop_ref_map
from .storage import LocalBlobStore

RETRY_HINT = "\n\n注意：只输出 JSON 本体，不要 markdown、不要任何解释。"


@dataclass
class JudgeOutcome:
    event: HazardEvent
    raw_text: str = ""
    ok: bool = True
    error: str | None = None


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def parse_judge_output(text: str) -> VLJudgeOutput:
    """严格解析模型输出；解析不出就抛异常，由上层降级为人工复核。"""
    data = json.loads(_strip_fence(text))
    return VLJudgeOutput.model_validate(data)


def _save_evidence(
    store: LocalBlobStore,
    frame_ref: FrameRef,
    event_id: str,
    work: Any,
    work_bytes: bytes,
    bbox_px: list[float] | None,
    min_side: int,
) -> str:
    """证据图：优先裁剪，裁剪太小或无框则退化为整图（保证永不为空）。"""
    if bbox_px:
        crop = imaging.crop_evidence(work, bbox_px)
        if crop is not None and min(crop.size) >= min_side:
            return store.save_bytes(
                frame_ref.task_id,
                f"{event_id}_crop.jpg",
                imaging.to_jpeg(crop),
                sub="crops",
            )
    return store.save_bytes(
        frame_ref.task_id, f"{event_id}_full.jpg", work_bytes, sub="crops"
    )


def judge_frame(
    image_bytes: bytes,
    *,
    frame_ref: FrameRef,
    point: dict[str, Any] | None,
    client: LLMClient,
    rules: RuleSet,
    taxonomy: dict[str, Any],
    store: LocalBlobStore,
    model: str,
    network_mode: NetworkMode = NetworkMode.ONLINE,
    long_side: int = imaging.DEFAULT_LONG_SIDE,
) -> JudgeOutcome:
    img = imaging.load_image(image_bytes)
    work = imaging.resize_long_side(img, long_side)
    work_bytes = imaging.to_jpeg(work)

    prompt = build_judge_prompt(vl_categories(taxonomy), point=point)
    refs, names = sop_ref_map(taxonomy)
    event_id = new_event_id()

    res = None
    failure: str | None = None
    try:
        res = client.chat_vision(work_bytes, prompt, model=model, json_mode=True)
    except MaasError as exc:
        failure = f"模型调用失败：{exc}"

    parsed: VLJudgeOutput | None = None
    if res is not None:
        try:
            parsed = parse_judge_output(res.text)
        except (json.JSONDecodeError, ValidationError) as exc:
            failure = f"输出解析失败：{exc}"
            try:
                retry = client.chat_vision(
                    work_bytes, prompt + RETRY_HINT, model=model, json_mode=True
                )
            except MaasError as exc2:
                failure = f"重试仍失败：{exc2}"
            else:
                res = retry
                try:
                    parsed = parse_judge_output(retry.text)
                    failure = None
                except (json.JSONDecodeError, ValidationError) as exc3:
                    failure = f"重试后仍无法解析：{exc3}"

    if res is None or parsed is None:
        evidence = _save_evidence(store, frame_ref, event_id, work, work_bytes, None, 0)
        verdict = Verdict(
            is_hazard=False,
            confidence=0.0,
            reason=f"AI 服务不可用（{failure}），请人工判定",
            evidence_crop_uri=evidence,
            need_manual_review=True,
        )
        event = HazardEvent(
            event_id=event_id,
            frame_ref=frame_ref,
            verdict=verdict,
            engine=EngineInfo(
                model_id=model,
                prompt_version=PROMPT_VERSION,
                rule_version=rules.version,
                degraded=True,
                network_mode=network_mode,
            ),
            usage=UsageInfo(latency_ms=res.latency_ms if res else 0),
        )
        return JudgeOutcome(event=event, raw_text=res.text if res else "", ok=False, error=failure)

    decision = decide(
        rules, parsed.detections, parsed.other_observations, sop_refs=refs, names=names
    )

    bbox_px: list[float] | None = None
    if decision.hazard_type:
        for det in parsed.detections:
            if det.present and det.hazard_type == decision.hazard_type and det.bbox:
                bbox_px = Detection(
                    hazard_type=det.hazard_type,
                    score=det.confidence,
                    bbox=det.bbox,
                    bbox_space="norm1000",
                ).to_pixel_bbox(*work.size)
                break

    evidence_uri = _save_evidence(
        store, frame_ref, event_id, work, work_bytes, bbox_px, rules.crop_min_side_px
    )

    detections = [
        Detection(
            hazard_type=det.hazard_type,
            score=det.confidence,
            bbox=det.bbox,
            source="vl",
            bbox_space="norm1000",
        )
        for det in parsed.detections
        if det.present
    ]

    verdict = Verdict(
        is_hazard=decision.is_hazard,
        hazard_type=decision.hazard_type,
        level=decision.level,
        confidence=decision.confidence,
        reason=decision.reason,
        sop_ref=decision.sop_ref,
        action=decision.action,
        evidence_crop_uri=evidence_uri,
        need_manual_review=decision.need_manual_review,
        other_observations=parsed.other_observations,
    )
    event = HazardEvent(
        event_id=event_id,
        frame_ref=frame_ref,
        verdict=verdict,
        engine=EngineInfo(
            model_id=res.model or model,
            prompt_version=PROMPT_VERSION,
            rule_version=rules.version,
            degraded=False,
            network_mode=network_mode,
        ),
        detections=detections,
        usage=UsageInfo(
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
            latency_ms=res.latency_ms,
        ),
    )
    return JudgeOutcome(event=event, raw_text=res.text, ok=True)


__all__ = ["JudgeOutcome", "judge_frame", "parse_judge_output"]

