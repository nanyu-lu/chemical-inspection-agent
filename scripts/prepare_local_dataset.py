"""把《用于训练的照片第一批》落盘并生成可复现清单。

背景：
- 外层 zip 里还套了一个 zip（下载器把内层文件名改成了 ``...zip.9mb）``）。
- 内层按 24 个隐患子条目分目录，共 94 张 JPG；其中 7 组图片跨条目复用。
- 本脚本只做「解压 + 映射 + 去重标记 + 尺寸/哈希」，不改图片内容。

产物：
- data/datasets/local/45项/第一批/<原目录>/<原文件>
- data/eval/45项_第一批_manifest.csv
- data/eval/45项_第一批_summary.json
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "云文档" / "化工巡检项目文档" / "用于训练的照片第一批.zip"
OUT_DIR = ROOT / "data" / "datasets" / "local" / "45项" / "第一批"
MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
SUMMARY = ROOT / "data" / "eval" / "45项_第一批_summary.json"

# 45 项关键词的稳定编号（顺序与《巡检典型问题清单.xlsx》一致）
ITEM_NAMES = {
    "CI-01": "安全阀",
    "CI-02": "爆破片",
    "CI-03": "安全阀与爆破片安全",
    "CI-04": "泄压人孔",
    "CI-05": "呼吸阀",
    "CI-06": "法兰",
    "CI-07": "工业管道（压力管道）",
    "CI-08": "管道支承件",
    "CI-09": "阻火器",
    "CI-10": "静电接地",
    "CI-11": "防爆电气设备",
    "CI-12": "UPS和蓄电池",
    "CI-13": "围堰防火堤",
    "CI-14": "固定式可燃有毒气体报警器（含装卸站台）",
    "CI-15": "紧急切断阀",
    "CI-16": "磁翻板液位计",
    "CI-17": "压力表",
    "CI-18": "热电偶",
    "CI-19": "装卸作业",
    "CI-20": "化学品存储",
    "CI-21": "视镜",
    "CI-22": "高压水清洗",
    "CI-23": "反应釜",
    "CI-24": "配电（控制）箱、柜",
    "CI-25": "配电室",
    "CI-26": "电缆布设",
    "CI-27": "电动工具/移动电器设备",
    "CI-28": "油浸式变压器",
    "CI-29": "机械设备",
    "CI-30": "化学品存放",
    "CI-31": "作业环境与安全防护",
    "CI-32": "动火作业",
    "CI-33": "高处作业",
    "CI-34": "吊装作业",
    "CI-35": "脚手架作业",
    "CI-36": "钢结构安装",
    "CI-37": "电焊机",
    "CI-38": "气瓶",
    "CI-39": "施工电梯",
    "CI-40": "吊篮",
    "CI-41": "挖机",
    "CI-42": "登高车",
    "CI-43": "应急消防设施",
    "CI-44": "叉车",
    "CI-45": "堆垛",
}

# 第一批 24 个目录 -> 45 项 / 子条目。
# 11、18、21 同时涉及相邻项，secondary_codes 用于多标签。
FOLDER_MAP = {
    "01": ("CI-01", "3.14", "安全阀有明显渗漏、锈蚀", ()),
    "02": ("CI-05", "5.9", "呼吸阀渗漏出化学品", ()),
    "03": ("CI-05", "5.10", "呼吸阀的阀座法兰之间螺栓未上全", ()),
    "04": ("CI-06", "6.5", "酸碱管道（紫色管道）法兰处未有效安装防喷溅防护套", ()),
    "05": ("CI-06", "6.7", "管道法兰螺栓未使用同一规格，或安装方向不一致", ()),
    "06": ("CI-06", "6.9", "法兰密封面有介质混痕迹（如结霜、结垢、腐蚀斑）", ()),
    "07": ("CI-06", "6.11", "法兰螺栓或螺母松动、缺失或腐蚀生锈", ()),
    "08": ("CI-06", "6.13", "长度过短导致丝扣外露不足2-3扣", ()),
    "09": ("CI-06", "6.14", "法兰存在偏口，两法兰面不平行，不完全对称，或有明显夹角翘曲变形", ()),
    "10": ("CI-06", "6.16", "两片法兰尺寸不匹配，螺栓孔无法对齐", ()),
    "11": ("CI-06", "6.18", "法兰跨接线脱落", ("CI-10",)),
    "12": ("CI-07", "7.6", "管道保温或保冷破损、脱落、潮湿发霉", ()),
    "13": ("CI-08", "8.1", "支吊架锈蚀、断裂、变形", ()),
    "14": ("CI-08", "8.3", "管道与支吊架接触处磨损、脱漆", ()),
    "15": ("CI-10", "10.2", "跨接线断裂、缺失或未连接", ()),
    "16": ("CI-10", "10.6", "涉及易燃易爆化学品的油罐车/桶装容器/移动容器未接地或跨接", ()),
    "17": ("CI-11", "11.1", "防爆分区内使用电气设备设施铭牌上无防爆EX标识，非防爆", ()),
    "18": ("CI-11", "11.4", "空闲的电缆进线口没有使用防爆格兰头且无封堵", ("CI-26",)),
    "19": ("CI-26", "11.5", "电缆绝缘皮破损", ()),
    "20": ("CI-11", "11.3", "防爆电气设备设施或带EX标识的防爆接线盒外壳开裂、螺栓缺失、螺栓松动", ()),
    "21": ("CI-11", "11.6", "电缆进出口未使用防爆格兰头且未使用防爆胶泥封堵", ("CI-26",)),
    "22": ("CI-11", "11.7", "防爆格兰头脱落或未拧紧", ()),
    "23": ("CI-11", "11.8", "防爆照明灯防爆结构及保护罩有缝隙", ()),
    "24": ("CI-17", "17.5", "压力表指针不在满量程1/3~2/3之间，量程选择不当", ()),
}


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def suggested_split(sha1: str) -> str:
    """按哈希做确定性切分，避免同一张图同时进训练和测试。"""
    bucket = int(sha1[:8], 16) % 10
    if bucket < 7:
        return "train"
    if bucket < 9:
        return "val"
    return "test"


def open_payload(zip_path: Path) -> zipfile.ZipFile:
    """打开外层 zip；若里面只有一个 zip，则继续打开内层。"""
    outer = zipfile.ZipFile(zip_path)
    files = [i for i in outer.infolist() if not i.is_dir()]
    if len(files) == 1:
        data = outer.read(files[0])
        if data[:2] == b"PK":
            return zipfile.ZipFile(io.BytesIO(data))
    return outer


def main() -> int:
    if not DEFAULT_ZIP.exists():
        print(f"找不到 zip：{DEFAULT_ZIP}")
        return 1

    zf = open_payload(DEFAULT_ZIP)
    infos = [
        i
        for i in zf.infolist()
        if not i.is_dir() and i.filename.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    if not infos:
        print("压缩包里没有图片")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    by_sha1: dict[str, str] = {}
    dup_groups: set[str] = set()
    errors: list[str] = []

    for info in infos:
        parts = info.filename.split("/")
        if len(parts) < 3:
            errors.append(f"目录层级不符：{info.filename}")
            continue
        folder = parts[-2]
        filename = parts[-1]
        prefix = folder.split("_", 1)[0]
        mapping = FOLDER_MAP.get(prefix)
        if mapping is None:
            errors.append(f"未映射的目录：{folder}")
            continue
        item_code, sub_code, sub_name, secondary = mapping

        data = zf.read(info)
        digest = sha1_bytes(data)
        try:
            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
                fmt = im.format or ""
        except Exception as exc:  # noqa: BLE001 - 单张坏图不能中断整批
            errors.append(f"无法读取图片 {info.filename}：{exc}")
            continue

        rel_path = Path(folder) / filename
        target = OUT_DIR / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)

        duplicate_of = by_sha1.get(digest, "")
        if duplicate_of:
            dup_groups.add(digest)
        else:
            by_sha1[digest] = str(rel_path)

        rows.append(
            {
                "item_code": item_code,
                "item_name": ITEM_NAMES[item_code],
                "secondary_codes": ",".join(secondary),
                "sub_code": sub_code,
                "sub_name": sub_name,
                "folder": folder,
                "file": filename,
                "rel_path": str(rel_path),
                "sha1": digest,
                "width": width,
                "height": height,
                "format": fmt,
                "size_bytes": len(data),
                "is_duplicate": 1 if duplicate_of else 0,
                "duplicate_of": duplicate_of,
                "split": suggested_split(digest),
            }
        )


    fieldnames = [
        "item_code",
        "item_name",
        "secondary_codes",
        "sub_code",
        "sub_name",
        "folder",
        "file",
        "rel_path",
        "sha1",
        "width",
        "height",
        "format",
        "size_bytes",
        "is_duplicate",
        "duplicate_of",
        "split",
    ]
    with MANIFEST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    per_item = Counter(r["item_code"] for r in rows)
    per_sub = Counter(f'{r["item_code"]}/{r["sub_code"]}' for r in rows)
    unique = len(by_sha1)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_zip": str(DEFAULT_ZIP),
        "output_dir": str(OUT_DIR),
        "files": len(rows),
        "unique_files": unique,
        "duplicate_files": len(rows) - unique,
        "items_covered": len(per_item),
        "sub_items_covered": len(per_sub),
        "per_item": dict(sorted(per_item.items())),
        "per_sub_item": dict(sorted(per_sub.items())),
        "duplicate_groups": len(dup_groups),
        "errors": errors,
        "note": "duplicate_of 为空表示该 sha1 的首次出现；跨条目复用是刻意保留的多标签，不是脏数据。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已落盘：{len(rows)} 张（唯一 {unique} 张，重复 {len(rows) - unique} 张）")
    print(f"覆盖：{len(per_item)}/45 项，{len(per_sub)} 个子条目")
    print(f"清单：{MANIFEST}")
    print(f"摘要：{SUMMARY}")
    if errors:
        print(f"有 {len(errors)} 条未处理：")
        for err in errors[:10]:
            print("  -", err)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

