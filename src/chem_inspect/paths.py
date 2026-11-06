"""运行时路径解析：把「只读资源」和「可写数据」彻底分开。

打包成 .app / .exe 之后：
- **资源**（web/dist、config、docs）在只读位置（``sys._MEIPASS`` 或可执行文件同级）→ 只读
- **数据**（data、logs、config.json 里的 Key）必须写到用户目录 → 可写，且不会破坏签名

开发态两者都落在项目根目录，行为与之前完全一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ChemInspect"
APP_DISPLAY_NAME = "化工巡检"


def is_frozen() -> bool:
    """是否是 PyInstaller 打出来的可执行文件。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """源码根目录（仅开发态有意义）。"""
    return Path(__file__).resolve().parents[2]


def app_home() -> Path:
    """用户数据目录（可写）。可用 CHEM_INSPECT_HOME 覆盖。"""
    env = os.environ.get("CHEM_INSPECT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if not is_frozen():
        return project_root()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / APP_NAME


def resources_root() -> Path:
    """只读资源目录（源码 / 打包后的 bundle 内）。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).resolve().parent
    return project_root()


def data_dir() -> Path:
    return app_home() / "data"


def logs_dir() -> Path:
    return app_home() / "logs"


def user_config_path() -> Path:
    return app_home() / "config.json"


def ensure_dirs() -> None:
    """启动时确保可写目录存在（打包后第一次运行会创建）。"""
    for path in (data_dir(), logs_dir(), data_dir() / "blobs"):
        path.mkdir(parents=True, exist_ok=True)


__all__ = [
    "APP_DISPLAY_NAME",
    "APP_NAME",
    "app_home",
    "data_dir",
    "ensure_dirs",
    "is_frozen",
    "logs_dir",
    "project_root",
    "resources_root",
    "user_config_path",
]
