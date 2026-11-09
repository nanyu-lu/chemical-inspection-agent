"""把 web_review.csv 里的候选图拼成一张 contact sheet，便于人工快速剔除。"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "eval" / "web_review.csv"
OUT = ROOT / "data" / "eval" / "web_contact_sheet.jpg"
CELL = 190
COLS = 10
LABEL_H = 18


def main() -> int:
    rows = [
        r
        for r in csv.DictReader(REVIEW.open(encoding="utf-8"))
        if r.get("local_path") and (r.get("人工保留(1/0)") or "").strip() != "0"
    ]
    if not rows:
        print("没有可拼的图")
        return 1

    rows_per_sheet = 40
    for sheet_idx in range(math.ceil(len(rows) / rows_per_sheet)):
        subset = rows[sheet_idx * rows_per_sheet : (sheet_idx + 1) * rows_per_sheet]
        rows_n = math.ceil(len(subset) / COLS)
        canvas = Image.new("RGB", (COLS * CELL, rows_n * (CELL + LABEL_H)), "white")
        draw = ImageDraw.Draw(canvas)
        for idx, row in enumerate(subset):
            path = ROOT / row["local_path"]
            if not path.exists():
                continue
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((CELL - 6, CELL - 6))
                    x = (idx % COLS) * CELL + (CELL - im.width) // 2
                    y = (idx // COLS) * (CELL + LABEL_H) + (CELL - im.height) // 2
                    canvas.paste(im, (x, y))
            except Exception as exc:  # noqa: BLE001
                print(f"跳过 {path}: {exc}")
                continue
            label = row.get("review_id") or f'{row["item_code"]} #{idx + 1}'
            draw.text(((idx % COLS) * CELL + 4, (idx // COLS) * (CELL + LABEL_H) + CELL), label, fill="black")
        target = OUT.with_name(f"{OUT.stem}_{sheet_idx + 1}{OUT.suffix}")
        canvas.save(target, quality=88)
        print(f"已生成 {target}（{len(subset)} 张）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
