#!/usr/bin/env bash
# 构建交付包（Mac + Windows 同一个包）：前端预构建 + 白名单拷贝 + 双格式压缩 + 自检
#
#   ./scripts/build_release.sh            # 版本号取自 pyproject.toml
#   ./scripts/build_release.sh 0.1.1      # 指定版本号
#
# 产物：
#   dist/chem-inspect-v<版本>-mvp.tar.gz   （macOS / Linux，保留可执行位）
#   dist/chem-inspect-v<版本>-mvp.zip      （Windows，资源管理器可直接解压）
#   dist/SHA256SUMS
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(python3 -c "import re,pathlib;print(re.search(r'version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text(encoding='utf-8')).group(1))")}"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
DATE="$(date '+%Y-%m-%d %H:%M')"
NAME="chem-inspect-v${VERSION}-mvp"
STAGE="build/${NAME}"

echo "▶ 版本 ${VERSION}（commit ${COMMIT}）"

# ---------------------------------------------------------------- 1. 前端构建
echo "▶ 构建前端…"
(cd web && if [ -d node_modules ]; then npm run build; else npm ci --no-audit --no-fund && npm run build; fi)

# ---------------------------------------------------------------- 2. 暂存（白名单）
echo "▶ 拷贝文件…"
rm -rf build "dist/${NAME}.tar.gz" "dist/${NAME}.zip"
mkdir -p "$STAGE"

copy() {
  if [ -e "$1" ]; then
    mkdir -p "$STAGE/$(dirname "$1")"
    cp -R "$1" "$STAGE/$1"
  else
    echo "  ! 跳过（不存在）：$1"
  fi
}

for item in \
  src config scripts tools docs \
  pyproject.toml uv.lock .env.example README.md \
  install.sh start.sh stop.sh healthcheck.sh \
  install.ps1 start.ps1 stop.ps1 \
  install.bat start.bat stop.bat \
  测试图片
do
  copy "$item"
done

mkdir -p "$STAGE/web"
cp -R web/dist "$STAGE/web/dist"
mkdir -p "$STAGE/data"
cp -f data/.gitkeep "$STAGE/data/" 2>/dev/null || true

# 确保脚本可执行（zip→Windows 会忽略，tar.gz 保留）
chmod +x "$STAGE"/*.sh 2>/dev/null || true
chmod +x "$STAGE"/scripts/*.py "$STAGE"/scripts/*.sh 2>/dev/null || true

# ---------------------------------------------------------------- 3. 元信息
cat > "$STAGE/VERSION" <<EOF
version: ${VERSION}
built_at: ${DATE}
commit: ${COMMIT}
platform: macOS / Windows（通用，依赖在安装时按目标平台解析）
python: ">=3.11"
EOF

# ---------------------------------------------------------------- 4. 自检
echo "▶ 自检…"
fail=0
for must in pyproject.toml uv.lock src/chem_inspect/api/app.py web/dist/index.html \
            config/hazard_rules.yaml install.sh start.bat tools/manage.py VERSION; do
  [ -e "$STAGE/$must" ] || { echo "  ✗ 缺少 $must"; fail=1; }
done
[ -e "$STAGE/.env" ] && { echo "  ✗ 包里出现了 .env（含密钥）"; fail=1; }
[ -e "$STAGE/data/app.db" ] && { echo "  ✗ 包里出现了演示数据库 data/app.db"; fail=1; }
if grep -rIl "sk-ws-" "$STAGE" >/dev/null 2>&1; then
  echo "  ✗ 包内发现 API Key 明文"; fail=1
fi
[ "$fail" -ne 0 ] && { echo "❌ 自检未通过，终止打包"; exit 1; }
echo "  ✓ 文件齐全 / 无 .env / 无演示库 / 无密钥明文"

# ---------------------------------------------------------------- 5. 压缩
echo "▶ 压缩…"
mkdir -p dist
tar -czf "dist/${NAME}.tar.gz" -C build "$NAME"
python3 scripts/pack_zip.py "$STAGE" "dist/${NAME}.zip"

# ---------------------------------------------------------------- 6. 校验和
python3 scripts/write_sha.py "$NAME"

echo ""
echo "✅ 打包完成："
ls -lh dist/"${NAME}".tar.gz dist/"${NAME}".zip | awk '{print "   " $9 "  " $5}'
echo ""
echo "下一步（务必做）：解压到空目录验证一次"
echo "   rm -rf /tmp/rel-test && mkdir -p /tmp/rel-test && tar -xzf dist/${NAME}.tar.gz -C /tmp/rel-test"
echo "   cd /tmp/rel-test/${NAME} && ./install.sh --yes && ./start.sh --no-open"
