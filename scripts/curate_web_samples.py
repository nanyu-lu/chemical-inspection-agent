"""审核 Commons 候选图：明显跑偏的移到 rejected/，生成 web_review.csv。

不删除 LICENSES.csv 记录，只增加 status=rejected，保留来源可追溯。
"""

from __future__ import annotations

import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "data" / "datasets" / "web"
LICENSES = WEB / "LICENSES.csv"
REVIEW = ROOT / "data" / "eval" / "web_review.csv"

# 标题黑名单：明显不是目标设备/场景
# 2026-11-08 人工审核 74 张后追加，理由见 data/eval/web_review.csv 的「人工备注」
REJECT_PATTERNS = (
    "shanghai bund",
    "bund bull",
    "wall of flowers",
    "ashtray",
    "ultracold atoms",
    "vintage child",
    "eiffel tower",
    "laguna aerial",
    "chemical warfare",
    "space station",
    "bicycle chain",
    "waveguide",
    "thyristor",
    "industrial & sugar machinery",
    "main electrical room",
    "door of an room",
    "walnut industrial machinery",
    "cable tray fire",
    # 人工审核追加
    "sheet sleeping bag",  # 接地床单是床上用品
    "sergo zakariadze",  # 船舶搁浅，非电气接地
    "railway grounding cable",  # 列车运动模糊，电缆不可辨
    "gas detector (5881943678)",  # 实为太赫兹波形图
    "chemical storage - hazera berurim",  # 只有建筑外墙
    "wesseling germany lyondellbasell",  # 只有管线标志桩
)

FIELDS = [
    "item_code",
    "review_id",
    "item_name",
    "usage",
    "source",
    "title",
    "url",
    "author",
    "license",
    "license_url",
    "width",
    "height",
    "sha1",
    "downloaded_at",
    "query",
    "notes",
    "local_path",
    "status",
]


def find_file(item_code: str, sha1: str) -> Path | None:
    matches = list(WEB.glob(f"*/{item_code}_*/*{sha1[:8]}*"))
    return matches[0] if matches else None


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not LICENSES.exists():
        print(f"找不到 {LICENSES}")
        return 1

    with LICENSES.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    kept: list[dict] = []
    rejected = 0
    missing = 0
    for row in rows:
        row["review_id"] = ""
        title = (row.get("title") or "").lower()
        # 已经人工/自动剔除过的不要复活（文件已移入 rejected/，find_file 找不到）
        was_rejected = (row.get("status") or "") == "rejected"
        is_rejected = was_rejected or any(p in title for p in REJECT_PATTERNS)
        path = find_file(row.get("item_code", ""), row.get("sha1", ""))
        if path:
            row["local_path"] = str(path.relative_to(ROOT))
        row["status"] = "rejected" if is_rejected else "candidate"
        if is_rejected:
            rejected += 1
            if path and path.exists() and not dry_run:
                target_dir = WEB / "rejected" / row["item_code"]
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target_dir / path.name))
        else:
            if not path:
                missing += 1
            kept.append(row)

    kept.sort(key=lambda r: (r["item_code"], r["title"]))
    counters: dict[str, int] = defaultdict(int)
    for row in kept:
        code = row["item_code"]
        counters[code] += 1
        row["review_id"] = f"{code}-{counters[code]:03d}"

    if dry_run:
        print(f"[dry-run] 保留 {len(kept)} 张，拒绝 {rejected} 张，找不到文件 {missing} 张")
        return 0

    with LICENSES.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})

    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS + ["人工保留(1/0)", "人工备注"])
        writer.writeheader()
        for row in sorted(kept, key=lambda r: (r["item_code"], r["title"])):
            writer.writerow({**{k: row.get(k, "") for k in FIELDS}, "人工保留(1/0)": "", "人工备注": ""})

    print(f"候选 {len(kept)} 张，拒绝 {rejected} 张，找不到文件 {missing} 张")
    print(f"审核表：{REVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
