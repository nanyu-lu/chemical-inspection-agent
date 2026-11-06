#!/usr/bin/env python3
"""多模型横向评测（用带真实标签的现场图）。

数据：`测试图片/` 下文件名前缀即真值（HZ-01/04/05/06），HZ-02 不在 MVP 提示词内，剔除。
指标：
  · 召回率      —— 该类的图里，模型正确报出该类的比例
  · 跨类误报率  —— 其他类别的图里，模型误报成该类的比例（没有正常样本时的精确率代理）
  · 时延 / token / 解析失败率

用法：
    python scripts/bench_models.py                       # 默认 5 个候选模型
    python scripts/bench_models.py --models qwen3-vl-plus qwen3.8-omni-flash
    python scripts/bench_models.py --workers 4

产物：docs/模型对比报告.md、data/eval/model_bench.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chem_inspect.contracts import VLJudgeOutput
from chem_inspect.llm.maas import MaasClient, MaasError
from chem_inspect.prompt import build_judge_prompt, load_taxonomy, vl_categories
from chem_inspect.settings import Settings

DATA_DIR = ROOT / "测试图片"
REPORT = ROOT / "docs" / "模型对比报告.md"
RAW_CSV = ROOT / "data" / "eval" / "model_bench.csv"

DEFAULT_MODELS = [
    "qwen3-vl-plus",
    "qwen3.5-omni-plus",
    "qwen3.8-omni-flash",
    "qwen3.5-omni-flash",
    "qwen3-omni-flash",
]

CLASS_NAME = {
    "HZ-01": "未佩戴安全帽",
    "HZ-04": "消防通道堵塞",
    "HZ-05": "消防器材遮挡",
    "HZ-06": "应急出口堵塞",
}


def strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def run_model(
    client: MaasClient, model: str, prompt: str, samples: list[tuple[Path, str]], workers: int
) -> list[dict[str, Any]]:
    def one(item: tuple[Path, str]) -> dict[str, Any]:
        path, label = item
        started = time.perf_counter()
        base = {"model": model, "file": path.name, "label": label}
        try:
            res = client.chat_vision(path.read_bytes(), prompt, model=model, json_mode=True)
        except MaasError as exc:
            return {**base, "ok": False, "error": str(exc)[:200], "present": [], "confs": {},
                    "latency_ms": 0, "in_tok": 0, "out_tok": 0}
        latency = res.latency_ms or int((time.perf_counter() - started) * 1000)
        try:
            parsed = VLJudgeOutput.model_validate(json.loads(strip_fence(res.text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            return {**base, "ok": False, "error": f"解析失败: {str(exc)[:160]}", "present": [],
                    "confs": {}, "latency_ms": latency,
                    "in_tok": res.prompt_tokens, "out_tok": res.completion_tokens}
        return {
            **base,
            "ok": True,
            "error": "",
            "present": [d.hazard_type for d in parsed.detections if d.present],
            "confs": {d.hazard_type: d.confidence for d in parsed.detections if d.present},
            "latency_ms": latency,
            "in_tok": res.prompt_tokens,
            "out_tok": res.completion_tokens,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, samples))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)

    per_class: dict[str, dict[str, Any]] = {}
    for label, items in by_label.items():
        ok_items = [r for r in items if r["ok"]]
        hits = [r for r in ok_items if label in r["present"]]
        others = [
            r for lab, rs in by_label.items() if lab != label for r in rs if r["ok"]
        ]
        false_pos = [r for r in others if label in r["present"]]
        confs = [r["confs"].get(label, 0.0) for r in hits]
        per_class[label] = {
            "n": len(items),
            "ok": len(ok_items),
            "hits": len(hits),
            "recall": (len(hits) / len(ok_items)) if ok_items else 0.0,
            "fp": len(false_pos),
            "n_other": len(others),
            "fpr": (len(false_pos) / len(others)) if others else 0.0,
            "avg_conf": (sum(confs) / len(confs)) if confs else 0.0,
        }

    ok_rows = [r for r in rows if r["ok"]]
    total_hits = sum(v["hits"] for v in per_class.values())
    total_pos = sum(v["ok"] for v in per_class.values())
    latencies = [r["latency_ms"] for r in ok_rows if r["latency_ms"]]
    return {
        "per_class": per_class,
        "total_hits": total_hits,
        "total_pos": total_pos,
        "macro_recall": (sum(v["recall"] for v in per_class.values()) / len(per_class))
        if per_class else 0.0,
        "macro_fpr": (sum(v["fpr"] for v in per_class.values()) / len(per_class))
        if per_class else 0.0,
        "fail": len(rows) - len(ok_rows),
        "n": len(rows),
        "p50_ms": statistics.median(latencies) if latencies else 0,
        "avg_ms": statistics.mean(latencies) if latencies else 0,
        "in_tok": statistics.mean([r["in_tok"] for r in ok_rows]) if ok_rows else 0,
        "out_tok": statistics.mean([r["out_tok"] for r in ok_rows]) if ok_rows else 0,
    }


def load_samples() -> list[tuple[Path, str]]:
    """从文件名解析真值：HZ-01_未佩戴安全帽_03_0008.jpg → ('HZ-01')"""
    samples: list[tuple[Path, str]] = []
    for path in sorted(DATA_DIR.glob("*.jpg")):
        match = re.match(r"(HZ-\d{2})", path.name)
        if not match:
            continue
        label = match.group(1)
        if label not in CLASS_NAME:  # 跳过 HZ-02（不在 MVP 提示词内）
            continue
        samples.append((path, label))
    return samples


def write_report(results: dict[str, dict[str, Any]], samples: int) -> None:
    lines = [
        "# 百炼（MaaS）视觉模型横向评测",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M')}",
        f"- 测试集：{samples} 张现场图（4 类，文件名即真值；HZ-02 不在 MVP 提示词内已剔除）",
        "- 判定提示词、规则、坐标换算完全一致，只换模型",
        "",
        "## 一、总体对比",
        "",
        "| 模型 | 召回（命中/总数） | 宏平均召回 | 宏平均跨类误报 | 解析失败 | 时延 P50 | 平均 token(入/出) |",
        "|---|---|---|---|---|---|---|",
    ]
    ranked = sorted(results.items(), key=lambda kv: (-kv[1]["macro_recall"], kv[1]["macro_fpr"]))
    for model, stat in ranked:
        lines.append(
            f"| `{model}` | {stat['total_hits']}/{stat['total_pos']} "
            f"| {stat['macro_recall']:.0%} | {stat['macro_fpr']:.0%} "
            f"| {stat['fail']}/{stat['n']} | {stat['p50_ms']:.0f} ms "
            f"| {stat['in_tok']:.0f} / {stat['out_tok']:.0f} |"
        )

    lines += ["", "## 二、分类别明细", ""]
    for model, stat in ranked:
        lines += [f"### `{model}`", "", "| 类别 | 名称 | 召回 | 跨类误报 | 平均置信度 |", "|---|---|---|---|---|"]
        for code in sorted(stat["per_class"]):
            row = stat["per_class"][code]
            lines.append(
                f"| {code} | {CLASS_NAME[code]} | {row['hits']}/{row['ok']} = {row['recall']:.0%} "
                f"| {row['fp']}/{row['n_other']} = {row['fpr']:.0%} | {row['avg_conf']:.2f} |"
            )
        lines.append("")

    lines += [
        "## 三、指标说明（重要）",
        "",
        "- **召回**：该类别的图里模型正确报出该类别的比例（漏报即扣分）。",
        "- **跨类误报**：其他类别的图里模型误报成该类别的比例。这是**没有正常样本时的精确率代理指标**，",
        "  真实精确率仍需 50 张以上「无隐患现场图」才能算出，本报告不夸大。",
        "- 时延为并发条件下的观测值，仅作相对比较；单并发实测约 9~15 秒/张。",
        "",
        "## 四、结论",
        "",
    ]
    best = ranked[0][0]
    lines.append(f"- 综合召回与误报，当前这批图上表现最好的是 **`{best}`**。")
    lines.append("- 若某模型在某一类上明显更好（例如安全帽），可考虑「按类别选模型」，但维护成本会上升，MVP 不建议。")
    lines.append("- 样本仅 20 张，结论用于**排除明显不合适的模型**；正式选型建议扩到每类 30 张以上再跑一次。")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    samples = load_samples()
    if not samples:
        print(f"❌ 未在 {DATA_DIR} 找到带标签的图片")
        return 2
    print(f"测试集：{len(samples)} 张（{sorted({label for _, label in samples})}）")

    settings = Settings()
    if not settings.has_key:
        print("❌ 未配置 MAAS_API_KEY")
        return 2
    client = MaasClient(
        api_key=settings.require_key(),
        base_url=settings.maas_base_url,
        timeout_s=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )
    prompt = build_judge_prompt(vl_categories(load_taxonomy(ROOT / "config" / "hazard_taxonomy.yaml")))

    results: dict[str, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    for model in args.models:
        print(f"\n▶ {model} …", flush=True)
        started = time.perf_counter()
        rows = run_model(client, model, prompt, samples, args.workers)
        stat = summarize(rows)
        results[model] = stat
        all_rows.extend(rows)
        print(
            f"  召回 {stat['total_hits']}/{stat['total_pos']} = {stat['macro_recall']:.0%}"
            f" | 跨类误报 {stat['macro_fpr']:.0%}"
            f" | 失败 {stat['fail']} | P50 {stat['p50_ms']:.0f} ms"
            f" | 用时 {time.perf_counter() - started:.0f}s",
            flush=True,
        )

    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RAW_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["model", "file", "label", "ok", "present", "latency_ms", "in_tok", "out_tok", "error"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in all_rows:
            out = dict(row)
            out["present"] = "|".join(row.get("present") or [])
            writer.writerow(out)

    write_report(results, len(samples))
    print(f"\n报告：{REPORT}")
    print(f"明细：{RAW_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

