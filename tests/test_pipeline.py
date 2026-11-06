"""流水线测试：不联网，用 Mock 客户端覆盖正常/降级/解析失败三条路径。"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from chem_inspect.contracts import FrameRef
from chem_inspect.llm.mock import MockClient
from chem_inspect.pipeline import judge_frame, parse_judge_output
from chem_inspect.prompt import load_taxonomy
from chem_inspect.rules import RuleSet
from chem_inspect.storage import LocalBlobStore

RULES = RuleSet.from_yaml(Path("config/hazard_rules.yaml"))
TAXONOMY = load_taxonomy(Path("config/hazard_taxonomy.yaml"))


def _image_bytes() -> bytes:
    img = Image.new("RGB", (240, 180), (180, 180, 180))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _ref() -> FrameRef:
    return FrameRef(
        task_id="T-1",
        point_id="WH-A-03",
        captured_at=datetime.now(UTC),
        frame_uri="local://raw/T-1/a.jpg",
    )


def _run(tmp_path: Path, client: MockClient):
    return judge_frame(
        _image_bytes(),
        frame_ref=_ref(),
        point={"id": "WH-A-03", "name": "3号库房东侧消防通道", "facilities": ["灭火器 x2"]},
        client=client,
        rules=RULES,
        taxonomy=TAXONOMY,
        store=LocalBlobStore(tmp_path / "blobs"),
        model="mock-vl",
    )


def test_judge_success(tmp_path: Path) -> None:
    outcome = _run(tmp_path, MockClient())
    assert outcome.ok is True
    verdict = outcome.event.verdict
    assert verdict.hazard_type == "HZ-06"
    assert verdict.is_hazard is True
    assert verdict.need_manual_review is True
    assert verdict.evidence_crop_uri is not None
    assert verdict.evidence_crop_uri.startswith("local://crops/")
    # 模型给的是 0~1000 相对坐标，必须原样保留并标明坐标系
    assert outcome.event.detections[0].bbox_space == "norm1000"
    assert outcome.event.engine.degraded is False


def test_evidence_file_actually_written(tmp_path: Path) -> None:
    outcome = _run(tmp_path, MockClient())
    store = LocalBlobStore(tmp_path / "blobs")
    path = store.resolve(outcome.event.verdict.evidence_crop_uri or "")
    assert path.exists() and path.stat().st_size > 0


def test_degraded_when_api_fails(tmp_path: Path) -> None:
    outcome = _run(tmp_path, MockClient(fail_vision_times=5))
    assert outcome.ok is False
    assert outcome.event.engine.degraded is True
    assert outcome.event.verdict.is_hazard is False
    assert outcome.event.verdict.need_manual_review is True
    assert "AI 服务不可用" in outcome.event.verdict.reason
    assert outcome.event.verdict.evidence_crop_uri is not None


def test_unparsable_output_degrades(tmp_path: Path) -> None:
    outcome = _run(tmp_path, MockClient(vision_json="抱歉，我无法判断这张图。"))
    assert outcome.ok is False
    assert outcome.event.engine.degraded is True
    assert "无法解析" in (outcome.error or "")


def test_parse_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        parse_judge_output('{"detections":[],"other_observations":"","extra":1}')


def test_parse_accepts_code_fence() -> None:
    out = parse_judge_output('```json\n{"detections":[],"other_observations":"ok"}\n```')
    assert out.other_observations == "ok"
