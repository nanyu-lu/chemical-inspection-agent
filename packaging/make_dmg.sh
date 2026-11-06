#!/usr/bin/env bash
# 把 PyInstaller 产出的 .app 打成 dmg（含 Applications 快捷方式 + 首次打开说明）
#
# 前置：uv run pyinstaller packaging/chem.spec --noconfirm
# 产物：dist/chem-inspect-v<版本>-<arch>.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(python3 -c "import re,pathlib;print(re.search(r'version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text(encoding='utf-8')).group(1))")}"
APP="build/dist/化工巡检.app"
ARCH="$(uname -m)"

if [ ! -d "$APP" ]; then
  echo "❌ 找不到 $APP，请先执行：uv run pyinstaller packaging/chem.spec --noconfirm"
  exit 1
fi

# Apple Silicon 上未签名的二进制无法运行，至少做一次 ad-hoc 签名
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
  echo "✓ ad-hoc 签名完成（未公证，首次打开仍需右键→打开）"
fi

STAGE="build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp -f "packaging/首次打开说明.txt" "$STAGE/"

mkdir -p dist
OUT="dist/chem-inspect-v${VERSION}-${ARCH}.dmg"
rm -f "$OUT"
hdiutil create -volname "化工巡检" -srcfolder "$STAGE" -ov -format UDZO -quiet "$OUT"

echo "✓ ${OUT}  ($(du -h "$OUT" | cut -f1))"
shasum -a 256 "$OUT"
