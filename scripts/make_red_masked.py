"""生成「去掉人工红圈」的图片副本，用于测自主发现能力。

为什么不能直接把圈内涂灰：红圈圈住的正是缺陷本身，涂灰等于连问题一起删掉，
召回必然掉到 0，测出来的是「删除缺陷」，不是「去掉提示」。

做法（纯 PIL，不用 numpy，避免动项目依赖）：
1. 按颜色阈值取出红色笔画像素；
2. 外扩几个像素，盖住抗锯齿边缘；
3. 先把笔画像素填成中性灰，再按 1/12 缩放回放，得到「不含红线的邻域底色」；
4. 只用这块底色覆盖被外扩的掩膜区域 —— 笔画消失，圈内内容原样保留。

原始图不动，副本写到 第一批_遮红/ 镜像目录。

用法
  .venv/bin/python scripts/make_red_masked.py --limit 2      # 抽 2 张看效果
  .venv/bin/python scripts/make_red_masked.py                # 全量 87 张
  .venv/bin/python scripts/make_red_masked.py --report       # 只统计红色占比，不写文件
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
SRC_BASE = ROOT / "data" / "datasets" / "local" / "45项" / "第一批"
DST_BASE = ROOT / "data" / "datasets" / "local" / "45项" / "第一批_遮红"


def _thr(img: Image.Image, lo: int | None = None, hi: int | None = None) -> Image.Image:
    if lo is not None:
        return img.point(lambda v: 255 if v > lo else 0)
    assert hi is not None
    return img.point(lambda v: 255 if v < hi else 0)


def red_mask(img: Image.Image) -> Image.Image:
    """纯红/深红标注；锈迹偏暗褐、G/B 与 R 差距小，用双差值阈值分开。"""
    r, g, b = img.split()
    cond = ImageChops.multiply(_thr(r, lo=120), _thr(g, hi=95))
    cond = ImageChops.multiply(cond, _thr(b, hi=95))
    cond = ImageChops.multiply(cond, _thr(ImageChops.subtract(r, g), lo=55))
    cond = ImageChops.multiply(cond, _thr(ImageChops.subtract(r, b), lo=55))
    return cond.convert("L")


def ratio(mask: Image.Image) -> float:
    hist = mask.histogram()
    return sum(i * n for i, n in enumerate(hist)) / 255 / (mask.width * mask.height)


def mask_image(
    img: Image.Image, grow: int, rounds: int, radius: float
) -> tuple[Image.Image, float, float]:
    """把红色笔画从画面里抹掉，圈内内容保留。

    粗尺度重建会沿环留下一圈灰带——那等于把红色提示换成灰色提示，仍是变相指路。
    这里改成「扩散填充」：笔画先抹成邻近底色，再反复做 模糊→只保留掩膜内 的迭代，
    颜色由环两侧边界渗进来，环带塌成连续背景。
    """
    img = img.convert("RGB")
    mask = red_mask(img)
    before = ratio(mask)
    if before == 0:
        return img, 0.0, 0.0

    grown = mask.filter(ImageFilter.MaxFilter(grow | 1)) if grow > 0 else mask

    # 只在掩膜外接框内做迭代，避免全图反复模糊
    box = grown.getbbox()
    if not box:
        return img, before, before
    margin = 48
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(img.width, x1 + margin), min(img.height, y1 + margin)

    region = img.crop((x0, y0, x1, y1))
    rmask = grown.crop((x0, y0, x1, y1))
    # 边界色：用掩膜外一圈的中值近似，先抹掉红线再取
    erased = region.copy()
    erased.paste((128, 128, 128), mask=rmask)

    work = erased
    for _ in range(rounds):
        work = Image.composite(work.filter(ImageFilter.GaussianBlur(radius)), erased, rmask)

    out = img.copy()
    out.paste(work, (x0, y0))
    return out, before, ratio(red_mask(out))


def load_rows() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for r in rows:
        if r.get("is_duplicate", "0") not in ("0", "", "False"):
            continue
        if r["rel_path"] in seen:
            continue
        seen.add(r["rel_path"])
        uniq.append(r)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser(description="去掉人工红圈，生成对照图副本")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--grow", type=int, default=9, help="掩膜外扩像素（奇数）")
    ap.add_argument("--rounds", type=int, default=60, help="扩散迭代次数")
    ap.add_argument("--radius", type=float, default=4.0, help="扩散模糊半径")
    ap.add_argument("--report", action="store_true", help="只统计红色占比，不写文件")
    args = ap.parse_args()

    rows = load_rows()
    if args.limit:
        rows = rows[: args.limit]

    hit = 0
    ratios: list[float] = []
    left: list[tuple[str, float]] = []
    for i, r in enumerate(rows, 1):
        src = SRC_BASE / r["rel_path"]
        if not src.exists():
            print(f"  缺失 {src}")
            continue
        with Image.open(src) as im:
            out, before, after = mask_image(im, args.grow, args.rounds, args.radius)
            if before > 0.002:
                hit += 1
                ratios.append(before)
            if after > 0.0005:
                left.append((r["file"], after))
            if not args.report:
                dst = DST_BASE / r["rel_path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                out.save(dst, quality=95)
        if i % 20 == 0:
            print(f"  {i}/{len(rows)}", flush=True)

    print(f"\n处理 {len(rows)} 张 | 含红圈 {hit} 张 ({hit / max(1, len(rows)) * 100:.0f}%)")
    if ratios:
        ratios.sort()
        print(
            f"红色像素占比 中位 {ratios[len(ratios) // 2] * 100:.2f}% "
            f"最大 {ratios[-1] * 100:.2f}%"
        )
    if left:
        print(f"遮盖后仍有红色残留 >0.05% 的 {len(left)} 张：")
        for name, v in left[:8]:
            print(f"    {name[:40]:<40} {v * 100:.3f}%")
    else:
        print("遮盖后红色残留均 <0.05%")
    if not args.report:
        print(f"输出目录 {DST_BASE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
