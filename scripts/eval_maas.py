#!/usr/bin/env python3
"""用真实训练图做一次快速评估（第一版：只测「该类是否被检出」）。

⚠️ 能力边界（务必看清）
- 正样本来自各隐患类别的图集，因此只能得到**每类检出率（recall 代理）**；
- **没有正常/负样本集，所以算不出精确率与误报率** —— 需要再补 50+ 张"无隐患"现场图。
- 不做 bbox IoU 评估（当前图集只有图级标签，没有框标注）。

用法：
  uv run python scripts/eval_maas.py --per-class 6
  uv run python scripts/eval_maas.py --data-dir <图片根目录> --per-class 10
产物：
  docs/评估报告初版.md、data/eval/raw.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError

from chem_inspect.contracts import VLJudgeOutput
from chem_inspect.llm.maas import MaasClient, MaasError
from chem_inspect.prompt import build_judge_prompt, load_taxonomy, vl_categories
from chem_inspect.settings import get_settings

DEFAULT_DATA_DIR = (
    ROOT
    / "云文档"
    / "化工巡检项目文档"
    / "yolo调研"
    / "模型训练资料"
    / "模型训练图片"
)

# 目录名前缀 → 隐患类别（目录名来自团队已有图集）
FOLDER_TO_TYPE: dict[str, str] = {
    "01_人员拥挤": "HZ-02",
    "02_消防通道阻塞": "HZ-04",
    "03_未携带安全帽": "HZ-01",
    "04_消防器材遮挡": "HZ-05",
    "05_应急出口堵塞": "HZ-06",
}

TYPE_TO_NAME: dict[str, str] = {
    "HZ-01": "未佩戴安全帽",
    "HZ-02": "人员超员聚集",
    "HZ-03": "表计读数异常",
    "HZ-04": "消防通道堵塞",
    "HZ-05": "消防器材遮挡",
    "HZ-06": "应急出口堵塞",
}

RAW_DIR = ROOT / "data" / "eval"
REPORT_PATH = ROOT / "docs" / "评估报告初版.md"


def sample_images(folder: Path, n: int) -> list[Path]:
    """确定性等距抽样，避免每次跑出不同子集。"""
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not files:
        return []
    if len(files) <= n:
        return files
    step = len(files) / n
    return [files[min(int(i * step), len(files) - 1)] for i in range(n)]


def evaluate(
    client: MaasClient, model: str, prompt: str, rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        image = Path(row["path"]).read_bytes()
        started = time.perf_counter()
        try:
            res = client.chat_vision(image, prompt, model=model, json_mode=True)
        except MaasError as exc:
            row.update(ok=False, error=str(exc)[:300], present_types=[], latency_ms=0)
            print(f"  FAIL {row['file']}: {exc}")
            continue
        row["latency_ms"] = res.latency_ms or int((time.perf_counter() - started) * 1000)
        row["prompt_tokens"] = res.prompt_tokens
        row["completion_tokens"] = res.completion_tokens
        row["raw"] = res.text[:2000]
        try:
            data = json.loads(res.text.strip().strip("`").removeprefix("json").strip())
            out = VLJudgeOutput.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            row.update(ok=False, error=f"解析失败: {exc}"[:300], present_types=[])
            print(f"  PARSE-FAIL {row['file']}")
            continue
        present = [d.hazard_type for d in out.detections if d.present]
        confs = {d.hazard_type: d.confidence for d in out.detections if d.present}
        row.update(ok=True, error="", present_types=present, confs=confs)
        print(
            f"  {row['file']}: 真值={row['label']} 检出={present or '无'} "
            f"{res.latency_ms} ms"
        )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_class[row["label"]].append(row)

    per_class: list[dict[str, Any]] = []
    for label in sorted(by_class):
        items = by_class[label]
        ok_items = [r for r in items if r["ok"]]
        hits = [r for r in ok_items if label in r["present_types"]]
        confs = [r["confs"].get(label, 0.0) for r in hits]
        per_class.append(
            {
                "label": label,
                "name": TYPE_TO_NAME.get(label, label),
                "n": len(items),
                "ok": len(ok_items),
                "hit": len(hits),
                "hit_rate": (len(hits) / len(ok_items)) if ok_items else 0.0,
                "avg_conf": (sum(confs) / len(confs)) if confs else 0.0,
                "avg_latency_ms": (
                    sum(r["latency_ms"] for r in ok_items) / len(ok_items) if ok_items else 0
                ),
            }
        )

    confusion: dict[str, Counter[str]] = {}
    for label, items in by_class.items():
        counter: Counter[str] = Counter()
        for r in items:
            for t in r["present_types"]:
                counter[t] += 1
        confusion[label] = counter

    latencies = [r["latency_ms"] for r in rows if r["ok"]]
    tokens_in = [r["prompt_tokens"] for r in rows if r["ok"]]
    tokens_out = [r["completion_tokens"] for r in rows if r["ok"]]
    return {
        "per_class": per_class,
        "confusion": confusion,
        "total": len(rows),
        "failed": sum(1 for r in rows if not r["ok"]),
        "latency_p50": statistics.median(latencies) if latencies else 0,
        "latency_max": max(latencies) if latencies else 0,
        "avg_in": statistics.mean(tokens_in) if tokens_in else 0,
        "avg_out": statistics.mean(tokens_out) if tokens_out else 0,
    }


def render_report(summary: dict[str, Any], model: str, prompt_version: str) -> str:
    lines = [
        "# 隐患识别 · 评估报告（初版）",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模型：`{model}`，提示词版本：`{prompt_version}`",
        f"- 样本：{summary['total']} 张（各隐患类别等距抽样）",
        "",
        "> ⚠️ 本版**只测检出率（recall 代理）**：样本全部为「该类别确有隐患」的图，",
        "> 没有正常/负样本，因此**算不出精确率与误报率**。补 50+ 张无隐患现场图后才能给出完整指标。",
        "",
        "## 一、每类检出率",
        "",
        "| 类别 | 名称 | 样本 | 成功 | 检出 | 检出率 | 平均置信度 | 平均时延 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["per_class"]:
        lines.append(
            f"| {row['label']} | {row['name']} | {row['n']} | {row['ok']} | {row['hit']} "
            f"| {row['hit_rate']:.0%} | {row['avg_conf']:.2f} | {row['avg_latency_ms']:.0f} ms |"
        )
    lines += [
        "",
        "## 二、交叉检出（真值类别 → 模型实际报出的类别）",
        "",
        "| 真值 | 报出类别分布 |",
        "|---|---|",
    ]
    for label, counter in sorted(summary["confusion"].items()):
        dist = "、".join(f"{k}×{v}" for k, v in counter.most_common()) or "（无）"
        lines.append(f"| {label} | {dist} |")
    lines += [
        "",
        "## 三、性能与稳定性",
        "",
        f"- 失败/解析失败：{summary['failed']} / {summary['total']}",
        f"- 时延中位数：{summary['latency_p50']:.0f} ms，最大 {summary['latency_max']} ms",
        f"- 平均 token：输入 {summary['avg_in']:.0f}，输出 {summary['avg_out']:.0f}",
        "",
        "## 四、结论与下一步",
        "",
        "1. 逐类看「检出率低于 80%」的类别，优先补数据或细化判据（而不是先改模型）。",
        "2. 交叉检出里若出现稳定的跨类误报，说明这两类在提示词中需要更强的互斥描述。",
        "3. **补 50 张以上无隐患现场图**，重跑本脚本即可得到精确率与误报率。",
        "4. 本报告只覆盖 VL 直判；HZ-03 读表走 `qwen-vl-ocr`，需单独评估。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--per-class", type=int, default=6)
    parser.add_argument("--out", default=str(REPORT_PATH))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"❌ 数据目录不存在：{data_dir}")
        return 2

    settings = get_settings()
    if not settings.has_key:
        print("❌ 未配置 MAAS_API_KEY")
        return 2
    client = MaasClient(
        api_key=settings.require_key(),
        base_url=settings.maas_base_url,
        timeout_s=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )

    taxonomy = load_taxonomy(ROOT / "config" / "hazard_taxonomy.yaml")
    prompt = build_judge_prompt(vl_categories(taxonomy))
    prompt_types = {c["id"] for c in vl_categories(taxonomy)}
    model = settings.maas_vision_model

    rows: list[dict[str, Any]] = []
    for folder_name, hazard_type in FOLDER_TO_TYPE.items():
        if hazard_type not in prompt_types:
            print(f"跳过 {folder_name}：{hazard_type} 未纳入 MVP 提示词（in_mvp=false）")
            continue
        folder = data_dir / folder_name
        if not folder.exists():
            print(f"跳过（不存在）：{folder}")
            continue
        picked = sample_images(folder, args.per_class)
        print(f"\n[{folder_name}] {len(picked)} 张 → 真值 {hazard_type}")
        current = [{"path": str(p), "file": p.name, "label": hazard_type} for p in picked]
        evaluate(client, model, prompt, current)
        rows.extend(current)

    if not rows:
        print("❌ 没有可用样本")
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with (RAW_DIR / "raw.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "file",
                "label",
                "ok",
                "present_types",
                "latency_ms",
                "prompt_tokens",
                "completion_tokens",
                "error",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["present_types"] = "|".join(row.get("present_types") or [])
            writer.writerow(out)

    summary = summarize(rows)
    report = render_report(summary, model, "v1")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print("\n=== 汇总 ===")
    for row in summary["per_class"]:
        print(
            f"{row['label']} {row['name']}: {row['hit']}/{row['ok']} "
            f"= {row['hit_rate']:.0%}  平均时延 {row['avg_latency_ms']:.0f} ms"
        )
    print(f"\n报告：{out_path}")
    print(f"明细：{RAW_DIR / 'raw.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



