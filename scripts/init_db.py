#!/usr/bin/env python3
"""初始化数据库（MVP 版的"迁移"策略：**先备份，再建表**）。

为什么不直接上 Alembic：MVP 阶段表结构还在动，Alembic 的成本（写迁移脚本、
每次改表都要生成 revision）大于收益。这里的约定是：
    改表结构 → 先跑本脚本备份 → 再启动（会自动 create_all 补齐新表）

真正上生产（内网）前必须换成 Alembic，已记入 docs/MVP开发计划.md。

用法：
    python scripts/init_db.py
    python scripts/init_db.py --no-backup
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chem_inspect.db import init_db
from chem_inspect.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    db_path = settings.data_dir / "app.db"

    if db_path.exists() and not args.no_backup:
        backup_dir = settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"app-{time.strftime('%Y%m%d-%H%M%S')}.db"
        shutil.copy2(db_path, target)
        print(f"已备份旧库 → {target}")

    session = init_db(db_path)
    session.close()
    print(f"数据库就绪：{db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
