"""数据层（SQLAlchemy 2.0 + SQLite）。

表结构与 `docs/MVP开发计划.md` 一致：tasks / frames / events / reviews / llm_usage

约定：
- 只用 SQLAlchemy 通用类型，不写 SQLite 方言，便于后期换 PostgreSQL。
- events 是 append-only：业务字段不更新，状态变更只写 reviews。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .contracts import new_event_id


def naive_utcnow() -> datetime:
    """SQLite 的 DATETIME 不支持时区，统一存 UTC naive 时间。"""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_event_id)
    point_id: Mapped[str] = mapped_column(String(64), index=True)
    route_id: Mapped[str | None] = mapped_column(String(64), default=None)
    robot_id: Mapped[str] = mapped_column(String(64), default="manual")
    source: Mapped[str] = mapped_column(String(32), default="image")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)
    done_frames: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Frame(Base):
    __tablename__ = "frames"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_event_id)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id"), index=True)
    uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_event_id)
    frame_id: Mapped[str] = mapped_column(String(64), ForeignKey("frames.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    point_id: Mapped[str] = mapped_column(String(64), index=True)
    hazard_type: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    is_hazard: Mapped[bool] = mapped_column(Boolean, default=False)
    level: Mapped[str | None] = mapped_column(String(32), default=None)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    sop_ref: Mapped[str | None] = mapped_column(Text, default=None)
    action: Mapped[str | None] = mapped_column(Text, default=None)
    bbox_json: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_uri: Mapped[str | None] = mapped_column(Text, default=None)
    need_manual_review: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[str | None] = mapped_column(String(64), default=None)
    model_id: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    rule_version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_event_id)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("events.event_id"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(32), default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_event_id)
    event_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=naive_utcnow)


Index("ix_events_point_type_time", Event.point_id, Event.hazard_type, Event.created_at)

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(db_path: Path) -> Session:
    """建库并返回一个 Session（首次调用时初始化引擎）。"""
    global _engine, _SessionLocal
    if _engine is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    assert _SessionLocal is not None, "先调用 init_db()"
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_db() -> None:
    """仅供测试：释放引擎，使下一次 init_db() 指向新的库文件。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


