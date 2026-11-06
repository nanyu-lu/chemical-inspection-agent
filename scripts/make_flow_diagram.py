#!/usr/bin/env python3
"""生成「单图识别线路图」PNG（深色线路图风格）。

版式参考 `111单图识别线路图.html`（深底、居中卡片链、左色条 + 序号圆点、
技术栈/输入输出两行注释、实线主链路 + 橙色虚线支路），**内容为本项目真实实现**。

用法：python scripts/make_flow_diagram.py
产物：docs/运行流程图.png
"""

from __future__ import annotations

import itertools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "运行流程图.png"

S = 2  # 2 倍图，保证在微信/文档里清晰
W, H = 2400, 3300

SANS = "/System/Library/Fonts/STHeiti Medium.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

BG = "#141413"
CARD = "#1A1A19"
CARD_STROKE = "#3A3A36"
CIRCLE = "#1F1F1E"
CIRCLE_STROKE = "#454541"
FG = "#EDEBE6"
MONO_FG = "#9C9A92"
OUT_FG = "#7E7C75"
TIME_FG = "#6F6D66"
NUM_FG = "#B4B2A9"
LINE = "#7F7D76"
DASH = "#EF9F27"

ACC = {
    "接入": "#85B7EB",
    "预处理": "#FAC775",
    "模型": "#5DCAA5",
    "后处理": "#AFA9EC",
    "裁决": "#F09595",
    "存储": "#C0DD97",
    "人工": "#D3ADF7",
}

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def f_sans(size: int) -> ImageFont.FreeTypeFont:
    key = ("sans", size)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(SANS, size)
    return _cache[key]


def f_mono(size: int) -> ImageFont.FreeTypeFont:
    key = ("mono", size)
    if key not in _cache:
        try:
            _cache[key] = ImageFont.truetype(MONO, size)
        except OSError:
            _cache[key] = ImageFont.truetype(SANS, size)
    return _cache[key]


def arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: str = LINE,
          dashed: bool = False, head: bool = True) -> None:
    for (x1, y1), (x2, y2) in itertools.pairwise(points):
        if dashed:
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length == 0:
                continue
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            pos = 0.0
            while pos < length:
                end = min(pos + 12, length)
                draw.line(
                    [(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)],
                    fill=color,
                    width=3,
                )
                pos += 20
        else:
            draw.line([(x1, y1), (x2, y2)], fill=color, width=3)
    if not head:
        return
    (px, py), (qx, qy) = points[-2], points[-1]
    if qy != py:  # 竖向
        step = 1 if qy > py else -1
        draw.polygon([(qx, qy), (qx - 9, qy - 15 * step), (qx + 9, qy - 15 * step)], fill=color)
    else:  # 横向
        step = 1 if qx > px else -1
        draw.polygon([(qx, qy), (qx - 15 * step, qy - 9), (qx - 15 * step, qy + 9)], fill=color)


def draw_rich(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    size: int,
    color: str,
    anchor: str = "la",
) -> None:
    """中英混排：ASCII 用等宽字体（像代码），中文用黑体（Menlo 没有中文字形，会变方块）。"""
    runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
    for is_ascii, group in itertools.groupby(text, key=lambda ch: ch.isascii()):
        segment = "".join(group)
        runs.append((segment, f_mono(size) if is_ascii else f_sans(size)))

    total = sum(draw.textlength(seg, font=f) for seg, f in runs)
    if anchor.startswith("r"):
        x -= int(total)
    elif anchor.startswith("m"):
        x -= int(total / 2)
    for segment, f in runs:
        draw.text((x, y), segment, font=f, fill=color, anchor="ls")
        x += draw.textlength(segment, font=f)


def card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    index: int,
    title: str,
    acc_key: str,
    time_text: str,
    tech: str,
    output: str,
) -> None:
    color = ACC[acc_key]
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=CARD, outline=CARD_STROKE, width=2)
    draw.rectangle([x + 2, y + 6, x + 10, y + h - 6], fill=color)

    cx, cy, r = x - 46, y + h // 2, 26
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CIRCLE, outline=CIRCLE_STROKE, width=2)
    label = str(index)
    draw.text((cx, cy), label, font=f_mono(24), fill=NUM_FG, anchor="mm")

    draw.text((x + 34, y + 22), title, font=f_sans(34), fill=FG)
    draw.text((x + w - 28, y + 30), time_text, font=f_mono(22), fill=TIME_FG, anchor="ra")
    draw_rich(draw, x + 34, y + 94, tech, 21, MONO_FG)
    draw.text((x + 34, y + 114), output, font=f_sans(20), fill=OUT_FG)


def branch(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    desc: str,
) -> None:
    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=14, fill="#1E1B15", outline="#7A5A22", width=2
    )
    draw_rich(draw, x + 24, y + 46, title, 22, DASH)
    draw_rich(draw, x + 24, y + 98, desc, 20, MONO_FG)


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((88, 66), "化工巡检 · 隐患识别 单图线路图", font=f_sans(48), fill=FG)
    d.text(
        (88, 136),
        "一张巡检图从上传到台账导出，全程一条主线；第 5、7 步分出条件支路（异常降级 / 阈值分流），最终汇入人工复核。",
        font=f_sans(24),
        fill=TIME_FG,
    )

    # ---------------- 图例 ----------------
    d.rounded_rectangle([88, 196, W - 88, 276], radius=14, fill="#191918", outline="#2E2E2B", width=2)
    x = 124
    for key, color in ACC.items():
        d.rectangle([x, 216, x + 6, 256], fill=color)
        d.text((x + 16, 224), key, font=f_sans(24), fill="#A8A69E")
        x += 16 + int(d.textlength(key, font=f_sans(24))) + 44
    d.text((W - 124, 224), "实线＝主链路　虚线＝条件支路", font=f_sans(22), fill=TIME_FG, anchor="ra")

    # ---------------- 主链路 ----------------
    cx, cw, ch, step, y0 = 700, 800, 144, 232, 320

    nodes = [
        ("双击启动", "接入", "~2 s", "PyInstaller · tkinter 启动器", "本地服务 127.0.0.1:8000（被占用自动顺延 8010）"),
        ("上传巡检图", "接入", "~50 ms", "React 18 · AntD Upload · multipart", "JPEG bytes × N（可多选拖拽）"),
        ("接入与去重", "接入", "~20 ms", "FastAPI · sha256 去重", "frames 落盘 + 入队（同一张图不重复计费）"),
        ("预处理", "预处理", "~30 ms", "Pillow · EXIF 纠正 · 长边 1280 · JPEG q88", "工作图 bytes（≤1280，控制 token 成本）"),
        ("视觉模型判定", "模型", "9~17 s", "千炼 MaaS · qwen3-vl-plus · 强制 JSON", "detections[]：类别 / 置信度 / bbox / 证据描述"),
        ("契约校验", "后处理", "<5 ms", "Pydantic 严格校验 · 失败重试 1 次", "VLJudgeOutput（多吐字段直接拒收，防幻觉）"),
        ("规则裁决", "裁决", "~3 ms", "rules.decide() · 阈值 0.45/0.75 · 等级查表", "隐患 / 丢弃 / 待复核；等级与条款只来自 YAML"),
        ("证据裁剪", "存储", "~15 ms", "0~1000 相对坐标→像素 · 外扩 12%", "crops/{event_id}_crop.jpg（无框退化为整图）"),
        ("事件落库", "存储", "~8 ms", "SQLite · events / llm_usage / reviews", "engine 记 model / prompt / rule 三版本"),
        ("看板人工复核", "人工", "10~30 s/条", "AntD Table + Drawer · 驳回必选原因", "确认 / 驳回（原因入误报案例集）"),
        ("导出台账", "存储", "~1 s", "CSV（UTF-8 BOM）· Excel 直接打开", "隐患台账 / 统计 / Token 成本"),
    ]

    for i, (title, acc, t, tech, out) in enumerate(nodes):
        y = y0 + i * step
        card(d, cx, y, cw, ch, i + 1, title, acc, t, tech, out)
        if i < len(nodes) - 1:
            arrow(d, [(cx + cw // 2, y + ch + 10), (cx + cw // 2, y + step - 10)])

    # ---------------- 条件支路 ----------------
    bx, bw, bh = 1630, 560, 132
    y5 = y0 + 4 * step + ch // 2
    y7 = y0 + 6 * step + ch // 2
    y10 = y0 + 9 * step + ch // 2

    branch(d, bx, y5 - bh // 2, bw, bh, "异常支路 · 超时 / 429 / 非法 JSON",
           "重试 1 次 → 仍失败转人工（标 degraded）")
    arrow(d, [(cx + cw, y5), (bx - 8, y5)], color=DASH, dashed=True)

    branch(d, bx, y7 - bh // 2, bw, bh, "阈值分流 · conf<0.45 丢弃",
           "0.45~0.75 强制复核；原响应留存")
    arrow(d, [(cx + cw, y7), (bx - 8, y7)], color=DASH, dashed=True)

    # 支路回流到第 10 步（人工复核）：走卡片与支路框之间的空隙，避免穿过支路框
    trunk = cx + cw + 64
    arrow(
        d,
        [(trunk, y5 + bh // 2), (trunk, y10), (cx + cw + 6, y10)],
        color=DASH,
        dashed=True,
    )
    d.line([(trunk, y7 + bh // 2), (trunk, y10)], fill=DASH, width=3)

    # ---------------- 页脚说明 ----------------
    fy = y0 + 10 * step + ch + 96
    d.line([(88, fy), (W - 88, fy)], fill="#2E2E2B", width=2)

    lines = [
        ("三条保障", "断网/超时自动降级为人工判定；判据未确认时每条标「判据待专家确认」；全程记录模型/提示词/规则版本 + 复核人。"),
        (
            "实测基线",
            (
                "20 张现场图（可用「测试图片/」复现）：应急出口堵塞 4/5=80% · 消防器材遮挡 5/5=100% · "
                "未戴安全帽 2/5=40% · 消防通道堵塞 3/5=60%；单张 9~18 s；跨类误报 20%。"
            ),
        ),
        ("技术栈", "Python 3.11 · FastAPI · SQLite · React 18 + AntD 5 · 千炼 MaaS（OpenAI 兼容）· PyInstaller"),
    ]
    y = fy + 32
    for label, text in lines:
        d.text((88, y), label, font=f_sans(24), fill="#A8A69E")
        d.text((232, y), text, font=f_sans(24), fill=TIME_FG)
        y += 46

    d.text(
        (88, H - 56),
        "注：本图为 MVP 现状；判定由模型给出、规则负责定级与兜底。人员超员计数等类别列为二期，交给 YOLO 方向。",
        font=f_sans(22),
        fill="#5C5A54",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"✓ {OUT}  ({img.size[0]}x{img.size[1]}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

