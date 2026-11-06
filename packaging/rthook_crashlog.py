"""PyInstaller runtime hook：把未捕获异常写进用户目录 logs/crash.log。

windowed（无控制台）模式下崩溃时界面上什么都看不到，
这个钩子是唯一能拿到堆栈的地方，也方便评委把日志发回来排查。
"""

import os
import sys
import traceback
from pathlib import Path


def _home() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ChemInspect"


def _write(text: str) -> None:
    try:
        logs = _home() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "crash.log").write_text(text, encoding="utf-8")
    except OSError:
        pass


def _hook(exc_type, exc, tb) -> None:
    _write("".join(traceback.format_exception(exc_type, exc, tb)))


sys.excepthook = _hook

# windowed 模式下这两个流是 None，先占位避免下游库报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115
