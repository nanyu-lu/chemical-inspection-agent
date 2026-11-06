#!/usr/bin/env python3
"""从已有训练图集里抽一批图片，放到「测试图片/」文件夹，方便直接拖到上传页验证。

用法：
    python3 scripts/make_test_images.py
    python3 scripts/make_test_images.py --per-class 8 --out 测试图片

产出：
    测试图片/HZ-01_未佩戴安全帽_03_0008.jpg ...
    测试图片/说明.txt（含预期结果与清单）
"""

from __future__ import annotations

import argparse
import pathlib
import shutil

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SRC = (
    PROJECT_ROOT / "云文档" / "化工巡检项目文档" / "yolo调研" / "模型训练资料" / "模型训练图片"
)
DEFAULT_DST = PROJECT_ROOT / "测试图片"

# (源目录, 隐患ID, 名称, 默认抽几张)
PLAN = [
    ("03_未携带安全帽", "HZ-01", "未佩戴安全帽", 5),
    ("02_消防通道阻塞", "HZ-04", "消防通道堵塞", 5),
    ("04_消防器材遮挡", "HZ-05", "消防器材遮挡", 5),
    ("05_应急出口堵塞", "HZ-06", "应急出口堵塞", 5),
    ("01_人员拥挤", "HZ-02", "人员超员聚集不在MVP范围", 2),
]

EXPECT = {
    "HZ-01": "应报 HZ-01（远景/侧脸容易漏，属已知短板）",
    "HZ-04": "应报 HZ-04，但可能误报成 HZ-06（跨类误报，已知问题）",
    "HZ-05": "应报 HZ-05",
    "HZ-06": "应报 HZ-06（当前表现最好）",
    "HZ-02": "不在 MVP 提示词内，预期「不报」，不是 bug",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=str(DEFAULT_SRC))
    parser.add_argument("--out", default=str(DEFAULT_DST))
    parser.add_argument("--per-class", type=int, default=5)
    args = parser.parse_args()

    src = pathlib.Path(args.src)
    dst = pathlib.Path(args.out)
    if not src.exists():
        print(f"❌ 源目录不存在：{src}")
        return 2
    dst.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, str, str]] = []
    for folder, code, name, default_n in PLAN:
        n = 2 if code == "HZ-02" else args.per_class
        files = sorted(p for p in (src / folder).iterdir() if p.suffix.lower() == ".jpg")
        if not files:
            print(f"跳过（无图片）：{folder}")
            continue
        step = max(1, len(files) // n)
        picked = [files[min(i * step, len(files) - 1)] for i in range(n)]
        for f in picked:
            dst_name = f"{code}_{name}_{f.name}"
            shutil.copy2(f, dst / dst_name)
            rows.append((dst_name, code, folder))
        print(f"{folder}: 抽 {len(picked)} 张 → {code}")

    lines = [
        "化工巡检 MVP · 测试图片说明",
        "=" * 40,
        "",
        "用途：在 http://127.0.0.1:5173/upload 直接拖拽这些图片做识别验证。",
        "文件名格式：隐患类别ID_隐患名称_原始文件名.jpg",
        f"共 {len(rows)} 张。",
        "",
        "【预期结果】",
    ]
    for code, text in EXPECT.items():
        lines.append(f"- {code}：{text}")
    lines += [
        "",
        "【注意】",
        "1. 所有结论都需人工确认，页面显示「判据待专家确认」属预期（判定标准原文未提供）。",
        "2. 同一张图重复上传会按 sha256 去重，不会重复计费。",
        "3. 单张约 10~15 秒出结果。",
        "",
        "【清单】",
    ]
    for i, (dst_name, code, _) in enumerate(rows, 1):
        lines.append(f"{i:2d}. {code}  {dst_name}")

    (dst / "说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n✅ 共 {len(rows)} 张，输出目录：{dst.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
