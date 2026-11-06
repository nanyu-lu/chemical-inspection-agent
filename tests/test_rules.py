"""规则裁决测试：等级/条款/复核判定只能来自规则表。"""

from __future__ import annotations

from pathlib import Path

from chem_inspect.contracts import VLCheckItem
from chem_inspect.prompt import load_taxonomy
from chem_inspect.rules import RuleSet, decide, sop_ref_map

RULES = RuleSet.from_yaml(Path("config/hazard_rules.yaml"))
TAXONOMY = load_taxonomy(Path("config/hazard_taxonomy.yaml"))
REFS, NAMES = sop_ref_map(TAXONOMY)


def _det(hazard_type: str, conf: float, present: bool = True) -> VLCheckItem:
    return VLCheckItem(
        hazard_type=hazard_type, present=present, confidence=conf, bbox=None, evidence="测试证据"
    )


def test_below_drop_threshold_is_not_hazard() -> None:
    decision = decide(
        RULES, [_det("HZ-06", 0.2)], "", sop_refs=REFS, names=NAMES
    )
    assert decision.is_hazard is False
    assert decision.hazard_type is None


def test_mid_confidence_is_hazard_and_needs_review() -> None:
    decision = decide(RULES, [_det("HZ-06", 0.6)], "", sop_refs=REFS, names=NAMES)
    assert decision.is_hazard is True
    assert decision.need_manual_review is True
    assert decision.level == RULES.levels["HZ-06"]


def test_highest_confidence_wins() -> None:
    decision = decide(
        RULES,
        [_det("HZ-06", 0.7), _det("HZ-01", 0.95)],
        "",
        sop_refs=REFS,
        names=NAMES,
    )
    assert decision.hazard_type == "HZ-01"


def test_missing_sop_marks_review_not_drop() -> None:
    """条款未补齐时不能静默丢弃真实隐患（mark_review 策略）。"""
    decision = decide(RULES, [_det("HZ-06", 0.9)], "", sop_refs=REFS, names=NAMES)
    assert decision.is_hazard is True
    assert decision.missing_sop is True
    assert decision.need_manual_review is True
    assert decision.reason.startswith("[判据条款待专家确认]")


def test_no_detection_means_no_hazard() -> None:
    decision = decide(
        RULES, [_det("HZ-06", 0.1, present=False)], "无异常", sop_refs=REFS, names=NAMES
    )
    assert decision.is_hazard is False
    assert decision.need_manual_review is False
    assert "无异常" in decision.reason
