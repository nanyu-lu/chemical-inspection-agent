#!/usr/bin/env python3
"""45 项第一批 · VL 基线评测（试点 4 组）。

只做评测，不碰 src/ 与 web/src/：模型调用走现有 MaasClient，图像预处理复用
chem_inspect.imaging（与生产一致：长边压到 1280）。判据来自 config/baseline_criteria.yaml。

口径（重要，写进报告）
- 样本全部为现场「已确认缺陷」图 → 只能算**召回**，没有负样本，不算精确率/误报率。
- 一张图一次调用，prompt 里只问一个子项（CI-11 额外跑一组合并判据做对照）。
- 去重：manifest 中 is_duplicate=0 的 87 张参与，重复图不重复计分。

用法
  .venv/bin/python scripts/eval_baseline.py --dry-run          # 只打印计划与提示词
  .venv/bin/python scripts/eval_baseline.py --limit 2          # 冒烟：每组建 2 条
  .venv/bin/python scripts/eval_baseline.py                    # 全量 89 次
产物
  data/eval/baseline_{6_11,6_13,6_9,CI-11}.csv
  data/eval/baseline_summary.json
  data/eval/baseline_report.md
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from chem_inspect import imaging
from chem_inspect.llm.maas import MaasClient, MaasError
from chem_inspect.settings import Settings

MANIFEST = ROOT / "data" / "eval" / "45项_第一批_manifest.csv"
IMG_BASE = ROOT / "data" / "datasets" / "local" / "45项" / "第一批"
CRITERIA_PATH = ROOT / "config" / "baseline_criteria.yaml"
OUT_DIR = ROOT / "data" / "eval"

# 由 --img-base 覆盖：用于「红圈遮蔽」等对照实验，读同一份 manifest、另一份图
IMG_ROOT = IMG_BASE

MODEL = "qwen3-vl-plus"
LONG_SIDE = 1280
MAX_CALLS = 100

CI11_SUBS = ["11.1", "11.3", "11.4", "11.6", "11.7", "11.8"]

GROUPS: dict[str, dict[str, Any]] = {
    "6.11": {"item_code": "CI-06", "sub_codes": ["6.11"], "modes": ["per_sub"]},
    "6.13": {"item_code": "CI-06", "sub_codes": ["6.13"], "modes": ["per_sub"]},
    "6.9": {"item_code": "CI-06", "sub_codes": ["6.9"], "modes": ["per_sub"]},
    "CI-11": {"item_code": "CI-11", "sub_codes": CI11_SUBS, "modes": ["per_sub", "merged"]},
}

PROMPT_TMPL = """你是化工设备巡检视觉判定器。只判断一个检查项。

检查项：{code} {name}
判据：{criteria}
边界（以下情况不算缺陷）：{boundary}
观察条件：{observation}
上下文：无（现场巡检实拍图，无点位台账与设备型号信息）

纪律：
- 看不清、被遮挡、画面中没有该设备 → present=false, undecidable=true
- confidence 取 0~1 的真实把握，禁止照抄示例
- bbox 用 0~1000 相对坐标；无法给出写 null
- 只输出严格 JSON，不要 markdown

输出：
{{"present": false, "confidence": 0.0, "evidence": "", "bbox": null, "undecidable": false, "reason": ""}}
"""


class ItemVerdict(BaseModel):
    """单检查项输出。extra=ignore 只是为了不让多余键拖垮解析，字段本身严格。"""

    model_config = ConfigDict(extra="ignore")

    present: bool = False
    confidence: float = 0.0
    evidence: str = ""
    bbox: list[float] | None = None
    undecidable: bool = False
    reason: str = ""


@dataclass
class Task:
    group: str
    mode: str
    item_code: str
    sub_code: str
    ask_code: str
    ask_name: str
    file: str
    rel_path: str
    native_w: int
    native_h: int
    prompt: str = ""
    result: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- 数据装配


def strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def load_rows() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    uniq = [r for r in rows if r.get("is_duplicate", "0") in ("0", "", "False")]
    return uniq


def build_prompt(entry: dict[str, str]) -> str:
    boundary = entry["boundary"].strip()
    for prefix in ("不算缺陷：", "不算缺陷:"):
        if boundary.startswith(prefix):
            boundary = boundary[len(prefix) :].strip()
    return PROMPT_TMPL.format(
        code=entry.get("code", ""),
        name=entry["name"],
        criteria=entry["criteria"],
        boundary=boundary,
        observation=entry["observation"],
    )


def build_tasks(rows: list[dict[str, str]], crit: dict[str, Any], groups: list[str]) -> list[Task]:
    subs = crit["sub_items"]
    merged = crit["merged"]
    tasks: list[Task] = []

    for gname in groups:
        spec = GROUPS[gname]
        picked = [r for r in rows if r.get("sub_code") in spec["sub_codes"]]
        for r in picked:
            sub = r["sub_code"]
            if "per_sub" in spec["modes"]:
                entry = subs[sub]
                tasks.append(
                    Task(
                        group=gname,
                        mode="per_sub",
                        item_code=spec["item_code"],
                        sub_code=sub,
                        ask_code=sub,
                        ask_name=entry["name"],
                        file=r["file"],
                        rel_path=r["rel_path"],
                        native_w=int(r.get("width") or 0),
                        native_h=int(r.get("height") or 0),
                        prompt=build_prompt({"code": sub, **entry}),
                    )
                )
        if "merged" in spec["modes"]:
            entry = merged[spec["item_code"]]
            for r in picked:
                tasks.append(
                    Task(
                        group=gname,
                        mode="merged",
                        item_code=spec["item_code"],
                        sub_code=r["sub_code"],
                        ask_code=spec["item_code"],
                        ask_name=entry["name"],
                        file=r["file"],
                        rel_path=r["rel_path"],
                        native_w=int(r.get("width") or 0),
                        native_h=int(r.get("height") or 0),
                        prompt=build_prompt({"code": spec["item_code"], **entry}),
                    )
                )
    return tasks


def build_client() -> MaasClient:
    s = Settings(_env_file=str(ROOT / ".env"))
    if not s.has_key:
        raise SystemExit("未找到 MAAS_API_KEY：请检查项目根目录 .env")
    return MaasClient(
        api_key=s.require_key(),
        base_url=s.maas_base_url,
        timeout_s=120,
        max_retries=1,
    )


# ---------------------------------------------------------------- 单条执行


def run_one(client: MaasClient, t: Task) -> dict[str, Any]:
    path = IMG_ROOT / t.rel_path
    started = time.perf_counter()
    try:
        img = imaging.load_image(path.read_bytes())
        work = imaging.resize_long_side(img, LONG_SIDE)
        payload = imaging.to_jpeg(work)
    except Exception as exc:  # noqa: BLE001 - 单张读图失败不该中断整批
        return {"ok": False, "error": f"读图失败: {exc}", "latency_ms": 0, "json_ok": False}

    res = None
    err = ""
    try:
        res = client.chat_vision(payload, t.prompt, model=MODEL, json_mode=True)
    except MaasError as exc:
        err = f"调用失败: {exc}"

    latency = int((time.perf_counter() - started) * 1000)
    rec: dict[str, Any] = {
        "ok": False,
        "error": err,
        "json_ok": False,
        "schema_ok": False,
        "latency_ms": latency,
        "in_tok": 0,
        "out_tok": 0,
        "present": "",
        "confidence": "",
        "undecidable": "",
        "evidence": "",
        "bbox": "",
        "reason": "",
        "raw": "",
    }
    if res is None:
        return rec

    rec.update(
        latency_ms=res.latency_ms or latency,
        in_tok=res.prompt_tokens,
        out_tok=res.completion_tokens,
        raw=res.text[:1500],
    )

    try:
        data = json.loads(strip_fence(res.text))
        rec["json_ok"] = True
    except json.JSONDecodeError as exc:
        rec["error"] = f"JSON 解析失败: {exc}"
        return rec

    try:
        v = ItemVerdict.model_validate(data)
        rec["schema_ok"] = True
    except ValidationError as exc:
        rec["error"] = f"字段校验失败: {exc}".replace("\n", " ")[:300]
        return rec

    rec.update(
        ok=True,
        present=v.present,
        confidence=round(float(v.confidence), 3),
        undecidable=v.undecidable,
        evidence=v.evidence[:300],
        bbox=json.dumps(v.bbox, ensure_ascii=False) if v.bbox else "",
        reason=v.reason[:300],
    )
    return rec


def run_all(client: MaasClient, tasks: list[Task], concurrency: int) -> None:
    total = len(tasks)
    done = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(run_one, client, t): t for t in tasks}
        for fut in as_completed(futs):
            t = futs[fut]
            t.result = fut.result()
            done += 1
            r = t.result
            flag = "T" if r.get("present") is True else ("U" if r.get("undecidable") is True else "F")
            print(
                f"[{done:>3}/{total}] {t.group:<6} {t.mode:<7} {t.sub_code:<5} "
                f"{t.file[:34]:<34} -> {flag} conf={r.get('confidence','')} "
                f"{r.get('latency_ms',0)}ms"
                + (f"  ERR={r.get('error','')[:60]}" if r.get("error") else ""),
                flush=True,
            )
    print(f"\n总耗时 {time.perf_counter() - started:.1f}s", flush=True)


# ---------------------------------------------------------------- 统计与产出


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def quantile(values: list[int], p: float) -> int:
    """最近秩法分位数，避免小样本插值带来的假精度。"""
    if not values:
        return 0
    idx = min(len(values) - 1, round(p * (len(values) - 1)))
    return int(values[idx])


def summarize(tasks: list[Task]) -> dict[str, Any]:
    buckets: dict[tuple[str, str], list[Task]] = {}
    for t in tasks:
        buckets.setdefault((t.group, t.mode), []).append(t)

    out: dict[str, Any] = {"model": MODEL, "long_side": LONG_SIDE, "groups": {}}
    for (group, mode), items in sorted(buckets.items()):
        n = len(items)
        lat = sorted(t.result.get("latency_ms", 0) for t in items)
        present = sum(1 for t in items if t.result.get("present") is True)
        undec = sum(1 for t in items if t.result.get("undecidable") is True)
        bad_json = sum(1 for t in items if not t.result.get("json_ok"))
        failed = [t for t in items if not t.result.get("ok")]

        out["groups"].setdefault(group, {})[mode] = {
            "n": n,
            "present_true": present,
            "recall": round(present / n, 4) if n else 0.0,
            "undecidable": undec,
            "undecidable_rate": round(undec / n, 4) if n else 0.0,
            "invalid_json": bad_json,
            "invalid_json_rate": round(bad_json / n, 4) if n else 0.0,
            "p50_ms": quantile(lat, 0.5),
            "p90_ms": quantile(lat, 0.9),
            "in_tok_total": sum(t.result.get("in_tok", 0) for t in items),
            "out_tok_total": sum(t.result.get("out_tok", 0) for t in items),
            "failed_files": [t.file for t in failed],
        }
    return out


def write_csvs(tasks: list[Task], tag: str = "") -> list[Path]:
    cols = [
        "group", "mode", "item_code", "sub_code", "ask_code", "ask_name",
        "file", "rel_path", "native_w", "native_h",
        "present", "confidence", "undecidable", "evidence", "bbox", "reason",
        "latency_ms", "in_tok", "out_tok", "json_ok", "schema_ok", "error",
    ]
    written: list[Path] = []
    for group in GROUPS:
        items = [t for t in tasks if t.group == group]
        if not items:
            continue
        stem = group.replace(".", "_")
        name = f"baseline_{tag}_{stem}.csv" if tag else f"baseline_{stem}.csv"
        path = OUT_DIR / name
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for t in items:
                row = {
                    "group": t.group, "mode": t.mode, "item_code": t.item_code,
                    "sub_code": t.sub_code, "ask_code": t.ask_code, "ask_name": t.ask_name,
                    "file": t.file, "rel_path": t.rel_path,
                    "native_w": t.native_w, "native_h": t.native_h,
                }
                row.update({k: t.result.get(k, "") for k in cols if k not in row})
                w.writerow(row)
        written.append(path)
    return written


def write_report(summary: dict[str, Any], written: list[Path], tag: str = "") -> Path:
    title = "# 45 项第一批 · VL 基线报告"
    if tag:
        title = f"# 45 项第一批 · 对照实验报告（{tag}）"
    lines = [
        title,
        "",
        f"- 模型：`{summary['model']}`，长边压到 {summary['long_side']}（与生产一致）",
        f"- 图片目录：`{summary.get('img_root', str(IMG_BASE))}`",
        f"- 判据文件：`{summary.get('criteria', str(CRITERIA_PATH))}`",
        "- 样本：manifest 94 行，去重后 87 张参与（`is_duplicate=1` 的 7 张不计分）",
        "- 口径：样本全为已确认缺陷图，**只能报召回**；无负样本，不算精确率/误报率",
        "",
    ]
    if not tag:
        lines += [
            "> ⚠️ **这批图带人工红圈标注**（6.11/6.13 抽样 100%，CI-11 88%），且带公众号水印。",
            "> 召回只能当**上限**读：它测的是「缺陷被圈出后能否确认」，不是「能否自主发现」。",
            "> 详见 `data/eval/baseline_分析.md`。",
            "",
        ]
    lines += [
        "| 组 | 问法 | n | 召回 | 不可判定 | 无效JSON | P50 | P90 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for group, modes in summary["groups"].items():
        for mode, m in modes.items():
            lines.append(
                f"| {group} | {mode} | {m['n']} | {pct(m['recall'])} ({m['present_true']}/{m['n']}) "
                f"| {pct(m['undecidable_rate'])} | {pct(m['invalid_json_rate'])} "
                f"| {m['p50_ms']}ms | {m['p90_ms']}ms |"
            )
    lines += ["", "## 失败样本", ""]
    any_fail = False
    for group, modes in summary["groups"].items():
        for mode, m in modes.items():
            if m["failed_files"]:
                any_fail = True
                lines.append(f"- {group}/{mode}: " + ", ".join(m["failed_files"]))
    if not any_fail:
        lines.append("- 无")
    lines += ["", "## 产物", ""] + [f"- `{p.relative_to(ROOT)}`" for p in written]
    path = OUT_DIR / (f"baseline_{tag}_report.md" if tag else "baseline_report.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- 入口


def main() -> int:
    ap = argparse.ArgumentParser(description="45 项第一批 VL 基线评测")
    ap.add_argument("--groups", default="6.11,6.13,6.9,CI-11")
    ap.add_argument("--limit", type=int, default=0, help="每组最多跑 N 条（冒烟用）")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划与样例提示词")
    ap.add_argument("--force", action="store_true", help=f"超过 {MAX_CALLS} 次调用仍执行")
    ap.add_argument("--img-base", default="", help="替换图片根目录（对照实验用）")
    ap.add_argument("--criteria", default="", help="替换判据文件（判据 A/B 用）")
    ap.add_argument("--tag", default="", help="产物文件名后缀，避免覆盖基线")
    ap.add_argument("--modes", default="", help="只跑指定问法，逗号分隔：per_sub,merged")
    args = ap.parse_args()

    global IMG_ROOT
    img_root = Path(args.img_base).expanduser().resolve() if args.img_base else IMG_BASE
    if not img_root.is_dir():
        raise SystemExit(f"图片目录不存在: {img_root}")
    IMG_ROOT = img_root

    criteria_path = Path(args.criteria).expanduser().resolve() if args.criteria else CRITERIA_PATH
    if not criteria_path.exists():
        raise SystemExit(f"判据文件不存在: {criteria_path}")

    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        raise SystemExit(f"未知分组: {unknown}，可选 {list(GROUPS)}")

    crit = yaml.safe_load(criteria_path.read_text(encoding="utf-8"))
    rows = load_rows()
    tasks = build_tasks(rows, crit, groups)

    if args.modes:
        wanted = {m.strip() for m in args.modes.split(",") if m.strip()}
        tasks = [t for t in tasks if t.mode in wanted]

    if args.limit:
        capped: list[Task] = []
        for g in groups:
            capped.extend([t for t in tasks if t.group == g][: args.limit])
        tasks = capped

    print(f"计划调用 {len(tasks)} 次（模型 {MODEL}，并发 {args.concurrency}）")
    for g in groups:
        items = [t for t in tasks if t.group == g]
        per = {m: sum(1 for t in items if t.mode == m) for m in {t.mode for t in items}}
        print(f"  {g:<6} 合计 {len(items):>3} 次  {per}")

    if args.dry_run:
        t = tasks[0]
        print("\n--- 样例提示词 ---")
        print(t.prompt)
        print(f"--- 样例图 ---\n{IMG_ROOT / t.rel_path}")
        return 0

    if len(tasks) > MAX_CALLS and not args.force:
        print(f"\n⚠️ 计划调用 {len(tasks)} 次 > {MAX_CALLS}，需先与用户确认。加 --force 才执行。")
        return 2

    client = build_client()
    run_all(client, tasks, args.concurrency)

    summary = summarize(tasks)
    summary["img_root"] = str(IMG_ROOT.relative_to(ROOT)) if IMG_ROOT.is_relative_to(ROOT) else str(IMG_ROOT)
    summary["criteria"] = (
        str(criteria_path.relative_to(ROOT)) if criteria_path.is_relative_to(ROOT) else str(criteria_path)
    )
    tag = args.tag
    summary_path = OUT_DIR / (f"baseline_{tag}_summary.json" if tag else "baseline_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    written = write_csvs(tasks, tag)
    report = write_report(summary, written, tag)

    print("\n=== 结果 ===")
    for group, modes in summary["groups"].items():
        for mode, m in modes.items():
            print(
                f"{group:<6} {mode:<7} n={m['n']:>3} 召回={pct(m['recall']):>6} "
                f"不可判={pct(m['undecidable_rate']):>6} 无效JSON={pct(m['invalid_json_rate']):>6} "
                f"P50={m['p50_ms']}ms P90={m['p90_ms']}ms"
            )
    print(f"\n汇总 {summary_path.relative_to(ROOT)}")
    print(f"报告 {report.relative_to(ROOT)}")
    for p in written:
        print(f"明细 {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
