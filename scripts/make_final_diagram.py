#!/usr/bin/env python3
"""最终版流程图：已实现（实线卡片） + 待开发（虚线卡片，标 P0/P1/P2）。

版式沿用「单图识别线路图」的深色风格；复用 make_flow_diagram.py 的绘制工具。
用法：python scripts/make_final_diagram.py
产物：docs/最终版流程图.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_flow_diagram import (
    ACC,
    BG,
    FG,
    TIME_FG,
    arrow,
    card,
    draw_rich,
    f_mono,
    f_sans,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "最终版流程图.png"

W, H = 2400, 3600

PLAN_FILL = "#171614"
PLAN_STROKE = "#4A463C"
PLAN_TITLE = "#C9C5B9"
PLAN_DESC = "#8A8578"
PLAN_AT = "#6F6B60"
PHASE_COLOR = {"P0": "#EF9F27", "P1": "#85B7EB", "P2": "#9C9A92"}


def dashed_rect(
    d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, color: str = PLAN_STROKE
) -> None:
    for x in range(x0, x1, 18):
        d.line([(x, y0), (min(x + 10, x1), y0)], fill=color, width=2)
        d.line([(x, y1), (min(x + 10, x1), y1)], fill=color, width=2)
    for y in range(y0, y1, 18):
        d.line([(x0, y), (x0, min(y + 10, y1))], fill=color, width=2)
        d.line([(x1, y), (x1, min(y + 10, y1))], fill=color, width=2)


def plan_box(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    name: str,
    desc: str,
    at: str,
    phase: str,
) -> None:
    d.rectangle([x, y, x + w, y + h], fill=PLAN_FILL)
    dashed_rect(d, x, y, x + w, y + h)

    d.text((x + 26, y + 14), name, font=f_sans(27), fill=PLAN_TITLE)
    d.text((x + w - 24, y + 16), phase, font=f_mono(22), fill=PHASE_COLOR[phase], anchor="ra")
    draw_rich(d, x + 26, y + 80, desc, 20, PLAN_DESC)
    d.text((x + 26, y + h - 26), at, font=f_sans(19), fill=PLAN_AT)


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((88, 66), "化工巡检 · 隐患识别 最终版流程图", font=f_sans(48), fill=FG)
    d.text(
        (88, 136),
        "实线卡片＝已实现（可在安装包里逐项验证）；虚线卡片＝待开发（标 P0 立即 / P1 一周 / P2 二期），并注明它插在主链的哪一步。",
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
    d.text((W - 124, 224), "实线＝已实现　虚线＝待开发", font=f_sans(22), fill=TIME_FG, anchor="ra")

    # ---------------- 左：已实现主链 ----------------
    cx, cw, ch, step, y0 = 260, 680, 144, 232, 400

    nodes = [
        ("双击启动", "接入", "~2 s", "PyInstaller · tkinter 启动器", "本地服务 127.0.0.1:8000（占用顺延 8010）"),
        ("上传巡检图", "接入", "~50 ms", "React 18 · AntD Upload · multipart", "JPEG bytes × N（可多选拖拽）"),
        ("接入与去重", "接入", "~20 ms", "FastAPI · sha256 去重", "frames 落盘 + 入队，同图不重复计费"),
        ("预处理", "预处理", "~30 ms", "Pillow · EXIF 纠正 · 长边 1280 · q88", "工作图 bytes（≤1280）"),
        ("视觉模型判定", "模型", "9~17 s", "千炼 MaaS · qwen3-vl-plus · 强制 JSON", "detections[]：类别/置信度/bbox/证据"),
        ("契约校验", "后处理", "<5 ms", "Pydantic 严格校验 · 失败重试 1 次", "VLJudgeOutput，多吐字段直接拒收"),
        ("规则裁决", "裁决", "~3 ms", "rules.decide() · 阈值 0.45/0.75 · 等级查表", "隐患/丢弃/待复核；等级条款只来自 YAML"),
        ("证据裁剪", "存储", "~15 ms", "坐标还原：0~1000 相对 → 像素 · 外扩 12%", "crops/{event_id}_crop.jpg（无框退整图）"),
        ("事件落库", "存储", "~8 ms", "SQLite · events / llm_usage / reviews", "engine 记 model / prompt / rule 三版本"),
        ("看板人工复核", "人工", "10~30 s/条", "AntD Table + Drawer · 驳回必选原因", "确认/驳回，原因入误报案例集"),
        ("导出台账", "存储", "~1 s", "CSV（UTF-8 BOM）· Excel 直接开", "隐患台账 / 统计 / Token 成本"),
    ]

    for i, (title, acc, t, tech, out) in enumerate(nodes):
        y = y0 + i * step
        card(d, cx, y, cw, ch, i + 1, title, acc, t, tech, out)
        if i < len(nodes) - 1:
            arrow(d, [(cx + cw // 2, y + ch + 10), (cx + cw // 2, y + step - 10)])

    # ---------------- 右：待开发能力 ----------------
    px, pw, ph, gap, py0 = 1080, 1180, 124, 24, 400
    d.text((px, 320), "待开发能力（14 项）", font=f_sans(30), fill=PLAN_TITLE)
    d.text(
        (px + 340, 328),
        "P0 立即 / P1 一周内 / P2 二期　·　每项都注明插入主链哪一步",
        font=f_sans(21),
        fill=TIME_FG,
    )

    plans = [
        ("① 分辨率分档", "HZ-01/03 用 1600~2048，大目标 1024；替代当前一刀切 1280（实测压缩掉 15 点）",
         "↳ 插入 ④ 预处理", "P0"),
        ("② 质量门禁 + 图像增强", "模糊/过暗直接判「需重拍」；CLAHE 去反光、暗光提亮，减少烂图硬判",
         "↳ 插入 ④ 预处理", "P0"),
        ("③ ROI 裁剪复判", "裁出人员/器材区域放大后再判，专救小目标（HZ-01 现在仅 40%）",
         "↳ 插入 ④→⑤ 之间", "P0"),
        ("④ 提示词 v2：否定清单 + 互斥判据", "写明「货区划线内堆放不算」「半遮挡不影响取用不算」；通道/门/器材互斥",
         "↳ 改 ⑤ 视觉模型判定", "P0"),
        ("⑤ OCR 读表（qwen-vl-ocr）", "表计读数抽取，补上 HZ-03 这项空白能力（模型/契约已就绪，只差调用）",
         "↳ 与 ⑤ 并行的支路", "P0"),
        ("⑥ crop-and-verify 二次确认", "把模型给的框裁出来再问「这里确实有 X 吗」，专杀幻觉式误报",
         "↳ 插入 ⑤→⑥ 之间", "P0"),
        ("⑦ 一致性聚合（3 票 / 双模型）", "用投票一致率替代不可信的 confidence（实测 0.94~0.98 全一样）",
         "↳ 增强 ⑤ 的输出", "P1"),
        ("⑧ 元素化改造", "模型只做元素识别（人/帽/门/通道/堆物），判定交给规则——可审计、可调参",
         "↳ 重构 ⑤ + ⑦", "P1"),
        ("⑨ 区域几何配置", "通道多边形、门前 1.5m 禁放区、器材期望位；规则才判得了堵塞/遮挡",
         "↳ 输入 ⑦ 规则裁决", "P1"),
        ("⑩ 正常样本集 + 阈值校准", "补 50 张无隐患图 → 真实误报率 → ROC 校准阈值（现 0.45/0.75 是拍的）",
         "↳ 校验 ⑨→⑩ 全链路", "P1"),
        ("⑪ 多帧一致性", "机器人连拍 3~5 帧，≥2 帧出现才判隐患；只 1 帧转人工",
         "↳ 插入 ⑩ 复核之前", "P1"),
        ("⑫ 分块 · 瓦片", "超大图/极远小目标切块推理，需配套「局部→全局」坐标还原（当前只在证据裁剪用了坐标换算）",
         "↳ 备选，暂缓", "P2"),
        ("⑬ 精调 SFT / LoRA", "377 张图 + 人工复核结果构造「图像→JSON」样本，上限可再抬 10~20 点",
         "↳ 替换 ⑤ 的模型", "P2"),
        ("⑭ 机器人接入", "ROS2 相机桥 + MQTT + 断网 spool，边缘只跑 YOLO（L2），联网时再走 VL 复核",
         "↳ 接在 ② 之前", "P2"),
    ]

    for i, (name, desc, at, phase) in enumerate(plans):
        plan_box(d, px, py0 + i * (ph + gap), pw, ph, name, desc, at, phase)

    # ---------------- 页脚 ----------------
    fy = 2920
    d.line([(88, fy), (W - 88, fy)], fill="#2E2E2B", width=2)

    lines = [
        ("已实现", "左列 11 步全部可验证：上传→判定→裁决→证据→落库→复核→导出；含超时降级、判据待确认标记、版本可追溯。"),
        (
            "待开发",
            "右列 14 项，其中 P0 六项（分辨率分档 / 质量门禁 / ROI / 提示词 v2 / OCR / 二次确认）预计可把召回从 55% 提到 65~70%。",
        ),
        (
            "实测基线",
            (
                "20 张现场图（可用「测试图片/」复现）：应急出口堵塞 4/5=80% · 消防器材遮挡 5/5=100% · "
                "未戴安全帽 2/5=40% · 消防通道堵塞 3/5=60%；单张 9~18 s；跨类误报 20%。"
            ),
        ),
        ("技术栈", "Python 3.11 · FastAPI · SQLite · React 18 + AntD 5 · 千炼 MaaS（OpenAI 兼容）· PyInstaller"),
    ]
    y = fy + 30
    for label, text in lines:
        d.text((88, y), label, font=f_sans(24), fill="#A8A69E")
        d.text((232, y), text, font=f_sans(23), fill=TIME_FG)
        y += 46

    d.text(
        (88, H - 54),
        "注：判定当前由模型给出、规则只负责定级与兜底；「元素化改造」完成后判定权才回到规则。虚线项均为规划，未在包内实现。",
        font=f_sans(22),
        fill="#5C5A54",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"✓ {OUT}  ({img.size[0]}x{img.size[1]}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

