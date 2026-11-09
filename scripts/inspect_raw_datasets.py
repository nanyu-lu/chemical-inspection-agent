"""扫描 data/datasets/web/raw/，报告每个包的结构、图片数、标注文件。

只读，不解压、不改文件。用于 Kaggle 包放好后快速确认“下对了没有”。
"""

from __future__ import annotations

import csv
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "datasets" / "web" / "raw"
OUT = ROOT / "data" / "eval" / "raw_inventory.csv"

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
LABEL_EXT = (".txt", ".xml", ".json", ".csv", ".yaml", ".yml")


def zip_summary(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
    images = [n for n in names if n.lower().endswith(IMAGE_EXT)]
    labels = [n for n in names if n.lower().endswith(LABEL_EXT)]
    tops = Counter(n.split("/")[0] for n in names if "/" in n)
    return {
        "kind": "zip",
        "files": len(names),
        "images": len(images),
        "labels": len(labels),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
        "top_dirs": "; ".join(f"{k}({v})" for k, v in tops.most_common(5)),
        "path": str(path.relative_to(ROOT)),
    }


def dir_summary(path: Path) -> dict:
    files = [p for p in path.rglob("*") if p.is_file()]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXT]
    labels = [p for p in files if p.suffix.lower() in LABEL_EXT]
    tops = Counter(p.relative_to(path).parts[0] for p in files if len(p.relative_to(path).parts) > 1)
    return {
        "kind": "dir",
        "files": len(files),
        "images": len(images),
        "labels": len(labels),
        "size_mb": round(sum(p.stat().st_size for p in files) / 1024 / 1024, 1),
        "top_dirs": "; ".join(f"{k}({v})" for k, v in tops.most_common(5)),
        "path": str(path.relative_to(ROOT)),
    }


def main() -> int:
    if not RAW.exists():
        print(f"找不到 {RAW}")
        return 1

    rows: list[dict] = []
    for child in sorted(RAW.iterdir()):
        if not child.is_dir():
            continue
        zips = sorted(child.glob("*.zip"))
        if zips:
            for z in zips:
                rows.append({"dataset": child.name, **zip_summary(z)})
        else:
            rows.append({"dataset": child.name, **dir_summary(child)})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset", "kind", "files", "images", "labels", "size_mb", "top_dirs", "path"],
        )
        writer.writeheader()
        writer.writerows(rows)

    for row in rows:
        print(
            f'{row["dataset"]:22s} {row["kind"]:4s} images={row["images"]:6d} '
            f'labels={row["labels"]:4d} size={row["size_mb"]:7.1f}MB  {row["top_dirs"]}'
        )
    print(f"清单：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
