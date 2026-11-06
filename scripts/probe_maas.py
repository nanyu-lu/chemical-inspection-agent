#!/usr/bin/env python3
"""千炼（MaaS）接口探针。

目的：在写业务之前，用最小成本确认 5 件事
  1) 鉴权是否可用（GET /models）
  2) 视觉模型能否接收 **base64 内联图片**
  3) 是否支持 response_format=json_object（结构化输出）
  4) 视觉判定的时延与 token 量级
  5) OCR 模型能否抽取表计读数

用法：  uv run python scripts/probe_maas.py [--image 现场图路径]
产物：  docs/千炼探针报告.md、data/probe/*.jpg、data/probe/result.json
说明：  没有现场图时使用**合成图**，仅验证接口机制，不代表识别效果。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chem_inspect.contracts import MeterReading, VLJudgeOutput
from chem_inspect.llm.maas import MaasClient, MaasError
from chem_inspect.prompt import build_judge_prompt, load_taxonomy, vl_categories
from chem_inspect.settings import get_settings

PROBE_DIR = ROOT / "data" / "probe"
RAW_DIR = PROBE_DIR / "raw"
REPORT_PATH = ROOT / "docs" / "千炼探针报告.md"

_TAXONOMY = load_taxonomy(ROOT / "config" / "hazard_taxonomy.yaml")
VISION_PROMPT = build_judge_prompt(vl_categories(_TAXONOMY))



OCR_PROMPT = """读取图中仪表（pressure gauge）的读数。
只输出严格 JSON，不要 markdown、不要解释：
{"raw_text":"表盘上看到的完整文本","value":数值或null,"unit":"单位或null","confidence":0.95}
其中 confidence 取 0~1 的真实置信度，禁止照抄示例值。
"""



# --------------------------------------------------------------------------- 合成测试图


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_scene_image(path: Path) -> Path:
    """合成"仓库门口堆物"场景图（仅用于验证接口机制）。"""
    w, h = 960, 720
    img = Image.new("RGB", (w, h), (232, 232, 232))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 430, w, h], fill=(148, 148, 148))              # 地面
    d.rectangle([600, 170, 830, 520], fill=(96, 112, 96), outline=(40, 40, 40), width=6)  # 出口门
    d.rectangle([668, 138, 762, 168], fill=(0, 158, 82))            # 应急指示牌
    d.text((676, 143), "EXIT", fill=(255, 255, 255), font=_font(24))
    d.rectangle([600, 440, 726, 566], fill=(182, 140, 90), outline=(92, 70, 44), width=3)  # 纸箱
    d.rectangle([712, 470, 832, 578], fill=(172, 130, 86), outline=(92, 70, 44), width=3)
    d.rectangle([640, 570, 790, 660], fill=(162, 122, 80), outline=(92, 70, 44), width=3)
    d.rectangle([862, 402, 908, 520], fill=(200, 34, 34))           # 灭火器（被遮挡）
    d.ellipse([186, 296, 244, 354], fill=(232, 192, 162))           # 人员头部（无安全帽）
    d.rectangle([172, 356, 252, 520], fill=(44, 72, 140))           # 身体
    d.text((18, 16), "SYNTHETIC TEST IMAGE", fill=(20, 20, 20), font=_font(22))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=90)
    return path


def make_gauge_image(path: Path) -> Path:
    """合成压力表读数图（0.85 MPa），用于 OCR 验证。"""
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 30, 580, 450], fill=(255, 255, 255), outline=(60, 60, 60), width=6)
    cx, cy, r = 320, 240, 150
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(30, 30, 30), width=6)
    for i in range(11):
        angle = -210 + i * 24
        import math

        rad = math.radians(angle)
        x1, y1 = cx + (r - 18) * math.cos(rad), cy + (r - 18) * math.sin(rad)
        x2, y2 = cx + (r - 2) * math.cos(rad), cy + (r - 2) * math.sin(rad)
        d.line([x1, y1, x2, y2], fill=(30, 30, 30), width=3)
    import math

    needle = math.radians(-210 + 8.5 * 24)
    d.line([cx, cy, cx + (r - 26) * math.cos(needle), cy + (r - 26) * math.sin(needle)],
           fill=(200, 30, 30), width=5)
    d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(30, 30, 30))
    d.text((cx - 46, cy + 46), "0.85", fill=(20, 20, 20), font=_font(40))
    d.text((cx - 34, cy + 96), "MPa", fill=(20, 20, 20), font=_font(28))
    d.text((88, 396), "P-01", fill=(20, 20, 20), font=_font(26))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=92)
    return path


# --------------------------------------------------------------------------- 工具


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _parse_json(text: str) -> tuple[dict[str, Any] | None, str]:
    raw = _strip_code_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败: {exc}"
    if not isinstance(data, dict):
        return None, "顶层不是 JSON 对象"
    return data, ""


def _rec(results: list[dict[str, Any]], step: str, ok: bool, detail: str, **extra: Any) -> None:
    item: dict[str, Any] = {"step": step, "ok": ok, "detail": detail}
    item.update(extra)
    results.append(item)
    print(f"[{'PASS' if ok else 'FAIL'}] {step}: {detail}")


# --------------------------------------------------------------------------- 探针主流程


def run_vision(
    client: MaasClient, model: str, image_path: Path, results: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """视觉判定。先试 json_object，不支持则自动降级为「提示词约束 + 后处理」。"""
    image = image_path.read_bytes()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        res = client.chat_vision(image, VISION_PROMPT, model=model, json_mode=True)
        mode = "response_format=json_object"
    except MaasError as exc:
        _rec(results, "视觉判定(json_object)", False, f"降级重试：{exc}")
        try:
            res = client.chat_vision(image, VISION_PROMPT, model=model, json_mode=False)
            mode = "prompt-only"
        except MaasError as exc2:
            _rec(results, "视觉判定", False, f"调用失败：{exc2}")
            return None

    (RAW_DIR / "vision_response.txt").write_text(res.text, encoding="utf-8")
    parsed, err = _parse_json(res.text)
    extra = {
        "latency_ms": res.latency_ms,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "model": res.model,
        "mode": mode,
        "preview": res.text[:800],
    }
    if parsed is None:
        _rec(results, "视觉判定", False, f"{err}（模式 {mode}）", **extra)
        return None

    schema_err = ""
    try:
        parsed = VLJudgeOutput.model_validate(parsed).model_dump()
    except ValidationError as exc:  # 契约不匹配也是有效信息
        schema_err = str(exc)
    _rec(
        results,
        "视觉判定",
        True,
        f"{res.latency_ms} ms, in={res.prompt_tokens} out={res.completion_tokens} tokens, 模式 {mode}"
        + (f"，契约校验未通过：{schema_err[:200]}" if schema_err else "，契约校验通过"),
        schema_ok=not schema_err,
        **extra,
    )
    return parsed


def run_ocr(
    client: MaasClient, model: str, image_path: Path, results: list[dict[str, Any]]
) -> dict[str, Any] | None:
    image = image_path.read_bytes()
    try:
        res = client.chat_vision(image, OCR_PROMPT, model=model, json_mode=True)
    except MaasError as exc:
        _rec(results, "读表 OCR", False, f"调用失败：{exc}")
        return None

    (RAW_DIR / "ocr_response.txt").write_text(res.text, encoding="utf-8")
    parsed, err = _parse_json(res.text)
    extra = {
        "latency_ms": res.latency_ms,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
        "model": res.model,
        "preview": res.text[:400],
    }
    if parsed is None:
        _rec(results, "读表 OCR", False, err, **extra)
        return None

    schema_err = ""
    try:
        parsed = MeterReading.model_validate(parsed).model_dump()
    except ValidationError as exc:
        schema_err = str(exc)
    _rec(
        results,
        "读表 OCR",
        True,
        f"{res.latency_ms} ms, 值={parsed.get('value')} {parsed.get('unit') or ''}"
        + (f"，契约校验未通过：{schema_err[:200]}" if schema_err else ""),
        schema_ok=not schema_err,
        **extra,
    )
    return parsed


def run_text(client: MaasClient, model: str, results: list[dict[str, Any]]) -> None:
    prompt = '只输出严格 JSON：{"ok": true, "reply": "pong"}'
    try:
        res = client.chat_text(prompt, model=model, json_mode=True)
    except MaasError as exc:
        _rec(results, "文本模型(json_object)", False, f"调用失败：{exc}")
        return
    parsed, err = _parse_json(res.text)
    _rec(
        results,
        "文本模型(json_object)",
        parsed is not None,
        f"{res.latency_ms} ms, in={res.prompt_tokens} out={res.completion_tokens} tokens"
        + (f"，{err}" if parsed is None else ""),
        model=res.model,
        preview=res.text[:300],
    )


# --------------------------------------------------------------------------- 报告


def render_report(
    *,
    base_url: str,
    masked_key: str,
    network_mode: str,
    models: list[str] | None,
    results: list[dict[str, Any]],
    vision_models: list[str],
    scene_path: Path,
    gauge_path: Path,
) -> str:
    lines: list[str] = ["# 千炼（MaaS）接口探针报告", ""]
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 网关地址：`{base_url}`")
    lines.append(f"- 密钥：`{masked_key}`")
    lines.append(f"- 网络模式：`{network_mode}`")
    lines.append(f"- 模型总数：{len(models) if models is not None else '获取失败'}")
    lines.append("")
    lines.append("## 结论速览")
    lines.append("")
    lines.append("| 检查项 | 结果 |")
    lines.append("|---|---|")
    for item in results:
        lines.append(f"| {item['step']} | {'✅ 通过' if item['ok'] else '❌ 未通过'} |")
    lines.append("")
    lines.append("## 视觉候选模型")
    lines.append("")
    if vision_models:
        lines.append("```")
        lines.extend(vision_models)
        lines.append("```")
    else:
        lines.append("（未获取到模型清单）")
    lines.append("")
    lines.append("## 明细")
    lines.append("")
    for item in results:
        lines.append(f"### {item['step']}")
        lines.append("")
        lines.append(f"- 结果：{'通过' if item['ok'] else '未通过'}")
        lines.append(f"- 说明：{item['detail']}")
        for key in ("model", "mode", "latency_ms", "prompt_tokens", "completion_tokens"):
            if item.get(key) is not None:
                lines.append(f"- {key}：`{item[key]}`")
        if item.get("preview"):
            lines.append("")
            lines.append("响应片段：")
            lines.append("")
            lines.append("```")
            lines.append(str(item["preview"]))
            lines.append("```")
        lines.append("")
    lines.append("## 测试用图")
    lines.append("")
    try:
        scene_rel = scene_path.relative_to(ROOT)
    except ValueError:
        scene_rel = scene_path
    try:
        gauge_rel = gauge_path.relative_to(ROOT)
    except ValueError:
        gauge_rel = gauge_path
    lines.append(f"- 场景图：`{scene_rel}`（合成图，仅验证机制，不代表识别效果）")
    lines.append(f"- 表计图：`{gauge_rel}`（合成图，读数应为 0.85 MPa）")
    lines.append("")
    lines.append("## 待办")
    lines.append("")
    lines.append("1. 用**真实现场图**替换合成图重跑本探针，记录真实时延与 token。")
    lines.append("2. 把通过的模型 id 回填 `config/models.yaml` 的 `roles.*.verified: true`。")
    lines.append("3. 建立 150~300 张图级标注集，跑 `scripts/eval.py`（D7 实现）得到分类 P/R。")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- 入口


def main() -> int:
    args = sys.argv[1:]
    custom_image: Path | None = None
    if "--image" in args:
        idx = args.index("--image")
        if idx + 1 < len(args):
            custom_image = Path(args[idx + 1]).expanduser().resolve()

    settings = get_settings()
    print(f"网关：{settings.maas_base_url}")
    print(f"密钥：{settings.masked_key}  网络模式：{settings.network_mode.value}")

    if not settings.has_key:
        print("❌ 未配置 MAAS_API_KEY，请复制 .env.example 为 .env 并填入密钥。")
        return 2

    client = MaasClient(
        api_key=settings.require_key(),
        base_url=settings.maas_base_url,
        timeout_s=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )

    results: list[dict[str, Any]] = []
    models: list[str] | None = None
    vision_models: list[str] = []

    try:
        models = client.list_models()
        vision_models = [
            m for m in models if any(k in m.lower() for k in ("vl", "vision", "omni", "ocr"))
        ]
        _rec(
            results,
            "鉴权 & 模型清单",
            True,
            f"共 {len(models)} 个模型，视觉相关 {len(vision_models)} 个",
        )
    except MaasError as exc:
        _rec(results, "鉴权 & 模型清单", False, str(exc))

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if custom_image and custom_image.exists():
        scene_path = custom_image
        print(f"使用现场图：{scene_path}")
    else:
        scene_path = make_scene_image(PROBE_DIR / "scene_synthetic.jpg")
        print(f"未提供现场图，使用合成图：{scene_path}")
    gauge_path = make_gauge_image(PROBE_DIR / "gauge_synthetic.jpg")

    run_text(client, settings.maas_text_model, results)
    vision_out = run_vision(client, settings.maas_vision_model, scene_path, results)
    ocr_out = run_ocr(client, settings.maas_ocr_model, gauge_path, results)

    payload = {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": settings.maas_base_url,
        "models_count": len(models) if models else 0,
        "vision_models": vision_models,
        "results": results,
        "vision_output": vision_out,
        "ocr_output": ocr_out,
    }
    (PROBE_DIR / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        render_report(
            base_url=settings.maas_base_url,
            masked_key=settings.masked_key,
            network_mode=settings.network_mode.value,
            models=models,
            results=results,
            vision_models=vision_models,
            scene_path=scene_path,
            gauge_path=gauge_path,
        ),
        encoding="utf-8",
    )

    print(f"\n报告已写入：{REPORT_PATH.relative_to(ROOT)}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())




