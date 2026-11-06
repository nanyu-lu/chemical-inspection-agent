#!/usr/bin/env python3
"""启动前自检：把「装完跑不起来」的问题提前到安装阶段暴露。

只用标准库，不依赖项目依赖，因此在 `uv sync` 之前也能跑。

用法：
    python scripts/preflight.py
    python scripts/preflight.py --online      # 额外验证一次真实接口调用
    python scripts/preflight.py --port 8000
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PASS, WARN, FAIL = "✓", "!", "✗"


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


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--online", action="store_true", help="额外验证一次真实接口调用")
    args = parser.parse_args()

    hard_fail = 0

    def report(mark: str, name: str, detail: str = "", hard: bool = False) -> None:
        nonlocal hard_fail
        print(f"[{mark}] {name}{(' — ' + detail) if detail else ''}")
        if mark == FAIL and hard:
            hard_fail += 1

    # 1. Python
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    # 打包运行在评委机器上，可能不是 3.11（pyproject 的 requires-python 管不到这里）
    if sys.version_info[:2] < (3, 11):  # noqa: UP036
        report(FAIL, "Python 版本", f"{ver}，需要 3.11 或以上", hard=True)
    else:
        report(PASS, "Python 版本", ver)

    # 2. 必要文件
    required = [
        "pyproject.toml",
        "config/hazard_rules.yaml",
        "config/hazard_taxonomy.yaml",
        "config/points.yaml",
    ]
    missing = [p for p in required if not (ROOT / p).exists()]
    report(FAIL if missing else PASS, "配置文件", "缺少：" + ", ".join(missing) if missing else "齐全",
           hard=True)

    dist_index = ROOT / "web" / "dist" / "index.html"
    if dist_index.exists():
        report(PASS, "前端构建产物", "web/dist/index.html")
    else:
        report(WARN, "前端构建产物", "缺少 web/dist（只能访问 API，无法打开页面）")

    # 3. 数据目录可写
    data_dir = ROOT / "data"
    try:
        (data_dir / "blobs").mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report(PASS, "数据目录可写", str(data_dir))
    except OSError as exc:
        report(FAIL, "数据目录可写", f"{data_dir} 不可写：{exc}", hard=True)

    # 4. 端口
    if port_free(args.port):
        report(PASS, f"端口 {args.port}", "空闲")
    else:
        report(WARN, f"端口 {args.port}", "已被占用，可用 PORT 环境变量或 --port 换一个")

    # 5. 密钥
    env = read_env(ROOT / ".env")
    key = env.get("MAAS_API_KEY", "").strip()
    if key and key.startswith("sk-"):
        report(PASS, "模型密钥", f"已配置（{key[:7]}***{key[-4:]}）")
    else:
        report(
            WARN,
            "模型密钥",
            "未配置 MAAS_API_KEY → 将以 Mock 模式运行（演示效果会失真，需要真实识别请填 .env）",
        )

    # 6. ffmpeg（仅提示，图片功能不依赖）
    import shutil as _shutil

    if _shutil.which("ffmpeg"):
        report(PASS, "ffmpeg", "已安装（支持视频抽帧）")
    else:
        report(WARN, "ffmpeg", "未安装 → 仅支持图片上传，视频会返回 400")

    # 7. 可选：真实连通性
    if args.online:
        base = env.get("MAAS_BASE_URL", "").strip()
        if not key or not base:
            report(WARN, "接口连通性", "缺少密钥或 base_url，跳过")
        else:
            req = urllib.request.Request(
                base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                report(PASS, "接口连通性", f"HTTP {resp.status}，{len(body.get('data', []))} 个模型")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                report(WARN, "接口连通性", f"探测失败（可离线继续）：{exc}")

    print()
    if hard_fail:
        print(f"❌ 有 {hard_fail} 项必须修复的问题，请处理后重试。")
        return 1
    print("✅ 自检通过，可以启动：./start.sh（Windows 用 start.bat）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
