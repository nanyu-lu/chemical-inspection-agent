#!/usr/bin/env python3
"""生成「运行流程图」PNG（给评委看的一页纸说明）。

内容分三段：
  ① 评委看到的操作流程
  ② 一张图片进来后系统内部发生了什么
  ③ 三条保障（降级 / 判据待确认 / 全程留痕）

用法：python scripts/make_flow_diagram.py
产物：docs/运行流程图.png
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "运行流程图.png"

W, H = 2400, 1620
FONT_PATHS = ("/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc")

NAVY = "#0f2b46"
GRAY = "#595959"
LIGHT = "#8c8c8c"
BLUE = "#1677ff"
CYAN = "#08979c"
ORANGE = "#d46b08"
GREEN = "#389e0d"
RED = "#cf1322"
PURPLE = "#531dab"

BOX_STYLES = {
    "user": ("#e6f4ff", BLUE),
    "sys": ("#f5f5f5", "#434343"),
    "model": ("#fff2e8", ORANGE),
    "rule": ("#f0f5ff", "#2f54eb"),
    "store": ("#f6ffed", GREEN),
    "human": ("#f9f0ff", PURPLE),
    "warn": ("#fffbe6", "#ad8b00"),
}


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("找不到中文字体")


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        if draw.textlength(current + ch, font=f) <= width:
            current += ch
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def arrow(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], color: str = LIGHT) -> None:
    for start, end in itertools.pairwise(points):
        draw.line([start, end], fill=color, width=4)
    (x1, y1), (x2, y2) = points[-2], points[-1]
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 15
    draw.polygon(
        [
            (x2, y2),
            (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45)),
            (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45)),
        ],
        fill=color,
    )


def box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    index: str,
    title: str,
    body: str,
    style: str,
    *,
    title_size: int = 32,
    body_size: int = 23,
) -> None:
    x0, y0, x1, y1 = xy
    fill, border = BOX_STYLES[style]
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=fill, outline=border, width=3)

    r, cx, cy = 22, x0 + 34, y0 + 34
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=border)
    num_font = font(24)
    nw = draw.textlength(index, font=num_font)
    draw.text((cx - nw / 2, cy - 16), index, font=num_font, fill="white")

    draw.text((x0 + 70, y0 + 18), title, font=font(title_size), fill=NAVY)

    if body:
        f = font(body_size)
        y = y0 + 66
        for line in wrap(draw, body, f, x1 - x0 - 44)[:5]:
            draw.text((x0 + 22, y), line, font=f, fill=GRAY)
            y += body_size + 8


def section(draw: ImageDraw.ImageDraw, y: int, text: str, color: str, sub: str = "") -> None:
    draw.rectangle([80, y, 92, y + 40], fill=color)
    draw.text((112, y - 2), text, font=font(38), fill=color)
    if sub:
        offset = draw.textlength(text, font=font(38))
        draw.text((112 + offset + 24, y + 8), sub, font=font(24), fill=LIGHT)


def main() -> int:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    d.text((80, 54), "化工巡检 · 隐患识别 Agent（MVP）", font=font(58), fill=NAVY)
    d.text((80, 128), "评委验证流程 & 一张图片进来后系统做了什么", font=font(30), fill=GRAY)

    # ---------------- ① 用户流程 ----------------
    section(d, 208, "① 评委看到的操作流程（约 3 分钟）", BLUE, "双击即可用，不需要装 Python / Node / 数据库")

    bw, bh, gap = 520, 156, 34
    x_start, row1, row2 = 84, 272, 486

    steps = [
        ("1", "双击应用", "macOS 拖入 Applications\nWindows 双击安装包\n首次打开按说明放行一次", "user"),
        ("2", "启动器窗口", "显示「已就绪 · 端口 8000」\n自动打开浏览器，无需手输地址", "user"),
        ("3", "上传巡检", "选点位（如 3 号库房东侧通道）\n拖入 1~N 张现场图", "user"),
        ("4", "自动识别", "每张 10~15 秒\n进度条自动刷新", "model"),
        ("5", "隐患看板", "证据图 + 等级 + 置信度 + 判定理由\n依据条款 / 模型版本一并展示", "sys"),
        ("6", "人工复核", "确认 或 驳回\n驳回必须选原因（误报 / 判错 / 看不清…）", "human"),
        ("7", "导出台账", "一键导出 CSV\nExcel 直接打开（UTF-8 BOM）", "store"),
        ("8", "数据回流", "驳回原因进入误报案例集\n用于后续提示词与规则调优", "rule"),
    ]

    for i, (idx, title, body, style) in enumerate(steps):
        col, row = i % 4, i // 4
        x0 = x_start + col * (bw + gap)
        y0 = row1 if row == 0 else row2
        box(d, (x0, y0, x0 + bw, y0 + bh), idx, title, body, style)

    for row_y in (row1, row2):
        for col in range(3):
            ax = x_start + col * (bw + gap) + bw
            arrow(d, [(ax + 4, row_y + bh // 2), (ax + gap - 6, row_y + bh // 2)])

    x4 = x_start + 3 * (bw + gap) + bw // 2
    x5 = x_start + bw // 2
    arrow(d, [(x4, row1 + bh + 2), (x4, row1 + bh + 22), (x5, row1 + bh + 22), (x5, row2 - 4)])

    # ---------------- ② 系统链路 ----------------
    section(d, 706, "② 一张图片进来后发生了什么", CYAN, "模型只负责「看见什么」，等级与条款由规则表决定")

    bw2, gap2, x2, y_top, h2 = 292, 30, 84, 772, 196
    chain = [
        ("1", "接入", "POST /frames\nsha256 去重\n落盘 + 入队", "sys"),
        ("2", "预处理", "EXIF 纠正\n长边压到 1280\n转 JPEG", "sys"),
        ("3", "视觉模型", "千炼 qwen3-vl-plus\n单图多类别判定\n强制 JSON 输出", "model"),
        ("4", "契约校验", "Pydantic 严格校验\n不合格重试 1 次\n再失败转人工", "sys"),
        ("5", "规则裁决", "阈值三分支\n等级 / 处置建议\n条款只来自规则表", "rule"),
        ("6", "证据裁剪", "0~1000 相对坐标\n换算像素 + 外扩\n无框则退化为整图", "sys"),
        ("7", "落库", "SQLite 事件表\nappend-only\n证据图存本地", "store"),
    ]
    for i, (idx, title, body, style) in enumerate(chain):
        x0 = x2 + i * (bw2 + gap2)
        box(d, (x0, y_top, x0 + bw2, y_top + h2), idx, title, body, style)
        if i < len(chain) - 1:
            ax = x0 + bw2
            arrow(d, [(ax + 3, y_top + h2 // 2), (ax + gap2 - 5, y_top + h2 // 2)])

    d.text(
        (84, y_top + h2 + 14),
        "降级路径：模型超时 / 429 / 输出不合法 → 重试 → 仍失败则生成「需人工判定」事件（标 degraded），不丢帧、不返回 500",
        font=font(24),
        fill=RED,
    )

    # ---------------- ③ 三条保障 ----------------
    section(d, 1050, "③ 三条保障（化工场景的底线）", GREEN, "结果只作辅助，人工确认后才生效")

    cards = [
        ("断网 / 超时", "自动降级为「人工判定」，事件仍入库并标记 degraded；\n数据本地留存，恢复后可重跑。", "warn"),
        ("判据未确认", "企业判定标准原文未到时，每条都标「判据待专家确认」，\n只作辅助提示，不自动下发处置。", "warn"),
        ("全程可追溯", "记录模型 / 提示词 / 规则版本 + 复核人 + 驳回原因，\n任何一个结论都能回答「依据是什么」。", "store"),
    ]
    cw, cgap = 740, 34
    for i, (title, body, style) in enumerate(cards):
        x0 = 84 + i * (cw + cgap)
        box(d, (x0, 1112, x0 + cw, 1262), str(i + 1), title, body, style, title_size=30, body_size=23)

    # ---------------- 底部数据 ----------------
    d.rounded_rectangle([84, 1300, W - 84, 1420], radius=16, fill="#fafafa", outline="#e0e0e0", width=2)
    d.text((112, 1322), "真实数据基线（25 张现场图）", font=font(28), fill=NAVY)
    d.text(
        (112, 1364),
        "应急出口堵塞 5/5=100%    消防器材遮挡 4/5=80%    未戴安全帽 2/5=40%    消防通道堵塞 2/5=40%    "
        "单张 9~15 秒",
        font=font(26),
        fill=GRAY,
    )

    chips = ["Python 3.11", "FastAPI", "SQLite", "React + AntD", "千炼 MaaS（OpenAI 兼容）", "PyInstaller"]
    cx = 84
    for chip in chips:
        f = font(22)
        tw = d.textlength(chip, font=f)
        d.rounded_rectangle([cx, 1460, cx + tw + 36, 1508], radius=24, fill="#eef4ff",
                            outline="#adc6ff", width=2)
        d.text((cx + 18, 1470), chip, font=f, fill=BLUE)
        cx += tw + 52

    d.text((84, 1536), "注：本图为 MVP 现状；人员超员计数等类别列为二期，交给 YOLO 方向。",
           font=font(22), fill=LIGHT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"✓ {OUT}  ({img.size[0]}x{img.size[1]}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

