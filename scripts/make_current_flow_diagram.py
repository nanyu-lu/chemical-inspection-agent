"""生成「当前单张图片运行流程」PNG。

内容以当前代码为准：
- 上传 → Frame(pending) → worker → judge_frame_multi
- CHECK_ITEMS_PILOT=true：CI-06/CI-11 共 9 个子项，每个子项一次 VL 调用
- CHECK_ITEMS_PILOT=false：回退旧 HZ-01..06 链路
- 多事件落库 → API frame.events[] → 前端任务详情/看板/统计

用法：.venv/bin/python scripts/make_current_flow_diagram.py
产物：docs/当前单图运行流程图.png
"""

from __future__ import annotations

import itertools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "当前单图运行流程图.png"

W, H = 2200, 2920
SANS = "/System/Library/Fonts/STHeiti Medium.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

BG = "#141413"
CARD = "#1A1A19"
CARD_STROKE = "#3A3A36"
FG = "#EDEBE6"
MUTED = "#B4B2A9"
DIM = "#7E7C75"
LINE = "#7F7D76"
BLUE = "#85B7EB"
GREEN = "#5DCAA5"
AMBER = "#FAC775"
RED = "#F09595"
PURPLE = "#AFA9EC"
LIME = "#C0DD97"

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    key = ("mono" if mono else "sans", size)
    if key not in _cache:
        path = MONO if mono else SANS
        try:
            _cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _cache[key] = ImageFont.truetype(SANS, size)
    return _cache[key]


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int,
         color: str = FG, mono: bool = False) -> None:
    draw.text(xy, value, font=font(size, mono), fill=color)


def arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: str = LINE) -> None:
    for (x1, y1), (x2, y2) in itertools.pairwise(points):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=4)
    (px, py), (qx, qy) = points[-2], points[-1]
    if qy != py:
        step = 1 if qy > py else -1
        draw.polygon([(qx, qy), (qx - 11, qy - 18 * step), (qx + 11, qy - 18 * step)], fill=color)
    else:
        step = 1 if qx > px else -1
        draw.polygon([(qx, qy), (qx - 18 * step, qy - 11), (qx - 18 * step, qy + 11)], fill=color)


def box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    lines: list[str],
    accent: str,
    *,
    title_size: int = 27,
    line_size: int = 20,
    fill: str = CARD,
) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=fill, outline=CARD_STROKE, width=2)
    draw.rectangle([x + 2, y + 9, x + 12, y + h - 9], fill=accent)
    text(draw, (x + 32, y + 18), title, title_size, FG)
    for idx, line in enumerate(lines):
        text(draw, (x + 32, y + 62 + idx * 30), line, line_size, MUTED)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str, color: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill="#22221F", outline=color, width=2)
    text(draw, (x + 18, y + 12), label, 19, color)


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    text(draw, (100, 58), "单张图片在当前 Agent 中的运行流程", 52, FG)
    text(
        draw,
        (102, 132),
        "2026-11-09 · 45 项试点 CI-06/CI-11（9 子项）+ 旧 HZ-01..06 回退 · qwen3-vl-plus · 长边 1280",
        24,
        MUTED,
    )
    draw.line([(100, 188), (W - 100, 188)], fill="#2E2E2B", width=2)

    mx, mw = 650, 900
    cx = mx + mw // 2
    card1_y, card2_y, card3_y, card4_y, dec_y = 230, 380, 530, 680, 830

    box(draw, mx, card1_y, mw, 110, "① 前端上传页 /upload",
        ["选择点位 → 拖拽 1 张图片 → 提交（React + AntD）"], BLUE)
    box(draw, mx, card2_y, mw, 110, "② FastAPI 接收",
        ["POST /api/v1/tasks → POST /api/v1/tasks/{id}/frames",
         "校验图片 · sha256 去重 · 原图写 BlobStore"], BLUE)
    box(draw, mx, card3_y, mw, 110, "③ 建 Frame(pending)",
        ["写入 SQLite tasks / frames；同一任务内重复图直接跳过"], PURPLE)
    box(draw, mx, card4_y, mw, 110, "④ FrameWorker 领帧",
        ["DB 轮询 claim（默认并发 2）→ 读原图 + 点位上下文",
         "调用 pipeline.judge_frame_multi()"], GREEN)

    # 主链箭头
    arrow(draw, [(cx, card1_y + 110), (cx, card2_y)])
    arrow(draw, [(cx, card2_y + 110), (cx, card3_y)])
    arrow(draw, [(cx, card3_y + 110), (cx, card4_y)])
    arrow(draw, [(cx, card4_y + 110), (cx, dec_y)])

    # 分支判断
    draw.rounded_rectangle([mx, dec_y, mx + mw, dec_y + 120], radius=18, fill="#211F18",
                           outline=AMBER, width=3)
    text(draw, (mx + 32, dec_y + 18), "⑤ 是否启用 45 项试点？", 28, AMBER)
    text(draw, (mx + 32, dec_y + 62),
         "CHECK_ITEMS_PILOT=true 且 config/pilot_check_items.yaml enabled=true", 20, MUTED)

    split_y = 965
    left_cx, right_cx = 530, 1670
    arrow(draw, [(cx, dec_y + 120), (cx, split_y)], AMBER)
    draw.line([(left_cx, split_y), (right_cx, split_y)], fill=AMBER, width=4)
    arrow(draw, [(left_cx, split_y), (left_cx, 1010)], BLUE)
    arrow(draw, [(right_cx, split_y), (right_cx, 1010)], GREEN)

    # 左：旧链路
    text(draw, (120, 975), "旧链路（回退）", 26, BLUE)
    text(draw, (120, 1005), "CHECK_ITEMS_PILOT=false", 18, DIM, mono=True)
    box(draw, 120, 1040, 820, 170, "⑥A 旧 6 类 prompt",
        ["config/hazard_taxonomy.yaml → 4 个视觉类别",
         "qwen3-vl-plus(json_mode) → VLJudgeOutput",
         "rules.decide() 只取最高置信度那一条"], BLUE)
    box(draw, 120, 1250, 820, 120, "⑦A 1 条 HazardEvent",
        ["hazard_type = HZ-xx；level/action 来自 hazard_rules.yaml"], BLUE)

    # 右：45 项试点
    text(draw, (1260, 975), "45 项试点（当前默认：2/45 项）", 26, GREEN)
    text(draw, (1260, 1005), "CHECK_ITEMS_PILOT=true", 18, DIM, mono=True)
    box(draw, 1260, 1040, 820, 180, "⑥B 9 个子项 × 1 次调用",
        ["CI-06 法兰：6.11 螺栓 / 6.13 丝扣 / 6.9 密封面",
         "CI-11 防爆：11.1 / 11.3 / 11.4 / 11.6 / 11.7 / 11.8",
         "并发 4；每个子项独立 prompt，不注入点位上下文"], GREEN)
    box(draw, 1260, 1260, 820, 170, "⑦B 每个子项流水",
        ["build_sub_item_prompt（criteria/boundary/observation）",
         "qwen3-vl-plus(json_mode) → SubItemVerdict",
         "decide_sub_item() → 有/无/不可判定"], GREEN)
    box(draw, 1260, 1470, 820, 170, "⑧B 三态结果（都落事件）",
        ["有缺陷 → is_hazard=true，强制人工复核",
         "无缺陷 → is_hazard=false，保留审计",
         "不可判定/模型失败 → need_review=true，失败标 degraded"], AMBER)
    box(draw, 1260, 1680, 820, 120, "⑨B 9 条 HazardEvent",
        ["hazard_type = CI-06/6.11 ...；带 check_item_code/sub_item_code"], GREEN)

    # 左/右箭头
    arrow(draw, [(left_cx, 1040 + 170), (left_cx, 1250)], BLUE)
    arrow(draw, [(right_cx, 1040 + 180), (right_cx, 1260)], GREEN)
    arrow(draw, [(right_cx, 1260 + 170), (right_cx, 1470)], GREEN)
    arrow(draw, [(right_cx, 1470 + 170), (right_cx, 1680)], GREEN)

    # 汇合
    merge_y = 1900
    draw.line([(left_cx, 1370), (left_cx, 1840)], fill=BLUE, width=4)
    draw.line([(right_cx, 1800), (right_cx, 1840)], fill=GREEN, width=4)
    draw.line([(left_cx, 1840), (right_cx, 1840)], fill=LINE, width=4)
    arrow(draw, [(cx, 1840), (cx, merge_y)])
    box(draw, mx, merge_y, mw, 140, "⑩ persist_event × N",
        ["events 表：9 条（试点）或 1 条（旧链路）+ llm_usage",
         "同点位同类 24h 去重 · refresh_task 更新进度"], LIME)

    api_y, fe_y = 2080, 2240
    arrow(draw, [(cx, merge_y + 140), (cx, api_y)])
    box(draw, mx, api_y, mw, 120, "⑪ API 返回",
        ["GET /api/v1/tasks/{id}：frame.events[]（全部）",
         "兼容旧字段 frame.event（第一条隐患/结论）"], LIME)
    arrow(draw, [(cx, api_y + 120), (cx, fe_y)])
    box(draw, mx, fe_y, mw, 120, "⑫ 前端",
        ["任务详情：一帧多条结论；看板默认只看 is_hazard=true",
         "确认/驳回 → 统计 / CSV 导出"], PURPLE)

    # 失败/备注
    note_y = 2420
    draw.rounded_rectangle([120, note_y, W - 120, note_y + 150], radius=18, fill="#1D1A17",
                           outline="#5A4A33", width=2)
    text(draw, (150, note_y + 18), "注意：失败/不可判定不是静默丢弃", 26, AMBER)
    text(draw, (150, note_y + 62),
         "模型调用失败、JSON 解析失败 → 生成 degraded 事件（整图证据，need_review=true）；任一子项失败 → 帧 failed，但已成功的事件保留。",
         20, MUTED)
    text(draw, (150, note_y + 96),
         "试点单帧 9 次真实调用；关闭试点：CHECK_ITEMS_PILOT=false → 自动回退旧 1 次调用。", 20, MUTED)

    # 代码索引
    text(draw, (100, 2640), "代码索引", 24, FG)
    code_lines = [
        "api/app.py（上传/任务/事件）  worker.py（领帧/多事件落库）  pipeline.py（judge_frame_multi）",
        "check_items.py（45 项装载/prompt）  rules.py（decide_sub_item）  service.py（持久化/统计）  db.py（迁移）",
        "web/src/pages/TaskDetailPage.tsx（多事件）  BoardPage.tsx（看板）  StatsPage.tsx（统计）",
    ]
    for idx, line in enumerate(code_lines):
        text(draw, (100, 2682 + idx * 34), line, 19, DIM)

    text(draw, (100, 2800),
         "当前只接入 2/45 项，其余 43 项 enabled=false。首批 94 张图带人工红圈/水印，6.11 的 100% 是带标注确认上限，不是自主发现能力。",
         19, RED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, quality=92)
    print(f"已生成 {OUT}（{W}x{H}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
