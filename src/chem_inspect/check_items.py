"""45 项检查项（试点）装载与提示词。

设计原则：
- `config/check_items.yaml` 是 45 项目录；`config/pilot_check_items.yaml` 决定本轮
  实际启用哪些项；`config/baseline_criteria.yaml` 提供子项判据。
- 一次模型调用只问一个子项，避免 45 项全塞一个 prompt 造成注意力稀释。
- 试点不注入点位上下文（离线评测显示点位上下文只增误报）。
- 图片可能来自公开文章并带人工红圈/水印，提示词明确要求“不要依赖标注”。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SubItemSpec:
    item_code: str
    item_name: str
    group: str
    sub_code: str
    sub_name: str
    criteria: str
    boundary: str
    observation: str
    detection_mode: str


@dataclass(frozen=True)
class PilotCheckItems:
    version: str
    prompt_version: str
    specs: tuple[SubItemSpec, ...]
    max_calls_per_frame: int
    concurrency: int

    @property
    def enabled(self) -> bool:
        return bool(self.specs)

    def item_count(self) -> int:
        return len({s.item_code for s in self.specs})

    def to_dict(self) -> dict[str, Any]:
        items: dict[str, dict[str, Any]] = {}
        for spec in self.specs:
            item = items.setdefault(
                spec.item_code,
                {
                    "code": spec.item_code,
                    "name": spec.item_name,
                    "group": spec.group,
                    "detection_mode": spec.detection_mode,
                    "enabled": True,
                    "sub_items": [],
                },
            )
            item["sub_items"].append(
                {"code": spec.sub_code, "name": spec.sub_name}
            )
        return {
            "enabled": self.enabled,
            "version": self.version,
            "prompt_version": self.prompt_version,
            "max_calls_per_frame": self.max_calls_per_frame,
            "items": list(items.values()),
        }


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def load_pilot_check_items(config_dir: Path) -> PilotCheckItems | None:
    """装载试点配置；文件不存在或 enabled=false 时返回 None（保持旧链路）。"""
    pilot_path = config_dir / "pilot_check_items.yaml"
    if not pilot_path.exists():
        return None
    pilot = yaml.safe_load(pilot_path.read_text(encoding="utf-8")) or {}
    if not bool(pilot.get("enabled", False)):
        return None

    check_path = config_dir / "check_items.yaml"
    check = yaml.safe_load(check_path.read_text(encoding="utf-8")) or {}
    by_code = {item["code"]: item for item in check.get("items", [])}

    criteria_ref = Path(str(pilot.get("criteria_ref", "config/baseline_criteria.yaml")))
    criteria_path = config_dir / criteria_ref.name
    criteria_doc = yaml.safe_load(criteria_path.read_text(encoding="utf-8")) or {}
    criteria_by_sub = criteria_doc.get("sub_items", {})

    specs: list[SubItemSpec] = []
    for item_cfg in pilot.get("items", []):
        item_code = str(item_cfg["code"])
        item = by_code.get(item_code)
        if item is None:
            raise ValueError(f"pilot_check_items: check_items.yaml 里没有 {item_code}")
        sub_by_code = {sub["code"]: sub for sub in item.get("sub_items", [])}
        for sub_code in item_cfg.get("sub_items", []):
            sub = sub_by_code.get(str(sub_code))
            if sub is None:
                raise ValueError(
                    f"pilot_check_items: {item_code} 没有子项 {sub_code}（check_items.yaml）"
                )
            crit = criteria_by_sub.get(str(sub_code))
            if crit is None:
                raise ValueError(
                    f"pilot_check_items: {sub_code} 没有判据（{criteria_path.name}）"
                )
            specs.append(
                SubItemSpec(
                    item_code=item_code,
                    item_name=str(item.get("name", item_code)),
                    group=str(item.get("group", "")),
                    sub_code=str(sub_code),
                    sub_name=str(sub.get("name", sub_code)),
                    criteria=_text(crit.get("criteria")),
                    boundary=_text(crit.get("boundary")),
                    observation=_text(crit.get("observation")),
                    detection_mode=str(item.get("detection_mode", "vl_closeup")),
                )
            )

    max_calls = int(pilot.get("max_calls_per_frame", len(specs) or 1))
    if len(specs) > max_calls:
        raise ValueError(
            f"pilot_check_items: 启用 {len(specs)} 个子项，超过 max_calls_per_frame={max_calls}"
        )
    concurrency = max(1, min(8, int(pilot.get("concurrency", 4))))

    return PilotCheckItems(
        version=str(pilot.get("version", "unknown")),
        prompt_version=str(pilot.get("prompt_version", "pilot-v1")),
        specs=tuple(specs),
        max_calls_per_frame=max_calls,
        concurrency=concurrency,
    )


def build_sub_item_prompt(spec: SubItemSpec, point: dict[str, Any] | None = None) -> str:
    """单个子项提示词。point 暂不注入，保留参数便于后续按点位筛选。"""
    del point  # 试点阶段明确不注入点位上下文
    boundary = spec.boundary
    for prefix in ("不算缺陷：", "不算缺陷:"):
        if boundary.startswith(prefix):
            boundary = boundary[len(prefix) :].strip()

    return f"""你是化工设备巡检视觉判定器。只判断一个检查项。

检查项：{spec.sub_code} {spec.sub_name}（{spec.item_code} {spec.item_name}）
判据：{spec.criteria}
边界（以下情况不算缺陷）：{boundary}
观察条件：{spec.observation}
上下文：无（图片可能带人工标注圈/水印；只根据可见缺陷判断，不要把标注当判据）

纪律：
- 看不清、被遮挡、画面中没有该设备 → present=false, undecidable=true
- confidence 取 0~1 的真实把握，禁止照抄示例
- bbox 用 0~1000 相对坐标；无法给出写 null
- 只输出严格 JSON，不要 markdown

输出：
{{"present": false, "confidence": 0.0, "evidence": "", "bbox": null, "undecidable": false, "reason": ""}}
"""


__all__ = [
    "PilotCheckItems",
    "SubItemSpec",
    "build_sub_item_prompt",
    "load_pilot_check_items",
]
