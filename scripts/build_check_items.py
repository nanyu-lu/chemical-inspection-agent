"""生成 45 项检查项骨架 config/check_items.yaml。

数据来源：
- 45 个关键词：scripts/prepare_local_dataset.py 的 ITEM_NAMES
- 第一批 24 个子条目：FOLDER_MAP + data/eval/45项_第一批_manifest.csv

只生成骨架，不填 578 条完整判据；后续按批次补。
"""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "check_items.yaml"
MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
CATALOG = ROOT / "config" / "sub_items_catalog.yaml"


def load_prepare_module():
    path = ROOT / "scripts" / "prepare_local_dataset.py"
    spec = importlib.util.spec_from_file_location("prepare_local_dataset", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GROUPS = {
    "CI-01": "设备与管道", "CI-02": "设备与管道", "CI-03": "设备与管道",
    "CI-04": "设备与管道", "CI-05": "设备与管道", "CI-06": "设备与管道",
    "CI-07": "设备与管道", "CI-08": "设备与管道", "CI-09": "设备与管道",
    "CI-10": "电气与仪表", "CI-11": "电气与仪表", "CI-12": "电气与仪表",
    "CI-13": "储运与消防", "CI-14": "电气与仪表", "CI-15": "设备与管道",
    "CI-16": "电气与仪表", "CI-17": "电气与仪表", "CI-18": "电气与仪表",
    "CI-19": "作业安全", "CI-20": "储运与消防", "CI-21": "设备与管道",
    "CI-22": "作业安全", "CI-23": "设备与管道", "CI-24": "电气与仪表",
    "CI-25": "电气与仪表", "CI-26": "电气与仪表", "CI-27": "作业安全",
    "CI-28": "电气与仪表", "CI-29": "设备与管道", "CI-30": "储运与消防",
    "CI-31": "作业安全", "CI-32": "作业安全", "CI-33": "作业安全",
    "CI-34": "作业安全", "CI-35": "作业安全", "CI-36": "作业安全",
    "CI-37": "作业安全", "CI-38": "储运与消防", "CI-39": "作业安全",
    "CI-40": "作业安全", "CI-41": "作业安全", "CI-42": "作业安全",
    "CI-43": "储运与消防", "CI-44": "作业安全", "CI-45": "储运与消防",
}

MODES = {
    "CI-01": "vl_closeup", "CI-02": "vl_closeup", "CI-03": "geometry",
    "CI-04": "vl_closeup", "CI-05": "vl_closeup", "CI-06": "vl_closeup",
    "CI-07": "vl_closeup", "CI-08": "vl_closeup", "CI-09": "vl_closeup",
    "CI-10": "vl_closeup", "CI-11": "vl_closeup+ocr", "CI-12": "vl_single",
    "CI-13": "vl_single", "CI-14": "vl_single", "CI-15": "vl_closeup",
    "CI-16": "vl_closeup+ocr", "CI-17": "ocr", "CI-18": "vl_closeup",
    "CI-19": "multi_frame", "CI-20": "vl_single+metadata", "CI-21": "vl_closeup",
    "CI-22": "multi_frame", "CI-23": "vl_closeup", "CI-24": "vl_single",
    "CI-25": "vl_single", "CI-26": "vl_single", "CI-27": "vl_closeup",
    "CI-28": "vl_single+ocr", "CI-29": "vl_single", "CI-30": "vl_single+metadata",
    "CI-31": "vl_single", "CI-32": "multi_frame", "CI-33": "multi_frame",
    "CI-34": "multi_frame", "CI-35": "vl_single", "CI-36": "geometry",
    "CI-37": "vl_closeup", "CI-38": "vl_single+geometry", "CI-39": "vl_closeup+multi_frame",
    "CI-40": "geometry", "CI-41": "multi_frame", "CI-42": "multi_frame",
    "CI-43": "vl_single", "CI-44": "multi_frame", "CI-45": "geometry+metadata",
}


def main() -> int:
    prep = load_prepare_module()

    counts: Counter[tuple[str, str]] = Counter()
    folder_by_sub: dict[str, str] = {}
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                counts[(row["item_code"], row["sub_code"])] += 1
                folder_by_sub.setdefault(row["sub_code"], row["folder"])

    sub_map: dict[str, list[dict]] = {}
    for item_code, sub_code, sub_name, secondary in prep.FOLDER_MAP.values():
        sub_map.setdefault(item_code, []).append(
            {
                "code": sub_code,
                "name": sub_name,
                "source_folder": folder_by_sub.get(sub_code, ""),
                "images": counts.get((item_code, sub_code), 0),
                "secondary_codes": list(secondary),
            }
        )

    catalog_counts: dict[str, int] = {}
    catalog_total = 0
    if CATALOG.exists():
        catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
        for entry in catalog.get("items", []):
            catalog_counts[entry["code"]] = len(entry.get("sub_items") or [])
        catalog_total = sum(catalog_counts.values())

    items = []
    for code, name in prep.ITEM_NAMES.items():
        items.append(
            {
                "code": code,
                "name": name,
                "group": GROUPS[code],
                "detection_mode": MODES[code],
                "enabled": False,
                "criteria_confirmed": False,
                "sop_ref": None,
                "catalog_sub_item_count": catalog_counts.get(code, 0),
                "sub_items": sub_map.get(code, []),
            }
        )

    doc = {
        "version": "0.2.0",
        "updated_at": date.today().isoformat(),
        "source": "巡检典型问题清单.xlsx（45 关键词 / 578 子问题）",
        "catalog_ref": "config/sub_items_catalog.yaml",
        "catalog_sub_item_count": catalog_total,
        "note": (
            "items 里的 sub_items 只列第一批有图的 24 个；"
            "578 条完整判据在 catalog_ref 指向的目录文件里（全部 enabled=false）。"
            "enabled 默认 false，需有样本+判据+评测才可打开。"
        ),
        "items": items,
    }
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(
        f"已生成 {OUT}：{len(items)} 项，{sum(len(v) for v in sub_map.values())} 个有图子条目，"
        f"目录引用 {catalog_total} 条"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
