#!/usr/bin/env bash
# 启动服务并打开浏览器（macOS / Linux）
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo "❌ 未找到 Python。请先安装 Python 3.11+：https://www.python.org/downloads/"
  exit 1
fi

exec "$PY" tools/manage.py start "$@"
