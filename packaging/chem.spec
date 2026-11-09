# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（macOS / Windows 共用）。

产物：
  macOS  → build/dist/化工巡检.app
  Windows→ build/dist/ChemInspect/ChemInspect.exe

打包后会走 sys.frozen 分支：
  资源在 bundle 内（只读），数据写到用户目录（见 src/chem_inspect/paths.py）
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()                  # packaging/
PROJECT = ROOT.parent                            # 项目根

datas = [
    (str(PROJECT / "web" / "dist"), "web/dist"),
    (str(PROJECT / "config"), "config"),
    (str(PROJECT / "packaging" / "首次打开说明.txt"), "."),
]
for extra in ("交付说明.md",):
    candidate = PROJECT / extra
    if candidate.exists():
        datas.append((str(candidate), "."))
test_images = PROJECT / "测试图片"
if test_images.exists():
    datas.append((str(test_images), "测试图片"))

# uvicorn 在运行时按配置动态导入协议/生命周期实现，必须显式声明
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [str(PROJECT / "tools" / "launcher.py")],
    pathex=[str(PROJECT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[str(ROOT / "rthook_crashlog.py")],
    excludes=["pytest", "respx", "ruff", "packaging"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChemInspect",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 窗口模式：不弹黑框
    icon=str(ROOT / ("app.icns" if sys.platform == "darwin" else "app.ico")),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ChemInspect",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="化工巡检.app",
        icon=str(ROOT / "app.icns"),
        bundle_identifier="com.scouter.chenminspect",
        info_plist={
            "CFBundleDisplayName": "化工巡检",
            "CFBundleName": "ChemInspect",
            "CFBundleShortVersionString": "0.2.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
