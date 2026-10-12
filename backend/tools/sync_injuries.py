"""API-Football 伤停数据同步 CLI。

用法（在 backend/ 目录下）::

    python tools/sync_injuries.py                       # 按已启用联赛的当前赛季拉取
    python tools/sync_injuries.py --date 2026-10-07     # 按日期拉取
    python tools/sync_injuries.py --fixtures 1234567 7654321   # 按比赛精确拉取

注意：每次调用都消耗 API-Football 配额（免费层 100 次/天）。
"""
import argparse
import json
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from app.core.log_config import setup_logger  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.injury_service import sync_injuries  # noqa: E402

setup_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 API-Football 伤停数据到 injuries 表")
    parser.add_argument("--fixtures", nargs="*", type=int, default=None,
                        help="指定比赛 ID 列表（精确拉取，最省配额）")
    parser.add_argument("--date", type=str, default=None,
                        help="指定日期 YYYY-MM-DD")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = sync_injuries(db, fixture_ids=args.fixtures, date_str=args.date)
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
