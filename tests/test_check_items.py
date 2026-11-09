"""45 项试点：装载、提示词、单子项裁决、一帧多事件。"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from chem_inspect.check_items import build_sub_item_prompt, load_pilot_check_items
from chem_inspect.contracts import FrameRef, SubItemVerdict
from chem_inspect.llm.mock import MockClient
from chem_inspect.pipeline import (
    judge_frame_multi,
    parse_sub_item_output,
)
from chem_inspect.prompt import load_taxonomy
from chem_inspect.rules import RuleSet, decide_sub_item
from chem_inspect.storage import LocalBlobStore

RULES = RuleSet.from_yaml(Path("config/hazard_rules.yaml"))
TAXONOMY = load_taxonomy(Path("config/hazard_taxonomy.yaml"))
PILOT = load_pilot_check_items(Path("config"))


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


def test_load_pilot() -> None:
    assert PILOT is not None
    assert PILOT.enabled is True
    assert len(PILOT.specs) == 9
    assert PILOT.item_count() == 2
    assert PILOT.max_calls_per_frame == 9
    assert {s.item_code for s in PILOT.specs} == {"CI-06", "CI-11"}
    assert {s.sub_code for s in PILOT.specs} == {
        "6.11", "6.13", "6.9", "11.1", "11.3", "11.4", "11.6", "11.7", "11.8"
    }


def test_prompt_contains_criteria_and_no_site_claim() -> None:
    spec = PILOT.specs[0]
    prompt = build_sub_item_prompt(spec)
    assert spec.criteria in prompt
    assert "不要把标注当判据" in prompt
    assert "现场巡检实拍图" not in prompt


def _decision(output: SubItemVerdict):
    spec = PILOT.specs[0]
    return decide_sub_item(
        RULES,
        output,
        item_code=spec.item_code,
        item_name=spec.item_name,
        sub_code=spec.sub_code,
        sub_name=spec.sub_name,
        detection_mode=spec.detection_mode,
    )


def test_decide_positive() -> None:
    decision = _decision(
        SubItemVerdict(present=True, confidence=0.92, evidence="螺栓孔空置", bbox=[1, 2, 3, 4])
    )
    assert decision.is_hazard is True
    assert decision.hazard_type == "CI-06/6.11"
    assert decision.check_item_code == "CI-06"
    assert decision.sub_item_code == "6.11"
    assert decision.need_manual_review is True
    assert "判据条款待专家确认" in decision.reason


def test_decide_undecidable() -> None:
    decision = _decision(
        SubItemVerdict(present=False, confidence=0.2, undecidable=True, reason="图像模糊")
    )
    assert decision.is_hazard is False
    assert decision.need_manual_review is True
    assert decision.reason.startswith("[不可判定]")


def test_decide_negative() -> None:
    decision = _decision(
        SubItemVerdict(present=False, confidence=0.2, evidence="画面清晰，未发现缺陷")
    )
    assert decision.is_hazard is False
    assert decision.need_manual_review is False


def test_parse_sub_item_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        parse_sub_item_output(
            '{"present": false, "confidence": 0.1, "extra": 1}'
        )


def test_multi_returns_nine_events(tmp_path: Path) -> None:
    outcomes = judge_frame_multi(
        _image_bytes(),
        frame_ref=_ref(),
        point=None,
        client=MockClient(),
        rules=RULES,
        taxonomy=TAXONOMY,
        store=LocalBlobStore(tmp_path / "blobs"),
        model="mock-vl",
        check_items=PILOT,
    )
    assert len(outcomes) == 9
    assert all(o.ok for o in outcomes)
    assert {o.event.verdict.sub_item_code for o in outcomes} == {
        "6.11", "6.13", "6.9", "11.1", "11.3", "11.4", "11.6", "11.7", "11.8"
    }
    assert all(o.event.verdict.evidence_crop_uri for o in outcomes)
    assert all(o.event.engine.prompt_version == PILOT.prompt_version for o in outcomes)


def test_multi_falls_back_to_legacy(tmp_path: Path) -> None:
    outcomes = judge_frame_multi(
        _image_bytes(),
        frame_ref=_ref(),
        point=None,
        client=MockClient(),
        rules=RULES,
        taxonomy=TAXONOMY,
        store=LocalBlobStore(tmp_path / "blobs"),
        model="mock-vl",
        check_items=None,
    )
    assert len(outcomes) == 1
    assert outcomes[0].event.verdict.hazard_type == "HZ-06"
