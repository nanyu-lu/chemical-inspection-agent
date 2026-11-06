"""应用服务层：配置装载、事件持久化、去重、进度与统计。

把「不依赖 HTTP」的逻辑集中在这里，便于 worker、CLI、后期 FC handler 复用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .contracts import HazardEvent, NetworkMode
from .db import Event, Frame, LLMUsage, Task, naive_utcnow
from .llm.base import LLMClient
from .llm.maas import MaasClient
from .llm.mock import MockClient
from .prompt import load_taxonomy
from .rules import RuleSet
from .settings import Settings
from .storage import LocalBlobStore


@dataclass
class AppContext:
    settings: Settings
    store: LocalBlobStore
    rules: RuleSet
    taxonomy: dict[str, Any]
    points: dict[str, dict[str, Any]]
    client: LLMClient
    model: str


def load_points(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {p["id"]: p for p in data.get("points", []) if "id" in p}


def build_client(settings: Settings) -> LLMClient:
    """无 Key 或离线/隔离模式 → Mock，保证链路可跑、演示不中断。"""
    if not settings.has_key:
        return MockClient()
    if settings.network_mode in (NetworkMode.OFFLINE, NetworkMode.AIRGAP):
        return MockClient()
    return MaasClient(
        api_key=settings.require_key(),
        base_url=settings.maas_base_url,
        timeout_s=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )


def persist_event(
    session: Session, event: HazardEvent, *, frame: Frame, rules: RuleSet
) -> Event:
    """写入事件 + 调用记账；同点位同类隐患在窗口内标记 duplicate_of（不删除）。"""
    verdict = event.verdict
    duplicate_of: str | None = None
    if rules.dedupe_enabled and verdict.is_hazard and verdict.hazard_type:
        cutoff = naive_utcnow() - timedelta(hours=rules.dedupe_window_hours)
        duplicate_of = session.execute(
            select(Event.event_id)
            .where(
                Event.point_id == event.frame_ref.point_id,
                Event.hazard_type == verdict.hazard_type,
                Event.is_hazard.is_(True),
                Event.created_at >= cutoff,
                Event.duplicate_of.is_(None),
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    row = Event(
        event_id=event.event_id,
        frame_id=frame.id,
        task_id=event.frame_ref.task_id,
        point_id=event.frame_ref.point_id,
        hazard_type=verdict.hazard_type,
        is_hazard=verdict.is_hazard,
        level=verdict.level,
        confidence=verdict.confidence,
        reason=verdict.reason,
        sop_ref=verdict.sop_ref,
        action=verdict.action,
        bbox_json=json.dumps(
            [d.model_dump() for d in event.detections], ensure_ascii=False
        ),
        evidence_uri=verdict.evidence_crop_uri,
        need_manual_review=verdict.need_manual_review,
        status="draft",
        degraded=event.engine.degraded,
        duplicate_of=duplicate_of,
        model_id=event.engine.model_id,
        prompt_version=event.engine.prompt_version,
        rule_version=event.engine.rule_version,
    )
    session.add(row)
    session.add(
        LLMUsage(
            event_id=event.event_id,
            model=event.engine.model_id,
            prompt_tokens=event.usage.prompt_tokens,
            completion_tokens=event.usage.completion_tokens,
            latency_ms=event.usage.latency_ms,
            ok=not event.engine.degraded,
            error=None if not event.engine.degraded else "degraded",
        )
    )
    session.flush()
    return row


def refresh_task(session: Session, task_id: str) -> Task | None:
    task = session.get(Task, task_id)
    if task is None:
        return None
    total = session.scalar(
        select(func.count()).select_from(Frame).where(Frame.task_id == task_id)
    ) or 0
    done = session.scalar(
        select(func.count())
        .select_from(Frame)
        .where(Frame.task_id == task_id, Frame.status == "done")
    ) or 0
    failed = session.scalar(
        select(func.count())
        .select_from(Frame)
        .where(Frame.task_id == task_id, Frame.status == "failed")
    ) or 0
    task.total_frames = int(total)
    task.done_frames = int(done)
    if total and done + failed >= total:
        task.status = "failed" if done == 0 else "done"
        task.finished_at = naive_utcnow()
    elif done or failed:
        task.status = "running"
    session.flush()
    return task


def stats(session: Session) -> dict[str, Any]:
    total_frames = session.scalar(select(func.count()).select_from(Frame)) or 0
    total_events = session.scalar(select(func.count()).select_from(Event)) or 0
    hazard_events = session.scalar(
        select(func.count()).select_from(Event).where(Event.is_hazard.is_(True))
    ) or 0
    need_review = session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.is_hazard.is_(True), Event.need_manual_review.is_(True))
    ) or 0
    degraded = session.scalar(
        select(func.count()).select_from(Event).where(Event.degraded.is_(True))
    ) or 0

    by_type = session.execute(
        select(Event.hazard_type, func.count())
        .where(Event.is_hazard.is_(True))
        .group_by(Event.hazard_type)
    ).all()
    by_point = session.execute(
        select(Event.point_id, func.count())
        .where(Event.is_hazard.is_(True))
        .group_by(Event.point_id)
    ).all()

    prompt_tokens = session.scalar(select(func.coalesce(func.sum(LLMUsage.prompt_tokens), 0))) or 0
    completion_tokens = session.scalar(
        select(func.coalesce(func.sum(LLMUsage.completion_tokens), 0))
    ) or 0
    avg_latency = session.scalar(select(func.coalesce(func.avg(LLMUsage.latency_ms), 0))) or 0

    return {
        "frames": int(total_frames),
        "events": int(total_events),
        "hazards": int(hazard_events),
        "need_review": int(need_review),
        "degraded": int(degraded),
        "by_hazard_type": {k or "unknown": int(v) for k, v in by_type},
        "by_point": {k or "unknown": int(v) for k, v in by_point},
        "usage": {
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "avg_latency_ms": round(float(avg_latency), 1),
        },
    }


def export_rows(session: Session, limit: int = 5000) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Event).order_by(Event.created_at.desc()).limit(limit)
    ).scalars()
    out: list[dict[str, Any]] = []
    for e in rows:
        out.append(
            {
                "事件ID": e.event_id,
                "点位": e.point_id,
                "隐患类别": e.hazard_type or "",
                "等级": e.level or "",
                "置信度": f"{e.confidence:.2f}",
                "是否隐患": "是" if e.is_hazard else "否",
                "判定理由": e.reason,
                "依据条款": e.sop_ref or "待专家确认",
                "处置建议": e.action or "",
                "状态": e.status,
                "需复核": "是" if e.need_manual_review else "否",
                "降级": "是" if e.degraded else "否",
                "重复于": e.duplicate_of or "",
                "证据图": e.evidence_uri or "",
                "模型": e.model_id,
                "提示词版本": e.prompt_version,
                "规则版本": e.rule_version,
                "时间": e.created_at.isoformat(sep=" "),
            }
        )
    return out


def build_context(settings: Settings) -> AppContext:
    cfg = settings.config_dir
    return AppContext(
        settings=settings,
        store=LocalBlobStore(settings.data_dir / "blobs"),
        rules=RuleSet.from_yaml(cfg / "hazard_rules.yaml"),
        taxonomy=load_taxonomy(cfg / "hazard_taxonomy.yaml"),
        points=load_points(cfg / "points.yaml"),
        client=build_client(settings),
        model=settings.maas_vision_model,
    )

