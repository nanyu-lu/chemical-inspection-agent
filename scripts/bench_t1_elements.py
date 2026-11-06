#!/usr/bin/env python3
"""T1：纯识别能力（模型「只看不判」）。

与 T2（判定式提问）、T3（完整流水线）的区别：
T1 用的是一条**明确禁止下结论**的提示词，只让模型列出画面元素，用于测"识别能力本身"。

打分口径（双轨）：
  · 自动（代理）：该图真值类别的**关键元素**是否被提到（每类 2 组关键词，全中算命中）
  · 自动（代理）：六类元素（人员/设备/通道与门/消防器材/标识/环境异常）覆盖了几类
  · 人工（严格）：CSV 里留了 3 列，人工勾"漏关键元素/有幻觉/备注"，据此算真实召回与幻觉率

用法：
    python scripts/bench_t1_elements.py
    python scripts/bench_t1_elements.py --model qwen3.5-omni-plus --workers 4

产物：data/eval/t1_elements.csv、data/eval/t1_summary.json
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

from chem_inspect.contracts import ElementOutput
from chem_inspect.llm.maas import MaasClient, MaasError
from chem_inspect.prompt import build_element_prompt
from chem_inspect.settings import Settings

DATA_DIR = ROOT / "测试图片"
OUT_CSV = ROOT / "data" / "eval" / "t1_elements.csv"
OUT_JSON = ROOT / "data" / "eval" / "t1_summary.json"

CLASS_NAME = {
    "HZ-01": "未佩戴安全帽",
    "HZ-04": "消防通道堵塞",
    "HZ-05": "消防器材遮挡",
    "HZ-06": "应急出口堵塞",
}

# 每类隐患对应的「关键元素」关键词组：全部命中才记为"元素齐"
KEY_GROUPS: dict[str, list[tuple[str, list[str]]]] = {
    "HZ-01": [("人员", ["人", "工人", "作业人员", "员工"]), ("安全帽", ["安全帽", "安全头盔", "帽子"])],
    "HZ-04": [("通道", ["通道", "走道", "划线"]), ("堆物", ["堆", "托盘", "货物", "纸箱", "杂物", "箱"])],
    "HZ-05": [("器材", ["灭火器", "消防箱", "消防栓", "消火栓"]), ("遮挡", ["遮挡", "挡住", "覆盖", "堆"])],
    "HZ-06": [("门/出口", ["门", "出口"]), ("堵塞", ["堵", "堆", "挡", "封"])],
}

# 六类元素（用于统计"覆盖了几类"）
CANON_GROUPS: dict[str, list[str]] = {
    "人员": ["人", "人员", "工人", "员工"],
    "设备": ["设备", "罐", "泵", "阀", "法兰", "管道", "管"],
    "通道与门": ["通道", "门", "出口", "走道", "划线"],
    "消防器材": ["灭火器", "消防箱", "消防栓", "消火栓", "消防"],
    "标识与指示灯": ["标识", "标志", "指示", "灯", "牌"],
    "环境异常": ["积液", "积水", "油污", "烟雾", "堆", "破损", "锈", "泄漏", "渗"],
}


def load_samples() -> list[tuple[Path, str]]:
    samples: list[tuple[Path, str]] = []
    for path in sorted(DATA_DIR.glob("*.jpg")):
        match = re.match(r"(HZ-\d{2})", path.name)
        if match and match.group(1) in CLASS_NAME:
            samples.append((path, match.group(1)))
    return samples


def strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def score(elements: list[dict[str, Any]], label: str) -> tuple[bool, str, int]:
    """返回 (关键元素是否齐, 命中详情, 覆盖的六类数量)。"""
    blob = " ".join(
        f"{e.get('name', '')} {e.get('category', '')} {e.get('state', '')}" for e in elements
    )
    groups = KEY_GROUPS[label]
    hits = [name for name, words in groups if any(w in blob for w in words)]
    hit_all = len(hits) == len(groups)
    detail = "/".join(hits) or "无"

    covered = sum(1 for words in CANON_GROUPS.values() if any(w in blob for w in words))
    return hit_all, detail, covered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=4)
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
    prompt = build_element_prompt()

    def one(item: tuple[Path, str]) -> dict[str, Any]:
        path, label = item
        started = time.perf_counter()
        base: dict[str, Any] = {
            "file": path.name, "label": label, "ok": False, "n_elements": 0,
            "key_hit": False, "key_detail": "", "covered": 0,
            "latency_ms": 0, "in_tok": 0, "out_tok": 0, "error": "",
        }
        try:
            res = client.chat_vision(path.read_bytes(), prompt, model=model, json_mode=True)
        except MaasError as exc:
            return {**base, "error": str(exc)[:200],
                    "latency_ms": int((time.perf_counter() - started) * 1000)}
        base.update(
            latency_ms=res.latency_ms, in_tok=res.prompt_tokens, out_tok=res.completion_tokens
        )
        try:
            parsed = ElementOutput.model_validate(json.loads(strip_fence(res.text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            return {**base, "error": f"解析失败: {str(exc)[:160]}"}

        items = [e.model_dump() for e in parsed.elements]
        hit, detail, covered = score(items, label)
        return {
            **base, "ok": True, "n_elements": len(items),
            "key_hit": hit, "key_detail": detail, "covered": covered,
        }

    print(f"T1 元素描述：{len(samples)} 张，模型 {model}，并发 {args.workers}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, samples))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) + ["人工_漏关键元素", "人工_有幻觉", "人工_备注"]
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "人工_漏关键元素": "", "人工_有幻觉": "", "人工_备注": ""})

    ok_rows = [r for r in rows if r["ok"]]
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ok_rows:
        by_label[row["label"]].append(row)

    per_class = {
        code: {
            "name": CLASS_NAME[code],
            "n": len(items),
            "key_hit": sum(1 for r in items if r["key_hit"]),
            "hit_rate": round(sum(1 for r in items if r["key_hit"]) / len(items), 3),
        }
        for code, items in by_label.items()
    }
    all_hits = sum(1 for r in ok_rows if r["key_hit"])
    summary = {
        "model": model,
        "n": len(rows),
        "ok": len(ok_rows),
        "fail": len(rows) - len(ok_rows),
        "key_hit_rate": round(all_hits / len(ok_rows), 3) if ok_rows else 0.0,
        "avg_elements": round(statistics.mean([r["n_elements"] for r in ok_rows]), 1) if ok_rows else 0,
        "avg_covered_groups": round(statistics.mean([r["covered"] for r in ok_rows]), 2) if ok_rows else 0,
        "p50_ms": int(statistics.median([r["latency_ms"] for r in ok_rows])) if ok_rows else 0,
        "per_class": per_class,
        "ran_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== T1 汇总 ===")
    for code in sorted(per_class):
        row = per_class[code]
        print(f"{code} {row['name']}: 关键元素齐 {row['key_hit']}/{row['n']} = {row['hit_rate']:.0%}")
    print(
        f"总体：关键元素命中率 {summary['key_hit_rate']:.0%}"
        f" | 平均元素数 {summary['avg_elements']}"
        f" | 平均覆盖 {summary['avg_covered_groups']}/6 类"
        f" | 失败 {summary['fail']} | P50 {summary['p50_ms']} ms"
    )
    print(f"\n明细：{OUT_CSV}\n汇总：{OUT_JSON}")
    print("提示：CSV 最后三列留给人工勾选（漏关键元素 / 有幻觉 / 备注），填完可算严格召回与幻觉率。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
