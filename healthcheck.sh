#!/usr/bin/env bash
# 健康检查：服务正常返回 0，否则返回非 0（便于外部监控调用）
set -uo pipefail
cd "$(dirname "$0")"
exec python3 tools/manage.py status "$@"
