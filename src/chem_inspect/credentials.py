"""API Key 的读取与保存（永不写进二进制、永不进 git）。

优先级：环境变量 ``MAAS_API_KEY`` > 用户目录 ``config.json``
（项目根 ``.env`` 由 ``Settings`` 通过 pydantic-settings 读取，本模块不重复处理。）

打包后由启动器弹窗输入一次，存到 ``app_home()/config.json``（权限 600）。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .paths import user_config_path

ENV_KEY = "MAAS_API_KEY"


def load_api_key() -> str:
    """返回最优先的 Key；没有则返回空串。"""
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env

    cfg_path = user_config_path()
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            key = str(data.get("api_key", "")).strip()
            if key:
                return key
        except (json.JSONDecodeError, OSError):
            pass

    # 注意：不再回退去读项目根 .env —— 那是 Settings 的职责（pydantic-settings 已经处理）。
    # 这里只管「环境变量」与「用户目录 config.json」，避免测试/CI 上莫名其妙读到真实 Key。
    return ""


def save_api_key(key: str) -> Path:
    """保存到用户目录，并尽量设为仅本人可读。"""
    key = key.strip()
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["api_key"] = key
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600，Windows 上会被忽略
    except OSError:
        pass
    return path


def mask(key: str) -> str:
    if not key:
        return "（未配置）"
    if len(key) < 12:
        return "***"
    return f"{key[:7]}***{key[-4:]}"


__all__ = ["ENV_KEY", "load_api_key", "mask", "save_api_key"]
