"""下载 Hugging Face 上许可证明确的公开图片数据集。

只用于补负样本/参考图；不替代现场同分布数据。
当前支持：
- Voxel51/hard-hat-detection（CC0-1.0，999 张）
- 0707ryan/Bolt_Screw_Synthetic_Dataset（MIT，998 张合成螺栓/螺丝）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "datasets" / "web" / "raw"
LICENSES = ROOT / "data" / "datasets" / "web" / "LICENSES_HF.csv"
HF_API = "https://huggingface.co/api/datasets"
HF_RESOLVE = "https://huggingface.co/datasets"
UA = "ChemInspectDatasetCollector/0.1 (https://github.com/nanyu-lu/chemical-inspection-agent)"

DATASETS: dict[str, dict] = {
    "hf-hard-hat": {
        "repo": "Voxel51/hard-hat-detection",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "item_code": "HZ-01",
        "item_name": "未佩戴安全帽（33项功能，不在45项）",
        "usage": "negative",
        "prefixes": ("data/",),
    },
    "hf-bolt-screw-synthetic": {
        "repo": "0707ryan/Bolt_Screw_Synthetic_Dataset",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "item_code": "CI-06",
        "item_name": "法兰",
        "usage": "negative",
        "prefixes": ("bolt/", "screw/"),
    },
}

FIELDS = [
    "dataset",
    "repo",
    "item_code",
    "item_name",
    "usage",
    "path",
    "url",
    "license",
    "license_url",
    "sha1",
    "width",
    "height",
    "size_bytes",
    "local_path",
    "downloaded_at",
]


def list_files(client: httpx.Client, repo: str, prefixes: tuple[str, ...]) -> list[str]:
    resp = client.get(f"{HF_API}/{repo}/tree/main", params={"recursive": "true"}, timeout=60)
    resp.raise_for_status()
    files = []
    for item in resp.json():
        if item.get("type") != "file":
            continue
        path = item.get("path", "")
        if not path.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        if prefixes and not path.startswith(prefixes):
            continue
        files.append(path)
    return files


def download_one(client: httpx.Client, name: str, spec: dict, path: str) -> dict | None:
    url = f"{HF_RESOLVE}/{spec['repo']}/resolve/main/{path}"
    try:
        resp = client.get(url, timeout=90)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"下载失败 {path}: {exc}")
        return None

    data = resp.content
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception as exc:  # noqa: BLE001
        print(f"坏图 {path}: {exc}")
        return None

    target = RAW / name / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)

    return {
        "dataset": name,
        "repo": spec["repo"],
        "item_code": spec["item_code"],
        "item_name": spec["item_name"],
        "usage": spec["usage"],
        "path": path,
        "url": url,
        "license": spec["license"],
        "license_url": spec["license_url"],
        "sha1": hashlib.sha1(data).hexdigest(),
        "width": width,
        "height": height,
        "size_bytes": len(data),
        "local_path": str(target.relative_to(ROOT)),
        "downloaded_at": datetime.now(UTC).isoformat(),
    }


def append_rows(rows: list[dict]) -> None:
    is_new = not LICENSES.exists()
    with LICENSES.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 HF 公开图片数据集")
    parser.add_argument("--datasets", default="", help="逗号分隔，如 hf-hard-hat,hf-bolt-screw-synthetic")
    parser.add_argument("--max-files", type=int, default=0, help="每个数据集最多下载几张（0=全部）")
    parser.add_argument("--workers", type=int, default=8, help="并发下载数")
    args = parser.parse_args()

    selected = [s.strip() for s in args.datasets.split(",") if s.strip()] or list(DATASETS)
    unknown = [s for s in selected if s not in DATASETS]
    if unknown:
        print(f"未知数据集：{unknown}")
        return 2

    headers = {"User-Agent": UA}
    total = 0
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for name in selected:
            spec = DATASETS[name]
            files = list_files(client, spec["repo"], tuple(spec["prefixes"]))
            if args.max_files:
                files = files[: args.max_files]
            print(f"== {name}: {len(files)} 个文件")
            rows: list[dict] = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(download_one, client, name, spec, path): path for path in files
                }
                for idx, future in enumerate(as_completed(futures), start=1):
                    row = future.result()
                    if row:
                        rows.append(row)
                    if idx % 100 == 0:
                        print(f"  进度 {idx}/{len(files)}")
            append_rows(rows)
            total += len(rows)
            print(f"== {name}: 成功 {len(rows)} 张")

    print(f"完成：新增 {total} 张，台账 {LICENSES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
