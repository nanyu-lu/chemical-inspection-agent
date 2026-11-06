"""提示词构建（版本化）。

原则：**提示词与规则表同源**。检查项、判据都从 `config/hazard_taxonomy.yaml` 读，
禁止在代码里另写一份判据，否则改配置不生效、评审时说清"依据哪一版"。

提示词踩坑记录（来自 D1 探针）：
- 示例里出现 0.0 / 1.0 这类极端值，模型会照抄 → 一律用 0.82 这类中间值并显式声明
- bbox 必须声明为 0~1000 相对坐标，否则会按像素返回并越界
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROMPT_VERSION = "v1"
DEFAULT_TAXONOMY_PATH = Path("config/hazard_taxonomy.yaml")

_JSON_SHAPE = (
    '{"detections":[{"hazard_type":"HZ-01","present":false,"confidence":0.82,'
    '"bbox":[120,340,220,420],"evidence":""}],"other_observations":""}'
)


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "categories" not in data:
        raise ValueError(f"{path} 不是合法的隐患类别表")
    return data


def mvp_categories(taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in taxonomy["categories"] if c.get("in_mvp")]


def vl_categories(taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    """MVP 中交给视觉模型判定的类别（读表类走 OCR，不混在同一次调用里）。"""
    return [c for c in mvp_categories(taxonomy) if c.get("judged_by") != "ocr"]



def build_judge_prompt(
    categories: list[dict[str, Any]],
    point: dict[str, Any] | None = None,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """构建隐患判定提示词。

    Args:
        categories: 来自 taxonomy 的检查项（含 draft_criteria）
        point: 点位上下文（name / facilities / focus），缺省时退化为通用判定
    """
    lines: list[str] = [
        "你是化工仓库（甲类危化品仓库）安全检查助手，只依据图像判断，不得臆测。",
        "",
    ]

    if point:
        lines.append("# 当前巡检点位")
        lines.append(f"- 点位：{point.get('id', '')} {point.get('name', '')}".strip())
        if point.get("zone"):
            lines.append(f"- 区域：{point['zone']}")
        if point.get("location_hint"):
            lines.append(f"- 位置：{point['location_hint']}")
        if point.get("facilities"):
            lines.append(f"- 该点位应有设施：{'；'.join(point['facilities'])}")
        lines.append(
            "- 点位信息用于判断「应有而未到位」：例如该有的灭火器被遮挡或缺失，属于隐患。"
        )
        lines.append("")

    lines.append("# 检查项（每个检查项都必须输出一条结果）")
    for idx, cat in enumerate(categories, start=1):
        lines.append(f"{idx}. {cat['id']} {cat['name']}")
        for crit in cat.get("draft_criteria") or []:
            lines.append(f"   - 判据：{crit}")
        if cat.get("confusing_cases"):
            lines.append(f"   - 易混淆：{'；'.join(cat['confusing_cases'])}")
    lines.append("")

    lines.append("# 判定纪律")
    lines.append("- 看不清、距离远、被遮挡、画面中不存在该对象 → present=false，并在 evidence 说明原因，不要猜。")
    lines.append("- confidence 取 0~1 的真实把握。示例里的 0.82 只是格式示范，禁止照抄。")
    lines.append("- bbox 使用 **0~1000 的相对坐标**（左上角 [0,0]，右下角 [1000,1000]），不是像素；无法给出时为 null。")
    lines.append("- 未列入上述检查项的异常写入 other_observations，不计为隐患。")
    lines.append("")
    lines.append(f"# 输出格式（严格 JSON，不要 markdown、不要解释）\n{_JSON_SHAPE}")
    return "\n".join(lines)


ELEMENT_PROMPT_VERSION = "e1"

_ELEMENT_SHAPE = (
    '{"scene":"库房通道，地面有托盘","elements":['
    '{"name":"手提式灭火器","category":"消防器材","bbox":[620,410,670,540],'
    '"state":"被纸箱部分遮挡","confidence":0.86}],"notes":""}'
)


def build_element_prompt(prompt_version: str = ELEMENT_PROMPT_VERSION) -> str:
    """「只看不判」的元素描述提示词（T1 测评用）。

    与 ``build_judge_prompt`` 的本质区别：**不允许输出任何隐患结论**，
    只描述画面中的元素与状态。这样测出来的才是"识别能力"本身。
    """
    lines = [
        "你是化工仓库安全巡检的视觉观察员。**只描述，不下结论。**",
        "",
        "# 任务",
        "把画面里与安全相关的元素尽量列全，不要判断是否存在隐患。",
        "",
        "# 元素类别（尽量归到这几类）",
        (
            "人员 / 设备（罐·泵·阀门·法兰·管道）/ 通道与门 / 消防器材 / 标识与指示灯 / "
            "环境异常（积液·烟雾·堆放物·破损）"
        ),
        "",
        "# 每个元素要给出",
        "- name：具体名称（如「纸箱堆」「手提式灭火器」「应急出口门」）",
        "- category：上面六类之一",
        "- bbox：0~1000 相对坐标 [x1,y1,x2,y2]，认不出给 null",
        "- state：状态（如「被纸箱部分遮挡」「正常摆放」「门前堆物」）",
        "- confidence：0~1 的真实把握",
        "",
        "# 纪律",
        "- 只写确实看到的；不确定的写进 notes，不要编。",
        "- 禁止输出「存在隐患」「违反规定」「不合格」这类结论。",
        "",
        f"# 输出（严格 JSON，不要 markdown）\n{_ELEMENT_SHAPE}",
    ]
    return "\n".join(lines)


__all__ = [
    "DEFAULT_TAXONOMY_PATH",
    "ELEMENT_PROMPT_VERSION",
    "PROMPT_VERSION",
    "build_element_prompt",
    "build_judge_prompt",
    "load_taxonomy",
    "mvp_categories",
    "vl_categories",
]
