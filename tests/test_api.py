"""端到端 API 测试：上传 → worker 判定 → 事件 → 复核 → 统计 → 导出。

全程使用 Mock 客户端（`maas_api_key=""`），不产生任何外网调用。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from chem_inspect.api.app import create_app
from chem_inspect.db import reset_db
from chem_inspect.settings import Settings


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    reset_db()
    settings = Settings(
        maas_api_key="",
        data_dir=tmp_path / "data",
        config_dir=Path("config"),
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_interval=0.05,
    )
    with TestClient(create_app(settings)) as c:
        yield c
    reset_db()


def _jpg() -> bytes:
    img = Image.new("RGB", (240, 180), (200, 200, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _wait_task(client: TestClient, task_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        data = client.get(f"/api/v1/tasks/{task_id}").json()
        if data["status"] in {"done", "failed"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内完成：{data}")


def test_health_reports_mock(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["mock"] is True
    assert "WH-A-03" in body["points"]


def test_unknown_point_rejected(client: TestClient) -> None:
    resp = client.post("/api/v1/tasks", json={"point_id": "NOPE"})
    assert resp.status_code == 400


def test_full_flow(client: TestClient) -> None:
    task = client.post("/api/v1/tasks", json={"point_id": "WH-A-03"}).json()
    resp = client.post(
        f"/api/v1/tasks/{task['task_id']}/frames",
        files=[("files", ("a.jpg", _jpg(), "image/jpeg"))],
    )
    assert resp.status_code == 202

    detail = _wait_task(client, task["task_id"])
    assert detail["status"] == "done"
    assert detail["total_frames"] == 1

    event = detail["frames"][0]["event"]
    assert event is not None
    assert event["hazard_type"] == "HZ-06"
    assert event["level"] == "较大隐患"
    assert event["evidence_url"].startswith("/files/")
    assert event["sop_pending"] is True  # 条款待专家确认

    # 复核：驳回必须带原因，且成功后不可重复处理
    payload = {
        "event_id": event["event_id"],
        "action": "reject",
        "reason_code": "false_positive",
        "reviewer": "tester",
    }
    resp = client.post(f"/api/v1/events/{event['event_id']}/review", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    resp = client.post(f"/api/v1/events/{event['event_id']}/review", json=payload)
    assert resp.status_code == 409

    stats = client.get("/api/v1/stats").json()
    assert stats["hazards"] >= 1
    assert stats["usage"]["prompt_tokens"] > 0

    csv_text = client.get("/api/v1/export/events.csv").text
    assert "事件ID" in csv_text
    assert "HZ-06" in csv_text


def test_duplicate_image_is_deduped(client: TestClient) -> None:
    task = client.post("/api/v1/tasks", json={"point_id": "WH-A-03"}).json()
    data = _jpg()
    for _ in range(2):
        client.post(
            f"/api/v1/tasks/{task['task_id']}/frames",
            files=[("files", ("a.jpg", data, "image/jpeg"))],
        )
    detail = _wait_task(client, task["task_id"])
    assert detail["total_frames"] == 1


def test_reject_requires_reason(client: TestClient) -> None:
    task = client.post("/api/v1/tasks", json={"point_id": "WH-A-03"}).json()
    client.post(
        f"/api/v1/tasks/{task['task_id']}/frames",
        files=[("files", ("a.jpg", _jpg(), "image/jpeg"))],
    )
    event = _wait_task(client, task["task_id"])["frames"][0]["event"]
    resp = client.post(
        f"/api/v1/events/{event['event_id']}/review",
        json={"event_id": event["event_id"], "action": "reject"},
    )
    assert resp.status_code == 422
