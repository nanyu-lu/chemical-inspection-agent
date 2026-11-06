"""跨阶段稳定的数据契约（不变量）。

- 输入契约 ``InspectionFrame``：现场照片 / 视频帧 / 机器人相机 → 后端
- 输出契约 ``HazardEvent``：后端 → 看板 / 隐患单 / 下游系统
- 复核契约 ``ReviewAction``：人工确认或驳回（驳回必须给原因，用于数据回流）
- 模型输出契约 ``VLJudgeOutput`` / ``MeterReading``：校验模型返回，防幻觉

原则
1. 只允许**向后兼容**地新增可选字段；破坏性变更需递增 major 并同步前端与机器人侧。
2. 等级（level）与条款（sop_ref）**不得**来自模型输出，只来自 config 下的规则表。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def utcnow() -> datetime:
    """带时区的当前时间（契约里一律存 tz-aware，展示层再做本地化）。"""
    return datetime.now(UTC)


def new_event_id() -> str:
    """UUIDv7（进程内单调）：断网补传与乱序到达时，按 id 排序即等价按时间排序。

    128 位布局：48bit 毫秒时间戳 | 4bit 版本(0111) | 12bit rand_a(同毫秒计数器)
                | 2bit variant(10) | 62bit rand_b
    - 同一毫秒内用计数器自增保证严格递增（最多 4096 个/毫秒）
    - 检测到时钟回拨时，沿用上一个时间戳，避免 id 倒退
    """
    global _last_ms, _seq
    with _lock:
        ts_ms = int(time.time() * 1000)
        ts_ms = max(ts_ms, _last_ms)  # 时钟回拨保护：沿用上一个时间戳，避免 id 倒退
        if ts_ms == _last_ms:
            _seq += 1
            if _seq > 0xFFF:  # 同毫秒 4096 个用尽，借用下一毫秒
                ts_ms += 1
                _seq = 0
                _last_ms = ts_ms
        else:
            _seq = 0
            _last_ms = ts_ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ts_ms << 80) | (0x7 << 76) | (_seq << 64) | (0x2 << 62) | rand_b
    return str(uuid.UUID(int=value))



class Source(str, Enum):
    IMAGE = "image"
    VIDEO_FRAME = "video_frame"
    ROBOT_CAMERA = "robot_camera"


class NetworkMode(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    AIRGAP = "airgap"


class EventStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RejectReason(str, Enum):
    FALSE_POSITIVE = "false_positive"      # 误报：画面里没有该隐患
    NOT_HAZARD = "not_hazard"              # 有该现象但依标准不算隐患
    UNCLEAR = "unclear"                    # 看不清，无法判定
    WRONG_CATEGORY = "wrong_category"      # 类别判错
    ALREADY_HANDLED = "already_handled"    # 已整改/已闭环
    OTHER = "other"


# --------------------------------------------------------------------------- 输入契约


class Pose(BaseModel):
    """机器人位姿。MVP 允许为空，后期接机器人时填充，不改契约。"""

    x: float | None = None
    y: float | None = None
    z: float | None = None
    yaw: float | None = None


class InspectionFrame(BaseModel):
    """一帧待判定的巡检图像。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    point_id: str
    captured_at: datetime
    frame_uri: str
    source: Source = Source.IMAGE
    robot_id: str = "manual"
    route_id: str | None = None
    pose: Pose | None = None
    sha256: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- 输出契约


class FrameRef(BaseModel):
    task_id: str
    point_id: str
    captured_at: datetime
    frame_uri: str
    sha256: str | None = None


class Detection(BaseModel):
    """单个检测结果。

    ⚠️ 坐标系：Qwen-VL 系列返回的 bbox 是 **0~1000 归一化坐标**，不是像素。
    这里显式记录 ``bbox_space``，入库前必须调用 ``to_pixel_bbox`` 统一换算，
    否则证据裁剪会截错位置（探针实测 y2=917 超出 720 像素高的图像）。
    """

    hazard_type: str
    score: float = Field(ge=0.0, le=1.0)
    bbox: list[float] | None = None
    source: Literal["vl", "yolo", "ocr"] = "vl"
    bbox_space: Literal["pixel", "norm1000"] = "pixel"

    @field_validator("bbox")
    @classmethod
    def _bbox_len(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and len(v) != 4:
            raise ValueError("bbox 必须是 [x1, y1, x2, y2] 四个数字")
        return v

    def to_pixel_bbox(self, width: int, height: int) -> list[float] | None:
        """换算并裁剪到图像范围内，返回像素坐标 [x1, y1, x2, y2]。"""
        if self.bbox is None:
            return None
        if self.bbox_space == "norm1000":
            x1, y1, x2, y2 = (float(v) / 1000.0 for v in self.bbox)
            box = [x1 * width, y1 * height, x2 * width, y2 * height]
        else:
            x1, y1, x2, y2 = (float(v) for v in self.bbox)
            box = [x1, y1, x2, y2]
        x1, x2 = sorted((max(0.0, min(box[0], width)), max(0.0, min(box[2], width))))
        y1, y2 = sorted((max(0.0, min(box[1], height)), max(0.0, min(box[3], height))))
        return [x1, y1, x2, y2]



class Verdict(BaseModel):
    """判定结论。level / sop_ref 由规则表填充，不来自模型。"""

    is_hazard: bool
    hazard_type: str | None = None
    level: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    sop_ref: str | None = None
    action: str | None = None          # 处置建议（由规则表给出，非模型生成）
    evidence_crop_uri: str | None = None
    need_manual_review: bool = True
    other_observations: str = ""


class EngineInfo(BaseModel):
    """可追溯信息：出问题时能回答「当时是哪一版模型/prompt/规则」。"""

    model_id: str
    prompt_version: str
    rule_version: str
    pipeline_version: str = "0.1.0"
    adapter: str = "maas"
    degraded: bool = False
    network_mode: NetworkMode = NetworkMode.ONLINE


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_cny: float | None = None


class HazardEvent(BaseModel):
    """一条隐患事件（append-only：业务字段不更新，状态变更走独立日志）。"""

    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(default_factory=new_event_id)
    schema_version: str = SCHEMA_VERSION
    frame_ref: FrameRef
    verdict: Verdict
    engine: EngineInfo
    detections: list[Detection] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    status: EventStatus = EventStatus.DRAFT
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- 复核契约


class ReviewAction(BaseModel):
    """人工复核动作。驳回必须给原因——这是模型迭代的唯一数据来源。"""

    event_id: str
    action: Literal["confirm", "reject"]
    reason_code: RejectReason | None = None
    note: str = ""
    reviewer: str = ""

    @model_validator(mode="after")
    def _reject_needs_reason(self) -> ReviewAction:
        if self.action == "reject" and self.reason_code is None:
            raise ValueError("驳回必须提供 reason_code")
        return self


# --------------------------------------------------------------------------- 模型输出契约


class VLCheckItem(BaseModel):
    """视觉模型对单个检查项的原始输出（严格校验，多字段直接拒收）。"""

    model_config = ConfigDict(extra="forbid")

    hazard_type: str
    present: bool
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[float] | None = None
    evidence: str = ""


class VLJudgeOutput(BaseModel):
    """视觉模型整体输出。解析失败一律降级为人工复核，不允许猜测补全。"""

    model_config = ConfigDict(extra="forbid")

    detections: list[VLCheckItem] = Field(default_factory=list)
    other_observations: str = ""


class MeterReading(BaseModel):
    """读表结果。只抽读数，超限判定由规则表 + 量程表完成。"""

    model_config = ConfigDict(extra="forbid")

    meter_id: str | None = None
    raw_text: str = ""
    value: float | None = None
    unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


__all__ = [
    "SCHEMA_VERSION",
    "Detection",
    "EngineInfo",
    "EventStatus",
    "FrameRef",
    "HazardEvent",
    "InspectionFrame",
    "MeterReading",
    "NetworkMode",
    "Pose",
    "RejectReason",
    "ReviewAction",
    "Source",
    "UsageInfo",
    "VLCheckItem",
    "VLJudgeOutput",
    "Verdict",
    "new_event_id",
    "utcnow",
]

