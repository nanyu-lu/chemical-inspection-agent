"""在带红圈的图上追加 2 个同样式「诱饵圈」，用来测模型是否跟着标注走。

逻辑：同一张图放 3 个圈（1 个真标注 + 2 个随机诱饵）。
模型报的 bbox 若落在诱饵圈上，说明它在读「圈在哪」而不是「缺陷在哪」；
落在真圈上则不能区分（真圈本来就在缺陷上），所以这是**单侧检验**——
能证伪，不能证真。

产出
  data/datasets/local/45项/第一批_诱饵/<rel_path>
  data/eval/decoy_cues.json   每个文件的真圈/诱饵圈归一化圆心与半径
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

from make_red_masked import red_mask  # 同目录脚本
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
SRC_BASE = ROOT / "data" / "datasets" / "local" / "45项" / "第一批"
DST_BASE = ROOT / "data" / "datasets" / "local" / "45项" / "第一批_诱饵"
CUES = ROOT / "data" / "eval" / "decoy_cues.json"

RED = (214, 26, 26)


def red_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    return red_mask(img.convert("RGB")).getbbox()


def main() -> int:
    ap = argparse.ArgumentParser(description="追加诱饵红圈")
    ap.add_argument("--group", default="6.11")
    ap.add_argument("--decoys", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20261108)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    with MANIFEST.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r["sub_code"] == args.group and r.get("is_duplicate", "0") in ("0", "", "False")]

    cues: dict[str, dict] = {}
    done = 0
    for r in rows:
        src = SRC_BASE / r["rel_path"]
        if not src.exists():
            continue
        with Image.open(src) as im0:
            im = im0.convert("RGB")
        w, h = im.size
        box = red_bbox(im)
        if not box:
            continue
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rad = max(20.0, min(x1 - x0, y1 - y0) / 2)
        # 笔画粗细 ≈ 面积/周长，估个下限避免细到看不见
        width = int(max(3, round(rad * 0.10)))

        draw = ImageDraw.Draw(im)
        placed: list[tuple[float, float, float]] = []
        tries = 0
        while len(placed) < args.decoys and tries < 600:
            tries += 1
            # 诱饵别大到没处放：真圈常常占满画幅，诱饵取 0.3~0.55 倍半径
            rr = max(14.0, rad * rng.uniform(0.30, 0.55))
            if 2 * rr + 16 >= min(w, h):
                continue
            px = rng.uniform(rr + 8, w - rr - 8)
            py = rng.uniform(rr + 8, h - rr - 8)
            if math.hypot(px - cx, py - cy) < rad + rr + 8:
                continue
            if any(math.hypot(px - qx, py - qy) < rr + qr + 16 for qx, qy, qr in placed):
                continue
            draw.ellipse([px - rr, py - rr, px + rr, py + rr], outline=RED, width=width)
            placed.append((px, py, rr))

        dst = DST_BASE / r["rel_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, quality=95)
        cues[r["file"]] = {
            "rel_path": r["rel_path"],
            "size": [w, h],
            "true": [round(cx / w, 4), round(cy / h, 4), round(rad / max(w, h), 4)],
            "decoys": [[round(px / w, 4), round(py / h, 4), round(rr / max(w, h), 4)]
                       for px, py, rr in placed],
        }
        done += 1

    CUES.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
    total_decoy = sum(len(v["decoys"]) for v in cues.values())
    print(f"已生成 {done} 张诱饵图，共 {total_decoy} 个诱饵圈")
    print(f"输出 {DST_BASE.relative_to(ROOT)}")
    print(f"线索 {CUES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
