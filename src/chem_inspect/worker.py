"""DB 任务表 worker：轮询 pending 帧 → 跑 pipeline → 落库。

为什么不用 Redis/Celery：
- MVP 单机、要求断网可用、少运维；
- 任务状态本来就要持久化，直接放 DB 最省事，后期换 RQ 也只需换这一层。
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, update

from .contracts import FrameRef
from .db import Frame, Task, session_scope
from .pipeline import judge_frame_multi
from .service import AppContext, persist_event, refresh_task

log = logging.getLogger("chem_inspect.worker")


class FrameWorker:
    def __init__(self, ctx: AppContext, *, concurrency: int = 2, poll_interval: float = 1.0):
        self.ctx = ctx
        self.concurrency = max(1, concurrency)
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=self.concurrency)

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        self._recover()
        self._thread = threading.Thread(target=self._loop, name="frame-worker", daemon=True)
        self._thread.start()
        log.info("worker 启动（并发 %s）", self.concurrency)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=False)

    def _recover(self) -> None:
        """进程异常退出会留下 running 状态的帧，启动时重置，避免永久卡住。"""
        with session_scope() as s:
            res = s.execute(
                update(Frame).where(Frame.status == "running").values(status="pending")
            )
            if res.rowcount:
                log.warning("重置 %s 个卡在 running 的帧", res.rowcount)

    # ------------------------------------------------------------------ 主循环

    def _loop(self) -> None:
        while not self._stop.is_set():
            frame_id = self._claim()
            if frame_id is None:
                time.sleep(self.poll_interval)
                continue
            self._pool.submit(self.process_frame, frame_id)

    def _claim(self) -> str | None:
        with session_scope() as s:
            row = s.execute(
                select(Frame)
                .where(Frame.status == "pending")
                .order_by(Frame.received_at)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = "running"
            row.attempts += 1
            return row.id

    # ------------------------------------------------------------------ 单帧处理

    def process_frame(self, frame_id: str) -> None:
        try:
            with session_scope() as s:
                frame = s.get(Frame, frame_id)
                if frame is None:
                    return
                task = s.get(Task, frame.task_id)
                point_id = task.point_id if task else ""
                data = self.ctx.store.read_bytes(frame.uri)
                point = self.ctx.points.get(point_id)
                ref = FrameRef(
                    task_id=frame.task_id,
                    point_id=point_id,
                    captured_at=frame.captured_at,
                    frame_uri=frame.uri,
                    sha256=frame.sha256,
                )
                outcomes = judge_frame_multi(
                    data,
                    frame_ref=ref,
                    point=point,
                    client=self.ctx.client,
                    rules=self.ctx.rules,
                    taxonomy=self.ctx.taxonomy,
                    store=self.ctx.store,
                    model=self.ctx.model,
                    check_items=self.ctx.check_items,
                    network_mode=self.ctx.settings.network_mode,
                )
                for outcome in outcomes:
                    persist_event(s, outcome.event, frame=frame, rules=self.ctx.rules)
                errors = [o.error for o in outcomes if not o.ok and o.error]
                frame.status = "done" if all(o.ok for o in outcomes) else "failed"
                frame.error = "; ".join(errors)[:500] or None
                refresh_task(s, frame.task_id)
        except Exception as exc:  # noqa: BLE001 - 单帧失败不能拖垮 worker
            log.error("处理帧 %s 失败：%s\n%s", frame_id, exc, traceback.format_exc())
            with session_scope() as s:
                frame = s.get(Frame, frame_id)
                if frame is not None:
                    frame.status = "failed"
                    frame.error = str(exc)[:500]
                    refresh_task(s, frame.task_id)


__all__ = ["FrameWorker"]
