"""45 项试点 API：一帧 9 条事件、配置暴露、老库迁移。"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from chem_inspect.api.app import create_app
from chem_inspect.db import init_db, reset_db
from chem_inspect.settings import Settings


@pytest.fixture()
def pilot_client(tmp_path: Path) -> Iterator[TestClient]:
    reset_db()
    settings = Settings(
        maas_api_key="",
        data_dir=tmp_path / "data",
        config_dir=Path("config"),
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_interval=0.05,
        check_items_pilot=True,
    )
    with TestClient(create_app(settings)) as c:
        yield c
    reset_db()


def _jpg() -> bytes:
    img = Image.new("RGB", (240, 180), (200, 200, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _wait_task(client: TestClient, task_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        data = client.get(f"/api/v1/tasks/{task_id}").json()
        if data["status"] in {"done", "failed"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务未完成：{data}")


def test_health_and_config_expose_pilot(pilot_client: TestClient) -> None:
    health = pilot_client.get("/api/v1/health").json()
    assert health["check_items_pilot"] is True
    assert health["check_items_count"] == 9

    cfg = pilot_client.get("/api/v1/config").json()
    assert cfg["check_items"]["enabled"] is True
    assert {i["code"] for i in cfg["check_items"]["items"]} == {"CI-06", "CI-11"}
    assert sum(len(i["sub_items"]) for i in cfg["check_items"]["items"]) == 9


def test_upload_produces_nine_events(pilot_client: TestClient) -> None:
    task = pilot_client.post("/api/v1/tasks", json={"point_id": "WH-A-03"}).json()
    resp = pilot_client.post(
        f"/api/v1/tasks/{task['task_id']}/frames",
        files=[("files", ("a.jpg", _jpg(), "image/jpeg"))],
    )
    assert resp.status_code == 202

    detail = _wait_task(pilot_client, task["task_id"])
    assert detail["status"] == "done"
    events = detail["frames"][0]["events"]
    assert len(events) == 9
    assert {e["sub_item_code"] for e in events} == {
        "6.11", "6.13", "6.9", "11.1", "11.3", "11.4", "11.6", "11.7", "11.8"
    }
    assert all(e["check_item_code"] in {"CI-06", "CI-11"} for e in events)
    assert all(e["is_hazard"] is False for e in events)  # Mock 默认返回“未发现”
    assert detail["frames"][0]["event"] is not None  # 兼容旧前端字段


def test_old_db_migration_adds_columns(tmp_path: Path) -> None:
    reset_db()
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY)")
    session = init_db(db_path)
    session.close()
    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    assert {"check_item_code", "sub_item_code", "check_item_name", "detection_mode"} <= cols
    reset_db()
