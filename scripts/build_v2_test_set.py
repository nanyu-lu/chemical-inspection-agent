"""生成 45 项试点 v2 测试集（CI-06/CI-11 九个子项）。

- 18 张正样本来自第一批公开图（带红圈/水印，仅内部 smoke test）
- 4 张负样本来自 Wikimedia Commons（正常件/无关件）
- 输出 labels.csv、README.md、contact_sheet.jpg

用法：.venv/bin/python scripts/build_v2_test_set.py
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "datasets" / "local" / "45项" / "第一批"
OUT = ROOT / "data" / "datasets" / "local" / "45项" / "测试图片v2"
MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
LICENSES = ROOT / "data" / "datasets" / "web" / "LICENSES.csv"
SANS = "/System/Library/Fonts/STHeiti Medium.ttc"

# (item, sub, 目标子目录, 原文件, 输出文件名, 允许不可判定, 备注)
POSITIVES = [
    ("CI-06", "6.11", "CI-06_法兰/6.11_螺栓", "07_01_166539.jpg", "CI-06_6.11_pos_07_01.jpg", 0, "空螺栓孔/锈蚀"),
    ("CI-06", "6.11", "CI-06_法兰/6.11_螺栓", "07_15_2c5469.jpg", "CI-06_6.11_pos_07_15.jpg", 0, "螺母缺失/锈蚀"),
    ("CI-06", "6.13", "CI-06_法兰/6.13_丝扣", "08_01_3abfe3.jpg", "CI-06_6.13_pos_08_01.jpg", 0, "丝扣近景"),
    ("CI-06", "6.13", "CI-06_法兰/6.13_丝扣", "08_04_3e7007.jpg", "CI-06_6.13_pos_08_04.jpg", 1, "模糊，允许不可判定"),
    ("CI-06", "6.9", "CI-06_法兰/6.9_密封面", "06_01_7ce77.jpg", "CI-06_6.9_pos_06_01.jpg", 0, "接缝湿痕/锈蚀"),
    ("CI-06", "6.9", "CI-06_法兰/6.9_密封面", "06_06_10ba6d.jpg", "CI-06_6.9_pos_06_06.jpg", 0, "密封面痕迹"),
    ("CI-11", "11.1", "CI-11_防爆电气/11.1_EX标识", "17_01_5f950b.jpg", "CI-11_11.1_pos_17_01.jpg", 0, "无 EX 标识"),
    ("CI-11", "11.1", "CI-11_防爆电气/11.1_EX标识", "17_02_60e163.jpg", "CI-11_11.1_pos_17_02.jpg", 0, "无 EX 标识"),
    ("CI-11", "11.3", "CI-11_防爆电气/11.3_外壳", "20_03_698aca.jpg", "CI-11_11.3_pos_20_03.jpg", 0, "外壳缝隙"),
    ("CI-11", "11.3", "CI-11_防爆电气/11.3_外壳", "20_05_6ad8d1.jpg", "CI-11_11.3_pos_20_05.jpg", 0, "螺栓/缝隙"),
    ("CI-11", "11.4", "CI-11_防爆电气/11.4_进线口", "18_01_61c201.jpg", "CI-11_11.4_pos_18_01.jpg", 0, "空闲进线口/无效封堵"),
    ("CI-11", "11.4", "CI-11_防爆电气/11.4_进线口", "18_04_63f889.jpg", "CI-11_11.4_pos_18_04.jpg", 0, "进线口封堵问题"),
    ("CI-11", "11.6", "CI-11_防爆电气/11.6_电缆进出口", "21_01_6bde17.jpg", "CI-11_11.6_pos_21_01.jpg", 0, "无格兰头/胶泥"),
    ("CI-11", "11.6", "CI-11_防爆电气/11.6_电缆进出口", "21_03_6ea54c.jpg", "CI-11_11.6_pos_21_03.jpg", 0, "电缆进出口封堵"),
    ("CI-11", "11.7", "CI-11_防爆电气/11.7_格兰头", "22_04_73ad8b.jpg", "CI-11_11.7_pos_22_04.jpg", 0, "格兰头未拧紧"),
    ("CI-11", "11.7", "CI-11_防爆电气/11.7_格兰头", "22_05_7601d1.jpg", "CI-11_11.7_pos_22_05.jpg", 0, "格兰头/密封圈"),
    ("CI-11", "11.8", "CI-11_防爆电气/11.8_照明灯", "23_01_795a59.jpg", "CI-11_11.8_pos_23_01.jpg", 0, "防爆灯结构缝隙"),
    ("CI-11", "11.8", "CI-11_防爆电气/11.8_照明灯", "23_02_7ac914.jpg", "CI-11_11.8_pos_23_02.jpg", 0, "防爆灯结构"),
]

# (目标相对路径, Commons glob, 备注)
NEGATIVES = [
    ("negatives/normal_junction_box/normal_junction_box_01.jpg",
     "data/datasets/web/share_alike/CI-11_*/CI-11_File_FLAMEPROOF_JB*", "正常防爆接线盒"),
    ("negatives/normal_gauge/normal_gauge_01.jpg",
     "data/datasets/web/share_alike/CI-17_*/CI-17_File_MAXIMATOR-High-Pressure-Manometer-01a*", "正常压力表"),
    ("negatives/normal_pipeline/normal_pipeline_01.jpg",
     "data/datasets/web/share_alike/CI-07_*/CI-07_File_Industrial_architecture_pipelines_*", "工业管道（无目标法兰缺陷）"),
    ("negatives/normal_safety_valve/normal_safety_valve_01.jpg",
     "data/datasets/web/share_alike/CI-01_*/CI-01_File_Relief_valve01*", "安全阀（不是试点 9 项）"),
]


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(SANS, size)


def copy_one(src: Path, dst: Path) -> tuple[int, int, str]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    with Image.open(dst) as im:
        return im.width, im.height, sha1(dst)


def main() -> int:
    if not SRC.exists() or not MANIFEST.exists():
        print("找不到第一批图片或 manifest")
        return 1

    manifest = {}
    with MANIFEST.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            manifest[(row["sub_code"], row["file"])] = row["rel_path"]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    labels: list[dict[str, object]] = []
    for item, sub, folder, filename, out_name, undecidable, note in POSITIVES:
        rel = manifest.get((sub, filename))
        if not rel:
            print(f"manifest 缺 {sub}/{filename}")
            return 1
        src = SRC / rel
        dst = OUT / folder / out_name
        w, h, digest = copy_one(src, dst)
        labels.append({
            "file": str(dst.relative_to(OUT)),
            "item_code": item,
            "sub_code": sub,
            "expected_present": 1,
            "expected_undecidable": undecidable,
            "source": "第一批公开图（公众号，红圈/水印）",
            "license": "unresolved_internal_only",
            "note": note,
            "width": w,
            "height": h,
            "sha1": digest,
        })

    lic_rows = []
    if LICENSES.exists():
        with LICENSES.open(encoding="utf-8") as f:
            lic_rows = list(csv.DictReader(f))
    lic_by_path = {row.get("local_path", ""): row for row in lic_rows}

    for target, pattern, note in NEGATIVES:
        matches = list(ROOT.glob(pattern))
        if not matches:
            print(f"找不到负样本：{pattern}")
            return 1
        src = matches[0]
        dst = OUT / target
        w, h, digest = copy_one(src, dst)
        rel_src = str(src.relative_to(ROOT))
        lic = lic_by_path.get(rel_src, {})
        labels.append({
            "file": str(dst.relative_to(OUT)),
            "item_code": "",
            "sub_code": "",
            "expected_present": 0,
            "expected_undecidable": 0,
            "source": "Wikimedia Commons",
            "license": lic.get("license", "CC BY-SA (see LICENSES)"),
            "note": note,
            "width": w,
            "height": h,
            "sha1": digest,
        })

    with (OUT / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(labels[0].keys()))
        writer.writeheader()
        writer.writerows(labels)

    make_readme(len(POSITIVES), len(NEGATIVES))
    make_contact_sheet(labels)

    print(f"已生成 {OUT}")
    print(f"正样本 {len(POSITIVES)}，负样本 {len(NEGATIVES)}，共 {len(labels)}")
    return 0


def make_readme(n_pos: int, n_neg: int) -> None:
    body = f"""# 45 项试点 v2 测试图片

> 只测试当前接入的 **CI-06 法兰 / CI-11 防爆电气 9 个子项**。
> 不是 45 项全量，也不是准确率测试集。

## 数量

- 正样本：{n_pos} 张（第一批公开图，带红圈/水印，仅内部 smoke test）
- 负样本：{n_neg} 张（Wikimedia Commons 正常件/无关件）

## 目录

```
CI-06_法兰/6.11_螺栓       6.13_丝扣       6.9_密封面
CI-11_防爆电气/11.1_EX标识  11.3_外壳      11.4_进线口
              11.6_电缆进出口 11.7_格兰头   11.8_照明灯
negatives/normal_junction_box  normal_gauge  normal_pipeline  normal_safety_valve
```

## 用法

1. 上传页选点位 `WH-A-03`
2. 一次拖 1~3 张，不要一次 22 张
3. 任务详情应出现 **9 条结论**
4. 对照 `labels.csv`：
   - 正样本：对应子项 `is_hazard=true`
   - 负样本：9 项都应为 `is_hazard=false`
   - `08_04` 模糊图允许 `undecidable=true`

## 注意

- 每张图 **9 次真实模型调用**；22 张全跑约 198 次。
- 正样本带人工红圈，6.11 的召回是**上限**，不是自主发现能力。
- 没有现场同分布负样本；负样本只用于“是否乱报”的 smoke test。
"""
    (OUT / "README.md").write_text(body, encoding="utf-8")


def make_contact_sheet(labels: list[dict[str, object]]) -> None:
    cell, cols = 240, 5
    rows = (len(labels) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell), "white")
    draw = ImageDraw.Draw(canvas)
    small = font(14)
    for idx, row in enumerate(labels):
        path = OUT / str(row["file"])
        im = None
        try:
            with Image.open(path) as src:
                im = src.convert("RGB")
                im.thumbnail((cell - 8, cell - 34))
        except OSError as exc:
            print(f"跳过 {path}: {exc}")
        if im is not None:
            x = (idx % cols) * cell + (cell - im.width) // 2
            y = (idx // cols) * cell + 4
            canvas.paste(im, (x, y))
            label = str(row["file"]).split("/")[-1][:30]
            draw.text(((idx % cols) * cell + 5, (idx // cols) * cell + cell - 28),
                      label, font=small, fill="black")
    canvas.save(OUT / "contact_sheet.jpg", quality=88)


if __name__ == "__main__":
    raise SystemExit(main())

