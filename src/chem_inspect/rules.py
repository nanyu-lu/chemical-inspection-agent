"""规则裁决层。

模型的职责只有「看见了什么 + 多大把握」；
等级、处置建议、条款依据、是否需要复核，全部由本层按 YAML 决定。

⚠️ D2 阶段的现实约束：企业判定标准原文尚未提供，`hazard_taxonomy.yaml` 里
`standard_ref` 仍为 null。此时按 `missing_sop_policy` 处理（默认 mark_review）：
事件仍然入库，但强制人工复核并标注「判据待专家确认」——而不是静默丢弃真实隐患。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .contracts import VLCheckItem

DEFAULT_RULES_PATH = Path("config/hazard_rules.yaml")


@dataclass(frozen=True)
class RuleSet:
    version: str
    conf_drop: float
    conf_review: float
    levels: dict[str, str] = field(default_factory=dict)
    actions: dict[str, str] = field(default_factory=dict)
    dedupe_enabled: bool = True
    dedupe_window_hours: int = 24
    require_evidence: bool = True
    require_sop_ref: bool = True
    missing_sop_policy: str = "mark_review"  # mark_review | block
    default_need_review: bool = True
    crop_min_side_px: int = 160

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_RULES_PATH) -> RuleSet:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        th = data.get("thresholds", {})
        de = data.get("decision", {})
        dd = data.get("dedupe", {})
        ev = data.get("evidence", {})
        return cls(
            version=str(data.get("version", "unknown")),
            conf_drop=float(th.get("conf_drop", 0.45)),
            conf_review=float(th.get("conf_review", 0.75)),
            levels=dict(data.get("levels") or {}),
            actions=dict(data.get("actions") or {}),
            dedupe_enabled=bool(dd.get("enabled", True)),
            dedupe_window_hours=int(dd.get("window_hours", 24)),
            require_evidence=bool(de.get("require_evidence", True)),
            require_sop_ref=bool(de.get("require_sop_ref", True)),
            missing_sop_policy=str(de.get("missing_sop_policy", "mark_review")),
            default_need_review=bool(de.get("default_need_review", True)),
            crop_min_side_px=int(ev.get("crop_min_side_px", 160)),
        )

    def level_for(self, hazard_type: str | None) -> str | None:
        return self.levels.get(hazard_type or "")

    def action_for(self, hazard_type: str | None) -> str | None:
        return self.actions.get(hazard_type or "")


@dataclass(frozen=True)
class Decision:
    is_hazard: bool
    hazard_type: str | None
    level: str | None
    confidence: float
    reason: str
    action: str | None = None
    sop_ref: str | None = None
    missing_sop: bool = False
    need_manual_review: bool = True


def decide(
    rules: RuleSet,
    detections: list[VLCheckItem],
    other_observations: str,
    *,
    sop_refs: dict[str, str | None],
    names: dict[str, str],
) -> Decision:
    """按阈值、等级表、条款表给出最终结论。"""
    candidates = [
        d for d in detections if d.present and d.confidence >= rules.conf_drop
    ]
    candidates.sort(key=lambda d: d.confidence, reverse=True)

    if not candidates:
        top = max((d.confidence for d in detections), default=0.0)
        reason = "在本点位检查项内未发现隐患"
        if other_observations:
            reason += f"；其他观察：{other_observations}"
        return Decision(
            is_hazard=False,
            hazard_type=None,
            level=None,
            confidence=top,
            reason=reason,
            need_manual_review=False,
        )

    best = candidates[0]
    hazard_type = best.hazard_type
    sop_ref = sop_refs.get(hazard_type)
    missing_sop = sop_ref is None
    level = rules.level_for(hazard_type)

    evidence_text = (best.evidence or "").strip() or "模型未给出具体证据描述"
    reason = f"{names.get(hazard_type, hazard_type)}：{evidence_text}"
    if missing_sop:
        reason = f"[判据条款待专家确认] {reason}"

    need_review = (
        rules.default_need_review
        or best.confidence < rules.conf_review
        or missing_sop
    )

    if missing_sop and rules.require_sop_ref and rules.missing_sop_policy == "block":
        return Decision(
            is_hazard=False,
            hazard_type=None,
            level=None,
            confidence=best.confidence,
            reason=f"[已按策略拦截] 缺少判定依据条款：{reason}",
            need_manual_review=True,
        )

    return Decision(
        is_hazard=True,
        hazard_type=hazard_type,
        level=level,
        confidence=best.confidence,
        reason=reason,
        action=rules.action_for(hazard_type),
        sop_ref=sop_ref,
        missing_sop=missing_sop,
        need_manual_review=need_review,
    )


def sop_ref_map(taxonomy: dict[str, Any]) -> tuple[dict[str, str | None], dict[str, str]]:
    """从 taxonomy 取条款号与中文名（条款号不由模型生成，防编造法规）。"""
    refs: dict[str, str | None] = {}
    names: dict[str, str] = {}
    for cat in taxonomy.get("categories", []):
        cid = cat["id"]
        refs[cid] = cat.get("standard_ref")
        names[cid] = cat.get("name", cid)
    return refs, names
