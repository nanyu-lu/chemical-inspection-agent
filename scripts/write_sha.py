#!/usr/bin/env python3
"""为 dist/ 下某个前缀的产物生成 SHA256SUMS。"""

from __future__ import annotations

import hashlib
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: write_sha.py <产物名前缀>")
        return 2
    prefix = sys.argv[1]
    dist = pathlib.Path("dist")
    targets = sorted(p for p in dist.glob(f"{prefix}.*") if p.is_file())
    if not targets:
        print(f"❌ 未找到 dist/{prefix}.*")
        return 1
    lines = []
    for p in targets:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {p.name}")
    (dist / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
