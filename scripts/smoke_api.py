#!/usr/bin/env python3
"""接口冒烟测试：对一个已启动的服务跑一遍关键路径。

用法：
    uv run python scripts/smoke_api.py --base http://127.0.0.1:8000
    uv run python scripts/smoke_api.py --base ... --image 现场图.jpg

检查项：健康检查 → 建任务 → 上传 → 等待判定 → 证据图可访问 → 驳回(必填原因) → 重复驳回 409 → 统计 → CSV 导出
"""

from __future__ import annotations

import argparse
import time
from io import BytesIO

import httpx
from PIL import Image


def _demo_jpeg() -> bytes:
    img = Image.new("RGB", (320, 240), (190, 190, 190))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--image", default=None, help="可选：用真实现场图代替合成图")
    parser.add_argument("--point", default="WH-A-03")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and cond
        print(f"[{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")

    with httpx.Client(base_url=base, timeout=120.0) as c:
        health = c.get("/api/v1/health").json()
        check("健康检查", health.get("status") == "ok", f"client={health.get('client')}")

        task = c.post("/api/v1/tasks", json={"point_id": args.point}).json()
        task_id = task["task_id"]
        check("创建任务", bool(task_id), task_id)

        if args.image:
            with open(args.image, "rb") as fh:
                data = fh.read()
        else:
            data = _demo_jpeg()
        resp = c.post(f"/api/v1/tasks/{task_id}/frames", files=[("files", ("a.jpg", data, "image/jpeg"))])
        check("上传帧", resp.status_code == 202, f"HTTP {resp.status_code}")

        deadline = time.time() + args.timeout
        detail: dict = {}
        while time.time() < deadline:
            detail = c.get(f"/api/v1/tasks/{task_id}").json()
            if detail["status"] in {"done", "failed"}:
                break
            time.sleep(1.0)
        check("任务完成", detail.get("status") == "done", detail.get("status", "timeout"))

        frame = (detail.get("frames") or [{}])[0]
        event = frame.get("event") or {}
        check("生成事件", bool(event.get("event_id")), f"{event.get('hazard_type')} conf={event.get('confidence')}")

        if event.get("evidence_url"):
            r = c.get(event["evidence_url"])
            check("证据图可访问", r.status_code == 200 and r.content[:2] == b"\xff\xd8",
                  f"HTTP {r.status_code}, {len(r.content)} bytes")

        eid = event.get("event_id")
        if eid:
            payload = {"event_id": eid, "action": "reject", "reason_code": "false_positive", "reviewer": "smoke"}
            r = c.post(f"/api/v1/events/{eid}/review", json=payload)
            check("驳回成功", r.status_code == 200 and r.json().get("status") == "rejected", f"HTTP {r.status_code}")
            r = c.post(f"/api/v1/events/{eid}/review", json=payload)
            check("重复驳回应 409", r.status_code == 409, f"HTTP {r.status_code}")
            r = c.post(f"/api/v1/events/{eid}/review", json={"event_id": eid, "action": "reject"})
            check("驳回缺原因应 422", r.status_code == 422, f"HTTP {r.status_code}")

        stats = c.get("/api/v1/stats").json()
        check("统计接口", stats.get("frames", 0) >= 1, f"frames={stats.get('frames')} hazards={stats.get('hazards')}")

        csv_text = c.get("/api/v1/export/events.csv").text
        check("CSV 导出", "事件ID" in csv_text and "点位" in csv_text, f"{len(csv_text)} chars")

    print("\n结果：", "全部通过 ✅" if ok else "存在失败项 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
