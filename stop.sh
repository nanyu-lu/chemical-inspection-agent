#!/usr/bin/env bash
# 停止服务（macOS / Linux）
set -uo pipefail
cd "$(dirname "$0")"
exec python3 tools/manage.py stop "$@"
