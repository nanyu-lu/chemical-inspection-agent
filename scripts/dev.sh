#!/usr/bin/env bash
# 本地一键启动（MVP）：安装依赖 + 启动 API（含后台 worker）
set -euo pipefail
cd "$(dirname "$0")/.."

# 本机 uv 装在 ~/Library/Python/3.9/bin，其他环境可删掉这一行
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ 未找到 uv。安装：python3 -m pip install --user uv"
  exit 1
fi

if [ ! -f .env ]; then
  echo "❌ 缺少 .env。先执行：cp .env.example .env 并填入 MAAS_API_KEY"
  exit 1
fi

uv sync --dev
echo "▶ API: http://127.0.0.1:${PORT:-8000}/docs"
exec uv run uvicorn chem_inspect.api.app:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
