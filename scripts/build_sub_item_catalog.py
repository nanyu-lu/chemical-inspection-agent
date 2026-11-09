"""从「巡检典型问题清单.xlsx」生成 578 条子项判据目录。

背景：
- config/check_items.yaml 只填了第一批有图的 24 个子条目，其余 554 条没有判据文本；
- 主流程要按子项提问，必须每条都有 code / name / criteria / required_context。

产出：
- config/sub_items_catalog.yaml   45 项 × 578 子项，全部 enabled=false
- config/keyword_item_map.csv     序号 → CI-code → Keywords 映射

不引入 openpyxl：xlsx 就是 zip + XML，直接解，避免动项目依赖。
原始文本不改写（清单本身有错别字，如「易烯易爆」），只做空白归一和前缀符号清理。
"""

from __future__ import annotations

import csv
import re
import zipfile
from collections import OrderedDict
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "云文档" / "化工巡检项目文档" / "巡检Agent开发训练" / "巡检典型问题清单.xlsx"
OUT_CATALOG = ROOT / "config" / "sub_items_catalog.yaml"
OUT_MAP = ROOT / "config" / "keyword_item_map.csv"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# 按 detection_mode 给出最低拍摄要求；具体点位要求仍需专家补
CONTEXT_HINT = {
    "vl_closeup": "近景，目标主体占画面 1/3 以上，清晰对焦",
    "vl_single": "单帧整图可判，目标完整入画",
    "ocr": "铭牌/标识/读数清晰可读，占画面 1/5 以上",
    "geometry": "需参照物或正视角，可量取尺寸/间距/角度",
    "multi_frame": "视频或连续多帧，覆盖完整作业过程",
    "metadata": "需配合台账/点位/工单信息",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append(
                "".join(
                    t.text or ""
                    for t in si.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                    )
                )
            )
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))

    rows: list[dict[str, str]] = []
    for row in sheet.findall("m:sheetData/m:row", NS):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", NS):
            col = "".join(ch for ch in cell.get("r", "") if ch.isalpha())
            value = cell.find("m:v", NS)
            if value is None:
                text = ""
            elif cell.get("t") == "s":
                text = shared[int(value.text or "0")]
            else:
                text = value.text or ""
            cells[col] = text
        rows.append(cells)
    return rows


def clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.lstrip("-－·•、 ").strip()


def detection_modes() -> dict[str, str]:
    """复用 build_check_items 的 MODES，避免两处定义漂移。"""
    text = (ROOT / "scripts" / "build_check_items.py").read_text(encoding="utf-8")
    block = re.search(r"MODES = \{(.*?)\n\}", text, re.DOTALL)
    if not block:
        raise RuntimeError("无法从 build_check_items.py 解析 MODES")
    return dict(re.findall(r'"(CI-\d{2})": "([^"]+)"', block.group(1)))


def main() -> int:
    if not XLSX.exists():
        print(f"找不到 {XLSX}")
        return 1

    rows = read_rows(XLSX)
    header = rows[0]
    if not {"A", "B", "C", "D"} <= set(header):
        raise RuntimeError(f"表头不符合预期：{header}")

    modes = detection_modes()
    items: OrderedDict[str, dict] = OrderedDict()
    mapping: list[dict[str, str]] = []
    seen: set[str] = set()

    for cells in rows[1:]:
        seq = clean(cells.get("A", ""))
        keyword = clean(cells.get("B", ""))
        problem = clean(cells.get("C", ""))
        sub_code = clean(cells.get("D", ""))
        if not (seq and keyword and sub_code):
            continue

        item_code = f"CI-{int(seq):02d}"
        if sub_code in seen:
            print(f"  跳过重复子项编号 {sub_code}（{problem[:24]}）")
            continue
        seen.add(sub_code)

        entry = items.setdefault(
            item_code,
            {"code": item_code, "name": keyword, "sub_items": []},
        )
        if entry["name"] != keyword:
            # 同一序号下关键词应唯一；出现不一致时保留首个并记录
            print(f"  注意 {item_code} 关键词不一致：{entry['name']} / {keyword}")

        mode = modes.get(item_code, "vl_single")
        entry["sub_items"].append(
            {
                "code": sub_code,
                "name": problem,
                "criteria": problem,
                "required_context": CONTEXT_HINT.get(mode, CONTEXT_HINT["vl_single"]),
                "enabled": False,
                "criteria_confirmed": False,
            }
        )
        mapping.append({"seq": seq, "item_code": item_code, "keyword": keyword, "sub_code": sub_code})

    total = sum(len(v["sub_items"]) for v in items.values())
    doc = {
        "version": "0.1.0",
        "updated_at": date.today().isoformat(),
        "source": "云文档/化工巡检项目文档/巡检Agent开发训练/巡检典型问题清单.xlsx",
        "note": (
            "578 条子项判据目录，原文照录（清单存在错别字，未改写）。"
            "criteria 尚未经专家确认，故 criteria_confirmed=false、enabled=false；"
            "启用前需补判据边界（什么情况不算）与 neg_anchor。"
        ),
        "known_mismatches": [
            {
                "sub_code": "3.14",
                "catalog_item": "CI-03",
                "dataset_item": "CI-01",
                "detail": "第一批图片归在 CI-01 安全阀，编号取自 3 章；同名判据在目录中属 CI-03",
            },
            {
                "sub_code": "11.5",
                "catalog_item": "CI-11",
                "dataset_item": "CI-26",
                "detail": "电缆绝缘皮破损，图片按内容归 CI-26 电缆布设，编号取自 11 章",
            },
            {
                "sub_code": "5.9/5.10",
                "catalog_item": None,
                "dataset_item": "CI-05",
                "detail": "第一批图片有 5.9/5.10，但清单呼吸阀只到 5.8，缺对应判据文本",
            },
        ],
        "item_count": len(items),
        "sub_item_count": total,
        "items": list(items.values()),
    }
    OUT_CATALOG.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with OUT_MAP.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["seq", "item_code", "keyword", "sub_code"])
        writer.writeheader()
        writer.writerows(mapping)

    print(f"已生成 {OUT_CATALOG}：{len(items)} 项，{total} 个子项")
    print(f"已生成 {OUT_MAP}：{len(mapping)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
