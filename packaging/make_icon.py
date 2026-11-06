#!/usr/bin/env python3
"""生成应用图标（PNG / ICO / ICNS）。

设计：深蓝圆角底 + 白色盾牌 + 橙色警示三角 + 两条"巡检清单"线。
只用 Pillow，跨平台可跑；ICNS 仅在 macOS 且存在 iconutil 时生成。

用法：python packaging/make_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
BASE = 1024

NAVY = (15, 43, 70)
WHITE = (255, 255, 255)
ORANGE = (232, 121, 26)
LIGHT = (198, 214, 230)


def draw_icon(size: int = BASE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底
    pad = int(size * 0.06)
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad], radius=int(size * 0.22), fill=NAVY
    )

    # 盾牌轮廓（上宽下尖）
    w = size * 0.52
    left = (size - w) / 2
    top = size * 0.20
    bottom = size * 0.82
    shield = [
        (left, top),
        (left + w, top),
        (left + w, top + (bottom - top) * 0.55),
        (size / 2, bottom),
        (left, top + (bottom - top) * 0.55),
    ]
    d.polygon(shield, fill=WHITE)

    # 警示三角
    tri_w = w * 0.56
    tri_h = tri_w * 0.86
    cx = size / 2
    tri_top = top + (bottom - top) * 0.16
    d.polygon(
        [(cx, tri_top), (cx - tri_w / 2, tri_top + tri_h), (cx + tri_w / 2, tri_top + tri_h)],
        fill=ORANGE,
    )
    # 感叹号
    bar_w = max(3, int(size * 0.022))
    d.rounded_rectangle(
        [cx - bar_w / 2, tri_top + tri_h * 0.30, cx + bar_w / 2, tri_top + tri_h * 0.62],
        radius=bar_w / 2,
        fill=WHITE,
    )
    d.ellipse(
        [cx - bar_w * 0.75, tri_top + tri_h * 0.70, cx + bar_w * 0.75, tri_top + tri_h * 0.84],
        fill=WHITE,
    )

    # 底部两条"清单"线
    line_y = top + (bottom - top) * 0.80
    for i, ratio in enumerate((0.62, 0.44)):
        y = line_y + i * size * 0.055
        d.rounded_rectangle(
            [cx - w * ratio / 2, y, cx + w * ratio / 2, y + size * 0.026],
            radius=size * 0.013,
            fill=LIGHT,
        )

    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    png_path = OUT / "appicon.png"
    icon.save(png_path)

    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(OUT / "app.ico", sizes=ico_sizes)
    print(f"✓ {png_path.name} / app.ico")

    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT / "app.iconset"
        if iconset.exists():
            shutil.rmtree(iconset)
        iconset.mkdir()
        pairs = [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]
        for px, name in pairs:
            icon.resize((px, px), Image.LANCZOS).save(iconset / name)
        code = subprocess.call(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "app.icns")]
        )
        shutil.rmtree(iconset, ignore_errors=True)
        if code == 0:
            print("✓ app.icns")
        else:
            print("! iconutil 失败，mac 打包时可用 appicon.png 代替")
    else:
        print("! 非 macOS 或缺少 iconutil，跳过 icns（CI 的 mac job 会生成）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
