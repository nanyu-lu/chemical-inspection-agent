#!/usr/bin/env python3
"""把目录打成 zip（保留 Unix 可执行位，支持中文文件名）。

Windows 评委用 zip 最省事（资源管理器直接解压），macOS 走 tar.gz 保留 +x。
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("用法: pack_zip.py <源目录> <输出.zip>")
        return 2
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    if not src.is_dir():
        print(f"❌ 源目录不存在：{src}")
        return 2

    out.parent.mkdir(parents=True, exist_ok=True)
    root = src.name
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(src.rglob("*")):
            arc = f"{root}/{path.relative_to(src).as_posix()}"
            if path.is_dir():
                info = zipfile.ZipInfo(arc + "/")
                info.external_attr = (0o40755 & 0xFFFF) << 16
                zf.writestr(info, b"")
                continue
            zf.write(path, arc)
            count += 1

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"zip: {out.name} — {count} 个文件, {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
