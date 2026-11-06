"""FastAPI 应用（MVP 单机）。

职责边界：本层只做「收下 → 落盘 → 入队 → 查询」，识别全部交给 worker/pipeline。
这样后期搬阿里云 FC 时，handler 与 pipeline 都不用改。
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..contracts import ReviewAction
from ..db import Event, Frame, Review, Task, init_db, session_scope
from ..imaging import load_image
from ..service import AppContext, build_context, export_rows, refresh_task, stats
from ..settings import Settings, get_settings
from ..storage import sha256_bytes
from ..worker import FrameWorker

log = logging.getLogger("chem_inspect.api")


class TaskCreate(BaseModel):
    point_id: str = Field(min_length=1)
    route_id: str | None = None
    source: str = "image"
    robot_id: str = "manual"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ") if value else None


def _web(ctx: AppContext, uri: str | None) -> str | None:
    if not uri:
        return None
    try:
        return ctx.store.web_path(uri)
    except ValueError:
        return None


def event_dict(e: Event, ctx: AppContext) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "task_id": e.task_id,
        "point_id": e.point_id,
        "hazard_type": e.hazard_type,
        "is_hazard": e.is_hazard,
        "level": e.level,
        "confidence": round(e.confidence, 3),
        "reason": e.reason,
        "sop_ref": e.sop_ref,
        "sop_pending": e.sop_ref is None,
        "action": e.action,
        "status": e.status,
        "need_manual_review": e.need_manual_review,
        "degraded": e.degraded,
        "duplicate_of": e.duplicate_of,
        "evidence_url": _web(ctx, e.evidence_uri),
        "detections": json.loads(e.bbox_json or "[]"),
        "engine": {
            "model_id": e.model_id,
            "prompt_version": e.prompt_version,
            "rule_version": e.rule_version,
        },
        "created_at": _iso(e.created_at),
    }


def task_dict(t: Task) -> dict[str, Any]:
    return {
        "task_id": t.id,
        "point_id": t.point_id,
        "route_id": t.route_id,
        "robot_id": t.robot_id,
        "source": t.source,
        "status": t.status,
        "total_frames": t.total_frames,
        "done_frames": t.done_frames,
        "created_at": _iso(t.created_at),
        "finished_at": _iso(t.finished_at),
    }


def frame_dict(f: Frame, event: Event | None, ctx: AppContext) -> dict[str, Any]:
    return {
        "frame_id": f.id,
        "status": f.status,
        "error": f.error,
        "url": _web(ctx, f.uri),
        "width": f.width,
        "height": f.height,
        "captured_at": _iso(f.captured_at),
        "event": event_dict(event, ctx) if event else None,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    st = settings or get_settings()
    (st.data_dir / "blobs").mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(st.data_dir / "app.db")
        ctx = build_context(st)
        app.state.ctx = ctx
        app.state.worker = None
        if st.worker_enabled:
            worker = FrameWorker(
                ctx,
                concurrency=st.worker_concurrency,
                poll_interval=st.worker_poll_interval,
            )
            worker.start()
            app.state.worker = worker
        log.info(
            "API 启动：model=%s network=%s client=%s",
            ctx.model,
            st.network_mode.value,
            type(ctx.client).__name__,
        )
        try:
            yield
        finally:
            if app.state.worker:
                app.state.worker.stop()

    app = FastAPI(title="化工巡检 · 隐患识别 Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/files", StaticFiles(directory=str(st.data_dir / "blobs")), name="files")

    def ctx_of(request: Request) -> AppContext:
        return request.app.state.ctx

    # ---------------------------------------------------------------- 基础

    @app.get("/api/v1/health")
    def health(request: Request) -> dict[str, Any]:
        ctx = ctx_of(request)
        return {
            "status": "ok",
            "network_mode": ctx.settings.network_mode.value,
            "model": ctx.model,
            "client": type(ctx.client).__name__,
            "mock": type(ctx.client).__name__ == "MockClient",
            "rules_version": ctx.rules.version,
            "points": list(ctx.points),
        }

    @app.get("/api/v1/config")
    def config(request: Request) -> dict[str, Any]:
        ctx = ctx_of(request)
        return {
            "categories": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "in_mvp": bool(c.get("in_mvp")),
                    "vision_detectable": c.get("vision_detectable"),
                    "level": ctx.rules.level_for(c["id"]),
                }
                for c in ctx.taxonomy["categories"]
            ],
            "points": list(ctx.points.values()),
            "thresholds": {
                "conf_drop": ctx.rules.conf_drop,
                "conf_review": ctx.rules.conf_review,
            },
            "criteria_confirmed": bool(ctx.taxonomy.get("criteria_confirmed", False)),
        }

    # ---------------------------------------------------------------- 任务

    @app.post("/api/v1/tasks", status_code=201)
    def create_task(body: TaskCreate, request: Request) -> dict[str, Any]:
        ctx = ctx_of(request)
        if ctx.points and body.point_id not in ctx.points:
            raise HTTPException(400, f"未知点位：{body.point_id}")
        with session_scope() as s:
            task = Task(
                point_id=body.point_id,
                route_id=body.route_id,
                robot_id=body.robot_id,
                source=body.source,
            )
            s.add(task)
            s.flush()
            return task_dict(task)

    @app.get("/api/v1/tasks")
    def list_tasks(limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
        with session_scope() as s:
            rows = s.execute(
                select(Task).order_by(Task.created_at.desc()).limit(limit)
            ).scalars()
            return [task_dict(t) for t in rows]

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str, request: Request) -> dict[str, Any]:
        ctx = ctx_of(request)
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                raise HTTPException(404, "任务不存在")
            frames = (
                s.execute(
                    select(Frame).where(Frame.task_id == task_id).order_by(Frame.received_at)
                )
                .scalars()
                .all()
            )
            events = s.execute(select(Event).where(Event.task_id == task_id)).scalars().all()
            by_frame = {e.frame_id: e for e in events}
            return {
                **task_dict(task),
                "frames": [frame_dict(f, by_frame.get(f.id), ctx) for f in frames],
            }

    # ---------------------------------------------------------------- 上传

    @app.post("/api/v1/tasks/{task_id}/frames", status_code=202)
    async def upload_frames(
        task_id: str,
        request: Request,
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI 标准写法
    ) -> dict[str, Any]:
        ctx = ctx_of(request)
        if not files:
            raise HTTPException(400, "没有收到文件")
        saved: list[dict[str, Any]] = []
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                raise HTTPException(404, "任务不存在")
            for up in files:
                data = await up.read()
                if not data:
                    continue
                ctype = up.content_type or ""
                if ctype.startswith("video/"):
                    raise HTTPException(
                        400,
                        "视频抽帧需要 ffmpeg，当前环境未安装；请先上传图片。",
                    )
                try:
                    img = load_image(data)
                except Exception as exc:
                    raise HTTPException(400, f"无法解析图片 {up.filename}：{exc}") from exc

                digest = sha256_bytes(data)
                dup = s.execute(
                    select(Frame).where(Frame.task_id == task_id, Frame.sha256 == digest)
                ).scalar_one_or_none()
                if dup is not None:
                    saved.append({"frame_id": dup.id, "dedup": True})
                    continue

                frame = Frame(
                    task_id=task_id, uri="", sha256=digest, width=img.width, height=img.height
                )
                s.add(frame)
                s.flush()
                frame.uri = ctx.store.save_bytes(task_id, f"{frame.id}.jpg", data)
                saved.append({"frame_id": frame.id, "dedup": False})
            refresh_task(s, task_id)
        return {"task_id": task_id, "accepted": len(saved), "frames": saved}

    # ---------------------------------------------------------------- 事件

    @app.get("/api/v1/events")
    def list_events(
        request: Request,
        point_id: str | None = None,
        hazard_type: str | None = None,
        status: str | None = None,
        only_hazard: bool = True,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        ctx = ctx_of(request)
        stmt = select(Event)
        if point_id:
            stmt = stmt.where(Event.point_id == point_id)
        if hazard_type:
            stmt = stmt.where(Event.hazard_type == hazard_type)
        if status:
            stmt = stmt.where(Event.status == status)
        if only_hazard:
            stmt = stmt.where(Event.is_hazard.is_(True))
        stmt = stmt.order_by(Event.created_at.desc()).limit(limit).offset(offset)
        with session_scope() as s:
            rows = s.execute(stmt).scalars().all()
            return {"total": len(rows), "items": [event_dict(e, ctx) for e in rows]}

    @app.get("/api/v1/events/{event_id}")
    def get_event(event_id: str, request: Request) -> dict[str, Any]:
        ctx = ctx_of(request)
        with session_scope() as s:
            event = s.get(Event, event_id)
            if event is None:
                raise HTTPException(404, "事件不存在")
            reviews = (
                s.execute(
                    select(Review).where(Review.event_id == event_id).order_by(Review.created_at)
                )
                .scalars()
                .all()
            )
            return {
                **event_dict(event, ctx),
                "reviews": [
                    {
                        "action": r.action,
                        "reason_code": r.reason_code,
                        "note": r.note,
                        "reviewer": r.reviewer,
                        "created_at": _iso(r.created_at),
                    }
                    for r in reviews
                ],
            }

    @app.post("/api/v1/events/{event_id}/review")
    def review_event(event_id: str, body: ReviewAction) -> dict[str, Any]:
        if body.event_id != event_id:
            raise HTTPException(400, "路径与请求体的 event_id 不一致")
        with session_scope() as s:
            event = s.get(Event, event_id)
            if event is None:
                raise HTTPException(404, "事件不存在")
            if event.status != "draft":
                raise HTTPException(409, f"事件已处理（当前状态 {event.status}）")
            s.add(
                Review(
                    event_id=event_id,
                    action=body.action,
                    reason_code=body.reason_code.value if body.reason_code else None,
                    note=body.note,
                    reviewer=body.reviewer,
                )
            )
            # status 是 reviews 的物化投影，不是业务字段改写
            event.status = "confirmed" if body.action == "confirm" else "rejected"
            s.flush()
            return {"event_id": event_id, "status": event.status}

    # ---------------------------------------------------------------- 统计与导出

    @app.get("/api/v1/stats")
    def get_stats() -> dict[str, Any]:
        with session_scope() as s:
            return stats(s)

    @app.get("/api/v1/export/events.csv")
    def export_events(limit: int = Query(5000, ge=1, le=50000)) -> StreamingResponse:
        with session_scope() as s:
            rows = export_rows(s, limit=limit)
        header = list(rows[0].keys()) if rows else ["事件ID"]
        lines = [",".join(header)]
        for row in rows:
            lines.append(",".join(_csv_cell(row.get(h, "")) for h in header))
        body = "\ufeff" + "\n".join(lines) + "\n"
        return StreamingResponse(
            iter([body]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="hazard_events.csv"'},
        )

    # ---------------------------------------------------------------- 前端托管（单端口交付）

    web_dist = Path(st.web_dist)
    index_file = web_dist / "index.html"
    if st.serve_web and index_file.exists():
        assets_dir = web_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            """SPA 回退：/api、/files、/assets 之外的路径都返回 index.html。"""
            if full_path.startswith(("api/", "files/", "assets/")):
                raise HTTPException(404, "Not Found")
            return FileResponse(index_file)
    else:
        log.info(
            "未启用前端托管（serve_web=%s，dist 存在=%s）", st.serve_web, index_file.exists()
        )

    return app



def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if any(ch in text for ch in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


app = create_app()

__all__ = ["app", "create_app"]




