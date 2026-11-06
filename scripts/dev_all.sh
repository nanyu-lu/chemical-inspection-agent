#!/usr/bin/env bash
# 一条命令起「后端 + 前端」：用于本地演示
#   后端  http://127.0.0.1:8000/docs
#   前端  http://127.0.0.1:5173
set -euo pipefail
cd "$(dirname "$0")/.."

# 本机 uv 装在 ~/Library/Python/3.9/bin，其他环境可删掉这一行
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

if [ ! -f .env ]; then
  echo "❌ 缺少 .env。先执行：cp .env.example .env 并填入 MAAS_API_KEY"
  exit 1
fi

uv sync --dev

if [ ! -d web/node_modules ]; then
  echo "▶ 首次安装前端依赖…"
  (cd web && npm install --no-audit --no-fund)
fi

API_PORT="${PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

uv run uvicorn chem_inspect.api.app:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
(cd web && npx vite --host 127.0.0.1 --port "$WEB_PORT") &
WEB_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
  kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "▶ 后端 API : http://127.0.0.1:${API_PORT}/docs"
echo "▶ 前端页面 : http://127.0.0.1:${WEB_PORT}"
echo "▶ Ctrl+C 退出"
wait
