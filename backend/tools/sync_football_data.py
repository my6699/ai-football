"""football-data.co.uk 历史数据回填 CLI。

用法（在 backend/ 目录下）::

    python tools/sync_football_data.py                 # 用 DB 里已启用联赛的全部赛季
    python tools/sync_football_data.py --seasons 2024 2025
    python tools/sync_football_data.py --dry-run       # 只解析不写库
    python tools/sync_football_data.py --seasons 2025 --dry-run

免费、无需 API key，用于替代 API-Football 的历史回填，节省其 100 次/天的配额。
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
from app.services.football_data_service import (  # noqa: E402
    LEAGUE_CODE_MAP,
    sync_football_data,
)

setup_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description="从 football-data.co.uk 回填历史比赛与统计")
    parser.add_argument(
        "--seasons", nargs="*", type=int, default=None,
        help="赛季年份列表，如 2024 2025；缺省用 DB 中已启用联赛的全部赛季",
    )
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    print("支持的联赛码映射 (API-Football league_id -> football-data.co.uk code):")
    for lid, code in LEAGUE_CODE_MAP.items():
        print(f"  {lid} -> {code}")
    print()

    db = SessionLocal()
    try:
        result = sync_football_data(db, seasons=args.seasons, dry_run=args.dry_run)
    finally:
        db.close()

    print()
    print("=== 结果 ===")
    print(json.dumps(
        {k: v for k, v in result.items() if k != "unresolved"},
        ensure_ascii=False, indent=2,
    ))
    unresolved = result.get("unresolved") or []
    if unresolved:
        print(f"\n未解析队名 {len(unresolved)} 个（请补进 app/data/team_aliases.json）:")
        for name in unresolved:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
