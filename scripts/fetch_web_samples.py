"""从 Wikimedia Commons 采集 45 项的负样本/缺失样本（许可证可追溯）。

原则：
- 只下载 CC0 / Public domain / CC BY；CC BY-SA 默认跳过（避免 ShareAlike 传染）。
- 每张图记录来源、作者、许可证、URL、sha1，写入 ``data/datasets/web/LICENSES.csv``。
- 图片按 ``data/datasets/web/{negative|missing}/<CI-xx>_<名称>/`` 存放。
- 只做「参考/预训练/冒烟测试」，不替代现场同分布负样本。

用法：
    .venv/bin/python scripts/fetch_web_samples.py --per-query 6
    .venv/bin/python scripts/fetch_web_samples.py --items CI-06,CI-11 --per-query 8
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "data" / "datasets" / "web"
LICENSES = OUT_ROOT / "LICENSES.csv"
COVERAGE = ROOT / "data" / "eval" / "web_coverage.csv"
SKIPPED = OUT_ROOT / "SKIPPED.csv"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia 要求可识别的 UA + 联系方式，否则会 403。
USER_AGENT = (
    "ChemInspectDatasetCollector/0.1 "
    "(https://github.com/nanyu-lu/chemical-inspection-agent) httpx"
)

# 45 项 -> Commons 检索词。usage:
#   negative = 该项已有现场正样本，网图用来补“正常/参考”
#   missing  = 该项还没有现场图，网图只做“代表性参考/冒烟测试”
ITEM_QUERIES: dict[str, dict[str, object]] = {
    "CI-01": {"name": "安全阀", "usage": "negative", "queries": ["safety relief valve", "pressure relief valve"]},
    "CI-02": {"name": "爆破片", "usage": "missing", "queries": ["rupture disc", "bursting disc"]},
    "CI-03": {"name": "安全阀与爆破片安全", "usage": "missing", "queries": ["rupture disc", "safety valve"]},
    "CI-04": {"name": "泄压人孔", "usage": "missing", "queries": ["manhole cover", "pressure vessel manhole"]},
    "CI-05": {"name": "呼吸阀", "usage": "negative", "queries": ["pressure vacuum relief valve", "breather valve"]},
    "CI-06": {"name": "法兰", "usage": "negative", "queries": ["pipe flange", "flange bolts"]},
    "CI-07": {"name": "工业管道", "usage": "negative", "queries": ["industrial pipeline", "process pipe"]},
    "CI-08": {"name": "管道支承件", "usage": "negative", "queries": ["pipe support", "pipe hanger"]},
    "CI-09": {"name": "阻火器", "usage": "missing", "queries": ["flame arrester"]},
    "CI-10": {"name": "静电接地", "usage": "negative", "queries": ["grounding cable", "static grounding"]},
    "CI-11": {"name": "防爆电气设备", "usage": "negative", "queries": ["explosion proof junction box", "explosion proof enclosure", "cable gland"]},
    "CI-12": {"name": "UPS和蓄电池", "usage": "missing", "queries": ["battery room", "UPS battery"]},
    "CI-13": {"name": "围堰防火堤", "usage": "missing", "queries": ["containment bund", "oil containment", "fire dike"]},
    "CI-14": {"name": "固定式气体报警器", "usage": "missing", "queries": ["gas detector", "gas alarm"]},
    "CI-15": {"name": "紧急切断阀", "usage": "missing", "queries": ["emergency shutoff valve", "shut-off valve"]},
    "CI-16": {"name": "磁翻板液位计", "usage": "missing", "queries": ["magnetic level indicator", "level gauge"]},
    "CI-17": {"name": "压力表", "usage": "negative", "queries": ["pressure gauge", "manometer"]},
    "CI-18": {"name": "热电偶", "usage": "missing", "queries": ["thermocouple"]},
    "CI-19": {"name": "装卸作业", "usage": "missing", "queries": ["tank truck loading", "loading arm"]},
    "CI-20": {"name": "化学品存储", "usage": "missing", "queries": ["chemical storage", "chemical drums"]},
    "CI-21": {"name": "视镜", "usage": "missing", "queries": ["sight glass"]},
    "CI-22": {"name": "高压水清洗", "usage": "missing", "queries": ["high pressure water jetting"]},
    "CI-23": {"name": "反应釜", "usage": "missing", "queries": ["chemical reactor", "stirred tank reactor"]},
    "CI-24": {"name": "配电箱柜", "usage": "missing", "queries": ["distribution board", "electrical cabinet"]},
    "CI-25": {"name": "配电室", "usage": "missing", "queries": ["electrical room", "switchgear room"]},
    "CI-26": {"name": "电缆布设", "usage": "negative", "queries": ["cable tray", "cable duct"]},
    "CI-27": {"name": "电动工具", "usage": "missing", "queries": ["power tool", "angle grinder"]},
    "CI-28": {"name": "油浸式变压器", "usage": "missing", "queries": ["power transformer", "transformer substation"]},
    "CI-29": {"name": "机械设备", "usage": "missing", "queries": ["industrial machinery", "machine guard"]},
    "CI-30": {"name": "化学品存放", "usage": "missing", "queries": ["chemical drum storage", "IBC container"]},
    "CI-31": {"name": "作业环境与安全防护", "usage": "missing", "queries": ["industrial guardrail", "guard rail"]},
    "CI-32": {"name": "动火作业", "usage": "missing", "queries": ["welding sparks", "hot work"]},
    "CI-33": {"name": "高处作业", "usage": "missing", "queries": ["safety harness", "fall protection"]},
    "CI-34": {"name": "吊装作业", "usage": "missing", "queries": ["crane lifting", "crane hook"]},
    "CI-35": {"name": "脚手架作业", "usage": "missing", "queries": ["scaffolding"]},
    "CI-36": {"name": "钢结构安装", "usage": "missing", "queries": ["steel structure construction"]},
    "CI-37": {"name": "电焊机", "usage": "missing", "queries": ["welding machine"]},
    "CI-38": {"name": "气瓶", "usage": "missing", "queries": ["gas cylinder", "LPG cylinder"]},
    "CI-39": {"name": "施工电梯", "usage": "missing", "queries": ["construction elevator", "construction hoist"]},
    "CI-40": {"name": "吊篮", "usage": "missing", "queries": ["suspended platform", "gondola"]},
    "CI-41": {"name": "挖机", "usage": "missing", "queries": ["excavator"]},
    "CI-42": {"name": "登高车", "usage": "missing", "queries": ["aerial work platform", "boom lift"]},
    "CI-43": {"name": "应急消防设施", "usage": "missing", "queries": ["fire extinguisher", "fire hydrant"]},
    "CI-44": {"name": "叉车", "usage": "missing", "queries": ["forklift"]},
    "CI-45": {"name": "堆垛", "usage": "missing", "queries": ["pallet stack", "pallet racking"]},
}

# 允许的许可证（大小写不敏感）。CC BY-SA 默认不进主目录。
ALLOW_LICENSES = (
    "cc0",
    "public domain",
    "pd-",
    "cc by 2.0",
    "cc by 2.5",
    "cc by 3.0",
    "cc by 4.0",
)
SHARE_ALIKE_MARKERS = ("cc by-sa", "cc-by-sa", "cc by sa")

# 非照片/示意图/带文字的海报，直接跳过
SKIP_TITLE_WORDS = (
    "logo",
    "icon",
    "diagram",
    "schematic",
    "drawing",
    "blueprint",
    "map",
    "chart",
    "graph",
    "symbol",
    "sign",
    "poster",
    "cover",
    "stamp",
    "coin",
    "banknote",
    "book",
    "patent",
    "animation",
    "cartoon",
    "clipart",
    "svg",
    "plan",
    "scheme",
    "infographic",
    "waveguide",
    "thyristor",
    "psf",
    "nara",
    "clamp",
    "illustration",
    "engraving",
    "painting",
    "museum",
    "space station",
    "satellite",
    "stamp",
    "postcard",
    "bicycle",
    "chain",
    "bellows",
    "automotive",
    "car ",
    "engine",
    "artillery",
    "ammunition",
    "weapon",
    "toy",
    "model",
)

LICENSE_FIELDS = [
    "item_code",
    "item_name",
    "usage",
    "source",
    "title",
    "url",
    "author",
    "license",
    "license_url",
    "width",
    "height",
    "sha1",
    "downloaded_at",
    "query",
    "notes",
    "local_path",
    "status",
]


def clean_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def slugify(text: str, limit: int = 80) -> str:
    text = clean_html(text)
    text = re.sub(r"[^\w\-\.]+", "_", text, flags=re.UNICODE)
    text = text.strip("._")
    return (text or "image")[:limit]


def license_class(short_name: str) -> str:
    low = short_name.lower()
    if any(marker in low for marker in SHARE_ALIKE_MARKERS):
        return "share_alike"
    if any(allowed in low for allowed in ALLOW_LICENSES):
        return "permissive"
    return "other"


def should_skip_title(title: str) -> bool:
    low = title.lower()
    return any(word in low for word in SKIP_TITLE_WORDS)


def matches_query(title: str, query: str) -> bool:
    """标题至少命中一个检索词，避免“pipe flange”搜到螺栓夹具。"""
    tokens = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", query)]
    if not tokens:
        return True
    low = title.lower()
    return any(token in low for token in tokens)


def ensure_dirs() -> None:
    for path in (
        OUT_ROOT,
        OUT_ROOT / "negative",
        OUT_ROOT / "missing",
        OUT_ROOT / "share_alike",
    ):
        if not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)


def load_existing_sha1() -> set[str]:
    seen: set[str] = set()
    if not LICENSES.exists():
        return seen
    with LICENSES.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("sha1"):
                seen.add(row["sha1"])
    return seen


def append_license(row: dict[str, object]) -> None:
    is_new = not LICENSES.exists()
    with LICENSES.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LICENSE_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def append_skipped(row: dict[str, object]) -> None:
    fields = ["item_code", "title", "license", "url", "reason", "query"]
    is_new = not SKIPPED.exists()
    with SKIPPED.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fields})


def search_commons(client: httpx.Client, query: str, limit: int) -> list[dict]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": "1280",  # 用 1280 缩略图，避免下载几十 MB 原图
        "format": "json",
        "formatversion": "2",
    }
    resp = client.get(COMMONS_API, params=params, timeout=40)
    resp.raise_for_status()
    return resp.json().get("query", {}).get("pages", [])


def download_one(
    client: httpx.Client,
    page: dict,
    *,
    item_code: str,
    item_name: str,
    usage: str,
    query: str,
    seen_sha1: set[str],
    max_bytes: int,
    include_sharealike: bool,
    allow_png: bool,
) -> bool:
    title = page.get("title", "")
    info = (page.get("imageinfo") or [{}])[0]
    mime = (info.get("mime") or "").lower()
    original_url = info.get("url") or ""
    url = info.get("thumburl") or original_url

    if mime not in ("image/jpeg", "image/png"):
        append_skipped({"item_code": item_code, "title": title, "url": url, "reason": f"mime={mime}", "query": query})
        return False
    if mime == "image/png" and not allow_png:
        append_skipped({"item_code": item_code, "title": title, "url": url, "reason": "PNG 默认跳过（多为示意图）", "query": query})
        return False
    if not url or should_skip_title(title) or not matches_query(title, query):
        append_skipped({"item_code": item_code, "title": title, "url": url, "reason": "title/url/检索词过滤", "query": query})
        return False

    meta = info.get("extmetadata") or {}
    lic = clean_html((meta.get("LicenseShortName") or {}).get("value", ""))
    lic_url = clean_html((meta.get("LicenseUrl") or {}).get("value", ""))
    author = clean_html((meta.get("Artist") or {}).get("value", ""))
    lclass = license_class(lic)

    if lclass == "share_alike" and not include_sharealike:
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": "CC BY-SA 默认跳过", "query": query})
        return False
    if lclass == "other":
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": "许可证不在白名单", "query": query})
        return False

    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if width < 600 or height < 400:
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": f"尺寸过小 {width}x{height}", "query": query})
        return False

    try:
        resp = client.get(url, timeout=90)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": f"下载失败 {exc}", "query": query})
        return False

    data = resp.content
    if len(data) > max_bytes:
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": f"文件过大 {len(data)}", "query": query})
        return False

    sha1 = hashlib.sha1(data).hexdigest()
    if sha1 in seen_sha1:
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": "sha1 重复", "query": query})
        return False

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            fmt = (im.format or "").lower()
    except Exception as exc:  # noqa: BLE001
        append_skipped({"item_code": item_code, "title": title, "license": lic, "url": url, "reason": f"坏图 {exc}", "query": query})
        return False

    ext = ".png" if fmt == "png" else ".jpg"
    # CC BY-SA 单独隔离，避免和可交付的 permissive 数据混在一起
    usage_dir = "share_alike" if lclass == "share_alike" else usage
    folder = OUT_ROOT / usage_dir / f"{item_code}_{slugify(item_name, 30)}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{item_code}_{slugify(title, 70)}_{sha1[:8]}{ext}"
    target = folder / filename
    target.write_bytes(data)

    append_license(
        {
            "item_code": item_code,
            "item_name": item_name,
            "usage": usage,
            "source": "Wikimedia Commons",
            "title": title,
            "url": original_url,
            "author": author,
            "license": lic,
            "license_url": lic_url,
            "width": width,
            "height": height,
            "sha1": sha1,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "query": query,
            "notes": f"license_class={lclass}",
        }
    )
    seen_sha1.add(sha1)
    return True


def write_coverage() -> None:
    counts: dict[str, Counter] = defaultdict(Counter)
    if LICENSES.exists():
        with LICENSES.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("status") or "candidate") == "rejected":
                    continue
                key = row.get("item_code", "")
                counts[key]["downloaded"] += 1
                if "license_class=share_alike" in (row.get("notes") or ""):
                    counts[key]["share_alike"] += 1
                else:
                    counts[key]["permissive"] += 1

    COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item_code", "item_name", "usage", "downloaded", "permissive", "share_alike", "status"])
        for code, spec in ITEM_QUERIES.items():
            c = counts.get(code, Counter())
            downloaded = c["downloaded"]
            status = "ok" if downloaded >= 6 else ("partial" if downloaded else "none")
            writer.writerow([code, spec["name"], spec["usage"], downloaded, c["permissive"], c["share_alike"], status])
    print(f"覆盖表：{COVERAGE}")


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Wikimedia Commons 采集 45 项负样本/缺失样本")
    parser.add_argument("--items", default="", help="只跑指定项，逗号分隔，如 CI-06,CI-11")
    parser.add_argument("--per-query", type=int, default=6, help="每个检索词最多下载几张")
    parser.add_argument("--max-queries", type=int, default=0, help="每项最多跑几个检索词（0=全部）")
    parser.add_argument("--max-bytes", type=int, default=8_000_000, help="单张图片大小上限")
    parser.add_argument("--include-sharealike", action="store_true", help="是否下载 CC BY-SA（隔离到 share_alike/）")
    parser.add_argument("--allow-png", action="store_true", help="是否允许 PNG（默认只收 JPG）")
    parser.add_argument("--coverage-only", action="store_true", help="只重算覆盖表，不下载")
    parser.add_argument("--sleep", type=float, default=0.5, help="请求间隔秒数")
    args = parser.parse_args()

    ensure_dirs()
    if args.coverage_only:
        write_coverage()
        return 0
    selected = [s.strip() for s in args.items.split(",") if s.strip()] or list(ITEM_QUERIES)
    unknown = [s for s in selected if s not in ITEM_QUERIES]
    if unknown:
        print(f"未知项：{unknown}")
        return 2

    seen_sha1 = load_existing_sha1()
    total = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for code in selected:
            spec = ITEM_QUERIES[code]
            usage = str(spec["usage"])
            item_name = str(spec["name"])
            item_count = 0
            queries = list(spec["queries"])
            if args.max_queries:
                queries = queries[: args.max_queries]
            for query in queries:
                try:
                    pages = search_commons(client, str(query), limit=args.per_query * 3)
                except httpx.HTTPError as exc:
                    print(f"{code} 搜索失败 {query!r}: {exc}")
                    continue
                saved = 0
                for page in pages:
                    if saved >= args.per_query:
                        break
                    if download_one(
                        client,
                        page,
                        item_code=code,
                        item_name=item_name,
                        usage=usage,
                        query=str(query),
                        seen_sha1=seen_sha1,
                        max_bytes=args.max_bytes,
                        include_sharealike=args.include_sharealike,
                        allow_png=args.allow_png,
                    ):
                        saved += 1
                        item_count += 1
                        total += 1
                print(f"{code} {item_name} / {query}: +{saved}")
                time.sleep(args.sleep)
            print(f"== {code} {item_name}: 累计 {item_count} 张")

    print(f"完成：本次新增 {total} 张，累计 {len(seen_sha1)} 张唯一图")
    write_coverage()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
