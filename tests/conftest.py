"""测试全局隔离：不读真实 Key、不写真实用户目录。

之前踩过的坑：某个终端会话里残留了 ``MAAS_API_KEY`` 环境变量，
导致"期望 Mock 模式"的测试拿到了真实 Key 而失败。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("MAAS_API_KEY", raising=False)
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path / "home"))
    yield


def pytest_report_header(config: pytest.Config) -> str:
    return f"chem-inspect tests | MAAS_API_KEY in env: {'MAAS_API_KEY' in os.environ}"
