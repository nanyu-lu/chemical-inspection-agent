"""本地文件存储（BlobStore 的 fs 实现）。

URI 约定：`local://blobs/<task_id>/<name>.jpg`
- 与后期 MinIO 的 `s3://bucket/key` 语义一致，换实现只改这一层
- 对外暴露 `/files/...` 由 FastAPI StaticFiles 提供，避免路径穿越
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SCHEME = "local://"


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 写

    def save_bytes(self, task_id: str, name: str, data: bytes, sub: str = "raw") -> str:
        folder = self.root / sub / task_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(data)
        return f"{SCHEME}{sub}/{task_id}/{name}"

    def save_file(self, task_id: str, name: str, src: Path, sub: str = "raw") -> str:
        return self.save_bytes(task_id, name, src.read_bytes(), sub=sub)

    # ------------------------------------------------------------------ 读

    def resolve(self, uri: str) -> Path:
        if not uri.startswith(SCHEME):
            raise ValueError(f"不支持的 URI：{uri}")
        rel = uri[len(SCHEME) :]
        if ".." in rel.split("/"):
            raise ValueError("非法路径")
        return self.root / rel

    def read_bytes(self, uri: str) -> bytes:
        return self.resolve(uri).read_bytes()

    def web_path(self, uri: str) -> str:
        """给前端的相对 URL（StaticFiles 挂载在 /files）。"""
        return "/files/" + uri[len(SCHEME) :]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
