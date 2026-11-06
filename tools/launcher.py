#!/usr/bin/env python3
"""图形化启动器（macOS / Windows 通用，PyInstaller 入口）。

设计要点
- **同进程内跑 uvicorn**（`uvicorn.Server` + 后台线程）：关窗口即结束，不留孤儿进程
- `loop/http/ws` 显式指定，减少 PyInstaller 动态导入风险与体积
- 首次运行要求填 API Key，存到用户目录 `config.json`（不打进二进制）
- 出错时把日志尾部直接显示在窗口里，避免"双击闪退、什么也看不到"
- `--serve-only` 供命令行/冒烟测试使用（不开窗口）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from chem_inspect.credentials import load_api_key, mask, save_api_key
from chem_inspect.paths import APP_DISPLAY_NAME, ensure_dirs, logs_dir

PORT_RANGE = tuple(range(8000, 8011))
log = logging.getLogger("launcher")


def safe_streams() -> None:
    """windowed 模式下 stdout/stderr 是 None，部分库会因此抛异常。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - 进程级替换，不能关闭
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - 同上


def setup_logging() -> Path:
    ensure_dirs()
    path = logs_dir() / "api.log"
    logging.basicConfig(
        filename=str(path),
        level=logging.INFO,
        encoding="utf-8",
        force=True,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return path


def can_bind(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int | None = None) -> int:
    candidates = ([preferred] if preferred else []) + list(PORT_RANGE)
    for port in candidates:
        if can_bind(port):
            return port
    raise RuntimeError(f"{PORT_RANGE[0]}~{PORT_RANGE[-1]} 端口都被占用，请先关闭占用程序")


def health(port: int, timeout: float = 2.0) -> dict | None:
    url = f"http://127.0.0.1:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


class ServerHandle:
    """把 uvicorn 跑在当前进程的后台线程里。"""

    def __init__(self, port: int) -> None:
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> None:
        import uvicorn

        from chem_inspect.api.app import create_app

        class QuietServer(uvicorn.Server):
            """关闭信号处理。

            我们在线程里跑服务，而 Windows 的 ProactorEventLoop 不支持
            ``loop.add_signal_handler``，uvicorn 会退化成 ``signal.signal``，
            在非主线程里直接抛 ``ValueError: signal only works in main thread``。
            macOS/Linux 上 add_signal_handler 可用，所以这个坑只在 Windows 暴露。
            退出由启动器按钮 / Ctrl+C（主线程）负责，不需要信号处理。
            """

            def install_signal_handlers(self) -> None:  # noqa: D102 - 见类注释
                return

        app = create_app()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            loop="asyncio",
            http="h11",
            ws="none",
            log_config=None,
            log_level="info",
            access_log=False,
        )
        self._server = QuietServer(config)
        self._thread = threading.Thread(target=self._run, name="uvicorn", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            assert self._server is not None
            self._server.run()
        except BaseException as exc:  # 线程内异常必须兜住，否则窗口卡在"启动中"
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("uvicorn 启动失败")

    def wait_ready(self, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.error:
                return False
            if health(self.port):
                return True
            time.sleep(0.3)
        return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


def tail_log(path: Path, lines: int = 25) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(content[-lines:])
    except OSError:
        return "（无日志）"


def open_path(path: Path) -> None:
    """用系统默认程序打开文件/目录（跨平台）。"""
    try:
        if sys.platform == "darwin":
            __import__("subprocess").Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            __import__("subprocess").Popen(["xdg-open", str(path)])
    except OSError:
        log.warning("打开路径失败：%s", path)


def ask_api_key(root) -> str:
    """首次运行弹窗输入 Key（留空 = Mock 模式）。"""
    from tkinter import simpledialog

    root.withdraw()
    entered = simpledialog.askstring(
        f"{APP_DISPLAY_NAME} · 首次运行",
        "请粘贴千炼 API Key。\n\n留空 = Mock 模式（可走完流程，但识别结果是示例数据）",
        show="*",
        parent=root,
    )
    root.deiconify()
    key = (entered or "").strip()
    if key:
        save_api_key(key)
        log.info("已保存 API Key（%s）", mask(key))
    return key


def run_gui(port: int, log_path: Path, auto_open: bool = True) -> int:
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    root = tk.Tk()
    root.title(APP_DISPLAY_NAME)
    root.geometry("520x330")
    root.minsize(460, 300)

    key = load_api_key()
    if not key:
        key = ask_api_key(root)
    if key:
        os.environ["MAAS_API_KEY"] = key

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    dot = tk.Label(frame, text="●", fg="#d46b08", font=("Helvetica", 16))
    dot.grid(row=0, column=0, sticky="w")
    status_var = tk.StringVar(value="正在启动服务…")
    ttk.Label(frame, textvariable=status_var, font=("Helvetica", 13, "bold")).grid(
        row=0, column=1, sticky="w", padx=(6, 0)
    )

    url_var = tk.StringVar(value="—")
    ttk.Label(frame, text="访问地址").grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Label(frame, textvariable=url_var, foreground="#1677ff").grid(
        row=2, column=0, columnspan=3, sticky="w"
    )

    mode_var = tk.StringVar(value=f"模型：{mask(key)}")
    ttk.Label(frame, textvariable=mode_var, foreground="#888").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(2, 10)
    )

    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, columnspan=3, sticky="w")
    open_btn = ttk.Button(buttons, text="打开界面", state="disabled",
                          command=lambda: webbrowser.open(f"http://127.0.0.1:{port}"))
    open_btn.pack(side="left")
    ttk.Button(buttons, text="打开日志", command=lambda: open_path(log_path)).pack(
        side="left", padx=8
    )
    stop_btn = ttk.Button(buttons, text="停止并退出",
                          command=lambda: (handle.stop(), root.destroy()))
    stop_btn.pack(side="left")

    ttk.Label(frame, text="日志（启动失败时看这里）", foreground="#888").grid(
        row=5, column=0, columnspan=3, sticky="w", pady=(12, 4)
    )
    text = scrolledtext.ScrolledText(frame, height=7, font=("Menlo", 10))
    text.grid(row=6, column=0, columnspan=3, sticky="nsew")
    text.configure(state="normal")
    text.insert("end", f"数据目录：{log_path.parent.parent}\n")
    text.configure(state="disabled")
    frame.rowconfigure(6, weight=1)
    frame.columnconfigure(2, weight=1)

    handle = ServerHandle(port)
    handle.start()
    state = {"opened": False}

    def tick() -> None:
        if handle.error:
            dot.configure(fg="#cf1322")
            status_var.set("启动失败")
            url_var.set("请查看下方日志")
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("end", tail_log(log_path))
            text.configure(state="disabled")
            stop_btn.configure(text="关闭")
            return
        info = health(port)
        if info:
            dot.configure(fg="#389e0d")
            status_var.set(f"已就绪 · 端口 {port}")
            url_var.set(f"http://127.0.0.1:{port}")
            open_btn.configure(state="normal")
            mode_var.set(
                "模型：Mock 模式（未配置 Key）" if info.get("mock") else f"模型：{info.get('model')}"
            )
            if auto_open and not state["opened"]:
                state["opened"] = True
                webbrowser.open(f"http://127.0.0.1:{port}")
            return
        root.after(400, tick)

    def on_close() -> None:
        handle.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(300, tick)
    root.mainloop()
    handle.stop()
    return 0


def run_headless(port: int, open_browser: bool = True) -> int:
    handle = ServerHandle(port)
    handle.start()
    if not handle.wait_ready():
        print(f"❌ 启动失败：{handle.error}")
        print(tail_log(logs_dir() / "api.log"))
        return 1
    url = f"http://127.0.0.1:{port}"
    info = health(port) or {}
    print(f"✅ 已就绪：{url}（mock={info.get('mock')}）")
    if open_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        handle.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_DISPLAY_NAME} 启动器")
    parser.add_argument("--port", type=int, default=0, help="指定端口（默认自动挑 8000~8010）")
    parser.add_argument("--serve-only", action="store_true", help="不开窗口，仅启动服务")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    safe_streams()
    ensure_dirs()
    log_path = setup_logging()

    key = load_api_key()
    if key:
        os.environ["MAAS_API_KEY"] = key

    try:
        port = pick_port(args.port or None)
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 1

    if args.serve_only:
        return run_headless(port, open_browser=not args.no_browser)
    return run_gui(port, log_path, auto_open=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())

