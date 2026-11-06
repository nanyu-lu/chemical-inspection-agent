"""契约测试：这些断言是跨阶段/跨部署环境的不变量，改动必须评审。"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from chem_inspect.contracts import (
    SCHEMA_VERSION,
    Detection,
    EngineInfo,
    HazardEvent,
    InspectionFrame,
    RejectReason,
    ReviewAction,
    Source,
    Verdict,
    VLJudgeOutput,
    new_event_id,
)


def _frame() -> InspectionFrame:
    return InspectionFrame(
        task_id="T-001",
        point_id="WH-A-03",
        captured_at="2026-11-06T09:12:33+08:00",
        frame_uri="local://data/blobs/WH-A-03/1.jpg",
        source=Source.IMAGE,
    )


def test_event_id_is_uuid7() -> None:
    eid = new_event_id()
    parsed = uuid.UUID(eid)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


def test_event_id_time_ordered() -> None:
    ids = [new_event_id() for _ in range(20)]
    assert ids == sorted(ids), "UUIDv7 必须随时间单调递增，断网补传依赖此顺序"


def test_inspection_frame_defaults() -> None:
    frame = _frame()
    assert frame.robot_id == "manual"
    assert frame.pose is None
    assert frame.source is Source.IMAGE


def test_hazard_event_roundtrip() -> None:
    event = HazardEvent(
        frame_ref={
            "task_id": "T-001",
            "point_id": "WH-A-03",
            "captured_at": "2026-11-06T09:12:33+08:00",
            "frame_uri": "local://1.jpg",
        },
        verdict=Verdict(
            is_hazard=True,
            hazard_type="HZ-06",
            level="较大隐患",
            confidence=0.88,
            reason="出口门前堆放纸箱",
            sop_ref="TODO",
            evidence_crop_uri="local://crop/1.jpg",
        ),
        engine=EngineInfo(model_id="qwen3-vl-plus", prompt_version="v1", rule_version="0.1.0"),
        detections=[Detection(hazard_type="HZ-06", score=0.88, bbox=[10, 20, 110, 220])],
    )
    assert event.schema_version == SCHEMA_VERSION
    assert event.status.value == "draft"
    assert event.verdict.need_manual_review is True, "合规要求：默认必须人工复核"

    restored = HazardEvent.model_validate_json(event.model_dump_json())
    assert restored.event_id == event.event_id


@pytest.mark.parametrize("bbox", [[1, 2, 3], [1, 2, 3, 4, 5]])
def test_bbox_must_be_four_numbers(bbox: list[float]) -> None:
    with pytest.raises(ValidationError):
        Detection(hazard_type="HZ-01", score=0.5, bbox=bbox)


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        Detection(hazard_type="HZ-01", score=1.2)


def test_reject_requires_reason() -> None:
    with pytest.raises(ValidationError):
        ReviewAction(event_id="E-1", action="reject")
    ok = ReviewAction(event_id="E-1", action="reject", reason_code=RejectReason.FALSE_POSITIVE)
    assert ok.reason_code is RejectReason.FALSE_POSITIVE


def test_confirm_does_not_require_reason() -> None:
    assert ReviewAction(event_id="E-1", action="confirm").reason_code is None


def test_vl_output_rejects_extra_fields() -> None:
    """模型多吐字段必须被拒收，否则幻觉会悄悄流进业务。"""
    with pytest.raises(ValidationError):
        VLJudgeOutput.model_validate(
            {"detections": [], "other_observations": "", "confidence_note": "x"}
        )


def test_norm1000_bbox_converted_to_pixels() -> None:
    """Qwen-VL 返回 0~1000 相对坐标（探针实测），必须换算成像素并在范围内裁剪。"""
    det = Detection(hazard_type="HZ-06", score=0.9, bbox=[624, 189, 867, 917], bbox_space="norm1000")
    box = det.to_pixel_bbox(960, 720)
    assert box is not None
    x1, y1, x2, y2 = box
    assert 0 <= x1 < x2 <= 960
    assert 0 <= y1 < y2 <= 720
    assert x1 == pytest.approx(599.04, abs=0.1)
    assert y2 == pytest.approx(660.24, abs=0.1)


def test_pixel_bbox_is_clamped() -> None:
    det = Detection(hazard_type="HZ-01", score=0.5, bbox=[-20, 10, 2000, 900])
    box = det.to_pixel_bbox(960, 720)
    assert box == [0.0, 10.0, 960.0, 720.0]

