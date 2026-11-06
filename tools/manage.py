#!/usr/bin/env python3
"""跨平台管理脚本（macOS / Windows 通用）。

    python tools/manage.py install [--api-key KEY] [--yes]
    python tools/manage.py start   [--port 8000] [--no-open]
    python tools/manage.py stop
    python tools/manage.py status

设计原则：
- 只用标准库，保证在 `uv sync` 之前就能跑（安装入口需要它）
- 真正的服务进程由 uv 启动，不用 Windows 服务/launchd，避免权限问题
- PID 与日志都落在包目录内，整包可随意挪动
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WIN = os.name == "nt"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
PID_FILE = DATA_DIR / ".server.pid"
LOG_FILE = LOG_DIR / "api.log"


def info(msg: str) -> None:
    print(f"[manage] {msg}")


def die(msg: str) -> None:
    print(f"[manage] ❌ {msg}")
    raise SystemExit(1)


# --------------------------------------------------------------------------- uv


def uv_prefix() -> list[str] | None:
    """返回调用 uv 的命令前缀；找不到返回 None。"""
    exe = shutil.which("uv")
    if exe:
        return [exe]
    try:
        subprocess.run(
            [sys.executable, "-m", "uv", "--version"],
            capture_output=True,
            check=True,
            timeout=20,
        )
        return [sys.executable, "-m", "uv"]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def ensure_uv() -> list[str]:
    prefix = uv_prefix()
    if prefix:
        return prefix
    info("未找到 uv，正在通过 pip 安装（需要网络）…")
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--user", "uv"])
    if code != 0:
        die("uv 安装失败。请手动执行：python -m pip install --user uv")
    prefix = uv_prefix()
    if not prefix:
        # pip --user 装完可能不在当前 PATH，可直接用模块方式
        prefix = [sys.executable, "-m", "uv"]
    return prefix


# --------------------------------------------------------------------------- env


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def write_api_key(key: str) -> None:
    env_path = ROOT / ".env"
    lines: list[str] = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("MAAS_API_KEY="):
                lines.append(f"MAAS_API_KEY={key}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"MAAS_API_KEY={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- http


def health(port: int, timeout: float = 2.0) -> dict | None:
    url = f"http://127.0.0.1:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def wait_health(port: int, seconds: float = 60.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if health(port):
            return True
        time.sleep(0.5)
    return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(json.loads(PID_FILE.read_text(encoding="utf-8"))["pid"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def pid_alive(pid: int) -> bool:
    if IS_WIN:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, check=False
        )
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- 命令


def cmd_install(args: argparse.Namespace) -> int:
    # 运行在评委机器上，可能不是 3.11
    if sys.version_info[:2] < (3, 11):  # noqa: UP036
        die(f"需要 Python 3.11+，当前 {sys.version.split()[0]}")

    uv = ensure_uv()
    info("安装依赖（uv sync --frozen）…")
    if subprocess.call(uv + ["sync", "--frozen"], cwd=ROOT) != 0:
        die("依赖安装失败，请检查网络后重试")

    env_path = ROOT / ".env"
    if not env_path.exists() and (ROOT / ".env.example").exists():
        shutil.copy2(ROOT / ".env.example", env_path)
        info("已生成 .env（来自 .env.example）")

    if args.api_key:
        write_api_key(args.api_key.strip())
        info("已写入 API Key 到 .env")
    elif not read_env(env_path).get("MAAS_API_KEY", "").startswith("sk-"):
        if args.yes or not sys.stdin.isatty():
            info("未提供 API Key → 将以 Mock 模式运行")
        else:
            print("请输入千炼 API Key（回车跳过 = Mock 模式，演示效果会失真）：")
            try:
                entered = input().strip()
            except EOFError:
                entered = ""
            if entered:
                write_api_key(entered)

    info("运行自检…")
    subprocess.call(uv + ["run", "python", "scripts/preflight.py"], cwd=ROOT)

    print()
    info("安装完成，下一步启动服务：")
    print("     macOS / Linux : ./start.sh     （或 bash start.sh）")
    print("     Windows       : 双击 start.bat （或 powershell -File start.ps1）")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    pid = read_pid()
    if pid and pid_alive(pid):
        info(f"服务已在运行（pid={pid}）→ http://127.0.0.1:{args.port}")
        if not args.no_open:
            webbrowser.open(f"http://127.0.0.1:{args.port}")
        return 0

    if not port_free(args.port):
        die(f"端口 {args.port} 被占用，请换一个：python tools/manage.py start --port 8010")

    uv = uv_prefix() or [sys.executable, "-m", "uv"]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cmd = uv + [
        "run",
        "uvicorn",
        "chem_inspect.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
    ]

    popen_kwargs: dict = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": open(LOG_FILE, "ab"),  # noqa: SIM115 - 交给子进程持有
        "stderr": subprocess.STDOUT,
    }
    if IS_WIN:
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    PID_FILE.write_text(
        json.dumps(
            {"pid": proc.pid, "port": args.port, "started_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    info(f"启动中（pid={proc.pid}），日志：{LOG_FILE}")
    if not wait_health(args.port):
        info("启动超时。最后 20 行日志：")
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]
            print("\n".join(lines))
        return 1

    url = f"http://127.0.0.1:{args.port}"
    info(f"已就绪：{url}")
    if not args.no_open:
        webbrowser.open(url)
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    pid = read_pid()
    if not pid:
        info("没有找到运行中的服务")
        return 0

    if pid_alive(pid):
        if IS_WIN:
            subprocess.call(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, 15)
            for _ in range(20):
                if not pid_alive(pid):
                    break
                time.sleep(0.25)
            else:
                os.kill(pid, 9)
        info("已停止")
    else:
        info("进程已不存在，清理 PID 文件")

    PID_FILE.unlink(missing_ok=True)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    pid = read_pid()
    data = health(args.port)
    if data:
        print(
            json.dumps(
                {"pid": pid, "url": f"http://127.0.0.1:{args.port}", "health": data},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    info("服务未运行")
    return 1


def main() -> int:
    default_port = int(os.environ.get("PORT", "8000"))
    parser = argparse.ArgumentParser(description="化工巡检 MVP 管理脚本")
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="安装依赖并生成 .env")
    p_install.add_argument("--api-key", default="")
    p_install.add_argument("--yes", action="store_true", help="不交互，缺失 Key 时用 Mock 模式")
    p_install.set_defaults(func=cmd_install)

    p_start = sub.add_parser("start", help="后台启动服务并打开浏览器")
    p_start.add_argument("--port", type=int, default=default_port)
    p_start.add_argument("--no-open", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="停止服务")
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="查看运行状态")
    p_status.add_argument("--port", type=int, default=default_port)
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

