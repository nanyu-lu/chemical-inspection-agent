"""按 web_review.csv 的「人工保留(1/0)」列执行保留/剔除。

- 1 = 保留（status=candidate）
- 0 = 剔除（移到 rejected/，status=rejected）
- 空 = 不动
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "data" / "datasets" / "web"
LICENSES = WEB / "LICENSES.csv"
REVIEW = ROOT / "data" / "eval" / "web_review.csv"


def main() -> int:
    if not REVIEW.exists() or not LICENSES.exists():
        print("找不到 web_review.csv 或 LICENSES.csv")
        return 1

    decisions: dict[str, str] = {}
    with REVIEW.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            value = (row.get("人工保留(1/0)") or "").strip()
            if value in ("0", "1"):
                decisions[row["review_id"]] = value

    if not decisions:
        print("没有任何人工保留标记（1/0）")
        return 0

    with LICENSES.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    kept = 0
    rejected = 0
    for row in rows:
        decision = decisions.get(row.get("review_id", ""))
        if decision is None:
            continue
        local_path = row.get("local_path") or ""
        path = ROOT / local_path if local_path else None
        if decision == "1":
            row["status"] = "candidate"
            kept += 1
            continue
        row["status"] = "rejected"
        rejected += 1
        if path and path.exists():
            target_dir = WEB / "rejected" / row["item_code"]
            target = target_dir / path.name
            # 幂等：已剔除过的文件不再二次移动（否则 shutil.move 到自身会报错）
            if target != path:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
            row["local_path"] = str(target.relative_to(ROOT))

    with LICENSES.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    print(f"已应用：保留 {kept} 张，剔除 {rejected} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
