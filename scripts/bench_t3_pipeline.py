#!/usr/bin/env python3
"""T3：系统判定能力（走完整生产流水线）。

与 T2（`bench_models.py`：只调模型，无预处理、无规则）的区别：
  T3 = 预处理(EXIF + 长边1280) → 提示词 → 模型 → 契约校验(失败重试1次)
       → 规则裁决(0.45/0.75 阈值、定级、条款) → 证据裁剪

同一批图、同一模型，唯一变量是「有没有走管线」，用于回答：
预处理与规则到底贡献了多少准确率。

用法：
    python scripts/bench_t3_pipeline.py
    python scripts/bench_t3_pipeline.py --model qwen3.5-omni-plus --workers 4

产物：data/eval/t3_pipeline.csv、data/eval/t3_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chem_inspect.contracts import FrameRef, NetworkMode, utcnow
from chem_inspect.llm.maas import MaasClient
from chem_inspect.pipeline import judge_frame
from chem_inspect.prompt import load_taxonomy
from chem_inspect.rules import RuleSet
from chem_inspect.settings import Settings
from chem_inspect.storage import LocalBlobStore

DATA_DIR = ROOT / "测试图片"
OUT_CSV = ROOT / "data" / "eval" / "t3_pipeline.csv"
OUT_JSON = ROOT / "data" / "eval" / "t3_summary.json"

CLASS_NAME = {
    "HZ-01": "未佩戴安全帽",
    "HZ-04": "消防通道堵塞",
    "HZ-05": "消防器材遮挡",
    "HZ-06": "应急出口堵塞",
}


def load_samples() -> list[tuple[Path, str]]:
    samples: list[tuple[Path, str]] = []
    for path in sorted(DATA_DIR.glob("*.jpg")):
        match = re.match(r"(HZ-\d{2})", path.name)
        if match and match.group(1) in CLASS_NAME:
            samples.append((path, match.group(1)))
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-point", action="store_true", help="不注入点位上下文（与 T2 对齐）")
    parser.add_argument("--tag", default="", help="输出文件名后缀，如 t3a")
    args = parser.parse_args()

    samples = load_samples()
    if not samples:
        print(f"❌ {DATA_DIR} 没有带标签的图片")
        return 2

    settings = Settings()
    if not settings.has_key:
        print("❌ 未配置 MAAS_API_KEY")
        return 2
    model = args.model or settings.maas_vision_model

    client = MaasClient(
        api_key=settings.require_key(),
        base_url=settings.maas_base_url,
        timeout_s=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )
    rules = RuleSet.from_yaml(ROOT / "config" / "hazard_rules.yaml")
    taxonomy = load_taxonomy(ROOT / "config" / "hazard_taxonomy.yaml")
    store = LocalBlobStore(Path(tempfile.mkdtemp(prefix="t3-blobs-")))
    point = (
        None
        if args.no_point
        else {
            "id": "WH-A-03",
            "name": "3号库房东侧消防通道",
            "facilities": ["手提式干粉灭火器 x2"],
        }
    )
    point_id = (point or {}).get("id", "WH-A-03")
    suffix = f"_{args.tag}" if args.tag else ""
    out_csv = OUT_CSV.with_name(f"t3_pipeline{suffix}.csv")
    out_json = OUT_JSON.with_name(f"t3_summary{suffix}.json")

    def one(item: tuple[Path, str]) -> dict[str, Any]:
        path, label = item
        started = time.perf_counter()
        try:
            outcome = judge_frame(
                path.read_bytes(),
                frame_ref=FrameRef(
                    task_id="T3",
                    point_id=point_id,
                    captured_at=utcnow(),
                    frame_uri=f"local://raw/T3/{path.name}",
                ),
                point=point,
                client=client,
                rules=rules,
                taxonomy=taxonomy,
                store=store,
                model=model,
                network_mode=settings.network_mode or NetworkMode.ONLINE,
            )
        except Exception as exc:  # noqa: BLE001 - 单张失败不能中断整轮评测
            return {
                "file": path.name, "label": label, "ok": False, "hazard": "",
                "is_hazard": False, "confidence": 0.0, "degraded": False,
                "latency_ms": int((time.perf_counter() - started) * 1000), "error": str(exc)[:200],
            }
        verdict = outcome.event.verdict
        return {
            "file": path.name,
            "label": label,
            "ok": outcome.ok,
            "hazard": verdict.hazard_type or "",
            "is_hazard": verdict.is_hazard,
            "confidence": round(verdict.confidence, 3),
            "degraded": outcome.event.engine.degraded,
            "latency_ms": outcome.event.usage.latency_ms,
            "error": (outcome.error or "")[:200],
        }

    print(f"T3 系统判定：{len(samples)} 张，模型 {model}，并发 {args.workers}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, samples))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)

    per_class: dict[str, dict[str, Any]] = {}
    for label, items in by_label.items():
        ok_items = [r for r in items if r["ok"]]
        hits = [r for r in ok_items if r["hazard"] == label]
        others = [r for lab, rs in by_label.items() if lab != label for r in rs if r["ok"]]
        false_pos = [r for r in others if r["hazard"] == label]
        per_class[label] = {
            "name": CLASS_NAME[label],
            "n": len(items),
            "ok": len(ok_items),
            "hits": len(hits),
            "recall": round(len(hits) / len(ok_items), 3) if ok_items else 0.0,
            "fp": len(false_pos),
            "n_other": len(others),
            "fpr": round(len(false_pos) / len(others), 3) if others else 0.0,
        }

    ok_rows = [r for r in rows if r["ok"]]
    summary = {
        "model": model,
        "n": len(rows),
        "ok": len(ok_rows),
        "fail": len(rows) - len(ok_rows),
        "degraded": sum(1 for r in rows if r["degraded"]),
        "total_hits": sum(v["hits"] for v in per_class.values()),
        "total_pos": sum(v["ok"] for v in per_class.values()),
        "macro_recall": round(statistics.mean([v["recall"] for v in per_class.values()]), 3),
        "macro_fpr": round(statistics.mean([v["fpr"] for v in per_class.values()]), 3),
        "p50_ms": int(statistics.median([r["latency_ms"] for r in ok_rows])) if ok_rows else 0,
        "per_class": per_class,
        "ran_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== T3 汇总（{model}）===")
    for code in sorted(per_class):
        row = per_class[code]
        print(
            f"{code} {row['name']}: 召回 {row['hits']}/{row['ok']} = {row['recall']:.0%}"
            f" | 跨类误报 {row['fp']}/{row['n_other']} = {row['fpr']:.0%}"
        )
    print(
        f"总体：召回 {summary['total_hits']}/{summary['total_pos']} = {summary['macro_recall']:.0%}"
        f" | 跨类误报 {summary['macro_fpr']:.0%} | 失败 {summary['fail']} | 降级 {summary['degraded']}"
        f" | P50 {summary['p50_ms']} ms"
    )
    print(f"\n明细：{out_csv}\n汇总：{out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

